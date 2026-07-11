"""Fellegi-Sunter probabilistic record linkage — batch entity resolution."""
from .fellegi_sunter import LINK_THRESHOLD, POSSIBLE_THRESHOLD, resolve_entities

__all__ = ["resolve_entities", "LINK_THRESHOLD", "POSSIBLE_THRESHOLD"]
