"""A1 frame - the four Units that frame the literature search (rules: references/search/A1-frame.md).

  A1.p  protocol      what counts as this topic: review type, question framework + slots, search axes (OR-clusters),
                      outcomes, timeframe, eligibility criteria, completion criterion        -> step0 `protocol`
  A1.q  strategy      how to ask the databases: query variants built from the axes, anchor terms, sources, known items
                                                                                             -> step0 `queries` ... `known_items`
                      (the scope probe that fills `scope_probe` is `mcp_bridge.py probe`, the network side of A1.q)
  A1.e  evaluation    an independent reader's verdict on the protocol before any search     -> step1_protocol_evaluation.{json,md}
  A1.v  context       venues, expert domain, local-environment prose (read by Stage B, not by the search)
                                                                                             -> step0 `target_venues` ... `local_environment`
  view                step1_protocol.md (rendered from the above; never edited by hand)

Writes, each only into the fields its Unit owns (OWNERS below); a command that finds an ERROR writes nothing:
  ideate_tools.py frame set-protocol  <RD> protocol.json      A1.p
  ideate_tools.py frame set-strategy  <RD> strategy.json      A1.q   (before the search only)
  ideate_tools.py frame query-revise  <RD> revision.json      A2.c's declared revision of A1.q's queries (after the search)
  ideate_tools.py frame anchors-revise <RD> anchors.json      A2.c's declared revision of A1.q's anchor terms (after the search)
  ideate_tools.py frame set-context   <RD> context.json       A1.v
  ideate_tools.py frame eval-brief    <RD>                    A1.e: writes the reader's brief, prints its path
  ideate_tools.py frame set-evaluation <RD> evaluation.json   A1.e: stores the reader's JSON verdict as a round
Reads only:
  ideate_tools.py frame check   <RD> [--unit A1.p|A1.q|A1.e|A1.v|all] [--json]     exit 1 on any ERROR
  ideate_tools.py frame render  <RD>                          rebuilds the step1_protocol.md view
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date
from pathlib import Path

from it_common import (content_words, die, norm_title, now_iso, read_json, require_protocol, resolve_topic_file,
                       sha256_file, sha256_json, write_json, write_text)

PROTOCOL_SCHEMA = "ideate-protocol/1"
EVAL_SCHEMA = "ideate-protocol-eval/1"

# --------------------------------------------------------------------------------------------- the frozen vocabulary
# framework -> (slots in order, the anchor slot the search is about, the outcome-like slot or None).
# Source: rsrch-P2 references/framework_decision.md §4 (Richardson 1995; Kitchenham & Charters 2007; JBI; Cooke 2012;
# Denyer 2008). The slot names are the framework's own - a PCC question has no intervention to fill.
FRAMEWORKS = {
    "PICO":   (["population", "intervention", "comparison", "outcome"], "intervention", "outcome"),
    "PICOC":  (["population", "intervention", "comparison", "outcome", "context"], "intervention", "outcome"),
    "PECO":   (["population", "exposure", "comparator", "outcome"], "exposure", "outcome"),
    "PEO":    (["population", "exposure", "outcome"], "exposure", "outcome"),
    "PCC":    (["population", "concept", "context"], "concept", None),
    "SPIDER": (["sample", "phenomenon", "design", "evaluation", "research_type"], "phenomenon", "evaluation"),
    "PICo":   (["population", "phenomenon", "context"], "phenomenon", None),
    "CIMO":   (["context", "intervention", "mechanism", "outcome"], "intervention", "outcome"),
}
COMPARISON_SLOTS = {"comparison", "comparator"}
ROLES = ("search-and-eligibility", "eligibility-only", "extraction-only")
AXIS_KINDS = ("search", "anchor", "contrast", "counter", "rigor")
STRATEGIES = ("primary", "synonym-swap", "loosen", "anchor-methods", "contrast", "counter-evidence", "recent", "rigor")
DEPTH_STRATEGIES = {
    "quick": ["primary", "synonym-swap", "anchor-methods"],
    "standard": ["primary", "synonym-swap", "anchor-methods", "loosen", "contrast"],
    "deep": ["primary", "synonym-swap", "anchor-methods", "loosen", "contrast", "counter-evidence", "recent"],
}
DEPTH_AXIS_KINDS = {"quick": ["anchor"], "standard": ["anchor", "contrast"], "deep": ["anchor", "contrast", "counter"]}
MIN_TERMS = {"quick": 2, "standard": 3, "deep": 3}     # synonyms per search axis (rsrch query_construction §4: 3-8)
MAX_TERMS_WARN = 8
FLAT_WORDS = (3, 5)                                     # content words in a flat query (AND-ing backends)
MAX_QUERY_CHARS = 2000                                  # the scholar server's SearchInput.query limit (server.py); a longer
                                                        # form used to be cut at 400 characters without a word (Q22)
KNOWN_SOURCES = ("semantic_scholar", "openalex", "pubmed", "arxiv", "scopus", "ieee", "wos")
CHECK_IDS = ("E1", "E2", "E3", "E4", "E5", "E6")
LEGACY_CHECK_IDS = ("E1", "E2", "E3", "E4", "E5")      # rounds stored before E6 (2026-10-19) are judged on these
VERDICTS = ("approved", "approved-with-notes", "revision-required")
MAX_EVAL_ROUNDS = 2                                     # one forced revision, then finalize and record the doubt
DEFAULT_COMPLETION = ("every query variant has been run against every chosen source; the post-screen snowball has run; "
                      "the relevance check accepts every query (or records the weakness); every resolved known item is in "
                      "the collection or is reported missing")
OPERATOR = re.compile(r"(^|\s)(AND|OR|NOT)(\s|$)|[()\[\]]")

# Who writes which top-level key of step0_session_config.json. Anything else has no owner and is reported.
OWNERS = {
    "A1.p": ["topic", "topic_file", "depth", "timestamp", "protocol"],
    "A1.q": ["queries", "dropped_terms", "anchor_terms", "sources", "queries_history", "known_items", "scope_probe",
             "strategy_basis", "a1q_note"],
    "A1.v": ["target_venues", "expert_domain", "local_environment", "a1v_note"],
    "B6.1": ["consumed"],
}
# Tools in this module that write a field another Unit owns. `units check` refuses a tool listed here
# unless the owner's card declares it under `revised_by`.
REVISIONS = [{"tool": "cmd_query_revise", "by": "A2.c", "owner": "A1.q", "field": "queries"},
             {"tool": "cmd_add_terms", "by": "A2.c", "owner": "A1.p", "field": "protocol.axes[].terms (add only)"},
             {"tool": "cmd_retire_terms", "by": "A2.c", "owner": "A1.p", "field": "protocol.axes[].retired"},
             {"tool": "cmd_retire_terms", "by": "A2.c", "owner": "A1.q", "field": "queries[].boolean_query (re-rendered)"},
             {"tool": "cmd_anchors_revise", "by": "A2.c", "owner": "A1.q", "field": "anchor_terms"}]
PROTOCOL_KEYS = {"schema", "review_type", "reporting_standard", "purpose", "framework", "axes", "outcomes", "timeframe",
                 "languages",                       # optional: the languages screening keeps (A3.g); default ["en"]
                 "timeframe_reason", "setting", "criteria", "completion_criterion", "topic_sha256", "written_at",
                 "history", "a1p_note"}


# ----------------------------------------------------------------------------------------------------------- findings
def F(level: str, code: str, unit: str, msg: str) -> dict:
    return {"level": level, "code": code, "unit": unit, "msg": msg}


def errors(fs: list[dict]) -> list[dict]:
    return [f for f in fs if f["level"] == "ERROR"]


def _ids(xs, key="id"):
    return [x.get(key) for x in xs if isinstance(x, dict)]


def _dupes(xs) -> list:
    seen, out = set(), []
    for x in xs:
        if x in seen and x not in out:
            out.append(x)
        seen.add(x)
    return out


def framework_spec(fw: dict):
    name = fw.get("name")
    if name in FRAMEWORKS:
        return FRAMEWORKS[name]
    if name == "custom":
        slots = [s.get("slot") for s in fw.get("slots") or [] if isinstance(s, dict)]
        return slots, fw.get("anchor_slot"), fw.get("outcome_slot")
    return None


# --------------------------------------------------------------------------------------------------- A1.p protocol
def check_protocol(cfg: dict, rd: Path | None = None) -> list[dict]:
    U = "A1.p"
    fs: list[dict] = []
    for k in ("topic", "topic_file", "depth"):
        if not cfg.get(k):
            fs.append(F("ERROR", "P01", U, f"step0 has no `{k}`"))
    depth = cfg.get("depth") if cfg.get("depth") in DEPTH_STRATEGIES else "standard"
    if cfg.get("depth") and cfg.get("depth") not in DEPTH_STRATEGIES:
        fs.append(F("ERROR", "P01", U, f"depth {cfg.get('depth')!r} is not quick / standard / deep"))
    p = cfg.get("protocol")
    if not isinstance(p, dict):
        return fs + [F("ERROR", "P01", U, "step0 has no `protocol` block")]
    extra = sorted(set(p) - PROTOCOL_KEYS)
    if extra:
        fs.append(F("ERROR", "P11", U, f"protocol has keys nobody owns: {extra} (notes go in `a1p_note`)"))
    if p.get("review_type") != "scoping" or p.get("reporting_standard") != "PRISMA-ScR":
        fs.append(F("ERROR", "P01", U, "review_type must be `scoping` and reporting_standard `PRISMA-ScR`: Stage A maps a "
                                      "field to find gaps (Munn 2018), it does not pool effects"))

    # framework and slots
    fw = p.get("framework") or {}
    spec = framework_spec(fw)
    slots = {s.get("slot"): s for s in fw.get("slots") or [] if isinstance(s, dict)}
    if spec is None:
        fs.append(F("ERROR", "P02", U, f"framework {fw.get('name')!r} is not one of {sorted(FRAMEWORKS)} or `custom`"))
        names, anchor, outcome_slot = list(slots), None, None
    else:
        names, anchor, outcome_slot = spec
        if fw.get("name") == "custom":
            if len(names) < 2 or not str(fw.get("rationale", "")).strip() or anchor not in names:
                fs.append(F("ERROR", "P02", U, "a custom framework needs >= 2 slots, a rationale saying why no standard "
                                              "frame fits, and an `anchor_slot` that is one of its slots"))
        elif sorted(slots) != sorted(names):
            fs.append(F("ERROR", "P02", U, f"{fw.get('name')} has the slots {names}; the protocol lists {sorted(slots)} "
                                          "(no force-filled or missing slots)"))
    if not str(fw.get("rationale", "")).strip():
        fs.append(F("ERROR", "P02", U, "framework.rationale is empty: say which question semantics chose the frame"))
    for name, s in slots.items():
        if not str(s.get("value", "")).strip():
            fs.append(F("ERROR", "P03", U, f"slot `{name}` has no value"))
        if s.get("operational_role") not in ROLES:
            fs.append(F("ERROR", "P03", U, f"slot `{name}`: operational_role must be one of {ROLES}"))
        if not str(s.get("reason", "")).strip():
            fs.append(F("ERROR", "P03", U, f"slot `{name}` has no reason (the searchability-test outcome)"))
        if name in COMPARISON_SLOTS and s.get("operational_role") == "search-and-eligibility":
            fs.append(F("WARN", "P03", U, f"`{name}` is in the search: control arms are rarely named in titles; it is "
                                         "usually eligibility-only plus the contrast variant"))
    if anchor and anchor in slots and slots[anchor].get("operational_role") != "search-and-eligibility":
        fs.append(F("ERROR", "P04", U, f"the anchor slot `{anchor}` is left out of the search: dropping the anchor is a "
                                      "recall defect, not a searchability judgement"))
    searched = {n for n, s in slots.items() if s.get("operational_role") == "search-and-eligibility"}

    # axes
    axes = [a for a in p.get("axes") or [] if isinstance(a, dict)]
    for d in _dupes(_ids(axes)):
        fs.append(F("ERROR", "P05", U, f"axis id {d} is used twice"))
    search_axes = [a for a in axes if a.get("kind") == "search"]
    for a in axes:
        aid = a.get("id")
        if not re.fullmatch(r"C\d+", str(aid or "")):
            fs.append(F("ERROR", "P05", U, f"axis id {aid!r} must look like C1, C2, ..."))
        if a.get("kind") not in AXIS_KINDS:
            fs.append(F("ERROR", "P05", U, f"axis {aid}: kind must be one of {AXIS_KINDS}"))
        if a.get("kind") == "search" and a.get("slot") not in searched:
            fs.append(F("ERROR", "P05", U, f"search axis {aid} is tied to slot {a.get('slot')!r}, which is not a "
                                          "search-and-eligibility slot"))
        terms = a.get("terms") or []
        low = [str(t).strip().lower() for t in terms]
        if a.get("kind") == "search" and len(terms) < MIN_TERMS[depth]:
            fs.append(F("ERROR", "P05", U, f"search axis {aid} has {len(terms)} term(s); {depth} needs >= {MIN_TERMS[depth]} "
                                          "(every way the concept is written: synonyms, abbreviations, spelling variants)"))
        elif not terms:
            fs.append(F("ERROR", "P05", U, f"axis {aid} has no terms"))
        if len(terms) > MAX_TERMS_WARN:
            fs.append(F("WARN", "P05", U, f"axis {aid} has {len(terms)} terms (> {MAX_TERMS_WARN}): check none is a "
                                         "different concept"))
        for d in _dupes(low):
            fs.append(F("ERROR", "P05", U, f"axis {aid} lists the term {d!r} twice"))
        for t in terms:
            if not str(t).strip() or len(str(t).split()) > 4 or OPERATOR.search(str(t)):
                fs.append(F("ERROR", "P05", U, f"axis {aid}: term {t!r} must be 1-4 words without Boolean operators or "
                                              "brackets (the tool renders the Boolean form)"))
    if not 2 <= len(search_axes) <= 4:
        fs.append(F("ERROR", "P05", U, f"{len(search_axes)} search axes; a search needs 2-4 (fewer is imprecise, more "
                                      "over-constrains the AND chain)"))
    for n in sorted(searched):
        if not any(a.get("slot") == n for a in search_axes):
            fs.append(F("ERROR", "P05", U, f"slot `{n}` is searched but no search axis carries it"))
    for kind in DEPTH_AXIS_KINDS[depth]:
        if not any(a.get("kind") == kind for a in axes):
            fs.append(F("ERROR", "P09", U, f"{depth} needs a `{kind}` axis (see A1-frame.md, axis kinds)"))

    # outcomes
    outs = [o for o in p.get("outcomes") or [] if isinstance(o, dict)]
    out_ids = _ids(outs)
    for d in _dupes(out_ids):
        fs.append(F("ERROR", "P06", U, f"outcome id {d} is used twice"))
    for o in outs:
        if not re.fullmatch(r"O\d+", str(o.get("id") or "")) or not str(o.get("text", "")).strip():
            fs.append(F("ERROR", "P06", U, f"outcome {o.get('id')!r} needs an id like O1 and a text"))
    if outcome_slot and not outs:
        fs.append(F("ERROR", "P06", U, f"{fw.get('name')} has an outcome slot (`{outcome_slot}`): list each distinct "
                                      "outcome as O1, O2, ... so none is left unsearched or unscreened"))
    if outcome_slot and outcome_slot in searched:
        for oid in out_ids:
            if not any(a.get("kind") == "search" and a.get("outcome") == oid for a in search_axes):
                fs.append(F("ERROR", "P06", U, f"the outcome slot is searched but no search axis names {oid} "
                                              "(`outcome`: the half of the novelty claim nobody checked)"))

    # criteria
    crit = p.get("criteria") or {}
    inc = [c for c in crit.get("inclusion") or [] if isinstance(c, dict)]
    exc = [c for c in crit.get("exclusion") or [] if isinstance(c, dict)]
    if not inc or not exc:
        fs.append(F("ERROR", "P07", U, "criteria need >= 1 inclusion and >= 1 exclusion rule, written before any search"))
    for d in _dupes(_ids(inc + exc)):
        fs.append(F("ERROR", "P07", U, f"criterion id {d} is used twice"))
    known_refs = set(slots) | set(out_ids)
    for c in inc + exc:
        if not re.fullmatch(r"(IN|EX)\d+", str(c.get("id") or "")) or not str(c.get("text", "")).strip():
            fs.append(F("ERROR", "P07", U, f"criterion {c.get('id')!r} needs an id like IN1 / EX1 and a text"))
        bad = [r for r in c.get("refs") or [] if r not in known_refs]
        if bad:
            fs.append(F("ERROR", "P07", U, f"criterion {c.get('id')} refers to {bad}, which are neither slots nor outcomes"))
    inc_refs = {r for c in inc for r in c.get("refs") or []}
    all_refs = inc_refs | {r for c in exc for r in c.get("refs") or []}
    for oid in out_ids:
        if oid not in inc_refs:
            fs.append(F("ERROR", "P07", U, f"no inclusion criterion refers to {oid}: relevance is screened against every "
                                          "outcome"))
    for n, s in slots.items():
        applied = n in all_refs or (n == outcome_slot and any(o in all_refs for o in out_ids))  # O1.. are its parts
        if s.get("operational_role") == "eligibility-only" and not applied:
            fs.append(F("ERROR", "P07", U, f"slot `{n}` is eligibility-only, so a criterion must apply it"))

    # timeframe, completion, topic hash
    m = re.fullmatch(r"(\d{4})-(\d{4})", str(p.get("timeframe") or ""))
    if not m or int(m.group(1)) > int(m.group(2)) or int(m.group(2)) > date.today().year + 1:
        fs.append(F("ERROR", "P08", U, f"timeframe {p.get('timeframe')!r} must be YYYY-YYYY, start <= end"))
    if not str(p.get("timeframe_reason", "")).strip():
        fs.append(F("ERROR", "P08", U, "timeframe_reason is empty (5 years for fast ML topics; wider when the field "
                                      "rests on older standards)"))
    if not str(p.get("completion_criterion", "")).strip():
        fs.append(F("ERROR", "P08", U, "completion_criterion is empty"))
    if rd is not None and p.get("topic_sha256"):
        tf = resolve_topic_file(rd, cfg.get("topic_file"))
        cur = sha256_file(tf) if tf else None
        if cur and cur != p["topic_sha256"]:
            fs.append(F("WARN", "P10", U, "STALE: the topic file changed after A1.p was written - re-run A1.p if the "
                                         "change touches the question"))
    return fs


def as_written(protocol: dict) -> dict:
    """The protocol as A1.p wrote it: without timestamps, history, and A2.c's later term revisions (terms it added,
    terms it retired - declared revisions, logged deviations, not a new protocol)."""
    p = {k: v for k, v in (protocol or {}).items() if k not in ("written_at", "history", "topic_sha256")}
    axes = []
    for a in p.get("axes") or []:
        added = {x.get("term") for x in a.get("added") or []}
        a = {k: v for k, v in a.items() if k not in ("added", "retired")}
        a["terms"] = [t for t in a.get("terms") or [] if t not in added]
        axes.append(a)
    if axes:
        p["axes"] = axes
    return p


def protocol_content_hash(cfg: dict) -> str:
    """The protocol's decisions, without timestamps and history: what A1.q was built on."""
    return sha256_json(as_written(cfg.get("protocol") or {}))


