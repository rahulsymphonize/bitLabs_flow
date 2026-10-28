import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import config
from app.graph.chunking import chunk_text
from app.graph.errors import GraphError, SourceUnreadable
from app.graph.extract import extract_chunks
from app.graph.models import Source
from app.graph.parsing import parse
from app.graph.store import apply_extraction

STALE = timedelta(minutes=10)


def _fresh(source: Source) -> bool:
    updated = source.updated_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - updated < STALE


def _report(results, failures):
    rejects, ents, rels = {}, 0, 0
    for res in results:
        if res.valid:
            ents += len(res.valid.entities)
            rels += len(res.valid.relations)
            for k, n in res.valid.rejects.items():
                rejects[k] = rejects.get(k, 0) + n
    return {
        "chunks": len(results),
        "failed_chunks": sum(1 for r in results if r.valid is None),
        "entities": ents,
        "relations": rels,
        "rejected": rejects,
        "errors": dict(failures),
    }


def ingest(db, llm, company_id, title, filename, data, source=None):
    """Parse, extract and store one source. Returns (source, applied).

    The LLM runs with no database transaction open. A source that was fully
    ingested is replaced only by another fully successful run.
    """
    kind, text = parse(filename, data)
    chunks = chunk_text(text, config.CHUNK_CHARS)
    if len(chunks) > config.MAX_CHUNKS:
        raise SourceUnreadable("File is too large")
    digest = hashlib.sha256(text.encode()).hexdigest()

    clash = db.scalar(
        select(Source).where(
            Source.company_id == company_id,
            Source.content_hash == digest,
            Source.id != (source.id if source else 0),
        )
    )
    if source is None:
        if clash:
            if clash.status == "done":
                return clash, False
            if clash.status == "processing" and _fresh(clash):
                raise HTTPException(
                    409, "This file is already being processed."
                )
            source = clash
        else:
            source = Source(
                company_id=company_id,
                title=title[:300],
                kind=kind,
                content_hash=digest,
                status="processing",
            )
            db.add(source)
            try:
                db.flush()
            except IntegrityError:  # lost a race with the same upload
                db.rollback()
                raise HTTPException(
                    409, "This file is already being processed."
                )
    else:
        if clash:
            raise HTTPException(409, "Another source already has this content.")
        if source.content_hash == digest and source.status == "done":
            return source, False

    previous = source.status
    if previous == "processing":
        previous = "failed"  # a stale row from a crashed run
    source.status = "processing"
    source_id = source.id
    db.commit()

    results, failures = extract_chunks(llm, chunks)
    report = _report(results, failures)
    ok = report["failed_chunks"]
    status = "failed" if ok == len(results) else "partial" if ok else "done"
    report["status"] = status

    # Embeddings are a bonus: a failure here never fails the ingestion.
    try:
        vectors = llm.embed([r.text for r in results])
        if len(vectors) != len(results) or any(
            len(v) != config.EMBED_DIM for v in vectors
        ):
            raise GraphError("unexpected embedding size")
        for res, vec in zip(results, vectors):
            res.vector = vec
    except GraphError:
        report["embedding_failed"] = True

    source = db.get(Source, source_id)
    apply = status != "failed" and (status == "done" or previous != "done")
    if apply:
        source.title, source.kind, source.content_hash = (
            title[:300],
            kind,
            digest,
        )
        apply_extraction(db, company_id, source, results, status, report)
    else:
        source.status = previous
        source.report = {**(source.report or {}), "last_attempt": report}
    db.flush()
    return source, apply
