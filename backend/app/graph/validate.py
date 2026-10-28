import re
from collections import Counter
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.graph.models import ENTITY_TYPES
from app.graph.schemas import ExtractedEntity, ExtractedRelation
from app.graph.text import collapse, normalize_name

MIN_QUOTE = 8
_PRED = re.compile(r"[^a-z0-9]+")


@dataclass
class Valid:
    # normalized_name -> (name, type, description)
    entities: dict = field(default_factory=dict)
    # (subject_norm, predicate, object_norm, quote, confidence)
    relations: list = field(default_factory=list)
    rejects: Counter = field(default_factory=Counter)


def normalize_predicate(predicate: str) -> str:
    return _PRED.sub("_", predicate.casefold()).strip("_")[:80]


def validate(raw: dict, chunk: str, min_confidence: float) -> Valid:
    """Quality gate between the LLM output and the graph."""
    out = Valid()
    text = collapse(chunk)
    entities, relations = raw.get("entities"), raw.get("relations")
    if not isinstance(entities, list):
        out.rejects["entities_not_a_list"] += entities is not None
        entities = []
    if not isinstance(relations, list):
        out.rejects["relations_not_a_list"] += relations is not None
        relations = []
    for item in entities:
        try:
            e = ExtractedEntity.model_validate(item)
        except (ValidationError, TypeError):
            out.rejects["entity_bad_schema"] += 1
            continue
        norm = normalize_name(e.name)
        if not norm or len(norm) > 200:
            out.rejects["entity_bad_name"] += 1
        elif norm not in text:
            out.rejects["entity_not_in_text"] += 1
        elif norm not in out.entities:
            kind = e.type.casefold()
            out.entities[norm] = (
                e.name.strip()[:200],
                kind if kind in ENTITY_TYPES else "other",
                e.description.strip()[:500],
            )
    for item in relations:
        try:
            r = ExtractedRelation.model_validate(item)
        except (ValidationError, TypeError):
            out.rejects["relation_bad_schema"] += 1
            continue
        subj, obj = normalize_name(r.subject), normalize_name(r.object)
        pred = normalize_predicate(r.predicate)
        quote = collapse(r.quote)
        if subj not in out.entities or obj not in out.entities:
            out.rejects["relation_unknown_endpoint"] += 1
        elif subj == obj:
            out.rejects["relation_self_loop"] += 1
        elif not pred:
            out.rejects["relation_bad_predicate"] += 1
        elif r.confidence < min_confidence:
            out.rejects["relation_low_confidence"] += 1
        elif len(quote) < MIN_QUOTE or quote not in text:
            out.rejects["relation_quote_not_verbatim"] += 1
        else:
            out.relations.append(
                (subj, pred, obj, r.quote.strip(), r.confidence)
            )
    return out
