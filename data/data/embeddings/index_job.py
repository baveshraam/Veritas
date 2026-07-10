"""Build the vector collections from the loaded Postgres record layer.

Rerunnable and incremental (upsert on (collection, source_id)). Called at the end
of a full rebuild and standalone via `python -m data.embeddings.index_job`.
"""
from sqlalchemy import text

from ..db import get_session
from ..vectors import upsert_embeddings


def index_fir_narratives() -> int:
    with get_session() as s:
        rows = s.execute(text(
            "SELECT fir_id, narrative FROM fir WHERE narrative IS NOT NULL AND narrative <> ''"
        )).all()
    return upsert_embeddings(
        {"collection": "fir_narrative", "source_id": str(r.fir_id), "content": r.narrative}
        for r in rows)


def index_mo() -> int:
    with get_session() as s:
        rows = s.execute(text(
            "SELECT fir_id, modus_operandi FROM fir "
            "WHERE modus_operandi IS NOT NULL AND modus_operandi <> ''"
        )).all()
    return upsert_embeddings(
        {"collection": "mo", "source_id": str(r.fir_id), "content": r.modus_operandi}
        for r in rows)


def index_criminal_profiles() -> int:
    """One synthesized profile per person with a record: identity + the crimes they're
    accused in + gang. This is what 'find similar offenders' retrieves over."""
    with get_session() as s:
        rows = s.execute(text(
            "SELECT p.person_id, p.name_en, p.gender, p.gang_affiliation, "
            "  array_agg(DISTINCT f.crime_type) AS crimes "
            "FROM person p "
            "JOIN criminal_record cr ON cr.person_id = p.person_id "
            "JOIN fir f ON f.fir_id = cr.fir_id "
            "GROUP BY p.person_id, p.name_en, p.gender, p.gang_affiliation"
        )).all()
    return upsert_embeddings(
        {"collection": "criminal_profile", "source_id": str(r.person_id),
         "content": _profile_text(r)} for r in rows)


def _profile_text(r) -> str:
    gang = f" Affiliated with {r.gang_affiliation}." if r.gang_affiliation else ""
    crimes = ", ".join(c for c in (r.crimes or []) if c)
    return (f"{r.name_en}, {r.gender}. Habitual offender accused in cases of "
            f"{crimes}.{gang}")


def run_all() -> dict[str, int]:
    counts = {
        "fir_narrative": index_fir_narratives(),
        "mo": index_mo(),
        "criminal_profile": index_criminal_profiles(),
    }
    return counts


if __name__ == "__main__":
    print("indexed:", run_all())
