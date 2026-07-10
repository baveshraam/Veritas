"""Persist a generated Dataset to Postgres.

Row-mapping is pure (`*_rows` return list[dict]) so column coverage is testable
without a database; `load_dataset` is the thin executemany layer. Geometry WKT is
wrapped in ST_GeomFromText on the way in; ipc_sections goes in as a Python list
(psycopg adapts to text[]).
"""
from dataclasses import asdict

from sqlalchemy import text

from ..db import get_session
from .build import Dataset

# Insert order respects FKs: officer/person before fir; fir before criminal_record.
_OFFICER_COLS = ["officer_id", "badge_no", "name", "ps_code", "district_code", "role"]
_PERSON_COLS = ["person_id", "scrb_id", "name_en", "name_kn", "dob", "gender",
                "aadhaar_hash", "criminal_history", "risk_score", "gang_affiliation",
                "canonical_entity_id", "address_geom"]
_FIR_COLS = ["fir_id", "ps_code", "district_code", "fir_number", "date_filed",
             "ipc_sections", "crime_type", "occurrence_from", "occurrence_to",
             "district", "taluk", "complainant_id", "io_id", "case_status",
             "modus_operandi", "narrative", "location_geom"]
_RECORD_COLS = ["record_id", "person_id", "fir_id", "role", "arrest_date",
                "bail_status", "conviction"]


def officer_rows(ds: Dataset) -> list[dict]:
    return [asdict(o) for o in ds.officers]


def person_rows(ds: Dataset) -> list[dict]:
    return [asdict(p) for p in ds.persons]


def fir_rows(ds: Dataset) -> list[dict]:
    return [asdict(f) for f in ds.firs]


def record_rows(ds: Dataset) -> list[dict]:
    return [asdict(r) for r in ds.criminal_records]


def _insert_sql(table: str, cols: list[str], geom_col: str | None = None) -> str:
    values = []
    for c in cols:
        if c == geom_col:
            values.append(f"ST_GeomFromText(:{c}, 4326)")
        else:
            values.append(f":{c}")
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(values)})"


def load_dataset(ds: Dataset, wipe: bool = True) -> None:
    with get_session() as s:
        if wipe:
            # only the generated record layer — leaves district_socioeconomic
            # (real data) and the session/audit tables untouched.
            s.execute(text("TRUNCATE criminal_record, fir, person, officer CASCADE"))
        s.execute(text(_insert_sql("officer", _OFFICER_COLS)), officer_rows(ds))
        s.execute(text(_insert_sql("person", _PERSON_COLS, "address_geom")), person_rows(ds))
        s.execute(text(_insert_sql("fir", _FIR_COLS, "location_geom")), fir_rows(ds))
        s.execute(text(_insert_sql("criminal_record", _RECORD_COLS)), record_rows(ds))
