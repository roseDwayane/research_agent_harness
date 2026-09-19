from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

from .base import HttpClient
from .records import Hit

BASE = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
SAFE = ':()[]"'  # characters arXiv wants literal in search_query


def to_arxiv_query(q: str) -> str:
    """Turn a free-text/Boolean query into arXiv `all:` syntax (deterministic)."""
    q = re.sub(r"\[MeSH[^\]]*\]", "", q, flags=re.I)
    q = re.sub(r"\"([^\"]+)\"", lambda m: '"' + m.group(1) + '"', q)
    tokens = re.findall(r'"[^"]+"|\(|\)|\bAND\b|\bOR\b|\bNOT\b|[^\s()]+', q)
    out: list[str] = []
    for t in tokens:
        if t in ("(", ")", "AND", "OR", "NOT"):
            out.append("ANDNOT" if t == "NOT" else t)
        else:
            out.append(f"all:{t}")
    # implicit AND between bare terms
    joined: list[str] = []
    for i, t in enumerate(out):
        if i > 0 and t not in ("AND", "OR", "ANDNOT", ")") and joined[-1] not in ("AND", "OR", "ANDNOT", "("):
            joined.append("AND")
        joined.append(t)
    return " ".join(joined)


class ArXiv:
    name = "arxiv"

    def __init__(self, http: HttpClient):
        self.http = http
        http.limiter.intervals["export.arxiv.org"] = 3.1

    def search(self, query: str, query_id: str, year_from: int, year_to: int, limit: int = 30) -> list[Hit]:
        sq = f"({to_arxiv_query(query)}) AND submittedDate:[{year_from}01010000 TO {year_to}12312359]"
        # arXiv's parser wants ':' '(' ')' '[' ']' literal and spaces as '+', exactly as in its docs —
        # a fully percent-encoded query (httpx default) is answered with HTTP 406.
        url = f"{BASE}?search_query={quote(sq, safe=SAFE)}&start=0&max_results={limit}&sortBy=relevance&sortOrder=descending".replace("%20", "+")
        r = self.http.get(url)
        if not r.ok:
            raise RuntimeError(f"arxiv HTTP {r.status}")
        return self.parse(r.text or "", query_id)

    @staticmethod
    def parse(xml_text: str, query_id: str) -> list[Hit]:
        out: list[Hit] = []
        if not xml_text.strip():
            return out
        root = ET.fromstring(xml_text)
        for e in root.findall("a:entry", NS):
            raw_id = (e.findtext("a:id", default="", namespaces=NS) or "").strip()
            m = re.search(r"abs/([^v]+?)(v\d+)?$", raw_id)
            arxiv_id = m.group(1) if m else raw_id.rsplit("/", 1)[-1]
            title = " ".join((e.findtext("a:title", default="", namespaces=NS) or "").split())
            if not title:
                continue
            summary = " ".join((e.findtext("a:summary", default="", namespaces=NS) or "").split())
            published = e.findtext("a:published", default="", namespaces=NS) or ""
            authors = [a.findtext("a:name", default="", namespaces=NS) for a in e.findall("a:author", NS)]
            doi = e.findtext("arxiv:doi", default=None, namespaces=NS)
            journal_ref = e.findtext("arxiv:journal_ref", default=None, namespaces=NS)
            pc = e.find("arxiv:primary_category", NS)
            out.append(
                Hit(
                    source="arxiv",
                    query_id=query_id,
                    title=title,
                    authors=[a for a in authors if a],
                    year=int(published[:4]) if published[:4].isdigit() else None,
                    journal=journal_ref,
                    doi=doi,
                    url=f"https://arxiv.org/abs/{arxiv_id}",
                    abstract=summary or None,
                    arxiv_id=arxiv_id,
                    venue_type="preprint",
                    arxiv_primary_class=pc.get("term") if pc is not None else None,
                )
            )
        return out
