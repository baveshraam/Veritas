"""Translation — self-hosted. FIR text never leaves the network.

Deliberately NOT routed to a cloud LLM: the architecture requires record content stay
inside the network, and QuickML is used only for reasoning/synthesis over evidence the
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
     are provisioned — a local path, or the HF id after accepting the licence). Loaded
     through raw `transformers`, since it ships only as a HF checkpoint.
  2. Otherwise -> NLLB-200 distilled 600M, which is open, self-hosted, and supports
     Kannada in both directions. This is what makes Kannada work out of the box.
  3. Neither loadable -> `TranslationUnavailable`, with the remedy. The Translation
     Agent then answers in English and SAYS so, rather than silently replying in the
     wrong language.

## Why NLLB is baked in as CTranslate2, not raw `transformers`

The raw fp32 checkpoint is ~2.4GB — the same reason faster-whisper is used for ASR
instead of raw Whisper. CTranslate2 (already a dependency, via faster-whisper) converts
NLLB to an int8-quantized format once at build time: ~650MB, and faster on CPU. The
image is deployed through a platform with a real disk quota on the pull/unpack step, so
this is not a micro-optimization — a fp32 NLLB checkpoint is the single largest thing
in the image, by itself larger than every other model combined.

The tokenizer is still loaded through `transformers` (a few MB — vocabulary and merge
rules, not weights), because CTranslate2 translates token IDs, not raw text.

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
_CT2_DIR = os.getenv("VERITAS_NLLB_CT2_DIR", "/opt/models/nllb-ct2")


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

    backend = _load()
    return backend.translate(text, _FLORES[src], _FLORES[tgt])


@lru_cache(maxsize=1)
def _load():
    """Pick a backend once, cache it for the process.

    IndicTrans2, or any model an officer points `VERITAS_TRANSLATION_MODEL` at, loads
    through raw `transformers` — it is not baked into CTranslate2 form. The baked-in
    NLLB default loads through CTranslate2 if the converted directory is present (the
    deployed image), and falls back to a raw `transformers` load of the same model
    otherwise (local dev without the Docker build step).
    """
    indictrans = os.getenv("VERITAS_INDICTRANS2_MODEL")
    custom = os.getenv("VERITAS_TRANSLATION_MODEL")
    if indictrans or custom:
        return _TransformersBackend(indictrans or custom)
    if os.path.isdir(_CT2_DIR):
        return _CTranslate2Backend(_CT2_DIR, DEFAULT_MODEL)
    return _TransformersBackend(DEFAULT_MODEL)


class _CTranslate2Backend:
    """NLLB via CTranslate2 int8 — see module docstring for why.

    Tokenization prefers a `tokenizer.json` sitting next to the converted model,
    loaded through the `tokenizers` runtime directly (~10MB). The deployed image
    ships without the full `transformers` package (~110MB of model code serving
    nothing once translation runs on CTranslate2); `transformers.AutoTokenizer`
    is the fallback for local dev, where the HF cache exists but no tokenizer.json
    was copied beside the model.
    """

    def __init__(self, ct2_dir: str, tokenizer_name: str):
        try:
            import ctranslate2
        except ImportError as e:
            raise TranslationUnavailable(
                f"ctranslate2 is not installed, so no self-hosted translation "
                f"backend can run ({e}).") from e
        try:
            self._translator = ctranslate2.Translator(ct2_dir, device="cpu")
            tok_json = os.path.join(ct2_dir, "tokenizer.json")
            if os.path.isfile(tok_json):
                from tokenizers import Tokenizer
                self._tok = Tokenizer.from_file(tok_json)
                self._hf = None
            else:
                from transformers import AutoTokenizer
                self._hf = AutoTokenizer.from_pretrained(tokenizer_name)
                self._tok = None
        except Exception as e:
            raise TranslationUnavailable(
                f"could not load the baked NLLB CTranslate2 model at {ct2_dir!r}: "
                f"{type(e).__name__}.") from e

    def translate(self, text: str, src_flores: str, tgt_flores: str) -> str:
        if self._hf is not None:
            self._hf.src_lang = src_flores
            source = self._hf.convert_ids_to_tokens(self._hf.encode(text))
            result = self._translator.translate_batch(
                [source], target_prefix=[[tgt_flores]], beam_size=4)
            output_tokens = result[0].hypotheses[0][1:]    # drop the target-prefix token
            output_ids = self._hf.convert_tokens_to_ids(output_tokens)
            return self._hf.decode(output_ids, skip_special_tokens=True).strip()

        # NLLB's convention, applied by hand: [src_lang] ... </s> on the source side,
        # exactly what transformers' fast tokenizer emits for encode(text).
        enc = self._tok.encode(text, add_special_tokens=False)
        source = [src_flores] + enc.tokens + ["</s>"]
        result = self._translator.translate_batch(
            [source], target_prefix=[[tgt_flores]], beam_size=4)
        hyp = result[0].hypotheses[0][1:]                  # drop the target-prefix token
        ids = [i for i in (self._tok.token_to_id(t) for t in hyp) if i is not None]
        return self._tok.decode(ids, skip_special_tokens=True).strip()


class _TransformersBackend:
    """Raw `transformers` AutoModelForSeq2SeqLM — IndicTrans2, or any custom model an
    officer points at. Not baked into CTranslate2 form, so this pays the full weight."""

    def __init__(self, name: str):
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as e:
            raise TranslationUnavailable(
                f"torch/transformers are not installed, so no self-hosted translation "
                f"backend can run ({e}). Record text is never sent to a cloud translator, "
                f"so there is no fallback here.") from e
        try:
            self._tok = AutoTokenizer.from_pretrained(name, trust_remote_code=True)
            self._model = AutoModelForSeq2SeqLM.from_pretrained(name, trust_remote_code=True)
        except Exception as e:
            raise TranslationUnavailable(
                f"could not load translation model {name!r}: {type(e).__name__}. "
                f"IndicTrans2 is a gated HuggingFace repo — accept its licence, then set "
                f"VERITAS_INDICTRANS2_MODEL. Otherwise set VERITAS_TRANSLATION_MODEL to an "
                f"ungated model (default: {DEFAULT_MODEL}).") from e
        self._model.eval()
        self._torch = torch

    def translate(self, text: str, src_flores: str, tgt_flores: str) -> str:
        self._tok.src_lang = src_flores
        batch = self._tok(text, return_tensors="pt", truncation=True, max_length=512)
        bos = self._tok.convert_tokens_to_ids(tgt_flores)
        with self._torch.no_grad():
            out = self._model.generate(**batch, forced_bos_token_id=bos,
                                        max_length=512, num_beams=4)
        return self._tok.batch_decode(out, skip_special_tokens=True)[0].strip()
