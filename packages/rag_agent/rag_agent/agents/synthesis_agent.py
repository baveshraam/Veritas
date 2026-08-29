"""Evidence Synthesis — final answer, citations, and the visualization payload.

Citations are built from the evidence FIRST, and the answer is written against that
numbered list. It never works the other way round: an answer is not generated and
then decorated with whichever citations look plausible, because that is exactly how
a citation ends up not supporting the sentence it is attached to.

With an LLM the prose is fluent; without one it is extractive. Both are grounded in
the same evidence and carry the same citations — the LLM changes the register of the
answer, never its factual content.

## Routing: QuickML only where a narrative adds something the list doesn't already say

Live-measured (2026-08-28): calling the LLM for EVERY answer — including a plain FIR
status lookup or a crime count with sample FIRs — cost 20-30s regardless of how simple
the underlying fact was, because the extractive template already says exactly what the
records say for those operations; a rephrasing buys nothing. `synthesize()` now takes
the resolved `operation` and only calls QuickML when it's in
`intents.NEEDS_NARRATIVE_SYNTHESIS` — a financial trail's "what stands out", a
network's "who's connected and how", a risk score's "why", a two-entity comparison's
"here's how these differ". This is the same principle `semantic_interpreter.interpret()`
already applies to routing the model for *understanding* a query, now applied to
whether it's worth calling for *phrasing* the answer — never a correctness trade-off,
since the extractive path is always fully grounded in the same evidence either way.
"""
from .. import intents
from ..evidence.evaluator import NOT_FOUND_MESSAGE
from ..llm import available, generate
from ..state import Citation, EvidenceItem, VisualizationPayload

_SYSTEM = (
    "You are an investigative assistant for the Karnataka State Police. Answer ONLY "
    "from the numbered evidence provided. Cite every factual claim with its [n]. "
    "If the evidence does not support a claim, do not make it. Be concise and precise. "
    "Never speculate about guilt; describe what the records show. "
    # The console renders answers as plain text (white-space: pre-wrap) — markdown
    # would show up as literal asterisks and hashes.
    "Write plain prose only: no markdown, no **bold**, no bullet characters, no headers."
)


def build_citations(evidence: list[EvidenceItem]) -> list[Citation]:
    """1-based, in evidence order — matches the [1] FIR/... render convention."""
    return [
        Citation(index=i, evidence_id=e.evidence_id, label=_label(e))
        for i, e in enumerate(evidence, start=1)
    ]


def _label(e: EvidenceItem) -> str:
    head = e.content.strip().split("\n")[0]
    return head[:120] + ("…" if len(head) > 120 else "")


def synthesize(query: str, evidence: list[EvidenceItem],
                operation: str = "") -> tuple[str, list[Citation]]:
    if not evidence:
        return NOT_FOUND_MESSAGE, []

    citations = build_citations(evidence)
    numbered = "\n".join(f"[{c.index}] {e.content}" for c, e in zip(citations, evidence))

    if operation in intents.NEEDS_NARRATIVE_SYNTHESIS and available():
        try:
            answer = generate(
                f"Question: {query}\n\nEvidence:\n{numbered}\n\n"
                f"Answer the question using only this evidence, citing [n] inline.",
                system=_SYSTEM,
            )
            if answer:
                return answer, citations
        except Exception:
            pass      # fall through to extractive synthesis — never fail the turn
    return _extractive(query, evidence, citations), citations


def _extractive(query: str, evidence: list[EvidenceItem], citations: list[Citation]) -> str:
    """Deterministic, fully-grounded answer: state what each record says, cite it."""
    lines = [f"Based on {len(evidence)} record(s) in the system:"]
    for c, e in zip(citations, evidence):
        lines.append(f"  [{c.index}] {e.content}")
    lines.append("")
    lines.append("Every statement above is drawn directly from the cited records; "
                 "no inference has been added.")
    return "\n".join(lines)


# --- visualization -----------------------------------------------------------

def build_visualization(intent: str, state) -> VisualizationPayload:
    """Shape depends on the kind — see packages/rag_agent/README.md."""
    from ..intents import visualization_for

    kind = visualization_for(intent)

    if kind == "network" and state.graph_query_results:
        nodes, edges, seen = [], [], set()
        root = state.active_entities.active_person
        if root:
            # 1.0 is a display-sizing sentinel (the subject renders largest), not a
            # real PageRank score — the field is real graph centrality for every
            # other node, and was named "risk_score" here, which is a different
            # concept the network view never actually measures (see BUG-011).
            nodes.append({"id": root, "label": "subject", "pagerank": 1.0})
            seen.add(root)
        for r in state.graph_query_results:
            pid = r.get("person_id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            nodes.append({"id": pid, "label": r.get("name_en") or pid,
                          "pagerank": float(r.get("pagerank") or 0.0)})
            if root:
                edges.append({"source": root, "target": pid,
                              "type": "CO_ACCUSED_WITH",
                              "strength": 1.0 / max(1, int(r.get("hops") or 1))})
        if nodes:
            return VisualizationPayload(kind="network", data={"nodes": nodes, "edges": edges})

    if kind == "sankey" and state.graph_query_results:
        names, links = [], []
        for r in state.graph_query_results:
            src, dst = r.get("from_account"), r.get("to_account")
            if not src or not dst:
                continue
            for a in (src, dst):
                if a not in names:
                    names.append(a)
            links.append({"source": src, "target": dst,
                          "value": float(r.get("amount") or 0.0)})
        if links:
            return VisualizationPayload(
                kind="sankey",
                data={"nodes": [{"name": n} for n in names], "links": links})

    if kind == "map":
        hotspots = state.prediction_results.get("detect_hotspots") or []
        polygons = [h.model_dump() if hasattr(h, "model_dump") else h for h in hotspots]
        points = [{"lat": r["lat"], "lng": r["lng"], "fir_id": r["fir_id"],
                   "crime_no": r.get("crime_no"), "filed": r.get("filed"),
                   "crime_type": r.get("crime_type"), "district": r.get("district")}
                  for r in state.sql_query_results
                  if r.get("lat") is not None and r.get("lng") is not None]
        if polygons or points:
            return VisualizationPayload(kind="map",
                                        data={"polygons": polygons, "fir_points": points})

    if kind == "timeline":
        t = state.prediction_results.get("timeline")
        if t:
            return VisualizationPayload(kind="timeline", data=t)

    if kind == "trend":
        fc = state.prediction_results.get("forecast_crime")
        if fc is not None:
            series = [[str(d), p, lo, hi] for d, p, lo, hi in fc.series]
            if series:
                return VisualizationPayload(kind="trend", data={"series": series})

    return VisualizationPayload(kind="none", data={})
