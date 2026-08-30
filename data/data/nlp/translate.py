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
import threading
from functools import lru_cache

# Kannada is U+0C80..U+0CFF. Script detection needs no model and cannot be wrong about
# which alphabet it is looking at, so it stays deterministic.
_KANNADA = re.compile(r"[ಀ-೿]")

# A KSP officer's Kannada is routinely code-switched with English: FIR numbers, IPC
# codes and vehicle plates are typed in Latin script inside an otherwise-Kannada
# sentence, exactly as spoken. NLLB translates the *whole string* it is given, with no
# concept that a digit run is a record identifier rather than a quantity to render
# idiomatically — so a record identifier's fidelity was, before this, left entirely to
# a generative model's discretion. This makes that fidelity structural instead:
# protected spans are removed before translation and spliced back verbatim after, so
# they cannot be altered by the model no matter what it does with the rest of the
# sentence.
#
# A second, separate class this fixes (compositional semantic layer pass):
# NLLB-200-distilled-600M mistranslated the district name "ಮಂಡ್ಯ" (Mandya) to
# "Mandi" — a real but wrong, more common Indian place name — specifically when
# "FIR" and a number sat in the same sentence; "ಬೆಂಗಳೂರು" (Bengaluru) in the
# identical construction translated correctly. Earlier investigation (see
# ENGINEERING_BRIEF.md §10) ruled out protecting the NUMBER sitting beside the
# district name — a placeholder swap there made no difference, because the root
# cause was never the digits, it was the model guessing wrong on the Kannada WORD
# itself. That is a different span than what _PROTECT below covers, so it needed
# its own fix: a closed, 31-entry Kannada-district gazetteer
# (data.districts.kannada_name_map) that removes the district name from the
# model's job entirely — looked up and substituted with the correct English name
# directly, never translated at all. This closes the whole class (any of the 31
# districts, not just the one reported instance), structurally rather than by
# hoping the model gets a specific name right.
#
# Blanket-protecting every Latin-script word (not just identifiers) was tried and
# rejected: it swallows the English loanwords ("FIR", "case") that anchor the
# model's translation of the surrounding Kannada grammar, and produced visibly
# worse output ("Is that 10001 to 10002 another 10003?"). So only
# numeric/identifier-shaped spans and the closed district gazetteer are
# protected — never ordinary words.
_PROTECT = re.compile(
    r"\bKA[\s-]?\d{2}[\s-]?[A-Z]{1,2}[\s-]?\d{3,4}\b"     # vehicle plate, e.g. KA 05 MJ 1234
    r"|\d{2,}",                                             # FIR numbers, IPC codes
    re.I,
)


