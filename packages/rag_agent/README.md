# RAG / Graph Reasoning (`packages/rag_agent/`)

**What this is**: the investigation brain. Takes a natural-language query + session context, decides what to retrieve (graph/vector/SQL/geospatial/ML), gathers evidence, verifies it, and returns a grounded answer with citations and a step-by-step trace. A Python package imported by `apps/api` — not a service you deploy or call over HTTP.

Owns Layers 2 (reasoning half), 3, and 5 of root [`CLAUDE.md`](../../CLAUDE.md).

## Data contracts (canonical source — other folders mirror these, don't redefine them)

```python
# SessionFocus is defined in and imported from `data` (from data import SessionFocus).
# It maps 1:1 to the session table's active_* columns and data's write helpers
# take/return it, so it lives in data to avoid a circular import (data must not
# import rag_agent). state.py re-exports it for local use.
class SessionFocus(BaseModel):         # canonical definition: data/data/models.py
    active_person: Optional[str]       # last-mentioned person_id (UUID as str) — the system-wide join key, NOT scrb_id
    active_fir: Optional[str]          # last-mentioned fir_id (UUID as str), NOT fir_number
    active_location: Optional[str]     # district or taluk name (matches session.active_location VARCHAR)
    active_date_range: Optional[tuple[date, date]]   # (from, to); persisted as session.active_date_from / active_date_to

class EvidenceItem(BaseModel):
    evidence_id: str
    source_type: Literal["FIR_RECORD", "CRIMINAL_RECORD", "GRAPH_RELATIONSHIP",
                          "COMMUNITY_SUMMARY", "ML_PREDICTION", "GEOSPATIAL_ANALYSIS"]
    source_id: str
    source_query: Optional[str]        # exact SQL / graph traversal that produced this
    content: str
    confidence: float
    timestamp: datetime

class Citation(BaseModel):             # index is 1-based — matches the [1] FIR/... render convention
    index: int
    evidence_id: str
    label: str                          # e.g. "FIR/BLR/2024/KGF/001234 — Filed 12 Mar 2024, Kolar PS, IPC 302"

class AgentTraceEntry(BaseModel):      # this is what the Reasoning Trace panel renders
    step: str                           # e.g. "HippoRAG retrieval"
    detail: str                         # plain-language, e.g. "3 corroborating records found"
    duration_ms: Optional[int]
    confidence: Optional[float]

class VisualizationPayload(BaseModel):  # drives apps/web's center context-view — see "Visualization payload" below
    kind: Literal["map", "network", "sankey", "trend", "none"]
    data: dict   # shape depends on kind — see below; "none" ships an empty dict

class InvestigationState(BaseModel):
    session_id: str; officer_id: str; officer_role: str
    original_query: Optional[str]; language: Literal["en", "kn"]
    input_audio: Optional[bytes] = None       # set when the turn started as voice; Voice Agent transcribes -> original_query
    respond_with_voice: bool = False          # frontend requests spoken response
    output_audio: Optional[bytes] = None      # set by Voice Agent (TTS) only if respond_with_voice
    active_entities: SessionFocus             # rehydrated from data.get_session_focus() by apps/api before calling in
    decomposed_subqueries: List[str]
    evidence_items: List[EvidenceItem]
    graph_query_results: List[dict]; sql_query_results: List[dict]
    vector_search_results: List[dict]; prediction_results: Dict[str, Any]   # keyed by ml_models function name, e.g. {"score_risk": RiskResult(...)}
    final_answer: Optional[str]; citations: List[Citation]
    visualization: VisualizationPayload
    confidence_score: float; requires_escalation: bool
    agent_trace: List[AgentTraceEntry]

class CopilotBrief(BaseModel):
    fir_id: str
    timeline: list[dict]              # chronological events: arrest/bail/court dates
    similar_cases: list[dict]         # top-5 MO matches, each with its recorded outcome
    leads: list[str]                  # ranked investigative leads, plain language
    draft_summary: str                # paste-ready case-diary paragraph
```

