"""NLP wrapper checks — no external model weights required."""
import pytest

from data.nlp import ner_extract, transliterate
from data.nlp.translate import (
    TranslationUnavailable, translate, _protect_spans, _restore_spans,
    _resolve_plural_markers,
)


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


def test_a_leading_comparison_verb_does_not_merge_into_the_name():
    """Found live: "Compare Usha Naika and Netrawathi Nanjappa" merged the sentence-
    initial "Compare" into the following name span ("Compare Usha Naika" as ONE
    PERSON entity, "Usha" being pool-matched and the left-extension only excluding
    known stopwords), so the resulting lookup found nobody and the whole two-entity
    comparison feature refused with "No person of that name appears in the records"
    even though both people are real. "did"/"was" etc. were already excluded for
    exactly this reason; "compare"/"compared"/"versus"/"vs" were not."""
    got = _labels("Compare Usha Naika and Netrawathi Nanjappa")
    assert ("PERSON", "Usha Naika") in got
    assert ("PERSON", "Netrawathi Nanjappa") in got
    assert not any(text.startswith("Compare ") for label, text in got if label == "PERSON")


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


def test_a_surname_outside_the_pool_is_not_clipped_off_a_known_first_name():
    """Found live: 'Tell me more about Usha Naika' resolved to a DIFFERENT 'Usha' in
    the database (whichever had the most records) because NER saw only 'Usha' —
    'Naika' isn't in ka_names.csv's surname sample. The wrong person's full criminal
    history was then answered at high confidence, with nothing to indicate a
    substitution had happened. 'Usha' alone is in the pool; 'Naika' alone is not."""
    got = _labels("Tell me more about Usha Naika.")
    assert ("PERSON", "Usha Naika") in got


def test_query_stopwords_are_not_mistaken_for_names():
    for q in ("Show crime hotspots in Kolar",
              "Trace the money trail",
              "Forecast crime next month"):
        assert not [e for e in ner_extract(q) if e.label == "PERSON"], q


# --- code-switched translation: protecting identifiers from the MT model ----------
#
# A KSP officer types FIR numbers, IPC codes and vehicle plates in Latin script inside
# an otherwise-Kannada sentence — the ordinary way of speaking, not an edge case. NLLB
# translates the whole string with no notion that a digit run is a record identifier;
# measured directly against the real model (see data/data/nlp/translate.py's module
# comment), the number itself usually survives on its own, but leaving that to the
# model's discretion is not a guarantee a police tool can stand behind. These tests
# check the guarantee structurally, with a fake backend under our own control, rather
# than depending on a specific model's current behaviour.

def test_protect_spans_finds_fir_numbers_ipc_codes_and_plates():
    text = 'FIR 100222201202600022, IPC 302, vehicle KA 05 MJ 1234'
    protected, mapping = _protect_spans(text)
    assert '100222201202600022' not in protected
    assert 'KA 05 MJ 1234' not in protected
    assert set(mapping.values()) == {'100222201202600022', '302', 'KA 05 MJ 1234'}


def test_protect_then_restore_spans_round_trips_exactly():
    text = 'ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ FIR 100222201202600022, IPC 302 ಬಗ್ಗೆ ಏನಿದೆ?'
    protected, mapping = _protect_spans(text)
    assert _restore_spans(protected, mapping) == text


def test_protect_spans_leaves_ordinary_words_and_short_numbers_alone():
    # Single digits and plain words are not identifiers — protecting them would only
    # fragment the sentence the model has to translate, for no benefit (see the
    # module comment's "Is that 10001 to 10002 another 10003?" counter-example).
    protected, mapping = _protect_spans('ಆ case ಗೆ related ಇನ್ನೊಂದು FIR ಇದ್ಯಾ? 5 ಜನ')
    assert mapping == {}
    assert protected == 'ಆ case ಗೆ related ಇನ್ನೊಂದು FIR ಇದ್ಯಾ? 5 ಜನ'


