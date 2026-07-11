# 03 — Kannada translation and voice

**Status**: translation and voice input implemented and wired end-to-end, including
the Command Console UI. Voice output (TTS) is gated on weights we don't have — see
below.

## The problem

Two rows of the requirement traceability matrix — *Multi-language* and *Voice
interaction*, both Core — had a backend contract (`packages/rag_agent`'s
`translation_agent`/`voice_agent`, `apps/api`'s `audio`/`respond_with_voice` fields)
but no self-hosted model behind it, and no UI control to reach it: `apps/web` had no
mic capture at all.

## What was implemented

### Translation — `data/data/nlp/translate.py`

Backend chosen at load time, self-hosted only (FIR text never leaves the network):

1. `VERITAS_INDICTRANS2_MODEL` — IndicTrans2 (AI4Bharat), the right model for EN<->KN,
   MIT-licensed. Gated HuggingFace repo — needs a one-click licence acceptance by the
   account owner, so it cannot be what Kannada depends on by default.
2. `VERITAS_TRANSLATION_MODEL`, defaulting to NLLB-200-distilled-600M — ungated, self-
   hosted, covers Kannada both directions out of the box. **CC-BY-NC-4.0, non-
   commercial** — correct for this build, not for a KSP production deployment.
3. Neither loadable → `TranslationUnavailable`. The Translation Agent answers in
   English and says so, rather than replying in the wrong language.

`packages/rag_agent/rag_agent/agents/translation_agent.py` wraps this for both
directions: inbound (kn->en, before intent classification — the keyword/regex/gazetteer
layer is English-only and would retrieve nothing on raw Kannada script) and outbound
(en->kn, on the way out through synthesis).

### Voice input (ASR) — `data/data/nlp/speech.py`

Works today, both languages, no out-of-band provisioning: **faster-whisper**
(`base.en` for English, multilingual `small` with `language="kn"` for Kannada — or
Vakyansh if `VERITAS_VAKYANSH_MODEL` is set, the better Kannada model when available).

### Voice output (TTS) — gated

IndicTTS (Kannada) and Kokoro-TTS (English) both need weights provisioned out-of-band
(Kokoro also needs the `espeak-ng` system binary). `VoiceUnavailable` degrades the
turn to text-only rather than failing it — voice reply is an enhancement, never a
precondition for answering.

### Orchestrator wiring — `packages/rag_agent/rag_agent/orchestrator.py`

```
voice_in -> translate_in -> orchestrate -> retrieve -> evaluate -> synthesize -> voice_out
```

`node_voice_in` transcribes `state.input_audio` and appends a **"Voice Agent (ASR)"**
trace step whose detail is the literal transcript (`Transcribed: "..."`) — the officer
sees what the system heard, not just a byte count, matching the reasoning-trace
principle that every step renders in plain language.

### Console UI — `apps/web/components/ChatPane.tsx`

- **Push-to-talk mic button** in the composer: `MediaRecorder` captures audio; a live
  waveform (canvas + `AnalyserNode`, no charting dependency) renders while recording.
  Stopping encodes the clip to base64 and sends it as `POST /chat`'s `audio` field
  instead of `query` — there is no separate voice endpoint, matching the documented
  contract.
- **Voice-reply toggle** (🔈/🔊) in the pane header sets `respond_with_voice`; a
  returned `type: "audio"` SSE frame is base64-decoded and played back
  (`lib/api.ts: playBase64Audio`).
- EN/KN toggle was already wired; it now also governs which ASR checkpoint the server
  selects.

## A real bug this pass found and fixed: refusals weren't translated

`node_synthesize`'s CRAG-refusal branch (`state.requires_escalation`) set
`state.final_answer = NOT_FOUND_MESSAGE` and returned immediately — the
`translation_agent.to_language()` call lower down in the function never ran for it.
A Kannada-speaking officer whose query found no evidence got refused **in English**,
the one place a bilingual system should least fail silently on language. Live-testing
the Kannada path (see below) is what surfaced this — it doesn't show up in unit tests
because none of them exercise the full `requires_escalation` → `node_synthesize`
path with a non-English `state.language`. Fixed in `orchestrator.py`: the refusal
branch now runs the same `to_language` call as the normal path.

## Verified

- `data/tests/test_nlp.py` — translation no-ops same-language, raises
  `TranslationUnavailable` cleanly regardless of whether torch/transformers happen to
  be installed on the host (forced deterministically via `monkeypatch`, not by relying
  on missing packages — see below).
- `apps/web`: `tsc --noEmit` and `next build` both clean with the mic/voice-reply/
  Copilot/alerts changes.
- Live, against the running stack with real data: `/copilot/{fir_id}`, the SSE
  `/chat` endpoint (map/network/sankey/trend visualizations all confirmed), `WS
  /alerts` (received a real `AnomalyAlert` immediately), and `POST /export/pdf`
  (produced a real 1-page PDF via headless Chrome).
- **Not verified live**: an actual Kannada round-trip through NLLB-200. This host has
  torch/transformers installed and can reach `huggingface.co` (plain HTTPS: instant),
  but the 2.4GB NLLB-200 weight download never completed in several multi-minute
  attempts — no cache directory ever formed. That's a sandbox egress/bandwidth
  characteristic for large file transfers, not a code defect: the translation and
  degrade-to-English-with-a-note logic is exercised by hermetic unit tests instead
  (`monkeypatch`-forced `TranslationUnavailable`), and the *english* path (which needs
  no model) was verified live end-to-end above.
- **Not verified**: actual microphone capture and audio playback in a real browser —
  no browser-automation tool was available in this pass to grant mic permission and
  drive it. The code path (MediaRecorder → base64 → the already-verified `/chat`
  `audio` field → ASR trace → optional TTS playback) is exercised end-to-end on the
  backend only.

## A test hang this pass found and fixed

`test_translate_is_noop_same_lang_and_errors_clearly_without_weights` assumed
torch/transformers would be absent, so `translate(..., "kn")` would raise
`TranslationUnavailable` immediately via an `ImportError`. Once this host had them
installed (for the work above), the same call instead attempted the real NLLB-200
download and hung — consistent with the slow/incomplete large-file transfer noted
above. Fixed by forcing the no-weights path with `monkeypatch` instead of relying on
the host's package state, and testing the (genuinely dependency-free) unsupported-
language-pair path for the immediate-raise case. `data/tests/test_nlp.py` now runs
in under a second; full suite is 76/76.

## Licence constraint the deployment must not skip

NLLB-200 is CC-BY-NC-4.0 (non-commercial) — correct for this datathon/research build,
not for KSP production use. IndicTrans2 (MIT) is the production path, and the reason
it stays the *preferred* backend rather than being replaced outright by the fallback.