def strategy_hash(cfg: dict) -> str:
    """What the scope probe answered: the active queries' axes and flat words, the sources and the known items."""
    qs = [{k: q.get(k) for k in ("id", "strategy", "axes", "flat_query", "year")} for q in cfg.get("queries") or []
          if q.get("status", "active") == "active"]
    return sha256_json({"queries": qs, "sources": cfg.get("sources"), "known_items": cfg.get("known_items")})


def _terms(protocol: dict) -> dict:
    """Per axis, the terms "all" stands for: A1.p's own. A term A2.c added is used only by a query that names it; a term
    A2.c retired is used by none."""
    out = {}
    for a in protocol.get("axes") or []:
        if isinstance(a, dict) and a.get("id"):
            added = {x.get("term") for x in a.get("added") or []}
            out[a["id"]] = [t for t in a.get("terms") or [] if t not in added and t not in retired_terms(a)]
    return out


def retired_terms(axis: dict) -> set:
    return {x.get("term") for x in axis.get("retired") or []}


def selected_terms(protocol: dict, q: dict) -> dict:
    """{axis_id: [terms]} the query uses, in protocol axis order; "all" means every term of the axis."""
    T = _terms(protocol)
    out = {}
    for a in protocol.get("axes") or []:
        sel = (q.get("axes") or {}).get(a.get("id"))
        if sel is None:
            continue
        out[a["id"]] = list(T.get(a["id"], [])) if sel == "all" else [t for t in sel if t not in retired_terms(a)]
    return out


