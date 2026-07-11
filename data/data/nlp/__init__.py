"""Kannada/English NLP wrappers (Layer 6). All self-hosted — record text never
leaves the network. See data/README.md for the contract.

No external weights needed: `ner_extract`, `transliterate`, `detect_language`.

`translate` works out of the box on an ungated self-hosted model (NLLB-200), and
prefers IndicTrans2 when its gated weights are provisioned — see translate.py.

Still gated on out-of-band model provisioning: `speech_to_text`, `text_to_speech`.
Each raises a clear *Unavailable error rather than degrading silently.
"""
from .entities import Entity, ner_extract
from .speech import VoiceUnavailable, speech_to_text, text_to_speech
from .translate import TranslationUnavailable, detect_language, translate
from .translit import transliterate

__all__ = [
    "Entity", "ner_extract", "transliterate",
    "translate", "detect_language", "TranslationUnavailable",
    "speech_to_text", "text_to_speech", "VoiceUnavailable",
]
