"""Vector store access: self-hosted embedder + hybrid (dense + lexical) search.

Embeddings are computed locally via fastembed (ONNX bge-small-en-v1.5, 384-dim) —
no FIR content leaves the network, per the architecture. packages/rag_agent's
Vector Search Agent calls `hybrid_search`; the index job calls `upsert_embeddings`.
"""
from functools import lru_cache
from typing import Iterable

from sqlalchemy import text

from .db import get_session

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384


@lru_cache(maxsize=1)
def _embedder():
    # Lazy: importing/loading the ONNX model is ~130MB on first run, cached after.
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=EMBED_MODEL)


def embed(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _embedder().embed(texts)]


def embed_one(text_in: str) -> list[float]:
    return embed([text_in])[0]


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


def upsert_embeddings(rows: Iterable[dict]) -> int:
    """rows: {collection, source_id, content}. Embeds content and upserts. Returns count."""
    rows = list(rows)
    if not rows:
        return 0
    vectors = embed([r["content"] for r in rows])
    params = [{
        "collection": r["collection"], "source_id": r["source_id"],
        "content": r["content"], "embedding": _vec_literal(v),
    } for r, v in zip(rows, vectors)]
    with get_session() as s:
        s.execute(text(
            "INSERT INTO document_embedding (collection, source_id, content, embedding) "
            "VALUES (:collection, :source_id, :content, CAST(:embedding AS vector)) "
            "ON CONFLICT (collection, source_id) DO UPDATE SET "
            "  content = EXCLUDED.content, embedding = EXCLUDED.embedding"
        ), params)
    return len(params)


def hybrid_search(query: str, collection: str | None = None, k: int = 5,
                  alpha: float = 0.6) -> list[dict]:
    """Reciprocal-rank-style blend of dense (cosine) and lexical (ts_rank) scores.

    alpha weights the dense half. Returns [{source_id, collection, content, score}].
    """
    qvec = _vec_literal(embed_one(query))
    coll_filter = "AND collection = :coll" if collection else ""
    params = {"qvec": qvec, "q": query, "k": k, "alpha": alpha}
    if collection:
        params["coll"] = collection
    sql = f"""
        WITH dense AS (
            SELECT embedding_id, collection, source_id, content,
                   1 - (embedding <=> CAST(:qvec AS vector)) AS dscore
            FROM document_embedding
            WHERE TRUE {coll_filter}
            ORDER BY embedding <=> CAST(:qvec AS vector)
            LIMIT :k * 4
        ),
        lexical AS (
            SELECT embedding_id,
                   ts_rank(to_tsvector('english', content),
                           plainto_tsquery('english', :q)) AS lscore
            FROM document_embedding
            WHERE to_tsvector('english', content) @@ plainto_tsquery('english', :q)
              {coll_filter}
        )
        SELECT d.source_id, d.collection, d.content,
               (:alpha * d.dscore + (1 - :alpha) * COALESCE(l.lscore, 0)) AS score
        FROM dense d
        LEFT JOIN lexical l USING (embedding_id)
        ORDER BY score DESC
        LIMIT :k
    """
    with get_session() as s:
        rows = s.execute(text(sql), params).all()
    return [{"source_id": r.source_id, "collection": r.collection,
             "content": r.content, "score": float(r.score)} for r in rows]