def _quote(term: str) -> str:
    t = str(term).strip()
    return f'"{t}"' if (" " in t or "-" in t) else t


def render_boolean(protocol: dict, q: dict) -> str:
    parts = []
    for terms in selected_terms(protocol, q).values():
        ors = " OR ".join(_quote(t) for t in terms)
        parts.append(f"({ors})" if len(terms) > 1 else ors)
    return " AND ".join(parts)


def _render(protocol: dict, q: dict) -> dict:
    q = dict(q)
    q["boolean_query"] = render_boolean(protocol, q)
    q["query"] = str(q.get("flat_query") or "").strip()     # what the current search bridge sends; = flat_query
    q.setdefault("status", "active")
    return q


def check_strategy(cfg: dict, probe: bool = True, rd: Path | None = None) -> list[dict]:
    U = "A1.q"
    fs: list[dict] = []
    basis = (cfg.get("strategy_basis") or {}).get("protocol_sha")
    if basis and basis != protocol_content_hash(cfg):
        fs.append(F("ERROR", "Q21", U, "STALE: the protocol changed after this strategy was written - run `frame "
                                       "set-strategy` again (before the search) or `frame query-revise` (after it)"))
    p = cfg.get("protocol") or {}
    depth = cfg.get("depth") if cfg.get("depth") in DEPTH_STRATEGIES else "standard"
    axes = {a.get("id"): a for a in p.get("axes") or [] if isinstance(a, dict)}
    kind = {i: a.get("kind") for i, a in axes.items()}
    search_ids = [i for i, k in kind.items() if k == "search"]
    anchor_slot = (framework_spec(p.get("framework") or {}) or (None, None, None))[1]
    anchor_axes = {i for i in search_ids if axes[i].get("slot") == anchor_slot}
    qs = [q for q in cfg.get("queries") or [] if isinstance(q, dict)]
    active = [q for q in qs if q.get("status", "active") == "active"]
    for d in _dupes(_ids(qs)):
        fs.append(F("ERROR", "Q01", U, f"query id {d} is used twice (a revised query gets a new id; the old one is retired)"))
    primary = [q for q in active if q.get("strategy") == "primary"]
    sig_seen = {}
    for q in qs:
        qid = q.get("id")
        if q.get("strategy") not in STRATEGIES:
            fs.append(F("ERROR", "Q01", U, f"{qid}: strategy must be one of {STRATEGIES}"))
        if q.get("status", "active") not in ("active", "retired"):
            fs.append(F("ERROR", "Q01", U, f"{qid}: status must be active or retired"))
        if not str(q.get("rationale", "")).strip():
            fs.append(F("ERROR", "Q01", U, f"{qid}: rationale is empty"))
        qa = q.get("axes") or {}
        bad = [i for i in qa if i not in axes]
        if bad:
            fs.append(F("ERROR", "Q02", U, f"{qid} uses axes {bad} that the protocol does not define"))
            continue
        for i, sel in qa.items():
            if sel != "all" and (not isinstance(sel, list) or not sel or any(t not in axes[i].get("terms", []) for t in sel)):
                fs.append(F("ERROR", "Q02", U, f"{qid}: axis {i} must be \"all\" or a non-empty subset of its terms "
                                              "(new terms are added in A1.p, not here)"))
        if len(qa) < 2 and q.get("strategy") != "loosen":   # loosening a 2-axis search leaves one axis by design
            fs.append(F("ERROR", "Q19", U, f"{qid} uses {len(qa)} axis: a query ANDs >= 2 axes"))
        if q.get("status", "active") != "active":
            continue
        s_ids = {i for i in qa if kind.get(i) == "search"}
        kinds = {kind.get(i) for i in qa}
        st = q.get("strategy")
        need = {
            "primary": (s_ids == set(search_ids) and kinds == {"search"}, "uses every search axis and nothing else"),
            "synonym-swap": (s_ids == set(search_ids) and kinds == {"search"}, "uses every search axis and nothing else"),
            "loosen": (kinds == {"search"} and len(s_ids) == len(search_ids) - 1, "drops exactly one search axis"),
            "anchor-methods": ("anchor" in kinds and s_ids and not s_ids & anchor_axes,
                               "pairs an anchor axis with search axes other than the anchor slot's"),
            "contrast": ("contrast" in kinds and s_ids and not s_ids & anchor_axes,
                         "pairs a contrast axis with search axes other than the anchor slot's"),
            "counter-evidence": ("counter" in kinds and len(s_ids) >= len(search_ids) - 1,
                                 "adds a counter axis to all (or all but one) search axes"),
            "recent": (s_ids == set(search_ids) and q.get("year") == "last-12-months",
                       "uses every search axis with year = last-12-months"),
            "rigor": ("rigor" in kinds and s_ids == set(search_ids), "adds a rigor axis to every search axis"),
        }.get(st)
        if need and not need[0]:
            fs.append(F("ERROR", "Q03", U, f"{qid} is a `{st}` variant, so it {need[1]}"))
        if st == "synonym-swap" and primary:
            ps, qs_ = selected_terms(p, primary[0]), selected_terms(p, q)
            if all(sorted(ps.get(i, [])) == sorted(qs_.get(i, [])) for i in search_ids):
                fs.append(F("ERROR", "Q03", U, f"{qid} is a synonym-swap but selects the same terms as the primary"))
        sig = json.dumps({i: sorted(v) for i, v in selected_terms(p, q).items()}, sort_keys=True) + str(q.get("year"))
        if sig in sig_seen:
            fs.append(F("ERROR", "Q17", U, f"{qid} repeats {sig_seen[sig]} (same axes and terms)"))
        sig_seen[sig] = qid
        # flat form: 3-5 content words, every one taken from the query's own terms
        words = content_words(q.get("flat_query"))
        if not FLAT_WORDS[0] <= len(words) <= FLAT_WORDS[1]:
            fs.append(F("ERROR", "Q12", U, f"{qid}: flat_query has {len(words)} content words; ranking engines and the "
                                          f"AND-ing fallbacks need {FLAT_WORDS[0]}-{FLAT_WORDS[1]}"))
        toks = {t.strip("*").lower() for terms in selected_terms(p, q).values() for term in terms
                for t in re.split(r"[\s/-]+", str(term)) if t.strip("*")}
        stray = [w for w in words if not any(w.lower().startswith(t) or t.startswith(w.lower().strip("*")) for t in toks)]
        if stray:
            fs.append(F("ERROR", "Q12", U, f"{qid}: flat_query words {stray} come from none of the query's axis terms"))
        if q.get("strategy") == "anchor-methods":
            named = [t for i in qa if kind.get(i) == "anchor" for t in selected_terms(p, q).get(i, [])
                     if all(any(w.lower().startswith(x.strip("*").lower()) for w in words) for x in str(t).split())]
            if len(named) > 1:      # the AND-ing backends then want a paper naming all of them (probe: 0 hits)
                fs.append(F("ERROR", "Q12", U, f"{qid}: the flat form names {len(named)} anchors {named}; name one - the "
                                              "Boolean form carries them all"))
        if q.get("boolean_query") is not None and q.get("boolean_query") != render_boolean(p, q):
            fs.append(F("ERROR", "Q18", U, f"{qid}: boolean_query was edited by hand; it is rendered from the axes"))
        if q.get("query") is not None and q.get("query") != str(q.get("flat_query") or "").strip():
            fs.append(F("ERROR", "Q18", U, f"{qid}: `query` must equal flat_query (the search bridge sends it)"))
        n_bool = len(render_boolean(p, q))
        if n_bool > MAX_QUERY_CHARS:
            fs.append(F("ERROR", "Q22", U, f"{qid}: the Boolean form is {n_bool} characters; the scholar server takes at "
                                          f"most {MAX_QUERY_CHARS} - select term subsets and spread the axis's terms "
                                          "over several queries (every term is still asked: Q13)"))
    if len(primary) != 1:
        fs.append(F("ERROR", "Q03", U, f"{len(primary)} active primary queries; there must be exactly one"))
    have = {q.get("strategy") for q in active}
    for st in DEPTH_STRATEGIES[depth]:
        if st not in have:
            fs.append(F("ERROR", "Q11", U, f"{depth} needs a `{st}` query variant"))
    # every term of every search axis is asked somewhere, or dropped with a reason
    used = {(i, t.lower()) for q in active for i, terms in selected_terms(p, q).items() for t in terms}
    dropped = {(d.get("axis"), str(d.get("term", "")).lower()) for d in cfg.get("dropped_terms") or []
               if str(d.get("reason", "")).strip()}
    dropped |= {(i, str(t).lower()) for i in search_ids for t in retired_terms(axes[i])}   # retired by A2.c
    for i in search_ids:
        for t in axes[i].get("terms") or []:
            if (i, t.lower()) not in used and (i, t.lower()) not in dropped:
                fs.append(F("ERROR", "Q13", U, f"term {t!r} of axis {i} is in no query and not in dropped_terms"))
    at = cfg.get("anchor_terms") or []
    if not 2 <= len(at) <= 5 or any(str(x) != str(x).lower() or not str(x).strip() for x in at):
        fs.append(F("ERROR", "Q14", U, "anchor_terms: 2-5 lower-case substrings, at least one of which any on-topic paper "
                                      "contains"))
    src = cfg.get("sources") or []
    if len(src) < 2 or any(s not in KNOWN_SOURCES for s in src):
        fs.append(F("ERROR", "Q15", U, f"sources: >= 2 of {KNOWN_SOURCES}"))
    ki = [k for k in cfg.get("known_items") or [] if isinstance(k, dict)]
    if depth != "quick" and len(ki) < 2:
        fs.append(F("ERROR", "Q16", U, f"{depth} needs >= 2 known items (papers any expert expects this search to find)"))
    for k in ki:
        if not (str(k.get("title", "")).strip() or str(k.get("doi", "")).strip()) or not str(k.get("why", "")).strip():
            fs.append(F("ERROR", "Q16", U, f"known item {k!r} needs a title or DOI and a `why`"))
    searched = rd is not None and (Path(rd) / "step2_raw_papers.json").exists()
    if probe and depth != "quick":
        sp = cfg.get("scope_probe")
        if not isinstance(sp, dict):
            fs.append(F("ERROR", "Q20", U, "no scope probe: run `mcp_bridge.py probe <RD>` (or record why it was skipped)"))
        elif not searched and sp.get("strategy_sha") and sp["strategy_sha"] != strategy_hash(cfg):
            fs.append(F("ERROR", "Q20", U, "the scope probe answered a different strategy: run `mcp_bridge.py probe <RD>` again"))
        elif sp.get("skipped"):
            fs.append(F("WARN", "Q20", U, f"scope probe skipped: {sp['skipped']}"))
        else:
            kr = sp.get("known_items") or []
            miss = [k.get("ref") for k in kr if not k.get("resolved")]
            if kr and len(miss) * 2 > len(kr):
                fs.append(F("WARN", "Q20", U, f"{len(miss)}/{len(kr)} known items could not be found in any database - "
                                             f"check they exist: {miss}"))
    return fs


