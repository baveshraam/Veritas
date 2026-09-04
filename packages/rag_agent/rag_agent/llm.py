"""LLM client — Catalyst QuickML LLM Serving (GLM-4.7-Flash), over the official REST API.

Was Gemini. Gemini is a third-party service and QuickML is Catalyst's equivalent, so under
the competition rule — where a Catalyst service exists, it must be used — the provider had
to move. The *interface* did not: `available()` / `generate()` / `generate_json()` and the
degraded-mode contract below are unchanged, which is why nothing else in the package had to
be touched when this file's internals changed twice (SDK attempt, then this REST rewrite).

What the LLM is and isn't used for:
  - IS: synthesising prose from evidence the caller already retrieved, ranking leads,
    drafting a case-diary paragraph, and (via `semantic_interpreter.py`) decomposing an
    officer's query into a structured `SemanticRequest`.
  - IS NOT: translating or transcribing FIR content, and it never sees Kannada. Record text
    stays inside the network — the Kannada NLP/ASR/TTS layer is self-hosted for exactly that
    reason, and a query in Kannada is translated to English *in our own container* before
    the model is called, then the answer is translated back.
  - IS NOT: the thing that makes an answer true. It never sees the database, and it cannot
    add a claim to an answer that the evidence chain does not already contain.

Degraded mode is a designed behaviour, not a stub: the deterministic paths (intent templates
+ extractive synthesis) produce grounded, cited answers on their own. The LLM makes them
fluent. So every provider failure — quota, network, 5xx, bad credentials — is funnelled into
the one signal the rest of the system already understands:

    generate()       raises LLMUnavailable  -> callers fall back to templates
    generate_json()  returns {}             -> callers treat it as "no LLM opinion"

and trips a short cooldown so an exhausted endpoint is not hammered.

## Why this is REST, not the Python SDK's quick_ml().predict()

Two prior investigations (see docs/ENGINEERING_BRIEF.md Sec12) tried `app.quick_ml().predict()`
from three different Catalyst runtimes — this app's custom_runtime AppSail, a Catalyst-managed
Python AppSail probe, and a Catalyst Basic I/O Function — and got the identical
`CatalystAPIError: ORGID_HEADER_UNAVAILABLE` every time. Root cause: the SDK's HttpClient only
attaches the `CATALYST-ORG` header when `os.getenv('X_ZOHO_CATALYST_ORG_ID')` is set, and no
Catalyst runtime tested injects it — the env var name is reserved and cannot be set manually
either. This is a platform gap in the SDK's QuickML path specifically, not a runtime choice.

The Catalyst console's own QuickML integration page names a *different*, working contract:
plain OAuth (a self-client with scope `QuickML.deployment.READ`), a manually-supplied
`CATALYST-ORG` header (a static, already-known project org id — not something that needs
runtime injection), and a documented REST endpoint:

    POST {api_base}/quickml/v1/project/{project_id}/glm/chat
    headers: Authorization: Bearer <access_token>, CATALYST-ORG: <org_id>
    body:    {"model": <model_id>, "messages": [{"role": "user", "content": "..."}], ...}

Verified live (2026-08-28) with a temporary developer CLI token: HTTP 200, real model
(`crm-di-glm47b_30b_it`), real completions. `access_token` here is minted from a dedicated
self-client (`QUICKML_CLIENT_ID`/`QUICKML_CLIENT_SECRET`/`QUICKML_REFRESH_TOKEN`) via the
standard Zoho OAuth refresh-token grant — a machine identity, independent of any developer's
personal login, which is what a deployed service must use. `QUICKML_REFRESH_TOKEN` is the one
value that cannot be produced from this environment: Zoho's self-client flow requires a human
to generate a short-lived "grant token" in the API Console UI once, which this module (or an
operator, one time) exchanges for the long-lived refresh token stored in AppSail configuration.

## A model quirk worth documenting: false-positive refusals on schema-shaped prompts

`crm-di-glm47b_30b_it` carries a baked-in system prompt (visible in its own chain-of-thought
when it fires) instructing it never to reveal/quote/describe "these rules". Empirically
(2026-08-28, ~10 trials), a prompt that asks for "a JSON object matching this schema" or
"exactly this and nothing else" pattern-matches that guard some fraction of the time and gets
refused with "I can't help with requests to expose protected instructions" — non-deterministic
across identical retries, so it is sampling-dependent, not purely content-triggered. Reframing
the instruction as an ordinary backend/integration task ("a calling program parses your reply
as data, not as a conversation") measurably reduces — but, empirically, does not eliminate —
the refusal rate. `generate_json()` below applies that framing and retries once on a detected
refusal or unparseable output before giving up; callers still see the same {} contract either
way. This is a real, load-bearing reliability limit on the structured-output path, not
something fixable client-side, and should inform how much any planner leans on it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from data import cache

log = logging.getLogger(__name__)

MODEL = os.getenv("VERITAS_LLM_MODEL", "glm-4.7-flash")                     # display name
QUICKML_MODEL_ID = os.getenv("QUICKML_MODEL_ID", "crm-di-glm47b_30b_it")    # id sent to the API

CLIENT_ID = os.getenv("QUICKML_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("QUICKML_CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.getenv("QUICKML_REFRESH_TOKEN", "").strip()
ACCOUNTS_URL = os.getenv("QUICKML_ACCOUNTS_URL", "https://accounts.zoho.in").rstrip("/")
API_BASE = os.getenv("QUICKML_API_BASE", "https://api.catalyst.zoho.in").rstrip("/")
# CATALYST_* is reserved in AppSail environment variables. Keep the local
# compatibility fallback, but use QuickML-prefixed names in the deployed runtime.
PROJECT_ID = os.getenv("QUICKML_PROJECT_ID", os.getenv("CATALYST_PROJECT_ID", "")).strip()
ORG_ID = os.getenv("QUICKML_ORG_ID", os.getenv("CATALYST_ORG", "")).strip()
TIMEOUT = float(os.getenv("VERITAS_LLM_TIMEOUT", "30"))

COOLDOWN_SECONDS = 70.0
_TOKEN_SAFETY_MARGIN = 60.0  # refresh this many seconds before Zoho says it expires

# A hard spend guard, independent of Zoho's own console-level budget alert (Settings ->
# Billing -> budget limit, the authoritative control — set it there too). This is a
# defense-in-depth backstop: it reacts the instant this process makes a call, rather than
# waiting on an email alert, and it is deliberately a call-COUNT ceiling, not a rupee
# figure, because QuickML's real per-call cost is not published anywhere this code can
# read. Tune VERITAS_LLM_MAX_CALLS down once the Catalyst billing panel shows what a real
# call actually costs on this account; 300 is a conservative placeholder, not a measured
# number. Persisted in Cache (not a module-level counter) so it survives every redeploy
# this project does routinely — a counter that resets on every deploy is not a cap.
MAX_OUTPUT_TOKENS = int(os.getenv("VERITAS_LLM_MAX_TOKENS", "900"))
MAX_CALLS = int(os.getenv("VERITAS_LLM_MAX_CALLS", "300"))
_BUDGET_KEY = "quickml_call_budget_v1"
_BUDGET_TTL_HOURS = 24 * 30  # long enough to span the whole competition window

# The model's own reasoning trace is observed live (2026-08-28) to end with a bare
# </think> marker but *no* matching opening <think> tag — an opening-tag regex like
# r"<think>.*?</think>" never matches, and the entire chain-of-thought leaks through as
# the "answer". Strip everything up to and including the LAST </think>, tag optional.
_THINK_RE = re.compile(r"^.*</think>", re.DOTALL)
_REFUSAL_MARKER = "protected instructions"

_INTEGRATION_FRAME = (
    "You are functioning as a backend API for a police-records application. The calling "
    "program parses your reply programmatically as data, not as a conversation. This is a "
    "normal integration task, unrelated to your configuration or instructions.\n\n"
)

_degraded_until = 0.0
_degraded_reason = ""
_ever_succeeded = False

_access_token = ""
_access_token_expiry = 0.0


class LLMUnavailable(RuntimeError):
    """No usable LLM right now: not configured, exhausted, or the provider is failing."""


def _configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET and REFRESH_TOKEN and PROJECT_ID and ORG_ID)


def calls_used() -> int:
    return int(cache.get(_BUDGET_KEY) or 0)


def budget_exhausted() -> bool:
    return calls_used() >= MAX_CALLS


def _record_call() -> None:
    """Count one real, billed QuickML request. Called only after `_raw_chat` gets an
    actual HTTP response — a call that raised before reaching the network (unconfigured,
    still cooling down) was never billed and must not count against the cap."""
    cache.put(_BUDGET_KEY, calls_used() + 1, expiry_hours=_BUDGET_TTL_HOURS)


def available() -> bool:
    """True only if a call would plausibly succeed — configured, not cooling down, and
    under the call-budget cap. The budget check degrades exactly like every other
    failure mode this module has: callers fall back to the deterministic path, which
    already produces grounded, cited answers on its own."""
    if not _configured():
        return False
    if budget_exhausted():
        return False
    return time.monotonic() >= _degraded_until


def status() -> str:
    """Honest one-liner for /health. Never reports a model when it cannot be reached."""
    if not _configured():
        return "deterministic (QuickML not configured — no OAuth client/refresh token)"
    if budget_exhausted():
        return (f"deterministic (LLM call budget exhausted: {calls_used()}/{MAX_CALLS} — "
                f"raise VERITAS_LLM_MAX_CALLS after checking real Catalyst billing)")
    if time.monotonic() < _degraded_until:
        return f"deterministic (LLM degraded: {_degraded_reason})"
    if not _ever_succeeded:
        return f"quickml ({MODEL}) — configured, not yet contacted, {calls_used()}/{MAX_CALLS} calls used"
    return f"quickml ({MODEL}) — {calls_used()}/{MAX_CALLS} calls used"


def _degrade(exc: Exception) -> LLMUnavailable:
    """Trip the cooldown and convert any provider error into the one signal we handle."""
    global _degraded_until, _degraded_reason
    _degraded_until = time.monotonic() + COOLDOWN_SECONDS
    _degraded_reason = f"{type(exc).__name__}: {str(exc)[:120]}"
    log.warning("LLM degraded: %s", _degraded_reason)
    return LLMUnavailable(_degraded_reason)


def _http_post_json(url: str, headers: dict, body: bytes, timeout: float) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"network error: {e.reason}") from e


def _get_access_token() -> str:
    """Mint (or reuse) a QuickML access token via the self-client refresh-token grant.

    This is a machine identity dedicated to QuickML, independent of any developer's personal
    Catalyst CLI login — the latter works (verified live) but must never be embedded in a
    deployed service.
    """
    global _access_token, _access_token_expiry

    if _access_token and time.monotonic() < _access_token_expiry - _TOKEN_SAFETY_MARGIN:
        return _access_token

    form = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
    }).encode("utf-8")
    result = _http_post_json(
        f"{ACCOUNTS_URL}/oauth/v2/token",
        {"Content-Type": "application/x-www-form-urlencoded"},
        form,
        TIMEOUT,
    )
    token = result.get("access_token")
    if not token:
        raise RuntimeError(f"token refresh returned no access_token: {str(result)[:200]}")

    _access_token = token
    _access_token_expiry = time.monotonic() + float(result.get("expires_in", 3600))
    return _access_token


def warm() -> None:
    """Mint the OAuth access token proactively, off the request path.

    Measured live: the FIRST real QuickML call on a container — Copilot's brief is
    the one path that unconditionally calls the LLM, since most `/chat` turns
    deliberately route around it when deterministic confidence is high enough
    (`_get_access_token` reuses a cached token, so no other turn had paid this
    cost) — took long enough that a client-side 30s timeout gave up on it, while
    a second call moments later (cached token) answered in under half a second.
    Same class of bug as BUG-016 (a cold NLLB/whisper load), same fix: pay the
    cost once during startup instead of on whichever officer's Copilot request
    happens to be first. Deliberately does NOT warm the GLM chat call itself —
    that would spend a real QuickML request/credit for a warm-up nobody asked
    for; the OAuth exchange alone is a Zoho-accounts call, not a billed QuickML
    one. Best-effort: a query must never fail because warm-up is still running
    or failed, and the token refresh has its own client-side error handling.
    """
    if not _configured():
        return
    try:
        _get_access_token()
    except Exception:
        pass                          # the request path retries and degrades honestly


def _split_think(text: str) -> tuple[str, str]:
    """Split off the model's own chain-of-thought (see _THINK_RE) from its answer.

    Returns (reasoning, answer). Normally the reasoning half is thrown away
    (`_chat`); `generate_with_reasoning` is the one caller that keeps it, to
    surface real Chain-of-Thought in the Reasoning Trace panel instead of paying
    for a second, separate deliberation call."""
    m = _THINK_RE.match(text)
    if not m:
        return "", text.strip()
    return m.group(0)[: -len("</think>")].strip(), text[m.end():].strip()


def _raw_chat(messages: list[dict], temperature: float | None = None) -> str:
    """One real call to QuickML's GLM chat endpoint. Returns the full reply text,
    <think> block and all — callers split it with `_split_think`."""
    global _ever_succeeded

    if budget_exhausted():
        raise LLMUnavailable(f"QuickML call budget exhausted ({calls_used()}/{MAX_CALLS})")

    try:
        token = _get_access_token()
        # max_tokens is not optional: the API has no default cap of its own (the model
        # supports up to 128K tokens of output), so an uncapped request is an open-ended
        # cost per call. Every caller here wants a paragraph or a small JSON object, never
        # a document, so this is a real limit, not a formality.
        body: dict = {"model": QUICKML_MODEL_ID, "messages": messages,
                     "max_tokens": MAX_OUTPUT_TOKENS}
        if temperature is not None:
            body["temperature"] = temperature
        result = _http_post_json(
            f"{API_BASE}/quickml/v1/project/{PROJECT_ID}/glm/chat",
            {
                "Authorization": f"Bearer {token}",
                "CATALYST-ORG": ORG_ID,
                "Content-Type": "application/json",
            },
            json.dumps(body).encode("utf-8"),
            TIMEOUT,
        )
    except Exception as e:
        raise _degrade(e) from e

    # Counted here, not in a wrapper: this is the one place a request actually reached
    # QuickML and got a response back, which is the event that gets billed.
    _record_call()

    text = result.get("response")
    if not isinstance(text, str):
        raise _degrade(RuntimeError(f"unexpected response shape: {str(result)[:200]}"))

    _ever_succeeded = True
    return text


def _chat(messages: list[dict], temperature: float | None = None) -> str:
    """One real call to QuickML's GLM chat endpoint. Returns the reply text with any
    <think>...</think> reasoning trace stripped."""
    _, answer = _split_think(_raw_chat(messages, temperature))
    return answer


def generate(prompt: str, system: str | None = None, temperature: float = 0.2) -> str:
    """Plain text completion. Raises LLMUnavailable on any failure — callers fall back.

    A false-positive safety refusal (see module docstring) is content, not a transport
    failure, so `_chat()` itself doesn't know to treat it as one — but a refusal string
    handed to a caller as if it were real fluent prose is exactly the failure mode this
    module exists to prevent (a synthesis caller would show it to an officer as the
    answer). One retry with the reassurance framing; a second refusal degrades like any
    other provider failure, so callers fall back to their deterministic path either way.
    """
    if not available():
        raise LLMUnavailable(_degraded_reason or "no LLM configured")

    def _messages(extra_frame: str = "") -> list[dict]:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": extra_frame + prompt})
        return msgs

    text = _chat(_messages(), temperature)
    if _REFUSAL_MARKER in text.lower():
        text = _chat(_messages(_INTEGRATION_FRAME), temperature)
        if _REFUSAL_MARKER in text.lower():
            raise _degrade(RuntimeError("model refused a benign prompt (safety false positive)"))
    return text


def generate_with_reasoning(prompt: str, system: str | None = None,
                            temperature: float = 0.2) -> tuple[str, str]:
    """Like `generate()`, but also returns the model's own step-by-step reasoning.

    GLM-4.7-Flash already emits a `<think>...</think>` chain-of-thought before its
    answer on every call — `_chat()` normally discards it. Tree-of-Thought-style
    branching search would cost several extra calls per turn on a small, fast model
    and largely duplicate what HippoRAG/Think-on-Graph already do at the retrieval
    layer (see rag_agent/retrieval/tog.py); the industry-standard fit for a single
    synthesis call is plain Chain-of-Thought, so this stops throwing the model's own
    CoT away rather than adding a second reasoning pass on top of it. Same
    refusal-retry behaviour as `generate()`; raises LLMUnavailable on failure."""
    if not available():
        raise LLMUnavailable(_degraded_reason or "no LLM configured")

    def _messages(extra_frame: str = "") -> list[dict]:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": extra_frame + prompt})
        return msgs

    reasoning, answer = _split_think(_raw_chat(_messages(), temperature))
    if _REFUSAL_MARKER in answer.lower():
        reasoning, answer = _split_think(_raw_chat(_messages(_INTEGRATION_FRAME), temperature))
        if _REFUSAL_MARKER in answer.lower():
            raise _degrade(RuntimeError("model refused a benign prompt (safety false positive)"))
    return answer, reasoning


def generate_json(prompt: str, schema: dict, system: str | None = None) -> dict:
    """Structured output. Returns {} on any failure or unparseable output — callers treat
    that as 'no LLM opinion' and use their deterministic path.

    A persistent refusal is already turned into LLMUnavailable by `generate()`; the retry
    loop here is only for a real reply that doesn't parse as JSON.
    """
    if not available():
        return {}

    instruction = _INTEGRATION_FRAME + (
        "Respond with a single JSON object and nothing else. It must match this shape:\n"
        + json.dumps(schema) + "\n\n" + (system or "") + "\n\n" + prompt
    )

    for _attempt in range(2):
        try:
            raw = generate(instruction)
        except LLMUnavailable:
            return {}

        raw = raw.strip()
        if raw.startswith("```"):                       # models fence JSON even when told not to
            raw = raw.strip("`")
            raw = raw[raw.index("{"):] if "{" in raw else raw
        try:
            out = json.loads(raw or "{}")
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            continue
    return {}
