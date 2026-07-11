# Status — what actually runs

Last updated: the Kannada/voice pass.

## Runs today, against the live stack

| Capability | Backing | Verified by |
|---|---|---|
| Knowledge graph + GDS | Neo4j, PageRank / Louvain / betweenness | `data/tests/test_graph_sync.py` |
| Retrieval | HippoRAG (personalised PageRank) + Think-on-Graph beam search | `test_engine.py`, live API |
| Verification | CRAG evaluator — refuses on weak/empty evidence | `test_engine.py` |
| Entity resolution | Fellegi–Sunter, 100% precision/recall on injected duplicates | `test_entity_resolution.py` |
| Forecasting | Prophet + MinT (coherence to 1e-9) | `test_models.py` |
| Hotspots | KDE + DBSCAN over PostGIS | `test_models.py` |
| Risk / recidivism | XGBoost+SHAP, calibrated LightGBM, temporal split | `test_models.py` |
| Financial crime | Rule-based structuring detector + GraphSAGE GNN | `test_models.py` |
| **Causal inference** | **DoWhy on real Census 2011 — identified, estimated, refuted** | live API; [`01`](./01-causal-layer.md) |
| Fairness | Aequitas-style audit, 80% rule, gender + district subgroups | `fairness_run_audit.py` |
| RBAC | Enforced at query-construction *and* on structured responses | `test_rules.py`, `test_api.py` |
| Audit | Append-only, SHA-256, DB-level immutability | `test_api.py` |
| **LLM synthesis** | **Gemini `gemini-flash-lite-latest`, degrading on any failure** | live API; [`02`](./02-llm-resilience.md) |
| **Kannada translation** | **Self-hosted NLLB-200; IndicTrans2 when provisioned** | [`03`](./03-kannada-and-voice.md) |
| **Voice input (ASR)** | **faster-whisper — English + Kannada, both self-hosted** | [`03`](./03-kannada-and-voice.md) |

## Blocked, and precisely why

Each fails loudly with the exact remedy. None degrades silently.

| Blocked | The actual blocker | Can we unblock it? |
|---|---|---|
| **IndicTrans2** (the *better* Kannada model) | Gated HuggingFace repo. The weights need a one-click licence acceptance on the model page, by the account owner. | **No — human action.** Accept the licence, then set `VERITAS_INDICTRANS2_MODEL`. NLLB-200 covers Kannada meanwhile. |
| **Text-to-speech** (voice *output*) | Kokoro-TTS needs the `espeak-ng` system binary; IndicTTS weights are provisioned out-of-band. | **No — system dependency.** Voice *input* works; the console degrades to text output. |
| **District-level police strength** | Not published in India below state level (BPR&D/KSP are state-wide; Indiastat's district cut is paywalled). | **No — data does not exist publicly.** Declared an unmeasured confounder on every causal estimate. |
| **Per-district causal effects** | Census 2011 is a single year → a 30-district cross-section, not a panel. | **No — needs district-year data.** One state-wide effect is reported, and says so. |
| **Micro-geography** | Incidents cluster on synthetic activity centres; the WorldPop/OSM attractor layer isn't loaded. | Yes, with the WorldPop download. The hotspot *method* is production-grade; the geography under it isn't yet. |

## Licence constraint the deployment must not skip

**NLLB-200 is CC-BY-NC-4.0 (non-commercial).** Correct for a datathon/research build,
**not** for production use by KSP. IndicTrans2 is MIT — that is the production path, and
the reason it stays the *preferred* backend rather than being replaced by the fallback.
