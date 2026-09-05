"""Repo-root pytest bootstrap and the one shared dataset fixture.

Two jobs.

**sys.path.** The repo has a top-level `data/` directory and the installed package inside it
is also called `data` (data/data/). With the repo root on sys.path, `import data` resolves to
the *folder* as a PEP-420 namespace package and every suite fails to collect. Dropping the
repo root makes `import data` resolve to the installed veritas-data package, which is what
every other entrypoint already gets.

**The dataset.** Everything below the API is tested against a real, fully-built dataset in
SQLite, not against mocks. That is worth stating plainly, because it is the property the
whole data layer was designed for: ZCQL is a subset of SQL, so `data.ds` runs the *same query
strings* against SQLite that the deployed service sends to the Catalyst Data Store. A test
that passes here is not a test against a stand-in — it is the production query, executed.

The fixture builds a small but complete world: the organizers' ER, then identity resolution
on top of it, then the financial layer, the graph, and the graph algorithms — in that order,
because each genuinely depends on the last. It is session-scoped: it takes a few seconds, and
every suite wants the same one.
"""
import pathlib
import random
import sys

import pytest

_ROOT = pathlib.Path(__file__).parent.resolve()
sys.path[:] = [p for p in sys.path if p not in ("", ".", str(_ROOT))]

# 400, raised from 250. The hotspot assertion in ml_models was marginal by
# construction at 250 and had been passing on luck: the busiest district drew ~67
# cases, which over the generator's 4 activity centres is ~12 incidents each against
# DBSCAN's production `min_samples=10` — so a change anywhere upstream that shifts the
# RNG stream by a few draws flips it. Measured across seeds at 250: 0 clusters. At
# 400 the busiest district draws ~108 and DBSCAN finds 3, which is the property this
# fixture is supposed to be able to express. The alternative — lowering min_samples —
# would have weakened a production spatial parameter that is correct for the real
# 10,000-case dataset, to accommodate a fixture that was too sparse.
TEST_CASES = 400          # enough for co-offending crews, hotspots and a money trail

# Where the session dataset lives. `ds.reset_for_tests()` re-points a module global, so a
# suite that resets to an in-memory database (test_ds, test_audit_sessions) would otherwise
# leave the session dataset unreachable for every suite that runs after it. `_bind_backend`
# below re-binds before any test that asked for it.
_DATASET_ENV: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _reset_llm_call_budget():
    """The QuickML call-budget guard (llm.py) persists its counter in Cache so it
    survives a redeploy — which also means it survives across tests in the same
    process unless reset here, the same cross-test-pollution concern `_bind_backend`
    exists for below. Every test that calls llm.generate()/_raw_chat() (mocked or
    real) increments the same key `_record_call()` writes to."""
    from data import cache
    from rag_agent import llm
    cache.evict(llm._BUDGET_KEY)
    yield
    cache.evict(llm._BUDGET_KEY)


@pytest.fixture(autouse=True)
def _bind_backend(request):
    """Point `data.ds` at whichever database this test actually wants."""
    if not _DATASET_ENV:
        return
    if not {"dataset", "indexed", "habitual"} & set(request.fixturenames):
        return
    import os

    from data import ds
    os.environ.update(_DATASET_ENV)
    if str(ds._SQLITE_PATH) != _DATASET_ENV["VERITAS_SQLITE"]:
        ds.reset_for_tests(_DATASET_ENV["VERITAS_SQLITE"])
        from data.graph import reset_graph
        reset_graph()
        from data.vectors import load_index
        load_index.cache_clear()


@pytest.fixture(scope="session")
def dataset(tmp_path_factory):
    """A complete ER dataset in SQLite: records -> identities -> money -> graph -> metrics.

    Returns the `build.Dataset`, whose `accused_truth` is the entity-resolution answer key.
    """
    import os

    tmp = tmp_path_factory.mktemp("veritas")
    _DATASET_ENV.update({
        "VERITAS_DS_BACKEND": "sqlite",
        "VERITAS_SQLITE": str(tmp / "ds.sqlite3"),
        "VERITAS_AML_LABELS": str(tmp / "aml_labels.json"),
    })
    os.environ.update(_DATASET_ENV)

    from data import ds
    ds.reset_for_tests(str(tmp / "ds.sqlite3"))

    from data.generator.build import generate
    from data.generator.financial import make_financial
    from data.generator.graph_sync import sync_graph
    from data.generator.load import load_dataset
    from data.socioeconomic import load as load_socioeconomic

    load_socioeconomic()
    rng = random.Random(42)
    built = generate(rng, TEST_CASES)
    load_dataset(built)

    from ml_models.entity_resolution import resolve_entities
    resolve_entities()

    people = ds.query('SELECT "PersonUID", "IsHabitualOffender" FROM "vx_person"')
    case_ids = [c["CaseMasterID"] for c in built.tables["CaseMaster"]]
    accounts, txns, labels = make_financial(rng, people, case_ids)
    ds.insert("vx_account", accounts)
    ds.insert("vx_txn", txns)

    import json
    pathlib.Path(os.environ["VERITAS_AML_LABELS"]).write_text(json.dumps(labels))

    sync_graph()
    from data.gds import run_all as run_gds
    run_gds()

    return built


@pytest.fixture(scope="session")
def indexed(dataset):
    """The dataset, plus a built vector index. Separate because embedding is the slow part
    and only the retrieval suites need it."""
    from data.embeddings.index_job import run_all
    run_all()
    return dataset


@pytest.fixture
def habitual(dataset):
    """A person with more than one case — the subject of every "does he have priors" test."""
    from data import ds
    row = ds.one('SELECT "PersonUID", "CanonicalName" FROM "vx_person" '
                 'WHERE "IsHabitualOffender" = 1 ORDER BY "PageRank" DESC')
    assert row, "the generator produced no habitual offender — the crew model is broken"
    return row
