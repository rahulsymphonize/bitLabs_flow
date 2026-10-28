import time
from collections import defaultdict, deque

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from app import config
from app.audit import log_action
from app.db import get_db
from app.deps import graph_scope, require_permission
from app.graph import answer as answering
from app.graph import service, store
from app.graph.errors import GraphError, SourceUnreadable
from app.graph.llm import get_llm
from app.graph.models import Chunk, Entity, Evidence, Relation, Source
from app.graph.retrieve import retrieve

router = APIRouter(prefix="/graph", tags=["graph"])

can_read = require_permission("graph:read")
can_write = require_permission("graph:write")

_hits: dict[tuple, deque] = defaultdict(deque)
LLM_DOWN = "The language model is unavailable. Try again later."


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    title: str
    kind: str
    status: str
    report: dict


def _rate_limit(company_id: int, kind="write"):
    # ponytail: per-process counter, use a shared store with several workers
    now = time.monotonic()
    hits = _hits[(company_id, kind)]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= config.GRAPH_WRITES_PER_MIN:
        raise HTTPException(429, "Too many requests. Try again in a minute.")
    hits.append(now)


def _read(file: UploadFile | None, text: str | None, title: str | None):
    if file is not None:
        data = file.file.read(config.MAX_UPLOAD_BYTES + 1)
        return title or file.filename or "untitled", file.filename or "", data
    if text:
        name = title or "Pasted text"
        return name, "pasted.txt", text.encode()
    raise HTTPException(422, "Send a file or text")


def _finish(db, user, cid, action, source, applied):
    log_action(
        db,
        user,
        action,
        "source",
        source.id,
        company_id=cid,
        status=(source.report or {}).get("status", source.status),
        applied=applied,
    )
    db.commit()
    last = (source.report or {}).get("last_attempt", source.report or {})
    if last.get("status") == "failed":
        raise HTTPException(502, LLM_DOWN)
    return source


def _get_source(db, cid, source_id, lock=False):
    query = select(Source).where(
        Source.company_id == cid, Source.id == source_id
    )
    source = db.scalar(query.with_for_update() if lock else query)
    if not source:
        raise HTTPException(404, "Not found")
    return source


@router.post("/sources", response_model=SourceOut, status_code=201)
def create_source(
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    title: str | None = Form(None),
    company_id: int | None = Form(None),
    user=Depends(can_write),
    db=Depends(get_db),
    llm=Depends(get_llm),
):
    cid = graph_scope(user, company_id, db, write=True)
    _rate_limit(cid)
    name, filename, data = _read(file, text, title)
    try:
        source, applied = service.ingest(db, llm, cid, name, filename, data)
    except SourceUnreadable as e:
        log_action(
            db, user, "graph.source_ingest", company_id=cid, status="rejected"
        )
        db.commit()
        raise HTTPException(422, str(e))
    return _finish(db, user, cid, "graph.source_ingest", source, applied)


@router.put("/sources/{source_id}", response_model=SourceOut)
def update_source(
    source_id: int,
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    title: str | None = Form(None),
    company_id: int | None = Form(None),
    user=Depends(can_write),
    db=Depends(get_db),
    llm=Depends(get_llm),
):
    cid = graph_scope(user, company_id, db, write=True)
    _rate_limit(cid)
    source = _get_source(db, cid, source_id, lock=True)
    name, filename, data = _read(file, text, title or source.title)
    try:
        source, applied = service.ingest(
            db, llm, cid, name, filename, data, source=source
        )
    except SourceUnreadable as e:
        log_action(
            db,
            user,
            "graph.source_update",
            "source",
            source_id,
            company_id=cid,
            status="rejected",
        )
        db.commit()
        raise HTTPException(422, str(e))
    return _finish(db, user, cid, "graph.source_update", source, applied)