def match_known_items(items: list[dict], hits: list[dict]) -> list[dict]:
    """Pure: which known items appear among database hits (DOI equality, else one normalised title containing the
    other). Used by the scope probe (A1.q) and, later, by the relevance check (A2.c) against the whole collection."""
    out = []
    by_doi = {str(h.get("doi") or "").lower(): h for h in hits if h.get("doi")}
    titles = [(norm_title(h.get("title")), h) for h in hits]
    for k in items:
        ref = k.get("doi") or k.get("title")
        h = by_doi.get(str(k.get("doi") or "").lower()) if k.get("doi") else None
        if h is None and k.get("title"):
            kt = norm_title(k["title"])
            h = next((x for t, x in titles if len(kt) >= 12 and (kt in t or (len(t) >= 12 and t in kt))), None)
        out.append({"ref": ref, "resolved": h is not None, "title": (h or {}).get("title"), "doi": (h or {}).get("doi"),
                    "year": (h or {}).get("year")})
    return out


# ----------------------------------------------------------------------------------------------------- A1.v context
def check_context(cfg: dict) -> list[dict]:
    U = "A1.v"
    fs = []
    tv = cfg.get("target_venues") or []
    if not 2 <= len(tv) <= 4:
        fs.append(F("ERROR", "V01", U, "target_venues: 2-4 plausible venues"))
    if not str(cfg.get("expert_domain", "")).strip():
        fs.append(F("ERROR", "V01", U, "expert_domain is empty"))
    le = cfg.get("local_environment")
    if not isinstance(le, dict) or not any(le.get(k) is not None for k in ("artefacts", "cached_data", "packages_present",
                                                                            "packages_missing")):
        fs.append(F("ERROR", "V01", U, "local_environment needs artefacts / cached_data / packages_present / "
                                      "packages_missing (empty lists are fine: say you looked)"))
    return fs


# -------------------------------------------------------------------------------------------------- A1.e evaluation
def protocol_hash(cfg: dict) -> str:
    """What the reader evaluated: the protocol and the strategy, without timestamps and rendered fields."""
    p = as_written(cfg.get("protocol") or {})
    # The queries as A1.q wrote them, whatever their status: a declared A2.c revision after the search (a retired
    # query plus its replacement) is a logged deviation, not a change to the protocol that was evaluated.
    qs = [{k: v for k, v in q.items() if k not in ("boolean_query", "query", "status", "retired_by", "retire_reason")}
          for q in cfg.get("queries") or [] if q.get("added_by") != "A2.c"]
    return sha256_json({"protocol": p, "queries": qs, "anchor_terms": a1q_anchor_terms(cfg),   # anchors-revise: a deviation
                        "sources": cfg.get("sources"), "known_items": cfg.get("known_items"),
                        "dropped_terms": cfg.get("dropped_terms")})


def eval_path(rd: Path) -> Path:
    return Path(rd) / "step1_protocol_evaluation.json"


def check_round(r: dict, criteria: set | None = None) -> list[dict]:
    """One stored round. `checks` records which checks its brief asked for (a round stored before E6 has none: E1-E5).
    `criteria` (the protocol's IN / EX ids), when given, is what an E6 finding must name."""
    U = "A1.e"
    fs = []
    if r.get("verdict") not in VERDICTS:
        fs.append(F("ERROR", "E02", U, f"verdict must be one of {VERDICTS}"))
    finds = [f for f in r.get("findings") or [] if isinstance(f, dict)]
    asked = tuple(r.get("checks") or LEGACY_CHECK_IDS)
    for c in asked:
        if not any(f.get("check") == c for f in finds):
            fs.append(F("ERROR", "E02", U, f"no finding for check {c} (a passing check is a finding with result pass)"))
    for f in finds:
        if f.get("check") not in asked or f.get("result") not in ("pass", "fail", "note"):
            fs.append(F("ERROR", "E02", U, f"finding {f!r}: check in {asked}, result pass / fail / note"))
        if f.get("check") == "E6" and f.get("result") != "pass":
            if not str(f.get("criterion") or "").strip() or not str(f.get("alt_reading") or "").strip() \
                    or not str(f.get("word") or "").strip():
                fs.append(F("ERROR", "E06", U, "an E6 note / fail names the `criterion` (IN / EX id), the question's "
                                              "`word` it rests on and the other plausible reading (`alt_reading`)"))
            elif criteria is not None and f["criterion"] not in criteria:
                fs.append(F("ERROR", "E06", U, f"E6 names {f['criterion']!r}, which is not a criterion of the protocol"))
        if not str(f.get("evidence", "")).strip():
            fs.append(F("ERROR", "E02", U, f"finding for {f.get('check')} quotes no evidence"))
        if f.get("result") == "fail" and (f.get("severity") not in ("blocking", "improvable")
                                          or f.get("fix_target") not in ("A1.p", "A1.q")):
            fs.append(F("ERROR", "E03", U, f"failed {f.get('check')}: severity blocking / improvable and fix_target "
                                          "A1.p / A1.q are required"))
    if r.get("verdict") == "approved" and any(f.get("result") == "fail" for f in finds):
        fs.append(F("ERROR", "E05", U, "verdict approved with failed checks"))
    if r.get("verdict") != "revision-required" and any(f.get("severity") == "blocking" for f in finds):
        fs.append(F("ERROR", "E05", U, "a blocking finding needs verdict revision-required"))
    return fs


def criteria_ids(cfg: dict) -> set:
    crit = (cfg.get("protocol") or {}).get("criteria") or {}
    return {c.get("id") for c in (crit.get("inclusion") or []) + (crit.get("exclusion") or []) if isinstance(c, dict)}


