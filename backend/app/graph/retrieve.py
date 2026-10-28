import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from pgvector.sqlalchemy import Vector
from sqlalchemy import case, or_, select, type_coerce

from app import config
from app.graph.models import (
    Chunk,
    ChunkEmbedding,
    Entity,
    Evidence,
    Relation,
    Source,
)
from app.graph.text import collapse, normalize_name

STOP = set(
    "a an and are as at be by can did do does for from has have how in is it "
    "its of on or that the their there this to was were what when where which "
    "who whom why with about tell me explain give list".split()
)
MAX_SEEDS = 10
FALLBACK_CHUNKS = 5


@dataclass
class Passage:
    id: str
    chunk_id: int
    source_id: int
    source_title: str
    text: str


@dataclass
class Fact:
    id: str
    subject: str
    predicate: str
    object: str
    hop: int
    support: int


@dataclass
class Retrieval:
    seeds: list = field(default_factory=list)
    facts: list = field(default_factory=list)
    passages: list = field(default_factory=list)

    @property
    def empty(self):
        return not self.passages


def _tokens(question: str) -> list[str]:
    words = [w for w in re.findall(r"\w+", collapse(question))]
    return [w for w in words if w not in STOP]


def _ngrams(question: str) -> set[str]:
    words = re.findall(r"\w+", collapse(question))
    grams = set()
    for n in range(1, 5):
        for i in range(len(words) - n + 1):
            grams.add(normalize_name(" ".join(words[i : i + n])))
    return {g for g in grams if g and g not in STOP}


def _seeds(db, company_id, question) -> list[int]:
    exact = list(
        db.scalars(
            select(Entity.id)
            .where(
                Entity.company_id == company_id,
                Entity.normalized_name.in_(_ngrams(question)),
            )
            .limit(MAX_SEEDS)
        )
    )
    if len(exact) >= MAX_SEEDS:
        return exact
    # Weaker match: a long question word inside an entity name.
    words = [w for w in _tokens(question) if len(w) >= 4]
    if not words:
        return exact
    loose = db.scalars(
        select(Entity.id)
        .where(
            Entity.company_id == company_id,
            Entity.id.not_in(exact or [0]),
            or_(
                *[
                    Entity.normalized_name.contains(w, autoescape=True)
                    for w in words
                ]
            ),
        )
        .order_by(Entity.id)
        .limit(MAX_SEEDS - len(exact))
    )
    return exact + list(loose)


def _expand(db, company_id, seeds, hops):
    """Breadth-first over relations in both directions, with hard caps."""
    seen_nodes = set(seeds)
    frontier = set(seeds)
    edges = {}  # relation id -> (Relation, hop)
    per_node = defaultdict(int)
    for hop in range(1, hops + 1):
        if not frontier or len(edges) >= config.GRAPH_MAX_EDGES:
            break
        rows = db.scalars(
            select(Relation)
            .where(
                Relation.company_id == company_id,
                or_(
                    Relation.subject_id.in_(frontier),
                    Relation.object_id.in_(frontier),
                ),
            )
            .order_by(Relation.id)
            .limit(config.GRAPH_PER_NODE * len(frontier))
        ).all()
        nxt = set()
        for r in rows:
            if r.id in edges:
                continue
            ends = {r.subject_id, r.object_id}
            anchor = ends & frontier
            if any(per_node[n] >= config.GRAPH_PER_NODE for n in anchor):
                continue
            new = ends - seen_nodes
            if len(seen_nodes) + len(new) > config.GRAPH_MAX_NODES:
                continue
            if len(edges) >= config.GRAPH_MAX_EDGES:
                break
            edges[r.id] = (r, hop)
            for n in anchor:
                per_node[n] += 1
            seen_nodes |= new
            nxt |= new
        frontier = nxt
    return edges, seen_nodes


def _evidence(db, company_id, relation_ids, entity_ids):
    """Chunk ids per relation and entity, with source id and confidence."""
    rows = db.execute(
        select(
            Evidence.relation_id,
            Evidence.entity_id,
            Evidence.chunk_id,
            Evidence.confidence,
            Chunk.source_id,
        )
        .join(
            Chunk,
            (Chunk.id == Evidence.chunk_id)
            & (Chunk.company_id == Evidence.company_id),
        )
        .where(
            Evidence.company_id == company_id,
            or_(
                Evidence.relation_id.in_(relation_ids or [0]),
                Evidence.entity_id.in_(entity_ids or [0]),
            ),
        )
        .order_by(Evidence.id)
    ).all()
    by_rel, by_ent = defaultdict(list), defaultdict(list)
    for rel_id, ent_id, chunk_id, conf, source_id in rows:
        (by_rel if rel_id else by_ent)[rel_id or ent_id].append(
            (chunk_id, source_id, conf)
        )
    return by_rel, by_ent


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def vector_chunks(db, company_id, vec) -> list[int]:
    """Nearest chunks of this company above the similarity floor."""
    if not vec:
        return []
    if db.get_bind().dialect.name == "postgresql":
        # The column is a JSON variant for sqlite, so type it as a vector here.
        column = type_coerce(ChunkEmbedding.embedding, Vector(config.EMBED_DIM))
        dist = column.cosine_distance(vec)
        rows = db.execute(
            select(ChunkEmbedding.chunk_id, dist)
            .where(
                ChunkEmbedding.company_id == company_id,
                ChunkEmbedding.model == config.GEMINI_EMBED_MODEL,
            )
            .order_by(dist)
            .limit(config.VECTOR_TOP)
        ).all()
        return [c for c, d in rows if 1 - d >= config.VECTOR_MIN_SIM]
    # sqlite (tests): exact scan in Python over this company's rows
    scored = sorted(
        (
            (_cosine(vec, e.embedding), e.chunk_id)
            for e in db.scalars(
                select(ChunkEmbedding).where(
                    ChunkEmbedding.company_id == company_id,
                    ChunkEmbedding.model == config.GEMINI_EMBED_MODEL,
                )
            )
        ),
        reverse=True,
    )
    return [
        c for s, c in scored[: config.VECTOR_TOP] if s >= config.VECTOR_MIN_SIM
    ]


