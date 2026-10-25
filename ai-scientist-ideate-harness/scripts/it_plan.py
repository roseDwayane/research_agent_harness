"""The planning block - one idea from one question, in five ordered steps (rules: references/planning/; decision record
docs/decisions/PLAN_ideate_planning.md).

  P1  Gap2Hypo        the gap's move and primary collision -> the primary hypothesis's form, its direction, its rivals
  P2  design          experiments, measures, thresholds, controls, power (research-cycle §4, unchanged)
  P3  decision tree   nodes = an experiment's reading, branches = thresholds, leaves = what we learn + what paper it is
  P4  attack          targets x weakness x weapon (E-id) x landing leaf x if-miss x concession -> Related Work
  P5  packaging       Title, Short Hypothesis, Abstract (each sentence with its move and sources), per-leaf titles

  ideate_tools.py plan-status <gen_dir>      which step's files exist (the steps built so far are listed in PLAN §11)
  ideate_tools.py hypo-prefill <gen_dir>     P1: the primary collision, the default form of the hypothesis, the rival
                                             accounts as rival candidates, the magnitudes -> gen_k/p1_prefill.json
  ideate_tools.py tree-prefill <gen_dir>     P3: skeleton (one node per deciding experiment, licensing order, the
                                             branch kinds, each branch's prior floor) -> gen_k/decision_tree.draft.json
  ideate_tools.py tree-render <gen_dir> [--project]   decision_tree.md; --project writes the leaves' conclusions into
                                             claims[].outcomes and records based_on
  ideate_tools.py tree-check <gen_dir>       P3: T01-T13 (T09 = the decision gate)
  ideate_tools.py attack-prefill <gen_dir>   P4: skeleton from question.json targets, the primary test as weapon, leaves
                                             to land on and to miss into, agree collisions to concede -> attack_plan.draft.json
  ideate_tools.py attack-render <gen_dir>    related_work.md (the Related Work field), targets_hit into the tree, based_on
  ideate_tools.py attack-check <gen_dir> [--idea idea_draft.json]   P4: R01-R12
  ideate_tools.py pack-prefill <gen_dir>     P5: skeleton (the five abstract moves with candidate sources, the leaves
                                             to package) -> packaging.draft.json
  ideate_tools.py pack-render <gen_dir>      Title, Short Hypothesis, Abstract and Related Work into idea_draft.json
  ideate_tools.py pack-check <gen_dir> [--idea idea_draft.json]   P5: K01-K10
  ideate_tools.py hypo-check <gen_dir>       P1: C25-C27 alone, before P2 exists (argument-check runs them too, on a
                                             generation that has gen_k/question.json, and says when they found nothing)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from it_common import die, now_iso, read_json, write_json

STEPS = (
    ("P0", "question.json", "the question taken from the fusion block (question-take)"),
    ("P1", "step8_hypothesis.md", "Gap2Hypo: RQ, hypotheses, rival explanations"),
    ("P2", "argument.json", "design: experiments, controls, power (and P1's claims)"),
    ("P3", "decision_tree.json", "decision tree"),
    ("P4", "attack_plan.json", "attack-type Related Work"),
    ("P5", "packaging.json", "packaging: title, short hypothesis, abstract"),
)


def status(gd: Path) -> list[dict]:
    gd = Path(gd)
    if not gd.is_dir():
        die(f"{gd} is not a generation folder", 2)
    out = []
    for step, name, what in STEPS:
        p = gd / name
        out.append({"step": step, "file": name, "exists": p.exists(), "what": what})
    qj = gd / "question.json"
    if qj.exists():
        q = read_json(qj)
        out[0]["handover"] = bool(q.get("handover"))
    return out


def cmd_status(a):
    rows = status(Path(a.gen_dir))
    if a.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    for r in rows:
        extra = "" if "handover" not in r else (" (with section 9 hand-over)" if r["handover"] else
                                                " (no section 9: targets, rivals, magnitudes missing)")
        print(f"  {r['step']}  {'ok ' if r['exists'] else '-- '} {r['file']:<22} {r['what']}{extra}")




# ================================================================================================ P1 Gap2Hypo
# The default form of the primary hypothesis, from the result of the question's primary collision (PLAN §1.4,
# references/planning/P1-gap2hypo.md). `modes` are the argument modes the form allows for the primary claim.
FORMS = {
    "moderation":      {"modes": ("test",), "says": "the varied axis X explains the two sides' difference: on the same data, "
                                                    "changing only X moves the effect by at least the SESOI"},
    "adjudication":    {"modes": ("test",), "says": "under the shared conditions, side A's result (or side B's) is reproduced"},
    "interaction":     {"modes": ("test",), "says": "the effect's slope along the condition axis is not zero"},
    "premise-test":    {"modes": ("test", "equivalence"),
                        "says": "premise P fails under condition C (the effect changes by at least the SESOI) - or, as "
                                "equivalence, P holds within a stated margin, with a positive control"},
    "share":           {"modes": ("estimate", "test"), "says": "how much of conclusion Z is explained by the violation of P "
                                                                "(an estimate, tested against 0 and against all of it)"},
    "evaluation":      {"modes": ("test",), "says": "judged by the paper's own criterion K, method M does not meet it"},
    "increment":       {"modes": ("test",), "says": "the next step improves on the current best by at least the SESOI "
                                                   "(a comparator is required)"},
    "non-inferiority": {"modes": ("equivalence", "test"), "says": "the convention still holds under this machine's "
                                                                 "conditions (non-inferiority / equivalence)"},
    "estimate":        {"modes": ("estimate",), "says": "how large / how reliable - only with study: descriptive (C21)"},
}
PREMISE_RESULTS = {"untested-shared", "assumption-at-stake"}


def default_form(collision: dict | None) -> str:
    """The form §1.4 gives a primary collision; `estimate` when the question rests on not-done units only."""
    if not collision:
        return "estimate"
    r = collision.get("result")
    if r == "conflict":
        return "moderation" if [a for a in collision.get("axes_differ") or [] if a != "none"] else "adjudication"
    return {"boundary": "interaction", "untested-shared": "premise-test", "assumption-at-stake": "premise-test",
            "assumption-challenged": "share", "criterion-unmet": "evaluation", "extends": "increment",
            "convention-vs-lens": "non-inferiority", "empty-cell": "estimate"}.get(r, "estimate")


def _ids(v) -> list:
    return [v] if isinstance(v, str) else [x for x in (v or []) if isinstance(x, str)]


def context(gd: Path) -> dict | None:
    """What P1's checks read besides argument.json: gen_k/question.json, its gap in step7_gaps.json, and the current
    collision records of the question. None for a generation that did not take a question from the fusion block."""
    gd = Path(gd)
    qp = gd / "question.json"
    if not qp.exists():
        return None
    try:
        q = read_json(qp)
    except Exception as e:
        die(f"{qp} does not parse ({e})", 2)
    rd = gd.parent
    gaps = read_json(rd / "step7_gaps.json") if (rd / "step7_gaps.json").exists() else {}
    gap = next((g for g in gaps.get("gaps") or [] if g.get("id") == q.get("gap")), {})
    cur = {}
    if (rd / "knowledge" / "collisions.jsonl").exists():
        import it_collide
        cur = {r["collision_id"]: r for r in it_collide.current(it_collide.log(rd))}
    cols = _ids(q.get("collisions")) or _ids(gap.get("collisions"))
    return {"question": q, "gap": gap, "collisions": {c: cur[c] for c in set(cols) | set(gap.get("collisions") or [])
                                                      if c in cur},
            "primary_collision": cols[0] if cols else None}


def p1_findings(arg: dict, P: dict) -> list[dict]:
    """C25 derivation, C26 rival accounts -> rivals, C27 magnitudes -> direction and power. Findings in
    argument-check's shape: {level, check, claim, text}."""
    out = []
    add = lambda level, check, text, claim=None: out.append({"level": level, "check": check, "claim": claim, "text": text})
    q, gap, cols = P["question"], P["gap"], P["collisions"]
    claims = [c for c in arg.get("claims") or [] if isinstance(c, dict)]
    prim = next((c for c in claims if c.get("primary") is True), None)
    if not prim:
        return out                                        # C1 reports the missing primary claim
    cid = prim.get("id")
    # ---- C25 the primary hypothesis is derived from the gap
    d = prim.get("derivation")
    if not isinstance(d, dict):
        add("ERROR", "C25", "the primary claim has no `derivation` {gap, move, primary_collision, form, deviation}: "
                            "derive its form from the question's primary collision (hypo-prefill; P1-gap2hypo.md)", cid)
    else:
        if d.get("gap") != q.get("gap") or d.get("move") != q.get("move"):
            add("ERROR", "C25", f"derivation gap / move {d.get('gap')!r} / {d.get('move')!r} are not the question's "
                                f"({q.get('gap')!r} / {q.get('move')!r})", cid)
        pc = d.get("primary_collision")
        qcols = _ids(q.get("collisions"))
        if pc is not None and pc not in qcols:
            add("ERROR", "C25", f"derivation.primary_collision {pc!r} is not one of the question's collisions {qcols}", cid)
        elif pc is None and qcols:
            add("ERROR", "C25", f"derivation.primary_collision is null, but the question rests on {qcols}", cid)
        elif pc and qcols and pc != qcols[0]:
            add("WARN", "C25", f"derivation.primary_collision is {pc}, not the question's first collision {qcols[0]}: say "
                               "why in `deviation`", cid)
        form = d.get("form")
        if form not in FORMS:
            add("ERROR", "C25", f"derivation.form {form!r}; allowed: {' | '.join(FORMS)}", cid)
        else:
            want = default_form(cols.get(pc)) if pc else "estimate"
            if form != want and not str(d.get("deviation") or "").strip():
                add("ERROR", "C25", f"form {form!r} departs from the default {want!r} for {pc or 'a not-done gap'} "
                                    f"({(cols.get(pc) or {}).get('result', 'not done')}): write the reason in "
                                    "derivation.deviation, or use the default form", cid)
            if prim.get("mode") not in FORMS[form]["modes"]:
                add("ERROR", "C25", f"form {form!r} takes mode {' | '.join(FORMS[form]['modes'])}, not "
                                    f"{prim.get('mode')!r}", cid)
            if form == "increment" and not prim.get("comparator"):
                add("ERROR", "C25", "form increment: the falsifier is the increment over the current best - name it in "
                                    "`comparator`", cid)
    # ---- C26 every rival account of the field becomes a rival, or is set aside with a reason
    rivals = [r for r in prim.get("rivals") or [] if isinstance(r, dict)]
    ids = [r.get("id") for r in rivals]
    if q.get("handover") or q.get("rival_accounts"):
        bad = [i for i in ids if not (isinstance(i, str) and re.fullmatch(r"R\d+", i))]
        if bad or len(set(ids)) != len(ids):
            add("ERROR", "C26", f"every rival of the primary claim carries an id R1, R2, … once (the decision tree names "
                                f"them): {ids}", cid)
    accounts = {a.get("id"): a for a in q.get("rival_accounts") or [] if isinstance(a, dict)}
    if accounts:
        used = {r.get("account") for r in rivals}
        aside = {x.get("account"): x for x in ((d or {}).get("set_aside") or []) if isinstance(x, dict)}
        unknown = sorted(a for a in used | set(aside) if a and a not in accounts)
        if unknown:
            add("ERROR", "C26", f"rival / set_aside accounts {unknown} are not in question.json rival_accounts", cid)
        for aid in sorted(accounts):
            if aid in used:
                continue
            why = str((aside.get(aid) or {}).get("why") or "").strip()
            if not why:
                add("ERROR", "C26", f"rival account {aid} ({str(accounts[aid].get('account'))[:90]}) is neither a rival "
                                    "(`rivals[].account`) nor in derivation.set_aside with a `why`", cid)
        mains = [r for r in rivals if r.get("main") is True]
        recorded = [a for a in accounts.values() if _ids(a.get("basis"))]
        if mains and recorded and not mains[0].get("account"):
            add("WARN", "C26", "the main rival is none of the field's own accounts: say in the round-2 critique why a "
                               "reader of the target venue would reach for it first", cid)
        elif mains and mains[0].get("account") in accounts and not _ids(accounts[mains[0]["account"]].get("basis")):
            add("WARN", "C26", f"the main rival carries {mains[0]['account']}, an account no record holds (the study's own "
                               "conjecture): say in the round-2 critique why a reader would reach for it first", cid)
    # ---- C27 the field's numbers reach the direction and the power
    M = q.get("magnitudes")
    rows = [m for m in M if isinstance(m, dict)] if isinstance(M, list) else []
    same = [m["exp_id"] for m in rows if m.get("relation", "same") == "same" and m.get("exp_id")]
    if rows:
        ed = prim.get("expected_direction") if isinstance(prim.get("expected_direction"), dict) else {}
        if prim.get("mode") == "test" and str(ed.get("basis") or "").startswith("unknown") and same:
            add("ERROR", "C27", f"expected_direction is 'unknown:' although the question hands over reported numbers "
                                f"{same}: say what they predict (settled / contested), or why they do not bear on it", cid)
        pw = prim.get("power") if isinstance(prim.get("power"), dict) else {}
        if pw and re.match(r"^\(\s*(TBD|P\d|write|todo)", str(pw.get("literature_effect") or "").strip(), re.I):
            add("ERROR" if same else "WARN", "C27",
                f"power.literature_effect is (TBD) although the question hands over "
                f"{'reported numbers ' + str(same) if same else 'neighbouring numbers ' + str([m.get('exp_id') for m in rows])}"
                ": compare the smallest detectable effect with them", cid)
    return out


