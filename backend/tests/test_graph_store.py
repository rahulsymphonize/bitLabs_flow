import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import db as app_db
from app.graph.models import Chunk, Entity, Evidence, Relation, Source
from app.graph.store import ChunkResult, apply_extraction, delete_source
from app.graph.validate import Valid


def valid(ents, rels=()):
    v = Valid()
    for n in ents:
        v.entities[n] = (n.title(), "other", "")
    v.relations = [(s, p, o, f"{s} {p} {o} quote", 0.9) for s, p, o in rels]
    return v


@pytest.fixture()
def db(client):  # client fixture recreates the tables and companies 1 and 2
    with app_db.SessionLocal() as s:
        yield s


def new_source(db, company=1, title="doc", h="h1"):
    src = Source(
        company_id=company,
        title=title,
        kind="text",
        content_hash=h,
        status="processing",
    )
    db.add(src)
    db.flush()
    return src


def counts(db, company=1):
    q = lambda m: db.scalar(
        select(func.count()).select_from(m).where(m.company_id == company)
    )
    return q(Entity), q(Relation), q(Evidence), q(Chunk)


def ingest(db, src, chunks, company=1):
    results = [ChunkResult(i, f"chunk {i}", v) for i, v in enumerate(chunks)]
    apply_extraction(db, company, src, results, "done", {})
    db.commit()


def test_apply_builds_graph_with_evidence(db):
    src = new_source(db)
    ingest(db, src, [valid(["a", "b"], [("a", "knows", "b")])])
    assert counts(db) == (2, 1, 3, 1)
    assert src.status == "done"


def test_same_entity_in_two_chunks_is_one_node_with_two_evidence(db):
    src = new_source(db)
    ingest(db, src, [valid(["a", "b"]), valid(["a", "c"])])
    assert counts(db)[0] == 3
    a = db.scalar(select(Entity.id).where(Entity.normalized_name == "a"))
    n = db.scalar(
        select(func.count())
        .select_from(Evidence)
        .where(Evidence.entity_id == a)
    )
    assert n == 2


def test_type_drift_does_not_split_a_node(db):
    src = new_source(db)
    v1, v2 = valid(["a"]), valid(["a"])
    v2.entities["a"] = ("A", "person", "")
    ingest(db, src, [v1, v2])
    assert counts(db)[0] == 1


def test_update_keeps_shared_entity_ids_and_prunes_stale(db):
    src = new_source(db)
    ingest(
        db, src, [valid(["a", "b", "c"], [("a", "x", "b"), ("b", "y", "c")])]
    )
    a_id = db.scalar(select(Entity.id).where(Entity.normalized_name == "a"))
    ingest(db, src, [valid(["a", "b"], [("a", "x", "b")])])
    assert (
        db.scalar(select(Entity.id).where(Entity.normalized_name == "a"))
        == a_id
    )
    assert (
        db.scalar(select(Entity).where(Entity.normalized_name == "c")) is None
    )
    assert counts(db)[1] == 1  # b -y-> c is gone


def test_delete_prunes_only_what_the_source_alone_supported(db):
    s1, s2 = (
        new_source(db, title="one", h="h1"),
        new_source(db, title="two", h="h2"),
    )
    ingest(db, s1, [valid(["a", "b"], [("a", "x", "b")])])
    ingest(db, s2, [valid(["a", "c"], [("a", "z", "c")])])
    delete_source(db, 1, s1)
    db.commit()
    names = set(db.scalars(select(Entity.normalized_name)))
    assert names == {"a", "c"}  # a is still supported by s2
    assert counts(db)[1] == 1


def test_failed_chunk_is_stored_without_evidence(db):
    src = new_source(db)
    ingest(db, src, [None, valid(["a"])])
    assert counts(db) == (1, 0, 1, 2)


def test_same_relation_twice_in_a_chunk_is_one_evidence(db):
    src = new_source(db)
    ingest(db, src, [valid(["a", "b"], [("a", "x", "b"), ("a", "x", "b")])])
    assert counts(db)[1:3] == (1, 3)


def test_each_company_has_its_own_nodes(db):
    ingest(db, new_source(db, 1), [valid(["a"])], 1)
    ingest(db, new_source(db, 2), [valid(["a"])], 2)
    assert counts(db, 1)[0] == counts(db, 2)[0] == 1


def test_cross_company_reference_is_rejected_by_composite_fk(db):
    ingest(db, new_source(db, 1), [valid(["a"])], 1)
    chunk = db.scalar(select(Chunk).where(Chunk.company_id == 1))
    db.add(
        Evidence(
            company_id=2, chunk_id=chunk.id, entity_id=None, relation_id=None
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    ent = db.scalar(select(Entity).where(Entity.company_id == 1))
    db.add(Evidence(company_id=2, chunk_id=chunk.id, entity_id=ent.id))
    with pytest.raises(IntegrityError):
        db.flush()


def test_evidence_needs_exactly_one_target(db):
    ingest(db, new_source(db), [valid(["a"])])
    chunk = db.scalar(select(Chunk))
    db.add(Evidence(company_id=1, chunk_id=chunk.id))
    with pytest.raises(IntegrityError):
        db.flush()
