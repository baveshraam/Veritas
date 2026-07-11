"""LLM client — Google Gemini, read from the environment, never hardcoded.

What the LLM is and isn't used for:
  - IS: synthesising prose from evidence the caller already retrieved, ranking
    leads, and NL->Cypher for queries no intent template covers.
  - IS NOT: translating or transcribing FIR content. Record text stays inside the
    network (Layer 6 is self-hosted for exactly this reason).

Degraded mode is a designed behaviour, not a stub: the deterministic paths (intent
templates + extractive synthesis) produce grounded, cited answers on their own. The
LLM makes them fluent; it is never the thing that makes them true.

**A present key is not an available LLM.** The original design only degraded when
`GEMINI_API_KEY` was absent, which turned out to be the rare case. The common one is
a key that is valid but rate-limited: Gemini's free tier returns 429 RESOURCE_
EXHAUSTED, and it does so precisely when a demo hammers it. Under the old contract
`available()` returned True, the guard passed, and the raw provider error propagated
out of the Cypher Agent and the ToG beam search (neither wrapped its call) and killed
the turn.

So every provider failure — quota, network, 5xx, bad key — is funnelled into the one
signal the rest of the system already understands:

    generate()       raises LLMUnavailable  -> callers fall back to templates
    generate_json()  returns {}             -> callers treat as "no LLM opinion"

and trips a short cooldown so we stop hammering an exhausted quota. The cooldown is
deliberately short: free-tier limits are per-minute, so a permanent trip would give
up an LLM that is seconds away from working again.
"""
import json
import os
import time
from functools import lru_cache

# Free-tier quota is the binding constraint and it differs per model: this key is
# 429-exhausted on gemini-2.0-flash/-lite and 2.5-pro, and serving on flash-lite-
# latest. Override with VERITAS_GEMINI_MODEL when the quota picture moves.
MODEL = os.getenv("VERITAS_GEMINI_MODEL", "gemini-flash-lite-latest")

# Gemini free-tier limits are per-minute, so back off for slightly over a minute.
COOLDOWN_SECONDS = 70.0

_degraded_until = 0.0
_degraded_reason = ""


class LLMUnavailable(RuntimeError):
    """No usable LLM right now: no key, exhausted quota, or the provider is failing."""


def available() -> bool:
    """True only if a call would plausibly succeed — key present AND not cooling down."""
    if not os.getenv("GEMINI_API_KEY", "").strip():
        return False
    return time.monotonic() >= _degraded_until


def status() -> str:
    """Honest one-liner for /health. Never reports 'gemini' when the quota is spent."""
    if not os.getenv("GEMINI_API_KEY", "").strip():
        return "deterministic (no GEMINI_API_KEY)"
    if time.monotonic() < _degraded_until:
        return f"deterministic (LLM degraded: {_degraded_reason})"
    return f"gemini ({MODEL})"


def _degrade(exc: Exception) -> LLMUnavailable:
    """Trip the cooldown and convert any provider error into the one signal we handle."""
    global _degraded_until, _degraded_reason
    _degraded_until = time.monotonic() + COOLDOWN_SECONDS
    _degraded_reason = f"{type(exc).__name__}: {str(exc)[:120]}"
    return LLMUnavailable(_degraded_reason)


@lru_cache(maxsize=1)
def _client():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise LLMUnavailable("GEMINI_API_KEY is not set; running in deterministic mode")
    from google import genai
    return genai.Client(api_key=key)


def generate(prompt: str, system: str | None = None, temperature: float = 0.2) -> str:
    """Plain text completion. Raises LLMUnavailable on any failure — callers fall back."""
    if not available():
        raise LLMUnavailable(_degraded_reason or "no LLM configured")
    from google.genai import types

    cfg = types.GenerateContentConfig(temperature=temperature)
    if system:
        cfg.system_instruction = system
    try:
        resp = _client().models.generate_content(model=MODEL, contents=prompt, config=cfg)
    except LLMUnavailable:
        raise
    except Exception as e:                     # quota, network, 5xx, safety block
        raise _degrade(e) from e
    return (resp.text or "").strip()


def generate_json(prompt: str, schema: dict, system: str | None = None) -> dict:
    """Structured output. Returns {} on any failure or unparseable output — callers
    treat that as 'no LLM opinion' and use their deterministic path."""
    if not available():
        return {}
    from google.genai import types

    cfg = types.GenerateContentConfig(
        temperature=0.0,
        response_mime_type="application/json",
        response_schema=schema,
    )
    if system:
        cfg.system_instruction = system
    try:
        resp = _client().models.generate_content(model=MODEL, contents=prompt, config=cfg)
    except LLMUnavailable:
        return {}
    except Exception as e:
        _degrade(e)
        return {}
    try:
        return json.loads(resp.text or "{}")
    except json.JSONDecodeError:
        return {}