`apps/api` calls `run_investigation(state: InvestigationState) -> InvestigationState` once per turn, and `generate_copilot_brief(fir_id: str, officer_role: str) -> CopilotBrief` for the Investigation Copilot workspace (`officer_role` is required so the brief can apply `packages/policy` — see below). Both are the only two entrypoints `apps/api` calls into this package.

**What `apps/api` builds before calling `run_investigation`**: a *fresh* `InvestigationState` each turn — `session_id`/`officer_id`/`officer_role`/`original_query` (or `input_audio`)/`language` from the request, `active_entities` rehydrated via `data.get_session_focus(session_id)`, everything else empty/default. Prior turns' `evidence_items`, `*_query_results`, `citations` etc. are **not** carried forward — they're per-turn artifacts, not session state. (Full conversation history for re-display/PDF export lives in `data.conversation_turn`, written by `apps/api` after each turn — see `data/README.md`.)

## Visualization payload — what each `kind` puts in `data`

Produced by the Evidence Synthesis Agent, based on which specialist agent(s) contributed the strongest results:

- `map`: `{ "polygons": [HotspotPolygon, ...], "fir_points": [{lat, lng, fir_id}, ...] }`
- `network`: `{ "nodes": [{id, label, risk_score}, ...], "edges": [{source, target, type, strength}, ...] }` — Sigma.js/Cytoscape shape
- `sankey`: `{ "nodes": [{name}, ...], "links": [{source, target, value}, ...] }` — ECharts Sankey's native shape
- `trend`: `{ "series": [(date, point, lower, upper), ...] }` — straight from `ForecastResult.series`
- `none`: `{}` — plain-text answer, no visual (e.g. "does he have priors")

## How a query gets answered

0. **Voice Agent** (only if `input_audio` is set): transcribes via `data.speech_to_text()`, populates `original_query`. Runs before the Orchestrator and appears in `agent_trace` as its own step so the demo shows "audio in → text out" explicitly.
1. **Orchestrator** classifies intent, resolves pronouns/references against `SessionFocus` ("does **he** have priors" → look up `active_person`), updates `SessionFocus` (and calls `data.upsert_session_focus()` so it survives to the next turn), decomposes the query into subqueries, routes to specialist agents.
2. **Retrieval**:
   - **HippoRAG** (Gutiérrez et al., NeurIPS 2024) is the default path: extract query entities → seed **Personalized PageRank** (`data.gds`, NetworkX) over the knowledge graph → single-step multi-hop retrieval. ~10-20x cheaper than iterative retrieval.
   - **Think-on-Graph / ToG** (Sun et al., ICLR 2024) kicks in when HippoRAG's confidence is low or the query is explicitly multi-hop/relational (e.g. "how are these three gangs financially connected over the last year"): the LLM iteratively beam-searches entity/relation paths on the graph itself, producing a traceable reasoning path instead of trusting one generated query.
   - Louvain community summaries (`data.gds`, NetworkX) sit underneath both as the global-context layer.
3. **Specialist agents** run in parallel where possible: Graph Agent (bounded NetworkX traversal over the `graph_edge` list, depth-capped by `packages/policy`'s rules for `officer_role` *before* the walk starts — see Non-goals), SQL Agent (text-to-SQL against the `data/` schema, same policy pass), Vector Search Agent (hybrid dense+BM25, RRF fusion), Geospatial Agent (lat/lng + KDE/DBSCAN), Prediction Agent (calls `packages/ml_models`'s `detect_hotspots`/`forecast_crime`/`score_risk`/`predict_recidivism`/`estimate_causal_effect`/`flag_transactions` — never predicts inline; `estimate_causal_effect` specifically for "why"/socioeconomic-correlation questions), Translation Agent (IndicTrans2).
4. **Evidence Evaluator** — CRAG-style (Yan et al., 2024): scores each retrieval batch for relevance/confidence and triggers one of: **accept** → **widen query and retry** → explicitly answer **"not found in available records."** Never fabricates on empty evidence — this is the single most important trust guarantee in the whole system.
5. **Evidence Synthesis Agent** produces `final_answer`, ordered `citations` (each traceable to an `EvidenceItem`), and the `visualization` payload. `apps/api` forwards the **full** `evidence_items` list (not just `citations`) in the SSE final event, so the frontend's evidence-rail drawer has real content to show, not just a label.
6. **Voice Agent** (only if `respond_with_voice`): synthesizes `output_audio` from `final_answer` via `data.text_to_speech()`.

