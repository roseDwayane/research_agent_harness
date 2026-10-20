"""IdeaBench-style target-paper subset builder (Insight Score data, not Step 0–8)."""

from .build import build_subset
from .cutoffs import MODEL_REGISTRY, safe_start_after_cutoffs, validate_target_window

__all__ = [
    "MODEL_REGISTRY",
    "build_subset",
    "safe_start_after_cutoffs",
    "validate_target_window",
]
