"""Vector helpers + a regression guard against the SQLAlchemy `:param::type` bug."""
import re
from pathlib import Path

from data.vectors import EMBED_DIM, _vec_literal

_PKG = Path(__file__).resolve().parent.parent / "data"


def test_vec_literal_format():
    lit = _vec_literal([0.1, -0.2, 0.3])
    assert lit.startswith("[") and lit.endswith("]")
    assert lit.count(",") == 2
    assert EMBED_DIM == 384


def test_no_colon_colon_casts_in_any_helper():
    # SQLAlchemy text() silently drops `:name` when followed by `::` — every cast
    # must be CAST(:name AS type). This scans all helper modules so the bug that
    # broke the embedding upsert can't reappear anywhere.
    offenders = []
    for py in _PKG.glob("*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r":\w+::\w+", line):
                offenders.append(f"{py.name}:{i}")
    assert not offenders, f"`:param::type` casts found (use CAST): {offenders}"
