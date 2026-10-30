"""Normalize free-text search strings for S2 / OpenAlex."""
from __future__ import annotations

import re

_SEARCH_STOP = frozenset(
    "a an the of for and or not in on with to from by via using based into at as is are be "
    "was were been being its their this that these those it i we you me my our your any some "
    "could would should can may might please point recommend looking explore find there have "
    "has had do does did about over than then so such also more most other between which who "
    "whom what where when how why particularly especially specifically including include "
    "could you point me to research on".split()
)


def sanitize_search(query: str) -> str:
    """Strip `?`/`*` — OpenAlex treats them as wildcards and HTTP 400s stemmed search."""
    return re.sub(r"[?*]+", " ", query).strip()


def compact_search(query: str) -> str:
    return " ".join(w for w in sanitize_search(query).split() if w.lower() not in _SEARCH_STOP and len(w) > 2)


def search_variants(query: str) -> list[str]:
    """Full sanitized query first, then stopword-stripped fallback (no duplicates)."""
    out: list[str] = []
    for q in (sanitize_search(query), compact_search(query)):
        q = " ".join(q.split())
        if q and q not in out:
            out.append(q)
    return out
