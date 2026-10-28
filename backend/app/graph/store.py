from dataclasses import dataclass

from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app import config
from app.graph.models import (
    Chunk,
    ChunkEmbedding,
    Entity,
    Evidence,
    Relation,
    Source,
)
from app.graph.validate import Valid


@dataclass
class ChunkResult:
    ordinal: int
    text: str
    valid: Valid | None  # None: extraction failed for this chunk
    vector: list | None = None


def _insert_ignore(db, model, **values):
    insert = (
        pg_insert
        if db.get_bind().dialect.name == "postgresql"
        else sqlite_insert
    )
    db.execute(insert(model).values(**values).on_conflict_do_nothing())


def _entity_id(db, company_id, norm, name, kind, description):
    # Resolve by name alone so a type label that drifts cannot split a node.
    found = db.scalar(
        select(Entity.id)
        .where(Entity.company_id == company_id, Entity.normalized_name == norm)
        .order_by(Entity.id)
    )
    if found:
        return found
    _insert_ignore(
        db,
        Entity,
        company_id=company_id,
        name=name,
        normalized_name=norm,
        type=kind,
        description=description,
    )
    return db.scalar(
        select(Entity.id)
        .where(Entity.company_id == company_id, Entity.normalized_name == norm)
        .order_by(Entity.id)
    )


def _relation_id(db, company_id, subject_id, predicate, object_id):
    _insert_ignore(
        db,
        Relation,
        company_id=company_id,
        subject_id=subject_id,
        predicate=predicate,
        object_id=object_id,
    )
    return db.scalar(
        select(Relation.id).where(
            Relation.company_id == company_id,
            Relation.subject_id == subject_id,
            Relation.predicate == predicate,
            Relation.object_id == object_id,
        )
    )


def prune(db, company_id):
    """Relations first, then entities nothing supports any more."""
    has_evidence = exists().where(Evidence.relation_id == Relation.id)
    db.execute(
        delete(Relation).where(Relation.company_id == company_id, ~has_evidence)
    )
    ent_evidence = exists().where(Evidence.entity_id == Entity.id)
    ent_in_relation = exists().where(
        (Relation.subject_id == Entity.id) | (Relation.object_id == Entity.id)
    )
    db.execute(
        delete(Entity).where(
            Entity.company_id == company_id, ~ent_evidence, ~ent_in_relation
        )
    )


def apply_extraction(db, company_id, source: Source, results, status, report):
    """The only writer of graph rows. The caller commits.

    New chunks and evidence go in before the old chunks go out, so entities
    shared between the old and new content keep their ids.
    """
    old_chunks = list(
        db.scalars(
            select(Chunk.id).where(
                Chunk.company_id == company_id, Chunk.source_id == source.id
            )
        )
    )
    for res in results:
        chunk = Chunk(
            company_id=company_id,
            source_id=source.id,
            ordinal=res.ordinal,
            text=res.text,
        )
        db.add(chunk)
        db.flush()
        if res.vector:
            db.add(
                ChunkEmbedding(
                    chunk_id=chunk.id,
                    company_id=company_id,
                    model=config.GEMINI_EMBED_MODEL,
                    embedding=res.vector,
                )
            )
        if not res.valid:
            continue
        ids = {}
        for norm, (name, kind, desc) in res.valid.entities.items():
            eid = _entity_id(db, company_id, norm, name, kind, desc)
            ids[norm] = eid
            db.add(
                Evidence(
                    company_id=company_id,
                    chunk_id=chunk.id,
                    entity_id=eid,
                    quote=name,
                )
            )
        seen = set()
        for subj, pred, obj, quote, conf in res.valid.relations:
            rid = _relation_id(db, company_id, ids[subj], pred, ids[obj])
            if rid in seen:
                continue
            seen.add(rid)
            db.add(
                Evidence(
                    company_id=company_id,
                    chunk_id=chunk.id,
                    relation_id=rid,
                    quote=quote,
                    confidence=conf,
                )
            )
        db.flush()
    if old_chunks:
        db.execute(delete(Chunk).where(Chunk.id.in_(old_chunks)))
    prune(db, company_id)
    source.status = status
    source.report = report
    db.flush()


def delete_source(db, company_id, source: Source):
    db.delete(source)
    db.flush()
    prune(db, company_id)
