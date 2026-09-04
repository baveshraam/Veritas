"""Why is this here? — the provenance chain behind ONE result.

## The problem this exists to solve

An investigator can already see *what* Veritas found and *which* records it cited.
What they could not do was point at a single line of an answer — one associate, one
similar case, one hotspot, one timeline event — and ask **"why is this one here?"**
and get an answer about the CLAIM rather than about the software.

The one place that question was already answered, `orchestrator._reasoning_explanation`,
answered it by restating the agent trace: *"HippoRAG retrieval: Personalized PageRank
from 15 seeded nodes; Cypher Agent: 12 associate(s) within policy depth"*. Every word
of that is true and none of it is what was asked. An officer does not care that
PageRank ran. They care that these two people are named on the same FIR.

## The shape of an answer

Every explanation is the same five things, in the same order, because that is the
order the question is actually asked in:

    CLAIM          what is being asserted
    BASIS          record / derived / model / prediction  (the console's own four)
    RECORDS        the specific records underneath it, by their real identifiers
    DERIVATION     how those records were combined to get here — in officer language
    QUALIFIES      why it made the cut, and what it does NOT mean

Dispatch is on the `evidence_id` prefix, which every producing branch in
`orchestrator.py` already writes to a fixed convention (`fir:`, `assoc:`, `same_as:`,
`flow:`, `hotspot:`, `forecast:`, `risk:`, `timeline:`, ...). That convention was
already load-bearing — `_fir_ids_from_turn`, `_recent_person_candidates` and
`_pin_evidence_from_context` all parse it — so this module reads what is already
there rather than adding a parallel channel that could drift out of step with it.

## Why the explanation is computed here, not stored on the item

An `EvidenceItem` is persisted into `vx_conversation_turn` on every turn, and the
Data Store's text column is already tight enough that `sessions._pack` sheds
`evidence_items` first when a turn is too big. A stored paragraph per item would make
that worse for a string most turns never ask for. Explanations are asked for rarely
and by a deliberate act (a click, or a typed "why is this one here"), so they are
derived on demand from the record layer — which also means an explanation can never
go stale against the records it describes.

## What it must never do

Invent a reason. Where the derivation genuinely is not reconstructable — an item
whose id follows no convention, a graph path that no longer exists — this says so.
"I retrieved this because the wording was similar and I cannot tell you more than
that" is a real answer; a plausible-sounding fabricated chain is the exact failure
this platform exists to prevent.
"""
from __future__ import annotations

import logging
from typing import Any, Literal, NamedTuple, Optional

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

Basis = Literal["record", "derived", "model", "prediction"]

# Mirrors apps/web/lib/evidence.ts's BY_SOURCE. Two copies is one too many, but the
# alternative is the console fetching a classification it can compute locally on
# every render — and the console's copy has to work for an item that never went
# through this module (a board item, a timeline event fetched over REST).
_BASIS_BY_SOURCE: dict[str, Basis] = {
    "FIR_RECORD": "record",
    "CRIMINAL_RECORD": "record",
    "GRAPH_RELATIONSHIP": "derived",
    "COMMUNITY_SUMMARY": "derived",
    "ML_PREDICTION": "model",
    "GEOSPATIAL_ANALYSIS": "model",
}

BASIS_MEANING: dict[Basis, str] = {
    "record": "Stated directly in the case records.",
    "derived": "Constructed by Veritas from records — not written down in any one of them.",
    "model": "Computed by an analytical model. Decision support, not a recorded fact.",
    "prediction": "A forecast about what has not happened yet. Never a record.",
}


class SourceRecord(BaseModel):
    """One record underneath a claim, named the way the paper file names it."""
    label: str                              # "FIR 100222201202600022"
    detail: str = ""                        # "Theft, Mandya, filed 30 Jun 2026"
    evidence_id: Optional[str] = None       # so the console can open it in turn


class Derivation(BaseModel):
    evidence_id: str
    claim: str
    basis: Basis
    basis_meaning: str
    records: list[SourceRecord] = Field(default_factory=list)
    # The derivation, one step per line, in the order the reasoning actually ran.
    steps: list[str] = Field(default_factory=list)
    # Why this one made the cut — a threshold, a hop limit, a filter, a rank.
    qualifies: str = ""
    # What this result does NOT establish. Present wherever the claim is easy to
    # over-read (a co-accusation is not joint guilt; a hotspot is not a prediction).
    caveat: Optional[str] = None
    # Questions the engine can actually answer next about this exact thing. Only
    # phrasings that route (see intents.py) — never an aspirational action.
    next_questions: list[str] = Field(default_factory=list)
    # True when the chain could not be reconstructed and this is saying so.
    incomplete: bool = False


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #

def _get(item: Any, key: str, default=None):
    """Evidence items reach here as EvidenceItem or as the plain dict a stored turn
    round-trips. One accessor rather than two code paths."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _fir_source(row: dict) -> SourceRecord:
    from .orchestrator import _fir_date
    bits = [x for x in (row.get("crime_type"), row.get("district")) if x]
    detail = ", ".join(bits)
    if row.get("date_filed"):
        detail += f", filed {_fir_date(row.get('date_filed'))}"
    if row.get("case_status"):
        detail += f" — status {row['case_status']}"
    return SourceRecord(label=f"FIR {row.get('fir_number') or row.get('fir_id')}",
                        detail=detail.strip(", "),
                        evidence_id=f"fir:{row['fir_id']}")


def _person_name(pid: str) -> str:
    from .agents import sql_agent
    try:
        return sql_agent.person_name(pid) or f"person {pid}"
    except Exception:
        return f"person {pid}"


def _graph():
    from data.graph import load_graph
    return load_graph()


def _shared_cases(g, a: str, b: str) -> list[str]:
    """The case nodes both people are ACCUSED_IN — which is precisely what a
    CO_ACCUSED_WITH edge is a summary of. Read back out of the graph rather than
    trusted from the edge weight, because the officer's question is *which* cases."""
    def cases(node: str) -> set[str]:
        if node not in g:
            return set()
        return {dst for _, dst, d in g.out_edges(node, data=True)
                if d.get("rel") == "ACCUSED_IN" and str(dst).startswith("case:")}
    return sorted(cases(a) & cases(b))


def _co_offending_path(g, subject_id: str, target_id: str) -> list[str]:
    """The shortest CO_ACCUSED_WITH chain from subject to target, as person nodes.

    This is the literal thing `person_network`'s `hops` column counts. Recomputing it
    here (rather than having the network query carry every path along) keeps the
    retrieval path unchanged for the overwhelming majority of turns that never ask
    why — and a path is cheap: the co-offending projection is already in memory."""
    import networkx as nx
    src, dst = f"person:{subject_id}", f"person:{target_id}"
    if src not in g or dst not in g:
        return []
    co = nx.Graph()
    for a, b, d in g.edges(data=True):
        if d.get("rel") == "CO_ACCUSED_WITH":
            co.add_edge(a, b)
    if src not in co or dst not in co:
        return []
    try:
        return nx.shortest_path(co, src, dst)
    except nx.NetworkXNoPath:
        return []


def _case_labels(case_nodes: list[str], role: str, ps: str) -> list[SourceRecord]:
    """Case nodes -> the case cards an officer recognises, policy-filtered.

    Filtered, not merely labelled: a graph path can legitimately run through a case
    at another station, and naming that case here would leak exactly what the IO
    station filter exists to withhold. The path itself is still reported — the hop
    is real — but the case behind it is named only where the officer may see it."""
    from .agents import sql_agent
    ids = [n.split(":", 1)[1] for n in case_nodes]
    if not ids:
        return []
    try:
        rows = sql_agent.filter_viewable(sql_agent.cases_by_ids(ids), role, ps)
    except Exception:
        return []
    return [_fir_source(r) for r in rows]


# --------------------------------------------------------------------------- #
# per-kind explanations                                                        #
# --------------------------------------------------------------------------- #

