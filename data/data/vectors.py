"""Vector store: self-hosted embedder + hybrid (dense + lexical) search.

Embeddings are computed locally via fastembed (ONNX bge-small-en-v1.5, 384-dim) — no FIR
content leaves the network, per the architecture. packages/rag_agent's Vector Search Agent
calls `hybrid_search`; the index job calls `build_index`.

There is no pgvector any more, and no Catalyst service that replaces it: QuickML's RAG is
a managed upload-your-documents pipeline with no arbitrary-embedding store and no custom
retrieval hook, so HippoRAG's Personalized-PageRank seeding could not run inside it. Under
the organizers' clarification — where no Catalyst service exists for a capability, an
external or self-hosted implementation is permitted — the index stays ours.

So it is a single **Stratus** object: one `.npz` holding the id/collection/content arrays
and the embedding matrix. Search is `matrix @ query` in numpy, in-process.

That is not a downgrade at this scale, it is the correct read of it. 24k narratives x 384
float32 is ~37 MB — one blob fetch on a cold container, then every query is a dense
matrix-vector product over RAM. An ANN index (HNSW, IVF) exists to avoid scanning the
corpus; scanning this corpus takes single-digit milliseconds. Approximation would cost
recall and buy nothing.

# ponytail: exact brute-force cosine. It is O(N) per query and stops being free somewhere
# north of a million documents — at which point the fix is an HNSW index inside this same
# module (hnswlib over the same matrix), not a different store. Every caller goes through
# hybrid_search().
"""
from __future__ import annotations

import io
import logging
import math
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np

log = logging.getLogger(__name__)

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384

_STRATUS_BUCKET = "veritas-cache"
_INDEX_KEY = "vectors/document_embedding.npz"


def _local_index() -> Path:
    """Read from the environment on every call, not at import. A path frozen at import time
    cannot be redirected by a test, and the offline backend is the one every test uses."""
    return Path(os.getenv("VERITAS_VECTOR_INDEX", ".veritas/document_embedding.npz"))

_TOKEN = re.compile(r"[a-z0-9]+")


@lru_cache(maxsize=1)
def _embedder():
    # Lazy: loading the ONNX model is ~130MB on first run, cached after.
    from data.nlp.model_fetch import ensure_models
    ensure_models()                    # no-op locally; File Store fetch on AppSail
    from fastembed import TextEmbedding
    cache_dir = os.getenv("VERITAS_FASTEMBED_CACHE")
    kwargs = {"cache_dir": cache_dir} if cache_dir else {}
    # `threads`: onnxruntime otherwise sizes its intra-op thread pool off the HOST's
    # full CPU count, not the container's actual cgroup-limited allocation -- a
    # well-known Docker/onnxruntime interaction. Live verification (2026-09-05): RSS
    # jumped ~1000MB on the very first 512-document batch (438MB -> 1430MB) for a
    # ~130MB ONNX model on short text, wildly disproportionate to the workload and
    # consistent with an oversized thread pool each allocating its own scratch
    # buffers, on a container documented as memory-constrained (whisper + NLLB +
    # the Data Store mirror already resident, "2048MB = FLOOR not ceiling").
    threads = int(os.getenv("VERITAS_FASTEMBED_THREADS", "1"))
    return TextEmbedding(model_name=EMBED_MODEL, threads=threads, **kwargs)


def embed(texts: list[str]) -> np.ndarray:
    """L2-normalised embeddings, so cosine similarity is a plain dot product."""
    m = np.asarray([v for v in _embedder().embed(texts)], dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.maximum(norms, 1e-9)


def embed_one(text_in: str) -> np.ndarray:
    return embed([text_in])[0]


def _bucket():
    try:
        import zcatalyst_sdk
        return zcatalyst_sdk.initialize().stratus().bucket(_STRATUS_BUCKET)
    except Exception:
        return None


EMBED_BATCH = 512   # documents per embed() call — see build_index's own docstring

# ------------------------------------------------------------------------------- build
def build_index(rows: Iterable[dict], on_progress=None) -> int:
    """rows: {collection, source_id, content}. Embeds every row and replaces the index.

    Rebuilt whole, never patched. The index is derived from the record layer, and an
    embedding that outlives the FIR it was made from is a citation to a deleted record —
    the one failure a citation-grounded system must never have.

    Embeds in bounded-size batches, not one call over the whole corpus. Live verification
    (2026-09-05): a single `embed()` call over ~13,729 documents reliably preceded the
    container itself resetting (`/health`'s `model_weights` reverted to fresh-boot values
    mid-computation, with the API otherwise staying responsive throughout — consistent
    with the platform killing a process that spiked memory, not a hang). fastembed/
    onnxruntime pads a batch to its longest sequence, so one all-at-once call's peak
    memory scales with the SINGLE longest narrative in the whole corpus times the FULL
    row count at once, on a container already documented as memory-constrained (whisper +
    NLLB + the Data Store mirror already resident, "2048MB = FLOOR not ceiling" per
    CLAUDE.md's cost posture). `on_progress(done, total)`, if given, is called after each
    batch — the caller can use it to make this observable mid-run, since AppSail exposes
    no runtime logs.
    """
    rows = [r for r in rows if r.get("content")]
    if not rows:
        return 0

    texts = [r["content"] for r in rows]
    parts = []
    for start in range(0, len(texts), EMBED_BATCH):
        parts.append(embed(texts[start:start + EMBED_BATCH]))
        if on_progress is not None:
            on_progress(min(start + EMBED_BATCH, len(texts)), len(texts))
    matrix = np.concatenate(parts, axis=0)
    buf = io.BytesIO()
    np.savez_compressed(
        buf,
        source_id=np.asarray([str(r["source_id"]) for r in rows]),
        collection=np.asarray([str(r["collection"]) for r in rows]),
        content=np.asarray([r["content"] for r in rows]),
        matrix=matrix,
    )
    blob = buf.getvalue()

    b = _bucket()
    if b is not None:
        b.put_object(_INDEX_KEY, blob)
    else:
        path = _local_index()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)

    load_index.cache_clear()
    return len(rows)


