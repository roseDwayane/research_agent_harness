"""Shared pieces of the AutoSurvey-style evaluation (naive_baseline.py, autosurvey_eval.py).

* ``load_papers``     the session's legal sources: bib keys with title / year / abstract (fusion-block sessions:
                      the bibliography and the search records; archived-engine sessions: step5 frontmatter)
* ``step6_survey``    the Step 6 review as a reader sees it, without code-generated parts
* ``step6_sections``  its judged sections (Executive Summary, Themes, Cross-Theme Analysis)
* ``OllamaChat``      one-message chat call (AutoSurvey sends a single user message, no system prompt)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests

from step6_cites import CiteFinder, is_fusion_session
from step6_common import is_papers_inventory, parse_bib_keys, split_frontmatter
from step6_world import load_world

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


def _bib_fields(bib_text: str) -> dict[str, dict[str, str]]:
    """{key: {title, year}} from step4_references.bib."""
    out = {}
    for entry in re.split(r"\n(?=@)", bib_text):
        head = re.match(r"@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,", entry)
        if not head:
            continue
        title = re.search(r"\btitle\s*=\s*\{(.+?)\},?\s*\n", entry, re.S)
        year = re.search(r"\byear\s*=\s*\{?(\d{4})", entry)
        out[head.group(1)] = {"title": " ".join(title.group(1).split()) if title else "",
                              "year": year.group(1) if year else ""}
    return out


def load_papers(session_dir: Path) -> dict[str, dict[str, Any]]:
    """{key: {title, year, abstract, access_level}} for every key in step4_references.bib (sorted).

    Fusion-block session (knowledge/decon/): the files of step5_full_text carry no frontmatter, so the title and year
    come from the bibliography, the abstract from the search records (step2 raw / snowball) and access_level from the
    decon record's `basis` ("full-text", else "abstract-only"). Archived-engine session: the step5 frontmatter."""
    bib_text = (session_dir / "step4_references.bib").read_text(encoding="utf-8")
    keys = sorted(parse_bib_keys(bib_text))
    if is_fusion_session(session_dir):
        world = load_world(session_dir)
        fields = _bib_fields(bib_text)
        return {key: {"title": fields.get(key, {}).get("title", ""), "year": fields.get(key, {}).get("year", ""),
                      "access_level": "full-text" if world.paper_basis(key) == "full-text" else "abstract-only",
                      "abstract": " ".join(world.abstracts.get(key, "").split())}
                for key in keys}
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


def survey_text(review_md: Path, cite_render: str) -> str:
    """The review as the judge reads it. A fusion-block review cites ids (X0019, galt2019#E1); with `keys` they are
    written as the paper keys they rest on (step6_cites.py), so the judge reads a survey, not identifiers. The judge
    prompts are MetaSyn's and are not changed. An archived-engine review is returned as it is."""
    survey = step6_survey(review_md.read_text(encoding="utf-8"))
    if cite_render != "keys":
        return survey
    session = review_md.parent
    return CiteFinder(session, set(load_papers(session))).render(survey)


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


# --------------------------------------------------------------------------- #
# Gemini (API judge)
# --------------------------------------------------------------------------- #
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def load_api_key(name: str) -> str | None:
    """`name` from the environment, else from the nearest `.env` above this file. The value is never printed."""
    import os
    if os.environ.get(name):
        return os.environ[name]
    for folder in Path(__file__).resolve().parents:
        env = folder / ".env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8").splitlines():
                m = re.match(rf"\s*(?:export\s+)?{re.escape(name)}\s*=\s*(.*)", line)
                if m and m.group(1).strip().strip("\"'"):
                    return m.group(1).strip().strip("\"'")
    return None


class GeminiChat:
    """Same call shape as OllamaChat, for a Gemini model. Thinking is `low` (see __call__); the local judges run with think=False.
    `max_calls` bounds the spend of one process: the call that would exceed it raises instead of being sent."""

    THINK_ROOM = 1024

    def __init__(self, model: str, max_calls: int = 600, timeout: float = 300.0):
        self.model, self.max_calls, self.timeout = model, max_calls, timeout
        self.calls = self.prompt_tokens = self.output_tokens = 0
        self.key = load_api_key("GEMINI_API_KEY")
        if not self.key:
            raise SystemExit("GEMINI_API_KEY is not set (environment or a .env above evaluation/)")

    def __call__(self, prompt: str, *, num_predict: int, temperature: float = 0.0) -> dict[str, Any]:
        import time
        if self.calls >= self.max_calls:
            raise RuntimeError(f"{self.model}: call budget of {self.max_calls} reached")
        # Gemini 3.x cannot switch thinking off (thinkingBudget 0 is ignored) and counts the thinking tokens against
        # maxOutputTokens, so a short answer budget alone returns an empty reply. Thinking is set to `low` and the limit
        # leaves room for it; the answer itself is still cut at what the prompt asks for.
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": num_predict + self.THINK_ROOM, "seed": 0,
                                     "thinkingConfig": {"thinkingLevel": "low"}}}
        for attempt in range(6):
            response = requests.post(f"{GEMINI_URL}/{self.model}:generateContent", json=body, timeout=self.timeout,
                                     headers={"x-goog-api-key": self.key})
            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 2 ** attempt * 3))
                continue
            break
        if response.status_code != 200:   # the body can echo the request; report the status and the API's message only
            try:
                message = response.json().get("error", {}).get("message", "")[:200]
            except ValueError:
                message = ""
            raise RuntimeError(f"{self.model}: HTTP {response.status_code} {message}")
        payload = response.json()
        self.calls += 1
        usage = payload.get("usageMetadata", {})
        self.prompt_tokens += usage.get("promptTokenCount", 0)
        self.output_tokens += usage.get("candidatesTokenCount", 0)
        cand = (payload.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
        if not text.strip():   # never cache an empty judgement as if it were an answer
            raise RuntimeError(f"{self.model}: empty reply (finishReason {cand.get('finishReason')})")
        return {"text": text, "thought_tokens": usage.get("thoughtsTokenCount"), "prompt_tokens": usage.get("promptTokenCount"),
                "output_tokens": usage.get("candidatesTokenCount"), "done_reason": cand.get("finishReason")}


def is_api_model(model: str) -> bool:
    return model.startswith("gemini")


def make_chat(model: str, num_ctx: int = 32768, think: bool | None = False, max_calls: int = 600):
    """The client for a judge name: `gemini-*` goes to the Gemini API, anything else to the local Ollama server."""
    return GeminiChat(model, max_calls=max_calls) if is_api_model(model) else OllamaChat(model, num_ctx, think=think)
