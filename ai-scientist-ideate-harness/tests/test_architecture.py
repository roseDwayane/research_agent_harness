"""Integration tests of the contracts, the ledger view, gates, reports and the documentation."""
from __future__ import annotations

import json

import pytest

from ideate_v2 import ARCHITECTURE_DOC, docs, events, gates, ledger, report
from ideate_v2.contracts import validate_registry
from ideate_v2.errors import IdeateError
from ideate_v2.spec import FIELDS, canonical_spec


def test_contracts_are_valid(reg):
    found = validate_registry(reg, include_info=False)
    assert found == [], found


def test_inventory_counts(reg):
    assert len(reg.units) == 38 and len(reg.substeps) == 31
    assert {s["block"] for s in reg.steps()} == {"BLK-search", "BLK-fusion", "BLK-planning"}


def test_every_unit_has_all_27_fields(reg):
    for u in reg.units:
        spec = canonical_spec(reg, u)
        assert list(spec) == [k for k, _ in FIELDS]
        assert all(spec[k] for k, _ in FIELDS), u


def test_topological_order_respects_requires(reg):
    order = reg.topo_order()
    pos = {u: i for i, u in enumerate(order)}
    assert all(pos[r] < pos[u] for u in reg.units for r in reg.requires(u))


def test_on_ledger_units_match_the_legacy_registry(reg):
    assert {u for u, s in reg.units.items() if s["on_ledger"]} == set(reg.legacy["units"]) - {"P1", "P2", "P3", "P4",
                                                                                              "P5"}


def test_gates_chain_the_steps(reg):
    order = reg.step_order()
    for g in reg.arch["gates"]:
        assert order.index(g["from_step"]) < order.index(g["to_step"])


def test_stale_propagates_downstream_only(reg, dataset):
    _, run = dataset("search_complete")
    before = ledger.unit_states(reg, run)
    assert all(before[u]["state"] == "done" for u in ("A1.p", "A2.s", "A3", "A5", "A4.b"))
    (run / "step2_relevance_check.json").write_text('{"rounds": [], "caveats": []}\n', encoding="utf-8")
    after = ledger.unit_states(reg, run)
    assert after["A2.c"]["state"] == "stale"
    assert after["A2.m"]["state"] == "done"                       # upstream untouched
    assert after["A3.b"]["state"] == "stale"                      # downstream, through requires


def test_planning_status_by_presence(dataset):
    _, run = dataset("planning")
    st = ledger.planning_status(run, 2)
    assert st["units"]["B5"]["state"] == "todo" and st["units"]["P5"]["state"] == "done"


def test_gate_on_unknown_or_missing_generation(reg, dataset):
    _, run = dataset("planning")
    with pytest.raises(IdeateError):
        gates.evaluate_gate(reg, run, "GATE-tree-check", generation=9)
    with pytest.raises(IdeateError):
        gates.evaluate_gate(reg, run, "GATE-nope")


def test_report_writes_only_ignored_paths(reg, dataset):
    _, run = dataset("search_complete")
    before = {p.relative_to(run).as_posix() for p in run.rglob("*") if p.is_file()}
    report.build_report(reg, run, "r_20261022_100000_abcd")
    after = {p.relative_to(run).as_posix() for p in run.rglob("*") if p.is_file()}
    new = after - before
    assert new and all(p.startswith("_state/errors/") or p == "ERRORS.md" for p in new), new


def test_event_lifecycle_table():
    ev = lambda t, **k: events.build_event(t, run_id="r_20261022_100000_abcd", trace_id="0" * 32, **k)  # noqa: E731
    log = [ev("RUN_STARTED")]
    assert events.lifecycle_problems(log, ev("TOOL_CALLED", unit_id="A3"))
    log.append(ev("UNIT_STARTED", unit_id="A3"))
    assert not events.lifecycle_problems(log, ev("TOOL_CALLED", unit_id="A3"))
    assert events.lifecycle_problems(log, ev("UNIT_COMPLETED", unit_id="A3", attempt=2))
    log.append(ev("UNIT_FAILED", unit_id="A3"))
    assert not events.lifecycle_problems(log, ev("RETRY_SCHEDULED", unit_id="A3"))
    assert events.lifecycle_problems(log, ev("UNIT_STARTED", unit_id="A3", attempt=1))   # attempt must advance
    log.append(ev("RUN_COMPLETED"))
    assert events.lifecycle_problems(log, ev("UNIT_STARTED", unit_id="A3", attempt=2))


def test_generated_docs_are_fresh(reg):
    from ideate_v2 import MODULE_ROOT
    for path in (ARCHITECTURE_DOC, MODULE_ROOT / "references" / "unit_contracts.md"):
        assert docs.stale_blocks(reg, path) == [], path


def test_stale_block_is_detected(reg, tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("x\n" + docs.BEGIN.format(name="decisions") + "\nold\n" + docs.END.format(name="decisions") + "\n",
                 encoding="utf-8")
    assert docs.stale_blocks(reg, p) == ["decisions"]
    p.write_text(docs.render_file(reg, p.read_text(encoding="utf-8")), encoding="utf-8")
    assert docs.stale_blocks(reg, p) == []


def test_legacy_snapshot_is_pinned(reg):
    src = reg.legacy["source"]
    assert src["schema"] == "ideate-units/1" and len(src["sha256"]) == 64
    assert json.loads(json.dumps(reg.legacy))["units"]["A6.d"]["achieved_level"] == "L2"
