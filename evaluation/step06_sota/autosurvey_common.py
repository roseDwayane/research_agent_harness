"""Shared pieces of the AutoSurvey-style evaluation (naive_baseline.py, autosurvey_eval.py).

* ``load_papers``     the session's legal sources: bib keys with title / year / abstract from step5_full_text
* ``step6_survey``    the Step 6 review as a reader sees it, without code-generated parts
* ``step6_sections``  its judged sections (Executive Summary, Themes, Cross-Theme Analysis)
* ``OllamaChat``      one-message chat call (AutoSurvey sends a single user message, no system prompt)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests

from step6_common import is_papers_inventory, parse_bib_keys, split_frontmatter

OLLAMA_URL = "http://127.0.0.1:11434"
# Generated from data by the engine, not written by the model: not part of the judged survey.
CODE_GENERATED_SECTIONS = re.compile(r"^(Methodology Legend|Paper[–-]Theme Mapping)\b", re.IGNORECASE)
STEP6_SECTION_RE = re.compile(r"^##\s+(Executive Summary|Theme\s+\d+\s*:|Cross[-\s]Theme Analysis)", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #
def _abstract(body: list[str]) -> str:
    out, inside = [], False
    for line in body:
        if re.match(r"^##\s+Abstract\b", line, re.IGNORECASE):
            inside = True
            continue
        if inside and re.match(r"^#{1,2}\s", line):
            break
        if inside:
            out.append(line)
    return " ".join(" ".join(out).split())


def load_papers(session_dir: Path) -> dict[str, dict[str, Any]]:
    """{key: {title, year, abstract, access_level}} for every key in step4_references.bib (bib order)."""
    keys = sorted(parse_bib_keys((session_dir / "step4_references.bib").read_text(encoding="utf-8")))
    papers = {}
    for key in keys:
        path = session_dir / "step5_full_text" / f"{key}.md"
        meta: dict[str, str] = {}
        body: list[str] = []
        if path.exists():
            meta, body, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        papers[key] = {
            "title": meta.get("title", "").strip('"'),
            "year": meta.get("year", "").strip('"'),
            "access_level": meta.get("access_level", "").strip('"') or None,
            "abstract": _abstract(body),
        }
    return papers


# --------------------------------------------------------------------------- #
# survey text
# --------------------------------------------------------------------------- #
def step6_survey(review_md: str) -> str:
    """The review with Methodology Legend, Paper–Theme Mapping and Papers inventory lines removed."""
    _, body, _ = split_frontmatter(review_md)
    kept, skipping = [], False
    for line in body:
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading and len(heading.group(1)) <= 2:
            skipping = bool(CODE_GENERATED_SECTIONS.match(heading.group(2).strip()))
        if skipping or is_papers_inventory(line):
            continue
        kept.append(line)
    text = "\n".join(kept)
    text = re.sub(r"\n(?:-{3,}\s*\n)+", "\n", text)  # section separators
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def step6_sections(survey: str) -> list[tuple[str, str]]:
    """(title, text with its '## ' heading) for every judged section of a step6_survey text, in order:
    Executive Summary, each Theme, Cross-Theme Analysis (Limitations and other level-2 parts are left out)."""
    blocks = re.split(r"(?m)^(?=##\s)", survey)
    return [(b.splitlines()[0][2:].strip(), b.strip() + "\n") for b in blocks if STEP6_SECTION_RE.match(b)]


def strip_fence(text: str) -> str:
    """Drop a ```markdown fence some models wrap the whole answer in."""
    match = re.match(r"^\s*```(?:markdown|md)?\s*\n(.*?)\n```\s*$", text, re.S)
    return match.group(1) if match else text


# --------------------------------------------------------------------------- #
# Ollama
# --------------------------------------------------------------------------- #
class OllamaChat:
    def __init__(self, model: str, num_ctx: int = 32768, think: bool | None = False, base_url: str = OLLAMA_URL,
                 timeout: float = 1800.0):
        self.model, self.num_ctx, self.think, self.timeout = model, num_ctx, think, timeout
        self.url = f"{base_url.rstrip('/')}/api/chat"

    def __call__(self, prompt: str, *, num_predict: int, temperature: float = 0.0) -> dict[str, Any]:
        response = requests.post(self.url, timeout=self.timeout, json={
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": temperature, "seed": 0, "num_ctx": self.num_ctx, "num_predict": num_predict},
            **({"think": self.think} if self.think is not None else {}),
        })
        response.raise_for_status()
        payload = response.json()
        prompt_tokens = payload.get("prompt_eval_count")
        # Ollama silently drops the start of an overflowing prompt; refuse instead.
        if prompt_tokens is not None and prompt_tokens + num_predict > self.num_ctx:
            raise RuntimeError(f"{prompt_tokens} prompt tokens + {num_predict} new tokens exceed num_ctx={self.num_ctx}")
        return {"text": payload["message"]["content"], "prompt_tokens": prompt_tokens,
                "output_tokens": payload.get("eval_count"), "done_reason": payload.get("done_reason")}
