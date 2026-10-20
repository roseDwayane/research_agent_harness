"""IdeaBench Figure-5 target-idea extraction (exact paper wording in the user prompt)."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from scholar_research.llm.client import LLMClient

PROMPT_NAME = "ideabench_extract_idea"
_START = re.compile(r"^(Hypothesis:|Given that)\s", re.I)


class IdeaBenchTargetIdea(BaseModel):
    """One paragraph beginning with Hypothesis: or Given that ."""

    summary: str = Field(description="Single paragraph starting with 'Hypothesis: ' or 'Given that '")

    @field_validator("summary")
    @classmethod
    def _must_start_correctly(cls, v: str) -> str:
        text = (v or "").strip()
        if not _START.match(text):
            raise ValueError("summary must begin with 'Hypothesis: ' or 'Given that '")
        return text


def extract_target_idea(llm: LLMClient, abstract: str, *, step: int = 80) -> str:
    out = llm.structured(
        PROMPT_NAME,
        IdeaBenchTargetIdea,
        {"target_paper_abstract": abstract.strip()},
        step=step,
        tag="ideabench:extract",
    )
    return out.summary
