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

## The invocation contract — corrected against the real Python SDK (v1.4.0), not guessed

Every prior version of this file called a hand-built URL (`QUICKML_ENDPOINT`) with a raw
`urllib.request` POST and an OpenAI-shaped `{"model", "messages", "temperature"}` body,
because QuickML LLM Serving's own invoke contract is not published in the reachable docs.
That was wrong on more than the missing key: `pip install zcatalyst-sdk` and reading
`zcatalyst_sdk/quick_ml.py` directly shows the ONLY method the Python SDK exposes for
QuickML is:

    app.quick_ml().predict(end_point_key: str, input_data: Dict[str, Union[str, int]])
        -> POST {base}/quickml/v1/project/{project_id}/endpoints/predict
           headers: X-QUICKML-ENDPOINT-KEY: <end_point_key>
           body:    {"data": input_data}

which is a generic ML-pipeline `predict()` call — a flat key/value dict in, a JSON dict out
— not an OpenAI chat-completions shape, and not a `messages` array (the SDK's own type hint
forbids nesting). Two real consequences:

  1. The base URL is resolved by the SDK's own `AuthorizedHttpClient` from the project id
     already known — `QUICKML_ENDPOINT` was never a real requirement, only a symptom of not
     having found this. Removed.
  2. Multi-turn conversation ("Conversation Mode" in the GLM-4.7-Flash docs) cannot be a
     client-sent message array through this call shape; whatever mechanism it uses is
     server-side and undocumented here. Not implemented — `generate()`/`generate_json()`
     stay single-turn, exactly as every caller already treats them.

