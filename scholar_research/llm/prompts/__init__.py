"""Versioned prompt files.

Each ``prompts/*.md`` starts with a small frontmatter::

    ---
    version: 1.0.0
    tool_name: emit_pico_queries
    tool_description: ...
    ---
    <system prompt>
    ===USER===
    <user template with {{variables}}>

Changing a prompt changes its version → changes every cache key → old cached
answers are never mistaken for new ones (plan §4.2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    tool_name: str
    tool_description: str
    system: str
    user_template: str

    def render(self, variables: dict[str, Any]) -> str:
        def sub(m: re.Match) -> str:
            key = m.group(1)
            if key not in variables:
                raise KeyError(f"prompt {self.name}: missing variable {key!r}")
            v = variables[key]
            return v if isinstance(v, str) else str(v)

        return re.sub(r"\{\{(\w+)\}\}", sub, self.user_template)


@lru_cache(maxsize=None)
def load_prompt(name: str) -> Prompt:
    path = _DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"prompt {name}: missing frontmatter")
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    body = m.group(2)
    if "===USER===" not in body:
        raise ValueError(f"prompt {name}: missing ===USER=== separator")
    system, user = body.split("===USER===", 1)
    return Prompt(
        name=name,
        version=meta.get("version", "0.0.0"),
        tool_name=meta.get("tool_name", f"emit_{name}"),
        tool_description=meta.get("tool_description", "Return the structured result."),
        system=system.strip(),
        user_template=user.strip(),
    )


def list_prompts() -> list[str]:
    return sorted(p.stem for p in _DIR.glob("*.md"))
