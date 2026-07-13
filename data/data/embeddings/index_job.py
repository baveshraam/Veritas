"""Build the vector index from the loaded record layer.

Two collections:
  fir_narrative     one document per case, from `CaseMaster.BriefFacts`.
  criminal_profile  one synthesized document per resolved person — identity plus the
                    crimes they are accused in. This is what "find similar offenders"
                    and the Copilot's "cases like this one" retrieve over.

There is no separate `mo` collection any more. The organizers' ER has no modus-operandi
column — the method of operation is stated inside `BriefFacts`, so MO similarity *is*
narrative similarity, and a second collection over the same text would only have been two
names for one index.

The whole index is rebuilt in one pass, never patched: `data.vectors.build_index` writes a
single Stratus object, and an embedding that outlives the case it was made from is a
citation to a deleted record.

    python -m data.embeddings.index_job
"""
from .. import ds
from ..vectors import build_index


def fir_documents() -> list[dict]:
    rows = ds.query('SELECT "CaseMasterID", "BriefFacts" FROM "CaseMaster"')
    return [{"collection": "fir_narrative", "source_id": str(r["CaseMasterID"]),
             "content": r["BriefFacts"]}
            for r in rows if (r["BriefFacts"] or "").strip()]


def profile_documents() -> list[dict]:
    """One document per person who has been accused of something.

    The join is over `vx_accused_identity`, not `Accused` — that is the whole point. On
    the raw ER an offender in four cases is four unrelated rows, so a profile built from
    them would describe four first-timers instead of one habitual offender.
    """
    rows = ds.query(
        'SELECT "vx_person"."PersonUID", "vx_person"."CanonicalName", '
        '       "vx_person"."GangAffiliation", "CrimeSubHead"."CrimeHeadName" '
        'FROM "vx_accused_identity" '
        'JOIN "vx_person" ON "vx_accused_identity"."PersonUID" = "vx_person"."PersonUID" '
        'JOIN "Accused" ON "vx_accused_identity"."AccusedMasterID" = "Accused"."AccusedMasterID" '
        'JOIN "CaseMaster" ON "Accused"."CaseMasterID" = "CaseMaster"."CaseMasterID" '
        'JOIN "CrimeSubHead" '
        '  ON "CaseMaster"."CrimeMinorHeadID" = "CrimeSubHead"."CrimeSubHeadID"'
    )
    by_person: dict[int, dict] = {}
    for r in rows:
        p = by_person.setdefault(r["PersonUID"], {
            "name": r["CanonicalName"], "gang": r["GangAffiliation"], "crimes": set()})
        if r["CrimeHeadName"]:
            p["crimes"].add(r["CrimeHeadName"])

    return [{"collection": "criminal_profile", "source_id": str(uid),
             "content": _profile_text(p)} for uid, p in by_person.items()]


def _profile_text(p: dict) -> str:
    crimes = ", ".join(sorted(p["crimes"])) or "unspecified offences"
    group = f" Associated with {p['gang']}." if p["gang"] else ""
    return f"{p['name']}. Accused in cases of {crimes}.{group}"


def run_all() -> dict[str, int]:
    firs, profiles = fir_documents(), profile_documents()
    build_index(firs + profiles)
    return {"fir_narrative": len(firs), "criminal_profile": len(profiles)}


if __name__ == "__main__":
    print("indexed:", run_all())
