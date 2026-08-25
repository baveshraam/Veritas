"""LLM client — Catalyst QuickML LLM Serving (GLM-4.7-Flash).

Was Gemini. Gemini is a third-party service and QuickML is Catalyst's equivalent, so under
the competition rule — where a Catalyst service exists, it must be used — the provider had
to move. The *interface* did not: `available()` / `generate()` / `generate_json()` and the
degraded-mode contract below are unchanged, which is why nothing else in the package had to
be touched.

What the LLM is and isn't used for:
  - IS: synthesising prose from evidence the caller already retrieved, ranking leads,
    drafting a case-diary paragraph.
  - IS NOT: translating or transcribing FIR content, and it never sees Kannada. Record text
    stays inside the network — the Kannada NLP/ASR/TTS layer is self-hosted for exactly that
    reason, and a query in Kannada is translated to English *in our own container* before
    the model is called, then the answer is translated back.
  - IS NOT: the thing that makes an answer true. It never sees the database, and it cannot
    add a claim to an answer that the evidence chain does not already contain.

Authentication is nothing. Inside AppSail the Catalyst SDK is injected with the app's own
credentials (`CATALYST_AUTH`), so there is no API key in the image, no secret to rotate, and
nothing to leak. Locally, where there is no Catalyst, `available()` is simply False.

Degraded mode is a designed behaviour, not a stub: the deterministic paths (intent templates
+ extractive synthesis) produce grounded, cited answers on their own. The LLM makes them
fluent. So every provider failure — quota, network, 5xx, bad credentials — is funnelled into
the one signal the rest of the system already understands:

    generate()       raises LLMUnavailable  -> callers fall back to templates
    generate_json()  returns {}             -> callers treat it as "no LLM opinion"

and trips a short cooldown so an exhausted endpoint is not hammered.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

MODEL = os.getenv("VERITAS_LLM_MODEL", "glm-4.7-flash")
ENDPOINT = os.getenv("QUICKML_ENDPOINT", "").strip()
TIMEOUT = float(os.getenv("VERITAS_LLM_TIMEOUT", "30"))

COOLDOWN_SECONDS = 70.0

_degraded_until = 0.0
_degraded_reason = ""
_ever_succeeded = False


class LLMUnavailable(RuntimeError):
    """No usable LLM right now: not configured, exhausted, or the provider is failing."""


def _token() -> str | None:
    """The app's own Catalyst token. In AppSail the SDK context comes from the request
    headers the API middleware captured into data.ds — a bare initialize() would fail
    with empty headers. Absent everywhere else."""
    try:
        from data.ds import catalyst_app
        cred = catalyst_app()._app._credential  # noqa: SLF001
        return cred.get_token()
    except Exception:
        return None


def _configured() -> bool:
    return bool(ENDPOINT) and os.getenv("CATALYST_PROJECT_ID", "").strip() != ""


def available() -> bool:
    """True only if a call would plausibly succeed — configured AND not cooling down."""
    if not _configured():
        return False
    return time.monotonic() >= _degraded_until


def status() -> str:
    """Honest one-liner for /health. Never reports a model when it cannot be reached.

    It used to break that promise twice over. It reported `quickml (glm-4.7-flash)`
    whenever an endpoint URL was merely *configured* — reachable or not, contacted or
    not — and the one failure mode that was actually occurring in production ("no
    Catalyst credential", raised straight out of _chat) bypassed _degrade(), so the
    cooldown never tripped and the status never changed. Live, every answer was
    extractive and the Copilot diary was the deterministic string, while /health
    reported the model as serving. Configured is not the same as working, and this
    now says which one it knows.
    """
    if not _configured():
        return "deterministic (QuickML not configured)"
    if time.monotonic() < _degraded_until:
        return f"deterministic (LLM degraded: {_degraded_reason})"
    if not _ever_succeeded:
        return f"quickml ({MODEL}) — configured, not yet contacted"
    return f"quickml ({MODEL})"


def _degrade(exc: Exception) -> LLMUnavailable:
    """Trip the cooldown and convert any provider error into the one signal we handle."""
    global _degraded_until, _degraded_reason
    _degraded_until = time.monotonic() + COOLDOWN_SECONDS
    _degraded_reason = f"{type(exc).__name__}: {str(exc)[:120]}"
    log.warning("LLM degraded: %s", _degraded_reason)
    return LLMUnavailable(_degraded_reason)


def _chat(messages: list[dict], temperature: float, json_mode: bool) -> str:
    global _ever_succeeded

    token = _token()
    if not token:
        # Through _degrade(), not raised bare. Raised bare it left _degraded_until at
        # zero, so status() went on reporting a serving model while every single call
        # failed on this line — which is exactly what was happening in production.
        raise _degrade(RuntimeError(
            "no Catalyst credential — QuickML is only reachable in AppSail"))

    body: dict = {"model": MODEL, "messages": messages, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Authorization": f"Zoho-oauthtoken {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        raise _degrade(RuntimeError(f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"))
    except Exception as e:
        raise _degrade(e) from e

    try:
        out = (payload["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise _degrade(RuntimeError(f"unexpected response shape: {str(payload)[:200]}")) from e
    _ever_succeeded = True
    return out


def generate(prompt: str, system: str | None = None, temperature: float = 0.2) -> str:
    """Plain text completion. Raises LLMUnavailable on any failure — callers fall back."""
    if not available():
        raise LLMUnavailable(_degraded_reason or "no LLM configured")
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    return _chat(messages, temperature, json_mode=False)


def generate_json(prompt: str, schema: dict, system: str | None = None) -> dict:
    """Structured output. Returns {} on any failure or unparseable output — callers treat
    that as 'no LLM opinion' and use their deterministic path.

    The schema is stated in the prompt rather than enforced by the provider: QuickML's
    OpenAI-compatible surface has `json_object` but no `json_schema`, so the model is told
    the shape and the result is validated by parsing. An unparseable answer degrades to {},
    which is the same thing a refusal would have produced.
    """
    if not available():
        return {}
    sys_prompt = (system or "") + (
        "\n\nRespond with a single JSON object and nothing else. It must match this schema:\n"
        + json.dumps(schema)
    )
    try:
        raw = _chat([{"role": "system", "content": sys_prompt.strip()},
                     {"role": "user", "content": prompt}], 0.0, json_mode=True)
    except LLMUnavailable:
        return {}

    raw = raw.strip()
    if raw.startswith("```"):                       # models fence JSON even when told not to
        raw = raw.strip("`")
        raw = raw[raw.index("{"):] if "{" in raw else raw
    try:
        out = json.loads(raw or "{}")
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        return {}
