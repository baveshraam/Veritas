"""The graph: what `vx_graph_edge` must contain, and what the algorithms must find.

Neo4j is gone and no Catalyst service replaces it, so the guarantee that used to come from
a graph database now has to come from tests: that the edge list is a faithful projection of
the records, that symmetric relations traverse from either end, and that money does not.
"""
import networkx as nx

from data import ds
from data.gds import co_offending, community_members, display_names, personalized_pagerank
from data.graph import load_graph, node_label


def test_node_ids_carry_their_own_type():
    assert node_label("person:412") == "Person"
    assert node_label("case:1043") == "CrimeEvent"
    assert node_label("acct:77") == "Account"
    assert node_label("loc:Kolar") == "Location"


def test_the_graph_is_built_from_resolved_people_not_accused_rows(dataset):
    """The edge list keys on PersonUID. If it keyed on AccusedMasterID, every offender would
    be a first-timer and CO_ACCUSED_WITH would mean nothing."""
    g = load_graph()
    people = {n for n in g.nodes if n.startswith("person:")}
    n_persons = ds.scalar('SELECT COUNT("PersonUID") AS c FROM "vx_person"')
    n_accused = ds.scalar('SELECT COUNT("AccusedMasterID") AS c FROM "Accused"')

    assert len(people) <= n_persons
    assert len(people) < n_accused, (
        "there are as many person nodes as Accused rows — identity was never applied")


def test_co_accused_traverses_from_either_end(dataset):
    """A MultiDiGraph stores the row's direction only. Without the reverse edge, "who is he
    co-accused with" would work from one end of a pair and return nothing from the other."""
    g = load_graph()
    pair = next(((a, b) for a, b, d in g.edges(data=True)
                 if d["rel"] == "CO_ACCUSED_WITH"), None)
    assert pair, "no co-offending edges at all"
    a, b = pair
    assert g.has_edge(a, b) and g.has_edge(b, a)


def test_money_flows_one_way_only(dataset):
    """TRANSFERRED_TO is the one genuinely directed relation. Reversing it would invent a
    payment that never happened — so it is deliberately absent from the symmetric set."""
    g = load_graph()
    transfers = [(a, b) for a, b, d in g.edges(data=True) if d["rel"] == "TRANSFERRED_TO"]
    assert transfers, "no transfers in the graph"

    # For at least one transfer there must be no reverse edge of the same relation.
    reversed_pairs = {(b, a) for a, b in transfers}
    forward = set(transfers)
    assert forward - reversed_pairs, "every transfer has a mirror — direction was lost"


def test_transfer_edges_carry_their_amount(dataset):
    g = load_graph()
    amounts = [d.get("amount") for _, _, d in g.edges(data=True)
               if d["rel"] == "TRANSFERRED_TO"]
    assert amounts and all(a for a in amounts), "a money trail with no money on it"


def test_louvain_finds_crews_not_one_giant_component(dataset):
    """Run over the *whole* graph this fails: every case joins to its district, so
    `loc:Bengaluru Urban` is a hub connecting every offender in the state. The person metrics
    run on the co-offending projection for exactly this reason."""
    g = co_offending()
    assert all(n.startswith("person:") for n in g.nodes)

    sizes = sorted(
        (len(c) for c in nx.community.louvain_communities(g, weight="weight", seed=0)),
        reverse=True)
    assert len(sizes) >= 3
    assert sizes[0] < 0.8 * g.number_of_nodes()


def test_graph_metrics_are_written_back_onto_the_person(dataset):
    rows = ds.query('SELECT "PersonUID", "PageRank", "CommunityID", "GangAffiliation" '
                    'FROM "vx_person" WHERE "CommunityID" IS NOT NULL')
    assert rows, "gds wrote nothing back"
    for r in rows[:10]:
        assert r["PageRank"] > 0
        assert r["GangAffiliation"] == f"Community {r['CommunityID']}"


def test_community_members_are_ranked_by_influence(dataset):
    cid = ds.scalar('SELECT "CommunityID" AS c FROM "vx_person" '
                    'WHERE "CommunityID" IS NOT NULL')
    members = community_members(cid)
    assert members
    ranks = [m["PageRank"] or 0 for m in members]
    assert ranks == sorted(ranks, reverse=True)


def test_personalized_pagerank_ranks_the_seed_itself_highest(dataset, habitual):
    """HippoRAG's primitive. Seeding from a person and *not* getting that person back would
    mean the personalization vector was not applied at all."""
    seed = f"person:{habitual['PersonUID']}"
    rows = personalized_pagerank([seed], top_k=10)
    assert rows
    assert rows[0]["id"] == seed
    assert rows[0]["score"] > 0


def test_personalized_pagerank_reaches_beyond_the_seed(dataset, habitual):
    """One graph pass, multi-hop retrieval — that is the whole claim. If it only ever
    returned the seed, HippoRAG would be an expensive way to echo the query."""
    rows = personalized_pagerank([f"person:{habitual['PersonUID']}"], top_k=15)
    others = [r for r in rows if r["id"] != f"person:{habitual['PersonUID']}"]
    assert len(others) >= 3
    assert {r["label"] for r in others} - {"Person"}, "retrieval never left the person layer"


def test_unknown_seeds_return_nothing_rather_than_everything(dataset):
    assert personalized_pagerank(["person:99999999"]) == []
    assert personalized_pagerank([]) == []


def test_display_names_resolve_each_node_kind(dataset, habitual):
    case_id = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster"')
    ids = [f"person:{habitual['PersonUID']}", f"case:{case_id}", "loc:Kolar"]
    names = display_names(ids)
    assert names[ids[0]] == habitual["CanonicalName"]
    assert names[ids[1]]                      # the crime number or type
    assert names["loc:Kolar"] == "Kolar"      # named by its own id