def _phrase(s) -> str:
    """Case, punctuation (hyphens too) and spacing ignored - the same normalisation as A3's quote check."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%.+]|_", " ", str(s or "").lower())).strip()


def soft_criteria(rd: Path, cfg: dict | None = None) -> dict:
    """{criterion id: {word, alt_reading, round, linked}} - the **exclusion** criteria the final A1.e round names under
    E6 (note or fail): they rest on one reading of a word in the topic. A3 keeps a paper that violates only these, meets
    them under the other reading, and would be included without them, as borderline (§14-§15 of PLAN_ideate_search).
    An inclusion criterion named under E6 stays a note for the protocol author: inclusion criteria define the topic, and
    failing them is the most common exclusion. `linked` = the other criteria whose text holds the same word (after
    normalisation): A3 reads the word the same way there, or the soft reading would change nothing (q032: IN1 and EX1
    both turn on "low-resource language"). {} when there is no evaluation, or it predates E6."""
    path = eval_path(rd)
    if not path.exists():
        return {}
    ev = read_json(path)
    rounds = ev.get("rounds") or []
    n = (ev.get("final") or {}).get("round")
    r = next((x for x in rounds if x.get("round") == n), rounds[-1] if rounds else None)
    out = {}
    for f in (r or {}).get("findings") or []:
        if isinstance(f, dict) and f.get("check") == "E6" and f.get("result") in ("note", "fail") \
                and str(f.get("criterion") or "").startswith("EX"):
            out[f["criterion"]] = {"word": f.get("word"), "alt_reading": f.get("alt_reading"), "round": r.get("round")}
    if out:
        if cfg is None:
            cfg = load_cfg(rd) if cfg_path(rd).exists() else {}
        crit = (cfg.get("protocol") or {}).get("criteria") or {}
        allc = [c for c in (crit.get("inclusion") or []) + (crit.get("exclusion") or []) if isinstance(c, dict)]
        for cid, s in out.items():
            w = _phrase(s.get("word"))
            s["linked"] = sorted(c["id"] for c in allc if w and c.get("id") != cid and c.get("id") not in out
                                 and f" {w} " in f" {_phrase(c.get('text'))} ")
    return out


def check_evaluation(cfg: dict, rd: Path) -> list[dict]:
    U = "A1.e"
    path = eval_path(rd)
    if not path.exists():
        return [F("ERROR", "E01", U, "no step1_protocol_evaluation.json: run `frame eval-brief`, give the brief to a "
                                     "subagent, store its answer with `frame set-evaluation`")]
    ev = read_json(path)
    rounds = ev.get("rounds") or []
    if not rounds:
        return [F("ERROR", "E01", U, "the evaluation has no rounds")]
    fs = check_round(rounds[-1], criteria_ids(cfg))
    if rounds[-1].get("protocol_sha") != protocol_hash(cfg):
        fs.append(F("ERROR", "E01", U, "STALE: the protocol or the strategy changed after the last evaluation round - "
                                       "evaluate again"))
    fin = ev.get("final") or {}
    if fin.get("status") not in ("approved", "approved-with-notes", "accepted-with-doubts"):
        fs.append(F("ERROR", "E04", U, "revision required: fix the findings in A1.p / A1.q, then run round "
                                       f"{len(rounds) + 1} (`frame eval-brief`)"))
    return fs


# ------------------------------------------------------------------------------------------------------ ownership
def check_ownership(cfg: dict) -> list[dict]:
    owned = {k for ks in OWNERS.values() for k in ks}
    extra = sorted(k for k in cfg if k not in owned)
    return [F("WARN", "X01", "step0", f"step0 keys with no owner: {extra} (a note goes in the writer's own `*_note`)")] \
        if extra else []


def run_checks(cfg: dict, rd: Path, unit: str = "all") -> list[dict]:
    require_protocol(cfg, rd)
    fs = []
    if unit in ("all", "A1.p"):
        fs += check_protocol(cfg, rd)
    if unit in ("all", "A1.q"):
        fs += check_strategy(cfg, rd=rd)
    if unit in ("all", "A1.v"):
        fs += check_context(cfg)
    if unit in ("all", "A1.e"):
        fs += check_evaluation(cfg, rd)
    if unit == "all":
        fs += check_ownership(cfg)
    return fs


def search_gate(cfg: dict, rd: Path) -> list[dict]:
    """What A2 requires of A1 before it may search: A1.p, A1.q and A1.e pass (A1.v serves Stage B and is not
    required)."""
    require_protocol(cfg, rd)
    return errors(check_protocol(cfg, rd) + check_strategy(cfg, rd=rd) + check_evaluation(cfg, rd))


# ------------------------------------------------------------------------------------------------------------- io
def cfg_path(rd: Path) -> Path:
    return Path(rd) / "step0_session_config.json"


def load_cfg(rd: Path) -> dict:
    p = cfg_path(rd)
    return read_json(p) if p.exists() else {}


def print_findings(fs: list[dict]) -> None:
    for f in fs:
        print(f"  {f['level']:<5} {f['code']} [{f['unit']}] {f['msg']}")


def refuse_if_errors(fs: list[dict], what: str) -> None:
    errs = errors(fs)
    print_findings(fs)
    if errs:
        die(f"{len(errs)} error(s) in {what}; nothing was written", 2)


def _only_keys(data: dict, allowed: set, what: str) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        die(f"{what} has keys this Unit does not own: {extra}", 2)


# ------------------------------------------------------------------------------------------------------- commands
def _cmd_set_protocol(a):
    rd = Path(a.research_dir)
    new = read_json(Path(a.input_json))
    _only_keys(new, {"topic", "topic_file", "depth", "protocol"}, "protocol.json")
    cfg = load_cfg(rd)
    before = copy.deepcopy(cfg.get("protocol"))
    out = {**cfg, **{k: new[k] for k in ("topic", "topic_file", "depth") if k in new}}
    p = dict(new.get("protocol") or {})
    p["schema"] = PROTOCOL_SCHEMA
    p.setdefault("review_type", "scoping")
    p.setdefault("reporting_standard", "PRISMA-ScR")
    p.setdefault("purpose", "gap-identification")
    p.setdefault("completion_criterion", DEFAULT_COMPLETION)
    tf = resolve_topic_file(rd, out.get("topic_file"))
    p["topic_sha256"] = sha256_file(tf) if tf else None
    p["written_at"] = now_iso()
    p["history"] = list((before or {}).get("history") or []) + [
        {"at": p["written_at"], "by": "A1.p", "action": "set" if before is None else "reset", "note": a.note or ""}]
    out["protocol"] = p
    out.setdefault("timestamp", p["written_at"])
    out.pop("pico", None)                    # the protocol's framework slots are the one description of the question
    fs = check_protocol(out, rd)
    if tf is None:
        fs.append(F("WARN", "P10", "A1.p", f"topic file {out.get('topic_file')!r} not found; its hash is not recorded"))
    refuse_if_errors(fs, "the protocol")
    if (rd / "step2_raw_papers.json").exists():
        print("  note: the search has already run - a protocol change after it makes every screening score stale")
    write_json(cfg_path(rd), out)
    render_view(rd, out)
    print(f"A1.p: protocol written ({p['framework'].get('name')}, {sum(1 for x in p['axes'] if x.get('kind') == 'search')} "
          f"search axes, {len(p.get('outcomes') or [])} outcomes) -> step0_session_config.json")


def _cmd_set_strategy(a):
    rd = Path(a.research_dir)
    new = read_json(Path(a.input_json))
    _only_keys(new, {"queries", "dropped_terms", "anchor_terms", "sources", "known_items", "a1q_note"}, "strategy.json")
    cfg = load_cfg(rd)
    if "protocol" not in cfg:
        die("no protocol in step0: run `frame set-protocol` (A1.p) first", 2)
    if errors(check_protocol(cfg, rd)):
        die("the protocol has errors (`frame check --unit A1.p`); fix A1.p first", 2)
    if (rd / "step2_raw_papers.json").exists():
        if _same_strategy(cfg, new):
            print("A1.q: the strategy is the one in step0 - nothing written, the Unit re-recorded")
            return
        die("the search has run: change a query with `frame query-revise` (it retires the old one and keeps its papers)", 2)
    out = dict(cfg)
    out["queries"] = [_render(cfg["protocol"], q) for q in new.get("queries") or []]
    for k in ("dropped_terms", "anchor_terms", "sources", "known_items", "a1q_note"):
        if k in new:
            out[k] = new[k]
    out["strategy_basis"] = {"protocol_sha": protocol_content_hash(cfg), "at": now_iso()}
    sp = cfg.get("scope_probe")
    if not (isinstance(sp, dict) and sp.get("strategy_sha") == strategy_hash(out)):
        out.pop("scope_probe", None)        # the probe answered another strategy; an unchanged one keeps it
    entry = {"at": now_iso(), "by": "A1.q", "action": "set",
             "queries": [{"id": q["id"], "query": q["query"], "boolean_query": q["boolean_query"]} for q in out["queries"]]}
    hist = list(cfg.get("queries_history") or [])
    same = hist and hist[-1].get("action") == "set" and hist[-1].get("queries") == entry["queries"] and \
        all(cfg.get(k) == out.get(k) for k in ("dropped_terms", "anchor_terms", "sources", "known_items"))
    out["queries_history"] = hist if same else hist + [entry]   # the same strategy again (a resumed run) adds nothing
    refuse_if_errors(check_strategy(out, probe=False), "the strategy")
    write_json(cfg_path(rd), out)
    render_view(rd, out)
    print(f"A1.q: {len(out['queries'])} query variants written -> step0_session_config.json")
    if out.get("depth") != "quick" and "scope_probe" not in out:
        print("  next: `mcp_bridge.py probe <RD>` (scope probe + known-item lookup), then A1.e")


def a1q_anchor_terms(cfg: dict) -> list:
    """The anchor terms as A1.q wrote them, whatever A2.c's `anchors-revise` made of them since."""
    for h in cfg.get("queries_history") or []:
        if h.get("action") == "anchors":
            return h.get("from") or []
    return cfg.get("anchor_terms") or []


def _same_strategy(cfg: dict, new: dict) -> bool:
    """`new` is exactly the strategy A1.q wrote into step0 (its own queries and anchors, whatever A2.c revised since)."""
    keys = ("id", "strategy", "axes", "flat_query", "year", "sources")
    mine = [{k: q.get(k) for k in keys} for q in cfg.get("queries") or [] if q.get("added_by") != "A2.c"]
    a1q = {**cfg, "anchor_terms": a1q_anchor_terms(cfg)}
    return mine == [{k: q.get(k) for k in keys} for q in new.get("queries") or []] and \
        all(a1q.get(k) == new.get(k) for k in ("dropped_terms", "anchor_terms", "sources", "known_items") if k in new)


def _cmd_anchors_revise(a):
    """A2.c's declared revision of A1.q's anchor terms after the search (§15 G2): a protocol revised after the search
    can leave anchors of the reading it rejected (q386: "spontaneous", "in-the-wild"). Logged in queries_history; A2.m
    reads anchor_terms, so the merge is stale until `mcp_bridge.py merge <RD>` recomputes anchor_match (offline)."""
    rd = Path(a.research_dir)
    rev = read_json(Path(a.input_json))
    _only_keys(rev, {"anchor_terms", "reason", "round"}, "anchors.json")
    if not str(rev.get("reason", "")).strip():
        die("anchors-revise needs a `reason` (it goes into the strategy's deviation log)", 2)
    cfg = load_cfg(rd)
    if not (rd / "step2_raw_papers.json").exists():
        die("the search has not run: change the anchors with `frame set-strategy` (A1.q)", 2)
    new = [str(t) for t in rev.get("anchor_terms") or []]
    if new == list(cfg.get("anchor_terms") or []):
        die("these are the anchor terms already in step0", 2)
    out = dict(cfg)
    out["anchor_terms"] = new
    out["queries_history"] = list(cfg.get("queries_history") or []) + [
        {"at": now_iso(), "by": "A2.c", "action": "anchors", "round": rev.get("round"),
         "from": list(cfg.get("anchor_terms") or []), "to": new, "reason": rev["reason"]}]
    refuse_if_errors([f for f in check_strategy(out, probe=False) if f["code"] == "Q14"], "the anchor terms")
    write_json(cfg_path(rd), out)
    render_view(rd, out)
    print(f"A2.c: anchor_terms {cfg.get('anchor_terms')} -> {new}; A2.m is stale: `mcp_bridge.py merge <RD>` "
          "recomputes anchor_match, then `search-check` and a new A2.c round")


def _cmd_query_revise(a):
    """A2.c's declared revision of A1.q's queries: retire one query, add its replacement under a new id. The input may
    be a list of such revisions, applied together and checked once - terms added with `add-terms` for several queries
    are asked only when all their replacements are in."""
    rd = Path(a.research_dir)
    raw = read_json(Path(a.input_json))
    revs = raw if isinstance(raw, list) else [raw]
    cfg = load_cfg(rd)
    out = dict(cfg)
    qs = [dict(q) for q in cfg.get("queries") or []]
    hist = list(cfg.get("queries_history") or [])
    done = []
    for rev in revs:
        _only_keys(rev, {"retire", "add", "reason", "round"}, "revision.json")
        if not str(rev.get("reason", "")).strip():
            die("a revision needs a reason (it goes into the protocol's deviation log)", 2)
        old = next((q for q in qs if q.get("id") == rev.get("retire")), None)
        if old is None or old.get("status", "active") != "active":
            die(f"no active query {rev.get('retire')!r} to retire", 2)
        add = _render(cfg["protocol"], rev.get("add") or {})
        add["added_by"] = "A2.c"
        old.update({"status": "retired", "retired_by": add.get("id"), "retire_reason": rev["reason"]})
        qs.append(add)
        hist.append({"at": now_iso(), "by": "A2.c", "action": "revise", "round": rev.get("round"), "retired": old["id"],
                     "added": {"id": add.get("id"), "query": add["query"], "boolean_query": add["boolean_query"]},
                     "reason": rev["reason"]})
        done.append((old["id"], add["id"]))
    out["queries"] = qs
    out["strategy_basis"] = {"protocol_sha": protocol_content_hash(cfg), "at": now_iso(), "by": "A2.c"}
    out["queries_history"] = hist
    refuse_if_errors(check_strategy(out, probe=False), "the revised strategy")
    write_json(cfg_path(rd), out)
    render_view(rd, out)
    for o, n in done:
        print(f"A2.c: {o} retired, {n} added")
    print(f"  -> run `mcp_bridge.py search <RD> --only {','.join(n for _, n in done)}`")


