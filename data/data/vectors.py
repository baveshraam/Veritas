"""Vector store: self-hosted embedder + hybrid (dense + lexical) search.

Embeddings are computed locally via fastembed (ONNX bge-small-en-v1.5, 384-dim) — no FIR
content leaves the network, per the architecture. packages/rag_agent's Vector Search Agent
calls `hybrid_search`; the index job calls `build_index`.

There is no pgvector any more, and no Catalyst service that replaces it: QuickML's RAG is
a managed upload-your-documents pipeline with no arbitrary-embedding store and no custom
retrieval hook, so HippoRAG's Personalized-PageRank seeding could not run inside it. Under
the organizers' clarification — where no Catalyst service exists for a capability, an
external or self-hosted implementation is permitted — the index stays ours.

The index is one row per document in `vx_vector_embedding` (Data Store), not a single
Stratus blob object as originally designed: Stratus bucket creation is scope-blocked on
this org (OAUTH_SCOPE_MISMATCH, console-only fix — CLAUDE.md §2), and local disk turned
out not to be a safe fallback either — live verification (2026-09-05) found AppSail
restarts the container running a background `/jobs/refresh` far more often than assumed,
silently wiping local-disk state and resetting the resumable reindex's progress back to
whatever's baked into the current image, every time. Data Store is the one storage layer
already proven reliable across restarts throughout that investigation (the graph/AML/
cache steps all depend on exactly that). The whole index is still loaded into memory as
one matrix for search — `EMBED_DIM=384 x 24k narratives` is ~37MB, trivial — this only
changes where it's PERSISTED, not how it's searched. Search is `matrix @ query` in numpy,
in-process.

That is not a downgrade at this scale, it is the correct read of it. An ANN index (HNSW,
IVF) exists to avoid scanning the corpus; scanning this corpus takes single-digit
milliseconds. Approximation would cost recall and buy nothing.

# ponytail: exact brute-force cosine. It is O(N) per query and stops being free somewhere
# north of a million documents — at which point the fix is an HNSW index inside this same
# module (hnswlib over the same matrix), not a different store. Every caller goes through
# hybrid_search().
"""
from __future__ import annotations

import base64
import logging
import math
import os
import re
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from typing import Iterable

import numpy as np

from . import ds

log = logging.getLogger(__name__)

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384

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


EMBED_BATCH = 512          # documents per embed() call — see build_index's own docstring
INCREMENTAL_BATCH_CAP = int(os.getenv("VERITAS_REINDEX_BATCH_CAP", "1024"))