def _explain_associate(eid: str, item, subject_id: Optional[str],
                       role: str, ps: str) -> Derivation:
    """'Why is this person connected?' — the flagship.

    A co-offending edge is the single most consequential derived claim this platform
    makes: it is the thing that does not exist on the organizers' ER at all (CLAUDE.md
    §0), and the one an officer is most entitled to interrogate before acting on it.
    So the answer is the actual chain — which people, which FIRs — not the hop count
    the answer already printed."""
    target_id = eid.split(":", 1)[1]
    target = _person_name(target_id)
    d = Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim=f"{target} is connected to the person you asked about.",
        next_questions=[f"Does {target} have priors?",
                        f"Show me the timeline for {target}.",
                        f"Where did {target}'s money go?"],
        caveat=("Being named as accused on the same FIR is a recorded co-accusation. "
                "It is not a finding that either person is guilty, nor that they knew "
                "each other."),
    )
    if not subject_id:
        d.steps = ["This person came out of a co-offending search, but the subject it "
                   "was run from is no longer in view, so the connecting cases cannot "
                   "be named here."]
        d.incomplete = True
        return d

    g = _graph()
    path = _co_offending_path(g, subject_id, target_id)
    if not path:
        d.steps = ["The co-offending path between these two people could not be "
                   "reconstructed from the current graph."]
        d.incomplete = True
        return d

    d.claim = f"{_person_name(subject_id)} is connected to {target}."
    multi_hop = len(path) > 2
    for a, b in zip(path, path[1:]):
        a_id, b_id = a.split(":", 1)[1], b.split(":", 1)[1]
        shared = _shared_cases(g, a, b)
        cards = _case_labels(shared, role, ps)
        if cards:
            # The step sentence is written from the card's ORIGINAL detail, before
            # the multi-hop prefix below: the sentence already names the pair, so
            # prefixing first made it say so twice.
            named = "; ".join(f"{c.label} ({c.detail})" if c.detail else c.label
                              for c in cards)
            d.steps.append(f"{_person_name(a_id)} and {_person_name(b_id)} are both "
                           f"named as accused on {named}.")
            if multi_hop:
                # On a multi-hop path the record LIST is a pool of several different
                # pairs' cases, and printed flat it reads as "these nine FIRs connect
                # you to this person" — an over-claim, since the person at the far end
                # appears on only the last hop's cases. Found by clicking a 2-hop node
                # in the live console. Each row says which pair it links.
                for c in cards:
                    c.detail = (f"links {_person_name(a_id)} and {_person_name(b_id)}"
                                + (f" · {c.detail}" if c.detail else ""))
            d.records += cards
        elif shared:
            d.steps.append(f"{_person_name(a_id)} and {_person_name(b_id)} share "
                           f"{len(shared)} case(s) filed at a station outside your "
                           f"access scope — the link is real, the case cannot be named "
                           f"here.")
        else:
            d.steps.append(f"{_person_name(a_id)} and {_person_name(b_id)} are recorded "
                           f"as co-accused, but the shared case could not be read back.")
            d.incomplete = True

    hops = len(path) - 1
    d.steps.insert(0,
        "Each name here is a person reconstructed from Accused rows across cases — the "
        "records themselves have no cross-case person, so identity resolution matched "
        "those rows first.")
    d.qualifies = (
        f"{hops} step(s) of co-accusation away"
        + (" — a direct co-accused." if hops == 1 else
           " — reached through the people in between, not named alongside your subject "
           "on any single case.")
        + " Your rank allows co-accusation to be followed this far.")
    return d


def _explain_accused(eid: str, item, case_id: Optional[str], role: str, ps: str) -> Derivation:
    """'Why is this person on this case?' — the identity link, stated in both names.

    This is the one derived claim that reads as a record and is not: the file names
    "Suma Nadkarni D/o Eshwar" and every derived surface calls the same PersonUID
    "Soom Nadkarni", because 35% of Accused rows in this data are recorded under a
    romanisation variant. Naming only one of them is what made two names for one
    person look like a rendering bug (BUG-026); naming both, and saying which is
    which, is what makes the identity layer auditable rather than merely correct.
    """
    pid = eid.split(":", 1)[1]
    canonical = _person_name(pid)
    d = Derivation(
        evidence_id=eid, basis="record", basis_meaning=BASIS_MEANING["record"],
        claim=f"{canonical} is named as accused on this case.",
        steps=["The case file names this person in its own Accused rows — that part is "
               "stated, not inferred."],
        qualifies="Named in the file. The accusation is a record; nothing about it is "
                  "a model output.",
        next_questions=[f"Does {canonical} have priors?",
                        f"Who are {canonical}'s associates?",
                        f"Show me the timeline for {canonical}."])
    if not case_id:
        return d
    from .agents import sql_agent
    try:
        rows = sql_agent.fir_by_id(case_id, role, ps)
        accused = sql_agent.accused_on_case(case_id) if rows else []
    except Exception:
        rows, accused = [], []
    if rows:
        d.records = [_fir_source(rows[0])]
    filed = sorted({a["AccusedName"] for a in accused
                    if str(a["PersonUID"]) == str(pid) and a.get("AccusedName")})
    if filed:
        as_filed = "; ".join(f"'{n}'" for n in filed)
        d.steps.append(
            f"The file records the name {as_filed}. Veritas shows this person as "
            f"'{canonical}' throughout, which is a DERIVED canonical spelling — "
            f"identity resolution matched that Accused row to the same person as the "
            f"rows on their other cases.")
        if canonical and canonical not in filed:
            d.caveat = (f"'{canonical}' is not the spelling on this file. It is the "
                        f"canonical name identity resolution assigned, and the two "
                        f"refer to the same person only because that match is correct.")
    return d


def _explain_alias(eid: str, item, subject_id, role, ps) -> Derivation:
    pid = eid.split(":", 1)[1]
    if pid == "none":
        return Derivation(
            evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
            claim="No second name or spelling is recorded for this person.",
            steps=["Every Accused row matched to this person carries the same name "
                   "spelling, so there is no alias to report."],
            qualifies="This is a checked absence, not an unanswered question.",
            caveat="It means no OTHER spelling was matched to them — not that no other "
                   "spelling of their name exists anywhere.")
    from .agents import graph_agent
    d = Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim="These name spellings are the same person.",
        caveat="An identity match is a probabilistic judgement over names, dates and "
               "places — strong evidence, not a fingerprint.",
        next_questions=["Does this person have priors?",
                        "Who are this person's associates?"])
    try:
        rows = graph_agent.aliases(pid)
    except Exception:
        rows = []
    if rows:
        spellings = ", ".join(f"'{r['name_en']}' ({r['confidence']:.0%})" for r in rows)
        d.steps = [
            f"The records name this person under {len(rows)} different spellings: "
            f"{spellings}.",
            "Probabilistic record linkage (Fellegi-Sunter) compared those Accused rows "
            "on name, date of birth, address and case details, and judged them to be "
            "one individual.",
        ]
        d.qualifies = (f"Matched above the linkage threshold — "
                       f"{max(r['confidence'] for r in rows):.0%} on the strongest "
                       f"pairing. Measured F1 against the answer key: 0.989.")
    else:
        d.steps = ["The alias link could not be read back from the identity table."]
        d.incomplete = True
    return d


# Why THIS case, of ten thousand, is the one on screen. Keyed by the operation that
# retrieved it — the record itself is the same either way; only the reason differs.
_WHY_THIS_CASE = {
    "FIR_LOOKUP": "You gave this FIR number. This is that exact record — no search or "
                  "ranking was involved.",
    "CASE_CONTEXT": "This is the case currently open in your workspace.",
    "CASE_PEOPLE": "This is the case currently open in your workspace.",
    "PERSON_HISTORY": "The person you asked about is named as accused on this case. The "
                      "link runs through identity resolution: the Accused row on this "
                      "FIR was matched to the same person as the rows on their other "
                      "cases.",
    "RISK": "It is part of the recorded history the risk model read.",
    "CRIME_SEARCH": "It matched the filters in your question, and was taken from the top "
                    "of the matching set.",
    "SIMILAR_CASES": "It was ranked against the open case on narrative wording and on "
                     "structured overlap — shared IPC sections, crime type, district, "
                     "time of day.",
    "CASE_LOCATIONS": "It was one of the cases the previous answer cited; this turn only "
                      "tallied where they are.",
    "HOTSPOT": "It is one of the district's cases whose own recorded coordinates were "
               "plotted for this analysis. The point on the map is where the file says "
               "the incident was; the shaded region around it is the model's.",
    "TIMELINE": "It is dated, and it belongs to the case or person this timeline is "
                "about.",
}


