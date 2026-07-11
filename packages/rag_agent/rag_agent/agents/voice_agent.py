"""Voice Agent — ASR in, TTS out. Wraps data's self-hosted speech models.

Runs before the Orchestrator (transcription) and after Synthesis (speech). Appears
in the trace as its own step so "audio in -> text out" is visible, not implied.
If the speech weights aren't provisioned, the turn continues as text rather than
failing — voice is an enhancement, not a precondition for answering.
"""
from data.nlp import VoiceUnavailable, speech_to_text, text_to_speech


def transcribe(audio: bytes, language: str) -> tuple[str | None, str]:
    """Returns (text, trace detail)."""
    try:
        text = speech_to_text(audio, language)   # type: ignore[arg-type]
        return text, f"Transcribed {len(audio)} bytes of {language} audio"
    except VoiceUnavailable as e:
        return None, f"Speech model unavailable ({e}); expecting text input"


def synthesize(text: str, language: str) -> tuple[bytes | None, str]:
    try:
        audio = text_to_speech(text, language)   # type: ignore[arg-type]
        return audio, f"Synthesised {len(audio)} bytes of {language} speech"
    except VoiceUnavailable as e:
        return None, f"TTS model unavailable ({e}); returning text only"
