"""Connection settings, read from the environment once.

Single source for every DSN so no module hardcodes a connection string.
Defaults target a local docker-compose dev stack; override via env in prod.
"""
import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    postgres_dsn: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # One store now: the knowledge graph is an edge-list table in the same database
    # (see data.graph), so there is no second DSN to configure.
    return Settings(
        postgres_dsn=os.getenv(
            "VERITAS_POSTGRES_DSN",
            "postgresql+psycopg://veritas:veritas@localhost:5432/veritas",
        ),
    )
