#!/usr/bin/env python3
"""Run every available check and report which ran, passed, failed or were skipped (and why).

    python scripts/run_checks.py [--strict] [--json] [--only NAME ...] [--fast]

Checks (in order): compile, json-parse, contracts, docs-fresh, architecture-doc, datasets, unit-tests, evals,
mcp-smoke, legacy-drift, shadow-compare, lint. A check whose tool or prerequisite is unavailable is SKIPPED with the
reason and the command to run it - never silently. --fast skips the slow shadow comparison.

Exit codes: 0 every check that ran passed; 1 a check failed; 2 --strict and a check was skipped.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

MODULE = Path(__file__).resolve().parent.parent
PY = sys.executable
ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}


def sh(args: list, timeout: int = 1800) -> tuple[int, str]:
    p = subprocess.run([str(a) for a in args], cwd=MODULE, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=ENV, timeout=timeout)
    return p.returncode, (p.stdout + ("\n" + p.stderr if p.stderr.strip() else "")).strip()


def last_line(text: str, pattern: str | None = None) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip() and '"event": "tool_call"' not in ln]
    if pattern:
        hits = [ln for ln in lines if re.search(pattern, ln)]
        if hits:
            return hits[-1].strip()[:220]
    return (lines[-1].strip() if lines else "")[:220]


def has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


# each check -> (status, detail); status PASS | FAIL | SKIP
def c_compile():
    code, out = sh([PY, "-m", "compileall", "-q", "ideate_v2", "harness", "mcp", "scripts", "evals", "tests"])
    return ("PASS" if code == 0 else "FAIL"), (out[-300:] or "all modules compile")


def c_json():
    bad = []
    files = [p for p in MODULE.rglob("*.json") if "results" not in p.parts and ".pytest_cache" not in p.parts]
    for p in files:
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            bad.append(f"{p.relative_to(MODULE)}: {e}")
    return ("FAIL", "; ".join(bad[:5])) if bad else ("PASS", f"{len(files)} JSON files parse")


def c_contracts():
    code, out = sh([PY, "scripts/validate_contracts.py", "--quiet"])
    return ("PASS" if code == 0 else "FAIL"), last_line(out, r"units, .* substeps")


def c_docs():
    code, out = sh([PY, "scripts/render_docs.py", "--check"])
    return ("PASS" if code == 0 else "FAIL"), " | ".join(out.splitlines())[:220]


def c_architecture():
    code, out = sh([PY, "scripts/validate_architecture.py", "--quiet"])
    return ("PASS" if code == 0 else "FAIL"), last_line(out, r"ARCHITECTURE_v2")


def c_datasets():
    code, out = sh([PY, "evals/build_datasets.py", "--check"])
    return ("PASS" if code == 0 else "FAIL"), last_line(out)


def c_tests():
    if not has("pytest"):
        return "SKIP", "pytest not installed: pip install -r requirements-dev.txt, then python -m pytest tests -q"
    code, out = sh([PY, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "--no-header", "-rs"])
    summary = last_line(out, r"(passed|failed|error)")
    skips = [ln.strip() for ln in out.splitlines() if ln.startswith("SKIPPED")]
    detail = summary + (f" | skipped: {'; '.join(s[:120] for s in skips)}" if skips else "")
    return ("PASS" if code == 0 else "FAIL"), detail


def c_evals():
    code, out = sh([PY, "evals/run_evals.py"])
    return ("PASS" if code == 0 else "FAIL"), last_line(out, r"cases:")


def c_mcp():
    if not has("mcp"):
        return "SKIP", "the official MCP SDK is not installed: pip install -r requirements.txt"
    code, out = sh([PY, "mcp/ideate_v2_mcp/server.py", "--check"])
    if code != 0:
        return "FAIL", out[-300:]
    data = json.loads(out[out.index("{"):])
    return "PASS", f"{len(data['tools'])} tools registered, {data['units']} units loaded"


def c_legacy_drift():
    code, out = sh([PY, "scripts/import_legacy_registry.py", "--check"])
    return ("PASS" if code == 0 else "FAIL"), last_line(out)


def c_shadow():
    code, out = sh([PY, "evals/shadow_compare.py"], timeout=3600)
    if code == 2:
        return "SKIP", last_line(out)
    return ("PASS" if code == 0 else "FAIL"), last_line(out, r"TOTAL")


# The v2 layer only: the Unit implementation (scripts/ideate_tools.py, it_*.py, mcp/scholar_mcp, ...) is kept as it
# came and is checked by its own suite (scripts/tests).
LINT_PATHS = ["ideate_v2", "harness", "mcp/ideate_v2_mcp", "tests", "scripts/run_checks.py", "scripts/render_docs.py",
              "scripts/validate_architecture.py", "scripts/validate_contracts.py", "scripts/import_legacy_registry.py",
              "evals/run_evals.py", "evals/build_datasets.py", "evals/shadow_compare.py"]


def c_lint():
    paths = [p for p in LINT_PATHS if (MODULE / p).exists()]
    if not has("ruff"):
        return "SKIP", "ruff not installed (optional): pip install ruff, then ruff check " + " ".join(paths)
    code, out = sh([PY, "-m", "ruff", "check", "--select", "E,F,W", "--ignore", "E501", *paths])
    return ("PASS" if code == 0 else "FAIL"), last_line(out) or "clean"


def c_recipes():
    code, out = sh([PY, "-m", "harness", "recipes"])
    return ("PASS" if code == 0 else "FAIL"), last_line(out, r"recipe\(s\)")


def c_legacy_units():
    code, out = sh([PY, "scripts/ideate_tools.py", "units", "check"])
    return ("PASS" if code == 0 else "FAIL"), last_line(out) or "units check"


CHECKS = [("compile", c_compile), ("json-parse", c_json), ("contracts", c_contracts), ("docs-fresh", c_docs),
          ("architecture-doc", c_architecture), ("datasets", c_datasets), ("unit-tests", c_tests), ("evals", c_evals),
          ("mcp-smoke", c_mcp), ("legacy-drift", c_legacy_drift), ("legacy-units", c_legacy_units),
          ("recipes", c_recipes), ("shadow-compare", c_shadow), ("lint", c_lint)]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):        # a console code page (cp1252) must not crash on a path
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description="Run every available check.")
    ap.add_argument("--strict", action="store_true", help="a skipped check fails the run")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", action="append", default=[], choices=[n for n, _ in CHECKS])
    ap.add_argument("--fast", action="store_true", help="skip the shadow comparison")
    a = ap.parse_args(argv)
    results = []
    for name, fn in CHECKS:
        if a.only and name not in a.only:
            continue
        if a.fast and name == "shadow-compare":
            results.append({"check": name, "status": "SKIP", "seconds": 0.0, "detail": "--fast"})
            continue
        t0 = time.monotonic()
        try:
            status, detail = fn()
        except Exception as e:  # noqa: BLE001 - a crashing check is a failure, reported as such
            status, detail = "FAIL", f"{type(e).__name__}: {e}"
        results.append({"check": name, "status": status, "seconds": round(time.monotonic() - t0, 1), "detail": detail})
        if not a.json:
            print(f"{status:4}  {name:17} {results[-1]['seconds']:6.1f}s  {detail}", flush=True)
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ("PASS", "FAIL", "SKIP")}
    code = 1 if counts["FAIL"] else (2 if a.strict and counts["SKIP"] else 0)
    if a.json:
        print(json.dumps({"results": results, "counts": counts, "exit_code": code}, indent=2, ensure_ascii=False))
    else:
        print(f"\n{len(results)} checks: {counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped"
              f" -> exit {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
