#!/usr/bin/env python3
"""Protocol checks and averages of the deterministic checks for one batch.

Every topic in runs.jsonl is counted, failures included. Each metric is reported two ways:

* ``all``    — over every topic; a topic with no value gets the worst value (rate/pass → 0);
* ``scored`` — over the topics that produced a value, with ``n`` alongside.

The Prometheus columns this summary used to have were removed with the Prometheus judge
(see README "History").

    python evaluation/step06_sota/aggregate.py --batch evaluation/runs/<batch_id>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from statistics import mean
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # evaluation/: eval_common, run_batch

from eval_common import batch_paths, read_json, read_runs, sha256_file, write_json


# --------------------------------------------------------------------------- #
# protocol: same model / prompts / params, auto checkpoints, untouched outputs
# --------------------------------------------------------------------------- #
def protocol_checks(batch: dict, runs: list[dict], batch_dir: Path) -> dict[str, Any]:
    expected = batch["protocol"]
    per_topic = {}
    for record in runs:
        if "session_dir" not in record:
            per_topic[record["id"]] = {"session": False}
            continue
        session = batch_dir / record["session_dir"]
        checks: dict[str, Any] = {"session": session.is_dir()}
        manifest_path = session / "run_manifest.json"
        if manifest_path.exists():
            manifest = read_json(manifest_path)
            checks["same_config"] = manifest.get("config") == expected["config"]
            checks["same_engine_sha"] = manifest.get("engine_git_sha") == expected["git"]["sha"]
            used = {}
            for step in manifest.get("steps", []):
                used.update(step.get("prompt_versions") or {})
            checks["same_prompt_versions"] = all(expected["prompt_versions"].get(k) == v for k, v in used.items())
            # A provider that errors (e.g. Semantic Scholar 429 without an API key) is only a warning in
            # the harness, so "same search sources" can silently differ between topics.
            step2 = next((s for s in manifest.get("steps", []) if s["step"] == 2), None)
            if step2 is not None:
                failed = sorted({n.split(":", 1)[1].strip().split("/", 1)[0] for n in step2.get("notes", [])
                                 if n.startswith("source failure:")} - {"snowball"})
                raw = session / "step2_raw_papers.json"
                counts = read_json(raw).get("search_summary", {}).get("sources", {}) if raw.exists() else {}
                checks["search_sources_failed"] = failed
                checks["search_source_counts"] = counts
                checks["search_sources_complete"] = not failed
            step6 = next((s for s in manifest.get("steps", []) if s["step"] == 6 and s["status"] == "ok"), None)
            if step6 is not None:
                now = sha256_file(session / "step6_sota_review.md")
                checks["step6_untouched"] = now == step6["outputs"].get("step6_sota_review.md") == record.get("step6_sha256_at_run_end")
        cps_path = session / "checkpoints.json"
        if cps_path.exists():
            modes = {d["mode"] for d in read_json(cps_path).get("decisions", {}).values()}
            checks["auto_checkpoints_only"] = modes <= {"auto"}
        per_topic[record["id"]] = checks

    def all_true(key: str) -> bool | None:
        values = [c[key] for c in per_topic.values() if key in c]
        return all(values) if values else None

    keys = ("same_config", "same_engine_sha", "same_prompt_versions", "auto_checkpoints_only", "step6_untouched",
            "search_sources_complete")
    summary = {key: all_true(key) for key in keys}
    summary["git_tree_clean_at_start"] = not expected["git"]["dirty_files"]
    return {"summary": summary, "per_topic": per_topic}


# --------------------------------------------------------------------------- #
def both_ways(values: list[float | None], worst: float) -> dict[str, Any]:
    present = [v for v in values if v is not None]
    return {
        "all": round(float(mean(v if v is not None else worst for v in values)), 4) if values else None,
        "scored": round(float(mean(present)), 4) if present else None,
        "n_scored": len(present),
        "n_total": len(values),
    }


def rate(flags: list[bool | None]) -> dict[str, Any]:
    return both_ways([None if f is None else float(f) for f in flags], 0.0)


def build_rows(runs: list[dict]) -> list[dict]:
    rows = []
    for r in runs:
        det = r.get("deterministic", {})
        contract = det.get("contract", {}) if det.get("contract", {}).get("status") != "checker_error" else {}
        numeric = det.get("numeric", {}) if det.get("numeric", {}).get("status") != "checker_error" else {}
        rows.append({
            "id": r["id"],
            "pipeline_status": r["pipeline_status"],
            "failed_step": r.get("failed_step"),
            "error": r.get("error"),
            "wall_seconds": r.get("wall_seconds"),
            "step6_present": r.get("step6_present", False),
            "checker_status": det.get("status"),
            "integrity_pass": None if not contract else not contract["integrity_fail"],
            "structure_pass": contract.get("structure_pass"),
            "theme_count": contract.get("theme_count"),
            "coverage_rate": contract.get("coverage_rate"),
            "coverage_pass": contract.get("coverage_pass"),
            "contract_overall_pass": contract.get("overall_pass"),
            "numeric_attestation": numeric.get("numeric_attestation"),
            "numeric_pass": numeric.get("pass"),
        })
    return rows


def metrics(rows: list[dict]) -> dict[str, Any]:
    return {
        "topics": len(rows),
        "pipeline_ok": sum(r["pipeline_status"] == "ok" for r in rows),
        "step6_present": sum(r["step6_present"] for r in rows),
        "deterministic": {
            "integrity_pass": rate([r["integrity_pass"] for r in rows]),
            "structure_pass": rate([r["structure_pass"] for r in rows]),
            "coverage_pass": rate([r["coverage_pass"] for r in rows]),
            "contract_overall_pass": rate([r["contract_overall_pass"] for r in rows]),
            "numeric_pass": rate([r["numeric_pass"] for r in rows]),
            "coverage_rate": both_ways([r["coverage_rate"] for r in rows], 0.0),
            "numeric_attestation": both_ways([r["numeric_attestation"] for r in rows], 0.0),
        },
    }


def render_markdown(batch_id: str, protocol: dict, m: dict, rows: list[dict]) -> str:
    fmt = lambda v: "—" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))  # noqa: E731
    yn = lambda v: "—" if v is None else ("✓" if v else "✗")  # noqa: E731
    lines = [f"# Step 6 evaluation — batch `{batch_id}`", "",
             f"Topics: {m['topics']} · pipeline ok: {m['pipeline_ok']} · Step 6 produced: {m['step6_present']}",
             "", "## Protocol", ""]
    lines += [f"- {k}: {yn(v)}" for k, v in protocol["summary"].items()]
    lines += ["", "## Averages", "", "`all` counts every topic (missing → worst value); `scored` only topics with a value.", "",
              "| Metric | all | scored | n scored / total |", "|---|---|---|---|"]
    for name, v in m["deterministic"].items():
        lines.append(f"| {name} | {fmt(v['all'])} | {fmt(v['scored'])} | {v['n_scored']}/{v['n_total']} |")
    header = ["Topic", "Pipeline", "Integrity", "Structure", "Themes", "Coverage", "Numeric"]
    lines += ["", "## Per topic", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        pipe = "ok" if r["pipeline_status"] == "ok" else f"{r['pipeline_status']} @ step {r['failed_step']}"
        lines.append("| " + " | ".join([r["id"], pipe, yn(r["integrity_pass"]), yn(r["structure_pass"]), fmt(r["theme_count"]),
                                         fmt(r["coverage_rate"]), fmt(r["numeric_attestation"])]) + " |")
    search = {tid: c for tid, c in protocol["per_topic"].items() if "search_source_counts" in c}
    if search:
        lines += ["", "## Search sources (papers returned per source)", "", "| Topic | Counts | Failed sources |", "|---|---|---|"]
        lines += [f"| {tid} | {', '.join(f'{k} {v}' for k, v in c['search_source_counts'].items())} | "
                  f"{', '.join(c['search_sources_failed']) or '—'} |" for tid, c in search.items()]
    failures = [r for r in rows if r["pipeline_status"] != "ok"]
    if failures:
        lines += ["", "## Failures (kept, not dropped)", ""]
        for r in failures:
            lines.append(f"- **{r['id']}** pipeline={r['pipeline_status']} step={r['failed_step']}: {r['error'] or ''}")
    return "\n".join(lines) + "\n"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", required=True)
    args = parser.parse_args()

    batch_dir = Path(args.batch).resolve()
    paths = batch_paths(batch_dir)
    batch, runs = read_json(paths["batch"]), read_runs(batch_dir)

    rows = build_rows(runs)
    protocol = protocol_checks(batch, runs, batch_dir)
    m = metrics(rows)
    write_json(paths["eval"] / "summary.json", {"batch_id": batch["batch_id"], "protocol": protocol,
                                                "metrics": m, "topics": rows})
    md = render_markdown(batch["batch_id"], protocol, m, rows)
    (paths["eval"] / "summary.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