What remains an honest guess, clearly marked as one: the exact key name(s)
`input_data` must carry for an LLM Serving endpoint specifically (the generic ML-pipeline
docs show arbitrary "column name" keys; GLM-4.7-Flash's own page states "Input type: Text
only" but not the field name). `PROMPT_FIELD` below is the inferred value — change it in
one place, not a claim it is confirmed correct.

## A second, deeper blocker found by actually invoking predict() — not just the missing key

Confirmed live (2026-08-27, "build the actual conversational brain" pass): with a
deliberately invalid `QUICKML_ENDPOINT_KEY` set temporarily on the deployed app to force a
real call through this exact code path, the SDK's own `AuthorizedHttpClient` never even
reaches key validation — it fails first with:

    CatalystAPIError: {'code': 'API_ERROR', 'message': "Request failed with status 400
    and response data: {'code': 'ORGID_HEADER_UNAVAILABLE' ...

Traced to `zcatalyst_sdk/_http_client.py`: `HttpClient.request()` only attaches the
`CATALYST-ORG` header when `os.getenv('X_ZOHO_CATALYST_ORG_ID')` is set, and QuickML's
gateway specifically requires it (Data Store/Cache/every other call this app makes do not
— confirmed working throughout this deployment). Two things rule out a workaround from
this environment, not just "not yet tried":

  1. Setting `X_ZOHO_CATALYST_ORG_ID` via `POST /appsail/{id}/configuration` (the same
     endpoint that successfully manages every other env var this app has) is rejected
     outright: `{"error_code": "INVALID_INPUT", "message": "environment_variables must
     not contain reserved keywords"}` — the platform reserves this name for itself, and
     is not injecting it into a `custom_runtime` AppSail container.
  2. It is not recoverable from an incoming request either: the AppSail gateway's own
     per-request headers this SDK reads (`ProjectHeader`/`CredentialHeader` in
     `_constants.py` — project id, domain, key, environment, admin/user credential
     tokens) carry no org id in any form.

So the honest state is: **even a real, published `endpoint_key` would not be sufficient**
on its own — this app has no path to the org-id context QuickML's gateway requires, and
no configuration surface reachable from here can supply one. This is a platform gap for
custom_runtime AppSail apps calling QuickML specifically, not a missing credential this
project forgot to obtain. (The live diagnostic env var was set and then immediately
reverted to the exact prior state — this file's behavior with an absent key is unchanged.)
"""
import json
import logging
import os
import time

log = logging.getLogger(__name__)

MODEL = os.getenv("VERITAS_LLM_MODEL", "glm-4.7-flash")
# The unique id of a PUBLISHED QuickML LLM Serving endpoint — the one thing that must come
# from the console (see module docstring). Everything else the SDK's predict() call needs
# (base URL, project id, auth) it resolves itself from the already-initialized CatalystApp.
ENDPOINT_KEY = os.getenv("QUICKML_ENDPOINT_KEY", "").strip()
# Inferred input_data key for a single text prompt — see module docstring's last paragraph.
PROMPT_FIELD = os.getenv("VERITAS_LLM_PROMPT_FIELD", "prompt")
TIMEOUT = float(os.getenv("VERITAS_LLM_TIMEOUT", "30"))

COOLDOWN_SECONDS = 70.0

_degraded_until = 0.0
_degraded_reason = ""
_ever_succeeded = False


class LLMUnavailable(RuntimeError):
    """No usable LLM right now: not configured, exhausted, or the provider is failing."""


def _configured() -> bool:
    """A published endpoint key is the only thing predict() genuinely requires — the SDK
    resolves project id/base URL/auth itself from the already-initialized CatalystApp."""
    return bool(ENDPOINT_KEY)


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
        return "deterministic (QuickML not configured — no published endpoint key)"
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


def _predict(prompt: str) -> str:
    """The one real call: app.quick_ml().predict(endpoint_key, {PROMPT_FIELD: prompt}).

    Auth is handled entirely by the SDK's AuthorizedHttpClient (it switches to the admin
    credential internally, the same way every Data Store/Cache call in this codebase
    already authenticates) — no manual token fetch, unlike the raw-HTTP version this
    replaced.
    """
    global _ever_succeeded

    try:
        from data.ds import catalyst_app
        result = catalyst_app().quick_ml().predict(ENDPOINT_KEY, {PROMPT_FIELD: prompt})
    except ImportError as e:
        raise _degrade(RuntimeError(f"zcatalyst-sdk not installed: {e}")) from e
    except Exception as e:
        raise _degrade(e) from e

    # Response shape is the generic ML-pipeline one documented for predict():
    # {"status": "success", "result": [...]}. Handle a bare string or a dict with a
    # "response"/"text" key too — genuinely unverified which one LLM Serving uses
    # (see module docstring), so this degrades cleanly to "unexpected shape" rather
    # than crashing on whichever guess is wrong.
    text = None
    if isinstance(result, dict):
        r = result.get("result")
        if isinstance(r, list) and r:
            text = r[0] if isinstance(r[0], str) else json.dumps(r[0])
        elif isinstance(r, str):
            text = r
        elif isinstance(result.get("response"), str):
            text = result["response"]
        elif isinstance(result.get("text"), str):
            text = result["text"]
    if text is None:
        raise _degrade(RuntimeError(f"unexpected response shape: {str(result)[:200]}"))
    _ever_succeeded = True
    return text.strip()


def generate(prompt: str, system: str | None = None, temperature: float = 0.2) -> str:
    """Plain text completion. Raises LLMUnavailable on any failure — callers fall back.

    temperature is accepted for interface compatibility but not sent — predict()'s
    input_data is a flat str/int dict scoped to whatever LLM Serving's own endpoint
    schema defines, which is not documented anywhere this session could reach (see
    module docstring); adding an unconfirmed extra key risks the call being rejected
    rather than merely ignored.
    """
    if not available():
        raise LLMUnavailable(_degraded_reason or "no LLM configured")
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    return _predict(full_prompt)


def generate_json(prompt: str, schema: dict, system: str | None = None) -> dict:
    """Structured output. Returns {} on any failure or unparseable output — callers treat
    that as 'no LLM opinion' and use their deterministic path.

    The schema is stated in the prompt rather than enforced by the provider: predict()'s
    generic input_data shape has no response-format parameter to request JSON mode with,
    so correctness depends entirely on the model following the instruction and on the
    parsing below, not on a provider guarantee.
    """
    if not available():
        return {}
    sys_prompt = (system or "") + (
        "\n\nRespond with a single JSON object and nothing else. It must match this schema:\n"
        + json.dumps(schema)
    )
    try:
        raw = _predict(f"{sys_prompt.strip()}\n\n{prompt}")
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
