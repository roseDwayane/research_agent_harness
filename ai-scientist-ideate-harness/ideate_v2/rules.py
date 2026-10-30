"""Numeric rules stated on slides 3-5, as pure functions, plus the bounded-loop evaluator.

These are contract-level re-statements used by the v2 gates and evals. The legacy tools stay authoritative for the
domain checks; where a constant is copied, its legacy source is named so drift can be checked.
"""
from __future__ import annotations

import math
import re

from .errors import IdeateError

# slide 3, A5 card; legacy it_snowball.py BACKWARD_MIN, BACKWARD_SHARE, BACKWARD_CAP, COCITE_CAP, ROUND2_GROWTH
BACKWARD_MIN, BACKWARD_SHARE, BACKWARD_CAP, COCITE_CAP = 3, 0.02, 40, 20
ROUND2_GROWTH = 0.10
# slide 5, P3 card T09; legacy references/planning/P3-decision-tree.md (T09 row)
PRIOR_ODDS = {"likely": 0.65, "possible": 0.30, "unlikely": 0.05}
WEAK_PAPERS = {"methods-caveat", "not-publishable"}
WEAK_BRANCHES = {"uninformative", "imprecise"}
# slide 5, P5 card K01-05
ABSTRACT_WORD_LIMIT = 250


def snowball_threshold(n_population: int) -> int:
    """Backward (and co-citation): cited by >= max(3, 2% of the population counted)."""
    if n_population < 0:
        raise IdeateError("IDEATE.INPUT.INVALID", "population size must be >= 0")
    return max(BACKWARD_MIN, math.ceil(BACKWARD_SHARE * n_population))


def snowball_round2_allowed(growth: float) -> bool:
    """A second snowball round only when round 1 grew the included set by >= 10%."""
    return growth >= ROUND2_GROWTH


def ready_question_target(max_num_generations: int | None) -> int:
    """recon-check: ready questions >= max(generations, 3) + 2 (legacy it_recon.target)."""
    return max(int(max_num_generations or 3), 3) + 2


def reflection_round_cap(num_reflections: int = 3) -> int:
    """B5: rounds are capped at num_reflections + 2."""
    return int(num_reflections) + 2


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def _by_id(items) -> dict:
    """decision_tree.json keeps nodes and leaves as lists of {id, ...}; evals may use {id: {...}} maps."""
    if isinstance(items, dict):
        return {k: v for k, v in items.items() if isinstance(v, dict)}
    return {x.get("id"): x for x in items or [] if isinstance(x, dict)}


def _target(branch: dict) -> str | None:
    return branch.get("next") or branch.get("leaf") or branch.get("to")


def leaf_odds(tree: dict) -> dict[str, float]:
    """Probability of reaching each leaf: branch priors (likely 0.65, possible 0.3, unlikely 0.05), normalised within
    each node, multiplied along the path from the root (the legacy it_plan.leaf_odds rule).

    Accepts decision_tree.json ({"root", "nodes": [{id, claims, branches: [{kind, prior, next | leaf}]}], "leaves":
    [{id, paper}]}) or the same with id-keyed maps and ``to`` as the branch target."""
    nodes, leaves = _by_id(tree.get("nodes")), _by_id(tree.get("leaves"))
    root = tree.get("root")
    if root not in nodes:
        raise IdeateError("IDEATE.INPUT.INVALID", f"decision tree root {root!r} is not a node")
    out: dict[str, float] = {}

    def walk(nid: str, p: float, seen: tuple) -> None:
        if nid in seen:
            raise IdeateError("IDEATE.INPUT.INVALID", f"decision tree has a cycle at {nid}")
        branches = nodes[nid].get("branches") or []
        weights = []
        for b in branches:
            if b.get("prior") not in PRIOR_ODDS:
                raise IdeateError("IDEATE.INPUT.INVALID", f"branch {b.get('kind')!r} of {nid}: prior must be one of "
                                  f"{sorted(PRIOR_ODDS)}")
            weights.append(PRIOR_ODDS[b["prior"]])
        total = sum(weights) or 1.0
        for b, w in zip(branches, weights):
            q, to = p * w / total, _target(b)
            if to in nodes:
                walk(to, q, seen + (nid,))
            elif to in leaves:
                out[to] = out.get(to, 0.0) + q
            else:
                raise IdeateError("IDEATE.INPUT.INVALID", f"branch {b.get('kind')!r} of {nid} leads to unknown {to!r}")

    walk(root, 1.0, ())
    return out


