"""LLM client — Google Gemini, read from the environment, never hardcoded.

`GEMINI_API_KEY` lives in the Vercel project as a *sensitive* variable: it is
injected at deploy/runtime and cannot be read back locally (`vercel env pull`
returns it empty). So the engine must run correctly **without** it, and light up
automatically when it's present. `available()` is that switch.

What the LLM is and isn't used for:
  - IS: synthesising prose from evidence the caller already retrieved, ranking
    leads, and NL->Cypher for queries no intent template covers.
  - IS NOT: translating or transcribing FIR content. Record text stays inside the
    network (Layer 6 is self-hosted for exactly this reason).

Degraded mode is a designed behaviour, not a stub: the deterministic paths
(intent templates + extractive synthesis) produce grounded, cited answers on their
own. The LLM makes them fluent; it is never the thing that makes them true.
"""
import json
import os
from functools import lru_cache

MODEL = "gemini-2.0-flash"


class LLMUnavailable(RuntimeError):
    """No GEMINI_API_KEY in the environment."""


def available() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


@lru_cache(maxsize=1)
def _client():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise LLMUnavailable(
            "GEMINI_API_KEY is not set. The engine runs in deterministic mode; set "
            "the key (it is injected on Vercel) to enable LLM synthesis.")
    from google import genai
    return genai.Client(api_key=key)


def generate(prompt: str, system: str | None = None, temperature: float = 0.2) -> str:
    """Plain text completion. Raises LLMUnavailable if no key — callers fall back."""
    from google.genai import types

    cfg = types.GenerateContentConfig(temperature=temperature)
    if system:
        cfg.system_instruction = system
    resp = _client().models.generate_content(model=MODEL, contents=prompt, config=cfg)
    return (resp.text or "").strip()


def generate_json(prompt: str, schema: dict, system: str | None = None) -> dict:
    """Structured output. Returns {} if the model returns something unparseable —
    callers treat that as 'no LLM opinion' and use their deterministic path."""
    from google.genai import types

    cfg = types.GenerateContentConfig(
        temperature=0.0,
        response_mime_type="application/json",
        response_schema=schema,
    )
    if system:
        cfg.system_instruction = system
    resp = _client().models.generate_content(model=MODEL, contents=prompt, config=cfg)
    try:
        return json.loads(resp.text or "{}")
    except json.JSONDecodeError:
        return {}
