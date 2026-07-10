"""Connection settings, read from the environment once.

Single source for every DSN so no module hardcodes a connection string.
Defaults target a local docker-compose dev stack; override via env in prod.
"""
import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    postgres_dsn: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        postgres_dsn=os.getenv(
            "VERITAS_POSTGRES_DSN",
            "postgresql+psycopg://veritas:veritas@localhost:5432/veritas",
        ),
        neo4j_uri=os.getenv("VERITAS_NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("VERITAS_NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("VERITAS_NEO4J_PASSWORD", "veritas-dev"),
    )
