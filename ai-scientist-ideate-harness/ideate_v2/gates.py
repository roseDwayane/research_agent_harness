"""Handover gates at contract level (decision D-10: a gate passes only when this check AND the legacy domain check pass).

A gate checks, for a research folder (topic scope) or a generation folder (generation scope):
1. every Unit in ``requires_done`` is in state done on the ledger (not stale, failed, waiting or interrupted);
2. every artifact in ``requires_artifacts`` exists and, when it is JSON/JSONL, parses;
3. its named contract rules (RULES below) hold.
Findings: {level ERROR|WARN|INFO, code, message, entity}. ERROR fails the gate.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from . import rules
from .errors import IdeateError
from .jsonio import FileTooLarge, read_json, read_jsonl
from .ledger import ledger_block, load_events, unit_states
from .registry import Registry


def _f(level: str, code: str, message: str, entity: str | None = None) -> dict:
    return {"level": level, "code": code, "message": message, "entity": entity}


def artifact_paths(reg: Registry, art_id: str, base: Path) -> list[Path]:
    """Concrete files for an artifact's path pattern (<key>, <id>, <hash>, <Name>, <topic> and * become globs)."""
    art = reg.get(art_id)
    pattern = art["path"].split(",")[0].strip()
    if pattern.startswith("gen_k/"):
        pattern = pattern[len("gen_k/"):]
    for token in ("<key>", "<id>", "<hash>", "<Name>", "<topic>", "<run_id>", "<unit>", "<instance>", "Q_NNN"):
        pattern = pattern.replace(token, "*")
    if any(ch in pattern for ch in "*?["):
        return sorted(p for p in base.glob(pattern) if p.is_file())
    p = base / pattern
    return [p] if p.is_file() else []


def _load(path: Path):
    if path.suffix == ".jsonl":
        recs, problems = read_jsonl(path)
        if problems:
            raise ValueError(f"line {problems[0]['line']}: {problems[0]['error']}")
        return recs
    if path.suffix == ".json":
        return read_json(path)
    return None


# ----------------------------------------------------------------------------------------------------- rules
def _rule_protocol_evaluation_accepted(reg, base, params, ctx):
    p = base / "step1_protocol_evaluation.json"
    if not p.is_file():
        return [_f("ERROR", "GATE.RULE.protocol_evaluation_accepted", "step1_protocol_evaluation.json missing", "A1.e")]
    status = ((read_json(p) or {}).get("final") or {}).get("status")
    if status in ("approved", "approved-with-notes"):
        return []
    if status == "accepted-with-doubts":
        return [_f("WARN", "GATE.RULE.protocol_evaluation_accepted", "protocol accepted with doubts: caveat "
                   "protocol-doubts must be disclosed", "A1.e")]
    return [_f("ERROR", "GATE.RULE.protocol_evaluation_accepted", f"final status is {status!r} (needs approved, "
               "approved-with-notes or accepted-with-doubts)", "A1.e")]


def _rule_rescreened_after(reg, base, params, ctx):
    """The screener's last done comes after the producer's last done (additions were screened again)."""
    evs = ctx["events"]
    last = {u: max((i for i, e in enumerate(evs) if e.get("unit") == u and e.get("ev") == "done"), default=-1)
            for u in (params["producer"], params["screener"])}
    if last[params["producer"]] < 0:
        return []                                      # reported by requires_done
    if last[params["screener"]] < last[params["producer"]]:
        return [_f("ERROR", "GATE.RULE.rescreened_after", f"{params['screener']} has not screened "
                   f"{params['producer']}'s additions (its last done is earlier)", params["screener"])]
    return []


def _rule_caveats_file_valid(reg, base, params, ctx):
    paths = artifact_paths(reg, params["artifact"], base)
    if not paths:
        return [_f("ERROR", "GATE.RULE.caveats_file_valid", f"{params['artifact']} missing", params["artifact"])]
    data = read_json(paths[0])
    problems = []
    if not isinstance(data.get("caveats"), list) or not isinstance(data.get("must_disclose"), list):
        problems.append("needs lists 'caveats' and 'must_disclose'")
    for c in data.get("caveats") or []:
        if not {"code", "unit", "text", "must_disclose"} <= set(c):
            problems.append(f"caveat {c.get('code', '?')} lacks code/unit/text/must_disclose")
            break
    must = {c.get("code") for c in data.get("caveats") or [] if c.get("must_disclose")}
    listed = {c.get("code") for c in data.get("must_disclose") or [] if isinstance(c, dict)}
    if must != listed:
        problems.append(f"must_disclose list {sorted(listed)} differs from flagged caveats {sorted(must)}")
    out = [_f("ERROR", "GATE.RULE.caveats_file_valid", p, params["artifact"]) for p in problems]
    if not problems and must:
        out.append(_f("INFO", "GATE.RULE.caveats_file_valid", "must disclose: " + ", ".join(sorted(must)),
                      params["artifact"]))
    return out


def _rule_ready_questions_target(reg, base, params, ctx):
    p = base / "questions" / "index.json"
    if not p.is_file():
        return [_f("ERROR", "GATE.RULE.ready_questions_target", "questions/index.json missing", "F.9")]
    idx = read_json(p)
    cfg = read_json(base / "step0_session_config.json") if (base / "step0_session_config.json").is_file() else {}
    target = rules.ready_question_target(cfg.get("max_num_generations"))
    ready = sum(1 for q in idx.get("questions") or [] if q.get("status") == "ready")
    unresolved = sum(1 for q in idx.get("questions") or [] if q.get("status") == "screen_unresolved")
    if ready == 0 and unresolved == 0:
        return [_f("ERROR", "GATE.RULE.ready_questions_target", "no ready question and none kept as screen_unresolved",
                   "F.9")]
    if ready < target:
        # Slide 4 states this as an exit condition; the implementation warns and adds caveat questions-short (OQ-04).
        return [_f("WARN", "GATE.RULE.ready_questions_target", f"{ready} ready question(s), target {target} "
                   "(max(generations, 3) + 2): caveat questions-short must be disclosed (OQ-04)", "F.9")]
    return []