def _cmd_add_terms(a):
    """A2.c's declared revision of A1.p: add synonyms an axis was missing (found by the relevance check's vocabulary
    feedback or a missing known item). Add only; every added term must then be asked by a query (`query-revise`)."""
    rd = Path(a.research_dir)
    rev = read_json(Path(a.input_json))
    _only_keys(rev, {"axis", "terms", "reason", "evidence", "round"}, "add-terms.json")
    if not str(rev.get("reason", "")).strip() or not rev.get("terms"):
        die("add-terms needs `terms` and a `reason` (it goes into the protocol's deviation log)", 2)
    cfg = load_cfg(rd)
    p = copy.deepcopy(cfg.get("protocol") or {})
    ax = next((x for x in p.get("axes") or [] if x.get("id") == rev.get("axis")), None)
    if ax is None or ax.get("kind") != "search":
        die(f"{rev.get('axis')!r} is not a search axis of the protocol", 2)
    have = {str(t).lower() for t in ax.get("terms") or []}
    new = [t for t in rev["terms"] if str(t).lower() not in have]
    if not new:
        die("every term is already in the axis", 2)
    at = now_iso()
    ax["terms"] = list(ax.get("terms") or []) + new
    ax["added"] = list(ax.get("added") or []) + [{"term": t, "by": "A2.c", "reason": rev["reason"],
                                                  "evidence": rev.get("evidence") or [], "round": rev.get("round"),
                                                  "at": at} for t in new]
    p["history"] = list(p.get("history") or []) + [{"at": at, "by": "A2.c", "action": "add-terms",
                                                    "note": f"{rev['axis']} += {new}: {rev['reason']}"}]
    out = {**cfg, "protocol": p}
    refuse_if_errors(check_protocol(out, rd), "the protocol with the added terms")
    write_json(cfg_path(rd), out)
    render_view(rd, out)
    print(f"A2.c: {rev['axis']} += {new} -> now ask them: `frame query-revise` with a query that names them")


def _cmd_retire_terms(a):
    """A2.c's declared revision of A1.p: stop asking terms that bring in mostly what the protocol does not mean (the
    relevance check's term_pull). The term stays in the protocol as written, marked retired; queries stop rendering
    it, so the instances of the queries that used it are stale and run again."""
    rd = Path(a.research_dir)
    rev = read_json(Path(a.input_json))
    _only_keys(rev, {"axis", "terms", "reason", "evidence", "round"}, "retire-terms.json")
    if not str(rev.get("reason", "")).strip() or not rev.get("terms"):
        die("retire-terms needs `terms` and a `reason` (it goes into the protocol's deviation log)", 2)
    cfg = load_cfg(rd)
    p = copy.deepcopy(cfg.get("protocol") or {})
    ax = next((x for x in p.get("axes") or [] if x.get("id") == rev.get("axis")), None)
    if ax is None or ax.get("kind") not in ("search", "contrast"):
        die(f"{rev.get('axis')!r} is not a search or contrast axis of the protocol (an anchor term is a named method: "
            "revise the anchor query instead)", 2)
    gone = retired_terms(ax)
    bad = [t for t in rev["terms"] if t not in (ax.get("terms") or []) or t in gone]
    if bad:
        die(f"not active terms of {ax['id']}: {bad}", 2)
    if not [t for t in ax.get("terms") or [] if t not in gone and t not in rev["terms"]]:
        die(f"{ax['id']} would have no term left", 2)
    at = now_iso()
    ax["retired"] = list(ax.get("retired") or []) + [{"term": t, "by": "A2.c", "reason": rev["reason"],
                                                      "evidence": rev.get("evidence") or [], "round": rev.get("round"),
                                                      "at": at} for t in rev["terms"]]
    empty = [q["id"] for q in cfg.get("queries") or [] if q.get("status", "active") == "active"
             and ax["id"] in (q.get("axes") or {}) and not selected_terms(p, q).get(ax["id"])]
    if empty:
        die(f"{empty} would ask {ax['id']} with no term: `frame query-revise` them first", 2)
    flat = [q["id"] for q in cfg.get("queries") or [] if q.get("status", "active") == "active"
            and any(str(t).lower().replace("*", "") in str(q.get("flat_query") or "").lower() for t in rev["terms"])]
    if flat:
        die(f"the flat form of {flat} names {rev['terms']} (Semantic Scholar would still be asked it): "
            "`frame query-revise` them first", 2)
    p["history"] = list(p.get("history") or []) + [{"at": at, "by": "A2.c", "action": "retire-terms",
                                                    "note": f"{rev['axis']} -= {rev['terms']}: {rev['reason']}"}]
    out = {**cfg, "protocol": p}
    refuse_if_errors(check_protocol(out, rd), "the protocol with the retired terms")
    out["queries"] = [_render(p, q) if q.get("status", "active") == "active" else q for q in cfg.get("queries") or []]
    refuse_if_errors(check_strategy(out, probe=False), "the queries without the retired terms (`frame query-revise` "
                     "the ones named first)")
    write_json(cfg_path(rd), out)
    render_view(rd, out)
    hit = [q["id"] for q in cfg.get("queries") or [] if q.get("status", "active") == "active" and ax["id"] in (q.get("axes") or {})]
    print(f"A2.c: {rev['axis']} -= {rev['terms']} -> run again: `mcp_bridge.py search <RD> --only {','.join(hit)}`")


def _cmd_set_context(a):
    rd = Path(a.research_dir)
    new = read_json(Path(a.input_json))
    _only_keys(new, {"target_venues", "expert_domain", "local_environment", "a1v_note"}, "context.json")
    if not isinstance(new.get("local_environment", {}), dict) or not isinstance(new.get("target_venues", []), list):
        die("context.json: local_environment is an object {artefacts, cached_data, packages_present, packages_missing} "
            "and target_venues a list of 2-4 venues", 2)
    cfg = load_cfg(rd)
    out = dict(cfg)
    for k in ("target_venues", "expert_domain", "a1v_note"):
        if k in new:
            out[k] = new[k]
    if "local_environment" in new:
        le = {k: v for k, v in (new["local_environment"] or {}).items() if k != "probe"}
        if "probe" in (cfg.get("local_environment") or {}):
            le["probe"] = cfg["local_environment"]["probe"]      # B0's field: kept, never written here
        out["local_environment"] = le
    refuse_if_errors(check_context(out), "the context")
    write_json(cfg_path(rd), out)
    print("A1.v: target_venues, expert_domain, local_environment written -> step0_session_config.json")


BRIEF = """# A1.e - protocol evaluation brief (round {round})

You are the independent reviewer Kitchenham §5.5 asks for: you check this literature-search protocol for internal
consistency **before any search result exists**. You do not rewrite it; you return a verdict and findings.

Read these two files and nothing else (no other folder, no network):

- the topic: `{topic}`
- the protocol (rendered from step0_session_config.json): `{view}`

Checks - give each one at least one finding (`result: pass` is a finding):

- **E1 search follows from the question.** Is every concept the topic is about represented by its own search axis,
  each axis expanded across synonyms, abbreviations and spelling variants? Was any slot left out of the search for the
  wrong reason (the anchor concept must be searched; a comparison arm is usually a screening criterion)? Any axis about
  a concept the topic never raises (scope creep)? Do the chosen sources cover where this literature is published?
- **E2 criteria follow from the question.** Do the inclusion and exclusion criteria follow from the slots and outcomes,
  is every eligibility-only slot applied by a criterion, and are the criteria concrete enough to apply the same way to
  400 abstracts?
- **E3 the frame fits.** Does the chosen framework match what the topic semantically asks (an applied method is an
  intervention, an exposure-outcome relation is PECO, an inventory is PCC), with no invented slot?
- **E4 recall risks.** Missing synonyms or spellings, a timeframe that cuts off the field's baselines, an anchor tool
  any expert would expect but not named, known items that look implausible or missing?
- **E5 completeness.** Anything empty, vague or `(TBD)`; is the completion criterion concrete?
- **E6 readings.** Does a criterion rest on one reading of a word in the topic that has another plausible reading
  ("elderly": aged 65 or over, or frail at any age)? For each such criterion, a finding with `result: note`
  (or `fail` if the protocol's reading is the less likely one) naming the `criterion`, the topic's `word` and the
  other reading (`alt_reading`). An exclusion criterion you name becomes *soft* in screening: a paper that violates
  only soft criteria, and would otherwise be included, is kept as borderline. An inclusion criterion you name stays a
  note for the protocol author. Name only readings that would change which papers belong; no such criterion: one
  finding `E6 pass`.

Severity for a failed check: `improvable` = fixed by editing one component; `blocking` = the question itself is
misframed (wrong framework or wrong anchor). `fix_target`: `A1.p` (protocol: frame, slots, axes, outcomes, criteria,
timeframe) or `A1.q` (strategy: query variants, anchor terms, sources, known items).

Return exactly one JSON object, saved verbatim:

```json
{{"verdict": "approved | approved-with-notes | revision-required",
  "summary": "two sentences",
  "model": "the model you are",
  "findings": [{{"check": "E1", "result": "pass | fail | note", "severity": "improvable | blocking (fail only)",
                "fix_target": "A1.p | A1.q (fail only)", "evidence": "quote the protocol line", "fix": "what to change"}},
               {{"check": "E6", "result": "note", "criterion": "EX1", "word": "elderly",
                "alt_reading": "frail patients at any age, not an age cut-off", "evidence": "EX1 participants under 65"}}]}}
```

`approved` has no failed check; a `blocking` finding means `revision-required`.
{previous}"""


