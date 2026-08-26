"""score_identity.py recomputes entity-resolution F1 against a persisted answer key,
instead of only against a `generate()` call still sitting in-process (the gap
`docs/DATA_GENERATION_AUDIT.md` §19 names: the AML labels survive to disk, the identity
answer key didn't). These tests drive it exactly the way `test_financial.py` drives the
AML labels: against the real `dataset` fixture, not a hand-built fixture."""
import json

from data.generator.score_identity import score


def test_score_matches_the_known_good_reconstruction(dataset, tmp_path):
    """Same bar fellegi_sunter.py's own self-check enforces (precision>=0.80,
    recall>=0.50) — this is the same reconstruction, scored a second way."""
    path = tmp_path / "identity_answer_key.json"
    path.write_text(json.dumps(dataset.accused_truth))

    precision, recall, f1 = score(path)

    assert precision >= 0.80, f"too many false links: precision={precision:.3f}"
    assert recall >= 0.50, f"missing most true links: recall={recall:.3f}"
    assert f1 > 0


def test_score_is_perfect_when_the_key_matches_reality_exactly(dataset, tmp_path):
    """A degenerate but meaningful case: score the resolved identities against
    themselves. If the pair-counting math were wrong, this is where it would show —
    a self-comparison must be precision=recall=f1=1.0, not merely 'close'."""
    from data import ds

    got = {str(r["AccusedMasterID"]): r["PersonUID"]
           for r in ds.query('SELECT "AccusedMasterID", "PersonUID" FROM "vx_accused_identity"')}
    path = tmp_path / "identity_answer_key.json"
    path.write_text(json.dumps(got))

    precision, recall, f1 = score(path)
    assert (precision, recall, f1) == (1.0, 1.0, 1.0)


def test_score_warns_but_does_not_crash_on_a_stale_key(dataset, tmp_path, capsys):
    """A key from a different generation run won't cover every current AccusedMasterID —
    this must degrade to 'score what overlaps', not raise."""
    path = tmp_path / "identity_answer_key.json"
    path.write_text(json.dumps({"999999999": 1}))

    precision, recall, f1 = score(path)

    assert (precision, recall, f1) == (0.0, 0.0, 0.0)
    assert "warning" in capsys.readouterr().out
