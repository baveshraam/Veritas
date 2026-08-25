"""NLP wrapper checks — no external model weights required."""
import pytest

from data.nlp import ner_extract, transliterate
from data.nlp.translate import TranslationUnavailable, translate


def _labels(text):
    return {(e.label, e.text) for e in ner_extract(text)}


def test_ner_extracts_each_entity_type():
    q = ("Was Ramesh Gowda accused under IPC 302 in Kolar, "
         "and was vehicle KA 05 MJ 1234 involved?")
    got = _labels(q)
    assert ("PERSON", "Ramesh Gowda") in got        # not "Was Ramesh"
    assert ("IPC_SECTION", "302") in got
    assert ("LOCATION", "Kolar") in got
    assert ("VEHICLE", "KA 05 MJ 1234") in got


def test_there_is_no_gang_entity():
    """Deliberate. The organizers' ER records no gang, so a GANG entity would have nothing
    to resolve against — organised-crime grouping is the Louvain community over co-offending,
    reached through a person. A gazetteer of invented gang names would match only invented
    gangs, which is worse than not having the label."""
    from data.nlp.entities import Entity
    import typing
    labels = typing.get_args(Entity.model_fields["label"].annotation)
    assert "GANG" not in labels


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


def test_translate_is_noop_same_lang_and_errors_clearly_without_weights(monkeypatch):
    assert translate("hello", "en", "en") == "hello"
    with pytest.raises(TranslationUnavailable):
        translate("hello", "en", "fr")  # unsupported pair — no model load, so this
                                         # stays hermetic even when torch/transformers
                                         # (and real weights) happen to be installed

    # The "weights genuinely unavailable" contract, forced deterministically rather
    # than by relying on this host lacking torch/transformers — which it may not.
    # importlib.import_module (not `import data.nlp.translate as ...`) because
    # data.nlp's __init__ re-exports the `translate` function under the same name,
    # which shadows the submodule as an attribute of the `data.nlp` package.
    import importlib
    translate_mod = importlib.import_module("data.nlp.translate")
    monkeypatch.setattr(translate_mod, "_load",
                         lambda: (_ for _ in ()).throw(TranslationUnavailable("no weights")))
    with pytest.raises(TranslationUnavailable):
        translate("hello", "en", "kn")


def test_translate_warm_forces_the_same_lazy_load_the_first_query_would(monkeypatch):
    """BUG-016: warm() exists so a container pays the cold-load cost during startup,
    not on an officer's first Kannada query. It must call the exact same _load() the
    request path uses — not a separate, possibly-drifting warm-up path."""
    import importlib
    translate_mod = importlib.import_module("data.nlp.translate")

    calls = []
    monkeypatch.setattr(translate_mod, "_load", lambda: calls.append(1))
    translate_mod.warm()
    assert calls == [1]


def test_backend_status_does_not_force_a_load():
    import importlib
    translate_mod = importlib.import_module("data.nlp.translate")
    translate_mod._load.cache_clear()
    assert translate_mod.backend_status() == "not yet loaded"
    assert translate_mod._load.cache_info().currsize == 0


def test_model_fetch_status_is_honest_about_why_it_never_ran(monkeypatch):
    from data.nlp import model_fetch

    monkeypatch.delenv("VERITAS_MODELS_FOLDER_ID", raising=False)
    monkeypatch.setattr(model_fetch, "_DONE", False)
    assert "not configured" in model_fetch.status()

    monkeypatch.setenv("VERITAS_MODELS_FOLDER_ID", "123")
    assert model_fetch.status() == "configured, not yet fetched"

    monkeypatch.setattr(model_fetch, "_DONE", True)
    assert "fetched from Catalyst File Store" in model_fetch.status()


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