def _explain_fir(eid: str, item, operation: str, subject_id, role, ps) -> Derivation:
    """A case record. What varies is not the record — it is why this case, of ten
    thousand, is the one on screen."""
    from .agents import sql_agent
    fir_id = eid.split(":", 1)[1]
    rows = sql_agent.fir_by_id(fir_id, role, ps)
    row = rows[0] if rows else None
    d = Derivation(
        evidence_id=eid, basis="record", basis_meaning=BASIS_MEANING["record"],
        claim=(f"FIR {row['fir_number']} is on record." if row
               else "This case is on record."),
        records=[_fir_source(row)] if row else [],
        next_questions=["What happened in this case?", "Who are all involved?",
                        "Show me the timeline.", "Find similar cases."])
    if row:
        d.steps.append(
            f"Read from the case file: "
            f"{row.get('crime_type') or 'crime type not recorded'}, "
            f"{row.get('district') or 'district not recorded'}, station "
            f"{row.get('ps_code')}, status "
            f"{row.get('case_status') or 'not recorded'}.")

    why = _WHY_THIS_CASE.get(operation)
    if why:
        d.steps.append(why)
    else:
        sq = _get(item, "source_query")
        d.steps.append(f"Retrieved by: {sq}." if sq else
                       "Retrieved as part of the previous answer's record set.")

    kind = _get(item, "confidence_kind", "support")
    conf = _get(item, "confidence")
    if kind == "similarity" and conf is not None:
        d.qualifies = (f"Text match {float(conf):.0%} — how closely the wording matches, "
                       f"which is a reason to look, not a reason to believe.")
        d.caveat = ("A high text match means the narratives read alike. It is not "
                    "evidence that the cases are connected.")
    elif operation == "FIR_LOOKUP":
        d.qualifies = "Exact identifier match. There is nothing to rank."
    elif conf is not None:
        d.qualifies = f"Cited with {float(conf):.0%} evidence support."
    return d


def _explain_flow(eid: str, item, subject_id, role, ps) -> Derivation:
    parts = eid.split(":")
    if len(parts) > 1 and parts[1] == "none":
        return Derivation(
            evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
            claim="No outbound money trail was found for this person.",
            steps=["Accounts owned by this person were read from the records, and every "
                   "outgoing transfer from them was followed forward.",
                   "Nothing was found within the number of transfer steps your rank "
                   "allows."],
            qualifies="This is a checked absence within a bounded walk.",
            caveat="Money moving IN to their accounts is not part of this trail — it is "
                   "on their timeline. An absence here is not proof no money moved.")
    d = Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim="Money moved between these two accounts.",
        steps=["Each transfer is a recorded transaction row; this line is their total "
               "along one route.",
               "The walk follows transfers FORWARD only — a trail can never run "
               "backwards up a payment and invent a transfer that did not happen."],
        qualifies="Within the number of transfer steps your rank allows to be followed.",
        caveat="An account appearing on a trail is not itself a finding of wrongdoing. "
               "Suspicion is flagged separately, by the structuring detector.",
        next_questions=["Show me the money trail.", "Show me the timeline."])
    if len(parts) >= 3:
        d.records = [SourceRecord(label=f"Account {parts[1][:8]}…",
                                  detail="source account on this route"),
                     SourceRecord(label=f"Account {parts[2][:8]}…",
                                  detail="destination account on this route")]
    return d


def _explain_hotspot(eid: str, item, subject_id, role, ps) -> Derivation:
    return Derivation(
        evidence_id=eid, basis="model", basis_meaning=BASIS_MEANING["model"],
        claim="This area is a crime hotspot in the district you asked about.",
        steps=["Every FIR in the district with coordinates on record was plotted — "
               "these are recorded incident locations, not estimates.",
               "Incidents lying within 500m of at least ten others were grouped into "
               "one cluster.",
               "The shading is a density estimate over those same points: how tightly "
               "they sit relative to the busiest area in THIS district."],
        qualifies=("A cluster is reported only where at least ten incidents fall within "
                   "500m of each other. Density is relative — 1.00 is the busiest place "
                   "in this result, not an absolute crime rate."),
        caveat=("This describes where crime was RECORDED, which is also where it was "
                "policed. It is a description of the past, not a prediction, and not a "
                "reason to expect crime here tomorrow."),
        next_questions=["Show me the cases here.", "What are the crime trends?"])


def _explain_forecast(eid: str, item, subject_id, role, ps) -> Derivation:
    return Derivation(
        evidence_id=eid, basis="prediction", basis_meaning=BASIS_MEANING["prediction"],
        claim="This is a projection of case volume, not a record of one.",
        steps=["The district's own recorded FIR counts per day were used as the history.",
               "Prophet fitted the trend and the weekly shape of that history and "
               "extended it forward.",
               "The district's figure was reconciled against its stations' figures so "
               "the two always sum coherently."],
        qualifies="Every point carries an interval. The interval is the answer; the line "
                  "through the middle is one reading of it.",
        caveat="Nothing here has happened. A forecast is decision support for allocating "
               "attention, and it is never evidence about a case.",
        next_questions=["Show me crime hotspots.", "How many cases are there?"])


_MODEL_EXPLANATIONS = {
    "risk": (
        "This is a model's risk ranking for this person.",
        ["Features are drawn from the person's own recorded case history — how many "
         "cases, how recent, how serious, and their position in the co-offending graph.",
         "No caste, religion or other protected attribute is a feature. The records "
         "store them; no model reads them.",
         "The contributing factors printed with the score are the model's own account "
         "of what moved it (TreeSHAP attributions)."],
        "Decision support for prioritising attention. Never a finding of fact, never an "
        "automated trigger, and never evidence."),
    "recidivism": (
        "This is a calibrated probability of re-offence within 180 days.",
        ["Fitted on the recorded histories of people with comparable case records, then "
         "calibrated so the number reads as a real probability.",
         "No protected attribute is a feature."],
        "A probability about a population, applied to one person. It says nothing about "
        "what this individual will do."),
    "aml": (
        "A money-laundering detector flagged this transaction.",
        ["The rule-based structuring detector looks for deposits placed just under a "
         "reporting threshold, and states in words what it matched — that is the part a "
         "court can audit line by line.",
         "Where it is available, a graph neural network additionally scores coordinated "
         "multi-account layering the rule structurally cannot see."],
        "A flag is a reason to look at a transaction. It is not a finding that laundering "
        "occurred."),
    "causal": (
        "This is a causal estimate over district socioeconomic data.",
        ["Real Census 2011 district figures, not survey estimates.",
         "The estimate adjusts for the confounders that ARE measured, and names the one "
         "that is not: police strength is not published per district in India."],
        "An estimate with a named unmeasured confounder. It is not proof of a cause, and "
        "it is not about any individual."),
}


def _explain_model(eid: str, item, kind: str) -> Derivation:
    claim, steps, caveat = _MODEL_EXPLANATIONS[kind]
    return Derivation(
        evidence_id=eid, basis="model", basis_meaning=BASIS_MEANING["model"],
        claim=claim, steps=steps, caveat=caveat,
        qualifies="Reported as a model output and kept visually distinct from the "
                  "records throughout, so it can never be read as something the file "
                  "says.")


# The one timeline event type that is NOT a stated fact: a person's OTHER cases,
# reachable only because Fellegi-Sunter matched two Accused rows to one person
# (rag_agent/timeline.py says so in its own docstring). Everything else — the FIR
# being filed, an arrest, a transfer in or out — is a column in a record.
_DERIVED_EVENT_TYPES = {"related_case"}

