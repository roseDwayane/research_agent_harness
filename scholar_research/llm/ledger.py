"""Append-only ledger of every LLM call (plan §4.2 / §4.4).

One JSON line per call in ``{session}/.cache/llm/ledger.jsonl``:
prompt name+version, model, params, cache hit/miss, token usage, wall time,
sha256 of the request and of the validated response.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LedgerTotals:
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    wall_seconds: float = 0.0
    by_prompt: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "cache_hits": self.cache_hits,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "wall_seconds": round(self.wall_seconds, 3),
            "by_prompt": self.by_prompt,
        }


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.totals = LedgerTotals()

    def record(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        t = self.totals
        t.calls += 1
        if entry.get("cache_hit"):
            t.cache_hits += 1
        usage = entry.get("usage") or {}
        t.input_tokens += int(usage.get("input_tokens") or 0)
        t.output_tokens += int(usage.get("output_tokens") or 0)
        t.wall_seconds += float(entry.get("wall_seconds") or 0.0)
        p = t.by_prompt.setdefault(entry.get("prompt", "?"), {"calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0})
        p["calls"] += 1
        p["cache_hits"] += 1 if entry.get("cache_hit") else 0
        p["input_tokens"] += int(usage.get("input_tokens") or 0)
        p["output_tokens"] += int(usage.get("output_tokens") or 0)