def decision_tree_findings(tree: dict, max_weak_share: float = 0.5, primary_claim: str | None = None) -> list[dict]:
    """T09 at contract level (authoritative check: legacy tree-check T09):
    - weak papers (methods-caveat, not-publishable) carry < ``max_weak_share`` of the tree;
    - no ``likely`` weak outcome of the primary claim: an uninformative/imprecise branch, or a branch straight into a
      weak leaf, on a node that tests the primary claim (nodes whose ``claims`` include it; without a primary claim,
      nodes with role ``tests``)."""
    findings = []
    nodes, leaves = _by_id(tree.get("nodes")), _by_id(tree.get("leaves"))
    odds = leaf_odds(tree)
    weak = sum(p for lid, p in odds.items() if (leaves.get(lid) or {}).get("paper") in WEAK_PAPERS)
    if weak >= max_weak_share:
        findings.append({"level": "ERROR", "code": "T09", "message": f"weak papers carry {weak:.0%} of the tree "
                         f"(must be < {max_weak_share:.0%})", "weak_share": round(weak, 4)})
    primary = primary_claim or tree.get("primary_claim")
    for nid, n in nodes.items():
        tests_primary = primary in (n.get("claims") or []) if primary else n.get("role") == "tests"
        if not tests_primary:
            continue
        for b in n.get("branches") or []:
            target_weak = (leaves.get(_target(b)) or {}).get("paper") in WEAK_PAPERS
            if b.get("prior") == "likely" and (b.get("kind") in WEAK_BRANCHES or target_weak):
                findings.append({"level": "ERROR", "code": "T09", "message": f"{nid}: the primary claim's likely "
                                 f"branch {b.get('kind')!r} is a weak outcome"})
    return findings


# ------------------------------------------------------------------------------------------------ bounded loops
def evaluate_loop(loop: dict, completed: int, observed: dict | None = None) -> dict:
    """May a declared loop run another iteration?

    ``completed`` = iterations already run; ``observed`` = measurements the bound's conditions read (growth,
    new_share, items). Returns {allowed, reason, bound, remaining}. A missing measurement a condition needs refuses
    the iteration (fail closed)."""
    if not isinstance(completed, int) or completed < 0:
        raise IdeateError("IDEATE.INPUT.INVALID", "completed must be an integer >= 0")
    observed = observed or {}
    bound = loop.get("bound") or {}
    mx = bound.get("max_iterations")
    if mx is not None and completed >= mx:
        return {"allowed": False, "reason": f"{loop['id']} reached its bound of {mx} iteration(s); "
                f"on exhaustion: {loop.get('on_exhausted')}", "bound": mx, "remaining": 0}
    for c in bound.get("conditions") or []:
        name, value = c["name"], c["value"]
        key = {"min_growth": "growth", "min_new_share": "new_share", "max_items": "items"}[name]
        if completed == 0 and name in ("min_growth", "min_new_share"):
            continue                                       # the first iteration has nothing to measure yet
        if key not in observed:
            return {"allowed": False, "reason": f"{loop['id']}: condition {name} needs observed.{key}", "bound": mx,
                    "remaining": None if mx is None else mx - completed}
        v = observed[key]
        ok = v >= value if name.startswith("min_") else v <= value
        if not ok:
            return {"allowed": False, "reason": f"{loop['id']}: {c['meaning']} (observed {key}={v})", "bound": mx,
                    "remaining": None if mx is None else mx - completed}
    note = "" if mx is not None else " (no numeric bound declared - see the loop's tbd note)"
    return {"allowed": True, "reason": f"{loop['id']}: iteration {completed + 1} allowed{note}", "bound": mx,
            "remaining": None if mx is None else mx - completed}