_EVENT_NOUN = {
    "fir_filed": "case filing", "arrest": "arrest", "related_case": "related case",
    "money_in": "incoming transfer", "money_out": "outgoing transfer",
}


def _explain_timeline(eid: str, item, subject_id, role, ps) -> Derivation:
    """'Why is this case in the timeline?' — the two populations a timeline mixes."""
    parts = eid.split(":")
    event_type = parts[1] if len(parts) > 1 else ""

    # The item's own `authoritative` flag wins where it survived storage. Where it
    # did not — a large turn is stored as evidence skeletons, and older turns were
    # stored with no items at all — the EVENT TYPE decides, because it is carried in
    # the evidence_id and cannot be lost. Reading a missing field as False is what
    # made a recorded ₹64,945 transfer explain itself as a probabilistic identity
    # inference on a truncated timeline. A model output must never be able to look
    # like a record, and the converse is a defect of the same kind.
    stored = _get(item, "authoritative", None)
    authoritative = (bool(stored) if stored is not None
                     else event_type not in _DERIVED_EVENT_TYPES)
    d = Derivation(
        evidence_id=eid,
        basis="record" if authoritative else "derived",
        basis_meaning=BASIS_MEANING["record" if authoritative else "derived"],
        claim=(f"This {_EVENT_NOUN.get(event_type, event_type.replace('_', ' ') or 'event')} "
               f"belongs on the timeline."),
        next_questions=["What happened before this?", "What happened after this?",
                        "Add this event to the investigation board."])
    if authoritative:
        d.steps = ["The date is a column in the record itself — it is not inferred.",
                   "It is on this timeline because the record it comes from IS the case "
                   "or person the timeline is about."]
        d.qualifies = "Stated in the file, on a date the file states."
    else:
        d.steps = ["This event comes from a DIFFERENT record than the one the timeline "
                   "is about.",
                   "It is here because identity resolution matched a person on that "
                   "record to a person on this one — the records themselves never say "
                   "they are the same individual.",
                   "Without that inference this event would be invisible; with it, the "
                   "link is a probabilistic judgement, not a stated fact."]
        d.qualifies = "Included as a DERIVED event, and marked as one wherever it renders."
        d.caveat = ("If the identity match is wrong, this event belongs to someone else. "
                    "Check the name spellings before relying on it.")
    return d


def _explain_count(eid: str, item, role, ps) -> Derivation:
    return Derivation(
        evidence_id=eid, basis="record", basis_meaning=BASIS_MEANING["record"],
        claim="This is a count of records, not an estimate.",
        steps=["Counted over the case table with the filters your question named, and "
               "with your own rank and station scope applied inside the query.",
               "The sample cases listed under it are the first few of that same set — "
               "the count is over all of them, the list is not."],
        qualifies="Exhaustive within your access scope. A different rank would see a "
                  "different number, and that is the rule working, not a discrepancy.",
        next_questions=["Only these?", "Where are those cases?"])


class Ctx(NamedTuple):
    """Everything a handler may need beyond the item itself.

    A tuple rather than six positional parameters threaded through twelve lambdas:
    the set grows (this already gained `case_id` once), and a positional list that
    grows is a list somebody eventually passes in the wrong order.
    """
    role: str
    ps: str
    operation: str = ""
    subject_id: Optional[str] = None
    case_id: Optional[str] = None


def _explain_result_summary(eid: str, item) -> Derivation:
    """The line a result-set follow-up or a location tally produces about the RESULT
    ITSELF ("73 records matched in total; 5 were shown before"), rather than about any
    one record in it. It is a real claim with a real derivation, and without a handler
    of its own it fell to the "could not be reconstructed" fallback — which reads as
    the system being unable to account for its own bookkeeping."""
    if eid.startswith("case_locations:"):
        return Derivation(
            evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
            claim="This is where the cases from the previous answer are.",
            steps=["The cases the previous answer put on screen were taken by their "
                   "record ids — not re-searched, so this is the same set, not a "
                   "similar one.",
                   "Each was re-checked against your own rank and station before being "
                   "counted: a citation from an earlier turn is not itself a permission.",
                   "The districts were then tallied."],
            qualifies="A count over an exact, already-cited set.",
            caveat="It describes where those cases were FILED, which is not necessarily "
                   "where the offences happened.",
            next_questions=["Show me crime hotspots.", "Only these?"])
    return Derivation(
        evidence_id=eid, basis="record", basis_meaning=BASIS_MEANING["record"],
        claim="This states how much of the matching set you have actually seen.",
        steps=["The total is a count over the record table with your question's filters "
               "and your own access scope applied inside the query.",
               "The records listed beneath it are the ones not already shown — the same "
               "search, widened, with what you had already seen removed."],
        qualifies="Bookkeeping about the result set, not a claim about any case in it.",
        next_questions=["Only these?", "Where are those cases?"])


def _explain_semantic(eid: str, item) -> Derivation:
    """A semantic-search hit. The most common thing on screen, and the one whose
    reason for being there is most easily over-read: it is here because it READS
    like the question, which is a reason to look and not a reason to believe."""
    conf = _get(item, "confidence")
    d = Derivation(
        evidence_id=eid, basis="record",
        basis_meaning=BASIS_MEANING["record"],
        claim=(_get(item, "content") or "").split("\n")[0][:200]
              or "A record whose wording is close to your question.",
        steps=["Your question was compared against the narrative text of every record "
               "you are allowed to see — both by meaning and by the literal words in "
               "it, so an exact term like 'IPC 457' still finds its records.",
               "The closest few were returned. Nothing about the relationship between "
               "this record and your question has been established beyond that the "
               "text is similar.",
               "The record itself is real and unaltered; only its SELECTION is a "
               "similarity judgement."],
        qualifies=(f"Text match {float(conf):.0%}." if conf is not None else
                   "Selected on textual closeness."),
        caveat="A close text match means the narratives read alike. It is not evidence "
               "that the cases are connected, and it is not a claim that this record "
               "answers your question.",
        next_questions=["What supports that?", "Only these?"])
    return d


def _explain_graph_reach(eid: str, item, kind: str) -> Derivation:
    what = {
        "ppr": ("This was reached from the people your question named.",
                ["The names in your question were located in the graph and used as "
                 "starting points.",
                 "Importance was then spread outwards from those starting points along "
                 "recorded relationships — co-accusation, shared cases, account "
                 "ownership — so things several steps away can still surface if enough "
                 "paths lead to them.",
                 "The highest-scoring nodes came back. Every edge walked is a recorded "
                 "relationship; the RANKING over them is derived."],
                "Being reachable from your subject is not the same as being relevant to "
                "them. This is a shortlist to check, not a finding."),
        "tog": ("This is a reasoning path through the records, not a single fact.",
                ["Starting from your subject, the most promising relationships were "
                 "followed one step at a time, keeping only the few best partial paths "
                 "at each step.",
                 "The path shown is the chain of real, recorded relationships that "
                 "connects the two ends of it.",
                 "Each link is in the records. The DECISION to follow this chain rather "
                 "than another is the derived part."],
                "A path existing between two people does not mean they are associated "
                "in any operational sense. Long paths connect almost everyone."),
    }[kind]
    claim, steps, caveat = what
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim=claim, steps=steps, caveat=caveat,
        qualifies="Bounded by the traversal depth your rank allows.",
        next_questions=["What supports that?", "Show me the chain."])


def _explain_lead(eid: str, item) -> Derivation:
    negative = eid.endswith(":none")
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim=("No direct co-accused lead could be produced for this case."
               if negative else "This is a suggested next line of enquiry."),
        steps=["The people accused on this case were resolved to their cross-case "
               "identities, and each one's DIRECT co-accused were read from the records.",
               "Only direct co-accused are offered. At the full traversal depth this "
               "would name most of the connected component — hundreds of people — which "
               "is true and useless; a lead has to be actionable this week."],
        qualifies="Derived from recorded co-accusation, one step out.",
        caveat="A lead is a person worth speaking to. It is not an allegation, and "
               "nothing here says they were involved in this case.",
        next_questions=["Save this as a lead.", "Who are all involved?"])