def _line_collisions(rd: Path) -> dict:
    """{Line id: its collisions} from knowledge/lines/*.md frontmatter"""
    out = {}
    ld = Path(rd) / "knowledge" / "lines"
    for f in sorted(ld.glob("*.md")) if ld.is_dir() else []:
        m = re.match(r"^---\n(.*?)\n---", f.read_text(encoding="utf-8"), re.S)
        fm = m.group(1) if m else ""
        lid = re.search(r"^id:\s*(\S+)", fm, re.M)
        cs = re.search(r"^collisions:\s*\[([^\]]*)\]", fm, re.M)
        out[lid.group(1) if lid else f.stem] = [x.strip().strip("'\"") for x in (cs.group(1).split(",") if cs else [])
                                                if x.strip()]
    return out


def prefill(gd: Path) -> dict:
    P = context(gd)
    if P is None:
        die(f"{gd}/question.json not found - P1 starts from a question taken from the fusion block (question-take)", 2)
    q = P["question"]
    pc = P["primary_collision"]
    col = P["collisions"].get(pc) if pc else None
    form = default_form(col)
    accounts = [a for a in q.get("rival_accounts") or [] if isinstance(a, dict)]
    on_axes = set((col or {}).get("axes_differ") or [])
    lines = _line_collisions(Path(gd).parent)

    def weight(a):
        """collisions behind the account, its Lines' collisions included"""
        cs = {b for b in _ids(a.get("basis")) if b.startswith("X")}
        for b in _ids(a.get("basis")):
            cs |= set(lines.get(b, []))
        return len(cs)

    def deferred(a):
        """an account the question itself hands to another question, or leaves out"""
        return bool(re.search(r"\bQ_\d{3}\b|\bleft to\b|\bdeferred\b", str(a.get("account") or ""), re.I))

    ranked = sorted(accounts, key=lambda a: (not _ids(a.get("basis")), deferred(a), -weight(a),
                                             a.get("axis") not in on_axes, a.get("id", "")))
    return {"at": now_iso(), "question": q.get("question"), "gap": q.get("gap"), "move": q.get("move"),
            "primary_collision": pc, "collision": {k: (col or {}).get(k) for k in ("result", "axes_differ", "reason")},
            "default_form": form, "modes": list(FORMS[form]["modes"]), "says": FORMS[form]["says"],
            "varies": q.get("varies") or [], "handover": bool(q.get("handover")),
            "rival_candidates": [{"suggested_id": f"R{i + 1}", "account": a.get("id"), "text": a.get("account"),
                                  "axis": a.get("axis"), "basis": a.get("basis"), "unrecorded": a.get("unrecorded")}
                                 for i, a in enumerate(ranked)],
            "suggested_main": ranked[0].get("id") if ranked and _ids(ranked[0].get("basis")) and not deferred(ranked[0])
            else None,
            "magnitudes": q.get("magnitudes"), "magnitude_absent": q.get("magnitude_absent"),
            "targets": [{"id": t.get("id"), "holds": t.get("holds"), "strength": t.get("strength")}
                        for t in q.get("targets") or [] if isinstance(t, dict)]}


def cmd_check(a):
    """P1 alone: C25-C27 on the argument as P1 left it (the rest of argument-check belongs after P2)."""
    gd = Path(a.gen_dir)
    P = context(gd)
    if P is None:
        die(f"{gd}/question.json not found - C25-C27 apply to a generation that took a question (question-take)", 2)
    if not (gd / "argument.json").exists():
        die(f"{gd}/argument.json not found", 2)
    fs = p1_findings(read_json(gd / "argument.json"), P)
    for f in fs:
        print(f"{f['level']} {f['check']}" + (f" {f['claim']}" if f["claim"] else "") + f": {f['text']}")
    errs = [f for f in fs if f["level"] == "ERROR"]
    print(f"hypo-check: C25-C27 {len(errs)} error(s), {len(fs) - len(errs)} warning(s)" + (" - REVISE" if errs else " - OK"))
    raise SystemExit(1 if errs else 0)


def cmd_prefill(a):
    gd = Path(a.gen_dir)
    out = prefill(gd)
    write_json(gd / "p1_prefill.json", out)
    print(f"hypo-prefill {gd.name}: {out['question']} on {out['gap']} ({out['move']}); primary collision "
          f"{out['primary_collision']} ({out['collision'].get('result')}, differs on {out['collision'].get('axes_differ')})")
    print(f"  default form: {out['default_form']} (mode {' | '.join(out['modes'])}) - {out['says']}")
    if not out["handover"]:
        print("  WARN the question has no section 9: no rival accounts, magnitudes or targets were handed over")
    for r in out["rival_candidates"]:
        main = "  <- suggested main" if r["account"] == out["suggested_main"] else ""
        print(f"  rival   {r['suggested_id']} = {r['account']} [{r['axis'] or '-'}] {str(r['text'])[:90]}{main}")
    m = out["magnitudes"]
    if isinstance(m, list):
        for x in m:
            print(f"  number  {x.get('exp_id')} ({x.get('relation', 'same')}): {str(x.get('value'))[:90]}")
    elif m:
        print(f"  number  {m}")
    if out["magnitude_absent"]:
        print(f"  absent  {out['magnitude_absent']}")
    print(f"  -> {gd.name}/p1_prefill.json; write step8 (RQ, hypotheses, rival explanations) and the claims' P1 fields "
          "(P1-gap2hypo.md), then P2")


# ================================================================================================ P3 decision tree
TREE = "decision_tree.json"
TREE_DRAFT = "decision_tree.draft.json"
TREE_SCHEMA = "ai-scientist-decision-tree/1"
PRIORS = ("unlikely", "possible", "likely")
WEIGHT = {"unlikely": 0.05, "possible": 0.3, "likely": 0.65}    # rough: unlikely ~5 %, so four checkpoints do not
                                                                # make half the tree weak by their count alone
PAPERS = ("finding", "informative-null", "boundary", "rival-finding", "descriptive", "methods-caveat", "not-publishable")
PUBLISHABLE = {"finding", "informative-null", "boundary", "rival-finding", "descriptive"}
WEAK_LEAF = {"methods-caveat", "not-publishable"}
# branch kinds by the experiment's role; `required` must each appear at least once (a kind may repeat with another `if`)
KINDS = {"tests": ("supported", "refuted", "uninformative"), "instrument": ("pass", "fail"),
         "control": ("pass", "fail"), "descriptive": ("precise", "imprecise")}
REQUIRED = {"tests": ("supported", "refuted"), "instrument": ("pass", "fail"), "control": ("pass", "fail"),
            "descriptive": ("precise", "imprecise")}
WEAK_KIND = {"uninformative", "imprecise"}
STATUS = {"supported", "refuted", "undecided", "estimated", "imprecise"}
BRANCH_STATUS = {"supported": "supported", "refuted": "refuted", "uninformative": "undecided",
                 "precise": "estimated", "imprecise": "imprecise"}
CONDITIONAL = re.compile(
    r"\bonly (when|if|for)\b|\bunless\b|\bprovided\b|\bas long as\b|\bon condition\b|\bif and only if\b|"
    r"\b(holds|returns|comes back|comes through|equals?|recovers|is recovered|reaches)\b[^.;]{0,60}\b(when|if)\b|"
    r"\bif it (stays|falls|is|remains)\b|\bnot read\b|\bis not predicted\b|\bcannot detect\b", re.I)
NUM = re.compile(r"(?<![\w.])[-+−]?\d+(?:\.\d+)?")
EID = re.compile(r"\bE\d+\b")


def _canon_argument(arg: dict) -> str:
    """argument.json without claims[].outcomes - the part the tree is built on (the outcomes are its projection)"""
    a = json.loads(json.dumps(arg))
    for c in a.get("claims") or []:
        if isinstance(c, dict):
            c.pop("outcomes", None)
    return json.dumps(a, sort_keys=True, ensure_ascii=False)


def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def based_on(gd: Path) -> dict:
    gd = Path(gd)
    out = {"argument.json": _sha(_canon_argument(read_json(gd / "argument.json")))}
    s8 = gd / "step8_hypothesis.md"
    if s8.exists():
        out["step8_hypothesis.md"] = _sha(s8.read_text(encoding="utf-8"))
    return out


def _claims(arg) -> dict:
    return {c.get("id"): c for c in arg.get("claims") or [] if isinstance(c, dict) and c.get("id")}


def _evidence_rule(c: dict, eid: str) -> str:
    rows = [e for e in c.get("evidence") or [] if isinstance(e, dict) and re.match(rf"{re.escape(eid)}\b", str(e.get("experiment", "")))]
    return " ".join(str(e.get("refuted_if") or "") for e in rows)


def _control_ids(c: dict) -> tuple[set, set]:
    ctl = c.get("controls") if isinstance(c.get("controls"), dict) else {}
    return set(EID.findall(str(ctl.get("positive") or ""))), set(EID.findall(str(ctl.get("negative") or "")))


def _threshold_sources(c: dict) -> set:
    """experiments the claim's decision rule takes a number from (a surrogate null, a calibration): named in its
    falsifier or refuted_if, other than the experiments its evidence rows are about"""
    ev = [e for e in c.get("evidence") or [] if isinstance(e, dict)]
    text = str(c.get("falsifier") or "") + " " + " ".join(str(e.get("refuted_if") or "") for e in ev)
    own = {m.group(0) for e in ev for m in [EID.match(str(e.get("experiment") or ""))] if m}
    return set(EID.findall(text)) - own


def prior_floor(arg: dict, node: dict, kind: str) -> tuple[str, str]:
    """The lowest prior a branch may carry, and why - computed from the argument, never chosen (PLAN §1.5)."""
    C = _claims(arg)
    floor, why = "unlikely", []
    rank = lambda p: PRIORS.index(p)

    def lift(f, w):
        nonlocal floor
        if rank(f) > rank(floor):
            floor = f
        why.append(w)
    for cid in node.get("claims") or []:
        c = C.get(cid) or {}
        pw = c.get("power") if isinstance(c.get("power"), dict) else {}
        if kind == "uninformative" and node.get("role") == "tests" and not node.get("external"):
            v = pw.get("verdict")
            lit = str(pw.get("literature_effect") or "").strip()
            if v == "underpowered":
                lift("likely", f"{cid} power underpowered")
            elif v == "marginal":
                lift("likely" if lit.startswith("(TBD)") or not lit else "possible",
                     f"{cid} power marginal" + (", literature effect (TBD)" if lit.startswith("(TBD)") or not lit else ""))
        if kind == "imprecise" and node.get("role") == "descriptive" and c.get("mode") == "estimate":
            pt = str(c.get("precision_target") or "").strip()
            if not pt or pt.startswith("(TBD)"):
                lift("possible", f"{cid} has no precision_target")
        if kind == "fail" and node.get("role") == "control":
            pos, _ = _control_ids(c)
            if node.get("experiment") in pos:
                pe = str((c.get("controls") or {}).get("positive_expected") or "")
                if CONDITIONAL.search(pe):
                    lift("possible", f"{cid} positive_expected holds only under a condition")
    return floor, "; ".join(why) or "no power or control finding"


