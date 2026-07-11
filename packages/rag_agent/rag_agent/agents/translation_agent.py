"""Translation Agent — self-hosted (IndicTrans2 preferred, NLLB-200 ungated fallback).

FIR text never goes to a cloud model. So if no translation backend is provisioned we
answer in English and SAY so, rather than silently replying in the wrong language or
shipping record text off-network to translate it.

Both directions matter, and for different reasons:
  - inbound  (kn->en): everything downstream — intent keywords, IPC/plate regexes, the
    district and name gazetteers — is English/Latin-script. An untranslated Kannada
    query matches none of it and retrieves nothing at all.
  - outbound (en->kn): the officer asked in Kannada and must be answered in Kannada.
"""
from data.nlp import TranslationUnavailable, translate
from data.nlp.translate import detect_language as _detect


def detect_language(text: str) -> str:
    """'kn' or 'en', by script. Deterministic — no model, no guess."""
    return _detect(text)


def to_english(text: str) -> tuple[str, str | None]:
    """Kannada query -> English. Returns (text, note); text is unchanged on failure."""
    if not text or _detect(text) == "en":
        return text, None
    try:
        return translate(text, "kn", "en"), None
    except TranslationUnavailable as e:
        return text, (f"Kannada query could not be translated ({e}); "
                      f"answering from the original text.")


def to_language(text: str, target: str) -> tuple[str, str | None]:
    """Answer -> the officer's language. `note` is set when translation could not run."""
    if target == "en" or not text:
        return text, None
    try:
        return translate(text, "en", target), None
    except TranslationUnavailable as e:
        return text, (f"[Answer shown in English — Kannada output needs a translation "
                      f"model: {e}]")
