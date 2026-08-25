"""Veritas RBAC rules — the single, versioned definition every enforcement point imports."""
from .rules import (
    ROLE_RANK,
    can_view_fir,
    MASKED_NAME,
    mask_person_fields,
    mask_person_name,
    max_traversal_depth,
)

__all__ = ["ROLE_RANK", "MASKED_NAME", "can_view_fir", "mask_person_fields",
           "mask_person_name", "max_traversal_depth"]
