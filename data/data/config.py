"""Veritas configuration — read from the environment once.

All data access goes through data.ds (ZCQL → Catalyst Data Store | SQLite).
This module exists only for any non-database settings that need a single source.
"""
import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    catalyst_project_id: str
    catalyst_org: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        catalyst_project_id=os.getenv("CATALYST_PROJECT_ID", "52852000000013048"),
        catalyst_org=os.getenv("CATALYST_ORG", "60077763394"),
    )