def _cmd_eval_brief(a):
    rd = Path(a.research_dir)
    cfg = load_cfg(rd)
    if errors(check_protocol(cfg, rd) + check_strategy(cfg)):
        die("A1.p / A1.q still have errors (`frame check`); the reader evaluates a protocol that passes its own checks", 2)
    view = render_view(rd, cfg)
    ev = read_json(eval_path(rd)) if eval_path(rd).exists() else {"rounds": []}
    n = len(ev["rounds"]) + 1
    if n > MAX_EVAL_ROUNDS:
        die(f"{MAX_EVAL_ROUNDS} rounds already ran; the evaluation is final", 2)
    prev = ""
    if ev["rounds"]:
        last = ev["rounds"][-1]
        prev = ("\nThis is round 2: the protocol was revised after round 1. Judge the protocol as it is now; the round-1 "
                "findings were:\n\n" + "\n".join(f"- {f['check']} {f['result']}: {f.get('evidence', '')}"
                                                for f in last.get("findings", []) if f.get("result") != "pass") + "\n")
    tf = resolve_topic_file(rd, cfg.get("topic_file"))
    brief = BRIEF.format(round=n, topic=tf or cfg.get("topic_file"), view=view.resolve(), previous=prev)
    path = rd / "_state" / "A1e" / f"brief_r{n}.md"
    write_text(path, brief)
    print(path)


def _cmd_set_evaluation(a):
    rd = Path(a.research_dir)
    cfg = load_cfg(rd)
    require_protocol(cfg, rd)                      # the reader judged a protocol: there must be one, and a brief for it
    if not list((rd / "_state" / "A1e").glob("brief_r*.md")):
        die("no brief: run `frame eval-brief` first; the reader answers that brief", 2)
    r = read_json(Path(a.input_json))
    _only_keys(r, {"verdict", "summary", "model", "findings"}, "evaluation.json")
    ev = read_json(eval_path(rd)) if eval_path(rd).exists() else {"schema": EVAL_SCHEMA, "rounds": []}
    last = ev["rounds"][-1] if ev["rounds"] else None
    if last and last.get("protocol_sha") == protocol_hash(cfg) and all(last.get(k) == r.get(k) for k in
                                                                      ("verdict", "summary", "model", "findings")):
        ev["rounds"].pop()                       # the same reply stored again (a resumed run): the same round, not a new one
    n = len(ev["rounds"]) + 1
    if n > MAX_EVAL_ROUNDS:
        die(f"{MAX_EVAL_ROUNDS} rounds already ran; the evaluation is final", 2)
    if n == 2 and ev["rounds"][-1].get("protocol_sha") == protocol_hash(cfg):
        die("round 2 needs a revised protocol: nothing changed since round 1", 2)
    rnd = {"round": n, "at": now_iso(), "evaluator": "subagent", "protocol_sha": protocol_hash(cfg),
           "checks": list(CHECK_IDS), **r}
    refuse_if_errors(check_round(rnd, criteria_ids(cfg)), "the evaluation")
    ev["rounds"].append(rnd)
    if r["verdict"] in ("approved", "approved-with-notes"):
        ev["final"] = {"status": r["verdict"], "round": n, "unresolved": []}
    elif n >= MAX_EVAL_ROUNDS:
        ev["final"] = {"status": "accepted-with-doubts", "round": n,
                       "unresolved": [f for f in r["findings"] if f.get("result") == "fail"]}
    else:
        ev["final"] = {"status": "pending-revision", "round": n, "unresolved": []}
    write_json(eval_path(rd), ev)
    write_text(rd / "step1_protocol_evaluation.md", render_evaluation_md(ev))
    render_view(rd, cfg)
    print(f"A1.e: round {n} stored - {r['verdict']} -> final status {ev['final']['status']}")
    if ev["final"]["status"] == "pending-revision":
        print("  fix the failed findings in A1.p / A1.q (one forced revision), then `frame eval-brief` for round 2")
    elif ev["final"]["status"] == "accepted-with-doubts":
        print("  round 2 still asks for revision: the doubts are recorded as caveats and the search goes ahead")


def cmd_check(a):
    rd = Path(a.research_dir)
    cfg = load_cfg(rd)
    if not cfg:
        die(f"{cfg_path(rd)} not found", 2)
    fs = run_checks(cfg, rd, a.unit)
    if a.json:
        print(json.dumps(fs, indent=2, ensure_ascii=False))
    else:
        print_findings(fs)
        n = len(errors(fs))
        print("OK" if not n else f"{n} error(s)")
    raise SystemExit(1 if errors(fs) else 0)


def cmd_render(a):
    print(render_view(Path(a.research_dir), load_cfg(Path(a.research_dir))))


# ------------------------------------------------------------------------------------------------------------ views
def render_evaluation_md(ev: dict) -> str:
    L = ["# Protocol evaluation (A1.e)", "", f"Final status: **{(ev.get('final') or {}).get('status')}**", ""]
    for r in ev.get("rounds") or []:
        L += [f"## Round {r['round']} — {r.get('verdict')} ({r.get('at')}, {r.get('model') or 'model not recorded'})", "",
              str(r.get("summary") or ""), "", "| Check | Result | Severity | Fix target | Evidence | Fix |", "|---|---|---|---|---|---|"]
        L += [f"| {f.get('check')} | {f.get('result')} | {f.get('severity', '')} | {f.get('fix_target', '')} | "
              f"{str(f.get('evidence', '')).replace('|', '/')} | "
              + (f"soft {f.get('criterion')}: \"{f.get('word')}\" may mean {f.get('alt_reading')}".replace('|', '/')
                 if f.get('check') == 'E6' and f.get('result') != 'pass' else str(f.get('fix', '')).replace('|', '/'))
              + " |" for f in r.get("findings") or []]
        L.append("")
    un = (ev.get("final") or {}).get("unresolved") or []
    if un:
        L += ["## Unresolved (recorded as caveats)", ""] + [f"- {f['check']}: {f.get('evidence')}" for f in un]
    return "\n".join(L) + "\n"


def render_view(rd: Path, cfg: dict) -> Path:
    """step1_protocol.md: the protocol as a PRISMA-ScR-style document. A view: rebuilt, never edited."""
    rd = Path(rd)
    path = rd / "step1_protocol.md"
    p = cfg.get("protocol") or {}
    fw = p.get("framework") or {}
    L = ["<!-- generated by `ideate_tools.py frame render` from step0_session_config.json - do not edit -->",
         f"# Search protocol — {cfg.get('topic')}", "",
         f"Review type: **{p.get('review_type')}** · reporting standard: **{p.get('reporting_standard')}** · purpose: "
         f"{p.get('purpose')} · depth: {cfg.get('depth')}  ", f"Topic file: `{cfg.get('topic_file')}` "
         f"(sha256 {str(p.get('topic_sha256'))[:12]}) · written {p.get('written_at')}", "",
         f"## 0. Question framework — {fw.get('name')}", "", str(fw.get("rationale") or ""), ""]
    if fw.get("alternative"):
        L += [f"Alternative considered: {fw['alternative']}", ""]
    L += ["| Slot | Value | Operational role | Searchability test |", "|---|---|---|---|"]
    L += [f"| {s.get('slot')} | {s.get('value')} | {s.get('operational_role')} | {s.get('reason')} |"
          for s in fw.get("slots") or []]
    L += ["", "## 1. Outcomes", ""]
    L += [f"- **{o.get('id')}** {o.get('text')}" for o in p.get("outcomes") or []] or ["- (none in this frame)"]
    L += ["", "## 2. Search axes", "", "| Axis | Kind | Slot / outcome | Terms (OR) |", "|---|---|---|---|"]
    L += [f"| {x.get('id')} {x.get('name', '')} | {x.get('kind')} | {x.get('slot') or ''} {x.get('outcome') or ''} | "
          f"{' · '.join(x.get('terms') or [])} |" for x in p.get("axes") or []]
    L += ["", f"Timeframe: **{p.get('timeframe')}** — {p.get('timeframe_reason')}  ", f"Setting: {p.get('setting')}", "",
          "## 3. Eligibility criteria", "", "**Inclusion**", ""]
    L += [f"- {c.get('id')} {c.get('text')} *(→ {', '.join(c.get('refs') or [])})*" for c in (p.get("criteria") or {}).get("inclusion") or []]
    L += ["", "**Exclusion**", ""]
    L += [f"- {c.get('id')} {c.get('text')} *(→ {', '.join(c.get('refs') or [])})*" for c in (p.get("criteria") or {}).get("exclusion") or []]
    L += ["", "## 4. Search strategy", "", f"Sources: {', '.join(cfg.get('sources') or [])} · anchor terms: "
          f"{', '.join(cfg.get('anchor_terms') or [])}", "", "| ID | Variant | Status | Boolean (PubMed / Scopus / IEEE / WoS) | Flat (ranking engines) |",
          "|---|---|---|---|---|"]
    L += [f"| {q.get('id')} | {q.get('strategy')} | {q.get('status', 'active')} | `{q.get('boolean_query')}` | `{q.get('flat_query')}` |"
          for q in cfg.get("queries") or []]
    if cfg.get("dropped_terms"):
        L += ["", "Dropped terms: " + "; ".join(f"{d.get('axis')} {d.get('term')!r} ({d.get('reason')})" for d in cfg["dropped_terms"])]
    L += ["", "Known items (an expert expects the search to find these):", ""]
    L += [f"- {k.get('title') or k.get('doi')} — {k.get('why')}" for k in cfg.get("known_items") or []] or ["- (none)"]
    sp = cfg.get("scope_probe")
    if isinstance(sp, dict):
        L += ["", f"Scope probe ({sp.get('at')}): " + (f"skipped — {sp['skipped']}" if sp.get("skipped") else
              f"rough yield {sp.get('rough_yield')}; known items found {sum(1 for k in sp.get('known_items') or [] if k.get('resolved'))}"
              f"/{len(sp.get('known_items') or [])}")]
    L += ["", "## 5. Completion criterion", "", str(p.get("completion_criterion") or ""), "",
          "## 6. Screening, extraction, synthesis", "",
          "Fixed by the skill, not per topic: screening = `references/search/A3-screen.md` (evidence first; relevance and "
          "quality judged, impact computed; composite ≥ 3.00); "
          "extraction = the methods matrix (`knowledge-passes.md`, Pass M); synthesis = the Point / Line / Plane / Body passes.", ""]
    ev = read_json(eval_path(rd)) if eval_path(rd).exists() else None
    L += ["## 7. Evaluation (A1.e)", "", f"Status: {(ev or {}).get('final', {}).get('status', 'not evaluated yet')} — see "
          "`step1_protocol_evaluation.md`", "", "## 8. Deviation log", "",
          "Every change after the protocol was first written, from `protocol.history` and `queries_history`; A3's criteria "
          "amendments are listed in `step3_screening_results.md`.", "",
          "| When | Unit | Change | Reason |", "|---|---|---|---|"]
    dev = [(h.get("at"), h.get("by"), h.get("action"), h.get("note", "")) for h in (p.get("history") or [])[1:]]
    dev += [(h.get("at"), h.get("by"), f"retired {h.get('retired')}, added {(h.get('added') or {}).get('id')}", h.get("reason"))
            for h in cfg.get("queries_history") or [] if h.get("action") == "revise"]
    L += [f"| {w} | {u} | {c} | {r} |" for w, u, c, r in sorted(dev, key=lambda x: str(x[0]))] or ["| — | — | (none) | — |"]
    write_text(path, "\n".join(L) + "\n")
    return path