def _branches(n: dict) -> list:
    return [b for b in n.get("branches") or [] if isinstance(b, dict)]


def _walk(nodes, leaves, root):
    """every root-to-leaf path as ([(node id, branch)], leaf id); cycles reported separately"""
    paths, cyc = [], []

    def walk(nid, path, trail):
        if nid in trail:
            cyc.append(nid)
            return
        for b in _branches(nodes.get(nid) or {}):
            step = path + [(nid, b)]
            if b.get("leaf") in leaves:
                paths.append((step, b["leaf"]))
            elif b.get("next") in nodes:
                walk(b["next"], step, trail | {nid})
    if root in nodes:
        walk(root, [], frozenset())
    return paths, cyc


def leaf_odds(tree: dict) -> dict:
    """{leaf id: rough probability} of the main tree, from the priors normalised within each node"""
    nodes = {n.get("id"): n for n in tree.get("nodes") or [] if isinstance(n, dict)}
    leaves = {l.get("id"): l for l in tree.get("leaves") or [] if isinstance(l, dict)}
    paths, _ = _walk(nodes, leaves, tree.get("root"))
    out = {}
    for p, lid in paths:
        pr = 1.0
        for nid, b in p:
            tot = sum(WEIGHT.get(x.get("prior"), 0) for x in _branches(nodes[nid])) or 1
            pr *= WEIGHT.get(b.get("prior"), 0) / tot
        out[lid] = out.get(lid, 0) + pr
    return out


def paper_mass(tree: dict, odds: dict | None = None) -> dict:
    """{paper type: rough probability} - the leaf odds summed by what the paper would be"""
    odds = leaf_odds(tree) if odds is None else odds
    papers = {l.get("id"): l.get("paper") for l in tree.get("leaves") or [] if isinstance(l, dict)}
    out = {}
    for lid, p in odds.items():
        out[papers.get(lid)] = out.get(papers.get(lid), 0) + p
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _mass_text(mass: dict) -> str:
    return ", ".join(f"{k} {v:.0%}" for k, v in mass.items())


def tree_findings(tree: dict, arg: dict, gd: Path | None = None) -> list[dict]:
    """T01-T13. Findings {level, code, text}."""
    out = []
    add = lambda level, code, text: out.append({"level": level, "code": code, "text": text})
    if tree.get("schema") != TREE_SCHEMA:
        add("ERROR", "T05", f"schema is {tree.get('schema')!r}, expected {TREE_SCHEMA!r}")
    C = _claims(arg)
    prim = next((c for c in C.values() if c.get("primary") is True), {})
    pid = prim.get("id")
    exps = {e.get("id"): e for e in arg.get("experiments") or [] if isinstance(e, dict)}
    nodes = {n.get("id"): n for n in tree.get("nodes") or [] if isinstance(n, dict)}
    leaves = {l.get("id"): l for l in tree.get("leaves") or [] if isinstance(l, dict)}
    if len(nodes) != len(tree.get("nodes") or []) or len(leaves) != len(tree.get("leaves") or []) or set(nodes) & set(leaves):
        add("ERROR", "T05", "node and leaf ids are unique (N…, L…)")
    # ---- T05 structure
    for nid, n in nodes.items():
        role = n.get("role")
        if role not in KINDS:
            add("ERROR", "T05", f"{nid}: role {role!r}; allowed: {' | '.join(KINDS)}")
            continue
        e = exps.get(n.get("experiment"))
        if not e:
            add("ERROR", "T05", f"{nid}: experiment {n.get('experiment')!r} is not in argument.json experiments[]")
        elif e.get("role") != role:
            add("ERROR", "T05", f"{nid}: role {role!r}, but {n.get('experiment')} has role {e.get('role')!r} in argument.json "
                                "(an external check keeps its own role; mark it `external: true`)")
        bad_claims = [c for c in n.get("claims") or [] if c not in C]
        if bad_claims or (not n.get("claims") and role != "instrument"):
            add("ERROR", "T05", f"{nid}: claims {n.get('claims')} must be claim ids of argument.json (only an instrument "
                                "may serve none)")
        if not str(n.get("reads") or "").strip():
            add("ERROR", "T05", f"{nid}: `reads` names the statistic and the threshold the node reads")
        kinds = [b.get("kind") for b in _branches(n)]
        ifs = [(b.get("kind"), str(b.get("if") or "").strip().lower()) for b in _branches(n)]
        if set(kinds) - set(KINDS[role]) or set(REQUIRED[role]) - set(kinds) or len(set(ifs)) != len(ifs):
            add("ERROR", "T05", f"{nid}: branch kinds {kinds}; a {role} node has {' | '.join(KINDS[role])} "
                                f"({' and '.join(REQUIRED[role])} at least once; a kind may repeat with another `if`)")
        for b in _branches(n):
            nx, lf = b.get("next"), b.get("leaf")
            if bool(nx) == bool(lf) or (nx and nx not in nodes) or (lf and lf not in leaves):
                add("ERROR", "T05", f"{nid} {b.get('kind')}: exactly one of `next` (a node) and `leaf` (a leaf) that exists")
            if not str(b.get("if") or "").strip():
                add("ERROR", "T05", f"{nid} {b.get('kind')}: `if` says the result that takes this branch")
            if b.get("prior") not in PRIORS:
                add("ERROR", "T09", f"{nid} {b.get('kind')}: prior {b.get('prior')!r}; allowed: {' | '.join(PRIORS)}")
    root = tree.get("root")
    if root not in nodes:
        add("ERROR", "T05", f"root {root!r} is not a node")
        return out
    subroots = _ids(tree.get("subtrees"))
    bad_sub = [s for s in subroots if s not in nodes]
    if bad_sub:
        add("ERROR", "T05", f"subtrees {bad_sub} are not nodes")
    paths, cyc = _walk(nodes, leaves, root)
    sub_paths = []
    for s in subroots:
        sp, sc = _walk(nodes, leaves, s)
        sub_paths += sp
        cyc += sc
    if cyc:
        add("ERROR", "T05", f"the tree has a cycle through {sorted(set(cyc))}")
        return out
    allp = paths + sub_paths
    seen_n = {nid for p, _ in allp for nid, _ in p}
    seen_l = {l for _, l in allp}
    if set(nodes) - seen_n or set(leaves) - seen_l:
        add("ERROR", "T05", f"unreachable: nodes {sorted(set(nodes) - seen_n)}, leaves {sorted(set(leaves) - seen_l)}")
    main_nodes = {nid for p, _ in paths for nid, _ in p}
    main_leaves = {l for _, l in paths}
    sub_nodes = {nid for p, _ in sub_paths for nid, _ in p}
    leak = sorted(x for x in sub_nodes if pid in (nodes[x].get("claims") or []))
    if leak:
        add("ERROR", "T05", f"subtree nodes {leak} serve the primary claim - its experiments belong to the main tree")
    # ---- T01 every primary experiment that decides something is in the tree
    in_tree = {nodes[x].get("experiment") for x in main_nodes}
    miss = sorted(eid for eid, e in exps.items() if e.get("role") in ("tests", "control", "instrument")
                  and pid in (e.get("claims") or []) and eid not in in_tree)
    if miss:
        add("ERROR", "T01", f"experiments {miss} of the primary claim {pid} are in no node of the main tree: every one "
                            "that decides something is read somewhere")
    # ---- T02 thresholds are the falsifier's (in the branches' own `if`, not only in `reads`)
    for nid, n in nodes.items():
        if n.get("role") != "tests":
            continue
        rule = " ".join(str((C.get(c) or {}).get("falsifier") or "") + " " + _evidence_rule(C.get(c) or {}, str(n.get("experiment")))
                        for c in n.get("claims") or [])
        want = set(NUM.findall(rule.replace("−", "-"))) - {str(i) for i in range(0, 10) if False}
        got = set(NUM.findall(" ".join(str(b.get("if") or "") for b in _branches(n)
                                        if b.get("kind") in ("supported", "refuted")).replace("−", "-")))
        if want and not want & got:
            add("ERROR", "T02", f"{nid}: its supported / refuted branches name none of the falsifier's or refuted_if's "
                                f"numbers {sorted(want)[:6]} - the tree reads the threshold the argument fixed")
    # ---- T03 uninformative is planned
    for nid, n in nodes.items():
        if n.get("role") == "tests" and "uninformative" not in [b.get("kind") for b in _branches(n)] \
                and not str(n.get("uninformative_closed") or "").strip():
            add("ERROR", "T03", f"{nid}: no `uninformative` branch (an interval that spans both readings, a failed "
                                "control, too few units) - add it, or say in `uninformative_closed` what closes it")
    # ---- T04 instruments, the positive control and controls that supply a threshold come before the test
    pos, _ = _control_ids(prim)
    feeds = _threshold_sources(prim)
    licensing = {nid for nid in main_nodes for n in [nodes[nid]]
                 if (n.get("role") == "instrument" and (not n.get("claims") or pid in n["claims"]))
                 or (n.get("role") == "control" and pid in (n.get("claims") or [])
                     and n.get("experiment") in pos | feeds)}
    for p, _ in paths:
        order = [nid for nid, _ in p]
        firsts = [i for i, nid in enumerate(order) if nodes[nid].get("role") == "tests" and pid in (nodes[nid].get("claims") or [])]
        if firsts:
            late = sorted(licensing - set(order[:firsts[0]]))
            if late:
                add("ERROR", "T04", f"on the path {' > '.join(order)}, {late} (instrument / positive control / control that "
                                    f"supplies a threshold of {pid}) do not come before the test they license")
                break
    # ---- T06 leaves
    for lid, l in leaves.items():
        if l.get("paper") not in PAPERS:
            add("ERROR", "T06", f"{lid}: paper {l.get('paper')!r}; allowed: {' | '.join(PAPERS)}")
        if not str(l.get("conclusion") or "").strip():
            add("ERROR", "T06", f"{lid}: `conclusion` - what we learn at this leaf, in one sentence")
        if l.get("answers_question") not in ("whole", "part", "none"):
            add("ERROR", "T06", f"{lid}: answers_question whole | part | none")
        st = l.get("claims") if isinstance(l.get("claims"), dict) else {}
        if pid and lid in main_leaves and pid not in st:
            add("ERROR", "T06", f"{lid}: says nothing about the primary claim {pid} (`claims`)")
        bad = {k: v for k, v in st.items() if k not in C or v not in STATUS}
        if bad:
            add("ERROR", "T06", f"{lid}: claim statuses {bad}; claims of argument.json, status in {sorted(STATUS)}")
    for p, lid in allp:
        st = leaves[lid].get("claims") if isinstance(leaves[lid].get("claims"), dict) else {}
        need = {}                     # claim -> (statuses the path allows, the node and kind that set them)
        for nid, b in p:
            n = nodes[nid]
            if n.get("external"):     # an external check bounds the scope, not the claim's status
                continue
            want = BRANCH_STATUS.get(b.get("kind"))
            for c in n.get("claims") or []:
                if want and (b.get("kind") not in ("precise", "imprecise") or (C.get(c) or {}).get("mode") == "estimate"):
                    need[c] = ({want} | ({"imprecise"} if want == "undecided" else set()), f"{nid} {b.get('kind')}")
            if b.get("kind") == "fail" and n.get("role") in ("control", "instrument"):
                # a control read after a test may void it: the claim keeps its status (with the caveat in the
                # conclusion) or becomes undecided
                for c in (n.get("claims") or list(need)):
                    if c in need:
                        need[c] = (need[c][0] | {"undecided"}, need[c][1] + f", then {nid} fail")
        for c, (allowed, where) in need.items():
            if c in st and st[c] not in allowed:
                add("ERROR", "T06", f"{lid}: {c} is {st[c]!r}, but the path takes {where} ({' or '.join(sorted(allowed))})")

    # ---- T07 a test that decides nothing
    def reach(b):
        if b.get("leaf"):
            return {leaves.get(b["leaf"], {}).get("conclusion", "").strip().lower()}
        return {leaves.get(l, {}).get("conclusion", "").strip().lower() for p, l in allp if any(x == b.get("next") for x, _ in p)}
    for nid, n in nodes.items():
        sup = set().union(*[reach(b) for b in _branches(n) if b.get("kind") == "supported"] or [set()])
        ref = set().union(*[reach(b) for b in _branches(n) if b.get("kind") == "refuted"] or [set()])
        if n.get("role") == "tests" and sup and sup == ref:
            add("WARN", "T07", f"{nid}: supported and refuted reach the same conclusion(s) - this experiment decides nothing")
    # ---- T08 the main rival dies in a publishable leaf, on a path through what rules it out
    mains = [r for r in prim.get("rivals") or [] if isinstance(r, dict) and r.get("main") is True]
    if mains and prim.get("mode") in ("test", "equivalence"):
        m = mains[0]
        names = {x for x in (m.get("id"), m.get("type")) if x}
        by = set(EID.findall(str(m.get("ruled_out_by") or "")))
        ok_leaf = False
        for p, lid in paths:
            l = leaves[lid]
            if set(_ids((l.get("rivals") or {}).get("killed"))) & names and l.get("paper") in PUBLISHABLE:
                if not by or by & {nodes[x].get("experiment") for x, _ in p}:
                    ok_leaf = True
        if not ok_leaf:
            add("ERROR", "T08", f"the main rival {m.get('id') or m.get('type')} is ruled out in no publishable leaf whose "
                                f"path passes through what rules it out ({', '.join(sorted(by)) or 'its ruled_out_by'})")
    # ---- T09 the decision gate
    anc = {}
    for p, _ in allp:
        for i, (nid, b) in enumerate(p):
            anc.setdefault(id(b), set()).update(x for x, _ in p[:i])
    for nid, n in nodes.items():
        for b in _branches(n):
            fl, why = prior_floor(arg, n, b.get("kind"))
            lifted = b.get("floor_lifted_by")
            if lifted:
                if lifted not in anc.get(id(b), set()):
                    add("ERROR", "T09", f"{nid} {b.get('kind')}: floor_lifted_by {lifted!r} is not a node above this branch")
                continue
            if b.get("prior") in PRIORS and PRIORS.index(b["prior"]) < PRIORS.index(fl):
                add("ERROR", "T09", f"{nid} {b.get('kind')}: prior {b['prior']!r} is below its floor {fl!r} ({why}) - raise "
                                    "it, or name the node above that measured what the floor assumes unknown "
                                    "(`floor_lifted_by`)")
    weak = []
    for nid in main_nodes:
        n = nodes[nid]
        serves = (pid in (n.get("claims") or []) or (n.get("role") == "instrument" and not n.get("claims"))) \
            and not n.get("external")
        for b in _branches(n):
            if serves and b.get("prior") == "likely" and (
                    b.get("kind") in WEAK_KIND or (leaves.get(b.get("leaf")) or {}).get("paper") in WEAK_LEAF):
                weak.append(f"{nid} {b.get('kind')}")
    odds = leaf_odds(tree)
    mass = paper_mass(tree, odds)
    weak_mass = sum(v for k, v in mass.items() if k in WEAK_LEAF)
    if weak:
        add("ERROR", "T09", f"decision gate: the primary claim's likeliest outcome is a weak one ({', '.join(sorted(set(weak)))}) "
                            "- change the design (P2) until it is at most possible, narrow the question, or record "
                            "'Uninformative branch likely: …'")
    elif weak_mass >= 0.5:
        add("ERROR", "T09", f"decision gate: weak outcomes (methods-caveat, not-publishable) carry about {weak_mass:.0%} of "
                            f"the tree ({_mass_text(mass)}) - change the design (P2), narrow the question, or record "
                            "'Uninformative branch likely: …'")
    # ---- T10 outcomes are the tree's projection
    proj = projection(tree, arg)
    for cid, c in C.items():
        if cid not in proj:
            add("WARN", "T10", f"{cid} is in no leaf: its outcomes are hand-written, not read off the tree")
        elif (c.get("outcomes") or {}) != proj[cid]:
            add("ERROR", "T10", f"{cid}: outcomes differ from the tree's leaves - run tree-render --project")
    # ---- T11 a checkpoint before the primary test
    for p, _ in paths:
        order = [nid for nid, _ in p]
        firsts = [i for i, nid in enumerate(order) if nodes[nid].get("role") == "tests" and pid in (nodes[nid].get("claims") or [])]
        if firsts and not any(nodes[x].get("checkpoint") for x in order[:firsts[0]]):
            add("WARN", "T11", f"no checkpoint before the primary test on {' > '.join(order[:firsts[0] + 1])}: the "
                               "experiment stage gets no early go / no-go")
            break
    # ---- T12 a not-publishable leaf says what happens then
    for lid, l in leaves.items():
        if l.get("paper") == "not-publishable" and not str(l.get("then") or "").strip():
            add("ERROR", "T12", f"{lid}: not-publishable - `then` says what the run does (stop, which question instead)")
    # ---- T13 built on the current argument
    if gd is not None and isinstance(tree.get("based_on"), dict):
        now = based_on(gd)
        stale = [k for k, v in tree["based_on"].items() if now.get(k) != v]
        if stale:
            add("ERROR", "T13", f"the tree was built on another {', '.join(stale)} - P1 or P2 changed since: rebuild it "
                                "(tree-prefill, then the tree)")
    elif gd is not None:
        add("ERROR", "T13", "`based_on` missing - tree-render --project writes it")
    # ---- T14 a publishable leaf of round 1 that is gone has its tradeoffs row
    if gd is not None and (Path(gd) / "decision_tree_r1.json").exists():
        r1 = read_json(Path(gd) / "decision_tree_r1.json")
        gone = [l.get("id") for l in r1.get("leaves") or [] if isinstance(l, dict) and l.get("paper") in PUBLISHABLE
                and l.get("id") not in leaves]
        missing = _r1_removed(arg, gone, "leaf")
        if missing:
            add("ERROR", "T14", f"publishable leaves {missing} of the round-1 tree are gone without a `tradeoffs` row naming "
                                "them (ids) - what can no longer be concluded")
    return out


