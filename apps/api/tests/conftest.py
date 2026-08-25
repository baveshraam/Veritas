"""Fixtures shared by the API suites.

`client` and `officers` used to live inside test_api.py. They moved here when the
acceptance suite was added in Phase 1 — two suites driving the same app through the same
tokens should not be building two of them, and a second copy is a second thing to keep
in step with the Employee table.
"""
import os

import pytest

os.environ.setdefault("VERITAS_DEV_MODE", "1")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from api.main import app
    return TestClient(app)


@pytest.fixture
def officers(dataset):
    """One badge number per role, straight out of the Employee table."""
    from data import ds
    from data.generator.refdata import DESIGNATION_TO_ROLE

    out: dict[str, dict] = {}
    for r in ds.query('SELECT "EmployeeID", "DesignationID", "KGID", "UnitID" '
                      'FROM "Employee" ORDER BY "EmployeeID"'):
        role = DESIGNATION_TO_ROLE.get(r["DesignationID"])
        if role and role not in out:
            out[role] = {"badge_no": r["KGID"], "ps_code": str(r["UnitID"])}
    return out
