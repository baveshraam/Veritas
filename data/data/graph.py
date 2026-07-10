"""Neo4j access. `get_driver()` is the only sanctioned way in.

    from data.graph import get_driver
    with get_driver().session() as s:
        s.run("MATCH (p:Person) RETURN p LIMIT 1")
"""
from functools import lru_cache
from pathlib import Path

from neo4j import Driver, GraphDatabase

from .config import get_settings

_CYPHER_DIR = Path(__file__).resolve().parent.parent / "graph"


@lru_cache(maxsize=1)
def get_driver() -> Driver:
    s = get_settings()
    return GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))


def init_graph() -> None:
    """Apply constraints/indexes from graph/*.cypher in filename order. Idempotent."""
    with get_driver().session() as session:
        for path in sorted(_CYPHER_DIR.glob("*.cypher")):
            for stmt in _split_statements(path.read_text(encoding="utf-8")):
                session.run(stmt)


def _split_statements(cypher: str) -> list[str]:
    no_comments = "\n".join(ln.split("//", 1)[0] for ln in cypher.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


if __name__ == "__main__":  # `python -m data.graph`
    init_graph()
    print("graph constraints applied")