def projection(tree: dict, arg: dict) -> dict:
    """claims[].outcomes from the leaves: if_supported / if_not / if_undecided = the conclusions of the leaves where the
    claim has that status (an estimate claim: estimated / imprecise). A claim in no leaf is left out."""
    C = _claims(arg)
    leaves = [l for l in tree.get("leaves") or [] if isinstance(l, dict)]
    out = {}
    for cid, c in C.items():
        est = c.get("mode") == "estimate"
        keys = (("if_supported", "estimated"), ("if_not", "imprecise")) if est else \
            (("if_supported", "supported"), ("if_not", "refuted"), ("if_undecided", "undecided"))
        o = {}
        for k, s in keys:
            texts = [f"[{l['id']}] {l.get('conclusion', '').strip()}" for l in leaves
                     if isinstance(l.get("claims"), dict) and l["claims"].get(cid) == s and l.get("id")]
            if texts:
                o[k] = " | ".join(texts)
        if o:
            out[cid] = o
    return out


def tree_prefill(gd: Path) -> dict:
    """A skeleton in the argument's own terms: one node per experiment that decides something, in a licensing order
    (instruments, the primary claim's positive control and the controls its rule takes a number from, its test, the
    other tests, the remaining controls, the external checks), the branch kinds and each branch's prior floor."""
    gd = Path(gd)
    arg = read_json(gd / "argument.json")
    C = _claims(arg)
    prim = next((c for c in C.values() if c.get("primary") is True), {})
    pid = prim.get("id")
    pos, neg = _control_ids(prim)
    feeds = _threshold_sources(prim)
    exps = [e for e in arg.get("experiments") or [] if isinstance(e, dict) and e.get("role") in KINDS]
    ext = arg.get("external_check") if isinstance(arg.get("external_check"), dict) else {}
    external = {x for x in (ext.get("real_data"), ext.get("second_dataset")) if isinstance(x, str) and re.fullmatch(r"E\d+", x)}

    def order(e):
        r, cl = e.get("role"), e.get("claims") or []
        if e.get("id") in external:
            return 5
        if r == "instrument":
            return 0
        if r in ("control", "descriptive") and e.get("id") in pos | feeds:
            return 1
        if r == "tests" and pid in cl:
            return 2
        if r == "tests":
            return 3
        return 4
    exps.sort(key=lambda e: (order(e), int(re.sub(r"\D", "", e.get("id") or "0") or 0)))
    nodes = []
    for i, e in enumerate(exps):
        role = e.get("role")
        names_first = lambda f: (EID.search(str(f or "")) or [None])[0] if EID.search(str(f or "")) else None
        rule = [str(C.get(c, {}).get("falsifier") or "") for c in e.get("claims") or []
                if role == "tests" and names_first(C.get(c, {}).get("falsifier")) == e.get("id")]
        norm = lambda s: " ".join(str(s).lower().split())
        for c in e.get("claims") or []:
            r = _evidence_rule(C.get(c, {}), e.get("id"))
            if r and norm(r) not in {norm(x) for x in rule}:
                rule.append(r)
        n = {"id": f"N{i}", "experiment": e.get("id"), "role": role, "claims": e.get("claims") or [],
             "reads": rule[0] if rule else "(write)",
             "checkpoint": order(e) in (0, 1) or bool(e.get("checkpoint_reads")), "branches": []}
        if len(rule) > 1:
            n["also_rules"] = rule[1:]
        if e.get("id") in external:
            n["external"] = True
        if e.get("checkpoint_reads"):
            n["checkpoint_reads"] = e["checkpoint_reads"]
        for k in KINDS[role]:
            fl, why = prior_floor(arg, n, k)
            n["branches"].append({"kind": k, "if": "(write)", "next": None, "leaf": None, "prior": fl, "prior_floor": fl,
                                  "prior_basis": why})
        nodes.append(n)
    return {"schema": TREE_SCHEMA, "idea": arg.get("idea"), "generation": arg.get("generation"),
            "question": (read_json(gd / "question.json").get("question") if (gd / "question.json").exists() else None),
            "root": "N0" if nodes else None, "subtrees": [], "nodes": nodes, "leaves": [],
            "_note": "a skeleton: link the branches (next / leaf), write the leaves, keep each prior at or above its floor; "
                     "a secondary claim read on every path goes into its own subtree (`subtrees`)"}


