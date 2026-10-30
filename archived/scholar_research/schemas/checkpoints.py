"""checkpoints.json — human decisions, recorded so replay can re-apply them."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CheckpointDecision(BaseModel):
    checkpoint: int
    name: str
    mode: str  # interactive | file | auto
    decided_at: str
    decision: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


class Checkpoints(BaseModel):
    decisions: dict[str, CheckpointDecision] = Field(default_factory=dict)  # key "1".."4"

    def get(self, n: int) -> CheckpointDecision | None:
        return self.decisions.get(str(n))