def _protect_spans(text: str, src: str = "en") -> tuple[str, dict[str, str]]:
    """Replace protected spans with digit-shaped placeholders NLLB reliably copies
    through untouched, and return the mapping needed to restore them.

    For FIR numbers/IPC codes/plates the restore value is the ORIGINAL text —
    verbatim fidelity is the whole point. For a district name it is instead a
    lookup substitution, not a translation, in whichever direction is being
    translated: src=="kn" restores the CORRECT ENGLISH NAME
    (data.districts.kannada_name_map, closing "ಮಂಡ್ಯ (Mandya) -> Mandi" — see
    ENGINEERING_BRIEF.md §10); src=="en" restores the CANONICAL KANNADA SPELLING
    (data.districts.english_to_kannada_district, closing the reverse-direction
    sibling found live this pass: a synthesized answer's "Mandya" translating to
    NLLB's own "ಮಂಡಯಾ" instead of the canonical "ಮಂಡ್ಯ" an officer's own query
    would use). Either way the model is never asked to translate the district name
    at all.
    """
    mapping: dict[str, str] = {}

    def _placeholder(restore_value: str) -> str:
        placeholder = str(90001 + len(mapping))
        mapping[placeholder] = restore_value
        return placeholder

    # Identifiers FIRST: the placeholder scheme is itself a digit run, and
    # _PROTECT's own pattern matches any 2+ digit run — so protecting a district
    # BEFORE this would make this pass re-protect the district's own placeholder
    # a second time (found by this pass's own round-trip test failing on exactly
    # that collision). Running identifiers first means their placeholders are the
    # ONLY digit runs left by the time the district pass (which searches for
    # Kannada script, never digits) runs, so nothing downstream re-matches them.
    text = _PROTECT.sub(lambda m: _placeholder(m.group(0)), text)

    if src == "kn":
        from data.districts import kannada_name_map
        kn_map = kannada_name_map()
        if kn_map:
            # Longest spelling first, so a name that happens to be a substring of
            # another (none today, but stays correct if one is ever added) is
            # never clipped mid-match — the same discipline entities.py's own
            # LOCATION gazetteer match already follows.
            pattern = "|".join(re.escape(k) for k in sorted(kn_map, key=len, reverse=True))
            text = re.sub(pattern, lambda m: _placeholder(kn_map[m.group(0)]), text)
    elif src == "en":
        # The reverse-direction sibling, found live this pass: a SYNTHESIZED
        # ANSWER (always in canonical English district names, e.g. "Mandya") gets
        # translated en->kn for the reply, and NLLB renders its own transliteration
        # ("ಮಂಡಯಾ") rather than the canonical spelling ("ಮಂಡ್ಯ") the officer's own
        # query would use — correct facts, non-canonical spelling. Same lookup-
        # substitution technique, opposite direction.
        from data.districts import english_to_kannada_district
        en_map = english_to_kannada_district()
        if en_map:
            # No case-insensitive matching: synthesis always inserts the canonical,
            # exact-case district name verbatim (it comes straight from the seed
            # data's own column), so exact-case matching is both sufficient and
            # avoids a case-folded match no longer being a valid dict key.
            pattern = "|".join(rf"\b{re.escape(k)}\b"
                               for k in sorted(en_map, key=len, reverse=True))
            text = re.sub(pattern, lambda m: _placeholder(en_map[m.group(0)]), text)

    return text, mapping


def _restore_spans(text: str, mapping: dict[str, str]) -> str:
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text


# Synthesis writes count-agnostic "case(s)"/"record(s)" markers throughout
# orchestrator.py rather than branching every f-string on singular/plural. English
# readers parse that convention fine; NLLB does not — it translates the noun and
# copies the literal "(s)" through untouched (observed live: "73 ಪ್ರಕರಣಗಳು(s)"). Since
# the actual count is already known wherever the marker was written, resolving it to
# real English singular/plural BEFORE translation removes the ambiguity structurally,
# the same way _protect_spans removes identifiers and district names from the model's
# job rather than hoping it renders them right.
_PLURAL_MARKER = re.compile(r"(?:(\d[\d,]*)\s+)?\b(\w+)\(s\)")


def resolve_plural_markers(text: str) -> str:
    """Turn the codebase's count-agnostic "case(s)" markers into real English.

    Synthesis writes them because it does not always know the count at the point
    the sentence is assembled. They were only ever resolved on the way into the
    translation model (NLLB copies the literal "(s)" through untouched, which is
    how "73 ಪ್ರಕರಣಗಳು(s)" reached a live answer). English readers were left with
    the marker itself — a form field in the middle of a finding — so the same
    resolution now runs on the English answer as well.""" 
    def repl(m: re.Match) -> str:
        num, word = m.group(1), m.group(2)
        if num is not None and int(num.replace(",", "")) == 1:
            return f"{num} {word}"
        plural = word if word.endswith("s") else word + "s"
        return f"{num} {plural}" if num is not None else plural

    return _PLURAL_MARKER.sub(repl, text)


