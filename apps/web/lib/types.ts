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
  timestamp: string;
};

export type TraceEntry = {
  step: string;
  detail: string;
  duration_ms: number | null;
  confidence: number | null;
};

export type VizKind = "map" | "network" | "sankey" | "trend" | "none";
export type Visualization = { kind: VizKind; data: any };

export type FinalEvent = {
  type: "final";
  final_answer: string;
  citations: Citation[];
  evidence_items: EvidenceItem[];
  visualization: Visualization;
};

export type Turn = {
  id: string;
  query: string;
  answer: string;
  streaming: boolean;
  trace: TraceEntry[];
  citations: Citation[];
  evidence: EvidenceItem[];
  visualization: Visualization;
};

export type Officer = { badge_no: string; name: string; role: string; ps_code: string };

export type CopilotBrief = {
  fir_id: string;
  timeline: Record<string, any>[];
  similar_cases: Record<string, any>[];
  leads: string[];
  draft_summary: string;
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
