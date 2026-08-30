import type { EvidenceItem, Visualization } from "./types";

/* ============================================================================
 * READING A NETWORK ANSWER
 *
 * The defect this exists to fix: an answer says "two people are accused in this
 * FIR" and the graph beside it draws forty. Both are true and the officer has
 * no way to know that. They are looking at two different populations — the
 * people named in the case file, and the people reachable from them through
 * shared cases — and nothing on screen said so.
 *
 * Everything below is derived from data the payload already carries. Nothing is
 * fetched, nothing is guessed:
 *
 *   DIRECT     evidence items with an `accused:<PersonUID>` id are the case's
 *              own accused, straight out of the record. Where the question was
 *              about a person rather than a case there are none, and a one-hop
 *              edge (the engine encodes strength as 1/hops) is the equivalent:
 *              somebody who has actually offended alongside the subject.
 *
 *   EXTENDED   every other node — reached through a chain of shared cases, not
 *              named in this file. A real finding, and NOT an accusation, which
 *              is why it is counted and labelled separately rather than folded
 *              into one number.
 * ========================================================================== */

export type NetworkNode = { id: string; label: string; pagerank: number };
export type NetworkEdge = { source: string; target: string; type: string; strength: number };

export type Connection = {
  id: string;
  name: string;
  /** In the front group: named in the case file, or a direct co-offender. */
  direct: boolean;
  /** Steps through shared cases to reach them from the subject. */
  hops: number;
  pagerank: number;
  /** 0-1 against the strongest MEASURED centrality in the graph. */
  normalised: number;
};

/** WHY the front group is the front group, which decides what it may be called.
 *  "record" — the case file names these people. "co-offending" — the file names
 *  nobody (the question was about a person), so the front group is everyone who
 *  has actually offended alongside the subject. That is a DERIVED finding and
 *  must never be captioned as something the records state. */
export type DirectBasis = "record" | "co-offending";

export type NetworkReading = {
  subjectId: string | null;
  subjectName: string | null;
  basis: DirectBasis;
  direct: Connection[];
  extended: Connection[];
  total: number;
  edges: number;
  communities: number;
  /** True when the graph holds people the answer text never named — the exact
   *  case an officer needs the layering explained for. */
  needsExplanation: boolean;
};

/** The root node is identified by its label, which the engine sets to the
 *  literal placeholder string "subject" and never to anything else
 *  (synthesis_agent.py — every other node's label is a real name or a bare
 *  person id, never that exact string). That check alone is authoritative.
 *
 *  A `pagerank >= 1` fallback used to sit here too, and it is what turned a
 *  real bug into a much worse one: a corrupted PageRank column (a Data Store
 *  scientific-notation defect, since fixed — see CLAUDE.md changelog v22)
 *  pushed several real associates' pagerank above 1, so EVERY one of them
 *  matched "is the root" and rendered with the subject's own name and size.
 *  The label check was never the problem; a numeric heuristic standing in for
 *  an identity check was. Removed rather than re-guarded, because the same
 *  failure mode returns the moment anything upstream — a future data bug, a
 *  differently-scaled centrality metric — produces one real node with
 *  pagerank >= 1. */
export const isRoot = (n: NetworkNode) => n.label === "subject";

export function readNetwork(
  viz: Visualization,
  evidence: EvidenceItem[],
  subjectName?: string | null,
): NetworkReading | null {
  if (viz?.kind !== "network") return null;
  const nodes: NetworkNode[] = viz.data?.nodes ?? [];
  const edges: NetworkEdge[] = viz.data?.edges ?? [];
  if (!nodes.length) return null;

  const root = nodes.find(isRoot) ?? null;
  const others = nodes.filter((n) => !isRoot(n));

  // The case's own accused, as cited. Ids are `accused:<PersonUID>`, and the
  // node ids ARE PersonUIDs, so this joins without a lookup.
  const namedInCase = new Set(
    evidence
      .filter((e) => e.evidence_id.startsWith("accused:"))
      .map((e) => e.evidence_id.slice("accused:".length)),
  );

  // Node ids arrive as NUMBERS from the engine (`{"id": 803}`) while an
  // evidence id is the string "accused:803". Comparing them raw silently
  // matched nothing, so the two people the case file actually named rendered as
  // "reached through shared cases" — the exact misattribution this module
  // exists to prevent. Everything below joins on the string form.
  const key = (v: unknown) => String(v);

  const hopsTo = new Map<string, number>();
  for (const e of edges) {
    const rootKey = root ? key(root.id) : null;
    const other = key(e.source) === rootKey ? key(e.target)
                : key(e.target) === rootKey ? key(e.source)
                : null;
    if (!other) continue;
    // The engine encodes strength as 1 / hops; invert it back.
    const h = e.strength > 0 ? Math.max(1, Math.round(1 / e.strength)) : 1;
    hopsTo.set(other, Math.min(hopsTo.get(other) ?? h, h));
  }

  const measured = others.map((n) => n.pagerank ?? 0);
  const max = Math.max(1e-9, ...(measured.length ? measured : [1]));

  const basis: DirectBasis = namedInCase.size ? "record" : "co-offending";

  const all: Connection[] = others.map((n) => {
    const id = key(n.id);
    const hops = hopsTo.get(id) ?? (basis === "record" ? 1 : 2);
    return {
      id,
      name: n.label,
      direct: basis === "record" ? namedInCase.has(id) : hops <= 1,
      hops,
      pagerank: n.pagerank ?? 0,
      normalised: Math.min(1, (n.pagerank ?? 0) / max),
    };
  });

  const byInfluence = (a: Connection, b: Connection) => b.pagerank - a.pagerank;
  const direct = all.filter((c) => c.direct).sort(byInfluence);
  const extended = all.filter((c) => !c.direct).sort(byInfluence);

  const communities = new Set(
    nodes.map((n: any) => n.community).filter((c) => c != null),
  ).size;

  return {
    subjectId: root ? key(root.id) : null,
    subjectName: subjectName ?? (root && !isRoot(root) ? root.label : null),
    basis,
    direct,
    extended,
    total: all.length,
    edges: edges.length,
    communities,
    needsExplanation: extended.length > 0,
  };
}