## Investigation Copilot

`generate_copilot_brief(fir_id: str, officer_role: str) -> CopilotBrief` — a separate entrypoint from `run_investigation`, called by `apps/api`'s `GET /copilot/{fir_id}`. Given an open FIR, generates:
1. Chronological timeline (every linked event: arrest, bail, court date, in order).
2. Top-5 MO-similar past cases, each with its recorded outcome (vector similarity over MO embeddings).
3. Ranked investigative leads (e.g. "matches Community 47; 3 associates in adjoining districts").
4. Draft case-summary paragraph the IO can paste into a diary entry.

`generate_copilot_brief` enforces `packages/policy` the same way `run_investigation` does: its graph reads pass through `max_traversal_depth`/`can_view_fir` for the caller's `officer_role`, and any victim-identifying field is masked *before* it reaches `draft_summary` (generated prose can't be reliably redacted after the fact). `apps/api` passes the JWT-derived `officer_role` into this call — it is not a body parameter.

## Suggested structure
```
packages/rag_agent/
  state.py             # InvestigationState, SessionFocus, EvidenceItem, Citation, AgentTraceEntry, VisualizationPayload, CopilotBrief
  orchestrator.py       # intent routing, session-focus resolution, query decomposition
  retrieval/
    hipporag.py          # personalized PageRank retrieval
    tog.py                # beam-search deep-dive
  agents/
    graph_agent.py, sql_agent.py, vector_agent.py, geo_agent.py,
    prediction_agent.py, synthesis_agent.py, translation_agent.py, voice_agent.py
  evidence/
    evaluator.py          # CRAG-style scoring/escalation
  copilot/
    timeline.py, similar_cases.py, leads.py, summary_draft.py   # generate_copilot_brief
```

## Provides / Consumes
- **Provides to `apps/api`**: `run_investigation(state) -> InvestigationState`, `generate_copilot_brief(fir_id, officer_role) -> CopilotBrief`. These are the only two entrypoints.
- **Consumes from `packages/ml_models`**: `score_risk`, `predict_recidivism`, `forecast_crime`, `detect_hotspots`, `flag_transactions`, `estimate_causal_effect` (exact signatures in that package's README) — via the Prediction Agent only. **Not** `resolve_entities` (batch, called from `data/generator/` instead) and **not** `check_anomalies` (called directly by `apps/api` for `/alerts`).
- **Consumes from `data/`**: Postgres session (`data.db.get_session()`), the knowledge graph (`data.graph.load_graph()`), vector store client, `speech_to_text`/`text_to_speech`, and the session/conversation write helpers (`upsert_session_focus`, `get_session_focus`) — never opens its own connection.
- **Consumes from `packages/policy`**: the same role→field/depth rules `apps/api` enforces on structured responses, applied here at query-construction time (see Non-goals).

## Non-goals
- No UI rendering, no schema definitions, no ML model training — this package calls `ml_models`, it doesn't contain them.
- **Not** a no-RBAC zone: masking a field (e.g. victim identity) or capping traversal depth *after* a traversal already ran is too late — those constraints must shape the query itself. So the Graph/SQL Agents import the shared `packages/policy` module (the same rules `apps/api` owns and versions) and apply them while building queries. `apps/api` still owns and defines the rules; this package only enforces the subset that can't be enforced post-hoc. Everything that *can* be checked on the final response (e.g. full-record masking) stays in `apps/api`.
