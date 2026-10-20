"""Resolve gold S2ORC corpusIds via the existing Semantic Scholar client."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from scholar_research.cache import Cache
from scholar_research.providers.base import HttpClient
from scholar_research.providers.semantic_scholar import SemanticScholar
from scholar_research.utils import normalize_doi


def unique_corpusids(questions: Iterable[dict[str, Any]]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for q in questions:
        for cid in q.get("corpusids") or []:
            n = int(cid)
            if n not in seen:
                seen.add(n)
                out.append(n)
    return out


def _entry(cid: int, rec: dict[str, Any] | None) -> dict[str, Any]:
    if rec is None:
        return {"corpusId": cid, "ok": False, "error": "s2_lookup_failed"}
    ext = rec.get("externalIds") or {}
    ax = ext.get("ArXiv")
    return {
        "corpusId": cid,
        "ok": True,
        "paperId": rec.get("paperId"),
        "title": rec.get("title"),
        "year": rec.get("year"),
        "doi": normalize_doi(ext.get("DOI")),
        "arxiv_id": str(ax) if ax else None,
        "citationCount": rec.get("citationCount"),
    }


def build_gold_id_map(
    corpusids: list[int],
    cache_dir: Path,
    api_key: str | None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lookup CorpusId:N. Cached HTTP; retries ids that previously failed (e.g. S2 429)."""
    out = dict(existing or {})
    todo = [c for c in corpusids if str(c) not in out or not out[str(c)].get("ok")]
    cache = Cache(cache_dir, "read-write")
    http = HttpClient(cache)
    s2 = SemanticScholar(http, api_key)
    if not api_key:
        http.limiter.intervals["api.semanticscholar.org"] = 4.0
    try:
        still: list[int] = []
        for cid in todo:
            rec = s2.lookup(f"CorpusId:{cid}")
            if rec:
                out[str(cid)] = _entry(cid, rec)
            else:
                still.append(cid)
        if still:
            # A cached 429 would otherwise stick forever; refetch those ids.
            http2 = HttpClient(Cache(cache_dir, "refresh"))
            s2b = SemanticScholar(http2, api_key)
            if not api_key:
                http2.limiter.intervals["api.semanticscholar.org"] = 4.0
            try:
                for cid in still:
                    rec = s2b.lookup(f"CorpusId:{cid}")
                    out[str(cid)] = _entry(cid, rec)
            finally:
                http2.close()
    finally:
        http.close()
    return out


def load_map(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def dump_map(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def years_for(question: dict[str, Any], id_map: dict[str, Any]) -> list[int]:
    years = []
    for cid in question.get("corpusids") or []:
        rec = id_map.get(str(cid)) or {}
        y = rec.get("year")
        if isinstance(y, int):
            years.append(y)
    return years