def _rule_decision_tree_weak_mass(reg, base, params, ctx):
    p = base / "decision_tree.json"
    if not p.is_file():
        return [_f("ERROR", "GATE.RULE.decision_tree_weak_mass", "decision_tree.json missing", "P3")]
    tree = read_json(p)
    primary = None
    arg = base / "argument.json"
    if arg.is_file():
        claims = (read_json(arg) or {}).get("claims") or []
        primary = next((c.get("id") for c in claims if isinstance(c, dict) and c.get("primary")), None)
    try:
        fs = rules.decision_tree_findings(tree, params.get("max_weak_share", 0.5), primary)
    except IdeateError as e:
        return [_f("ERROR", "GATE.RULE.decision_tree_weak_mass", f"tree not evaluable: {e}", "P3")]
    return [_f(x["level"], "GATE.RULE.decision_tree_weak_mass", x["message"], "P3") for x in fs]


def _rule_abstract_word_limit(reg, base, params, ctx):
    p = base / "idea_draft.json"
    if not p.is_file():
        return [_f("ERROR", "GATE.RULE.abstract_word_limit", "idea_draft.json missing", "P5")]
    n = rules.word_count((read_json(p) or {}).get("Abstract", ""))
    limit = params.get("limit", rules.ABSTRACT_WORD_LIMIT)
    return [] if n <= limit else [_f("ERROR", "GATE.RULE.abstract_word_limit", f"abstract has {n} words (limit {limit})",
                                     "P5")]


RULES: dict[str, Callable] = {
    "protocol_evaluation_accepted": _rule_protocol_evaluation_accepted,
    "rescreened_after": _rule_rescreened_after,
    "caveats_file_valid": _rule_caveats_file_valid,
    "ready_questions_target": _rule_ready_questions_target,
    "decision_tree_weak_mass": _rule_decision_tree_weak_mass,
    "abstract_word_limit": _rule_abstract_word_limit,
}


# ----------------------------------------------------------------------------------------------------- gate
def evaluate_gate(reg: Registry, run_dir: Path, gate_id: str, generation: int | None = None) -> dict:
    if reg.kind_of(gate_id) != "gate":
        raise IdeateError("IDEATE.INPUT.UNKNOWN_ID", f"no gate {gate_id!r}", context={"gate_id": gate_id})
    gate = reg.get(gate_id)
    rd = Path(run_dir)
    if gate["scope"] == "generation":
        if generation is None:
            raise IdeateError("IDEATE.INPUT.INVALID", f"{gate_id} is generation-scoped: pass generation=<k>")
        base = rd / f"gen_{int(generation)}"
        if not base.is_dir():
            raise IdeateError("IDEATE.ARTIFACT.MISSING", f"generation folder gen_{generation} does not exist",
                              context={"generation": generation})
    else:
        base = rd
    events, problems = load_events(rd)
    findings = [_f("ERROR", "IDEATE.LEDGER.MALFORMED", f"ledger line {p['line']}: {p['error']}", "INFRA-ledger")
                for p in problems]
    states = unit_states(reg, rd, events) if gate["requires_done"] else {}
    for u in gate["requires_done"]:
        if ledger_block(reg, u) is None:
            findings.append(_f("INFO", "GATE.UNIT.NOT_ON_LEDGER", f"{u} is not on the ledger; not checked", u))
            continue
        st = states.get(u, {"state": "todo", "why": ""})
        if st["state"] != "done":
            findings.append(_f("ERROR", "GATE.UNIT.NOT_DONE", f"{u} is {st['state']}" +
                               (f": {st['why']}" if st.get("why") else ""), u))
        elif st.get("unverifiable"):
            findings.append(_f("INFO", "GATE.UNIT.PARTIAL_HASHES", f"{u}: {st['unverifiable']} ledger hash(es) not "
                               "verifiable by v2 (D-11); run the legacy status for full staleness", u))
    for art in gate["requires_artifacts"]:
        paths = artifact_paths(reg, art, base)
        if not paths:
            findings.append(_f("ERROR", "GATE.ARTIFACT.MISSING", f"{art} ({reg.get(art)['path']}) not found", art))
            continue
        for p in paths[:200]:
            try:
                _load(p)
            except (ValueError, json.JSONDecodeError, FileTooLarge) as e:
                findings.append(_f("ERROR", "GATE.ARTIFACT.UNREADABLE", f"{p.relative_to(rd).as_posix()}: {e}", art))
                break
    ctx = {"events": events, "states": states}
    for r in gate["rules"]:
        try:
            findings += RULES[r["rule"]](reg, base, r.get("params") or {}, ctx)
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as e:
            findings.append(_f("ERROR", f"GATE.RULE.{r['rule']}", f"rule could not be evaluated: "
                               f"{type(e).__name__}: {e}", gate_id))
    passed = not any(f["level"] == "ERROR" for f in findings)
    return {"gate": gate_id, "name": gate["name"], "scope": gate["scope"], "from_step": gate["from_step"],
            "to_step": gate["to_step"], "passed": passed,
            "counts": {lvl: sum(1 for f in findings if f["level"] == lvl) for lvl in ("ERROR", "WARN", "INFO")},
            "findings": findings,
            "legacy_check": {"command": gate["legacy_command"], "status": "not run by v2",
                             "note": "the gate passes only when this command also exits 0 (D-10)"}}