def fallback_chunks(db, company_id, question, query_vec=None) -> list[int]:
    """Keyword hits and nearest-vector hits, interleaved, keyword first."""
    keyword = _keyword_chunks(db, company_id, question)
    nearest = vector_chunks(db, company_id, query_vec)
    merged = [c for pair in zip(keyword, nearest) for c in pair]
    merged += keyword[len(nearest) :] + nearest[len(keyword) :]
    return list(dict.fromkeys(merged))


def _keyword_chunks(db, company_id, question) -> list[int]:
    words = [w for w in _tokens(question) if len(w) >= 3][:8]
    if not words:
        return []
    hits = [
        case((Chunk.text.icontains(w, autoescape=True), 1), else_=0)
        for w in words
    ]
    score = sum(hits[1:], hits[0])
    rows = db.execute(
        select(Chunk.id, score.label("s"))
        .where(Chunk.company_id == company_id)
        .order_by(score.desc(), Chunk.id)
        .limit(FALLBACK_CHUNKS)
    ).all()
    return [cid for cid, s in rows if s]


def retrieve(
    db, company_id: int, question: str, query_vec: list | None = None
) -> Retrieval:
    out = Retrieval()
    seeds = _seeds(db, company_id, question)
    out.seeds = seeds
    edges, nodes = _expand(db, company_id, seeds, config.GRAPH_HOPS)
    by_rel, by_ent = _evidence(db, company_id, list(edges), seeds)

    def support(rid):
        return len({s for _, s, _ in by_rel.get(rid, [])})

    def conf(rid):
        return max((c for _, _, c in by_rel.get(rid, [])), default=0)

    ranked = sorted(
        edges.values(),
        key=lambda rh: (rh[1], -support(rh[0].id), -conf(rh[0].id), rh[0].id),
    )
    names = {
        e.id: e.name
        for e in db.scalars(
            select(Entity).where(
                Entity.company_id == company_id, Entity.id.in_(nodes or [0])
            )
        )
    }
    chunk_order = []
    for i, (r, hop) in enumerate(ranked, 1):
        out.facts.append(
            Fact(
                f"F{i}",
                names.get(r.subject_id, "?"),
                r.predicate,
                names.get(r.object_id, "?"),
                hop,
                support(r.id),
            )
        )
        chunk_order += [c for c, _, _ in by_rel.get(r.id, [])]
    for seed in seeds:
        chunk_order += [c for c, _, _ in by_ent.get(seed, [])]
    if not chunk_order:
        chunk_order = fallback_chunks(db, company_id, question, query_vec)

    ordered = list(dict.fromkeys(chunk_order))
    rows = {
        c.id: (c, title)
        for c, title in db.execute(
            select(Chunk, Source.title)
            .join(
                Source,
                (Source.id == Chunk.source_id)
                & (Source.company_id == Chunk.company_id),
            )
            .where(Chunk.company_id == company_id, Chunk.id.in_(ordered or [0]))
        )
    }
    budget = config.CONTEXT_CHARS
    for cid in ordered:
        if cid not in rows:
            continue
        chunk, title = rows[cid]
        if budget - len(chunk.text) < 0 and out.passages:
            break
        budget -= len(chunk.text)
        out.passages.append(
            Passage(
                f"S{len(out.passages) + 1}",
                chunk.id,
                chunk.source_id,
                title,
                chunk.text,
            )
        )
    return out


_MARK = re.compile(r"\[([SF]\d+)\]")


def escape(text: str) -> str:
    """Stop document text from forging citation markers or tags."""
    text = _MARK.sub(r"(\1)", text)
    return text.replace("<context>", "").replace("</context>", "")


def build_context(r: Retrieval) -> str:
    parts = ["Facts:"]
    parts += [
        f"[{f.id}] {escape(f.subject)} -{escape(f.predicate)}-> "
        f"{escape(f.object)}"
        for f in r.facts
    ] or ["(none)"]
    parts.append("\nPassages:")
    parts += [
        f'[{p.id}] (from "{escape(p.source_title)}") {escape(p.text)}'
        for p in r.passages
    ]
    return "<context>\n" + "\n".join(parts) + "\n</context>"
