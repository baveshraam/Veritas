/* Wire contract — mirrors apps/api's SSE envelope and the shapes canonically
 * defined in packages/rag_agent. Treat as append-only: add fields freely, never
 * rename or remove without telling the backend. */

export type Citation = { index: number; evidence_id: string; label: string };

export type EvidenceItem = {
  evidence_id: string;
  source_type:
    | "FIR_RECORD" | "CRIMINAL_RECORD" | "GRAPH_RELATIONSHIP"
    | "COMMUNITY_SUMMARY" | "ML_PREDICTION" | "GEOSPATIAL_ANALYSIS";
  source_id: string;
  source_query: string | null;
  content: string;
  confidence: number;
  confidence_kind: "support" | "similarity" | "model_estimate";
  timestamp: string;
};

export type TraceEntry = {
  step: string;
  detail: string;
  duration_ms: number | null;
  confidence: number | null;
};

export type VizKind = "map" | "network" | "sankey" | "trend" | "timeline" | "none";
export type Visualization = { kind: VizKind; data: any };

export type TimelineEvent = {
  date: string;
  entity_type: "case" | "person" | "transaction";
  entity_id: string | null;
  entity_name: string | null;
  event_type: string;
  description: string;
  // "authoritative": a directly stated ER/vx_ fact. "derived": a relationship this
  // system inferred (currently only a person's OTHER cases, linked by Fellegi-
  // Sunter's probabilistic identity match, not a directly stated fact) — never
  // render the two the same way.
  kind: "authoritative" | "derived";
  ref_type: string | null;
  ref_id: string | null;
  source_query: string | null;
};

export type TimelineEntity = { entity_type: string; entity_id: string; entity_name: string };

export type TimelineConnection = {
  person_a: { id: string; name: string };
  person_b: { id: string; name: string };
  direct: { type: string; kind: string; description: string }[];
  has_direct_connection: boolean;
};

export type TimelineResult = {
  anchor: "case" | "person" | "connection";
  fir_id?: string;
  fir_number?: string;
  person_id?: string;
  name?: string;
  entities: TimelineEntity[];
  events: TimelineEvent[];
  total: number;
  connection?: TimelineConnection;
};

export type FinalEvent = {
  type: "final";
  final_answer: string;
  citations: Citation[];
  evidence_items: EvidenceItem[];
  visualization: Visualization;
  // The engine's own true/false answer to "did this turn refuse" — NOT derivable
  // from citations.length alone (a CAPABILITY answer or a successful board
  // confirmation also carries zero citations without being a refusal).
  refused: boolean;
  // What the SESSION is about after this turn — the case and/or person the engine
  // resolved against. Names are already masked by the officer's rank server-side.
  focus?: SessionFocusView;
};

/** The standing answer to "which case / which person am I in", which a multi-turn
 *  conversation is unreadable without: "does she have priors?" answers about
 *  somebody, and until this existed the only place that said who was the reasoning
 *  trace's "resolved 'X'" line, collapsed by default. */
export type SessionFocusView = {
  case?: { fir_id: string; fir_number?: string; district?: string; crime_type?: string };
  person?: { person_id: string; name?: string };
};

export type Turn = {
  id: string;
  query: string;
  answer: string;
  streaming: boolean;
  refused: boolean;
  trace: TraceEntry[];
  citations: Citation[];
  evidence: EvidenceItem[];
  visualization: Visualization;
  focus?: SessionFocusView;
};

export type Officer = { badge_no: string; name: string; role: string; ps_code: string };

export type CopilotBrief = {
  fir_id: string;
  timeline: Record<string, any>[];
  similar_cases: Record<string, any>[];
  leads: string[];
  draft_summary: string;
};

export type CaseRow = {
  fir_id: string;
  fir_number: string;
  ps_code: string;
  district: string;
  taluk: string;
  crime_type: string;
  ipc_sections: string[];
  date_filed: string;
  case_status: string;
  modus_operandi: string | null;
};

export type Facet = { name: string; count: number };

export type CaseIndex = {
  cases: CaseRow[];
  matched: number;      // rows matching the current filter
  total: number;        // rows this officer can see at all
  crime_types: Facet[];
  statuses: Facet[];
};

export type BoardItemType = "evidence" | "person" | "lead" | "note" | "question" | "finding";

export type BoardItem = {
  item_id: string;
  case_id: string;
  item_type: BoardItemType;
  ref_type: string | null;
  ref_id: string | null;
  content: string;
  confidence: number | null;
  source_query: string | null;
  status: string | null;
  reason: string | null;
  created_by: string | null;
  created_at: string;
  updated_by: string | null;
  updated_at: string | null;
};

export type CaseBoard = {
  fir_id: string;
  fir_number: string;
  crime_type: string | null;
  district: string | null;
  case_status: string | null;
  items: BoardItem[];
  by_type: Record<BoardItemType, BoardItem[]>;
  total: number;
};

export type AnomalyAlert = {
  alert_id: string;
  district_code: string;
  metric: string;
  observed: number;
  expected: number;
  severity: "low" | "medium" | "high";
  detected_at: string;
};
