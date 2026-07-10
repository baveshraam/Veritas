"""Postgres/PostGIS access. `get_session()` is the only sanctioned way in.

    from data.db import get_session
    with get_session() as s:
        s.execute(text("SELECT ..."))
"""
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    # pool_pre_ping: the API is long-lived; drop dead connections rather than error.
    return create_engine(get_settings().postgres_dsn, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), class_=Session, expire_on_commit=False)


@contextmanager
def get_session() -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on exception."""
    s = _session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _split_statements(sql: str) -> list[str]:
    # ponytail: naive split on ';' + strip '--' comments to EOL — safe because
    # these files hold no ';' or '--' inside string literals. Revisit for PL/pgSQL.
    no_comments = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def init_db() -> None:
    """Run every sql/*.sql migration in filename order. Idempotent."""
    with get_engine().begin() as conn:
        for path in sorted(_SQL_DIR.glob("*.sql")):
            for stmt in _split_statements(path.read_text(encoding="utf-8")):
                conn.execute(text(stmt))


if __name__ == "__main__":  # `python -m data.db` bootstraps a fresh database
    init_db()
    print(f"applied {len(list(_SQL_DIR.glob('*.sql')))} migration(s)")
