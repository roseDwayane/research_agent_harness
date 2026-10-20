"""Load LitSearch queries and freeze the Table-7-shaped subset."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

SUBSET_SEED = 20260924
HF_DATASET = "princeton-nlp/LitSearch"
HF_ROWS = "https://datasets-server.huggingface.co/rows"
# LitSearch Table 7: 80 specific questions, 40 inline-citation + 40 author-written.
N_INLINE = 40
N_AUTHOR = 40


def is_inline(query_set: str) -> bool:
    return str(query_set).lower().startswith("inline")


def is_author(query_set: str) -> bool:
    s = str(query_set).lower()
    return s.startswith("manual") or "author" in s


def _row_from_hf(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_set": rec["query_set"],
        "query": rec["query"],
        "specificity": int(rec["specificity"]),
        "quality": int(rec["quality"]),
        "corpusids": [int(x) for x in rec["corpusids"]],
    }


def load_hf_queries() -> list[dict[str, Any]]:
    try:
        from datasets import load_dataset
    except ImportError:
        return _load_hf_queries_via_api()
    rows = []
    for rec in load_dataset(HF_DATASET, "query", split="full"):
        rows.append(_row_from_hf(rec))
    return rows


def _load_hf_queries_via_api() -> list[dict[str, Any]]:
    """Fallback when the `datasets` package is not installed."""
    import httpx

    rows: list[dict[str, Any]] = []
    offset = 0
    page = 100
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        while True:
            r = client.get(HF_ROWS, params={"dataset": HF_DATASET, "config": "query", "split": "full", "offset": offset, "length": page})
            r.raise_for_status()
            chunk = r.json().get("rows") or []
            if not chunk:
                break
            for item in chunk:
                rows.append(_row_from_hf(item["row"]))
            offset += len(chunk)
            if len(chunk) < page:
                break
    if len(rows) < 500:
        raise RuntimeError(f"HuggingFace rows API returned only {len(rows)} LitSearch queries")
    return rows


def _take_stratified_quality(pool: list[dict[str, Any]], n: int, rng: random.Random) -> list[dict[str, Any]]:
    """Sample n items, keeping Qual=1 / Qual=2 proportions, then fill shortages."""
    if n <= 0 or not pool:
        return []
    q1 = [q for q in pool if int(q["quality"]) == 1]
    q2 = [q for q in pool if int(q["quality"]) == 2]
    n2 = round(n * len(q2) / len(pool)) if pool else 0
    n2 = max(0, min(n2, len(q2), n))
    n1 = min(n - n2, len(q1))
    short = n - n1 - n2
    extra1 = min(short, len(q1) - n1)
    n1 += extra1
    n2 += min(short - extra1, len(q2) - n2)
    rng.shuffle(q1)
    rng.shuffle(q2)
    out = q1[:n1] + q2[:n2]
    rng.shuffle(out)
    return out


def stratified_table7(
    queries: list[dict[str, Any]],
    *,
    n_inline: int = N_INLINE,
    n_author: int = N_AUTHOR,
    seed: int = SUBSET_SEED,
) -> list[dict[str, Any]]:
    """80 specific questions: 40 inline + 40 author, Qual-stratified. IDs are assigned stably."""
    rng = random.Random(seed)
    specific = [q for q in queries if int(q["specificity"]) == 1]
    inline = _take_stratified_quality([q for q in specific if is_inline(q["query_set"])], n_inline, rng)
    author = _take_stratified_quality([q for q in specific if is_author(q["query_set"])], n_author, rng)
    chosen = inline + author
    chosen.sort(key=lambda q: (q["query_set"], q["query"]))
    out = []
    for i, q in enumerate(chosen, 1):
        row = dict(q)
        row["qid"] = f"ls_{i:03d}"
        row["split"] = "inline" if is_inline(q["query_set"]) else "author"
        out.append(row)
    return out


def dump_subset(path: Path, rows: list[dict[str, Any]], seed: int = SUBSET_SEED) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seed": seed,
        "description": "LitSearch Table-7 clone: 80 specific, 40 inline + 40 author, Qual-stratified.",
        "n": len(rows),
        "questions": rows,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_subset_file(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["questions"] if isinstance(data, dict) and "questions" in data else data


def packaged_subset_path() -> Path | None:
    p = Path(__file__).with_name("subset_v1.json")
    return p if p.exists() else None


def load_frozen_subset(path: Path | None = None) -> list[dict[str, Any]]:
    if path is not None:
        return load_subset_file(path)
    bundled = packaged_subset_path()
    if bundled is not None:
        return load_subset_file(bundled)
    raise FileNotFoundError("no frozen LitSearch subset — run with --freeze first")
