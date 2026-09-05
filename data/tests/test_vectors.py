"""Hybrid retrieval over the vector index.

pgvector is gone, and the reason the replacement is *hybrid* rather than pure dense is the
thing worth testing: an officer types a crime number or an IPC section, and a dense model
has no notion of either. The lexical half is what makes an exact identifier findable.
"""
import pytest

from data import ds
from data.vectors import build_index, embed, hybrid_search, load_index

DOCS = [
    {"collection": "fir_narrative", "source_id": "1",
     "content": "Chain snatching near the Kolar bus stand by two men on a motorcycle."},
    {"collection": "fir_narrative", "source_id": "2",
     "content": "Burglary at a jewellery shop in Hubballi; case registered under IPC 457."},
    {"collection": "fir_narrative", "source_id": "3",
     "content": "House break-in at night in Mysuru while the occupants were away."},
    {"collection": "criminal_profile", "source_id": "77",
     "content": "Ramesh Gowda. Accused in cases of Theft, Robbery."},
]


@pytest.fixture(scope="module", autouse=True)
def index():
    ds.reset_for_tests()          # fresh in-memory Data Store, isolated from other suites
    load_index.cache_clear()
    assert build_index(DOCS)["written"] == 4


def test_embeddings_are_l2_normalised():
    """Cosine similarity is then a plain dot product — which is what `hybrid_search` does."""
    import numpy as np
    m = embed(["a test sentence", "another one"])
    assert np.allclose(np.linalg.norm(m, axis=1), 1.0, atol=1e-5)


def test_dense_retrieval_finds_a_paraphrase():
    """No shared keywords with document 3 beyond 'house' — this is the half a keyword index
    could not do."""
    hits = hybrid_search("someone entered a residence at night while nobody was home", k=1)
    assert hits[0]["source_id"] == "3", hits


def test_lexical_retrieval_finds_an_exact_identifier():
    """The reason this is hybrid. 'IPC 457' is a rare token a dense model cannot represent,
    and it is exactly what an investigator types."""
    hits = hybrid_search("IPC 457", k=1)
    assert hits[0]["source_id"] == "2", hits


def test_collection_filter_is_respected():
    hits = hybrid_search("Ramesh Gowda", collection="criminal_profile", k=2)
    assert hits and all(h["collection"] == "criminal_profile" for h in hits)

    hits = hybrid_search("Ramesh Gowda", collection="fir_narrative", k=2)
    assert all(h["collection"] == "fir_narrative" for h in hits)


def test_scores_are_bounded_and_ranked():
    hits = hybrid_search("theft in Kolar", k=4)
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(-1.0 <= s <= 1.0 for s in scores)


def test_an_empty_index_returns_nothing_rather_than_raising():
    ds.reset_for_tests()          # a fresh Data Store has no vx_vector_embedding rows
    load_index.cache_clear()
    try:
        assert hybrid_search("anything") == []
    finally:
        ds.reset_for_tests()
        load_index.cache_clear()
        assert build_index(DOCS)["written"] == 4     # restore this module's shared index


def test_build_index_embeds_in_bounded_batches_not_one_giant_call(monkeypatch):
    """Live verification (2026-09-05): a single embed() call over ~13,729 documents
    reliably preceded the container itself resetting mid-computation on AppSail
    (/health's model_weights reverted to fresh-boot values while the job never
    advanced past this step) -- consistent with an unbounded batch's peak memory
    (fastembed pads to the corpus's longest sequence, times the FULL row count, in
    one call) exceeding a container already documented as memory-constrained.
    Batching bounds that peak and makes progress observable; the final matrix must
    still be exactly equivalent to one big call would have produced."""
    import numpy as np

    from data.vectors import EMBED_BATCH, build_index

    ds.reset_for_tests()
    load_index.cache_clear()

    rows = [{"collection": "fir_narrative", "source_id": str(i), "content": f"doc {i}"}
            for i in range(EMBED_BATCH + 3)]      # forces exactly two batches

    seen_calls = []

    def fake_embed(texts):
        seen_calls.append(len(texts))
        return np.ones((len(texts), 4), dtype=np.float32)

    monkeypatch.setattr("data.vectors.embed", fake_embed)

    progress = []
    result = build_index(rows, on_progress=lambda done, total: progress.append((done, total)))

    assert seen_calls == [EMBED_BATCH, 3], "must embed in EMBED_BATCH-sized chunks, not all at once"
    assert progress == [(EMBED_BATCH, EMBED_BATCH + 3), (EMBED_BATCH + 3, EMBED_BATCH + 3)]
    assert result == {"written": EMBED_BATCH + 3, "embedded": EMBED_BATCH + 3, "remaining": 0}

    ds.reset_for_tests()
    load_index.cache_clear()
    assert build_index(DOCS)["written"] == 4         # restore this module's shared index


def test_build_index_reuses_unchanged_embeddings_and_resumes_the_rest(monkeypatch):
    """The resumable design's core guarantee: a row whose content hasn't changed since
    the last successful build must NOT be re-embedded (embed() must not even see it),
    and a batch_cap smaller than the backlog must leave the rest for a later call to
    pick up rather than silently dropping it or blocking until it's all done. This is
    also what makes the design survive AppSail restarting the container mid-refresh
    (live-verified 2026-09-05): Data Store, not local disk, is what's actually reused
    on the next call."""
    import numpy as np

    from data.vectors import build_index

    ds.reset_for_tests()
    load_index.cache_clear()

    seen_calls = []

    def fake_embed(texts):
        seen_calls.append(list(texts))
        return np.ones((len(texts), 4), dtype=np.float32)

    monkeypatch.setattr("data.vectors.embed", fake_embed)

    rows = [{"collection": "fir_narrative", "source_id": str(i), "content": f"doc {i}"}
            for i in range(5)]
    first = build_index(rows)
    assert first == {"written": 5, "embedded": 5, "remaining": 0}
    assert seen_calls == [[r["content"] for r in rows]]

    # Same rows, nothing changed: a second call must embed NOTHING.
    seen_calls.clear()
    second = build_index(rows)
    assert second == {"written": 5, "embedded": 0, "remaining": 0}
    assert seen_calls == []

    # One row changes, one is new, one is dropped (no longer present) -- and a
    # batch_cap of 1 must embed only ONE of the two pending rows this call.
    seen_calls.clear()
    updated_rows = (
        [{"collection": "fir_narrative", "source_id": "0", "content": "doc 0 EDITED"}]
        + rows[1:4]        # unchanged; source_id "4" dropped
        + [{"collection": "fir_narrative", "source_id": "5", "content": "doc 5"}]
    )
    third = build_index(updated_rows, batch_cap=1)
    assert third["embedded"] == 1, "only one of the two pending (changed + new) rows"
    assert third["remaining"] == 1, "the other pending row must wait for a later call"
    assert third["written"] == 4, "3 unchanged/reused + 1 embedded this call; the " \
        "still-pending 5th isn't in the index yet"
    assert len(seen_calls) == 1 and len(seen_calls[0]) == 1

    load_index.cache_clear()
    idx = load_index()
    assert "4" not in set(idx["source_id"]), "a row no longer present must be dropped"

    ds.reset_for_tests()
    load_index.cache_clear()
    assert build_index(DOCS)["written"] == 4         # restore this module's shared index
