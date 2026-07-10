"""Offline checks for Neo4j node/edge builders — no database."""
import random

from data.generator.build import generate
from data.generator.graph_sync import (
    accused_in_edges, co_accused_edges, crimeevent_nodes, gang_nodes,
    location_nodes, member_of_edges, person_nodes, victim_in_edges,
)

_DS = generate(random.Random(9), 300)


def test_node_edge_endpoints_reference_real_nodes():
    person_ids = {n["person_id"] for n in person_nodes(_DS)}
    fir_ids = {n["fir_id"] for n in crimeevent_nodes(_DS)}
    locations = {n["name"] for n in location_nodes(_DS)}
    gangs = {n["name"] for n in gang_nodes(_DS)}

    for e in accused_in_edges(_DS):
        assert e["person_id"] in person_ids and e["fir_id"] in fir_ids
    for e in victim_in_edges(_DS):
        assert e["person_id"] in person_ids and e["fir_id"] in fir_ids
    for e in member_of_edges(_DS):
        assert e["person_id"] in person_ids and e["gang"] in gangs
    assert gangs  # generator seeds gang affiliations


def test_co_accused_is_deduped_ordered_and_strength_counted():
    edges = co_accused_edges(_DS)
    seen = set()
    for e in edges:
        assert e["a"] < e["b"]                       # one row per unordered pair
        assert (e["a"], e["b"]) not in seen
        seen.add((e["a"], e["b"]))
        assert e["strength"] == len(e["fir_ids"]) >= 1
