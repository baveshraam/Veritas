"""Kannada/English NLP wrappers (Layer 6). All self-hosted — record text never
leaves the network. See data/README.md for the contract.

Available today with no external weights: `ner_extract`, `transliterate` (the two
the entity-resolution and orchestration paths actually depend on).
Gated on out-of-band model provisioning: `translate`, `speech_to_text`,
`text_to_speech` — each raises a clear *Unavailable error rather than degrading
silently.
"""
from .entities import Entity, ner_extract
from .speech import VoiceUnavailable, speech_to_text, text_to_speech
from .translate import TranslationUnavailable, translate
from .translit import transliterate

__all__ = [
    "Entity", "ner_extract", "transliterate",
    "translate", "TranslationUnavailable",
    "speech_to_text", "text_to_speech", "VoiceUnavailable",
]
