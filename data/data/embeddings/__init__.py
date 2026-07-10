"""Vector-index build job. Reads the record layer from Postgres and (re)embeds
narratives, MO descriptions, and criminal profiles into document_embedding.
Community summaries are indexed after GDS Louvain runs (see data/graph)."""
