# 02 — The LLM is live, and degrades correctly when it isn't

**Status**: implemented and verified end-to-end.

## The stale premise

`llm.py` and the root README both asserted that `GEMINI_API_KEY` is a *sensitive* Vercel
variable that "cannot be read back locally (`vercel env pull` returns it empty)", and
that the engine therefore never exercises the LLM path in development.

**That is no longer true.** The key is present in `.env.local` and works: a live call
returns 39 available models. The primary synthesis path had, as far as the code showed,
never actually been run.

## What was found once it ran

The key is valid but **free-tier quota is exhausted on most models**:

| Model | Result |
|---|---|
| `gemini-2.0-flash` | 429 RESOURCE_EXHAUSTED |
| `gemini-2.0-flash-lite` | 429 |
| `gemini-2.5-pro` | 429 |
| `gemini-2.5-flash` / `-lite` | 404 (not available on this key) |
| **`gemini-flash-lite-latest`** | **works** |

`MODEL` now defaults to `gemini-flash-lite-latest`, overridable with
`VERITAS_GEMINI_MODEL` when the quota picture moves.

## The real bug this exposed

The engine only degraded when the key was **absent** — which turns out to be the rare
case. The common one is a key that is present but rate-limited, and Gemini's free tier
429s precisely when a demo hammers it.

Under the old contract `available()` returned `True` (the key exists), the guard passed,
and the raw provider exception propagated. Two call sites did **not** wrap their LLM
call:

- `retrieval/tog.py` — the Think-on-Graph beam-search scorer
- `agents/cypher_agent.py` — NL→Cypher generation

so a 429 there crashed the turn. (`synthesis_agent` and `copilot/brief` were already
guarded.)

## The fix

Rather than bolt a `try/except` onto each call site — which the next call site would
forget — the **client itself** degrades. Every provider failure (quota, network, 5xx,
bad key, safety block) is funnelled into the one signal the rest of the system already
understands:

```
generate()       raises LLMUnavailable  -> callers fall back to templates
generate_json()  returns {}             -> callers treat as "no LLM opinion"
```

`available()` now means *"a call would plausibly succeed"* — key present **and** not
cooling down — rather than merely *"a key exists"*.

A failure trips a **70-second cooldown**. Deliberately short: free-tier limits are
per-minute, so a permanent trip would give up an LLM that is seconds from working again.

`/health` now reports `status()`, which distinguishes the three states — a bare
"deterministic" cannot tell an unset key from a 429'd quota, and those need different
fixes:

```json
{"llm": "gemini (gemini-flash-lite-latest)"}
{"llm": "deterministic (no GEMINI_API_KEY)"}
{"llm": "deterministic (LLM degraded: ClientError: 429 RESOURCE_EXHAUSTED...)"}
```

## A second, worse bug: the silent hang

`POST /chat` runs the sync engine in a worker thread and awaits the result on a queue.
If `run_investigation()` raised, `queue.put_nowait` was never called — so `await
queue.get()` blocked **forever**. The officer watched keep-alive pings until the
connection timed out. No error, no answer, no explanation.

This is how the `causal("unemployment", ...)` regression surfaced: the engine threw
`ValueError: unsupported factor`, and the console simply hung.

Fixed on both sides:
- **API**: the worker hands the exception back on the queue; the stream emits a typed
  `error` frame and logs it.
- **Web**: `lib/api.ts` throws on an `error` frame instead of ignoring it, and
  `page.tsx` stops the turn and shows the message rather than spinning.

## Verified working

```
status: gemini (gemini-flash-lite-latest)
generate -> 'OK'

--- forced onto a quota-exhausted model ---
raised LLMUnavailable (not a raw ClientError)
available() -> False          (cooldown tripped)
status()    -> deterministic (LLM degraded: ClientError: 429 RESOURCE_EXHAUSTED...)
generate_json -> {}           (returns {}, never raises)

--- previously-unguarded call sites, under a dead LLM ---
tog._rank      -> [1.2, 1.2]      structural fallback, no crash
cypher_agent   -> LLMUnavailable  the handled type
```

And a full LLM-synthesised answer through the live API, grounded in 6 citations — see
[`01-causal-layer.md`](./01-causal-layer.md).

## Tests

`packages/rag_agent/tests/test_engine.py` (+2): a provider failure degrades instead of
propagating, trips the cooldown, and reports honestly; a missing key is distinguished
from a degraded one.

`apps/api/tests/test_api.py`: `/health` must say *why* the LLM is off, not just that it
is.

## Note on the "FIR data never leaves the network" claim

Unchanged and still true for Layer 6: translation, ASR and TTS are self-hosted and are
**not** routed to Gemini. The LLM only synthesises prose over evidence the caller has
already retrieved. That boundary is documented at the top of `llm.py`.
