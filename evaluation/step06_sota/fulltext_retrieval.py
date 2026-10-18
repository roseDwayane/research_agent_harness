"""Full-text evidence for the citation NLI: the cited paper's abstract + its top-K full-text windows.

AutoSurvey judges a citation against the cited paper's abstract. On Step 6 that underestimates
support for claims citing full-text papers (metasyn_v2, step6: abstract recall 0.54 vs 0.83 with
full text on those claims), because Step 6 reads full text. So the source for each (claim, key)
is the abstract plus the K windows of the paper's step5_full_text that best match the claim.

Designed on the 6 dev reviews only (255, 356, 225, 243, 324, 70), then frozen (2026-10-14):

    v1  paragraphs, plain token overlap, top-3, each cut to 1500 chars (feasibility run only)
    v2  ~120-word windows (stride 60), score = NUM_WEIGHT * claim numbers found in the window
        + BM25 (IDF over the paper's own windows), top-K windows in document order, abstract
        always included; sweep K 3–5, weight 3 / 6 → K = 3, weight 6       ← used here

Validity controls on metasyn_v2 (26 reviews): citations swapped for random other keys of the
same .bib → recall 0.04; numbers / direction words changed in the claim → recall 0.80 → 0.07.
"""
from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

from step6_common import split_frontmatter

STOP = set("the and for with that this from were was are has have had not but its their than into between among "
           "after before over under also more less both such these those which while when where who per vs".split())
NUM_RE = re.compile(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?")
WIN_WORDS, STRIDE, K, NUM_WEIGHT = 120, 60, 3, 6.0  # frozen 2026-10-14 after the dev-only sweep
VERSION = "v2"


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2 and t not in STOP]


def numbers(text: str) -> set[str]:
    """Distinctive numbers of a claim: drop years and bare single digits (citation-free counts like '3 studies')."""
    out = set()
    for raw in NUM_RE.findall(text):
        n = raw.replace(",", "").rstrip(".")
        if not n or (n.isdigit() and (len(n) == 1 or 1900 <= int(n) <= 2030)):
            continue
        out.add(n)
    return out


def has_number(n: str, text: str) -> bool:
    return re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", text.replace(",", "")) is not None


@lru_cache(maxsize=None)
def body_text(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    _, body, _ = split_frontmatter(p.read_text(encoding="utf-8"))
    return "\n".join(body)


@lru_cache(maxsize=None)
def windows(path: str) -> tuple[str, ...]:
    words = " ".join(body_text(path).split()).split(" ")
    if len(words) <= WIN_WORDS:
        return (" ".join(words),) if words != [""] else ()
    return tuple(" ".join(words[i:i + WIN_WORDS]) for i in range(0, len(words) - STRIDE, STRIDE))


def retrieve(path: str, claim: str, abstract: str, k: int = K) -> str:
    """Abstract + the k best-matching windows of the paper at ``path`` (a step5_full_text/{key}.md)."""
    wins = windows(path)
    if not wins:
        return abstract
    docs = [tokens(w) for w in wins]
    n, avg = len(docs), sum(map(len, docs)) / len(docs)
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    q, nums = set(tokens(claim)), numbers(claim)

    def score(i: int) -> float:
        d = docs[i]
        bm25 = sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * (tf := d.count(t)) * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(d) / avg))
                   for t in q if t in df)
        return NUM_WEIGHT * sum(has_number(x, wins[i]) for x in nums) + bm25

    top = sorted(sorted(range(n), key=score, reverse=True)[:k])  # keep document order
    return "\n".join([abstract, *["… " + wins[i] + " …" for i in top]])
