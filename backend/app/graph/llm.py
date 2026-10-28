import json
import time
from typing import Protocol

import httpx
from google import genai
from google.genai import errors, types

from app import config
from app.graph.errors import LLMBadOutput, LLMTimeout, LLMUnavailable

RETRIES = 3


class LLM(Protocol):
    def generate_json(self, system: str, prompt: str, schema: dict) -> dict: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class GeminiLLM:
    def __init__(self):
        if not config.GEMINI_API_KEY:
            raise LLMUnavailable("GEMINI_API_KEY is not set")
        self.client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(
                timeout=config.GEMINI_TIMEOUT_S * 1000
            ),
        )

    def _call(self, fn):
        for attempt in range(RETRIES):
            try:
                return fn()
            except (httpx.TimeoutException, TimeoutError):
                err = LLMTimeout("timeout")
            except errors.APIError as e:
                code = getattr(e, "code", None)
                if code not in (429, 500, 502, 503, 504):
                    raise LLMUnavailable(f"api error {code}") from e
                err = LLMUnavailable(f"api error {code}")
            except httpx.HTTPError as e:
                err = LLMUnavailable(type(e).__name__)
            if attempt < RETRIES - 1:
                time.sleep(2**attempt)
        raise err

    def generate_json(self, system, prompt, schema):
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0,
        )
        resp = self._call(
            lambda: self.client.models.generate_content(
                model=config.GEMINI_MODEL, contents=prompt, config=cfg
            )
        )
        cand = (resp.candidates or [None])[0]
        reason = str(getattr(cand, "finish_reason", "")).upper()
        if "MAX_TOKENS" in reason:
            raise LLMBadOutput("truncated")
        try:
            data = json.loads(resp.text)
        except (TypeError, ValueError):
            raise LLMBadOutput("not json")
        if not isinstance(data, dict):
            raise LLMBadOutput("not an object")
        return data

    def embed(self, texts):
        resp = self._call(
            lambda: self.client.models.embed_content(
                model=config.GEMINI_EMBED_MODEL,
                contents=texts,
                config=types.EmbedContentConfig(
                    output_dimensionality=config.EMBED_DIM
                ),
            )
        )
        return [e.values for e in resp.embeddings]


def get_llm() -> LLM:
    return GeminiLLM()
