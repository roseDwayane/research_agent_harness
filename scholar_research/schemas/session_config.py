"""step0_session_config.json — frozen contract shared by every step."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PICO(BaseModel):
    population: str
    intervention: str
    comparison: str
    outcome: str
    setting: str = ""
    timeframe: str = ""


class PICOZh(BaseModel):
    population: str
    intervention: str
    comparison: str
    outcome: str
    setting: str = ""


class Query(BaseModel):
    id: str
    strategy: str
    query: str
    rationale: str
    rationale_zh: str = ""
    strategy_zh: str = ""


class EngineInfo(BaseModel):
    """Pinned run-time facts (plan §4.2): never write 'latest'."""

    version: str
    llm_model: str
    llm_temperature: float = 0.0


class SessionConfig(BaseModel):
    session_id: str
    topic: str
    topic_original: str
    topic_slug: str
    timestamp: str
    current_step: int = 0
    pico: PICO
    pico_zh: PICOZh | None = None
    source_urls: list[str] = Field(default_factory=list)
    queries: list[Query] = Field(default_factory=list)
    field_type: str = "biomedical"  # biomedical | cs_engineering | other  (drives PubMed on/off)
    engine: EngineInfo | None = None

    @property
    def folder_name(self) -> str:
        return f"{self.session_id}_{self.topic_slug}"

    def year_range(self) -> tuple[int, int]:
        """Parse '2019-2026' → (2019, 2026). Falls back to a 7-year window."""
        import re

        m = re.findall(r"(19|20)\d{2}", self.pico.timeframe or "")
        years = [int(x) for x in re.findall(r"(?:19|20)\d{2}", self.pico.timeframe or "")]
        if len(years) >= 2:
            return min(years), max(years)
        if len(years) == 1:
            return years[0], years[0] + 7
        end = int(self.session_id[:4])
        return end - 7, end

    def dump(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)