def render(tree: dict) -> str:
    nodes = {n["id"]: n for n in tree.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
    leaves = {l["id"]: l for l in tree.get("leaves") or [] if isinstance(l, dict) and l.get("id")}
    odds = leaf_odds(tree)
    L = [f"# Decision tree — {tree.get('idea') or ''}", "",
         "Generated by `ideate_tools.py tree-render` from `decision_tree.json` - edit the JSON, not this file.", ""]
    if odds:
        L += [f"What the paper would be (rough, from the priors): {_mass_text(paper_mass(tree, odds))}.", ""]
    L.append("```")
    done = set()

    def node(nid, ind):
        n = nodes.get(nid)
        if not n:
            return
        tags = "".join([" [checkpoint]" if n.get("checkpoint") else "", " [external]" if n.get("external") else ""])
        L.append(f"{ind}{nid}  {n.get('experiment')} [{n.get('role')} {','.join(n.get('claims') or [])}] {n.get('reads')}{tags}")
        if nid in done:
            L.append(f"{ind}   (see above)")
            return
        done.add(nid)
        bs = _branches(n)
        for i, b in enumerate(bs):
            last = i == len(bs) - 1
            pre = ind + ("└ " if last else "├ ")
            tail = f"({b.get('prior')}) {b.get('if')}"
            if b.get("leaf"):
                l = leaves.get(b["leaf"], {})
                pct = f" ~{odds[b['leaf']]:.0%}" if b["leaf"] in odds else ""
                L.append(f"{pre}{b.get('kind')} {tail} → {b['leaf']} {l.get('paper')}{pct}: {l.get('conclusion')}")
            else:
                L.append(f"{pre}{b.get('kind')} {tail} →")
                node(b.get("next"), ind + ("   " if last else "│  "))
    node(tree.get("root"), "")
    for s in _ids(tree.get("subtrees")):
        L.append("")
        L.append(f"subtree (read on every path):")
        node(s, "")
    L += ["```", "", "| leaf | paper | claims | answers | rivals killed / alive | targets hit | conclusion | then |",
          "|---|---|---|---|---|---|---|---|"]
    for lid, l in leaves.items():
        rv = l.get("rivals") or {}
        L.append(f"| {lid} | {l.get('paper')} | {', '.join(f'{k} {v}' for k, v in (l.get('claims') or {}).items())} | "
                 f"{l.get('answers_question')} | {', '.join(_ids(rv.get('killed'))) or '—'} / {', '.join(_ids(rv.get('alive'))) or '—'} | "
                 f"{', '.join(_ids(l.get('targets_hit'))) or '—'} | {l.get('conclusion')} | {l.get('then') or '—'} |")
    return "\n".join(L) + "\n"


def _print_tree_findings(fs):
    for f in fs:
        print(f"{f['level']} {f['code']}: {f['text']}")


def stale(gd: Path) -> list[str]:
    """The planning files of a generation that were built on another argument / tree / attack plan than the current
    ones (argument-check C28). Empty when none exists - an older generation."""
    gd = Path(gd)
    out = []
    try:
        if (gd / TREE).exists():
            t = read_json(gd / TREE)
            if isinstance(t.get("based_on"), dict):
                now = based_on(gd)
                out += [f"{TREE} (built on another {k})" for k, v in t["based_on"].items() if now.get(k) != v]
        if (gd / ATTACK).exists():
            p = read_json(gd / ATTACK)
            if isinstance(p.get("based_on"), dict):
                now = attack_based_on(gd)
                out += [f"{ATTACK} (built on another {k})" for k, v in p["based_on"].items() if now.get(k) != v]
        if (gd / PACK).exists():
            k_ = read_json(gd / PACK)
            if isinstance(k_.get("based_on"), dict):
                now = pack_based_on(gd)
                out += [f"{PACK} (built on another {k})" for k, v in k_["based_on"].items() if now.get(k) != v]
    except Exception as e:                      # an unreadable planning file is its own check's problem
        out.append(f"a planning file cannot be read ({type(e).__name__})")
    return out


def _r1_removed(arg: dict, ids: list, kind: str) -> list[str]:
    """ids present in the round-1 copy and gone now, without a tradeoffs row that names them"""
    named = {i for r in arg.get("tradeoffs") or [] if isinstance(r, dict) for i in _ids(r.get("ids"))}
    return [i for i in ids if i not in named]


def cmd_tree_prefill(a):
    gd = Path(a.gen_dir)
    if not (gd / "argument.json").exists():
        die(f"{gd}/argument.json not found - the tree is drawn after P2", 2)
    sk = tree_prefill(gd)
    write_json(gd / TREE_DRAFT, sk)
    print(f"tree-prefill {gd.name}: {len(sk['nodes'])} node(s) -> {TREE_DRAFT}")
    for n in sk["nodes"]:
        fl = ", ".join(f"{b['kind']} >= {b['prior_floor']}" for b in n["branches"] if b["prior_floor"] != "unlikely")
        tag = " checkpoint" if n["checkpoint"] else ""
        tag += " external" if n.get("external") else ""
        print(f"  {n['id']} {n['experiment']} [{n['role']} {','.join(n['claims'])}]{tag}{'  floors: ' + fl if fl else ''}")
    print("  then write decision_tree.json (P3-decision-tree.md) and run tree-render --project, tree-check")


def cmd_tree_render(a):
    gd = Path(a.gen_dir)
    tree = read_json(gd / TREE)
    if a.project:
        arg = read_json(gd / "argument.json")
        proj = projection(tree, arg)
        for c in arg.get("claims") or []:
            if isinstance(c, dict) and c.get("id") in proj:
                c["outcomes"] = proj[c["id"]]
        write_json(gd / "argument.json", arg)
        tree["based_on"] = based_on(gd)
        write_json(gd / TREE, tree)
        print(f"tree-render --project: outcomes of {sorted(proj)} written into argument.json; based_on recorded")
    from it_common import write_text
    write_text(gd / "decision_tree.md", render(tree))
    print(f"tree-render: -> {gd.name}/decision_tree.md")


def cmd_tree_check(a):
    gd = Path(a.gen_dir)
    for f in (TREE, "argument.json"):
        if not (gd / f).exists():
            die(f"{gd}/{f} not found", 2)
    try:
        tree = read_json(gd / TREE)
        fs = tree_findings(tree, read_json(gd / "argument.json"), gd)
    except Exception as e:
        die(f"{gd / TREE} holds a value tree-check cannot read ({type(e).__name__}: {e}) - compare with P3-decision-tree.md", 2)
    if a.json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
    else:
        _print_tree_findings(fs)
    errs = [f for f in fs if f["level"] == "ERROR"]
    if not a.json:
        mass = paper_mass(tree)
        if mass:
            print(f"what the paper would be (rough, from the priors): {_mass_text(mass)}")
        print(f"tree-check: {len(errs)} error(s), {len(fs) - len(errs)} warning(s)" + (" - REVISE" if errs else " - OK"))
    raise SystemExit(1 if errs else 0)


# ================================================================================================ P4 attack-type Related Work
ATTACK = "attack_plan.json"
ATTACK_DRAFT = "attack_plan.draft.json"
ATTACK_SCHEMA = "ai-scientist-attack/1"
COVER_RESULTS = {"conflict", "boundary", "untested-shared", "assumption-challenged", "assumption-at-stake", "criterion-unmet"}
HEDGED = {"may", "suggests", "correlates"}
REFUTE_WORDS = re.compile(r"\b(refut\w*|disprov\w*|overturn\w*|debunk\w*|falsif\w*|wrong|invalidat\w*|demolish\w*)\b", re.I)
KEY = re.compile(r"\[([a-z][a-z0-9]*?(?:\d{4}|nd)[a-z]?)\]")
RW_ROLES = ("common-ground", "closest")


def _tree_canon(tree: dict) -> str:
    """the tree without what P4 writes into it (leaves' targets_hit) - the part the attack plan is built on"""
    t = json.loads(json.dumps(tree))
    for l in t.get("leaves") or []:
        if isinstance(l, dict):
            l.pop("targets_hit", None)
    return json.dumps(t, sort_keys=True, ensure_ascii=False)


def attack_based_on(gd: Path) -> dict:
    gd = Path(gd)
    out = {"argument.json": _sha(_canon_argument(read_json(gd / "argument.json")))}
    if (gd / TREE).exists():
        out[TREE] = _sha(_tree_canon(read_json(gd / TREE)))
    return out


def related_work_text(plan: dict) -> str:
    """The Related Work field: the paragraphs in order, one blank line between them."""
    return "\n\n".join(str(p.get("text") or "").strip() for p in plan.get("related_work") or []
                       if isinstance(p, dict) and str(p.get("text") or "").strip())


def _shortlist_keys(rd: Path) -> set:
    p = Path(rd) / "step3_shortlist.json"
    if not p.exists():
        return set()
    d = read_json(p)
    return {x.get("citation_key") for x in (d.get("papers") if isinstance(d, dict) else d) or [] if isinstance(x, dict)}


def _tree_paths(tree: dict) -> list:
    nodes = {n.get("id"): n for n in tree.get("nodes") or [] if isinstance(n, dict)}
    leaves = {l.get("id"): l for l in tree.get("leaves") or [] if isinstance(l, dict)}
    paths, _ = _walk(nodes, leaves, tree.get("root"))
    for s in _ids(tree.get("subtrees")):
        sp, _ = _walk(nodes, leaves, s)
        paths += sp
    return [([nodes[nid].get("experiment") for nid, _ in p], lid) for p, lid in paths]


def attack_findings(plan: dict, arg: dict, tree: dict, q: dict, rd: Path, gd: Path | None = None,
                    idea: dict | None = None) -> list[dict]:
    """R01-R12. Findings {level, code, text}."""
    out = []
    add = lambda level, code, text: out.append({"level": level, "code": code, "text": text})
    if plan.get("schema") != ATTACK_SCHEMA:
        add("ERROR", "R01", f"schema is {plan.get('schema')!r}, expected {ATTACK_SCHEMA!r}")
    import it_collide
    import it_decon
    recs = {k: r for k, r in it_decon.records(rd).items() if not r.get("_unreadable")}
    units = {u["id"]: {**u, "paper": k} for k, r in recs.items() for u in r.get("units") or []}
    cur = {r["collision_id"]: r for r in it_collide.current(it_collide.log(rd))} if (Path(rd) / it_collide.LOG).exists() else {}
    exps = {e.get("id"): e for e in arg.get("experiments") or [] if isinstance(e, dict)}
    leaves = {l.get("id"): l for l in tree.get("leaves") or [] if isinstance(l, dict)}
    paths = _tree_paths(tree)
    handed = {t.get("id"): t for t in q.get("targets") or [] if isinstance(t, dict)}
    level_of = lambda k: "abstract" if ((recs.get(k) or {}).get("eligibility") or {}).get("verdict") == "abstract-only" \
        or (recs.get(k) or {}).get("basis") == "abstract" else "full"
    T = [t for t in plan.get("targets") or [] if isinstance(t, dict)]
    # ---- R01 targets
    if not T:
        add("ERROR", "R01", "no targets: an attack-type Related Work names whose sentence the study tests (question.json "
                            "targets, from the question's section 9)")
    elif len(T) == 1:
        add("WARN", "R01", "one target: standard and deep runs attack at least two (the claim tested and the strongest "
                           "competing position)")
    ids = [t.get("id") for t in T]
    if len(set(ids)) != len(ids) or [i for i in ids if not re.fullmatch(r"T\d+", str(i))]:
        add("ERROR", "R01", f"target ids {ids}: T1, T2, … each once")
    orders = [t.get("order") for t in T]
    if sorted(o for o in orders if isinstance(o, int)) != list(range(1, len(T) + 1)):
        add("ERROR", "R01", f"`order` {orders}: 1 … {len(T)}, each once (1 = attacked first)")
    dropped = {d.get("id"): d for d in plan.get("dropped") or [] if isinstance(d, dict)}
    for hid in sorted(set(handed) - {t.get("id") for t in T}):
        if not str((dropped.get(hid) or {}).get("why") or "").strip():
            add("ERROR", "R01", f"handed-over target {hid} is neither attacked nor in `dropped` with a `why` (the design "
                                "cannot test it, say so)")
    for t in T:
        tid = t.get("id")
        h = handed.get(tid)
        if h:
            if sorted(_ids(h.get("claim_units"))) != sorted(_ids(t.get("claim_units"))) or \
                    (h.get("weakness") or {}) != (t.get("weakness") or {}):
                add("ERROR", "R01", f"{tid}: claim_units / weakness differ from the handed-over target {tid} - keep the "
                                    "fusion record, or add a new target with `added_because`")
        elif not str(t.get("added_because") or "").strip():
            add("ERROR", "R01", f"{tid}: not a handed-over target - say why it is added (`added_because`)")
        # ---- R02 the sentence exists, at its strength
        cu = _ids(t.get("claim_units"))
        bad = [u for u in cu if u not in units or not str(units[u].get("quote") or "").strip()]
        if not cu or bad:
            add("ERROR", "R02", f"{tid}: claim_units {bad or cu} are not deconstruction units with a verified quote")
            continue
        papers = sorted({units[u]["paper"] for u in cu})
        if sorted(_ids(t.get("papers"))) != papers:
            add("ERROR", "R02", f"{tid}: papers {t.get('papers')} are not its units' papers {papers}")
        # ---- R10 the weakness is a record
        w = t.get("weakness") if isinstance(t.get("weakness"), dict) else {}
        if w.get("overreach"):
            if w["overreach"] not in cu or not str(units[w["overreach"]].get("overreach") or "").strip():
                add("ERROR", "R10", f"{tid}: weakness overreach {w['overreach']!r} is not one of its units marked overreach")
        else:
            r = cur.get(w.get("collision"))
            if not r or r["result"] not in COVER_RESULTS:
                add("ERROR", "R10", f"{tid}: weakness {w.get('collision')!r} is no current conflict, boundary or premise "
                                    "collision - an attack rests on a record, not on a reading note's observation")
        # ---- R04 weapon and landing
        wp = _ids(t.get("weapon"))
        badw = [e for e in wp if (exps.get(e) or {}).get("role") not in ("tests", "control", "descriptive")]
        if not wp or badw:
            add("ERROR", "R04", f"{tid}: weapon {wp} - experiments of argument.json with role tests, control or descriptive "
                                f"(bad: {badw})")
        land = _ids(t.get("lands_on"))
        if not land or [l for l in land if l not in leaves]:
            add("ERROR", "R04", f"{tid}: lands_on {land} - leaves of the decision tree")
        elif wp and not any(lid in land and set(wp) & set(ex) for ex, lid in paths):
            add("ERROR", "R04", f"{tid}: no path to {land} passes through its weapon {wp} - the blow lands where the weapon "
                                "is read")
        elif [l for l in land if leaves[l].get("paper") in WEAK_LEAF]:
            add("ERROR", "R04", f"{tid}: lands on a weak leaf {[l for l in land if leaves[l].get('paper') in WEAK_LEAF]} - "
                                "an attack lands where a paper can say it")
        # ---- R05 if it misses
        m = t.get("if_miss") if isinstance(t.get("if_miss"), dict) else {}
        if m.get("leaf") not in leaves or m.get("leaf") in land or not str(m.get("say") or "").strip():
            add("ERROR", "R05", f"{tid}: if_miss {{leaf, say}} - another leaf of the tree, and what we then say about the "
                                "target (an attack never assumes the win)")
        # ---- R06 abstract-level targets
        lvl = "abstract" if any(level_of(p) == "abstract" for p in papers) else "full"
        if t.get("evidence_level") != lvl:
            add("ERROR", "R06", f"{tid}: evidence_level is {lvl!r} (the deconstruction basis), not {t.get('evidence_level')!r}")
        if lvl == "abstract" and t.get("order") == 1 and not str(t.get("fulltext_tried") or "").strip():
            add("ERROR", "R06", f"{tid}: the first target rests on an abstract - fetch its full text first (fusion F-M4) and "
                                "say so in `fulltext_tried`, or attack another target first")
        # ---- R09 fairness
        if not str(t.get("concede") or "").strip():
            add("WARN", "R09", f"{tid}: `concede` - what the target got right (an agree collision or its own unit)")
    # ---- can the tree deliver the attack? (the mass of the leaves it lands on or misses into)
    odds = leaf_odds(tree)
    if odds and T:
        reach = {l for t in T for l in _ids(t.get("lands_on")) + [((t.get("if_miss") or {}).get("leaf"))] if l}
        m = sum(odds.get(l, 0) for l in reach)
        if m < 0.5:
            gate = [f for f in tree_findings(tree, arg) if f["code"] == "T09" and f["level"] == "ERROR"]
            add("WARN", "R04", f"the leaves the attacks land on or miss into carry about {m:.0%} of the tree "
                               f"({_mass_text(paper_mass(tree, odds))}): most outcomes say nothing about the targets - "
                               + ("resolve the tree's gate (P3) before writing the attack as if it will be delivered"
                                  if gate else "let an attack land on, or miss into, the likeliest publishable leaves too"))
    # ---- the text
    paras = [p for p in plan.get("related_work") or [] if isinstance(p, dict)]
    roles = [p.get("role") for p in paras]
    rw = related_work_text(plan)
    if not paras or roles[0] != "common-ground" or "closest" not in roles:
        add("ERROR", "R07", f"related_work paragraphs {roles}: common-ground first, one per target (role = its id), "
                            "closest last")
    by_role = {p.get("role"): str(p.get("text") or "") for p in paras}
    for t in T:
        txt = by_role.get(t.get("id"))
        if txt is None:
            add("ERROR", "R07", f"{t.get('id')}: no Related Work paragraph with role {t.get('id')!r}")
            continue
        cited = set(KEY.findall(txt))
        missk = [k for k in _ids(t.get("papers")) if k not in cited]
        misse = [e for e in _ids(t.get("weapon")) if not re.search(rf"\b{re.escape(e)}\b", txt)]
        if missk or misse:
            add("ERROR", "R07", f"{t.get('id')}: its paragraph cites {sorted(cited)}; missing keys {missk}, weapon ids {misse}")
        if t.get("strength") in HEDGED and REFUTE_WORDS.search(txt):
            add("WARN", "R03", f"{t.get('id')}: the target only {t.get('strength')} ({REFUTE_WORDS.search(txt).group(0)!r} "
                               "in its paragraph) - test it, do not refute it")
        if t.get("evidence_level") == "abstract" and "abstract" not in txt.lower():
            add("ERROR", "R06", f"{t.get('id')}: rests on an abstract - its paragraph says so")
    cl = plan.get("closest") if isinstance(plan.get("closest"), dict) else {}
    ctext = by_role.get("closest", "")
    if not _ids(cl.get("papers")) or not str(cl.get("distinction") or "").strip() or not str(cl.get("lookup") or "").strip():
        add("ERROR", "R07", "closest {papers, lookup, distinction}: the most similar retrieved work, the lookup that found "
                            "it, and the one-sentence difference")
    elif [k for k in _ids(cl.get("papers")) if k not in set(KEY.findall(ctext))]:
        add("ERROR", "R07", f"the closest paragraph does not cite {_ids(cl.get('papers'))}")
    bad_cg = [i for i in _ids(plan.get("common_ground")) if i not in cur and i not in units
              and not re.fullmatch(r"[A-Z]_draft_\w+", i)]
    if bad_cg:
        add("ERROR", "R07", f"common_ground ids {bad_cg} are not current collisions, units or Lines")
    ncg = len(KEY.sub("", by_role.get("common-ground", "")).split())
    if ncg > 120:
        add("WARN", "R07", f"the common-ground paragraph is {ncg} words: keep it near 100 - the length belongs to the "
                           "target paragraphs, where the attack is")
    if not KEY.findall(by_role.get("common-ground", "")):
        add("ERROR", "R07", "the common-ground paragraph cites no paper")
    n = len(KEY.sub("", rw).split())                      # citation keys are not words a reader reads
    if rw and not 150 <= n <= 450:
        add("WARN", "R07", f"Related Work is {n} words (150-450)")
    # ---- R08 every key in the shortlist
    sl = _shortlist_keys(rd)
    if sl:
        alien = sorted({k for k in KEY.findall(rw) if k not in sl})
        if alien:
            add("ERROR", "R08", f"cited keys {alien} are not in step3_shortlist.json - cite only what was screened")
    if idea is not None and str(idea.get("Related Work") or "").strip() != rw.strip():
        add("ERROR", "R07", "the idea's Related Work is not the attack plan's text (P5 copies it verbatim; edit the plan)")
    # ---- R11 built on the current argument and tree; R12 the tree knows what lands where
    if gd is not None:
        if not isinstance(plan.get("based_on"), dict):
            add("ERROR", "R11", "`based_on` missing - attack-render writes it")
        else:
            now = attack_based_on(gd)
            stale = [k for k, v in plan["based_on"].items() if now.get(k) != v]
            if stale:
                add("ERROR", "R11", f"the attack plan was built on another {', '.join(stale)} - rebuild it")
    want = {lid: sorted(t.get("id") for t in T if lid in _ids(t.get("lands_on"))) for lid in leaves}
    have = {lid: sorted(_ids(l.get("targets_hit"))) for lid, l in leaves.items()}
    if want != have:
        add("ERROR", "R12", "the decision tree's targets_hit differ from the plan's lands_on - run attack-render")
    # ---- R13 a target of round 1 that is no longer attacked has its tradeoffs row
    if gd is not None and (Path(gd) / "attack_plan_r1.json").exists():
        r1 = read_json(Path(gd) / "attack_plan_r1.json")
        gone = [x.get("id") for x in r1.get("targets") or [] if isinstance(x, dict) and x.get("id") not in {t.get("id") for t in T}]
        missing = _r1_removed(arg, gone, "target")
        if missing:
            add("ERROR", "R13", f"targets {missing} of the round-1 plan are no longer attacked and no `tradeoffs` row names "
                                "them (ids) - the reader loses that attack")
    return out


def attack_prefill(gd: Path) -> dict:
    gd = Path(gd)
    rd = gd.parent
    q = read_json(gd / "question.json") if (gd / "question.json").exists() else {}
    arg = read_json(gd / "argument.json")
    tree = read_json(gd / TREE) if (gd / TREE).exists() else {}
    leaves = [l for l in tree.get("leaves") or [] if isinstance(l, dict)]
    C = _claims(arg)
    prim = next((c for c in C.values() if c.get("primary") is True), {})
    pid = prim.get("id")
    weapons = [e.get("id") for e in arg.get("experiments") or [] if isinstance(e, dict) and e.get("role") == "tests"
               and pid in (e.get("claims") or [])]
    odds = leaf_odds(tree)
    by_odds = sorted(leaves, key=lambda l: -odds.get(l.get("id"), 0))
    land = [l["id"] for l in by_odds if l.get("paper") in ("finding", "boundary", "rival-finding")
            and (l.get("claims") or {}).get(pid) == "supported"] or \
           [l["id"] for l in by_odds if l.get("paper") in PUBLISHABLE and (l.get("claims") or {}).get(pid) in ("supported", "refuted")]
    miss = [l["id"] for l in by_odds if l.get("paper") == "informative-null" and l["id"] not in land[:1]] or \
           [l["id"] for l in by_odds if l.get("id") not in land[:1] and l.get("paper") in PUBLISHABLE]
    import it_collide
    cur = it_collide.current(it_collide.log(rd)) if (rd / it_collide.LOG).exists() else []
    targets = []
    import it_decon
    recs = it_decon.records(rd)
    for i, t in enumerate(q.get("targets") or [], 1):
        papers = set(_ids(t.get("papers")))
        own = set(_ids(t.get("claim_units")))
        agree = sorted(r["collision_id"] for r in cur if r["result"] in ("agree", "extends")
                       and own & {s.get("id") for s in r["sides"]})
        agree += [u["id"] for k in sorted(papers) for u in (recs.get(k) or {}).get("units") or []
                  if re.search(r"#[LF]\d+$", str(u.get("id")))]
        paper_level = sorted(r["collision_id"] for r in cur if r["result"] == "agree"
                             and papers & {s.get("paper") for s in r["sides"]} and r["collision_id"] not in agree)
        targets.append({**{k: t.get(k) for k in ("id", "papers", "claim_units", "strength", "weakness", "evidence_level",
                                                   "holds")},
                        "order": i, "weapon": weapons[:1], "lands_on": land[:1],
                        "if_miss": {"leaf": miss[0] if miss else None, "say": "(write)"},
                        "concede": "(write)", "concede_candidates": agree[:12],
                        "concede_paper_level": paper_level[:6],
                        "_check": "prefill does not judge whether the design tests this target: drop it (`dropped`) if no "
                                  "experiment reaches its sentence"})
    return {"schema": ATTACK_SCHEMA, "idea": arg.get("idea"), "generation": arg.get("generation"),
            "question": q.get("question"), "common_ground": [], "targets": targets,
            "closest": {"papers": [], "lookup": "(the round-1 novelty lookup)", "distinction": "(write)"},
            "related_work": [{"role": "common-ground", "text": "(write)"}] +
                            [{"role": t["id"], "text": "(write)"} for t in targets] + [{"role": "closest", "text": "(write)"}],
            "_note": "a skeleton: choose each target's weapon and landing leaf, write if_miss and concede, then the "
                     "paragraphs (P4-attack.md)"}


def cmd_attack_prefill(a):
    gd = Path(a.gen_dir)
    for f in ("argument.json", TREE):
        if not (gd / f).exists():
            die(f"{gd}/{f} not found - P4 comes after the decision tree", 2)
    sk = attack_prefill(gd)
    write_json(gd / ATTACK_DRAFT, sk)
    print(f"attack-prefill {gd.name}: {len(sk['targets'])} target(s) -> {ATTACK_DRAFT}")
    for t in sk["targets"]:
        print(f"  {t['id']} {','.join(_ids(t.get('claim_units')))} ({t.get('strength')}, {t.get('evidence_level')}) "
              f"weapon {t['weapon']} lands {t['lands_on']} miss {t['if_miss']['leaf']}; agree with: "
              f"{', '.join(t['concede_candidates']) or '-'}")
    if not sk["targets"]:
        print("  WARN question.json hands over no targets (no section 9): add targets with `added_because`")


def cmd_attack_render(a):
    gd = Path(a.gen_dir)
    plan = read_json(gd / ATTACK)
    tree = read_json(gd / TREE)
    T = [t for t in plan.get("targets") or [] if isinstance(t, dict)]
    for l in tree.get("leaves") or []:
        if isinstance(l, dict):
            hit = sorted(t.get("id") for t in T if l.get("id") in _ids(t.get("lands_on")))
            if hit:
                l["targets_hit"] = hit
            else:
                l.pop("targets_hit", None)
    write_json(gd / TREE, tree)
    from it_common import write_text
    write_text(gd / "decision_tree.md", render(tree))
    plan["based_on"] = attack_based_on(gd)
    write_json(gd / ATTACK, plan)
    rw = related_work_text(plan)
    write_text(gd / "related_work.md", rw + "\n")
    print(f"attack-render: targets_hit written into the tree; Related Work ({len(rw.split())} words) -> "
          f"{gd.name}/related_work.md; based_on recorded")


def cmd_attack_check(a):
    gd = Path(a.gen_dir)
    for f in (ATTACK, TREE, "argument.json"):
        if not (gd / f).exists():
            die(f"{gd}/{f} not found", 2)
    idea = None
    if a.idea:
        d = read_json(Path(a.idea))
        idea = d.get("idea", d) if isinstance(d, dict) else None
    q = read_json(gd / "question.json") if (gd / "question.json").exists() else {}
    try:
        fs = attack_findings(read_json(gd / ATTACK), read_json(gd / "argument.json"), read_json(gd / TREE), q,
                             gd.parent, gd, idea)
    except Exception as e:
        die(f"{gd / ATTACK} holds a value attack-check cannot read ({type(e).__name__}: {e}) - compare with P4-attack.md", 2)
    if a.json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
    else:
        for f in fs:
            print(f"{f['level']} {f['code']}: {f['text']}")
    errs = [f for f in fs if f["level"] == "ERROR"]
    if not a.json:
        print(f"attack-check: {len(errs)} error(s), {len(fs) - len(errs)} warning(s)" + (" - REVISE" if errs else " - OK"))
    raise SystemExit(1 if errs else 0)


# ================================================================================================ P5 packaging
PACK = "packaging.json"
PACK_DRAFT = "packaging.draft.json"
PACK_SCHEMA = "ai-scientist-packaging/1"
MOVES = ("context", "gap", "approach", "outcomes", "contribution")
RESULT_TONE = re.compile(r"\b(we (show|showed|found|find|demonstrate[ds]?|reveal(ed)?|establish(ed)?)|results? (show|showed|"
                         r"reveal(ed)?|indicate[ds]?|demonstrate[ds]?)|was found|were found|it turned out)\b", re.I)
# internal ids that must not be printed in the abstract (C3 / T7 are electrode names, L1 a norm: not matched)
IDS_IN_TEXT = re.compile(r"\bE\d+\b|\bX\d{4}\b|\bGAP_\d{3}\b|\bQ_\d{3}\b|\[[a-z][a-z0-9]*?(?:\d{4}|nd)[a-z]?\]|#[CALFNE]\d+")
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def pack_based_on(gd: Path) -> dict:
    gd = Path(gd)
    out = attack_based_on(gd)
    if (gd / ATTACK).exists():
        a = read_json(gd / ATTACK)
        a.pop("based_on", None)
        out[ATTACK] = _sha(json.dumps(a, sort_keys=True, ensure_ascii=False))
    return out


def abstract_text(pack: dict) -> str:
    return " ".join(str(s.get("text") or "").strip() for s in pack.get("abstract") or [] if isinstance(s, dict)
                    and str(s.get("text") or "").strip())


def short_hypothesis_text(pack: dict) -> str:
    return " ".join(str(s).strip() for s in pack.get("short_hypothesis") or [] if str(s).strip())


def required_leaves(tree: dict, pid: str | None, odds: dict | None = None) -> list[str]:
    """The leaves P5 must package (K07): for each reading of the primary claim (supported, refuted, undecided) its
    likeliest publishable leaf, and the likeliest methods-caveat leaf - each with odds of 5 % or more; at most four."""
    odds = leaf_odds(tree) if odds is None else odds
    leaves = sorted((l for l in tree.get("leaves") or [] if isinstance(l, dict)), key=lambda l: -odds.get(l.get("id"), 0))
    out = []
    for st in ("supported", "refuted", "undecided"):
        x = next((l["id"] for l in leaves if l.get("paper") in PUBLISHABLE and (l.get("claims") or {}).get(pid) == st
                  and odds.get(l["id"], 0) >= 0.05), None)
        if x and x not in out:
            out.append(x)
    x = next((l["id"] for l in leaves if l.get("paper") == "methods-caveat" and odds.get(l["id"], 0) >= 0.05), None)
    if x:
        out.append(x)
    return out[:4]


def pack_findings(pack: dict, arg: dict, tree: dict, plan: dict, rd: Path, gd: Path | None = None,
                  idea: dict | None = None) -> list[dict]:
    """K01-K10. Findings {level, code, text}."""
    out = []
    add = lambda level, code, text: out.append({"level": level, "code": code, "text": text})
    if pack.get("schema") != PACK_SCHEMA:
        add("ERROR", "K02", f"schema is {pack.get('schema')!r}, expected {PACK_SCHEMA!r}")
    import it_collide
    import it_decon
    cur = {r["collision_id"] for r in it_collide.current(it_collide.log(rd))} if (Path(rd) / it_collide.LOG).exists() else set()
    units = {u["id"] for r in it_decon.records(rd).values() if not r.get("_unreadable") for u in r.get("units") or []}
    keys = _shortlist_keys(rd)
    exps = {e.get("id") for e in arg.get("experiments") or [] if isinstance(e, dict)}
    C = _claims(arg)
    pid = next((c for c, x in C.items() if x.get("primary") is True), None)
    leaves = {l.get("id"): l for l in tree.get("leaves") or [] if isinstance(l, dict)}
    targets = {t.get("id") for t in plan.get("targets") or [] if isinstance(t, dict)}
    kind = lambda i: ("collision" if i in cur else "unit" if i in units else "experiment" if i in exps else
                      "leaf" if i in leaves else "target" if i in targets else "claim" if i in C else
                      "key" if i in keys else None)
    S = [s for s in pack.get("abstract") or [] if isinstance(s, dict)]
    ab = abstract_text(pack)
    # ---- K01 length
    n = len(ab.split())
    if not 150 <= n <= 250:
        add("ERROR", "K01", f"the abstract is {n} words: 150-250 (the contract's 'about 250' as a ceiling)")
    # ---- K02 every sentence has sources, and they exist; no ids in the printed text
    for i, s in enumerate(S, 1):
        src = _ids(s.get("sources"))
        bad = [x for x in src if not kind(x)]
        if not src or bad:
            add("ERROR", "K02", f"abstract sentence {i} ({s.get('move')}): sources {src} - ids of collisions, units, "
                                f"experiments, leaves, targets, claims or shortlisted keys (unknown: {bad})")
        if len(SENT.split(str(s.get("text") or "").strip())) > 1:
            add("WARN", "K02", f"abstract item {i} holds more than one sentence - one sentence per item, so its sources "
                               "say what it rests on")
    rival_ids = {r.get("id") for c in C.values() for r in c.get("rivals") or [] if isinstance(r, dict) and r.get("id")}
    local = re.findall(r"\b[LR]\d+\b", ab)                  # leaf / rival ids of this generation (not electrode names)
    leak = sorted(set(IDS_IN_TEXT.findall(ab)) | {x for x in local if x in leaves or x in rival_ids})
    if leak:
        add("ERROR", "K02", f"the abstract prints internal ids {leak[:6]} - the sources carry them; the text reads as prose")
    # ---- K03 the five moves, in order
    mv = [s.get("move") for s in S]
    if [m for m in mv if m not in MOVES]:
        add("ERROR", "K03", f"moves {mv}; allowed: {' | '.join(MOVES)}")
    elif any(MOVES.index(a) > MOVES.index(b) for a, b in zip(mv, mv[1:])) or set(MOVES) - set(mv):
        add("ERROR", "K03", f"moves {mv}: all five, in the order {' -> '.join(MOVES)}")
    want = {"context": {"collision", "unit", "key"}, "gap": {"target", "collision", "unit"}, "approach": {"experiment"},
            "outcomes": {"leaf"}}
    for i, s in enumerate(S, 1):
        kinds = want.get(s.get("move"))
        if kinds and not {kind(x) for x in _ids(s.get("sources"))} & kinds:
            add("ERROR", "K03", f"abstract sentence {i} ({s.get('move')}) rests on no {' / '.join(sorted(kinds))}")
    # ---- K04 no results yet
    hit = RESULT_TONE.search(ab)
    if hit:
        add("WARN", "K04", f"{hit.group(0)!r}: the abstract announces what will be tested - there are no results yet")
    # ---- K05 the outcomes sentence names two different readings of the primary claim
    oleaves = {x for s in S if s.get("move") == "outcomes" for x in _ids(s.get("sources")) if x in leaves}
    states = {(leaves[l].get("claims") or {}).get(pid) for l in oleaves}
    if len(states - {None}) < 2 or not [l for l in oleaves if leaves[l].get("paper") in PUBLISHABLE]:
        add("ERROR", "K05", f"the outcomes sentences rest on leaves {sorted(oleaves)}: they name at least two readings of "
                            f"{pid} (supported / refuted / undecided), at least one of them a publishable leaf")
    weak = [l for l in oleaves if leaves[l].get("paper") in WEAK_LEAF]
    if weak and not re.search(r"\bif\b|\bwhether\b|\bshould\b|\bwould\b", " ".join(str(s.get("text")) for s in S if s.get("move") == "outcomes"), re.I):
        add("WARN", "K05", f"the outcomes cite a weak leaf {weak} without a conditional - say it as one outcome of several")
    # ---- K06 the title
    title = str(pack.get("title") or "").strip()
    if not title:
        add("ERROR", "K06", "`title` is empty")
    elif len(title.split()) > 20:
        add("WARN", "K06", f"the title is {len(title.split())} words (20 at most reads as a title)")
    if title and RESULT_TONE.search(title):
        add("ERROR", "K06", "the title states a result - there are none yet")
    # ---- K07 per-leaf packaging for the likely publishable leaves
    odds = leaf_odds(tree)
    PACKABLE = PUBLISHABLE | {"methods-caveat"}
    likely = required_leaves(tree, pid, odds)
    by = pack.get("by_leaf") if isinstance(pack.get("by_leaf"), dict) else {}
    alien = [l for l in by if l not in leaves or leaves[l].get("paper") not in PACKABLE]
    if alien:
        add("ERROR", "K07", f"by_leaf {alien}: only publishable or methods-caveat leaves of the tree are packaged")
    for l in likely:
        e = by.get(l) if isinstance(by.get(l), dict) else {}
        if not str(e.get("title") or "").strip() or not re.search(r"\{\{[^{}]+\}\}", str(e.get("result_sentence") or "")):
            add("ERROR", "K07", f"{l} ({leaves[l].get('paper')}, ~{odds[l]:.0%}) needs by_leaf {{title, result_sentence "
                                "with a {{…}} slot for the number}}")
    # ---- K09 the short hypothesis: four sentences, the first the research question
    sh = [str(x).strip() for x in pack.get("short_hypothesis") or []]
    if len(sh) != 4 or [x for x in sh if not x]:
        add("ERROR", "K09", f"short_hypothesis is {len(sh)} sentence(s): four (question, claim, tested vs estimated, why no "
                            "simpler route)")
    elif _norm(sh[0]).rstrip("?.") != _norm(str(arg.get("question") or "")).rstrip("?."):
        add("ERROR", "K09", "the first sentence of short_hypothesis is not the research question word for word")
    # ---- K08 the idea carries this text
    if idea is not None:
        for field, txt in (("Title", title), ("Short Hypothesis", short_hypothesis_text(pack)), ("Abstract", ab),
                           ("Related Work", related_work_text(plan))):
            if str(idea.get(field) or "").strip() != txt.strip():
                add("ERROR", "K08", f"the idea's {field} is not the packaging's / the attack plan's text - pack-render "
                                    "writes it; edit the source")
    # ---- K11 the idea reads as a proposal: no pipeline vocabulary, no Risk entry said twice
    if idea is not None:
        body = " ".join([*(str(x) for x in idea.get("Experiments") or []), *(str(x) for x in idea.get("Risk Factors and Limitations") or []),
                         str(idea.get("Short Hypothesis") or ""), str(idea.get("Related Work") or "")])
        jargon = sorted({m.group(0) for m in re.finditer(r"\bthe (decision )?tree\b|\benv-probe\b|\bthe loop\b|\bjournal step\b|"
                                                           r"\bleaf L\d+\b|\b(round|restatement)-[12]\b|\bgen_\d+\b|\bQ_\d{3}\b|\bGAP_\d{3}\b",
                                                           body, re.I)} | {x for x in re.findall(r"\bL\d+\b", body) if x in leaves})
        if jargon:
            add("WARN", "K11", f"the idea carries pipeline vocabulary {jargon[:6]} - a reader of the proposal has no tree, "
                               "leaves or rounds; say it in the study's own terms")
        risks = [re.sub(r"^[^:]{0,60}unresolved[^:]*:\s*", "", str(x)).strip().lower()[:80] for x in idea.get("Risk Factors and Limitations") or []]
        dup = len(risks) - len(set(risks))
        if dup:
            add("WARN", "K11", f"{dup} Risk entr(y/ies) repeat another - one entry per distinct risk, whichever reader raised it")
    # ---- K10 built on the current argument, tree and attack plan
    if gd is not None:
        if not isinstance(pack.get("based_on"), dict):
            add("ERROR", "K10", "`based_on` missing - pack-render writes it")
        else:
            now = pack_based_on(gd)
            stale = [k for k, v in pack["based_on"].items() if now.get(k) != v]
            if stale:
                add("ERROR", "K10", f"the packaging was built on another {', '.join(stale)} - rebuild it")
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def pack_prefill(gd: Path) -> dict:
    gd = Path(gd)
    arg = read_json(gd / "argument.json")
    tree = read_json(gd / TREE)
    plan = read_json(gd / ATTACK)
    C = _claims(arg)
    prim = next((c for c in C.values() if c.get("primary") is True), {})
    pid = prim.get("id")
    odds = leaf_odds(tree)
    leaves = [l for l in tree.get("leaves") or [] if isinstance(l, dict)]
    pub = sorted((l for l in leaves if l.get("paper") in PUBLISHABLE), key=lambda l: -odds.get(l.get("id"), 0))
    tests = [e.get("id") for e in arg.get("experiments") or [] if isinstance(e, dict)
             and e.get("role") in ("tests", "control", "descriptive", "instrument")]
    T = [t for t in plan.get("targets") or [] if isinstance(t, dict)]
    rd = gd.parent
    import it_collide
    cur = {r["collision_id"]: r for r in it_collide.current(it_collide.log(rd))} if (rd / it_collide.LOG).exists() else {}
    gists = {c: str(cur[c].get("reason") or "")[:160] for c in _ids(plan.get("common_ground")) if c in cur}
    for t_ in T:
        c = (t_.get("weakness") or {}).get("collision")
        if c in cur:
            gists[c] = str(cur[c].get("reason") or "")[:160]
    likeliest = sorted(leaves, key=lambda l: -odds.get(l.get("id"), 0))
    req = required_leaves(tree, pid, odds)
    packable = [l for l in leaves if l.get("id") in req]
    sk = {"schema": PACK_SCHEMA, "idea": arg.get("idea"), "generation": arg.get("generation"),
            "title": "(write: the key terms of the tested part - argument key_terms, coverage)",
            "short_hypothesis": [arg.get("question") or "(the research question)", "(the primary claim, Although … because …)",
                                 "(what is tested, what only estimated, why this setting)",
                                 "(why no simpler route answers it - construction.computable_without_experiment)"],
            "abstract": [{"move": "context", "text": "(write)", "sources": _ids(plan.get("common_ground"))[:3]},
                         {"move": "gap", "text": "(write)", "sources": [t.get("id") for t in T][:2]},
                         {"move": "approach", "text": "(write)", "sources": tests},
                         {"move": "outcomes", "text": "(write)", "sources": [l["id"] for l in pub[:2]]},
                         {"move": "outcomes", "text": "(write: the likeliest outcomes, when they are not the decisive ones)",
                          "sources": [l["id"] for l in likeliest[:3] if l not in pub[:2]]},
                         {"move": "contribution", "text": "(write)", "sources": [pid] if pid else []}],
            "by_leaf": {l["id"]: {"title": "(write)", "result_sentence": "(write, with {{primary result}})",
                                  "paper": l.get("paper"), "odds": round(odds.get(l["id"], 0), 3),
                                  "conclusion": l.get("conclusion")}
                        for l in packable},
            "_gists": gists, "_leaf_odds": {l["id"]: round(odds.get(l["id"], 0), 3) for l in likeliest},
            "_key_terms": arg.get("key_terms"), "_coverage": arg.get("coverage"),
            "_note": "a skeleton: one sentence per abstract item, sources = the ids it rests on (never printed)"}
    sk["abstract"] = [s for s in sk["abstract"] if s["sources"] or s["move"] != "outcomes"]
    return sk


def cmd_pack_prefill(a):
    gd = Path(a.gen_dir)
    for f in ("argument.json", TREE, ATTACK):
        if not (gd / f).exists():
            die(f"{gd}/{f} not found - P5 comes after the attack plan", 2)
    sk = pack_prefill(gd)
    write_json(gd / PACK_DRAFT, sk)
    print(f"pack-prefill {gd.name}: -> {PACK_DRAFT}; leaves to package: {', '.join(sk['by_leaf']) or 'none'}")


def cmd_pack_render(a):
    gd = Path(a.gen_dir)
    pack = read_json(gd / PACK)
    plan = read_json(gd / ATTACK)
    arg = read_json(gd / "argument.json")
    p = gd / "idea_draft.json"
    idea = read_json(p) if p.exists() else {}
    idea = idea.get("idea", idea) if isinstance(idea, dict) else {}
    order = ("Name", "Title", "Short Hypothesis", "Related Work", "Abstract", "Experiments", "Risk Factors and Limitations")
    new = {"Name": idea.get("Name") or arg.get("idea") or "(name)", "Title": str(pack.get("title") or "").strip(),
           "Short Hypothesis": short_hypothesis_text(pack), "Related Work": related_work_text(plan),
           "Abstract": abstract_text(pack), "Experiments": idea.get("Experiments") or ["(compose from argument.json, §6)"],
           "Risk Factors and Limitations": idea.get("Risk Factors and Limitations") or ["(compose from argument.json, §6)"]}
    write_json(p, {k: new[k] for k in order})
    gate = [f["text"] for f in tree_findings(read_json(gd / TREE), arg, gd) if f["code"] == "T09" and f["level"] == "ERROR"]
    pack["tree_gate"] = ("failed: " + gate[0]) if gate else "passed"
    pack["based_on"] = pack_based_on(gd)
    write_json(gd / PACK, pack)
    print(f"pack-render: Title, Short Hypothesis, Abstract ({len(new['Abstract'].split())} words) and Related Work -> "
          f"{gd.name}/idea_draft.json (Name, Experiments, Risk kept); based_on recorded; tree gate {pack['tree_gate'][:6]}")
    if pack["tree_gate"] != "passed":
        print("  the decision tree failed its gate: Risk Factors carries 'Uninformative branch likely: …' (P3, ways out)")


def cmd_pack_check(a):
    gd = Path(a.gen_dir)
    for f in (PACK, ATTACK, TREE, "argument.json"):
        if not (gd / f).exists():
            die(f"{gd}/{f} not found", 2)
    idea = None
    ip = Path(a.idea) if a.idea else None
    if ip:
        d = read_json(ip)
        idea = d.get("idea", d) if isinstance(d, dict) else None
    try:
        fs = pack_findings(read_json(gd / PACK), read_json(gd / "argument.json"), read_json(gd / TREE),
                           read_json(gd / ATTACK), gd.parent, gd, idea)
    except Exception as e:
        die(f"{gd / PACK} holds a value pack-check cannot read ({type(e).__name__}: {e}) - compare with P5-package.md", 2)
    if a.json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
    else:
        for f in fs:
            print(f"{f['level']} {f['code']}: {f['text']}")
    errs = [f for f in fs if f["level"] == "ERROR"]
    if not a.json:
        print(f"pack-check: {len(errs)} error(s), {len(fs) - len(errs)} warning(s)" + (" - REVISE" if errs else " - OK"))
    raise SystemExit(1 if errs else 0)


def add_parsers(sub) -> None:
    sp = sub.add_parser("plan-status", help="planning block: which step's files a generation has")
    sp.add_argument("gen_dir")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_status)
    sp = sub.add_parser("hypo-prefill", help="planning P1: default form, rival candidates and magnitudes for the primary "
                                             "hypothesis")
    sp.add_argument("gen_dir")
    sp.set_defaults(fn=cmd_prefill)
    sp = sub.add_parser("tree-prefill", help="planning P3: a decision-tree skeleton with each branch's prior floor")
    sp.add_argument("gen_dir")
    sp.set_defaults(fn=cmd_tree_prefill)
    sp = sub.add_parser("tree-render", help="planning P3: decision_tree.md; --project writes the leaves into outcomes")
    sp.add_argument("gen_dir")
    sp.add_argument("--project", action="store_true")
    sp.set_defaults(fn=cmd_tree_render)
    sp = sub.add_parser("tree-check", help="planning P3: decision-tree checks T01-T13 (T09 = the decision gate)")
    sp.add_argument("gen_dir")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_tree_check)
    sp = sub.add_parser("attack-prefill", help="planning P4: attack-plan skeleton from the handed-over targets")
    sp.add_argument("gen_dir")
    sp.set_defaults(fn=cmd_attack_prefill)
    sp = sub.add_parser("attack-render", help="planning P4: related_work.md, targets_hit into the tree, based_on")
    sp.add_argument("gen_dir")
    sp.set_defaults(fn=cmd_attack_render)
    sp = sub.add_parser("attack-check", help="planning P4: attack-plan checks R01-R12")
    sp.add_argument("gen_dir")
    sp.add_argument("--idea", help="also check that this idea file's Related Work is the plan's text")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_attack_check)
    sp = sub.add_parser("pack-prefill", help="planning P5: packaging skeleton (abstract moves with sources, leaves to package)")
    sp.add_argument("gen_dir")
    sp.set_defaults(fn=cmd_pack_prefill)
    sp = sub.add_parser("pack-render", help="planning P5: Title, Short Hypothesis, Abstract, Related Work into idea_draft.json")
    sp.add_argument("gen_dir")
    sp.set_defaults(fn=cmd_pack_render)
    sp = sub.add_parser("pack-check", help="planning P5: packaging checks K01-K10")
    sp.add_argument("gen_dir")
    sp.add_argument("--idea", help="also check that this idea file carries the packaging's text")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_pack_check)
    sp = sub.add_parser("hypo-check", help="planning P1: C25-C27 alone (argument-check runs them too, with the rest)")
    sp.add_argument("gen_dir")
    sp.set_defaults(fn=cmd_check)