# --------------------------------------------------------------------------------------------------------- CLI glue
# ------------------------------------------------------------------------------------------------ the scope probe
def _year_filter(timeframe) -> str | None:
    m = re.findall(r"\d{4}", str(timeframe or ""))
    return f"{m[0]}-{m[1]}" if len(m) >= 2 else (m[0] if m else None)


def openalex_total(query: str, year: str | None, mailto: str, rd: Path | None = None, fetch=None) -> int | None:
    """How many works OpenAlex has for a query (meta.count) - the order-of-magnitude yield a scope probe reports."""
    import urllib.parse
    from it_common import http_json
    fetch = fetch or http_json
    m = re.findall(r"\d{4}", str(year or ""))
    filt = f"&filter=publication_year:{m[0]}-{m[1]}" if len(m) >= 2 else ""
    url = (f"https://api.openalex.org/works?search={urllib.parse.quote(query)}{filt}&per-page=1&select=id"
           f"&mailto={urllib.parse.quote(mailto)}")
    try:
        return int((fetch(url, rd).get("meta") or {}).get("count"))
    except Exception:  # noqa: BLE001 - the probe records a missing total, it does not fail
        return None


async def _probe(server, cfg: dict, rd: Path, mailto: str, fetch=None, queries=None, limit: int = 10, sleep=None) -> dict:
    """A1.q's scope probe (references/search/A1-frame.md#a1q): 1-3 trial queries for an order-of-magnitude yield and
    a lookup of every known item, before the search. Nothing here enters the collection: raw answers go to
    _state/probes/A1q/, the summary to step0 `scope_probe`."""
    import asyncio
    sleep = sleep or asyncio.sleep
    rd = Path(rd)
    active = [q for q in cfg.get("queries") or [] if q.get("status", "active") == "active"]
    if queries:
        trial = [q for q in active if q["id"] in queries]
    else:
        order = ("primary", "loosen", "anchor-methods")
        trial = [next(q for q in active if q.get("strategy") == st) for st in order if any(q.get("strategy") == st for q in active)]
    trial = trial[:3]
    year = _year_filter((cfg.get("protocol") or {}).get("timeframe"))
    out_dir = rd / "_state" / "probes" / "A1q"
    summary = {"at": now_iso(), "limit": limit, "strategy_sha": strategy_hash(cfg), "queries": []}
    try:
        if server is None:
            raise RuntimeError("no scholar server")
        for q in trial:
            r = await server.call("scholar_search", {"query": q["query"], "sources": cfg.get("sources") or ["openalex"],
                                                     "limit": limit, "year": year, "found_via": f"probe:{q['id']}"})
            write_json(out_dir / f"{q['id']}.json", r)
            per = {}
            for p_ in r.get("papers") or []:
                for src in p_.get("sources_found_in") or []:
                    per[src] = per.get(src, 0) + 1
            summary["queries"].append({"id": q["id"], "flat_query": q["query"], "hits_per_source": per,
                                       "source_errors": r.get("source_errors") or {},
                                       "openalex_total": openalex_total(q["query"], year, mailto, rd, fetch)})
            await sleep(3)
        hits = []
        for k in cfg.get("known_items") or []:
            query = str(k.get("title") or k.get("doi"))[:400] if k.get("doi") else " ".join(str(k.get("title")).split()[:14])
            query = " ".join(re.sub(r"[?!+:;\"()\[\]]", " ", query).split())   # a '?' or '+' in a title broke the lookup
            r = await server.call("scholar_search", {"query": query, "sources": ["openalex"], "limit": 5,
                                                     "found_via": "probe:known-item"})
            hits += r.get("papers") or []
            await sleep(1)
        write_json(out_dir / "known_items.json", hits)
        summary["known_items"] = match_known_items(cfg.get("known_items") or [], hits)
    except Exception as e:  # noqa: BLE001 - a dead service is recorded, not fatal (degraded path)
        summary = {"at": summary["at"], "strategy_sha": summary["strategy_sha"],
                   "skipped": f"scholar server unavailable: {str(e)[:200]}"}
    tot = [f"{q['id']}~{q['openalex_total']:,}" for q in summary.get("queries", []) if q.get("openalex_total") is not None]
    if tot:
        summary["rough_yield"] = "OpenAlex totals in the timeframe: " + ", ".join(tot)
    cfg = load_cfg(rd)
    cfg["scope_probe"] = summary
    write_json(cfg_path(rd), cfg)
    return summary


async def run_probe(server, cfg: dict, rd: Path, mailto: str, fetch=None, queries=None, limit: int = 10, sleep=None) -> dict:
    """The probe as A1.q's network side: A1.q is done once it has answered and A1.q's checks pass."""
    from it_ledger import degraded_codes, run_unit
    with run_unit(rd, "A1.q", check=_unit_errors(rd, "A1.q"), degraded=lambda: degraded_codes(rd, "A1.q")):
        return await _probe(server, cfg, rd, mailto, fetch=fetch, queries=queries, limit=limit, sleep=sleep)

# ---------------------------------------------------------------------------------------------- ledger boundaries
# Each command is a Unit's boundary: it records `begin`, and `done` once the Unit's own checks pass (it_ledger).
def _unit_errors(rd, unit):
    return lambda: errors(run_checks(load_cfg(Path(rd)), Path(rd), unit))


def cmd_set_protocol(a):
    from it_ledger import run_unit
    with run_unit(a.research_dir, "A1.p", check=_unit_errors(a.research_dir, "A1.p")):
        _cmd_set_protocol(a)


def cmd_set_strategy(a):
    from it_ledger import run_unit                 # done once the probe has answered (standard, deep)
    with run_unit(a.research_dir, "A1.q", check=_unit_errors(a.research_dir, "A1.q"),
                  degraded=lambda: __import__("it_ledger").degraded_codes(a.research_dir, "A1.q")):
        _cmd_set_strategy(a)


def cmd_set_context(a):
    from it_ledger import run_unit
    with run_unit(a.research_dir, "A1.v", check=_unit_errors(a.research_dir, "A1.v")):
        _cmd_set_context(a)


def cmd_eval_brief(a):
    from it_ledger import begin
    _cmd_eval_brief(a)
    begin(a.research_dir, "A1.e")                  # the subagent reads the brief; set-evaluation closes the Unit


def cmd_set_evaluation(a):
    from it_ledger import _begin_event, _events, begin, done, pending
    rd = a.research_dir
    if _begin_event(_events(Path(rd)), "A1.e", "-")[1] is None:
        begin(rd, "A1.e")
    try:
        _cmd_set_evaluation(a)
    except BaseException as e:  # noqa: BLE001 - a refusal is recorded, then propagates
        __import__("it_ledger").fail(rd, "A1.e", f"{type(e).__name__}: {str(e)[:160]}")
        raise
    errs = _unit_errors(rd, "A1.e")()
    if errs:
        pending(rd, "A1.e", f"{errs[0]['code']}: {errs[0]['msg'][:160]}")
    else:
        done(rd, "A1.e", degraded=__import__("it_ledger").degraded_codes(rd, "A1.e"))


def cmd_query_revise(a):
    from it_ledger import note
    _cmd_query_revise(a)
    note(a.research_dir, "A2.c", "revise", target="A1.q", field="queries", input=str(a.input_json))


def cmd_add_terms(a):
    from it_ledger import note
    _cmd_add_terms(a)
    note(a.research_dir, "A2.c", "revise", target="A1.p", field="protocol.axes[].terms", input=str(a.input_json))


def cmd_retire_terms(a):
    from it_ledger import note
    _cmd_retire_terms(a)
    note(a.research_dir, "A2.c", "revise", target="A1.p", field="protocol.axes[].retired", input=str(a.input_json))


def cmd_anchors_revise(a):
    from it_ledger import note
    _cmd_anchors_revise(a)
    note(a.research_dir, "A2.c", "revise", target="A1.q", field="anchor_terms", input=str(a.input_json))


def add_parsers(sub) -> None:
    fp = sub.add_parser("frame", help="A1 frame: protocol, strategy, evaluation, context (references/search/A1-frame.md)")
    fsub = fp.add_subparsers(dest="frame_cmd", required=True)
    for name, fn in (("set-protocol", cmd_set_protocol), ("set-strategy", cmd_set_strategy),
                     ("query-revise", cmd_query_revise), ("add-terms", cmd_add_terms), ("retire-terms", cmd_retire_terms),
                     ("anchors-revise", cmd_anchors_revise),
                     ("set-context", cmd_set_context),
                     ("set-evaluation", cmd_set_evaluation)):
        sp = fsub.add_parser(name)
        sp.add_argument("research_dir")
        sp.add_argument("input_json")
        if name == "set-protocol":
            sp.add_argument("--note", default="", help="why the protocol is (re)written; goes into protocol.history")
        sp.set_defaults(fn=fn)
    sp = fsub.add_parser("eval-brief")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_eval_brief)
    sp = fsub.add_parser("check")
    sp.add_argument("research_dir")
    sp.add_argument("--unit", default="all", choices=["all", "A1.p", "A1.q", "A1.e", "A1.v"])
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_check)
    sp = fsub.add_parser("render")
    sp.add_argument("research_dir")
    sp.set_defaults(fn=cmd_render)