def test_resolve_plural_markers_picks_singular_or_plural_from_the_real_count():
    # Live defect: NLLB translated "case(s)" but copied the literal "(s)" through
    # untouched ("73 ಪ್ರಕರಣಗಳು(s)"). Resolving to real English before the model ever
    # sees it removes the ambiguity structurally instead of hoping NLLB drops it.
    assert _resolve_plural_markers('73 case(s) recorded') == '73 cases recorded'
    assert _resolve_plural_markers('1 case(s) recorded') == '1 case recorded'
    assert _resolve_plural_markers('0 case(s) recorded') == '0 cases recorded'
    assert _resolve_plural_markers("own account(s)") == 'own accounts'
    assert _resolve_plural_markers('12,345 record(s)') == '12,345 records'
    assert 'case(s)' not in _resolve_plural_markers('7 case(s) found, 1 case(s) open')


def test_translate_sends_the_backend_a_placeholder_not_the_raw_identifier(monkeypatch):
    """The identifier must never reach the backend at all — proving fidelity does not
    depend on the model choosing to preserve it, only on this wrapper never exposing
    it. A backend that "corrupts everything it can see" still can't corrupt what it's
    never shown; one that echoes its input back verbatim (a stand-in for how NLLB
    handles a short digit placeholder in practice — see the module comment) proves the
    round trip reconstructs the original text exactly."""
    import importlib
    translate_mod = importlib.import_module('data.nlp.translate')

    seen = {}

    class _RecordingEchoBackend:
        def translate(self, text, src_flores, tgt_flores):
            seen['text'] = text
            return text          # NLLB copies a short digit placeholder through as-is

    monkeypatch.setattr(translate_mod, '_load', lambda: _RecordingEchoBackend())
    # Deliberately no district name here — that half is covered separately below
    # (test_kannada_district_names_are_substituted_not_translated), since a
    # district match now restores to a DIFFERENT string (the English name), which
    # would make this test's "round trip is exact" assertion the wrong claim.
    query = 'ಆ ಬಗ್ಗೆ FIR 100222201202600022 ಏನಿದೆ'
    out = translate(query, 'kn', 'en')

    assert '100222201202600022' not in seen['text']   # never shown to the backend
    assert out == query                               # and the round trip is exact


def test_kannada_district_names_are_substituted_not_translated(monkeypatch):
    """The structural fix for the "ಮಂಡ್ಯ (Mandya) -> Mandi" mistranslation class
    (ENGINEERING_BRIEF.md §10): the district name must never reach the backend at
    all — a hostile backend that corrupts everything it sees still can't corrupt a
    span it's never shown, and the correct ENGLISH name comes back regardless."""
    import importlib
    translate_mod = importlib.import_module('data.nlp.translate')

    class _HostileBackend:
        def translate(self, text, src_flores, tgt_flores):
            return text.replace('ಮಂಡ್ಯ', 'garbled') if 'ಮಂಡ್ಯ' in text else text + ' [translated]'

    monkeypatch.setattr(translate_mod, '_load', lambda: _HostileBackend())
    out = translate('ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು ಪ್ರಕರಣಗಳಿವೆ?', 'kn', 'en')

    assert 'ಮಂಡ್ಯ' not in out and 'garbled' not in out
    assert 'Mandya' in out


def test_district_substitution_applies_in_both_translation_directions():
    """src='kn' protects a Kannada district spelling; src='en' protects the
    canonical English name (the reverse-direction fix, added this pass after being
    found live) — both districts protected, neither left to the model. A source
    that is neither (the default, 'en', used elsewhere for non-language text) with
    no known district present protects nothing, same as before this pass."""
    _, kn_mapping = _protect_spans('ಮಂಡ್ಯ ಜಿಲ್ಲೆ', src='kn')
    assert kn_mapping == {'90001': 'Mandya'}

    _, en_mapping = _protect_spans('Mandya district', src='en')
    assert en_mapping == {'90001': 'ಮಂಡ್ಯ'}

    protected, mapping = _protect_spans('no district named here', src='en')
    assert mapping == {}
    assert protected == 'no district named here'


