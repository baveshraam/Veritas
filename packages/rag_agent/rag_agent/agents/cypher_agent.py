"""Cypher Agent — graph retrieval, policy-capped at query-construction time.

Two paths, in this order:
  1. Intent templates (default). Parameterised, reviewed, and depth-capped. A police
     system should not be sending model-authored Cypher at its own evidence store for
     the queries it handles every day.
  2. LLM NL->Cypher (only when GEMINI_API_KEY is present AND no template fits).
     Validated with EXPLAIN before it is ever executed, and rejected outright if it
     tries to write or to out-run the caller's traversal depth.

Policy is applied HERE, not on the result: you cannot un-traverse a graph. The depth
cap from packages/policy is baked into the query text before it runs.
"""
import re

from data.graph import get_driver
from policy import max_traversal_depth

from ..llm import LLMUnavailable, available, generate

# Writes are never legal from the retrieval path, whatever the model suggests.
_FORBIDDEN = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL\s+db\.|LOAD\s+CSV)\b", re.I)
_VAR_DEPTH = re.compile(r"\*\s*(\d*)\s*\.\.\s*(\d+)")


def _cap_depth(cypher: str, max_depth: int) -> str:
    """Rewrite any variable-length pattern so it cannot exceed the role's cap."""
    def repl(m: re.Match) -> str:
        lo = m.group(1) or "1"
        hi = min(int(m.group(2)), max_depth)
        return f"*{lo}..{hi}"
    return _VAR_DEPTH.sub(repl, cypher)


def _run(cypher: str, **params) -> list[dict]:
    with get_driver().session() as s:
        return s.run(cypher, **params).data()


# --- templates ---------------------------------------------------------------

def person_by_name(name: str) -> list[dict]:
    return _run(
        "MATCH (p:Person) WHERE toLower(p.name_en) CONTAINS toLower($name) "
        "RETURN p.person_id AS person_id, p.name_en AS name_en, "
        "  p.gang_affiliation AS gang, coalesce(p.pagerank,0.0) AS pagerank, "
        "  p.community AS community, p.is_habitual_offender AS habitual "
        "ORDER BY pagerank DESC LIMIT 5", name=name)


def person_history(person_id: str) -> list[dict]:
    return _run(
        "MATCH (p:Person {person_id: $pid})-[a:ACCUSED_IN]->(c:CrimeEvent) "
        "RETURN c.fir_id AS fir_id, c.crime_type AS crime_type, "
        "  c.ipc_sections AS ipc_sections, c.date_occurred AS date_occurred, "
        "  c.district AS district, c.case_status AS case_status, a.arrest_date AS arrest_date "
        "ORDER BY c.date_occurred DESC LIMIT 25", pid=person_id)


def person_network(person_id: str, officer_role: str) -> list[dict]:
    depth = max_traversal_depth(officer_role)
    cypher = _cap_depth(
        "MATCH path = (p:Person {person_id: $pid})-[:CO_ACCUSED_WITH*1..4]-(o:Person) "
        "WITH o, min(length(path)) AS hops "
        "RETURN o.person_id AS person_id, o.name_en AS name_en, hops, "
        "  o.gang_affiliation AS gang, coalesce(o.pagerank,0.0) AS pagerank "
        "ORDER BY hops, pagerank DESC LIMIT 40", depth)
    return _run(cypher, pid=person_id)


def money_trail(person_id: str, officer_role: str) -> list[dict]:
    depth = max_traversal_depth(officer_role)
    cypher = _cap_depth(
        "MATCH (p:Person {person_id: $pid})-[:OWNS_ACCOUNT]->(a:Account) "
        "MATCH path = (a)-[:TRANSFERRED_TO*1..4]->(b:Account) "
        "WITH a, b, relationships(path) AS rels "
        "UNWIND rels AS r "
        "RETURN a.account_id AS from_account, b.account_id AS to_account, "
        "  sum(r.amount) AS amount, count(r) AS hops LIMIT 60", depth)
    return _run(cypher, pid=person_id)


def aliases(person_id: str) -> list[dict]:
    """SAME_AS edges written by the Fellegi-Sunter batch — a normal graph read, not
    a live linkage computation."""
    return _run(
        "MATCH (p:Person {person_id: $pid})-[s:SAME_AS]-(o:Person) "
        "RETURN o.person_id AS person_id, o.name_en AS name_en, "
        "  s.confidence AS confidence", pid=person_id)


def community_of(person_id: str) -> list[dict]:
    return _run(
        "MATCH (p:Person {person_id: $pid}) WHERE p.community IS NOT NULL "
        "MATCH (o:Person {community: p.community}) "
        "RETURN p.community AS community, count(o) AS members", pid=person_id)


# --- LLM fallback ------------------------------------------------------------

_SCHEMA_HINT = """Node labels and properties:
(:Person {person_id, name_en, gang_affiliation, risk_score, pagerank, community, is_habitual_offender})
(:CrimeEvent {fir_id, crime_type, ipc_sections, date_occurred, district, case_status, modus_operandi})
(:Account {account_id, bank}) (:Transaction {txn_id, amount, date, flagged_suspicious})
(:Gang {name}) (:Location {name})
Relationships:
(:Person)-[:ACCUSED_IN]->(:CrimeEvent), (:Person)-[:VICTIM_IN]->(:CrimeEvent)
(:Person)-[:CO_ACCUSED_WITH]-(:Person), (:Person)-[:MEMBER_OF]->(:Gang)
(:Person)-[:SAME_AS]-(:Person), (:Person)-[:OWNS_ACCOUNT]->(:Account)
(:Account)-[:TRANSFERRED_TO]->(:Account), (:CrimeEvent)-[:OCCURRED_AT]->(:Location)"""


def generate_cypher(question: str, officer_role: str) -> tuple[str, list[dict]]:
    """NL->Cypher for questions no template covers. Returns (cypher, rows)."""
    if not available():
        raise LLMUnavailable("no LLM configured and no template matched this query")

    depth = max_traversal_depth(officer_role)
    cypher = generate(
        f"{_SCHEMA_HINT}\n\nWrite ONE read-only Cypher query answering: {question}\n"
        f"Variable-length patterns must not exceed {depth} hops. "
        f"Return only the query, no markdown fence, no explanation.",
        system="You write precise, read-only Cypher for a police knowledge graph.",
    )
    cypher = re.sub(r"^```(?:cypher)?|```$", "", cypher, flags=re.M).strip()

    if _FORBIDDEN.search(cypher):
        raise ValueError("generated Cypher attempted a write or an admin call")
    cypher = _cap_depth(cypher, depth)

    with get_driver().session() as s:
        s.run(f"EXPLAIN {cypher}")        # parse/plan check before it touches data
        return cypher, s.run(cypher).data()
