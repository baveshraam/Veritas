"""Hybrid retrieval over the Stratus index.

pgvector is gone, and the reason the replacement is *hybrid* rather than pure dense is the
thing worth testing: an officer types a crime number or an IPC section, and a dense model
has no notion of either. The lexical half is what makes an exact identifier findable.
"""
import pytest

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
def index(tmp_path_factory):
    import os
    os.environ["VERITAS_VECTOR_INDEX"] = str(tmp_path_factory.mktemp("v") / "idx.npz")
    load_index.cache_clear()
    assert build_index(DOCS) == 4


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
    import numpy as np
    from data import vectors
    load_index.cache_clear()
    original = vectors._bucket
    vectors._bucket = lambda: None
    try:
        import os
        os.environ["VERITAS_VECTOR_INDEX"] = "/nonexistent/idx.npz"
        vectors._LOCAL_INDEX = __import__("pathlib").Path("/nonexistent/idx.npz")
        load_index.cache_clear()
        assert hybrid_search("anything") == []
    finally:
        vectors._bucket = original
        load_index.cache_clear()


def test_build_index_embeds_in_bounded_batches_not_one_giant_call(monkeypatch, tmp_path):
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

    rows = [{"collection": "fir_narrative", "source_id": str(i), "content": f"doc {i}"}
            for i in range(EMBED_BATCH + 3)]      # forces exactly two batches

    seen_calls = []

    def fake_embed(texts):
        seen_calls.append(len(texts))
        return np.ones((len(texts), 4), dtype=np.float32)

    monkeypatch.setattr("data.vectors.embed", fake_embed)
    monkeypatch.setattr("data.vectors._bucket", lambda: None)
    monkeypatch.setenv("VERITAS_VECTOR_INDEX", str(tmp_path / "idx.npz"))
    load_index.cache_clear()

    progress = []
    n = build_index(rows, on_progress=lambda done, total: progress.append((done, total)))

    assert seen_calls == [EMBED_BATCH, 3], "must embed in EMBED_BATCH-sized chunks, not all at once"
    assert progress == [(EMBED_BATCH, EMBED_BATCH + 3), (EMBED_BATCH + 3, EMBED_BATCH + 3)]
    assert n == EMBED_BATCH + 3