def _explain_briefing(eid: str, item) -> Derivation:
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim="This is a drafted case-diary paragraph, assembled from the case's own file.",
        steps=["The case's dated events, its accused, its similar past cases and its "
               "co-accused leads were gathered first.",
               "The paragraph is written from those, and from nothing else.",
               "Victim details are masked before the draft is written, not after — "
               "masking generated prose afterwards is not reliable."],
        qualifies="Every fact in it traces to the case file or to a derivation over it.",
        caveat="It is a draft for an officer to check and sign, not a document of "
               "record. Nothing in it is an official finding until you make it one.",
        next_questions=["Show me the timeline.", "Find similar cases."])


def _explain_connection(eid: str, item) -> Derivation:
    negative = eid.endswith(":none")
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim=("No recorded connection was found between these two people."
               if negative else "These two people are connected in the records."),
        steps=["Three kinds of recorded link were checked between them: a shared case, "
               "a co-accusation, and a transfer between accounts they own.",
               "Each is a relationship stated in, or resolved directly from, the "
               "records — none of them is a similarity judgement."],
        qualifies=("A checked absence across all three link types."
                   if negative else "A recorded link, of a named kind."),
        caveat=("It means no link of those three kinds is on record. Two people can be "
                "connected in ways the records do not hold."
                if negative else
                "A recorded link is not a finding of joint involvement in anything."),
        next_questions=["Show me the timeline.", "What supports that?"])


def _explain_offender_ranking(eid: str, item, role: str, ps: str) -> Derivation:
    """'Why is this person top of the list?' — the count, and what it is a count OF.

    The distinction this has to hold is the one the ranking itself is built on: the
    position is a count of RECORDS, not a model's opinion of who matters. `vx_person`
    also carries PageRank and a risk score, and ranking on either would have produced
    a superficially similar list that means something completely different.
    """
    pid = eid.split(":", 1)[1]
    who = _person_name(pid) if pid.isdigit() else "this person"
    d = Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim=f"{who} is on this list because of how many cases name them.",
        steps=["Every Accused row in scope was resolved to a person — the records "
               "themselves have no cross-case person, so this count exists only "
               "because identity resolution matched those rows first.",
               "Their distinct cases were counted, and the people were ordered by that "
               "count. Nothing is weighted, scored or modelled.",
               "Only cases you are permitted to see were counted, so the same question "
               "at a different rank returns a different list."],
        qualifies="Ranked on a recorded fact — the number of cases naming this person — "
                  "not on a risk score or a graph centrality, neither of which means "
                  "'most active'.",
        caveat="Being named as accused on many cases is a fact about the record, not a "
               "finding of guilt on any of them. A person acquitted ten times counts "
               "the same here as one convicted ten times.",
        next_questions=[f"Does {who} have priors?", f"Who are {who}'s associates?",
                        f"Show me the timeline for {who}."])
    if pid.isdigit():
        from .agents import sql_agent
        try:
            cases = sql_agent.filter_viewable(sql_agent.person_record(pid), role, ps)[:5]
        except Exception:
            cases = []
        d.records = [_fir_source(c) for c in cases]
        if cases:
            d.steps.append(f"The most recent of their cases: "
                           + "; ".join(c.label for c in d.records) + ".")
    return d


def _explain_priors(eid: str, item, role: str, ps: str) -> Derivation:
    """'Does he have priors?' — the flagship question, and the one the organizers'
    schema cannot answer at all without the identity layer.

    On the raw ER every offender is a first-timer: an Accused row belongs to exactly
    one case, and nothing says the man on case 412 is the man on case 908. So this
    answer is DERIVED, not a record — the individual cases under it are records, the
    fact that they are ONE MAN'S cases is an inference, and an officer acting on a
    prior needs to know which of the two they are relying on.
    """
    pid = eid.split(":", 1)[1]
    who = _person_name(pid)
    d = Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim=f"This is {who}'s recorded case history.",
        steps=["These records have no cross-case person: an Accused row belongs to one "
               "case, and its per-case label is not an identity. On the file alone, "
               "every offender is a first-timer.",
               "Probabilistic record linkage compared the Accused rows on name, date of "
               "birth, address and case details, and judged which of them are the same "
               "individual. That inference is what makes a 'prior' exist at all.",
               "Each case listed beneath is then read straight from its own file — the "
               "cases are records; the fact that they belong to one person is derived."],
        qualifies="Every case here was matched to this person above the linkage "
                  "threshold. Measured F1 against the answer key: 0.989.",
        caveat="If the identity match is wrong, a case listed here belongs to somebody "
               "else. Check the as-filed name spellings before relying on a prior.",
        next_questions=[f"Who are {who}'s associates?",
                        f"Show me the timeline for {who}.",
                        f"Is {who} recorded under another name?"])
    from .agents import sql_agent
    try:
        cases = sql_agent.filter_viewable(sql_agent.person_record(pid), role, ps)[:6]
    except Exception:
        cases = []
    d.records = [_fir_source(c) for c in cases]
    return d


def _explain_stats(eid: str, item) -> Derivation:
    kind = eid.split(":")[1] if ":" in eid else ""
    if kind == "rate":
        return Derivation(
            evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
            claim="This rate is a share of the cases that reached a verdict.",
            steps=["Every case in the scope you asked about was counted by its recorded "
                   "status.",
                   "The rate divides convictions by convictions plus acquittals — the "
                   "cases that actually reached an outcome.",
                   "Cases still under investigation or chargesheeted are NOT in the "
                   "denominator. Including them would report a rate that falls simply "
                   "because a station has recent cases."],
            qualifies="Computed from recorded statuses only; nothing is estimated.",
            caveat="It is a rate over the cases YOU can see. A different rank sees a "
                   "different denominator, and that is the access rule working, not a "
                   "discrepancy between two numbers.",
            next_questions=["Which police station has the most pending cases?",
                            "How many cases are pending?"])
    if kind == "sections_unavailable":
        return Derivation(
            evidence_id=eid, basis="record", basis_meaning=BASIS_MEANING["record"],
            claim="These records cannot rank IPC sections by how often they are used.",
            steps=["A section is attached to an OFFENCE TYPE in these records "
                   "(CrimeHeadActSection), not to an individual case.",
                   "So counting sections would really be counting offence types, once "
                   "per section each type happens to carry — a number that looks like a "
                   "frequency and is not one."],
            qualifies="A stated limit of the record structure, not a failed query.",
            caveat="It does not mean the sections are unrecorded. It means they are "
                   "recorded per offence type, which is the breakdown shown instead.")
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim="This is a count over the case records, grouped.",
        steps=["Every case matching the scope you asked about was counted, with your "
               "own rank and station applied inside the query.",
               "The grouping is a column the records already carry — district, station, "
               "offence type or status. Nothing is inferred and nothing is estimated."],
        qualifies="Exhaustive within your access scope.",
        caveat="Counts describe what was RECORDED, which is also what was policed. More "
               "recorded cases in a place can mean more crime, or more reporting.",
        next_questions=["Show me crime hotspots.", "What are the crime trends?"])