# ------------------------------------------------------------------------------- build
def build_index(rows: Iterable[dict], on_progress=None, batch_cap: int | None = None) -> dict:
    """rows: {collection, source_id, content}. Embeds new/changed rows, keeps existing
    embeddings for unchanged ones, drops rows no longer present, and replaces the index.

    Returns `{"written": total rows now in the index, "embedded": newly embedded THIS
    call, "remaining": still-pending rows left for a later call}`.

    Incremental and resumable, not "rebuilt whole" as this used to be. Live verification
    (2026-09-05): embedding the full ~13,729-document corpus in one continuous run —
    even split into EMBED_BATCH-sized `embed()` calls — reliably died at almost the same
    wall-clock point (~60-120s in) across five separate attempts with different
    mitigations (a real SDK-context threading bug fixed along the way, capped ONNX
    threads, bounded per-call memory), consistent with AppSail restarting the background
    thread's container under sustained CPU-bound work rather than a memory ceiling (RSS
    plateaued around 1.4-1.5GB, well under the container's 2GB). No single continuous
    run can be trusted to finish, so the design changed: **each row keeps its existing
    embedding when its content is unchanged, and only new/changed rows are embedded, up
    to `batch_cap` per call** (default `INCREMENTAL_BATCH_CAP`, tunable without a
    redeploy). A row whose (collection, source_id) no longer appears in `rows` is
    dropped — never an embedding that outlives the record it was made from, the one
    failure a citation-grounded system must never have. If more rows need embedding
    than `batch_cap` allows, the remainder is left for the NEXT call (Cron's regular
    cycle, or a manual retry) to pick up — `on_progress(done, total)` reports progress
    within THIS call's own batch, not the full remaining backlog.
    """
    rows = [r for r in rows if r.get("content")]
    if not rows:
        return {"written": 0, "embedded": 0, "remaining": 0}
    cap = INCREMENTAL_BATCH_CAP if batch_cap is None else batch_cap

    existing = load_index()
    existing_by_key = {
        (str(existing["collection"][i]), str(existing["source_id"][i])): i
        for i in range(len(existing["source_id"]))
    }

    kept: list[tuple[dict, int]] = []
    to_embed: list[dict] = []
    for r in rows:
        idx = existing_by_key.get((r["collection"], str(r["source_id"])))
        if idx is not None and str(existing["content"][idx]) == r["content"]:
            kept.append((r, idx))          # unchanged — reuse its existing embedding
        else:
            to_embed.append(r)             # new, or content changed since last embed

    this_round = to_embed[:cap] if cap else to_embed

    texts = [r["content"] for r in this_round]
    parts = []
    for start in range(0, len(texts), EMBED_BATCH):
        parts.append(embed(texts[start:start + EMBED_BATCH]))
        if on_progress is not None:
            on_progress(min(start + EMBED_BATCH, len(texts)), len(texts))
    new_matrix = (np.concatenate(parts, axis=0) if parts
                 else np.zeros((0, EMBED_DIM), np.float32))

    # `kept` rows are already correctly persisted — nothing to write for them. Only
    # `this_round` (new or content-changed) needs a Data Store write, split into
    # INSERT (a (collection, source_id) never seen before) vs UPDATE (content changed
    # since the last successful embed) — ZCQL has no UPSERT.
    now = datetime.now(timezone.utc)
    new_db_rows, changed_db_rows = [], []
    for r, vec in zip(this_round, new_matrix):
        key = (r["collection"], str(r["source_id"]))
        db_row = {
            "EmbeddingKey": f"{key[0]}:{key[1]}",
            "SourceID": key[1], "Collection": key[0], "Content": r["content"],
            "EmbeddingB64": base64.b64encode(np.asarray(vec, np.float32).tobytes()).decode("ascii"),
            "UpdatedAt": now,
        }
        (changed_db_rows if key in existing_by_key else new_db_rows).append(db_row)

    if new_db_rows:
        ds.insert("vx_vector_embedding", new_db_rows)
    if changed_db_rows:
        ds.update("vx_vector_embedding", "EmbeddingKey", changed_db_rows)

    # A (collection, source_id) that existed before but isn't in the CURRENT live rows
    # at all must be dropped — never an embedding that outlives the record it was made
    # from. Rare in practice (case data mostly only grows), so one DELETE per key.
    live_keys = {(r["collection"], str(r["source_id"])) for r in rows}
    for key in existing_by_key:
        if key not in live_keys:
            ds.execute('DELETE FROM "vx_vector_embedding" WHERE "EmbeddingKey" = :k',
                      {"k": f"{key[0]}:{key[1]}"})

    load_index.cache_clear()
    return {"written": len(kept) + len(this_round), "embedded": len(this_round),
            "remaining": len(to_embed) - len(this_round)}


@lru_cache(maxsize=1)
def load_index() -> dict:
    """The whole index, one row per document in `vx_vector_embedding` (Data Store) —
    the storage layer proven reliable across AppSail container restarts (see the
    module docstring). Cached per process; `build_index` clears this cache after a
    write so the next call re-reads the current state."""
    try:
        rows = ds.query('SELECT "SourceID", "Collection", "Content", "EmbeddingB64" '
                        'FROM "vx_vector_embedding"')
    except Exception as e:
        log.warning("vector index read failed (%s)", e)
        rows = []
    if not rows:
        return {"source_id": np.array([]), "collection": np.array([]),
                "content": np.array([]), "matrix": np.zeros((0, EMBED_DIM), np.float32),
                "idf": {}}

    idx = {
        "source_id": np.asarray([r["SourceID"] for r in rows]),
        "collection": np.asarray([r["Collection"] for r in rows]),
        "content": np.asarray([r["Content"] for r in rows]),
        "matrix": np.stack([np.frombuffer(base64.b64decode(r["EmbeddingB64"]), dtype=np.float32)
                            for r in rows]),
    }
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
    assert build_index(docs)["written"] == 3

    hits = hybrid_search("motorcycle chain snatching", k=2)
    assert hits[0]["source_id"] == "1", hits

    # The lexical half exists for this: a rare identifier a dense model has no notion of.
    hits = hybrid_search("IPC 457", k=1)
    assert hits[0]["source_id"] == "2", hits

    hits = hybrid_search("Ramesh Gowda", collection="fir", k=1)
    assert hits[0]["source_id"] == "3", hits
    print(f"vectors.py OK ({len(load_index()['source_id'])} docs indexed)")
