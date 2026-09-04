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
  /** The ENGINE's own answer to "did this turn refuse" — a first-class product
   *  state, not an error. Never derived from citations.length: a capability
   *  answer and a successful board confirmation both carry zero citations
   *  without being refusals. */
  refused: boolean;
  /** The turn did not complete at all — transport died, or the engine sent an
   *  `error` frame. Distinct from `refused`: a refusal is the system working
   *  correctly and declining to guess; this is the system failing, and the two
   *  must not look the same on screen. */
  failed?: boolean;
  /** Demonstration/unverified sign-in (LoginGate.enterUnverified) carries no
   *  token by design, so every record-scoped question is refused before the
   *  request is even sent — this is neither a CRAG refusal (the records were
   *  checked and don't support a claim) nor a transport failure (the engine
   *  broke). It is the console correctly declining to pretend to be signed in. */
  unauthenticated?: boolean;
  trace: TraceEntry[];
  citations: Citation[];
  evidence: EvidenceItem[];
  visualization: Visualization;
  focus?: SessionFocusView;
};

// No personal name — the console identifies an officer by rank and station only.
export type Officer = { badge_no: string; role: string; ps_code: string };

/** One entry in the pooled chat-history list — GET /sessions. Pooled by
 *  rank+station, never by individual officer (see lib/types.ts's Officer). */
export type SessionSummary = { session_id: string; updated_at: string; label: string };

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

/** One case in full, as `GET /fir/{id}` returns it. Names are already masked by
 *  the officer's rank server-side — this type is what reached the browser, not
 *  what exists in the record. */
export type CaseDetail = {
  fir_id: string;
  fir_number: string;
  ps_code: string;
  district: string;
  taluk?: string;
  crime_type: string;
  date_filed: string;
  case_status: string;
  modus_operandi?: string | null;
  narrative?: string | null;
  accused: { AccusedName: string | null; AgeYear: number | null; PersonUID: string | number | null }[];
  victims: { VictimName: string | null; AgeYear: number | null }[];
  sections: { ActID: string | number; SectionID: string | number }[];
  [k: string]: any;
};

/** A person reconstructed from Accused rows by probabilistic record linkage.
 *  `name_en` is the CANONICAL name — not necessarily the one on any one FIR. */
export type PersonDetail = {
  person_id: string;
  name_en: string | null;
  name_kn: string | null;
  criminal_history: boolean;
  community: number | null;
  cases: { fir_id: string; fir_number: string; date_filed: string; ps_code: string }[];
  [k: string]: any;
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

/* ---------------------------------------------------------------------------
 * "Why is this here?" — GET /explain. Mirrors provenance.Derivation.
 *
 * Four bases, not three: `prediction` is split out from `model` because a forecast
 * describes something that has NOT happened, which is a different kind of claim from
 * a hotspot describing where crime was recorded. The console's evidence rail keeps
 * the three-way record/derived/model split it already has (a forecast still renders
 * as MODEL there); this is the one surface where the distinction is worth a word.
 * ------------------------------------------------------------------------- */
export type DerivationBasis = "record" | "derived" | "model" | "prediction";

export type SourceRecord = {
  label: string;
  detail: string;
  evidence_id: string | null;
};

export type Derivation = {
  evidence_id: string;
  /** What is being asserted — the CLAIM, not the component that produced it. */
  claim: string;
  basis: DerivationBasis;
  basis_meaning: string;
  /** The specific records underneath it, by their real identifiers. */
  records: SourceRecord[];
  /** The derivation, one step per line, in the order the reasoning actually ran. */
  steps: string[];
  /** Why this one made the cut — a threshold, a hop limit, a filter, a rank. */
  qualifies: string;
  /** What this result does NOT establish. */
  caveat: string | null;
  /** Questions the engine can actually answer next about this exact thing. */
  next_questions: string[];
  /** The chain could not be reconstructed, and this is saying so. */
  incomplete: boolean;
};

/** One ranked hit from GET /search. `why` is the list of fields that actually
 *  matched — a result list whose ordering cannot be explained is one an officer
 *  learns to distrust, and "matched: crime, district" is the whole explanation. */
export type SearchHit = {
  kind: "case" | "person";
  id: string;
  /** What it IS — the crime type, or the person's name. */
  title: string;
  /** Where or what kind — district, station, status; or how many cases. */
  subtitle: string;
  /** The identifier, set in mono and placed last. */
  ident: string;
  why: string[];
  score: number;
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

export type SeriesMember = {
  fir_id: string;
  fir_number: string | null;
  ps_code: string;
  ps_name: string | null;
  district: string | null;
  date_filed: string | null;
  case_status: string | null;
  matched_features: string[];
  similarity: number;
};

/** A cross-station series discovery (rag_agent.series_detection), pushed through
 *  the same /alerts stream as AnomalyAlert. Unlike a district-anomaly alert this
 *  is case-scoped: the "case" pane surfaces it, not a district. */
export type SeriesAlert = {
  anchor_fir_id: string;
  anchor_ps_code: string;
  members: SeriesMember[];
  stations: string[];
  districts: string[];
};
