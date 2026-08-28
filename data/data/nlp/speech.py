"""ASR/TTS wrappers — self-hosted, so FIR audio never leaves the network.

Lazy: the model loads on first call and is cached.

**ASR works today, in both languages.** faster-whisper is pip-installable and pulls its
own weights, and Whisper's multilingual checkpoints cover Kannada — so voice input needs
no out-of-band provisioning at all:

  - English ASR : faster-whisper `base.en`  -> VERITAS_WHISPER_MODEL
  - Kannada ASR : Vakyansh IF provisioned (VERITAS_VAKYANSH_MODEL — it is the better
                  Kannada model), otherwise faster-whisper multilingual `small` with
                  language="kn" -> VERITAS_WHISPER_KN_MODEL.

The same principle as translation: use the specialist when it is present, but never let
the feature *depend* on weights we cannot pull ourselves.

STILL GATED — TTS only (voice OUTPUT; input and text chat are unaffected):
  - Kannada TTS : AI4Bharat IndicTTS -> VERITAS_INDICTTS_MODEL
  - English TTS : Kokoro-TTS         -> VERITAS_KOKORO_MODEL

Callers get a clear VoiceUnavailable rather than a silent empty result, so the API can
degrade to text instead of pretending it spoke.
"""
import io
import os
import threading
from functools import lru_cache
from typing import Literal


class VoiceUnavailable(RuntimeError):
    """Raised when the requested speech model isn't provisioned on this host."""


def speech_to_text(audio: bytes, lang: Literal["en", "kn"]) -> str:
    if lang == "kn":
        # Vakyansh is the better Kannada ASR, but its weights are provisioned
        # out-of-band. Whisper multilingual covers Kannada and installs itself, so
        # Kannada voice input works either way rather than being dark by default.
        if os.getenv("VERITAS_VAKYANSH_MODEL"):
            return _vakyansh_transcribe(audio)
        return _whisper_transcribe(audio, lang="kn")
    return _whisper_transcribe(audio)


def text_to_speech(text: str, lang: Literal["en", "kn"]) -> bytes:
    if lang == "kn":
        return _indictts(text)
    return _kokoro(text)


# --- English ASR: faster-whisper (CTranslate2, CPU-viable) -------------------

def _whisper_transcribe(audio: bytes, lang: str = "en") -> str:
    # English uses the English-only checkpoint (faster, more accurate on English);
    # Kannada needs a multilingual one, so they are separate models.
    name = (os.getenv("VERITAS_WHISPER_KN_MODEL", "small") if lang == "kn"
            else os.getenv("VERITAS_WHISPER_MODEL", "base.en"))
    model = _load_whisper(name)
    segments, _ = model.transcribe(io.BytesIO(audio), language=lang)
    return " ".join(s.text.strip() for s in segments).strip()


# Same reason as translate.py's `_LOAD_LOCK`: `lru_cache` memoises a result, it does
# not make the miss atomic, so `warm()` on the startup thread and the first voice
# request on a worker both load the checkpoint. Serialising makes the request WAIT for
# the warm-up rather than start a second concurrent load of the same weights.
_LOAD_LOCK = threading.Lock()


def _load_whisper(name: str):
    with _LOAD_LOCK:
        return _load_whisper_cached(name)


@lru_cache(maxsize=2)          # one English checkpoint, one multilingual
def _load_whisper_cached(name: str):
    from data.nlp.model_fetch import ensure_models
    ensure_models()                    # no-op locally; File Store fetch on AppSail
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise VoiceUnavailable(
            "ASR needs faster-whisper: pip install 'veritas-data[voice]'"
        ) from e
    return WhisperModel(name, device="cpu", compute_type="int8")


# `cache_clear` and `cache_info` are part of this function's public contract —
# tests reset the cached backend through the first, and `backend_status()` asks the
# second whether a load has happened WITHOUT triggering one. The locking wrapper
# would otherwise hide both, so they are re-exported from the memoised inner
# function they actually belong to.
_load_whisper.cache_clear = _load_whisper_cached.cache_clear
_load_whisper.cache_info = _load_whisper_cached.cache_info

def warm() -> None:
    """BUG-016. Same reasoning as translate.warm(): pay the one-time model-load cost
    during container warm-up, not on an officer's first voice query. Only the two
    whisper checkpoints this deployment actually depends on (Vakyansh/IndicTTS/Kokoro
    are out-of-band-provisioned and not assumed present)."""
    try:
        _load_whisper(os.getenv("VERITAS_WHISPER_MODEL", "base.en"))
        _load_whisper(os.getenv("VERITAS_WHISPER_KN_MODEL", "small"))
    except VoiceUnavailable:
        pass    # faster-whisper not installed in this environment — nothing to warm


# --- Kannada ASR / TTS, English TTS: weights provisioned out-of-band ---------

def _vakyansh_transcribe(audio: bytes) -> str:
    path = os.getenv("VERITAS_VAKYANSH_MODEL")
    if not path:
        raise VoiceUnavailable(
            "Kannada ASR needs Vakyansh weights; set VERITAS_VAKYANSH_MODEL")
    return _load_vakyansh(path).transcribe(audio)


@lru_cache(maxsize=1)
def _load_vakyansh(path: str):
    from vakyansh import Wav2VecInference          # provisioned separately
    return Wav2VecInference(path)


def _indictts(text: str) -> bytes:
    path = os.getenv("VERITAS_INDICTTS_MODEL")
    if not path:
        raise VoiceUnavailable(
            "Kannada TTS needs IndicTTS weights; set VERITAS_INDICTTS_MODEL")
    return _load_indictts(path).synthesize(text, lang="kn")


@lru_cache(maxsize=1)
def _load_indictts(path: str):
    from ai4bharat.tts import IndicTTS             # provisioned separately
    return IndicTTS(path)


def _kokoro(text: str) -> bytes:
    path = os.getenv("VERITAS_KOKORO_MODEL")
    if not path:
        raise VoiceUnavailable(
            "English TTS needs Kokoro weights; set VERITAS_KOKORO_MODEL")
    return _load_kokoro(path).synthesize(text)


@lru_cache(maxsize=1)
def _load_kokoro(path: str):
    from kokoro import KPipeline                   # provisioned separately
    return KPipeline(path)