# The pre-existing private name, kept so nothing that imported it has to change.
_resolve_plural_markers = resolve_plural_markers

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

    protected, mapping = _protect_spans(resolve_plural_markers(text), src)
    backend = _load()
    result = backend.translate(protected, _FLORES[src], _FLORES[tgt])
    return _restore_spans(result, mapping) if mapping else result


# Serialises backend construction. `lru_cache` memoises a RESULT; it does not make the
# miss atomic, so two threads that miss together both run the wrapped function. Here
# that means two concurrent full NLLB loads — which is not hypothetical, it is the
# normal case: `warm()` runs on the startup background thread while the first Kannada
# request comes in on a worker, so a cold container loads the model twice, on a box
# with 2048MB. Measured symptom: the FIRST Kannada query after a start returned an
# UNKNOWN-intent refusal (the backend raised, `to_english` degraded to the untranslated
# text, and Kannada script matches no keyword, gazetteer or regex downstream), while
# every later one answered correctly.
#
# With the lock the request path WAITS on the warm-up's load instead of starting a
# second one — the officer pays latency, which is honest, rather than getting a wrong
# refusal, which is not. Uncontended acquisition is ~100ns against a load measured at
# ~20s, so this costs nothing on the warm path.
_LOAD_LOCK = threading.Lock()


def _load():
    """Pick a backend once, cache it for the process. See `_LOAD_LOCK`."""
    with _LOAD_LOCK:
        return _load_backend()


@lru_cache(maxsize=1)
def _load_backend():
    """Pick a backend once, cache it for the process.

    IndicTrans2, or any model an officer points `VERITAS_TRANSLATION_MODEL` at, loads
    through raw `transformers` — it is not baked into CTranslate2 form. The baked-in
    NLLB default loads through CTranslate2 if the converted directory is present (the
    deployed image), and falls back to a raw `transformers` load of the same model
    otherwise (local dev without the Docker build step).
    """
    from data.nlp.model_fetch import ensure_models
    ensure_models()                    # no-op locally; File Store fetch on AppSail

    indictrans = os.getenv("VERITAS_INDICTRANS2_MODEL")
    custom = os.getenv("VERITAS_TRANSLATION_MODEL")
    if indictrans or custom:
        return _TransformersBackend(indictrans or custom)
    if os.path.isdir(_CT2_DIR):
        return _CTranslate2Backend(_CT2_DIR, DEFAULT_MODEL)
    return _TransformersBackend(DEFAULT_MODEL)


# `cache_clear` and `cache_info` are part of this function's public contract —
# tests reset the cached backend through the first, and `backend_status()` asks the
# second whether a load has happened WITHOUT triggering one. The locking wrapper
# would otherwise hide both, so they are re-exported from the memoised inner
# function they actually belong to.
_load.cache_clear = _load_backend.cache_clear
_load.cache_info = _load_backend.cache_info

def warm() -> None:
    """BUG-016: profiled live, the ~2s Kannada round-trip already reported was a warm
    container. A cold model load measured 22s locally (weight load, not inference —
    the very next call on the same process was 0.8-1.4s); nothing had paid that cost
    proactively, so it landed on whichever officer's query happened to be first after
    a container start/restart. Loading eagerly during the same background warm-up that
    already fetches the Data Store mirror and File Store weights moves the cost off
    the request path entirely."""
    _load()


def backend_status() -> str:
    """Which backend is active, without forcing a load — BUG-017's fix. The changelog
    claimed weights left the image for Catalyst File Store; the live evidence for that
    had been inferred from Kannada response latency, which cannot actually distinguish
    a File-Store-backed transformers load from a still-baked-in one. This reports the
    real, observable fact instead."""
    if _load.cache_info().currsize == 0:
        return "not yet loaded"
    return ("ctranslate2 (VERITAS_NLLB_CT2_DIR present — local/baked directory)"
            if isinstance(_load(), _CTranslate2Backend)
            else "transformers (HF cache — File Store or baked, see model_weights)")


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
