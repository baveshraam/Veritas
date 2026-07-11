"""Translation — self-hosted. FIR text never leaves the network.

Deliberately NOT routed to a cloud LLM: the architecture requires record content stay
inside the network, and Gemini is used only for reasoning/synthesis over evidence the
caller already holds, never as a translation service for record text.

## Which model, and why two

**IndicTrans2 (AI4Bharat) is the right model** for Indic translation — purpose-built,
state of the art on EN<->KN, and MIT-licensed, which is what a police deployment needs.
It is also a **gated** HuggingFace repo: the weights need a licence acceptance on the
model page before they can be pulled. That is a one-click human action, not something
the code can arrange for itself, so IndicTrans2 cannot be the thing Kannada depends on
being present today.

So the backend is chosen at load time:

  1. `VERITAS_INDICTRANS2_MODEL` -> IndicTrans2 (preferred; set this once the weights
     are provisioned — a local path, or the HF id after accepting the licence).
  2. `VERITAS_TRANSLATION_MODEL` -> any ungated seq2seq translation model, defaulting
     to NLLB-200 distilled 600M, which is open, self-hosted, and supports Kannada in
     both directions. This is what makes Kannada work out of the box.
  3. Neither loadable -> `TranslationUnavailable`, with the remedy. The Translation
     Agent then answers in English and SAYS so, rather than silently replying in the
     wrong language.

Licence note the deployment must not skip: NLLB-200 is **CC-BY-NC-4.0 (non-commercial)**.
That is correct for a datathon/research build and NOT for production use by KSP.
IndicTrans2 (MIT) is the production path — the other reason it stays the *preferred*
backend rather than being replaced by the fallback.
"""
import os
import re
from functools import lru_cache

# Kannada is U+0C80..U+0CFF. Script detection needs no model and cannot be wrong about
# which alphabet it is looking at, so it stays deterministic.
_KANNADA = re.compile(r"[ಀ-೿]")

# NLLB uses FLORES-200 codes; IndicTrans2 uses the same script-tagged convention.
_FLORES = {"en": "eng_Latn", "kn": "kan_Knda"}

DEFAULT_MODEL = "facebook/nllb-200-distilled-600M"


class TranslationUnavailable(RuntimeError):
    """No translation backend could be loaded on this host."""


def detect_language(text: str) -> str:
    """'kn' if the text contains Kannada script, else 'en'. Deterministic, no model."""
    return "kn" if _KANNADA.search(text or "") else "en"


def translate(text: str, src: str, tgt: str) -> str:
    if src == tgt or not text:
        return text
    if src not in _FLORES or tgt not in _FLORES:
        raise TranslationUnavailable(f"unsupported language pair {src}->{tgt}")

    tok, model, torch = _load()
    tok.src_lang = _FLORES[src]
    batch = tok(text, return_tensors="pt", truncation=True, max_length=512)
    bos = tok.convert_tokens_to_ids(_FLORES[tgt])
    with torch.no_grad():
        out = model.generate(**batch, forced_bos_token_id=bos,
                             max_length=512, num_beams=4)
    return tok.batch_decode(out, skip_special_tokens=True)[0].strip()


@lru_cache(maxsize=1)
def _load():
    """Load once, cache for the process. ~2.4GB resident for NLLB-600M on CPU."""
    name = os.getenv("VERITAS_INDICTRANS2_MODEL") or os.getenv(
        "VERITAS_TRANSLATION_MODEL", DEFAULT_MODEL)
    try:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    except ImportError as e:
        raise TranslationUnavailable(
            f"torch/transformers are not installed, so no self-hosted translation "
            f"backend can run ({e}). Record text is never sent to a cloud translator, "
            f"so there is no fallback here.") from e

    try:
        tok = AutoTokenizer.from_pretrained(name, trust_remote_code=True)
        model = AutoModelForSeq2SeqLM.from_pretrained(name, trust_remote_code=True)
    except Exception as e:
        raise TranslationUnavailable(
            f"could not load translation model {name!r}: {type(e).__name__}. "
            f"IndicTrans2 is a gated HuggingFace repo — accept its licence, then set "
            f"VERITAS_INDICTRANS2_MODEL. Otherwise set VERITAS_TRANSLATION_MODEL to an "
            f"ungated model (default: {DEFAULT_MODEL}).") from e

    model.eval()
    return tok, model, torch