def test_english_district_name_restores_the_canonical_kannada_spelling(monkeypatch):
    """The reverse-direction sibling of the kn->en district fix, found live testing
    this pass: a synthesized answer's "Mandya" translated en->kn came back as
    NLLB's own "ಮಂಡಯಾ" rather than the canonical "ಮಂಡ್ಯ". Same lookup-substitution
    technique, opposite direction -- the hostile backend proves the English name
    never reaches the model at all."""
    import importlib
    translate_mod = importlib.import_module('data.nlp.translate')

    class _HostileBackend:
        def translate(self, text, src_flores, tgt_flores):
            return text.replace('Mandya', 'garbled') if 'Mandya' in text else text

    monkeypatch.setattr(translate_mod, '_load', lambda: _HostileBackend())
    out = translate('73 cases in Mandya are recorded.', 'en', 'kn')

    assert 'Mandya' not in out and 'garbled' not in out
    assert 'ಮಂಡ್ಯ' in out


def test_district_and_identifier_protection_compose_without_collision():
    """Regression: identifier placeholders are themselves digit runs, and the
    identifier regex matches ANY 2+ digit run — protecting a district BEFORE
    identifiers let the identifier pass re-protect the district's own placeholder,
    which _restore_spans then failed to fully unwind (found by this test failing
    first, before the fix reordered the two passes)."""
    protected, mapping = _protect_spans(
        'ಮಂಡ್ಯದಲ್ಲಿ FIR 100222201202600022 ಬಗ್ಗೆ ಏನಿದೆ', src='kn')
    assert 'ಮಂಡ್ಯ' not in protected
    restored = _restore_spans(protected, mapping)
    assert restored == 'Mandyaದಲ್ಲಿ FIR 100222201202600022 ಬಗ್ಗೆ ಏನಿದೆ'
    assert '90001' not in restored and '90002' not in restored


def test_a_multi_citation_answer_is_translated_one_line_at_a_time(monkeypatch):
    """Found live: a real 6-citation Kannada answer degenerated into a citation's
    translation trailing off into "9004 ಮೇ, 9004 ಮೇ, ..." repeated a dozen times —
    the whole multi-line answer (header + one line per citation + footer) was sent
    to the backend as ONE translate_batch call, and the model's target-length
    budget (CTranslate2's own default is 256 tokens) ran out mid-answer, so the
    decoder had no natural stopping point and fell into repetition. A backend that
    counts how many separate calls it receives, and refuses to translate any input
    longer than one short line, proves the fix: real content survives only if the
    caller is genuinely sending it one line at a time."""
    import importlib
    translate_mod = importlib.import_module('data.nlp.translate')

    calls = []

    class _OneLineOnlyBackend:
        def translate(self, text, src_flores, tgt_flores):
            calls.append(text)
            # Any single line here is under 70 chars; the whole answer joined as
            # one blob (the bug) would be ~230 -- the gap is wide enough that this
            # only ever catches the failure mode under test.
            if len(text) > 100:
                raise AssertionError(f"backend received more than one line: {text!r}")
            return text + "_KN"

    monkeypatch.setattr(translate_mod, '_load', lambda: _OneLineOnlyBackend())

    answer = (
        "Based on 3 record(s) in the system:\n"
        "  [1] FIR one narrative line here.\n"
        "  [2] FIR two narrative line here.\n"
        "  [3] FIR three narrative line here.\n"
        "\n"
        "Every statement above is drawn directly from the cited records."
    )
    out = translate(answer, 'en', 'kn')

    # One backend call per non-blank line, never the whole answer in one call.
    assert len(calls) == 5
    # Blank line preserved untouched, not spent on a translate_batch call.
    assert out.split("\n")[4] == ""
    assert out.split("\n")[1].endswith("_KN")
