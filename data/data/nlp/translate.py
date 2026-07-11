"""Translation — AI4Bharat IndicTrans2, self-hosted (FIR data never leaves the network).

Deliberately NOT routed to a cloud LLM: the architecture requires FIR content stay
inside the network, and Gemini is used only for reasoning/synthesis over evidence
the caller already holds, never as a translation service for record text.

MISSING EXTERNAL MODEL: IndicTrans2 weights (~4GB). Set VERITAS_INDICTRANS2_MODEL
to enable. Until then `translate` is a no-op for same-language pairs and raises a
clear TranslationUnavailable for cross-language ones, so the Translation Agent can
report "Kannada output needs the IndicTrans2 model" instead of silently answering
in the wrong language.
"""
import os
from functools import lru_cache


class TranslationUnavailable(RuntimeError):
    """Raised when IndicTrans2 weights aren't provisioned on this host."""


def translate(text: str, src: str, tgt: str) -> str:
    if src == tgt or not text:
        return text
    path = os.getenv("VERITAS_INDICTRANS2_MODEL")
    if not path:
        raise TranslationUnavailable(
            f"{src}->{tgt} needs IndicTrans2 weights; set VERITAS_INDICTRANS2_MODEL")
    return _load(path).translate(text, src_lang=src, tgt_lang=tgt)


@lru_cache(maxsize=1)
def _load(path: str):
    from IndicTransToolkit import IndicTranslator   # provisioned separately
    return IndicTranslator(path)