def _explain_area(eid: str, item) -> Derivation:
    """'Why is this the profile?' — the crime mix and the Census row, kept explicitly
    apart. Answering this well means saying what it does NOT establish just as
    plainly as what it does: nothing here claims socioeconomic conditions CAUSE the
    crime count next to them (see CLAUDE.md §9/DoWhy's named-confounder discipline)."""
    kind = eid.split(":")[1] if eid.count(":") >= 1 else ""
    if kind == "census" or kind == "census_unavailable":
        return Derivation(
            evidence_id=eid, basis="record", basis_meaning=BASIS_MEANING["record"],
            claim="This is real Census 2011 ground truth for this district, not a "
                  "model estimate.",
            steps=["Read from vx_district_socioeconomic, the one table in this schema "
                   "loaded verbatim from the Census of India 2011 Primary Census "
                   "Abstract rather than generated.",
                   "Nothing here is combined with the crime count beside it — the two "
                   "are shown side by side, not scored together."],
            qualifies="Real, published, district-level figures. No district finer than "
                      "this exists in the data.",
            caveat="This is a fact ABOUT the district, not a cause of its recorded "
                   "crime count. This platform's causal layer names its confounders "
                   "explicitly rather than implying a link here.",
            next_questions=["Show me crime hotspots.", "What is the conviction rate?"])
    return Derivation(
        evidence_id=eid, basis="record", basis_meaning=BASIS_MEANING["record"],
        claim="This is the recorded offence mix for this district.",
        steps=["Every case matching this district was counted and grouped by offence "
               "type, with your own rank and station applied inside the query.",
               "Nothing is inferred: this is a count of what was recorded, not a "
               "model's estimate of what happened."],
        qualifies="Exhaustive within your access scope.",
        caveat="A count of what was RECORDED is also a count of what was POLICED. It "
               "does not by itself say where crime is worst, only where it was logged.",
        next_questions=["Show me crime hotspots.", "What is the conviction rate?"])


def _explain_community(eid: str, item, role: str, ps: str) -> Derivation:
    """'Why is this person in this group?' — a Louvain community, not a legal
    designation. The one place this platform's own naming discipline (CLAUDE.md §4:
    'There are no gangs') has to be restated at the point an officer might act on it."""
    rest = eid.split(":", 1)[1] if ":" in eid else ""
    d = Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim="This grouping is derived from co-offending patterns, not stated by any "
              "record.",
        steps=["The co-offending graph (who has been accused alongside whom) was "
               "partitioned by the Louvain community-detection algorithm.",
               "Everyone in this group ended up on the same side of that partition "
               "because of shared cases with each other — not because any record "
               "calls them a group."],
        qualifies="A community is a fact about the GRAPH. Membership can shift if the "
                  "underlying case records change.",
        caveat="This is not a gang designation. Nothing in these records asserts an "
               "organised-crime relationship; this states only that these people have "
               "offended together, derived, never treated as a record.",
        next_questions=["Who are this person's associates?", "Does this person have priors?"])
    if rest.isdigit():
        from .agents import sql_agent
        try:
            cases = sql_agent.filter_viewable(sql_agent.person_record(rest), role, ps)[:3]
        except Exception:
            cases = []
        d.records = [_fir_source(c) for c in cases]
    return d


def _explain_watchlist(eid: str, item) -> Derivation:
    """'Why is this transaction flagged?' — and, just as important, by WHICH detector,
    because CLAUDE.md §6 draws a hard line between the two: a rule a court can audit
    line by line, and a GNN pattern that is a lead, never a court-ready finding."""
    content = _get(item, "content", "") or ""
    is_gnn = "gnn" in content.lower()
    return Derivation(
        evidence_id=eid, basis="model", basis_meaning=BASIS_MEANING["model"],
        claim="This transaction was flagged by an anti-money-laundering detector, not "
              "recorded as suspicious by any officer.",
        steps=(["The GNN suspicious-subgraph classifier scored this transaction's "
                "surrounding account structure and flagged it as a coordinated pattern."]
               if is_gnn else
               ["The rule-based structuring detector checked this account for multiple "
                "sub-threshold deposits within a short window — the classic structuring "
                "pattern — and this transaction matched."]),
        qualifies=("A GNN pattern match: catches coordination the rule cannot see, but "
                   "is decision support, not a court-ready finding on its own."
                   if is_gnn else
                   "A rule-based match: the exact threshold and window are fixed and "
                   "auditable line by line, which is what makes this the one AML "
                   "signal here safe to put in front of a court."),
        caveat="A flag is a reason to look, not a finding of laundering. Detector "
               "output is never written back as training data for itself.",
        next_questions=["Show me the financial watchlist.", "What is the money trail for this case?"])


def _explain_workload(eid: str, item) -> Derivation:
    """'Why is this station ranked here?' — stalled count first, then age, because a
    station with fewer open cases but more NEGLECTED ones is the one that actually
    needs attention."""
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim="This station's position is derived from its open caseload and how much "
              "of it has gone untouched.",
        steps=["Every case still Under Investigation, within your access scope, was "
               "grouped by station.",
               "Each open case's age was computed from its registration date, and "
               "checked against the investigation board for any activity at all.",
               "Stations are ranked by how many of their open cases are BOTH old and "
               "untouched, then by average age — a raw open-case count alone would "
               "reward a quiet station over a neglected one."],
        qualifies="Exhaustive within your access scope; the staleness threshold is a "
                  "fixed cut (30 days), not a model's judgment.",
        caveat="This never assigns work or flags an officer — it names where a human "
               "should look. Nothing here is an automated trigger.",
        next_questions=["Which cases are stalled at this station?"])


def _explain_stalled(eid: str, item) -> Derivation:
    return Derivation(
        evidence_id=eid, basis="record", basis_meaning=BASIS_MEANING["record"],
        claim="This case has had no investigation-board activity recorded in over 30 "
              "days.",
        steps=["The case's own registration date was checked against today.",
               "Every board-item row was checked for this case's id, and none exist."],
        qualifies="A checked absence — no pinned evidence, lead, or note — not an "
                  "estimate of neglect.",
        caveat="Board silence does not prove no work has happened; it means no work "
               "was RECORDED on the board. An officer may be investigating without "
               "using it.",
        next_questions=["What is the status of this case?", "Who is involved in this case?"])


def _explain_idcheck(eid: str, item) -> Derivation:
    """The Compare Mode identity-resolution audit note itself. What it explains is
    the CHECK, not a claim about the two people — matching the same discipline
    _explain_priors uses for the identity layer generally."""
    content = _get(item, "content", "") or ""
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim="This checks whether two similarly-spelled names were resolved to the "
              "same person.",
        steps=["The two compared names were measured for text similarity.",
               "Because they were close enough to plausibly be the same person "
               "misspelled, their resolved PersonUIDs were compared directly rather "
               "than left implicit.",
               content or "The two PersonUIDs differ, so identity resolution treats "
                          "them as two separate people."],
        qualifies="A live audit of a linkage decision, not a new inference — it reports "
                  "what identity resolution already decided, computed on demand.",
        caveat="Text similarity is not evidence of identity by itself; it is the reason "
               "this check ran, not the basis for its answer.",
        next_questions=["Is this person recorded under another name?"])


def _explain_interview_prep(eid: str, item) -> Derivation:
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim="This is a point to prepare before questioning this person.",
        steps=["Their recorded case history, and the structural gaps on those cases "
               "(no arrest logged, no chargesheet filed), were read from the record.",
               "Their direct co-offending associates were read from the graph, "
               "nearest first.",
               "Each point below is either a case fact or a named gap in the file — "
               "nothing here is a suggested question or a guess at what they will say."],
        qualifies="Assembled from the record layer only; it prepares you with what is "
                  "on file, not with an interrogation script.",
        caveat="This is preparation, not evidence. Nothing here establishes what "
               "happened in this specific case.",
        next_questions=["Does this person have priors?", "Who are this person's associates?"])


def _explain_watch(eid: str, item) -> Derivation:
    negative = eid.endswith(":none")
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim=("No match was found in your own backlog or the unsolved case pool."
               if negative else "This case structurally resembles the one you have open."),
        steps=["The same structured-similarity check the Investigation Copilot runs "
               "for 'similar cases' was run again, narrowed to two populations: your "
               "own open cases, and cases on record closed as undetected.",
               "Only matches inside those two populations are shown — a strong match "
               "outside them would not appear here."],
        qualifies=("A checked absence across both populations." if negative else
                   "Ranked the same way SIMILAR_CASES is: shared crime type, IPC "
                   "sections, district and modus operandi first, text similarity as "
                   "the tiebreaker."),
        caveat="A structural match is a reason to compare the two cases, not a "
               "finding that they are connected.",
        next_questions=["Find similar cases.", "What happened in this case?"])


