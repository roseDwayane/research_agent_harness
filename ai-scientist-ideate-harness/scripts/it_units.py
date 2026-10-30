"""The Unit registry: scripts/ideate_units.json is the single source; references/units.md is rendered from it.

  ideate_tools.py units render     rebuild references/units.md
  ideate_tools.py units check      every card complete (the twelve conditions + code / server /
                                   tests), every pointer resolves (rules anchor, code function, test file, counter-example
                                   fixture), every check code in a card exists in the code, units.md up to date

It checks the cards and their pointers, not a run: no ledger records runs yet. The twelve conditions are defined in
docs/decisions/PLAN_ideate_armor.md §2.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from it_common import read_json, write_text

SKILL = Path(__file__).resolve().parent.parent
REGISTRY = SKILL / "scripts" / "ideate_units.json"
UNITS_MD = SKILL / "references" / "units.md"

# card field -> the condition it serves
FIELDS = {
    1: ["id", "purpose", "rules", "instance", "when"],
    2: ["reads", "requires", "forbidden", "frozen"],
    3: ["owns", "revises", "revised_by", "schemas"],
    4: ["actor", "network", "budget", "scratch"],
    5: ["done_when"],
    6: ["judgement_fields", "computed_by"],
    7: ["failures", "degraded", "hard_stop"],
    8: ["resume"],
    9: ["tests"],
    10: ["counts", "status_line", "audit"],
    11: ["decisions", "provenance"],
    12: ["override", "invalidates", "fork_entry"],
}
EXTRA = ["block", "code", "server", "achieved"]         # achieved = what is actually met, condition by condition
# A condition that depends on a shared armour part cannot be met while that part does not exist (registry
# `infrastructure`). Condition 9 needs replay only for a Unit that touches the network.
NEEDS = {2: ["ledger"], 3: ["ledger"], 4: ["ledger"], 8: ["ledger"], 9: ["interrupt_harness"], 10: ["ledger", "status_view"],
         11: ["trace"], 12: ["ledger", "overrides"]}
LEVELS = [("L1 boundary", [1, 2, 3, 4]), ("L2 decidable", [5, 6, 10]), ("L3 resilient", [7, 8, 9]),
          ("L4 complete", [11, 12])]
NAMES = {1: "identity", 2: "input contract", 3: "output contract", 4: "actor and side effects", 5: "done when",
         6: "judgement vs mechanics", 7: "failure and degradation", 8: "resumable", 9: "testable", 10: "observable",
         11: "traceable", 12: "intervenable"}


def load() -> dict:
    return read_json(REGISTRY)


APPEND = re.compile(r"""open\([^)]*,\s*["']a["']""")


def _test_exists(ref: str) -> bool:
    """`tests/search/test_harness.py::TestInterrupt.test_interrupt_a3` -> the file holds that test function."""
    path, _, name = str(ref).partition("::")
    f = SKILL / "scripts" / path
    fn = name.rsplit(".", 1)[-1]
    return bool(name) and f.exists() and re.search(rf"^\s+def {re.escape(fn)}\(", f.read_text(), re.M) is not None


def machine(card: dict, reg: dict | None = None) -> dict:
    """Per condition 2-4 and 7-12: (met, why not) judged from things a tool can verify - the card's machine-readable
    fields, the shared parts that exist, the code, the tests. Conditions 1, 5 and 6 are judged by check() itself."""
    reg = reg or load()
    infra = reg.get("infrastructure") or {}
    io = card.get("io") or {}
    t = card.get("tests") or {}
    mods = sorted({str(r).partition(":")[0] for r in card.get("code") or [] if str(r).startswith("it_")})
    src = {m: (SKILL / "scripts" / m).read_text() for m in mods if (SKILL / "scripts" / m).exists()}
    net = card.get("network") not in (None, "", "none")
    cid = card.get("id")
    ledger_src = (SKILL / "scripts" / "it_ledger.py").read_text() if (SKILL / "scripts" / "it_ledger.py").exists() else ""
    trace_src = (SKILL / "scripts" / "it_trace.py").read_text() if (SKILL / "scripts" / "it_trace.py").exists() else ""
    caveat_units = {}
    if ledger_src:
        for table in re.findall(r"CAVEAT_UNITS = \{(.*?)\}", ledger_src, re.S):      # the search's and the fusion's
            caveat_units.update(re.findall(r'"([a-z][a-z-]+)": "([A-Z]\d[\w.]*)"', table))
    named = set(re.findall(r"caveat `?([a-z][a-z-]+)`?", " ".join(card.get("degraded") or [])))

    def need(*parts):
        miss = [x for x in parts if not infra.get(x)]
        return f"needs {', '.join(miss)}" if miss else ""
    out = {}
    out[2] = need("ledger") or ("" if isinstance(io.get("reads"), list) and card.get("forbidden") else "no `io.reads` / `forbidden`")
    out[3] = need("ledger") or ("no `io.owns`" if not io.get("owns") else
                                next((f"{m} appends to a file (not atomic)" for m, x in src.items() if APPEND.search(x)), ""))
    out[4] = need("ledger") or ("" if card.get("actor") and card.get("network") and card.get("budget") and
                                isinstance(io.get("scratch"), list) else "actor / network / budget / `io.scratch` missing")
    out[7] = need("status_view") or ("" if (card.get("degraded") or card.get("hard_stop")) else "no degraded path or stop declared") \
        or next((f"caveat `{c}` is not collected by the caveats summary" for c in sorted(named) if caveat_units.get(c) != cid), "")
    out[8] = need("ledger", "interrupt_harness") or ("" if _test_exists(t.get("interrupt")) else "no interrupt test named in `tests.interrupt`")
    out[9] = need("interrupt_harness", *(["replay"] if net else [])) or \
        ("" if all((SKILL / "scripts" / f).exists() for f in t.get("files") or ["-"]) and _test_exists(t.get("interrupt"))
         and (not net or _test_exists(t.get("replay"))) else "fixture, interrupt test or (networked) replay test missing")
    out[10] = need("ledger", "status_view") or ("" if card.get("counts") and card.get("status_line")
                                                 and f'"{cid}": lambda' in ledger_src else "no counts / status line in the ledger")
    out[11] = need("trace") or ("" if card.get("decisions") and card.get("provenance") and f'"{cid}"' in trace_src
                                else "`trace` does not report this Unit")
    out[12] = need("ledger", "overrides") or ("" if card.get("override") and card.get("invalidates") and
                                              isinstance(card.get("fork_entry"), bool) and (card["fork_entry"] or card.get("fork_reason"))
                                              else "override / invalidates / fork entry undeclared")
    return {k: (v == "", v) for k, v in out.items()}


def achieved_level(card: dict) -> str:
    """The highest level whose conditions are all `yes` in the card's `achieved` block - after `check()` has refused
    every `yes` the code or the infrastructure does not back."""
    ach = card.get("achieved") or {}
    level = "L0"
    for name, conds in LEVELS:
        if all((ach.get(str(c)) or {}).get("status") == "yes" for c in conds):
            level = name
        else:
            break
    met = sum(1 for c in FIELDS if (ach.get(str(c)) or {}).get("status") == "yes")
    return f"{level} ({met}/12 conditions met)"


def emitted_codes(module: str) -> dict:
    f = SKILL / "scripts" / module
    if not f.exists():
        return {}
    out = {}
    for lvl, code in re.findall(r'F\("(ERROR|WARN|SKIP)", "([A-Z]\d\d)"', f.read_text()):
        out.setdefault(code, set()).add(lvl)
    return out


def declared_level(card: dict) -> str:
    """The highest maturity level whose conditions all have their fields present (declared, not enforced)."""
    level = "L0 declared"
    for name, conds in LEVELS:
        if all(card.get(f) not in (None, "") for c in conds for f in FIELDS[c]):
            level = name
        else:
            break
    return level


def _anchor_exists(rules: str) -> bool:
    path, _, anchor = str(rules).partition("#")
    f = SKILL / path
    if not f.exists():
        return False
    return not anchor or re.search(rf'<a id="{re.escape(anchor)}"></a>|\{{#{re.escape(anchor)}\}}', f.read_text()) is not None


def _code_exists(ref: str) -> bool:
    mod, _, fn = str(ref).partition(":")
    f = SKILL / "scripts" / mod
    return f.exists() and (not fn or re.search(rf"^(async )?def {re.escape(fn)}\(", f.read_text(), re.M) is not None)


def check() -> list[str]:
    problems = []
    reg = load()
    cards = reg.get("units") or []
    ids = [c.get("id") for c in cards]
    for d in {i for i in ids if ids.count(i) > 1}:
        problems.append(f"unit id {d} appears twice")
    infra = reg.get("infrastructure") or {}
    by_id = {c.get("id"): c for c in cards}
    # every check a module emits (ERROR or WARN) has a counter-example in some card's fixtures
    modules = {str(r).partition(":")[0] for c in cards for r in c.get("code") or [] if str(r).startswith("it_")}
    code_text = "".join((SKILL / "scripts" / m).read_text() for m in sorted(modules) if (SKILL / "scripts" / m).exists())
    fixture_expect = set()
    for c in cards:
        fd = SKILL / "scripts" / str((c.get("tests") or {}).get("fixtures") or "") / "neg"
        for f in fd.glob("*.json") if fd.is_dir() else []:
            fixture_expect.add(json.loads(f.read_text()).get("expect"))
    uncovered = sorted(code for m in modules for code, lv in emitted_codes(m).items()
                       if lv - {"SKIP"} and code not in fixture_expect)
    for code in uncovered:
        problems.append(f"check code {code} is emitted but no counter-example expects it")
    # a tool that writes another Unit's field must be declared in that owner's `revised_by`
    try:
        import it_frame
        revisions, owners = it_frame.REVISIONS, it_frame.OWNERS
    except Exception as e:  # noqa: BLE001
        revisions, owners = [], {}
        problems.append(f"it_frame could not be imported: {e}")
    for r in revisions:
        owner = by_id.get(r["owner"]) or {}
        if not any(x.get("by") == r["by"] and str(x.get("via", "")).endswith(":" + r["tool"]) and x.get("field") == r["field"]
                   for x in owner.get("revised_by") or []):
            problems.append(f"{r['tool']} lets {r['by']} write {r['owner']}.{r['field']} but {r['owner']}'s card does not "
                            "declare it under revised_by")
    for unit, keys in owners.items():
        card = by_id.get(unit)
        if card is None:
            continue
        owned = " ".join(card.get("owns") or [])
        for k in keys:
            if f"step0.{k}" not in owned:
                problems.append(f"{unit} writes step0.{k} (it_frame.OWNERS) but its card does not list it under owns")
    for c in cards:
        cid = c.get("id")
        for cond, fields in FIELDS.items():
            for f in fields:
                if f not in c:
                    problems.append(f"{cid}: missing `{f}` (condition {cond}, {NAMES[cond]})")
        for f in EXTRA:
            if f not in c:
                problems.append(f"{cid}: missing `{f}`")
        if c.get("rules") and not _anchor_exists(c["rules"]):
            problems.append(f"{cid}: rules pointer {c['rules']} does not resolve")
        for ref in c.get("code") or []:
            if not _code_exists(ref):
                problems.append(f"{cid}: code pointer {ref} does not resolve")
        t = c.get("tests") or {}
        for path in t.get("files") or []:
            if not (SKILL / "scripts" / path).exists():
                problems.append(f"{cid}: test file {path} not found")
        mach = machine(c, reg)
        for cond, a in (c.get("achieved") or {}).items():
            if a.get("status") not in ("yes", "partial", "no") or not str(a.get("evidence", "")).strip():
                problems.append(f"{cid}: achieved[{cond}] needs status yes / partial / no and evidence")
            if a.get("status") == "yes" and int(cond) in mach and not mach[int(cond)][0]:
                problems.append(f"{cid}: condition {cond} claims `yes` but {mach[int(cond)][1]}")
            if a.get("status") == "yes":
                need = list(NEEDS.get(int(cond), []))
                if int(cond) == 9 and c.get("network") not in (None, "none"):
                    need.append("replay")
                missing = [n for n in need if not infra.get(n)]
                if missing:
                    problems.append(f"{cid}: condition {cond} claims `yes` but needs {missing}, which is not built")
                if int(cond) == 5 and uncovered:
                    problems.append(f"{cid}: condition 5 claims `yes` while check codes lack counter-examples")
                if int(cond) == 1 and not _anchor_exists(c.get("rules", "")):
                    problems.append(f"{cid}: condition 1 claims `yes` but its rules pointer does not resolve")
        missing_c = [k for k in map(str, FIELDS) if k not in (c.get("achieved") or {})]
        if missing_c:
            problems.append(f"{cid}: achieved has no entry for conditions {missing_c}")
        fixdir = SKILL / "scripts" / str(t.get("fixtures") or "")
        for dw in c.get("done_when") or []:
            for code in dw.get("codes") or []:
                if f'"{code}"' not in code_text:
                    problems.append(f"{cid}: check code {code} is not emitted by the code")
            nf = dw.get("negative_fixture")
            if nf and not (fixdir / "neg" / f"{nf}.json").exists():
                problems.append(f"{cid}: counter-example {nf} not found under {t.get('fixtures')}/neg/")
            if not nf:
                problems.append(f"{cid}: done_when check {dw.get('check')!r} has no counter-example")
    if UNITS_MD.exists() and UNITS_MD.read_text() != render_md(reg):
        problems.append("references/units.md is out of date: run `ideate_tools.py units render`")
    elif not UNITS_MD.exists():
        problems.append("references/units.md does not exist: run `ideate_tools.py units render`")
    return problems


def _val(v) -> str:
    if isinstance(v, list):
        return "<br>".join(_val(x) for x in v) if v else "—"
    if isinstance(v, dict):
        return "<br>".join(f"**{k}**: {_val(x)}" for k, x in v.items()) if v else "—"
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return str(v).replace("|", "/") if str(v) else "—"


def _numbers() -> list[str]:
    """The numbers the checks enforce, quoted from the code so that no document retypes them."""
    import it_frame as F
    return ["| Rule | Value (from the code) |", "|---|---|",
            f"| flat query length (content words) | {F.FLAT_WORDS[0]}–{F.FLAT_WORDS[1]} |",
            f"| synonyms per search axis | quick ≥ {F.MIN_TERMS['quick']}, standard / deep ≥ {F.MIN_TERMS['standard']} "
            f"(warning above {F.MAX_TERMS_WARN}) |",
            "| search axes per protocol | 2–4 |",
            "| query variants by depth | " + "; ".join(f"{d}: {', '.join(v)}" for d, v in F.DEPTH_STRATEGIES.items()) + " |",
            "| axis kinds required by depth | " + "; ".join(f"{d}: {', '.join(v)}" for d, v in F.DEPTH_AXIS_KINDS.items()) + " |",
            f"| protocol evaluation rounds | at most {F.MAX_EVAL_ROUNDS} (one forced revision) |",
            "| frameworks | " + ", ".join(f"{k} ({', '.join(v[0])})" for k, v in F.FRAMEWORKS.items()) + ", custom |",
            "| sources | " + ", ".join(F.KNOWN_SOURCES) + " |",
            *_numbers_a2()]


def _numbers_a2() -> list[str]:
    import it_search as S
    return [f"| records per source per query (A2.s) | {S.LIMIT} (dense D1: {S.DENSE_LIMIT}) |",
            "| form each source gets (A2.s) | " + ", ".join(f"{k}: {v}" for k, v in S.SOURCE_FORM.items()) + " |",
            "| routing by variant (A2.s) | " + "; ".join(f"{k}: {', '.join(v)}" for k, v in S.ROUTES.items()) + "; others: every chosen source |",
            f"| on-anchor share below which a query cannot be ok (A2.c) | {S.ANCHOR_MIN:.0%} |",
            f"| relevance rounds (A2.c) | at most {S.MAX_ROUNDS} (two re-plan rounds) |",
            f"| saturation (A2.c) | a re-plan round adding < {S.SATURATED:.0%} new papers ends re-planning |",
            *_numbers_a3()]


def _numbers_a3() -> list[str]:
    import it_screen as X
    return [f"| composite (A3) | relevance × {X.WEIGHTS['relevance']:.2f} + quality × {X.WEIGHTS['quality']:.2f} + impact × "
            f"{X.WEIGHTS['recency_impact']:.2f}; included at >= {X.INCLUDE_AT:.2f} |",
            f"| impact (A3.b) | {X.W_CIT} × field-normalised citation percentile + {X.W_LOCAL} × in-collection citation percentile; "
            f"venue percentile as a prior below {X.COLD_YEARS} years (half), at {X.COLD_YEARS} (a quarter); 1 + 4 × value |",
            "| gate types (A3.g) | " + ", ".join(sorted(X.GATE_TYPES)) + " |",
            f"| batch size (A3) | {X.BATCH_SIZE} papers per subagent |",
            f"| bulk rules (A3) | relevance <= 2, only papers with no anchor term and sem_pct < {X.LOW_SEM_PCT} |"]


def render_md(reg: dict | None = None) -> str:
    reg = reg or load()
    cards = reg.get("units") or []
    L = ["<!-- generated by `ideate_tools.py units render` from scripts/ideate_units.json - do not edit -->",
         "# Units of ai-scientist-ideate", "",
         "A Unit = one step plus its armour: it runs from frozen inputs alone, a tool decides whether it is done, and a",
         "person can handle it without reading the other Units (docs/decisions/PLAN_ideate_armor.md §2). This file is",
         "rendered from `scripts/ideate_units.json`; the rules themselves live where each card's `rules` points.", "",
         "Blocks: **search** (A1–A5) · **fulltext** (A6.d, A6.c — references/scholar-pipeline.md §2) · **fusion** (A7, B1,",
         "B2, B3, B3.5 — once per topic; references/fusion/) · planning (B4–B6 — once per idea). The planning block runs",
         "as described in SKILL.md.", "",
         "**Fields declared** = every card field of a level's conditions is filled in. **Achieved** = the level whose",
         "conditions are all met, from each card's `achieved` block; `units check` refuses a `yes` that the",
         "code or the shared armour does not back (a counter-example missing, or a ledger / replay / trace / override",
         "entry that is not built). Built so far: " + (", ".join(k for k, v in (reg.get("infrastructure") or {}).items()
                                                          if v is True) or "none of the shared parts") + ".", "",
         "| Unit | Block | Purpose | Actor | Network | Rules | Fields declared | Achieved |", "|---|---|---|---|---|---|---|---|"]
    for c in cards:
        L.append(f"| {c['id']} | {c.get('block')} | {c.get('purpose')} | {c.get('actor')} | {c.get('network')} | "
                 f"[{c.get('rules')}]({str(c.get('rules')).removeprefix('references/')}) | {declared_level(c)} | "
                 f"{achieved_level(c)} |")
    L += ["", "## Numbers the checks enforce", ""] + _numbers()
    for c in cards:
        L += ["", f"## {c['id']} — {c.get('purpose')}", "", "| # | Condition | Met | Card |", "|---|---|---|---|"]
        for cond, fields in FIELDS.items():
            a = (c.get("achieved") or {}).get(str(cond)) or {}
            L.append(f"| {cond} | {NAMES[cond]} | **{a.get('status', '?')}** — {_val(a.get('evidence', ''))} | "
                     + "<br>".join(f"**{f}**: {_val(c.get(f))}" for f in fields) + " |")
        L.append(f"| — | code / server | **code**: {_val(c.get('code'))}<br>**server**: {_val(c.get('server'))} |")
    return "\n".join(L) + "\n"


def cmd_render(a):
    write_text(UNITS_MD, render_md())
    print(UNITS_MD)


def cmd_check(a):
    problems = check()
    for p in problems:
        print("  - " + p)
    reg = load()
    for c in reg.get("units") or []:
        print(f"  {c['id']:<5} fields: {declared_level(c):<13}  achieved: {achieved_level(c)}")
    print("OK" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


def add_parsers(sub) -> None:
    up = sub.add_parser("units", help="the Unit registry (scripts/ideate_units.json -> references/units.md)")
    us = up.add_subparsers(dest="units_cmd", required=True)
    sp = us.add_parser("render")
    sp.set_defaults(fn=cmd_render)
    sp = us.add_parser("check")
    sp.set_defaults(fn=cmd_check)
