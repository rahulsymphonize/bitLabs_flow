from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app import config
from app.db import Base

ENTITY_TYPES = (
    "person",
    "organization",
    "location",
    "product",
    "event",
    "concept",
    "other",
)


def _now():
    return datetime.now(timezone.utc)


def _company():
    return mapped_column(ForeignKey("companies.id"), index=True)


class Source(Base):
    __tablename__ = "graph_sources"
    __table_args__ = (
        UniqueConstraint("company_id", "id"),
        UniqueConstraint("company_id", "content_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = _company()
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20))
    content_hash: Mapped[str] = mapped_column(String(64))
    # processing | done | partial | failed
    status: Mapped[str] = mapped_column(String(20))
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now
    )


class Chunk(Base):
    __tablename__ = "graph_chunks"
    __table_args__ = (
        UniqueConstraint("company_id", "id"),
        ForeignKeyConstraint(
            ["company_id", "source_id"],
            ["graph_sources.company_id", "graph_sources.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = _company()
    source_id: Mapped[int] = mapped_column(index=True)
    ordinal: Mapped[int]
    text: Mapped[str] = mapped_column(Text)


class Entity(Base):
    __tablename__ = "graph_entities"
    __table_args__ = (
        UniqueConstraint("company_id", "id"),
        UniqueConstraint("company_id", "normalized_name", "type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = _company()
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    type: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(500), default="")


class Relation(Base):
    __tablename__ = "graph_relations"
    __table_args__ = (
        UniqueConstraint("company_id", "id"),
        UniqueConstraint("company_id", "subject_id", "predicate", "object_id"),
        ForeignKeyConstraint(
            ["company_id", "subject_id"],
            ["graph_entities.company_id", "graph_entities.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "object_id"],
            ["graph_entities.company_id", "graph_entities.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = _company()
    subject_id: Mapped[int] = mapped_column(index=True)
    predicate: Mapped[str] = mapped_column(String(80))
    object_id: Mapped[int] = mapped_column(index=True)


class Evidence(Base):
    """Provenance: which chunk supports which entity or relation."""

    __tablename__ = "graph_evidence"
    __table_args__ = (
        CheckConstraint(
            "(entity_id IS NULL) <> (relation_id IS NULL)",
            name="ck_evidence_one_target",
        ),
        UniqueConstraint("chunk_id", "entity_id"),
        UniqueConstraint("chunk_id", "relation_id"),
        ForeignKeyConstraint(
            ["company_id", "chunk_id"],
            ["graph_chunks.company_id", "graph_chunks.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "entity_id"],
            ["graph_entities.company_id", "graph_entities.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "relation_id"],
            ["graph_relations.company_id", "graph_relations.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = _company()
    chunk_id: Mapped[int] = mapped_column(index=True)
    entity_id: Mapped[int | None] = mapped_column(index=True)
    relation_id: Mapped[int | None] = mapped_column(index=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class ChunkEmbedding(Base):
    __tablename__ = "graph_chunk_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "chunk_id"],
            ["graph_chunks.company_id", "graph_chunks.id"],
            ondelete="CASCADE",
        ),
    )

    chunk_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = _company()
    model: Mapped[str] = mapped_column(String(80))
    # Real vector on Postgres, a JSON list on sqlite (tests).
    embedding: Mapped[list] = mapped_column(
        JSON().with_variant(Vector(config.EMBED_DIM), "postgresql")
    )
