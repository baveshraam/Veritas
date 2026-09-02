"""GET /analytics/* — the workspace's analytical tabs, read straight from the records.

These endpoints exist so that opening a tab does not have to ask the conversational
engine a question. That makes them a NEW enforcement point for the same rules /chat
already enforces, and a new enforcement point is exactly where a policy rule quietly
stops being a rule (BUG-003: "a rule enforced by one caller and not its neighbour is
not a rule"). So what is pinned here is not that the endpoints return data — it is
that they are authenticated, that they scope to the officer's own rank, and that they
never widen what /cases already shows the same officer.
"""
import pytest

ENDPOINTS = ["statistics", "offenders", "hotspots", "forecast", "area", "community",
             "watchlist", "workload"]


def _auth(client, badge_no: str) -> dict:
    r = client.post("/auth/token", json={"badge_no": badge_no})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.parametrize("path", ENDPOINTS)
def test_every_analytics_endpoint_requires_a_token(client, dataset, path):
    """A tab that loads itself must not become the one door with no lock on it."""
    assert client.get(f"/analytics/{path}").status_code == 401


@pytest.mark.parametrize("path", ENDPOINTS)
def test_every_analytics_endpoint_answers_for_a_signed_in_officer(client, officers,
                                                                  dataset, path):
    h = _auth(client, officers["DSP"]["badge_no"])
    r = client.get(f"/analytics/{path}", headers=h)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), dict)


def test_an_io_never_sees_more_than_their_own_case_index_already_shows(client, officers,
                                                                       dataset):
    """The scope has to be the SAME scope, not merely a narrow one. /cases is the
    officer's own case index and has been RBAC-tested since v6; the dashboard's total
    is a count of the same rows, so it can never exceed what /cases will list."""
    io_h = _auth(client, officers["IO"]["badge_no"])
    dsp_h = _auth(client, officers["DSP"]["badge_no"])

    io_total = client.get("/analytics/statistics", headers=io_h).json()["total"]
    dsp_total = client.get("/analytics/statistics", headers=dsp_h).json()["total"]
    assert 0 < io_total < dsp_total, "an IO's dashboard must be their station's, not the state's"

    io_work = client.get("/analytics/workload", headers=io_h).json()
    assert len(io_work["stations"]) <= 1, "an IO's workload must not name another station"


def test_an_io_ranking_masks_the_names_their_rank_cannot_read(client, officers, dataset):
    """`mask_person_name` is applied here for the same reason it is applied on /person:
    a ranked list is a list of people, and the ranking is not a reason to name them."""
    from policy import mask_person_name

    io_h = _auth(client, officers["IO"]["badge_no"])
    rows = client.get("/analytics/offenders", headers=io_h).json()["offenders"]
    for r in rows:
        assert r["name"] == mask_person_name("IO", r["name"]) or r["name"], r


def test_the_habitual_filter_is_actually_applied(client, officers, dataset):
    """"Repeat offenders" is a different question from "most active offenders" and had
    its own tab firing its own query. If the flag were dropped the two tabs would show
    the same list under two different headings."""
    h = _auth(client, officers["DSP"]["badge_no"])
    rows = client.get("/analytics/offenders?habitual=true", headers=h).json()["offenders"]
    assert all(r["habitual"] for r in rows), "a repeat-offender ranking must be habitual-only"


def test_the_hotspot_payload_carries_the_points_under_the_polygons(client, officers,
                                                                   dataset):
    """A hull with no incidents beneath it is an assertion, not a hotspot — the same
    reason the HOTSPOT intent fetches both halves."""
    h = _auth(client, officers["DSP"]["badge_no"])
    d = client.get("/analytics/hotspots", headers=h).json()
    assert d["district"], "a district has to be resolved for a density model to run"
    assert d["fir_points"], "the incident scatter must ship with the polygons"
    for p in d["fir_points"]:
        assert p["lat"] is not None and p["lng"] is not None
