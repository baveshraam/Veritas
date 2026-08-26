"""A translation-backend failure must degrade the answer, never crash the turn.

Found live 2026-08-26: a Kannada query mid-session raised a raw TypeError from inside
the CTranslate2 tokenizer, which `to_english`'s original except-clause (scoped only to
this module's own `TranslationUnavailable`) let propagate — the whole investigation
turn died with "the investigation engine failed on this query" instead of the honest
English-language degrade every other translation failure already produces.
"""
from rag_agent.agents import translation_agent


def test_to_english_degrades_on_any_backend_exception(monkeypatch):
    def _boom(*a, **k):
        raise TypeError("TextEncodeInput must be Union[TextInputSequence, ...]")

    monkeypatch.setattr(translation_agent, "translate", _boom)
    text, note = translation_agent.to_english("ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು ಪ್ರಕರಣಗಳಿವೆ?")

    assert text == "ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು ಪ್ರಕರಣಗಳಿವೆ?"   # unchanged, not lost
    assert note and "TypeError" in note


def test_to_language_degrades_on_any_backend_exception(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(translation_agent, "translate", _boom)
    text, note = translation_agent.to_language("The case is under investigation.", "kn")

    assert text == "The case is under investigation."
    assert note and "RuntimeError" in note


def test_to_english_still_reports_translation_unavailable_distinctly(monkeypatch):
    from data.nlp import TranslationUnavailable

    def _unavailable(*a, **k):
        raise TranslationUnavailable("no backend could be loaded")

    monkeypatch.setattr(translation_agent, "translate", _unavailable)
    text, note = translation_agent.to_english("ಏನಾಯಿತು?")

    assert text == "ಏನಾಯಿತು?"
    assert note and "no backend could be loaded" in note
