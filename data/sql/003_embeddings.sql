-- Vector store (pgvector). One table, four logical collections (FIR narratives,
-- MO descriptions, criminal profiles, GraphRAG community summaries). 384-dim to
-- match the self-hosted bge-small-en-v1.5 ONNX embedder (data.vectors).
-- packages/rag_agent queries this (hybrid dense + BM25); the index job in
-- data/embeddings populates it.

CREATE TABLE IF NOT EXISTS document_embedding (
    embedding_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    collection   VARCHAR(40) NOT NULL,   -- fir_narrative | mo | criminal_profile | community_summary
    source_id    VARCHAR(64) NOT NULL,   -- fir_id / person_id / community_id
    content      TEXT NOT NULL,
    embedding    vector(384) NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (collection, source_id)
);

-- Cosine HNSW: no training data needed, good recall out of the box (pgvector >= 0.5).
CREATE INDEX IF NOT EXISTS idx_docemb_hnsw
    ON document_embedding USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_docemb_collection ON document_embedding (collection);

-- BM25/lexical half of the hybrid retrieval: a tsvector over content.
CREATE INDEX IF NOT EXISTS idx_docemb_fts
    ON document_embedding USING gin (to_tsvector('english', content));
