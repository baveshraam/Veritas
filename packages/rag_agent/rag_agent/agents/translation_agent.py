"""Translation Agent — IndicTrans2, self-hosted.

FIR text never goes to a cloud model, so if the IndicTrans2 weights aren't
provisioned we answer in English and say so, rather than silently replying in the
wrong language or shipping record text off-network to translate it.
"""
from data.nlp import TranslationUnavailable, translate


def to_language(text: str, target: str) -> tuple[str, str | None]:
    """Returns (text, note). `note` is set when translation could not be performed."""
    if target == "en" or not text:
        return text, None
    try:
        return translate(text, "en", target), None
    except TranslationUnavailable as e:
        return text, (f"[Answer shown in English — Kannada output needs the "
                      f"IndicTrans2 model: {e}]")
