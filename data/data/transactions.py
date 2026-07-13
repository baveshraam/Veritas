"""Writes made by packages/ml_models back onto the record layer.

Only one is left: the AML flag. Entity resolution used to write here too
(`set_canonical_entity`, `write_same_as_edge`), but on the organizers' ER identity is not
an amendment to a person row — there is no person row. Resolution *constructs* the people
(`vx_person`) and their mapping (`vx_accused_identity`) wholesale, so it owns those tables
outright and writes them itself. Nothing to reconcile, nothing to keep in sync, and the
SAME_AS edge is gone with the duplicate it used to point at.
"""
from . import ds


def flag_transaction(txn_id: int, flag_type: str, detector: str, confidence: float) -> None:
    """Mark a transaction suspicious. `detector` names which model fired — a flag a court
    cannot attribute to a method is not evidence."""
    ds.update("vx_txn", "TxnID", [{
        "TxnID": int(txn_id), "FlaggedSuspicious": True, "FlagType": flag_type,
        "Detector": detector, "FlagConfidence": float(confidence),
    }])


def clear_flags() -> None:
    """Wipe every flag before a detector re-runs. Flags are derived, and a stale one points
    an investigator at a transaction the current model does not consider suspicious."""
    ds.execute('UPDATE "vx_txn" SET "FlaggedSuspicious" = false, "FlagType" = NULL, '
               '"Detector" = NULL, "FlagConfidence" = NULL '
               'WHERE "FlaggedSuspicious" = true')
