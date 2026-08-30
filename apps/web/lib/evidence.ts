import type { EvidenceItem } from "./types";

/* ============================================================================
 * EVIDENCE SEMANTICS
 *
 * The console's strongest claim is that it never lets a model's guess look like
 * a fact in a case file. That claim has to be a visual primitive, not a
 * sentence in the answer text — so every evidence item, board item and timeline
 * event is classified here, once, and every surface renders the result the same
 * way (see `.prov-*` / `.rail-*` in globals.css).
 *
 * Four kinds, and the boundary between them is where the fact came from:
 *
 *   record   Stated in the case file. The ER's own columns.
 *   derived  This system inferred it FROM records. A co-offending edge rests on
 *            Fellegi-Sunter's probabilistic identity match, and a "network
 *            community" is Louvain's output over that graph — both are real
 *            findings, and neither is written down anywhere in the FIR.
 *   model    A model computed it: a risk score, a hotspot density, a forecast.
 *   human    An officer typed it. Never a database fact.
 * ========================================================================== */

export type Provenance = "record" | "derived" | "model" | "human";

const BY_SOURCE: Record<EvidenceItem["source_type"], Provenance> = {
  FIR_RECORD: "record",
  CRIMINAL_RECORD: "record",
  GRAPH_RELATIONSHIP: "derived",
  COMMUNITY_SUMMARY: "derived",
  ML_PREDICTION: "model",
  GEOSPATIAL_ANALYSIS: "model",
};

export function provenanceOf(e: EvidenceItem): Provenance {
  return BY_SOURCE[e.source_type] ?? "record";
}

export const PROV_LABEL: Record<Provenance, string> = {
  record: "Record",
  derived: "Derived",
  model: "Model",
  human: "Note",
};

/** What the badge means, spelled out. Shown on hover and in the inspector — the
 *  officer must never have to learn a colour code to read a provenance. */
export const PROV_MEANING: Record<Provenance, string> = {
  record: "Stated directly in the case records.",
  derived: "Inferred by Veritas from the records — not written in any one of them.",
  model: "Computed by a model. Decision support, not a recorded fact.",
  human: "Written by an investigator. Not a database fact.",
};

/** The human-readable name of the record type, for the inspector's SOURCE field.
 *  Spelled out rather than de-cased from the enum: sentence-casing FIR_RECORD
 *  produced "Fir record", which reads as a typo in the one place an officer is
 *  checking whether a source is what it claims to be. */
const SOURCE_LABEL: Record<EvidenceItem["source_type"], string> = {
  FIR_RECORD: "FIR record",
  CRIMINAL_RECORD: "Criminal record",
  GRAPH_RELATIONSHIP: "Relationship between people",
  COMMUNITY_SUMMARY: "Network community",
  ML_PREDICTION: "Model prediction",
  GEOSPATIAL_ANALYSIS: "Geospatial analysis",
};

export function sourceLabel(e: EvidenceItem): string {
  return SOURCE_LABEL[e.source_type] ?? e.source_type.replace(/_/g, " ").toLowerCase();
}

/** The case a piece of evidence is about, when it is about one.
 *
 *  The same FIR reaches the console under two evidence_id shapes depending on which
 *  retriever found it: `fir:1194` from the structured layer, `vec:fir_narrative:1194`
 *  from semantic search. Both name case 1194. Anything that joins evidence to a case
 *  has to read both, and the map is where not doing so was visible: on a hotspot
 *  answer every cited case arrives as `vec:fir_narrative:…`, so selecting one lit up
 *  no point on the map and opened no case panel — the console silently behaving as
 *  though the case it had just cited were not on the map in front of it.
 *
 *  `criminal_profile` and `community_summary` hits are about a PERSON and a
 *  COMMUNITY; they deliberately return null rather than being coerced into a case. */
export function caseIdOf(evidenceId: string | null | undefined): string | null {
  if (!evidenceId) return null;
  const fir = /^fir:(\d+)$/.exec(evidenceId);
  if (fir) return fir[1];
  const vec = /^vec:fir_narrative:(\d+)$/.exec(evidenceId);
  return vec ? vec[1] : null;
}

/* ---------------------------------------------------------------------------
 * Confidence is three different measurements wearing one word, and showing them
 * identically is how "72% text similarity" ends up looking as authoritative as
 * "100% evidence support". Each kind gets its own name, and only the kinds that
 * mean "how well corroborated" are allowed to drive the support summary.
 * ------------------------------------------------------------------------- */

export type ConfKind = EvidenceItem["confidence_kind"];

export const CONF_NAME: Record<ConfKind, string> = {
  support: "Evidence support",
  similarity: "Text match",
  model_estimate: "Model output",
};

export const CONF_MEANING: Record<ConfKind, string> = {
  support: "How well the records corroborate this claim.",
  similarity: "How closely the wording matches — not how true the claim is.",
  model_estimate: "The model's own figure, already stated in the text.",
};

export type Band = "strong" | "fair" | "weak";

export function band(confidence: number): Band {
  if (confidence >= 0.75) return "strong";
  if (confidence >= 0.45) return "fair";
  return "weak";
}

/** Whether a percentage belongs on screen at all for this item.
 *
 *  A "model_estimate" item already carries its real number in the body text
 *  ("risk score of 0.62, calibrated"). A second percentage under a different
 *  meaning is just a second unlabeled number next to the first. */
export function showsPercent(kind: ConfKind): boolean {
  return kind !== "model_estimate";
}

export type Support = {
  total: number;
  authoritative: number;   // record-backed items
  corroborating: number;   // derived items that agree
  modelled: number;        // model outputs
  verdict: "None" | "Weak" | "Moderate" | "Strong";
  band: Band;
  /** 0-4, for the four-segment strength bar. */
  steps: number;
};

/** The support summary the officer reads instead of a wall of percentages.
 *
 *  Deliberately counts SOURCES, not an average of scores: "3 authoritative
 *  records, 2 corroborating" is a checkable statement about the evidence set.
 *  An averaged percentage over items measuring different things is not.
 *
 *  Only `support`-kind confidences influence the verdict. A high text-match
 *  score means the retrieval found similar wording; it is not evidence that the
 *  claim is true, so it must not be able to promote a weak answer to a strong
 *  one. */
export function summarise(items: EvidenceItem[]): Support {
  const authoritative = items.filter((e) => provenanceOf(e) === "record").length;
  const corroborating = items.filter((e) => provenanceOf(e) === "derived").length;
  const modelled = items.filter((e) => provenanceOf(e) === "model").length;

  const supportScores = items.filter((e) => e.confidence_kind === "support").map((e) => e.confidence);
  const best = supportScores.length ? Math.max(...supportScores) : 0;

  // A claim resting on named records is stronger than the same claim resting on
  // one inferred edge, however confident that edge is.
  let steps = 0;
  if (items.length) steps = 1;
  if (authoritative >= 1 || best >= 0.75) steps = 2;
  if (authoritative >= 2 && best >= 0.6) steps = 3;
  if (authoritative >= 3 && best >= 0.75) steps = 4;
  if (!authoritative && corroborating >= 3 && best >= 0.75) steps = Math.max(steps, 3);

  const verdict = (["None", "Weak", "Moderate", "Moderate", "Strong"] as const)[steps];
  const b: Band = steps >= 4 ? "strong" : steps >= 2 ? "fair" : "weak";

  return { total: items.length, authoritative, corroborating, modelled, verdict, band: b, steps };
}
