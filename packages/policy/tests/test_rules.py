"""One check per rule, per relevant role. This package has no effect without these."""
from policy import can_view_fir, mask_person_fields, max_traversal_depth


def test_io_sees_only_own_ps():
    assert can_view_fir("IO", "KA05-PS01", "KA05-PS01") is True
    assert can_view_fir("IO", "KA05-PS01", "KA05-PS02") is False


def test_non_io_roles_are_cross_ps():
    for role in ("SHO", "DSP", "SP", "IG", "SCRB_Analyst"):
        assert can_view_fir(role, "KA05-PS01", "KA23-PS09") is True


def test_unknown_role_cannot_view():
    assert can_view_fir("HACKER", "KA05-PS01", "KA05-PS01") is False


def test_victim_identity_masked_below_dsp():
    person = {"person_id": "p1", "name_en": "Ramesh Gowda", "dob": "1990-01-01",
              "aadhaar_hash": "abc", "address_lat": 13.0, "address_lng": 77.0,
              "risk_score": 0.4}
    for role in ("IO", "SHO"):
        m = mask_person_fields(role, person)
        assert m["name_en"] is None and m["dob"] is None and m["aadhaar_hash"] is None
        assert m["address_lat"] is None and m["address_lng"] is None   # home address is identity
        assert m["person_id"] == "p1" and m["risk_score"] == 0.4   # operational fields kept
    for role in ("DSP", "SP", "IG", "SCRB_Analyst"):
        assert mask_person_fields(role, person)["name_en"] == "Ramesh Gowda"


def test_mask_does_not_mutate_input():
    person = {"name_en": "X"}
    mask_person_fields("IO", person)
    assert person["name_en"] == "X"


def test_traversal_depth_capped_by_role():
    assert max_traversal_depth("IO") == 2
    assert max_traversal_depth("SHO") == 2
    assert max_traversal_depth("DSP") == 4
    assert max_traversal_depth("IG") == 4
    assert max_traversal_depth("SCRB_Analyst") == 4
