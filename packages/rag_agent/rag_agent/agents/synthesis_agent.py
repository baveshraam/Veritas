"""Evidence Synthesis — final answer, citations, and the visualization payload.

Citations are built from the evidence FIRST, and the answer is written against that
numbered list. It never works the other way round: an answer is not generated and
then decorated with whichever citations look plausible, because that is exactly how
a citation ends up not supporting the sentence it is attached to.

With an LLM the prose is fluent; without one it is extractive. Both are grounded in
the same evidence and carry the same citations — the LLM changes the register of the
answer, never its factual content.
"""
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


def synthesize(query: str, evidence: list[EvidenceItem]) -> tuple[str, list[Citation]]:
    if not evidence:
        return NOT_FOUND_MESSAGE, []

    citations = build_citations(evidence)
    numbered = "\n".join(f"[{c.index}] {e.content}" for c, e in zip(citations, evidence))

    if available():
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
            nodes.append({"id": root, "label": "subject", "risk_score": 1.0})
            seen.add(root)
        for r in state.graph_query_results:
            pid = r.get("person_id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            nodes.append({"id": pid, "label": r.get("name_en") or pid,
                          "risk_score": float(r.get("pagerank") or 0.0)})
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
        points = [{"lat": r["lat"], "lng": r["lng"], "fir_id": r["fir_id"]}
                  for r in state.sql_query_results
                  if r.get("lat") is not None and r.get("lng") is not None]
        if polygons or points:
            return VisualizationPayload(kind="map",
                                        data={"polygons": polygons, "fir_points": points})

    if kind == "trend":
        fc = state.prediction_results.get("forecast_crime")
        if fc is not None:
            series = [[str(d), p, lo, hi] for d, p, lo, hi in fc.series]
            if series:
                return VisualizationPayload(kind="trend", data={"series": series})

    return VisualizationPayload(kind="none", data={})
