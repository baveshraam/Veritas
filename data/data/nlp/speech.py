"""ASR/TTS wrappers — self-hosted, so FIR audio never leaves the network.

Both are lazy: the model loads on first call and is cached. The backends are real
(faster-whisper for English ASR, and the AI4Bharat/Vakyansh stacks for Kannada),
but their weights are multi-GB and are provisioned out-of-band, not vendored.

MISSING EXTERNAL MODELS (voice is an enhancement path; text chat is unaffected):
  - Kannada ASR : Vakyansh          -> VERITAS_VAKYANSH_MODEL
  - English ASR : faster-whisper    -> VERITAS_WHISPER_MODEL (default "base.en",
                  auto-downloaded by faster-whisper if the package is installed)
  - Kannada TTS : AI4Bharat IndicTTS-> VERITAS_INDICTTS_MODEL
  - English TTS : Kokoro-TTS        -> VERITAS_KOKORO_MODEL

Callers get a clear VoiceUnavailable rather than a silent empty result, so the API
can degrade to text instead of pretending it transcribed something.
"""
import io
import os
from functools import lru_cache
from typing import Literal


class VoiceUnavailable(RuntimeError):
    """Raised when the requested speech model isn't provisioned on this host."""


def speech_to_text(audio: bytes, lang: Literal["en", "kn"]) -> str:
    if lang == "kn":
        return _vakyansh_transcribe(audio)
    return _whisper_transcribe(audio)


def text_to_speech(text: str, lang: Literal["en", "kn"]) -> bytes:
    if lang == "kn":
        return _indictts(text)
    return _kokoro(text)


# --- English ASR: faster-whisper (CTranslate2, CPU-viable) -------------------

def _whisper_transcribe(audio: bytes) -> str:
    model = _load_whisper()
    segments, _ = model.transcribe(io.BytesIO(audio), language="en")
    return " ".join(s.text.strip() for s in segments).strip()


@lru_cache(maxsize=1)
def _load_whisper():
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise VoiceUnavailable(
            "English ASR needs faster-whisper: pip install 'veritas-data[voice]'"
        ) from e
    return WhisperModel(os.getenv("VERITAS_WHISPER_MODEL", "base.en"),
                        device="cpu", compute_type="int8")


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