@lru_cache(maxsize=1)
def load_index() -> dict:
    """The whole index, from Stratus on Catalyst and from disk locally. Cached per process."""
    b = _bucket()
    blob = None
    if b is not None:
        try:
            blob = b.get_object(_INDEX_KEY).read()
        except Exception as e:
            log.warning("Stratus vector index miss (%s)", e)
    path = _local_index()
    if blob is None and path.exists():
        blob = path.read_bytes()
    if blob is None:
        return {"source_id": np.array([]), "collection": np.array([]),
                "content": np.array([]), "matrix": np.zeros((0, EMBED_DIM), np.float32),
                "idf": {}}

    z = np.load(io.BytesIO(blob), allow_pickle=False)
    idx = {k: z[k] for k in ("source_id", "collection", "content", "matrix")}
    idx["idf"] = _idf(idx["content"])
    return idx


def _idf(contents: np.ndarray) -> dict[str, float]:
    """Document frequencies for the lexical half. Computed once per index load."""
    n = len(contents)
    df: Counter[str] = Counter()
    for c in contents:
        df.update(set(_TOKEN.findall(str(c).lower())))
    return {t: math.log(1 + n / (1 + d)) for t, d in df.items()}


# ------------------------------------------------------------------------------ search
def hybrid_search(query: str, collection: str | None = None, k: int = 5,
                  alpha: float = 0.6) -> list[dict]:
    """Blend of dense (cosine) and lexical (IDF-weighted term overlap) scores.

    `alpha` weights the dense half. Dense retrieval alone misses exact identifiers — a
    crime number, an IPC section, a name — which is exactly what an investigator types.
    Returns [{source_id, collection, content, score}].
    """
    idx = load_index()
    if len(idx["source_id"]) == 0:
        return []

    mask = (idx["collection"] == collection) if collection else np.ones(
        len(idx["source_id"]), dtype=bool)
    if not mask.any():
        return []

    dense = idx["matrix"][mask] @ embed_one(query)          # both sides L2-normalised
    lexical = _lexical_scores(query, idx["content"][mask], idx["idf"])
    score = alpha * dense + (1 - alpha) * lexical

    order = np.argsort(-score)[:k]
    sid, coll, content = idx["source_id"][mask], idx["collection"][mask], idx["content"][mask]
    return [{"source_id": str(sid[i]), "collection": str(coll[i]),
             "content": str(content[i]), "score": float(score[i])} for i in order]


def _lexical_scores(query: str, contents: np.ndarray, idf: dict[str, float]) -> np.ndarray:
    """Share of the query's IDF mass present in each document. 0..1, so it is on the same
    scale as cosine and `alpha` means what it says."""
    terms = set(_TOKEN.findall(query.lower()))
    if not terms:
        return np.zeros(len(contents), dtype=np.float32)
    weights = {t: idf.get(t, 1.0) for t in terms}
    total = sum(weights.values()) or 1.0

    out = np.zeros(len(contents), dtype=np.float32)
    for i, c in enumerate(contents):
        toks = set(_TOKEN.findall(str(c).lower()))
        out[i] = sum(w for t, w in weights.items() if t in toks) / total
    return out


if __name__ == "__main__":   # self-check: exact-identifier recall is why this is hybrid
    docs = [
        {"collection": "fir", "source_id": "1",
         "content": "Chain snatching near Kolar bus stand, two men on a motorcycle."},
        {"collection": "fir", "source_id": "2",
         "content": "Burglary at a jewellery shop in Hubballi, IPC 457 registered."},
        {"collection": "fir", "source_id": "3",
         "content": "Cheating case, accused Ramesh Gowda collected deposits in Mysuru."},
    ]
    assert build_index(docs) == 3

    hits = hybrid_search("motorcycle chain snatching", k=2)
    assert hits[0]["source_id"] == "1", hits

    # The lexical half exists for this: a rare identifier a dense model has no notion of.
    hits = hybrid_search("IPC 457", k=1)
    assert hits[0]["source_id"] == "2", hits

    hits = hybrid_search("Ramesh Gowda", collection="fir", k=1)
    assert hits[0]["source_id"] == "3", hits
    print(f"vectors.py OK ({len(load_index()['source_id'])} docs indexed)")
