import json
import zlib

from app.graph.errors import LLMBadOutput, LLMTimeout, LLMUnavailable


class FakeLLM:
    """Scriptable stand-in for Gemini. Records every prompt it sees."""

    def __init__(self, extract=None, answer=None, fail=None, fail_embed=False):
        self.fail_embed = fail_embed
        self.extract = extract or (
            lambda passage: {"entities": [], "relations": []}
        )
        self.answer = answer
        self.fail = fail  # None | "down" | "timeout" | "bad" | callable
        self.calls = []

    def generate_json(self, system, prompt, schema):
        self.calls.append((system, prompt))
        fail = self.fail(prompt) if callable(self.fail) else self.fail
        if fail == "down":
            raise LLMUnavailable("down")
        if fail == "timeout":
            raise LLMTimeout("timeout")
        if fail == "bad":
            raise LLMBadOutput("bad")
        if "knowledge graph" in system:
            return self.extract(prompt)
        return self.answer(prompt) if self.answer else {}

    def embed(self, texts):
        if self.fail_embed:
            raise LLMUnavailable("embed down")
        out = []
        for t in texts:
            vec = [0.0] * 768
            for w in t.casefold().split():
                vec[zlib.crc32(w.encode()) % 768] += 1.0
            out.append(vec)
        return out


def script(mapping):
    """extract fn: returns the entry whose key appears in the passage."""

    def fn(prompt):
        for key, value in mapping.items():
            if key in prompt:
                return value
        return {"entities": [], "relations": []}

    return fn


def rel(s, p, o, quote=None, conf=0.9):
    return {
        "subject": s,
        "predicate": p,
        "object": o,
        "quote": quote or f"{s} {p} {o}",
        "confidence": conf,
    }


def doc(entities, relations):
    return {"entities": [{"name": e} for e in entities], "relations": relations}


__all__ = ["FakeLLM", "script", "rel", "doc", "json"]