@router.get("/sources", response_model=list[SourceOut])
def list_sources(
    company_id: int | None = None, user=Depends(can_read), db=Depends(get_db)
):
    cid = graph_scope(user, company_id, db)
    return db.scalars(
        select(Source).where(Source.company_id == cid).order_by(Source.id)
    ).all()


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(
    source_id: int,
    company_id: int | None = None,
    user=Depends(can_write),
    db=Depends(get_db),
):
    cid = graph_scope(user, company_id, db, write=True)
    source = _get_source(db, cid, source_id, lock=True)
    store.delete_source(db, cid, source)
    log_action(
        db, user, "graph.source_delete", "source", source_id, company_id=cid
    )
    db.commit()


class QueryIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    company_id: int | None = None


@router.post("/query")
def query(
    body: QueryIn,
    user=Depends(can_read),
    db=Depends(get_db),
    llm=Depends(get_llm),
):
    cid = graph_scope(user, body.company_id, db)
    _rate_limit(cid, "query")
    try:
        query_vec = llm.embed([body.question])[0]
        if len(query_vec) != config.EMBED_DIM:
            query_vec = None
    except GraphError:
        query_vec = None  # keyword and graph retrieval still work
    found = retrieve(db, cid, body.question, query_vec)
    db.commit()  # no transaction is held while the model runs
    meta = {
        "question_chars": len(body.question),
        "facts": len(found.facts),
        "passages": len(found.passages),
    }
    try:
        result = answering.answer(llm, body.question, found)
    except GraphError as e:
        log_action(
            db,
            user,
            "graph.query",
            company_id=cid,
            status="error",
            error=type(e).__name__,
            **meta,
        )
        db.commit()
        raise
    log_action(
        db,
        user,
        "graph.query",
        company_id=cid,
        status="grounded" if result["grounded"] else "no_answer",
        **meta,
    )
    db.commit()
    return result


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    description: str


@router.get("/entities", response_model=list[EntityOut])
def list_entities(
    q: str | None = None,
    company_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(can_read),
    db=Depends(get_db),
):
    cid = graph_scope(user, company_id, db)
    query = select(Entity).where(Entity.company_id == cid)
    if q:
        query = query.where(
            Entity.normalized_name.contains(q.casefold(), autoescape=True)
        )
    return db.scalars(
        query.order_by(Entity.id).limit(limit).offset(offset)
    ).all()


@router.get("/entities/{entity_id}/neighbors")
def neighbors(
    entity_id: int,
    company_id: int | None = None,
    user=Depends(can_read),
    db=Depends(get_db),
):
    cid = graph_scope(user, company_id, db)
    entity = db.scalar(
        select(Entity).where(Entity.company_id == cid, Entity.id == entity_id)
    )
    if not entity:
        raise HTTPException(404, "Not found")
    rels = db.scalars(
        select(Relation)
        .where(
            Relation.company_id == cid,
            or_(
                Relation.subject_id == entity_id,
                Relation.object_id == entity_id,
            ),
        )
        .order_by(Relation.id)
        .limit(200)
    ).all()
    ids = {i for r in rels for i in (r.subject_id, r.object_id)}
    names = {
        e.id: e.name
        for e in db.scalars(
            select(Entity).where(
                Entity.company_id == cid, Entity.id.in_(ids or [0])
            )
        )
    }
    support = dict(
        db.execute(
            select(
                Evidence.relation_id, func.count(func.distinct(Chunk.source_id))
            )
            .join(
                Chunk,
                (Chunk.id == Evidence.chunk_id)
                & (Chunk.company_id == Evidence.company_id),
            )
            .where(
                Evidence.company_id == cid,
                Evidence.relation_id.in_([r.id for r in rels] or [0]),
            )
            .group_by(Evidence.relation_id)
        ).all()
    )
    return {
        "entity": EntityOut.model_validate(entity),
        "relations": [
            {
                "id": r.id,
                "direction": "out" if r.subject_id == entity_id else "in",
                "predicate": r.predicate,
                "other_id": r.object_id
                if r.subject_id == entity_id
                else r.subject_id,
                "other_name": names.get(
                    r.object_id if r.subject_id == entity_id else r.subject_id
                ),
                "support": support.get(r.id, 0),
            }
            for r in rels
        ],
    }
