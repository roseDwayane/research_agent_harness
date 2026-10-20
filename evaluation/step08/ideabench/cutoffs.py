"""Generator knowledge-cutoff registry and target-window safety checks.

Target papers must be published strictly after every evaluated generator's
training cutoff so Insight Score measures ideation, not memorization.
"""
from __future__ import annotations

import datetime as _dt
from typing import Iterable

# Exact calendar dates (YYYY-MM-DD). Update when you pin a new generator.
MODEL_REGISTRY: dict[str, str] = {
    "local_qwen_3.8B": "2024-10-29",
    "cloud_claude_3.5": "2024-04-30",
    "cloud_gpt_4o": "2023-10-31",
    "cloud_qwen_max": "2025-03-31",
}


def _parse(d: str) -> _dt.date:
    return _dt.datetime.strptime(d, "%Y-%m-%d").date()


def latest_cutoff(models: Iterable[str], registry: dict[str, str] | None = None) -> _dt.date:
    reg = registry or MODEL_REGISTRY
    latest = _dt.date.min
    missing: list[str] = []
    for name in models:
        if name not in reg:
            missing.append(name)
            continue
        c = _parse(reg[name])
        if c > latest:
            latest = c
    if missing:
        raise KeyError(f"unknown model(s) in MODEL_REGISTRY: {missing}; known={sorted(reg)}")
    if latest == _dt.date.min:
        raise ValueError("models list is empty")
    return latest


def safe_start_after_cutoffs(models: Iterable[str], registry: dict[str, str] | None = None) -> _dt.date:
    """Earliest allowed target start = first day of the month after the latest cutoff."""
    latest = latest_cutoff(models, registry)
    if latest.month == 12:
        return _dt.date(latest.year + 1, 1, 1)
    return _dt.date(latest.year, latest.month + 1, 1)


def validate_target_window(
    models: list[str],
    target_start: str,
    target_end: str,
    *,
    registry: dict[str, str] | None = None,
) -> dict[str, str]:
    """Raise ``ValueError`` if ``[target_start, target_end]`` overlaps any model cutoff window."""
    start = _parse(target_start)
    end = _parse(target_end)
    if end < start:
        raise ValueError(f"target_end ({target_end}) is before target_start ({target_start})")
    safe = safe_start_after_cutoffs(models, registry)
    latest = latest_cutoff(models, registry)
    if start < safe:
        raise ValueError(
            f"contamination risk: target_start {target_start} is before safe boundary {safe.isoformat()} "
            f"(latest cutoff among {models} is {latest.isoformat()})"
        )
    return {
        "latest_cutoff": latest.isoformat(),
        "safe_start": safe.isoformat(),
        "target_start": target_start,
        "target_end": target_end,
        "models": ",".join(models),
    }
