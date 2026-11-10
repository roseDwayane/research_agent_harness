"""Resolve official LitSearch gold corpus IDs to Semantic Scholar paper aliases."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .adapter import read_json, write_json

API = "https://api.semanticscholar.org/graph/v1/paper/"
FIELDS = "paperId,corpusId,title,year,externalIds,citationCount"


def gold_ids(tasks: list[dict]) -> list[str]:
    return list(dict.fromkeys(str(cid) for task in tasks for cid in task.get("corpusids") or []))


def lookup_corpus_id(cid: str, *, api_key: str | None = None, timeout: float = 30,
                     retries: int = 3) -> dict:
    url = API + urllib.parse.quote(f"CorpusId:{cid}") + "?fields=" + FIELDS
    headers = {"Accept": "application/json", "User-Agent": "litsearch-evaluation/1"}
    if api_key:
        headers["x-api-key"] = api_key
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt + 1 == retries:
                raise
            delay = exc.headers.get("Retry-After")
            time.sleep(float(delay) if delay and delay.isdigit() else min(30, 2 ** attempt * 4))
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 == retries:
                raise
            time.sleep(min(30, 2 ** attempt * 4))
    raise RuntimeError(f"no response for CorpusId:{cid}")


def make_entry(cid: str, paper: dict) -> dict:
    external = paper.get("externalIds") or {}
    doi = external.get("DOI")
    arxiv = external.get("ArXiv")
    return {"corpusId": int(cid), "ok": bool(paper.get("paperId")), "paperId": paper.get("paperId"),
            "title": paper.get("title"), "year": paper.get("year"),
            "doi": str(doi).removeprefix("https://doi.org/").lower() if doi else None,
            "arxiv_id": str(arxiv) if arxiv else None, "citationCount": paper.get("citationCount")}


def build_mapping(tasks_path: Path, out: Path, *, delay: float | None = None,
                  api_key_env: str = "SEMANTIC_SCHOLAR_API_KEY", lookup=lookup_corpus_id,
                  limit: int | None = None, say=print) -> dict:
    if delay is not None and delay < 0:
        raise ValueError("delay must be nonnegative")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    tasks = [json.loads(line) for line in Path(tasks_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit is not None:
        tasks = tasks[:limit]
    ids = gold_ids(tasks)
    if not ids:
        raise ValueError("tasks contain no gold corpusids")
    out = Path(out)
    data = read_json(out) if out.is_file() else {}
    key = os.environ.get(api_key_env)
    pause = delay if delay is not None else (0.5 if key else 4.0)
    pending = [cid for cid in ids if not (data.get(cid) or {}).get("ok")]
    for number, cid in enumerate(pending, 1):
        try:
            data[cid] = make_entry(cid, lookup(cid, api_key=key))
            if not data[cid]["ok"]:
                data[cid]["error"] = "paperId missing from Semantic Scholar response"
        except Exception as exc:
            data[cid] = {"corpusId": int(cid), "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        write_json(out, data)
        say(f"mapping {number}/{len(pending)} CorpusId:{cid} {'ok' if data[cid]['ok'] else 'failed'}")
        if number < len(pending):
            time.sleep(pause)
    matched = sum(bool((data.get(cid) or {}).get("ok")) for cid in ids)
    return {"status": "complete" if matched == len(ids) else "incomplete", "questions": len(tasks), "gold_ids": len(ids),
            "mapped": matched, "unmapped": len(ids) - matched, "path": str(out)}