def _explain_handoff(eid: str, item) -> Derivation:
    kind = eid.split(":")[-1] if eid.count(":") >= 2 else ""
    if kind == "board":
        return Derivation(
            evidence_id=eid, basis="record", basis_meaning=BASIS_MEANING["record"],
            claim="This states what previous officers left on this case's "
                  "investigation board.",
            steps=["Every pinned item, note and lead recorded against this case was "
                   "read and counted by type."],
            qualifies="A count of board rows, not a summary written by anyone.",
            next_questions=["What is on the board for this case?"])
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim="This is a handoff briefing, assembled so you do not have to rebuild "
              "the case from a blank file.",
        steps=["The same case-diary draft the Investigation Copilot generates was "
               "read first — the case's own facts, its timeline, its leads.",
               "The investigation board was read alongside it, so anything a "
               "previous officer already pinned, noted or ruled out does not need "
               "rediscovering."],
        qualifies="Every fact in it traces to the case file, the timeline, or the "
                  "board — nothing here is written from outside the record.",
        caveat="It is a briefing to read before you act, not a document of record.",
        next_questions=["What is on the board for this case?", "What should I do next?"])


def _explain_filing(eid: str, item) -> Derivation:
    negative = eid.endswith(":none")
    context = eid.endswith(":context")
    if context:
        return Derivation(
            evidence_id=eid, basis="record", basis_meaning=BASIS_MEANING["record"],
            claim="This is how other cases of the same offence type, within your "
                  "access scope, have actually been recorded as ending.",
            steps=["Every case sharing this case's crime type, within your rank and "
                   "station scope, was counted by its recorded status."],
            qualifies="Context for judgement, not a prediction about this case.",
            next_questions=["What is the conviction rate?"])
    return Derivation(
        evidence_id=eid, basis="record", basis_meaning=BASIS_MEANING["record"],
        claim=("No structural gap was found on this case file."
               if negative else "This is a structural gap in this case's own file."),
        steps=["The case's ArrestSurrender and ChargesheetDetails rows were read "
               "directly — this checks whether the paperwork is complete, not "
               "whether the evidence is strong."],
        qualifies=("A checked absence of the three gaps this look for." if negative
                   else "A fact read directly from the case's own records."),
        caveat="A structural gap is not a judgement that the case is weak, and its "
               "absence is not a judgement that it is strong. It states only what "
               "paperwork is or is not on file.",
        next_questions=["Has a chargesheet been filed?", "Was there an arrest?"])


def _explain_linkage(eid: str, item) -> Derivation:
    negative = eid.endswith(":none")
    withheld = "outside your access scope" in (_get(item, "content", "") or "")
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim=("No cross-station link was found for this case's accused."
               if negative else
               "This case's accused is also named on a case at a different station."
               if not withheld else
               "This case's accused is also named on a case at another station, "
               "outside what you may see."),
        steps=["Every person accused on this case was resolved to their cross-case "
               "identity, and their other cases were read.",
               "Any of those other cases filed at a DIFFERENT station than this "
               "case's own is reported here — the identity link is the same one "
               "'does this person have priors' reads.",
               "Each such case is then checked against your own rank and station: "
               "the LINK is always reported, the CASE is named only where your "
               "access allows it."],
        qualifies=("A checked absence across this case's own accused." if negative
                   else "The link is a resolved identity match, not a coincidence of "
                        "name."),
        caveat="A shared person across two stations' cases is a reason for those "
               "stations to compare notes. It is not itself a finding that the "
               "cases are related.",
        next_questions=["Who are this person's associates?", "Does this person have priors?"])


def _explain_series(eid: str, item) -> Derivation:
    content = _get(item, "content", "") or ""
    negative = eid.endswith(":none")
    is_summary = eid.endswith(":summary")
    withheld = "outside your access scope" in content
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim=("No cross-station pattern was found for this case." if negative else
              "This case is one of several that structurally match across different "
              "police stations." if is_summary else
              "This case matches the anchor case on crime type, act section(s), and "
              "an identical modus-operandi clause." if not withheld else
              "A matching case exists at another station, outside what you may see."),
        steps=["Structurally-similar cases were retrieved the same way SIMILAR_CASES "
               "does (crime type, shared act sections, district, and a direct match "
               "on the case-specific MO clause in BriefFacts).",
               "Candidates at the SAME station as this case were dropped — an "
               "officer's own station already sees those; the gap this checks for "
               "is the one nobody would otherwise cross-reference.",
               "Candidates that already share a resolved accused with this case were "
               "dropped — that overlap is what 'who else is this person named "
               "with' already answers, not a new pattern.",
               "What remains must match on the exact MO clause specifically, not "
               "just crime type and sections — several crime types cite a fixed, "
               "narrow set of sections, so those two alone are not distinctive.",
               "At least three total cases (this one plus two more) are required "
               "before this is reported as a pattern at all — one matching case "
               "elsewhere is coincidence, not a series."],
        qualifies=("A checked absence across other stations' open cases." if negative
                   else "A structural pattern — shared distinctive method, geography "
                        "and act sections — not a confirmed common offender."),
        caveat="This does not mean the same person committed all of these — it means "
               "nobody has yet ruled that in OR out, and right now nobody who is "
               "investigating any one of these cases would know the others exist.",
        next_questions=["Why do you think these are connected?",
                        "Add this pattern to the case board.",
                        "Should another station know about this?"])


def _explain_profile(eid: str, item) -> Derivation:
    negative = eid.endswith(":none")
    return Derivation(
        evidence_id=eid, basis="derived", basis_meaning=BASIS_MEANING["derived"],
        claim=("No recurring pattern was found across this person's recorded cases."
              if negative else
              "This is a recurring pattern read across this person's own cases, "
              "not a fact any single record states."),
        steps=["Every case this person is named as accused on was read (the same "
               "identity-resolved history 'does this person have priors' reads).",
               "Time of day, the case-specific method clause, incident location, "
               "offence severity and co-accused were compared ACROSS those cases.",
               "A pattern is only reported where it clears a real bar: a majority "
               "of cases sharing a time window, an exact repeated method, an "
               "actual severity increase per the record's own gravity "
               "classification, or a co-accused on more than one case — never "
               "from a single case or from demographic fields."],
        qualifies=("A checked absence — either too few recorded cases or nothing "
                   "lines up across them." if negative else
                   "A behavioral pattern read from records, not a prediction and "
                   "not a demographic inference — caste, religion and gender are "
                   "never read by this or any model in this system."),
        caveat="This describes what the record shows about past cases, not what "
               "this person will do next — it is not a risk score and carries no "
               "probability of reoffending.",
        next_questions=["Does this person have priors?", "Who are this person's associates?"])


def _explain_no_accused(eid: str, item) -> Derivation:
    return Derivation(
        evidence_id=eid, basis="record", basis_meaning=BASIS_MEANING["record"],
        claim="No accused person is recorded on this case.",
        steps=["The case's own Accused rows were read. There are none."],
        qualifies="A checked absence in the file itself, not a failed search.",
        caveat="It means nobody has been named on this FIR yet — not that nobody was "
               "involved.",
        next_questions=["What happened in this case?", "Find similar cases."])


