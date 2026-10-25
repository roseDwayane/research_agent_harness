"""The CLI scripts: exit codes on good and broken inputs (they are what CI runs)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from conftest import MODULE

PY = sys.executable


def run(*args, cwd=MODULE):
    return subprocess.run([PY, *map(str, args)], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          env={**__import__("os").environ, "PYTHONUTF8": "1"})


def test_validate_contracts_passes():
    p = run("scripts/validate_contracts.py", "--json")
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr
    assert json.loads(p.stdout)["counts"]["ERROR"] == 0


def test_validate_contracts_fails_on_a_broken_registry(tmp_path):
    shutil.copytree(MODULE / "contracts", tmp_path / "contracts")
    p = tmp_path / "contracts" / "units" / "search.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["units"][0]["requires"] = ["NOPE"]
    p.write_text(json.dumps(doc), encoding="utf-8")
    r = run("scripts/validate_contracts.py", "--registry", tmp_path / "contracts" / "architecture.json", "--quiet")
    assert r.returncode == 1 and "C-REF" in r.stdout


def test_validate_contracts_unreadable_registry(tmp_path):
    bad = tmp_path / "architecture.json"
    bad.write_text("{", encoding="utf-8")
    assert run("scripts/validate_contracts.py", "--registry", bad).returncode == 2


def test_validate_architecture_passes():
    p = run("scripts/validate_architecture.py", "--quiet")
    assert p.returncode == 0, p.stdout[-3000:]


def test_validate_architecture_detects_a_missing_section_and_unknown_id(tmp_path):
    from ideate_v2 import ARCHITECTURE_DOC
    text = ARCHITECTURE_DOC.read_text(encoding="utf-8")
    text = text.replace("## 8. Migration and Transition Plan", "## 8. Something else", 1) + "\nSee GATE-imaginary.\n"
    doc = tmp_path / "ARCHITECTURE.md"
    doc.write_text(text, encoding="utf-8")
    p = run("scripts/validate_architecture.py", "--doc", doc, "--json")
    found = {f["code"] for f in json.loads(p.stdout)["findings"]}
    assert p.returncode == 1 and {"A-SECTION", "A-ID-UNKNOWN"} <= found


def test_render_docs_check_is_clean():
    p = run("scripts/render_docs.py", "--check")
    assert p.returncode == 0, p.stdout


def test_datasets_are_reproducible():
    p = run("evals/build_datasets.py", "--check")
    assert p.returncode == 0, p.stdout
