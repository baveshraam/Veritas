"""NLP wrapper checks — no external model weights required."""
import pytest

from data.nlp import ner_extract, transliterate
from data.nlp.translate import TranslationUnavailable, translate


def _labels(text):
    return {(e.label, e.text) for e in ner_extract(text)}


def test_ner_extracts_each_entity_type():
    q = ("Was Ramesh Gowda accused under IPC 302 in Kolar, and is he linked to "
         "the KGF Syndicate vehicle KA 05 MJ 1234?")
    got = _labels(q)
    assert ("PERSON", "Ramesh Gowda") in got        # not "Was Ramesh"
    assert ("IPC_SECTION", "302") in got
    assert ("LOCATION", "Kolar") in got
    assert ("GANG", "KGF Syndicate") in got
    assert ("VEHICLE", "KA 05 MJ 1234") in got


def test_longest_location_alias_wins():
    # "Bangalore Urban" must not be truncated to the "Bangalore" alias
    assert ("LOCATION", "Bangalore Urban") in _labels("thefts in Bangalore Urban last year")


def test_ner_spans_do_not_overlap():
    ents = ner_extract("Ramesh Gowda in Kolar under IPC 302")
    for a, b in zip(ents, ents[1:]):
        assert a.end <= b.start


def test_transliterate_generates_real_romanisation_drift():
    assert "Ramesha" in transliterate("Ramesh")
    assert "Geeta" in transliterate("Geetha")
    laxmi = transliterate("Lakshmi")
    assert "Laxmi" in laxmi and "Lakshmy" in laxmi
    # and no runaway garbage from chained rules (the Rameshh/Lakshhhmi bug)
    assert not any("hh" in v.lower() for v in transliterate("Ramesh"))


def test_transliterate_preserves_original_first():
    assert transliterate("Manjunath Gowda")[0] == "Manjunath Gowda"
    assert transliterate("") == []


def test_translate_is_noop_same_lang_and_errors_clearly_without_weights():
    assert translate("hello", "en", "en") == "hello"
    with pytest.raises(TranslationUnavailable):
        translate("hello", "en", "kn")


def test_unknown_names_are_still_detected_as_persons():
    """A name outside the KA pool must still be SEEN.

    If NER can't see it, the orchestrator sees no subject in the query and the
    previous turn's person stays in focus — so an officer asking about an unknown
    suspect is silently handed a different person's record.
    """
    got = _labels("Does Zzyzx Qwertius have priors?")
    assert ("PERSON", "Zzyzx Qwertius") in got


def test_query_stopwords_are_not_mistaken_for_names():
    for q in ("Show crime hotspots in Kolar",
              "Trace the money trail",
              "Forecast crime next month"):
        assert not [e for e in ner_extract(q) if e.label == "PERSON"], q
