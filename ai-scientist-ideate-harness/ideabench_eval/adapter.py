from __future__ import annotations

import ast
import csv
import hashlib
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .jsonio import write_json


def _rows(path: Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _literal(value: str | None, default: Any) -> Any:
    try:
        return ast.literal_eval(value) if value else default
    except (SyntaxError, ValueError):
        return default


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def _domain_ids(source: Path, domain: str | None) -> set[str] | None:
    if not domain:
        return None
    path = source / "ideabench_clustering.json"
    if not path.is_file():
        raise FileNotFoundError(f"domain filtering requires {path}")
    clusters = json.loads(path.read_text(encoding="utf-8"))
    if domain not in clusters:
        raise ValueError(f"unknown domain {domain!r}; choices: {', '.join(sorted(clusters))}")
    return set(clusters[domain])


def import_official(source: Path, out: Path, *, domain: str | None = "Health & Medicine",
                    low_k: int = 5, seed: int = 0, limit: int | None = None) -> dict:
    """Freeze official IdeaBench refs and gold without exposing target abstracts.

    ``target_papers.csv.abstract_summary`` is copied only to ``gold/``. Generation
    task files contain no target title, abstract, or gold text.
    """
    source, out = Path(source), Path(out)
    if low_k != 5:
        raise ValueError("this offline protocol requires exactly five references")
    target_csv, refs_csv = source / "target_papers.csv", source / "filtered_references.csv"
    if not target_csv.is_file() or not refs_csv.is_file():
        raise FileNotFoundError("source must contain target_papers.csv and filtered_references.csv")
    allowed = _domain_ids(source, domain)
    by_target: dict[str, list[dict]] = defaultdict(list)
    for row in _rows(refs_csv):
        target_id = (row.get("targetPaperId") or "").strip()
        if not target_id or (allowed is not None and target_id not in allowed):
            continue
        ref = {
            "paperId": (row.get("paperId") or "").strip(),
            "title": (row.get("title") or "").strip(),
            "abstract": (row.get("abstract") or "").strip(),
            "year": int(float(row["year"])) if (row.get("year") or "").strip() else None,
            "venue": (row.get("venue") or "").strip() or None,
        }
        if ref["paperId"] and ref["title"] and ref["abstract"]:
            by_target[target_id].append(ref)

    tasks, skipped = [], defaultdict(int)
    for row in _rows(target_csv):
        target_id = (row.get("paperId") or "").strip()
        if allowed is not None and target_id not in allowed:
            continue
        gold = (row.get("abstract_summary") or "").strip()
        refs = sorted(by_target.get(target_id, []), key=lambda x: x["paperId"])
        if not gold:
            skipped["missing_abstract_summary"] += 1
            continue
        if len(refs) < low_k:
            skipped["fewer_than_five_references"] += 1
            continue
        task_seed = int(hashlib.sha256(f"{seed}:{target_id}".encode()).hexdigest()[:16], 16)
        selected = random.Random(task_seed).sample(refs, low_k)
        task_id = _safe(target_id)
        write_json(out / "tasks" / task_id / "references.json", {
            "paperId": target_id, "count": low_k, "selection_seed": task_seed, "references": selected,
        })
        gold_path = out / "gold" / f"{task_id}.txt"
        gold_path.parent.mkdir(parents=True, exist_ok=True)
        gold_path.write_text(gold + "\n", encoding="utf-8", newline="\n")
        tasks.append({"paperId": target_id, "taskKey": task_id, "references": f"tasks/{task_id}/references.json",
                      "gold": f"gold/{task_id}.txt"})
        if limit is not None and len(tasks) >= limit:
            break
    if not tasks:
        raise ValueError("no eligible IdeaBench tasks")
    manifest = {
        "schema": "ideabench-offline-dataset/1", "source": str(source.resolve()), "domain": domain or "all",
        "count": len(tasks), "low_k": low_k, "seed": seed,
        "gold": "target_papers.csv abstract_summary",
        "blinding": "generation reads references.json only; gold is loaded by ranking after P1/P2 generation",
        "skipped": dict(skipped), "tasks": tasks,
    }
    write_json(out / "manifest.json", manifest)
    return manifest


def load_tasks(dataset: Path, limit: int | None = None) -> list[dict]:
    dataset = Path(dataset)
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8-sig"))
    if manifest.get("low_k") != 5:
        raise ValueError("dataset is not a fixed-five-reference dataset")
    tasks = []
    for row in manifest["tasks"][:limit]:
        refs = json.loads((dataset / row["references"]).read_text(encoding="utf-8-sig"))["references"]
        if len(refs) != 5 or len({r["paperId"] for r in refs}) != 5:
            raise ValueError(f"{row['paperId']}: references must contain five distinct papers")
        tasks.append({"paperId": row["paperId"], "taskKey": row.get("taskKey") or _safe(row["paperId"]),
                      "references": refs, "gold_path": dataset / row["gold"]})
    return tasks