_PREFIX = {
    "assoc":       lambda eid, it, c: _explain_associate(eid, it, c.subject_id, c.role, c.ps),
    "accused":     lambda eid, it, c: _explain_accused(eid, it, c.case_id, c.role, c.ps),
    "same_as":     lambda eid, it, c: _explain_alias(eid, it, c.subject_id, c.role, c.ps),
    "fir":         lambda eid, it, c: _explain_fir(eid, it, c.operation, c.subject_id, c.role, c.ps),
    "flow":        lambda eid, it, c: _explain_flow(eid, it, c.subject_id, c.role, c.ps),
    "hotspot":     lambda eid, it, c: _explain_hotspot(eid, it, c.subject_id, c.role, c.ps),
    "forecast":    lambda eid, it, c: _explain_forecast(eid, it, c.subject_id, c.role, c.ps),
    "risk":        lambda eid, it, c: _explain_model(eid, it, "risk"),
    "recidivism":  lambda eid, it, c: _explain_model(eid, it, "recidivism"),
    "aml":         lambda eid, it, c: _explain_model(eid, it, "aml"),
    "causal":      lambda eid, it, c: _explain_model(eid, it, "causal"),
    "timeline":    lambda eid, it, c: _explain_timeline(eid, it, c.subject_id, c.role, c.ps),
    "crime_count": lambda eid, it, c: _explain_count(eid, it, c.role, c.ps),
    "result_followup":  lambda eid, it, c: _explain_result_summary(eid, it),
    "case_locations":   lambda eid, it, c: _explain_result_summary(eid, it),
    "vec":              lambda eid, it, c: _explain_semantic(eid, it),
    "ppr":              lambda eid, it, c: _explain_graph_reach(eid, it, "ppr"),
    "tog":              lambda eid, it, c: _explain_graph_reach(eid, it, "tog"),
    "lead":             lambda eid, it, c: _explain_lead(eid, it),
    "briefing_lead":    lambda eid, it, c: _explain_lead(eid, it),
    "briefing":         lambda eid, it, c: _explain_briefing(eid, it),
    "connection":       lambda eid, it, c: _explain_connection(eid, it),
    "no_accused":       lambda eid, it, c: _explain_no_accused(eid, it),
    "offender":         lambda eid, it, c: _explain_offender_ranking(eid, it, c.role, c.ps),
    "ranking":          lambda eid, it, c: _explain_offender_ranking(eid, it, c.role, c.ps),
    "stats":            lambda eid, it, c: _explain_stats(eid, it),
    "priors":           lambda eid, it, c: _explain_priors(eid, it, c.role, c.ps),
    "area":             lambda eid, it, c: _explain_area(eid, it),
    "community":        lambda eid, it, c: _explain_community(eid, it, c.role, c.ps),
    "watchlist":        lambda eid, it, c: _explain_watchlist(eid, it),
    "workload":         lambda eid, it, c: _explain_workload(eid, it),
    "stalled":          lambda eid, it, c: _explain_stalled(eid, it),
    "idcheck":          lambda eid, it, c: _explain_idcheck(eid, it),
    "interview":        lambda eid, it, c: _explain_interview_prep(eid, it),
    "watch":            lambda eid, it, c: _explain_watch(eid, it),
    "handoff":          lambda eid, it, c: _explain_handoff(eid, it),
    "filing":           lambda eid, it, c: _explain_filing(eid, it),
    "linkage":          lambda eid, it, c: _explain_linkage(eid, it),
    "series":           lambda eid, it, c: _explain_series(eid, it),
    "profile":          lambda eid, it, c: _explain_profile(eid, it),
}

# Every evidence_id prefix this system produces must have a handler above. The
# fallback is honest ("I cannot reconstruct why this is here") but it is a floor,
# not a design: an officer pointing at the most common thing on screen — a semantic
# search hit — and being told the derivation is unavailable would make the whole
# feature read as decorative. Kept as a test (tests/test_provenance.py) rather than
# a comment, so a new producer cannot add a prefix without noticing.


def explain(item: Any, *, role: str, ps: str, operation: str = "",
            subject_id: Optional[str] = None,
            case_id: Optional[str] = None) -> Derivation:
    """The provenance chain behind one evidence item.

    `item` is an EvidenceItem or the plain dict a stored conversation turn round-trips.
    Never raises: an explanation that cannot be built says so (`incomplete`), because
    "I cannot reconstruct why this is here" is a usable answer and a fabricated chain
    is not.
    """
    eid = _get(item, "evidence_id") or ""
    handler = _PREFIX.get(eid.split(":", 1)[0])
    if handler:
        try:
            return _resolve_markers(
                handler(eid, item, Ctx(role, ps, operation, subject_id, case_id)))
        except Exception as e:                       # never fail a "why?" question
            log.warning("provenance for %s failed: %s", eid, e)
    return _resolve_markers(_fallback(eid, item))


def _resolve_markers(d: Derivation) -> Derivation:
    """Resolve "step(s)"/"case(s)" against the count sitting next to them.

    The same convention the synthesis path resolves, applied here because a chain is
    reached two ways — typed into the copilot, and clicked in the console — and only
    the first went through synthesis. Live, the panel read "1 step(s) of co-accusation
    away": a form field in the middle of a finding.
    """
    try:
        from data.nlp.translate import resolve_plural_markers
    except Exception:
        return d
    d.claim = resolve_plural_markers(d.claim)
    d.qualifies = resolve_plural_markers(d.qualifies)
    d.steps = [resolve_plural_markers(s) for s in d.steps]
    if d.caveat:
        d.caveat = resolve_plural_markers(d.caveat)
    return d


def _fallback(eid: str, item) -> Derivation:
    """No convention matched, or the lookup failed. State that plainly."""
    source_type = _get(item, "source_type", "FIR_RECORD")
    basis = _BASIS_BY_SOURCE.get(source_type, "record")
    sq = _get(item, "source_query")
    steps = [f"Retrieved by: {sq}."] if sq else []
    steps.append("The step-by-step derivation for this particular item could not be "
                 "reconstructed. What is shown above is what the record itself says.")
    return Derivation(
        evidence_id=eid or "unknown", basis=basis, basis_meaning=BASIS_MEANING[basis],
        claim=(_get(item, "content") or "").split("\n")[0][:200],
        steps=steps, incomplete=True,
        qualifies="Shown because it was cited in the answer above.")


def as_text(d: Derivation) -> str:
    """The same chain as prose, for the conversational surface.

    Deliberately the same five sections in the same order as the panel, so an officer
    who asked by typing and an officer who asked by clicking are reading one thing in
    two places, not two different explanations of the same result.
    """
    lines = [d.claim, ""]
    lines.append(f"This is {d.basis.upper()} — {d.basis_meaning}")
    if d.records:
        lines.append("")
        lines.append("It rests on:")
        lines += [f"  · {r.label}" + (f" — {r.detail}" if r.detail else "")
                  for r in d.records]
    if d.steps:
        lines.append("")
        lines.append("How it was arrived at:")
        lines += [f"  {i}. {s}" for i, s in enumerate(d.steps, 1)]
    if d.qualifies:
        lines += ["", f"Why it qualifies: {d.qualifies}"]
    if d.caveat:
        lines += ["", f"What it does not mean: {d.caveat}"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# §4 — result truth: what KIND of result set is on screen                      #
# --------------------------------------------------------------------------- #

# What a result set IS, stated so "only these?" and "how many in total?" have a real
# fact to read rather than a guess. Written from the same `result_context` the
# orchestrator already records at the point a bounded result is produced.
_BASIS_OF_SET = {
    "CRIME_SEARCH": ("FILTERED", "every case matching the filters in your question, "
                                 "within your access scope"),
    "SIMILAR_CASES": ("RANKED", "ranked against the open case on narrative wording and "
                                "structured overlap"),
    "PERSON_NETWORK": ("EXHAUSTIVE", "every person reachable by co-accusation within the "
                                     "depth your rank allows"),
    "ALIAS_CHECK": ("EXHAUSTIVE", "every name spelling matched to this person"),
    "HOTSPOT": ("MODELLED", "every cluster the density model found in this district"),
    "FORECAST": ("MODELLED", "a projection, so there is no set to be complete about"),
}


def describe_result_set(rc: dict) -> Optional[str]:
    """One sentence stating what the result set on screen actually is.

    Appended to an answer whose result is bounded, ranked or modelled. The failure
    this exists to prevent is the quiet one: five cases listed under a question that
    asked for "the cases", read as all of them.
    """
    op = rc.get("operation")
    if not op or op not in _BASIS_OF_SET:
        return None
    kind, what = _BASIS_OF_SET[op]
    total, shown = rc.get("total_matched"), rc.get("shown", 0)
    if rc.get("is_sample") and total:
        return (f"Result set: SAMPLE — {shown} of {total} shown, {kind.lower()}: {what}. "
                f'Ask "only these?" for the rest.')
    if kind == "MODELLED":
        return f"Result set: MODELLED — {what}."
    if total is not None:
        return f"Result set: {kind} — {total} record(s): {what}."
    return f"Result set: {kind} — {what}."
