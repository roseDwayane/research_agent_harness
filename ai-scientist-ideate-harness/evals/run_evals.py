#!/usr/bin/env python3
"""Run the evaluation cases in evals/cases/*.json and write machine-readable results.

    python evals/run_evals.py [--tag T ...] [--case ID ...] [--json] [--results PATH] [--update-expected]

Case fields: case_id, unit_id, description, tags, evaluation_method (deterministic | llm_rubric), dataset (a folder
of evals/datasets/, copied fresh per case), steps [{id, tool | function, args}], assertions
[{step?, path, op, value?}], expected_error {error_code}, expected_output {file, path}, rubric (for llm_rubric).

Placeholders in args: "$RUN" (the case's copy of its dataset), "$WORK" (the case workspace, the only allowed root),
"$OUTSIDE" (a directory outside every allowed root), "${<step id>:<json pointer>}" (a value from an earlier step).
Deterministic cases call the tools through mcp/ideate_v2_mcp/tools/envelope.execute - the same validation and envelope as the
server - or a whitelisted pure function. llm_rubric cases need a judge and are reported as not_executed otherwise.

Exit codes: 0 every executed case passed, 1 a case failed or errored, 2 bad case files.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
sys.path[:0] = [str(MODULE), str(MODULE / "mcp" / "ideate_v2_mcp")]

from ideate_v2 import contracts, retry, rules  # noqa: E402
from ideate_v2.errors import IdeateError, from_exception  # noqa: E402
from ideate_v2.jsonio import read_json  # noqa: E402
from ideate_v2.paths import PathPolicy  # noqa: E402
from ideate_v2.registry import Registry  # noqa: E402
from ideate_v2.schema_lite import validate  # noqa: E402
from tools.envelope import execute  # noqa: E402
from tools.handlers import HANDLERS, Context  # noqa: E402

CASE_SCHEMA = read_json(HERE / "case.schema.json")
VOLATILE = {"timestamp", "at", "event_id", "span_id", "trace_id", "run_id", "duration_ms", "generated_at", "error_id",
            "run_dir", "recorded_event_id", "parent_error_id", "imported_at"}
_REF = re.compile(r"^\$\{([A-Za-z0-9_]+):(/[^}]*)\}$")


# --------------------------------------------------------------------------------------------- helpers
def pointer(doc, ptr: str):
    """JSON pointer lookup; keys may contain dots (A2.s). Raises KeyError when absent."""
    cur = doc
    for raw in ptr.split("/")[1:] if ptr else []:
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(ptr)
    return cur


def normalise(x):
    if isinstance(x, dict):
        return {k: normalise(v) for k, v in sorted(x.items()) if k not in VOLATILE}
    if isinstance(x, list):
        return [normalise(v) for v in x]
    return x


def contract_mutation(args: dict) -> dict:
    """Validate the contracts after applying mutations: patch_unit {id, set}, duplicate_unit, patch_artifact
    {id, set}. -> {codes: ERROR/WARN codes, counts}."""
    base = MODULE / "contracts"
    arch = read_json(base / "architecture.json")
    docs = [read_json(base / f) for f in arch["unit_files"]]
    for m in args.get("mutations", []):
        if "patch_unit" in m:
            for d in docs:
                for u in d["units"]:
                    if u["id"] == m["patch_unit"]["id"]:
                        u.update(m["patch_unit"]["set"])
        elif "duplicate_unit" in m:
            for d in docs:
                hit = [u for u in d["units"] if u["id"] == m["duplicate_unit"]]
                if hit:
                    d["units"].append(copy.deepcopy(hit[0]))
                    break
        elif "patch_artifact" in m:
            for a in arch["artifacts"]:
                if a["id"] == m["patch_artifact"]["id"]:
                    a.update(m["patch_artifact"]["set"])
        else:
            raise IdeateError("IDEATE.INPUT.INVALID", f"unknown mutation {m}")
    reg = Registry(arch, docs, read_json(base / "legacy_snapshot.json"), path=base / "architecture.json")
    found = contracts.validate_registry(reg, include_info=False)
    return {"codes": sorted({f["code"] for f in found}), "counts": contracts.summary(found),
            "findings": [f"{f['level']} {f['code']} {f['entity']}: {f['message']}" for f in found][:30]}


FUNCTIONS = {
    "rules.snowball_threshold": lambda a: {"value": rules.snowball_threshold(a["n"])},
    "rules.snowball_round2_allowed": lambda a: {"value": rules.snowball_round2_allowed(a["growth"])},
    "rules.ready_question_target": lambda a: {"value": rules.ready_question_target(a.get("max_num_generations"))},
    "rules.reflection_round_cap": lambda a: {"value": rules.reflection_round_cap(a["num_reflections"])},
    "rules.decision_tree_findings": lambda a: {"findings": rules.decision_tree_findings(
        read_json(Path(a["tree"])) if isinstance(a["tree"], str) else a["tree"], a.get("max_weak_share", 0.5),
        a.get("primary_claim"))},
    "rules.leaf_odds": lambda a: {"odds": {k: round(v, 4) for k, v in rules.leaf_odds(a["tree"]).items()}},
    "retry.backoff_delay": lambda a: {"delay_s": retry.backoff_delay(a["backoff"], a["attempt_done"], a["seed"])},
    "contracts.mutation": contract_mutation,
}


def call_function(name: str, args: dict) -> dict:
    t0 = time.monotonic()
    try:
        data = FUNCTIONS[name](args)
        env = {"ok": True, "tool": name, "data": data}
    except Exception as e:  # noqa: BLE001
        env = {"ok": False, "tool": name, "error": (e if isinstance(e, IdeateError) else from_exception(e)).payload()}
    env["duration_ms"] = round((time.monotonic() - t0) * 1000, 2)
    return env


def substitute(obj, env: dict, outputs: dict):
    if isinstance(obj, dict):
        return {k: substitute(v, env, outputs) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute(v, env, outputs) for v in obj]
    if isinstance(obj, str):
        m = _REF.match(obj)
        if m:
            return pointer(outputs[m.group(1)], m.group(2))
        for k, v in env.items():
            obj = obj.replace(k, v)
    return obj


OPS = {
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b, "gte": lambda a, b: a >= b, "lte": lambda a, b: a <= b,
    "in": lambda a, b: a in b, "contains": lambda a, b: b in a, "len_eq": lambda a, b: len(a) == b,
    "len_gte": lambda a, b: len(a) >= b, "matches": lambda a, b: re.search(b, str(a)) is not None,
    "any_eq": lambda a, b: any(all(x.get(k) == v for k, v in b.items()) for x in a),
    "none_eq": lambda a, b: not any(all(x.get(k) == v for k, v in b.items()) for x in a),
    "all_eq": lambda a, b: all(all(x.get(k) == v for k, v in b.items()) for x in (a.values() if isinstance(a, dict) else a)),
}


def check(assertion: dict, outputs: dict, last: str) -> str | None:
    target = outputs[assertion.get("step", last)]
    op, path = assertion["op"], assertion["path"]
    try:
        actual = pointer(target, path)
    except (KeyError, IndexError, ValueError):
        return None if op == "not_exists" else f"{path}: absent"
    if op == "exists":
        return None
    if op == "not_exists":
        return f"{path}: present ({actual!r})"
    expected = assertion.get("value")
    if isinstance(expected, str) and _REF.match(expected):
        expected = substitute(expected, {}, outputs)
    try:
        ok = OPS[op](actual, expected)
    except Exception as e:  # noqa: BLE001
        return f"{path} {op} {expected!r}: {type(e).__name__}: {e}"
    return None if ok else f"{path} {op} {expected!r} failed (actual {json.dumps(actual, ensure_ascii=False)[:200]})"


# --------------------------------------------------------------------------------------------- running
def run_case(case: dict, reg: Registry, update_expected: bool) -> dict:
    t0 = time.monotonic()
    res = {"case_id": case["case_id"], "unit_id": case["unit_id"], "tags": case["tags"],
           "evaluation_method": case["evaluation_method"], "failures": []}
    if case["evaluation_method"] == "llm_rubric":
        res.update(status="not_executed", reason="needs an LLM judge (rubric " + case.get("rubric", "?") + "); "
                   "no judge is configured - see evals/README.md")
        return res
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        work.mkdir()
        (work / "empty").mkdir()
        outside = Path(tmp) / "outside"
        outside.mkdir()
        run = work / "run"
        if case.get("dataset"):
            shutil.copytree(HERE / "datasets" / case["dataset"], run)
        env = {"$RUN": str(run), "$WORK": str(work), "$OUTSIDE": str(outside), "$DATASETS": str(HERE / "datasets")}
        ctx = Context(reg, PathPolicy((work.resolve(),)))
        outputs: dict = {}
        last = None
        try:
            for i, step in enumerate(case["steps"]):
                sid = step.get("id", f"s{i}")
                args = substitute(step.get("args", {}), env, outputs)
                if "tool" in step:
                    outputs[sid] = execute(step["tool"], HANDLERS[step["tool"]], ctx, args)
                else:
                    outputs[sid] = call_function(step["function"], args)
                last = sid
                if step.get("expect_ok", True) and not outputs[sid]["ok"] and step is not case["steps"][-1]:
                    res["failures"].append(f"step {sid} failed: {outputs[sid]['error']['error_code']}: "
                                           f"{outputs[sid]['error']['error_message'][:160]}")
                    break
            if not res["failures"]:
                exp_err = case.get("expected_error")
                if exp_err:
                    env_last = outputs[last]
                    if env_last["ok"]:
                        res["failures"].append(f"expected error {exp_err['error_code']}, got ok")
                    elif env_last["error"]["error_code"] != exp_err["error_code"]:
                        res["failures"].append(f"expected error {exp_err['error_code']}, got "
                                               f"{env_last['error']['error_code']}: {env_last['error']['error_message'][:120]}")
                for a in case.get("assertions", []):
                    msg = check(a, outputs, last)
                    if msg:
                        res["failures"].append(msg)
                eo = case.get("expected_output")
                if eo:
                    actual = normalise(pointer(outputs[eo.get("step", last)], eo["path"]))
                    path = HERE / eo["file"]
                    if update_expected:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps(actual, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                        newline="\n")
                    elif not path.is_file():
                        res["failures"].append(f"expected output {eo['file']} missing (run with --update-expected)")
                    elif read_json(path) != actual:
                        res["failures"].append(f"output differs from {eo['file']} (regression)")
        except Exception as e:  # noqa: BLE001 - a broken case is an error, not a pass
            res.update(status="error", failures=res["failures"] + [f"{type(e).__name__}: {e}"])
            res["duration_ms"] = round((time.monotonic() - t0) * 1000, 2)
            return res
    res["status"] = "pass" if not res["failures"] else "fail"
    res["duration_ms"] = round((time.monotonic() - t0) * 1000, 2)
    return res


def load_cases() -> tuple[list[dict], list[str]]:
    cases, problems = [], []
    for f in sorted((HERE / "cases").glob("*.json")):
        doc = read_json(f)
        for c in doc.get("cases", []):
            errs = validate(c, CASE_SCHEMA)
            if errs:
                problems.append(f"{f.name}:{c.get('case_id', '?')}: {errs[0]}")
            cases.append({**c, "_file": f.name})
    ids = [c.get("case_id") for c in cases]
    problems += [f"duplicate case_id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return cases, problems


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):        # a console code page (cp1252) must not crash on a path
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description="Run the ideate_v2 evaluation cases.")
    ap.add_argument("--tag", action="append", default=[], help="only cases with this tag (repeatable)")
    ap.add_argument("--case", action="append", default=[], help="only this case id (repeatable)")
    ap.add_argument("--json", action="store_true", help="print the results JSON")
    ap.add_argument("--results", type=Path, default=HERE / "results" / "latest.json")
    ap.add_argument("--update-expected", action="store_true", help="rewrite expected/ snapshots from this run")
    a = ap.parse_args(argv)
    cases, problems = load_cases()
    if problems:
        print("bad case files:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    sel = [c for c in cases if (not a.tag or set(a.tag) & set(c["tags"])) and (not a.case or c["case_id"] in a.case)]
    reg = Registry.load()
    results = [run_case(c, reg, a.update_expected) for c in sel]
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("pass", "fail", "error", "not_executed")}
    executed = counts["pass"] + counts["fail"] + counts["error"]
    summary = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cases": len(results),
               "counts": counts, "executed": executed,
               "pass_rate": round(counts["pass"] / executed, 4) if executed else None,
               "by_tag": {}}
    for r in results:
        for t in r["tags"]:
            b = summary["by_tag"].setdefault(t, {"pass": 0, "fail": 0, "error": 0, "not_executed": 0})
            b[r["status"]] += 1
    a.results.parent.mkdir(parents=True, exist_ok=True)
    a.results.write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8", newline="\n")
    if a.json:
        print(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False))
    else:
        for r in results:
            mark = {"pass": "PASS", "fail": "FAIL", "error": "ERR ", "not_executed": "N/E "}[r["status"]]
            print(f"{mark} {r['case_id']:16} {r['unit_id']:18} " + ("; ".join(r["failures"])[:200] if r["failures"]
                                                                   else r.get("reason", "")[:100]))
        print(f"\n{len(results)} cases: {counts['pass']} passed, {counts['fail']} failed, {counts['error']} errors, "
              f"{counts['not_executed']} not executed (LLM rubric); pass rate of executed "
              f"{summary['pass_rate'] if summary['pass_rate'] is not None else '-'}; results -> {a.results}")
    return 1 if counts["fail"] or counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
