from sqlalchemy import func, select

from app import db as app_db
from app.graph.models import ChunkEmbedding
from app.graph.retrieve import fallback_chunks, vector_chunks
from tests.conftest import login
from tests.fakes import FakeLLM
from tests.test_graph_api import GRAPH, TEXT, set_llm, upload
from tests.test_graph_query import good, ingest, ask


def embeddings():
    with app_db.SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(ChunkEmbedding))


def test_embeddings_are_stored_per_chunk(client):
    ingest(client)
    assert embeddings() == 2


def test_embedding_outage_does_not_fail_ingestion(client):
    set_llm(client, FakeLLM(extract=GRAPH, fail_embed=True))
    r = upload(client, "user_a@x.com")
    assert r.status_code == 201 and r.json()["status"] == "done"
    assert r.json()["report"]["embedding_failed"] is True
    assert embeddings() == 0


def test_nearest_chunks_respect_floor_and_company(client):
    ingest(client)
    set_llm(client, FakeLLM(extract=GRAPH))
    upload(client, "user_b@x.com", b"Zed Inc owns Yarn Co.", "b.txt")
    vec = client.llm.embed(["Acme Corp acquired Beta Labs in 2020."])[0]
    with app_db.SessionLocal() as s:
        mine = vector_chunks(s, 1, vec)
        theirs = vector_chunks(s, 2, vec)
        assert len(mine) == 1  # the unrelated chunk is under the floor
        assert theirs == []
        assert vector_chunks(s, 1, None) == []


def test_hybrid_fallback_merges_keyword_and_vector(client):
    ingest(client)
    vec = client.llm.embed(["Jane Doe founded Acme Corp."])[0]
    with app_db.SessionLocal() as s:
        ids = fallback_chunks(s, 1, "founded", vec)
    assert len(ids) == len(set(ids)) >= 1


def test_query_survives_embedding_outage(client):
    ingest(client)
    set_llm(client, FakeLLM(answer=good, fail_embed=True))
    body = ask(client).json()
    assert body["grounded"]  # graph retrieval did not need the vector


def test_wrong_size_embeddings_count_as_an_embedding_failure(client):
    fake = FakeLLM(extract=GRAPH)
    fake.embed = lambda texts: [[1.0, 2.0] for _ in texts]
    set_llm(client, fake)
    r = upload(client, "user_a@x.com")
    assert r.status_code == 201 and r.json()["report"]["embedding_failed"]
    assert embeddings() == 0
