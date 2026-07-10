# RAG / Graph Reasoning (`packages/rag_agent/`)

**What this is**: the investigation brain. Takes a natural-language query + session context, decides what to retrieve (graph/vector/SQL/geospatial/ML), gathers evidence, verifies it, and returns a grounded answer with citations and a step-by-step trace. A Python package imported by `apps/api` — not a service you deploy or call over HTTP.

Owns Layers 2 (reasoning half), 3, and 5 of root [`CLAUDE.md`](../../CLAUDE.md).

## Data contracts (canonical source — other folders mirror these, don't redefine them)

```python
class SessionFocus(BaseModel):
    active_person: Optional[str]       # last-mentioned SCRB ID
    active_fir: Optional[str]          # last-mentioned FIR
    active_location: Optional[str]
    active_date_range: Optional[tuple]

class EvidenceItem(BaseModel):
    evidence_id: str
    source_type: Literal["FIR_RECORD", "CRIMINAL_RECORD", "GRAPH_RELATIONSHIP",
                          "COMMUNITY_SUMMARY", "ML_PREDICTION", "GEOSPATIAL_ANALYSIS"]
    source_id: str
    source_query: Optional[str]        # exact SQL/Cypher that produced this
    content: str
    confidence: float
    timestamp: datetime

class Citation(BaseModel):             # suggested shape — refine against actual frontend needs
    index: int
    evidence_id: str
    label: str                          # e.g. "FIR/BLR/2024/KGF/001234 — Filed 12 Mar 2024, Kolar PS, IPC 302"

class AgentTraceEntry(BaseModel):      # suggested shape — this is what the Reasoning Trace panel renders
    step: str                           # e.g. "HippoRAG retrieval"
    detail: str                         # plain-language, e.g. "3 corroborating records found"
    duration_ms: Optional[int]
    confidence: Optional[float]

class InvestigationState(BaseModel):
    session_id: str; officer_id: str; officer_role: str
    original_query: str; language: Literal["en", "kn"]
    active_entities: SessionFocus
    decomposed_subqueries: List[str]
    evidence_items: List[EvidenceItem]
    graph_query_results: List[dict]; sql_query_results: List[dict]
    vector_search_results: List[dict]; prediction_results: Optional[dict]
    final_answer: Optional[str]; citations: List[Citation]
    confidence_score: float; requires_escalation: bool
    agent_trace: List[AgentTraceEntry]
```

`apps/api` calls `run_investigation(state: InvestigationState) -> InvestigationState` (one call per turn) and streams `agent_trace` entries to the frontend as they're appended.

## How a query gets answered

1. **Orchestrator** classifies intent, resolves pronouns/references against `SessionFocus` ("does **he** have priors" → look up `active_person`), updates `SessionFocus`, decomposes the query into subqueries, routes to specialist agents.
2. **Retrieval**:
   - **HippoRAG** (Gutiérrez et al., NeurIPS 2024) is the default path: extract query entities → seed **Personalized PageRank** (Neo4j GDS) over the knowledge graph → single-step multi-hop retrieval. ~10-20x cheaper than iterative retrieval.
   - **Think-on-Graph / ToG** (Sun et al., ICLR 2024) kicks in when HippoRAG's confidence is low or the query is explicitly multi-hop/relational (e.g. "how are these three gangs financially connected over the last year"): the LLM iteratively beam-searches entity/relation paths on the graph itself, producing a traceable reasoning path instead of trusting one generated Cypher query.
   - Louvain community summaries (Neo4j GDS) sit underneath both as the global-context layer.
3. **Specialist agents** run in parallel where possible: Cypher Agent (NL→Cypher, validated via `EXPLAIN` before execution), SQL Agent (text-to-SQL against the `data/` schema), Vector Search Agent (hybrid dense+BM25, RRF fusion), Geospatial Agent (PostGIS), Prediction Agent (calls `packages/ml_models` typed functions — never predicts inline), Translation Agent (IndicTrans2), Voice Agent (ASR/TTS).
4. **Evidence Evaluator** — CRAG-style (Yan et al., 2024): scores each retrieval batch for relevance/confidence and triggers one of: **accept** → **widen query and retry** → explicitly answer **"not found in available records."** Never fabricates on empty evidence — this is the single most important trust guarantee in the whole system.
5. **Evidence Synthesis Agent** produces `final_answer` + ordered `citations`, each traceable to an `EvidenceItem`.

## Investigation Copilot

Given an open FIR, generate:
1. Chronological timeline (every linked event: arrest, bail, court date, in order).
2. Top-5 MO-similar past cases, each with its recorded outcome (vector similarity over MO embeddings).
3. Ranked investigative leads (e.g. "matches Community 47; 3 associates in adjoining districts").
4. Draft case-summary paragraph the IO can paste into a diary entry.

## Suggested structure
```
packages/rag_agent/
  state.py             # InvestigationState, SessionFocus, EvidenceItem, Citation, AgentTraceEntry
  orchestrator.py       # intent routing, session-focus resolution, query decomposition
  retrieval/
    hipporag.py          # personalized PageRank retrieval
    tog.py                # beam-search deep-dive
  agents/
    cypher_agent.py, sql_agent.py, vector_agent.py, geo_agent.py,
    prediction_agent.py, synthesis_agent.py, translation_agent.py, voice_agent.py
  evidence/
    evaluator.py          # CRAG-style scoring/escalation
  copilot/
    timeline.py, similar_cases.py, leads.py, summary_draft.py
```

## Provides / Consumes
- **Provides to `apps/api`**: `run_investigation(state) -> InvestigationState`.
- **Consumes from `packages/ml_models`**: `score_risk`, `predict_recidivism`, `forecast_crime`, `detect_hotspots`, `flag_transactions`, `resolve_entities` (exact signatures in that package's README) — via the Prediction Agent only.
- **Consumes from `data/`**: Postgres session (`data.db.get_session()`), Neo4j driver (`data.graph.get_driver()`), vector store client — never opens its own connection.

## Non-goals
- No UI rendering, no auth/RBAC decisions (trusts `officer_role` as given by `apps/api`), no schema definitions, no ML model training — this package calls `ml_models`, it doesn't contain them.
