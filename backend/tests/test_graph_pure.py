import json

import pytest

from app.graph.chunking import chunk_text
from app.graph.errors import SourceUnreadable
from app.graph.parsing import parse
from app.graph.text import normalize_name
from app.graph.validate import validate

CHUNK = "Acme Corp acquired Beta Labs in 2020.\nThe deal was led by Jane Doe."


def rel(**kw):
    base = {
        "subject": "Acme Corp",
        "predicate": "Acquired",
        "object": "Beta Labs",
        "quote": "Acme Corp acquired Beta Labs",
        "confidence": 0.9,
    }
    return {**base, **kw}


ENTS = [{"name": "Acme Corp", "type": "Organization"}, {"name": "Beta Labs"}]


def run(relations, entities=ENTS, chunk=CHUNK):
    return validate({"entities": entities, "relations": relations}, chunk, 0.5)


def test_normalize_name():
    assert normalize_name("  The  ACME, Corp. ") == "the acme, corp"


def test_chunker_packs_paragraphs_and_cuts_long_ones():
    text = "a" * 30 + "\n\n" + "b" * 30
    assert chunk_text(text, 100) == [text]
    assert chunk_text(text, 40) == ["a" * 30, "b" * 30]
    long = " ".join(["word"] * 200)
    parts = chunk_text(long, 100)
    assert len(parts) > 5 and all(len(p) <= 100 for p in parts)


def test_parse_text_csv_json_and_errors():
    assert parse("a.md", b"hello")[0] == "text"
    kind, text = parse("a.csv", b"name,role\nAnn,CEO\nBob,CTO\n")
    assert kind == "csv" and "name: Ann; role: CEO" in text
    rows = json.dumps([{"a": 1}, {"a": 2}]).encode()
    assert "a: 2" in parse("a.json", rows)[1]
    for name, data in [
        ("a.exe", b"x"),
        ("a.txt", b"\xff\xfe\x00bad"),
        ("a.json", b"{"),
        ("a.json", b"[1]"),
        ("a.txt", b"   "),
        ("a.pdf", b"not a pdf"),
    ]:
        with pytest.raises(SourceUnreadable):
            parse(name, data)


def test_parse_strips_nul():
    assert "\x00" not in parse("a.txt", b"ab\x00cd")[1]


def test_validator_keeps_good_relation_and_normalizes():
    v = run([rel()])
    assert v.relations == [
        (
            "acme corp",
            "acquired",
            "beta labs",
            "Acme Corp acquired Beta Labs",
            0.9,
        )
    ]
    assert v.entities["acme corp"][1] == "organization"
    assert v.entities["beta labs"][1] == "other"


@pytest.mark.parametrize(
    "bad,reason",
    [
        ({"confidence": 0.1}, "relation_low_confidence"),
        ({"quote": "Acme bought Beta"}, "relation_quote_not_verbatim"),
        ({"quote": "Acme"}, "relation_quote_not_verbatim"),
        ({"object": "Gamma Inc"}, "relation_unknown_endpoint"),
        ({"object": " acme   CORP "}, "relation_self_loop"),
        ({"predicate": "!!!"}, "relation_bad_predicate"),
        ({"confidence": 5}, "relation_bad_schema"),
    ],
)
def test_validator_drops(bad, reason):
    v = run([rel(**bad)])
    assert v.relations == [] and v.rejects[reason] == 1


def test_validator_entity_must_be_in_chunk_text():
    v = run([rel()], entities=ENTS + [{"name": "Ghost Co"}])
    assert "ghost co" not in v.entities
    assert v.rejects["entity_not_in_text"] == 1


def test_validator_quote_survives_pdf_line_breaks():
    chunk = "Acme Corp\nacquired   Beta\nLabs in 2020."
    v = run([rel()], chunk=chunk)
    assert len(v.relations) == 1


def test_validator_tolerates_garbage_items():
    v = validate({"entities": [None, 5], "relations": ["x"]}, CHUNK, 0.5)
    assert v.rejects["entity_bad_schema"] == 2
    assert v.rejects["relation_bad_schema"] == 1
