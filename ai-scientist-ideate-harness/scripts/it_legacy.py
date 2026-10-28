"""Legacy output format - the fields the archived engine (archived/scholar_research, folders 10_Research/<session>/)
wrote into the files this pipeline also writes, kept so that a reader of the old files can read the new ones.

  step0_session_config.json   session_id, topic_original, topic_slug, current_step, pico{}, source_urls, field_type,
                              engine{}
  step2_raw_papers.json       session_id; search_summary.{snowball_additions, final_count, sources, queries,
                              hub_papers, clusters, source_failures}; per paper pmc_id, references, cited_by,
                              is_seed_paper, language, venue_type, volume, issue, pages, arxiv_primary_class,
                              citation_network{}
  step3_shortlist.json        the same paper fields, screening.{category, exclusion_reason, no_abstract},
                              manually_included; session_id, screening_timestamp, screening_config.{threshold,
                              borderline_threshold}, summary.{total_screened, borderline, inclusion_rate,
                              manually_included}
  step7_gaps.json             session_id, weights, summary{}; per gap rank, composite and the archived gap object
  step3_screening_all.json    a file of its own (A3 writes it beside the shortlist: screening_all): every candidate
                              with its decision, the criteria and the tier names - the archived ScreeningRecord

`augment(path, data)` is called by every JSON writer (it_common.write_json, write_json_stable, ideate_tools.write_json)
and adds these fields beside the pipeline's own. Rules:
  - nothing the pipeline wrote is removed, renamed or overwritten; a field both engines name (topic, queries,
    papers[].screening.tier, ...) stays the pipeline's;
  - a field only the archived engine has is recomputed on every write from the document and from files upstream of
    it, so it never goes stale and never makes a Unit read a file written after it (the ledger's staleness stays as it
    was); session_id, engine and screening_timestamp are pinned once set, as the archived engine pinned them;
  - a value this pipeline does not record at that step takes the archived schema's own default (None, [], 0, False).
    The raw collection's bibliographic fields and its citation network come from the merge's OpenAlex enrichment
    (it_search.openalex_batch: biblio, language, type, ids.pmcid, referenced_works restricted to the collection),
    the shortlist's network from A3.b's reference lists over every candidate.

The step0 keys are a view owned by no Unit (LEGACY_STEP0_KEYS): the ledger and the ownership check leave them out.
The markdown views get the archived front matter and sections from the *_md functions, called by their renderers;
step6_sota_review.md and step8_journal_recommendations.md are the model's, and their rules carry the archived layout.

`check(rd)` (CLI: `it_legacy.py check <research_dir>`) reports, file by file, what a research folder lacks of the
archived format (JSON_SPEC, MD_SPEC) and of the sections the rules fix for two files the archived engine did not write
(gen_k/step8_hypothesis.md and the prescriptive Body, as the legacy skill's runs write them). A model-written file's
gap is a WARN, a code-written file's a FAIL.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from it_common import read_json, resolve_topic_file

LEGACY_STEP0_KEYS = ("session_id", "topic_original", "topic_slug", "current_step", "pico", "source_urls", "field_type",
                     "engine")
LEGACY_PAPER_KEYS = ("pmc_id", "references", "cited_by", "is_seed_paper", "language", "venue_type", "volume", "issue",
                     "pages", "arxiv_primary_class", "citation_network")
HUB_IN_DEGREE = 3                          # archived config.SearchConfig.hub_in_degree
GAP_WEIGHTS = {"severity": 0.4, "novelty": 0.3, "feasibility": 0.3}    # it_collide.composite
INCLUDED_FLOOR = 3.5                       # it_screen.tier_of: tiers 1-3 start at 3.5, tier 4 (3.00-3.49) is borderline
# the archived engine's step numbers and the file that shows a step has run (current_step = the highest present)
STEP_FILES = ((2, "step2_raw_papers.json"), (3, "step3_shortlist.json"), (4, "step4_references.bib"),
              (5, "step5_full_text/_access_log.md"), (6, "step6_sota_review.md"), (7, "step7_gaps.json"))
STOPWORDS = set("a an the of for and or in on with to from by via using based towards toward into at as is are be its "
                "their this that these those study analysis approach method methods review systematic new novel effect "
                "effects evidence data model models".split())       # archived steps/s2_search.py
VENUE_TYPES = {"journal": "journal", "conference": "conference", "repository": "preprint", "preprint": "preprint"}
# the archived search_summary.sources always counted these four (0 for one not searched or down)
ARCHIVED_SOURCES = ("semantic_scholar", "openalex", "pubmed", "arxiv")
# archived schemas/paper.py Paper: the defaults of the fields a record may lack (a snowball record has no
# semantic_scholar_id, for one)
ARCHIVED_PAPER_DEFAULTS = {"authors": [], "year": None, "journal": None, "doi": None, "url": None, "abstract": None,
                           "citation_count": None, "sources_found_in": [], "semantic_scholar_id": None,
                           "openalex_id": None, "pubmed_id": None, "pmc_id": None, "arxiv_id": None, "found_via": "",
                           "volume": None, "issue": None, "pages": None, "arxiv_primary_class": None}


def augment(path, data):
    """`data` with the archived engine's fields of the file `path` names; any other file is returned as it is."""
    fn = WRITERS.get(Path(path).name)
    if fn is None or not isinstance(data, dict):
        return data
    return fn(data, Path(path).parent)


# ------------------------------------------------------------------------------------------------------- helpers
def _j(rd: Path, rel: str):
    p = Path(rd) / rel
    try:
        return read_json(p) if p.is_file() else None
    except ValueError:
        return None


def _old(rd: Path, rel: str) -> dict:
    d = _j(rd, rel)
    return d if isinstance(d, dict) else {}


def slugify(text: str, max_len: int = 40) -> str:
    """The archived utils.slugify: lowercase, hyphens, ascii-only, at most max_len characters."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    text = re.sub(r"-{2,}", "-", text)
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text or "topic"


def _title_tokens(title: str | None) -> set[str]:
    t = unicodedata.normalize("NFKD", title or "").lower()
    t = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t)).strip()
    return {w for w in t.split() if len(w) > 2}


def session_id_of(cfg: dict) -> str:
    """YYYYMMDD of the session's first write (archived session.make_session_id); pinned once in step0."""
    if isinstance(cfg.get("session_id"), str) and cfg["session_id"]:
        return cfg["session_id"]
    for ts in (cfg.get("timestamp"), (cfg.get("protocol") or {}).get("written_at")):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(ts or ""))
        if m:
            return "".join(m.groups())
    return datetime.now().astimezone().strftime("%Y%m%d")


def _session_id(rd: Path) -> str:
    return session_id_of(_old(rd, "step0_session_config.json"))


def _engine_version() -> str:
    pp = Path(__file__).resolve().parent.parent / "pyproject.toml"
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pp.read_text(encoding="utf-8")) if pp.is_file() else None
    return f"ai-scientist-ideate-harness {m.group(1)}" if m else "ai-scientist-ideate-harness"


# --------------------------------------------------------------------------------------------------------- step0
def _topic_text(rd: Path, cfg: dict) -> str:
    tf = resolve_topic_file(rd, cfg.get("topic_file"))
    try:
        return tf.read_text(encoding="utf-8") if tf else ""
    except OSError:
        return ""


def _pico(cfg: dict) -> dict:
    """The protocol's framework slots in the archived PICO shape: population, intervention (or exposure / concept /
    phenomenon), comparison, outcome; setting is the context slot, else the protocol's setting."""
    p = cfg.get("protocol") or {}
    slots = {s.get("slot"): s.get("value") or "" for s in (p.get("framework") or {}).get("slots") or [] if isinstance(s, dict)}

    def pick(*names):
        return next((slots[n] for n in names if slots.get(n)), "")
    outcome = pick("outcome", "evaluation") or "; ".join(o.get("text", "") for o in p.get("outcomes") or [] if isinstance(o, dict))
    return {"population": pick("population", "sample", "participants"),
            "intervention": pick("intervention", "exposure", "concept", "phenomenon"),
            "comparison": pick("comparison", "comparator"),
            "outcome": outcome,
            "setting": pick("context") or str(p.get("setting") or ""),
            "timeframe": str(p.get("timeframe") or "")}


def _field_type(cfg: dict) -> str:
    """The archived field_type switched PubMed on (biomedical) or off (cs_engineering); read back from the sources."""
    src = set(cfg.get("sources") or [])
    if "pubmed" in src:
        return "biomedical"
    if src & {"arxiv", "ieee"}:
        return "cs_engineering"
    return "other"


def current_step(rd: Path) -> int:
    rd = Path(rd)
    step = 1 if (_old(rd, "step0_session_config.json").get("protocol")) else 0
    for n, rel in STEP_FILES:
        if (rd / rel).exists():
            step = max(step, n)
    if any(rd.glob("gen_*/step8_hypothesis.md")):
        step = 8
    return step


def session_config(cfg: dict, rd: Path) -> dict:
    out = dict(cfg)
    text = _topic_text(rd, cfg)
    m = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    original = m.group(1) if m else str(cfg.get("topic") or "")
    old_engine = out.get("engine") if isinstance(out.get("engine"), dict) else {}
    model = os.environ.get("IDEATE_LLM_MODEL", "").strip()
    try:
        temperature = float(os.environ.get("IDEATE_LLM_TEMPERATURE", "1.0"))
    except ValueError:
        temperature = 1.0
    engine = old_engine if old_engine.get("llm_model") not in (None, "", "unrecorded") else {
        "version": _engine_version(),
        # the model the harness ran the Units with (it exports IDEATE_LLM_MODEL); claude -p sets no temperature, so
        # the API default applies (1.0, the only value extended thinking allows)
        "llm_model": model or "unrecorded", "llm_temperature": temperature}
    out.update({
        "session_id": session_id_of(cfg),
        "topic_original": original,
        "topic_slug": slugify(original),
        "current_step": current_step(rd),
        # the protocol's view; a topic framed before protocols keeps its own pico block (the readers' fallback)
        "pico": _pico(cfg) if cfg.get("protocol") or not isinstance(cfg.get("pico"), dict) else cfg["pico"],
        "source_urls": list(dict.fromkeys(re.findall(r"https?://[^\s)>\]]+", text))),
        "field_type": _field_type(cfg),
        "engine": engine,
    })
    return out


# --------------------------------------------------------------------------------------------------------- papers
def network(papers: list[dict], refs: dict[str, list[str]]) -> tuple[dict, list[dict]]:
    """The archived Phase 4: references inside the collection (OpenAlex work ids -> paper ids), cited_by, degrees, hubs
    (in-degree >= 3) and clusters (connected components of >= 2 papers, largest first, named cluster_A, ...)."""
    by_oa = {p.get("openalex_id"): p["id"] for p in papers if p.get("openalex_id") and p.get("id")}
    out = {p["id"]: {"references": [], "cited_by": []} for p in papers if p.get("id")}
    for pid, ws in refs.items():
        if pid not in out:
            continue
        out[pid]["references"] = sorted({by_oa[w] for w in ws or [] if w in by_oa and by_oa[w] != pid})
    for pid, n in out.items():
        for t in n["references"]:
            out[t]["cited_by"].append(pid)
    for n in out.values():
        n["cited_by"] = sorted(set(n["cited_by"]))
        n["citation_network"] = {"in_degree": len(n["cited_by"]), "out_degree": len(n["references"]),
                                 "is_hub": len(n["cited_by"]) >= HUB_IN_DEGREE, "cluster": None}
    adj = defaultdict(set)
    for pid, n in out.items():
        for r in n["references"]:
            adj[pid].add(r)
            adj[r].add(pid)
    seen, comps = set(), []
    for p in papers:
        pid = p.get("id")
        if pid in seen or pid not in adj:
            continue
        stack, comp = [pid], []
        seen.add(pid)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in sorted(adj[x]):
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        if len(comp) >= 2:
            comps.append(sorted(comp))
    comps.sort(key=lambda c: (-len(c), c[0]))
    title = {p["id"]: p.get("title") for p in papers if p.get("id")}
    clusters = []
    for i, comp in enumerate(comps):
        name = f"cluster_{chr(ord('A') + i)}" if i < 26 else f"cluster_{i}"
        words = Counter(t for x in comp for t in _title_tokens(title.get(x)) if t not in STOPWORDS)
        top = [w for w, _ in sorted(words.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
        for x in comp:
            out[x]["citation_network"]["cluster"] = name
        clusters.append({"name": name, "paper_ids": comp, "theme": " / ".join(top) if top else "connected component"})
    return out, clusters


def _paper(p: dict, net: dict, extra: dict | None = None) -> dict:
    """One record with the archived Paper fields: the pipeline's own values first, then what `net` and `extra` know,
    then the archived defaults."""
    q = dict(p)
    n = net.get(p.get("id")) or {}
    x = extra or {}
    defaults = {**ARCHIVED_PAPER_DEFAULTS, "language": x.get("language"), "venue_type": x.get("venue_type"),
                "is_seed_paper": bool(x.get("is_seed_paper"))}
    for k, v in defaults.items():
        if k not in p:
            q[k] = list(v) if isinstance(v, list) else v
    # the record's own lists (a snowball record's cited_by, the raw file's network a shortlist record carries) and the
    # network's, joined; the degrees are counted from them, so a row never shows edges its lists do not have
    for k in ("references", "cited_by"):
        own = list(p.get(k) or [])
        q[k] = own + sorted(set(n.get(k) or []) - set(map(str, own)))  # the record's own order kept, the network's added
    cn = dict(n.get("citation_network") or {"cluster": None})
    cn.update({"in_degree": len(q["cited_by"]), "out_degree": len(q["references"]),
               "is_hub": len(q["cited_by"]) >= HUB_IN_DEGREE})
    q["citation_network"] = {k: cn.get(k) for k in ("in_degree", "out_degree", "is_hub", "cluster")}
    return q


def raw_papers(doc: dict, rd: Path) -> dict:
    out = dict(doc)
    papers = [p for p in doc.get("papers") or [] if isinstance(p, dict)]
    # the merge's OpenAlex enrichment keeps each paper's references inside the collection (refs_in_collection), as
    # the archived Phase 4 drew them from referenced_works; a record without them has no outgoing edge
    refs = {p["id"]: p.get("refs_in_collection") or p.get("refs") for p in papers if p.get("id")}
    net, clusters = network(papers, {k: v for k, v in refs.items() if v})
    out["papers"] = [_paper(p, net) for p in papers]
    # from the document alone (and the pinned session id): an unchanged collection gives an unchanged file
    s = dict(doc.get("search_summary") or {})
    snow = sum(1 for p in papers if p.get("found_via") == "snowball")
    found = Counter(src for p in papers for src in p.get("sources_found_in") or [])
    # per query id, each paper once: a superseded instance ("Q5@<hash>", kept after a re-run) counts for its query
    queries = Counter(q for p in papers
                      for q in {str(x).split("@")[0] for x in (p.get("found_by") or [p.get("found_via")]) if x})
    qids = [str(i.get("file") or "").split("@")[0] for i in s.get("instances") or [] if isinstance(i, dict)]
    qids = [q for q in qids if re.fullmatch(r"Q\d+", q)]
    failures = []
    for c in s.get("caveats") or []:
        mm = re.match(r"^(\S+) failed on (\S+?): (.*)$", str(c.get("text") or "")) if c.get("code") == "source-failed" else None
        if mm:
            failures.append(f"{mm.group(1)}/{mm.group(2)}: {mm.group(3)}")
    s.update({
        "snowball_additions": snow,
        "final_count": len(papers),
        "sources": {k: found.get(k, 0) for k in list(dict.fromkeys([*ARCHIVED_SOURCES, *(s.get("identification") or {}),
                                                                    *found]))},
        "queries": {**{q: queries.get(q, 0) for q in list(dict.fromkeys([*qids, *queries])) if q != "snowball"},
                    "snowball": snow},
        "hub_papers": [p["id"] for p in out["papers"] if p["citation_network"]["is_hub"]],
        "clusters": clusters,
        "source_failures": failures,
    })
    out["search_summary"] = s
    out["session_id"] = _session_id(rd)
    return out


def _candidate_network(rd: Path) -> tuple[dict, list[dict], dict]:
    """The citation network of every candidate (raw + snowball) from A3.b's reference lists, and per paper what A3.b
    and A5 know (language, venue type, snowball seed)."""
    raw = [p for p in (_old(rd, "step2_raw_papers.json").get("papers") or []) if isinstance(p, dict)]
    snow_doc = _old(rd, "step2b_snowball_papers.json")
    snow = [p for p in snow_doc.get("papers") or [] if isinstance(p, dict)]
    bib = _old(rd, "step3_bibliometrics.json").get("papers") or {}
    cands = {p["id"]: p for p in raw + snow if p.get("id")}
    for pid, b in bib.items():
        if pid in cands and b.get("openalex_id") and not cands[pid].get("openalex_id"):
            cands[pid] = {**cands[pid], "openalex_id": b["openalex_id"]}
    net, clusters = network(list(cands.values()), {pid: b.get("refs") for pid, b in bib.items()})
    seeds = set()
    for r in snow_doc.get("rounds") or []:
        for way in ("forward", "similar"):
            seeds |= set(((r.get("status") or {}).get(way) or {}).get("seeds") or [])
    extra = {pid: {"language": b.get("language"),
                   "venue_type": VENUE_TYPES.get(((b.get("venue") or {}).get("type") or "").lower()),
                   "is_seed_paper": pid in seeds} for pid, b in bib.items()}
    for pid in seeds - set(extra):
        extra[pid] = {"is_seed_paper": True}
    return net, clusters, extra


def shortlist(doc: dict, rd: Path) -> dict:
    out = dict(doc)
    net, _, extra = _candidate_network(rd)
    papers = []
    for p in doc.get("papers") or []:
        if not isinstance(p, dict):
            continue
        q = _paper(p, net, extra.get(p.get("id")))
        s = dict(p.get("screening") or {})
        s.setdefault("category", "borderline" if s.get("tier") == 4 else "included")
        s.setdefault("exclusion_reason", None)
        s.setdefault("no_abstract", p.get("has_abstract") is False)
        q["screening"] = s
        q.setdefault("manually_included", s.get("decided_by") == "human")
        papers.append(q)
    out["papers"] = papers
    cfg = dict(doc.get("screening_config") or {})
    cfg.setdefault("threshold", INCLUDED_FLOOR)
    cfg.setdefault("borderline_threshold", cfg.get("include_at", 3.0))
    out["screening_config"] = cfg
    sm = dict(doc.get("summary") or {})
    total = sm.get("screened", len(papers))
    inc = sm.get("included", len(papers))
    sm.setdefault("total_screened", total)
    sm.setdefault("borderline", sum(1 for p in papers if p["screening"]["category"] == "borderline"))
    sm.setdefault("inclusion_rate", f"{round(100 * inc / total) if total else 0}%")
    sm.setdefault("manually_included", sum(1 for p in papers if p["manually_included"]))
    out["summary"] = sm
    out["session_id"] = _session_id(rd)
    out["screening_timestamp"] = (doc.get("screening_timestamp") or _old(rd, "step3_shortlist.json").get("screening_timestamp")
                                  or datetime.now().astimezone().isoformat(timespec="seconds"))
    return out


def _stage(code: str, gate_codes) -> str:
    if code in gate_codes:
        return "gate"
    return {"DUP": "duplicate", "HUMAN": "human", "SCORE": "score", "FLOOR": "score", "X-REC": "criteria-title"}.get(code,
                                                                                                                   "criteria")


def screening_all(rd: Path, cfg: dict, out: dict, excluded: list, scores: dict, tier_names: dict, gate_codes) -> dict:
    """step3_screening_all.json - the archived engine's ScreeningRecord: every candidate with its screening
    decision (included, borderline = tier 4, excluded), the criteria and the tier names, sorted by composite.

    `out` is the shortlist A3 is writing, `excluded` it_screen's (paper, screening or None, code, why) tuples. A paper
    excluded before it was scored (the gate, a criterion, a duplicate) has relevance, quality and composite null: this
    pipeline applies the criteria first and scores only what passes them (the archived engine scored every paper).
    citation_key and access_level are left out (A4.k's and A6.c's parts of the shortlist, written after A3)."""
    rd = Path(rd)
    net, _, extra = _candidate_network(rd)
    impact = {pid: b.get("impact") for pid, b in (_old(rd, "step3_bibliometrics.json").get("papers") or {}).items()}
    entries = {e.get("id"): e for e in (scores or {}).get("scores") or [] if isinstance(e, dict)}
    rows = [{k: v for k, v in p.items() if k not in ("citation_key", "access_level")}
            for p in shortlist(out, rd)["papers"]]
    for p, s, code, why in excluded:
        q = _paper(p, net, extra.get(p.get("id")))
        e = entries.get(p.get("id")) or {}
        scr = dict(s) if s else {"relevance": None, "quality": None, "recency_impact": impact.get(p.get("id")),
                                 "composite": None, "rationale": e.get("rationale") or why}
        scr.update({"tier": None, "category": "excluded", "exclusion_reason": f"{code}: {why}",
                    "no_abstract": p.get("has_abstract") is False, "exclusion_code": code,
                    "stage": _stage(code, gate_codes), "scored": bool(s)})
        for k in ("violates", "both_readings", "record_problem", "duplicate_of"):
            if k in e:
                scr.setdefault(k, e[k])
        q["screening"] = scr
        q["manually_included"] = False
        rows.append(q)
    rows.sort(key=lambda q: (q["screening"].get("composite") is None, -float(q["screening"].get("composite") or 0),
                             str(q.get("id"))))
    crit = (cfg.get("protocol") or {}).get("criteria") or {}
    cats = Counter(q["screening"]["category"] for q in rows)
    return {
        "schema": "ideate-screening-all/1", "session_id": session_id_of(cfg), "topic": cfg.get("topic"),
        "criteria_inclusion": [{"id": c.get("id") or "", "en": c.get("text") or ""} for c in crit.get("inclusion") or []],
        "criteria_exclusion": [{"id": c.get("id") or "", "en": c.get("text") or ""} for c in crit.get("exclusion") or []],
        "criteria_amendments": list((scores or {}).get("criteria_amendments") or []),
        "tier_names": [{"tier": k, "en": v} for k, v in sorted(tier_names.items())],
        "summary": {"candidates": len(rows), "included": cats.get("included", 0), "borderline": cats.get("borderline", 0),
                    "excluded": cats.get("excluded", 0),
                    "excluded_by_stage": dict(Counter(q["screening"]["stage"] for q in rows if "stage" in q["screening"]))},
        "papers": rows,
    }


# ----------------------------------------------------------------------------------------------------------- gaps
def _median(xs: list) -> float:
    s = sorted(xs)
    return (s[len(s) // 2] + s[(len(s) - 1) // 2]) / 2


def _counts(xs) -> str:
    c = Counter(x for x in xs if x)
    return ", ".join(f"{k} {n}" for k, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))) or "none"


def gaps(doc: dict, rd: Path) -> dict:
    out = dict(doc)
    year = {p.get("citation_key"): p.get("year") for p in (_old(rd, "step3_shortlist.json").get("papers") or [])
            if isinstance(p, dict) and p.get("citation_key")}
    ranked = list(doc.get("ranked") or [])
    comps = doc.get("composites") or {}

    def ev(xs, text_key):
        return [{"citation_key": e.get("key"), "year": year.get(e.get("key")), "explanation_en": e.get(text_key) or ""}
                for e in xs or [] if isinstance(e, dict)]
    gl = []
    for g in doc.get("gaps") or []:
        if not isinstance(g, dict):
            continue
        q = dict(g)
        ty = g.get("type") or {}
        fb = g.get("feasibility_basis")
        ce = g.get("consequence_evidence") or []
        q["rank"] = ranked.index(g.get("id")) + 1 if g.get("id") in ranked else None
        q["composite"] = comps.get(g.get("id"))
        q["gap"] = {
            "title_en": g.get("title") or "", "gap_type": ty.get("primary"), "secondary_type": ty.get("secondary"),
            "description_en": g.get("description") or "",
            "supporting_evidence": ev(g.get("supporting"), "how"), "counter_evidence": ev(g.get("counter"), "why_open"),
            "why_it_matters_en": g.get("why_it_matters") or "",
            "severity": g.get("severity"), "novelty": g.get("novelty"), "feasibility": g.get("feasibility"),
            "severity_rationale_en": f"consequence evidence: {', '.join(ce)}" if ce else "",
            "novelty_rationale_en": str(g.get("novelty_basis") or ""),
            "feasibility_rationale_en": "; ".join(fb) if isinstance(fb, list) else str(fb or ""),
        }
        gl.append(q)
    out["gaps"] = gl
    by_id = {g.get("id"): g for g in gl}
    top = by_id.get(ranked[0]) if ranked else None
    sup = [len(g.get("supporting") or []) for g in gl]
    out["session_id"] = _session_id(rd)
    out["weights"] = dict(GAP_WEIGHTS)
    out["summary"] = {
        "executive_en": (f"{len(gl)} gap(s) ranked by composite = 0.40 x severity + 0.30 x novelty + 0.30 x feasibility"
                         + (f"; first: {top['id']} - {top.get('title')} ({top.get('composite')})." if top else ".")),
        "coverage_en": (f"Supporting papers per gap: {min(sup)}-{max(sup)} (median {_median(sup):g}); "
                        f"{sum(1 for g in gl if g.get('counter'))} gap(s) carry counter-evidence. " if sup else "")
                       + f"{len(doc.get('single_paper') or [])} in-scope topic(s) rest on one paper only and "
                         f"{len(doc.get('adjacent') or [])} adjacent opportunity(ies) lie outside the scope (not ranked).",
        "methodology_en": f"Gap types (primary): {_counts((g.get('type') or {}).get('primary') for g in gl)}; secondary: "
                          f"{_counts((g.get('type') or {}).get('secondary') for g in gl)}.",
        "patterns_en": f"Moves: {_counts(g.get('move') for g in gl)}; axes: "
                       f"{_counts(a for g in gl for a in g.get('axes') or [])}.",
    }
    return out


WRITERS = {"step0_session_config.json": session_config, "step2_raw_papers.json": raw_papers,
           "step3_shortlist.json": shortlist, "step7_gaps.json": gaps}


# ======================================================================================================= markdown
# The archived views opened with YAML front matter and had sections this pipeline's views name differently or leave
# out. A view keeps its own text; the front matter goes on top and the archived sections after it, rendered from the
# legacy fields above (so the numbers are the JSON's). Everything here is a pure function of its arguments.
LEGACY_RULE = "\n\n---\n\n<!-- archived-format sections (it_legacy): the archived engine's layout of the same data -->\n\n"


def _cell(x) -> str:
    return str("" if x is None else x).replace("|", "\\|").replace("\n", " ").strip()


def _trunc(x, n: int) -> str:
    s = str(x or "")
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _last_name(author: str) -> str:
    a = str(author or "").strip()
    if "," in a:
        return a.split(",", 1)[0].strip()
    return a.split()[-1] if a.split() else ""


def in_text(p: dict) -> str:
    """APA in-text citation as the archived export wrote it: (Last, Y), (A & B, Y), (A et al., Y)."""
    au = [_last_name(a) for a in p.get("authors") or [] if a]
    y = p.get("year") or "n.d."
    if not au:
        return f"({_trunc(p.get('title'), 30)}, {y})"
    return f"({au[0]}, {y})" if len(au) == 1 else f"({au[0]} & {au[1]}, {y})" if len(au) == 2 else f"({au[0]} et al., {y})"


def frontmatter(fields: dict) -> str:
    """The archived utils.frontmatter."""
    import json
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        elif isinstance(v, list):
            lines.append(f"{k}: [{', '.join(json.dumps(x, ensure_ascii=False) for x in v)}]")
        elif v is None:
            lines.append(f"{k}: null")
        else:
            lines.append(f"{k}: {json.dumps(str(v), ensure_ascii=False)}")
    return "\n".join(lines + ["---"])


def wrap(view: str, fields: dict, sections: list[str]) -> str:
    """front matter + the pipeline's view + the archived sections."""
    return frontmatter(fields) + "\n" + view.rstrip("\n") + LEGACY_RULE + "\n".join(sections).rstrip("\n") + "\n"


def search_summary_md(view: str, cfg: dict, raw: dict, insts: list[dict]) -> str:
    """`raw`: step2_raw_papers.json as written (with the legacy fields: it_common.with_legacy)."""
    sm = raw["search_summary"]
    n = sm["final_count"]
    per_query_raw = Counter()
    for r in insts or []:
        if r.get("kind") == "query":
            per_query_raw[r.get("id")] += len(r.get("papers") or [])
    sources = list(sm.get("sources") or {})
    overlap = sum(1 for p in raw.get("papers") or [] if len(p.get("sources_found_in") or []) > 1)
    L = ["## Results", "", "| Query | Strategy | Raw | Unique |", "|-------|----------|-----|--------|"]
    for q in cfg.get("queries") or []:
        L.append(f"| {q.get('id')} | {_cell(q.get('strategy'))} | {per_query_raw.get(q.get('id'), 0)} | {sm['queries'].get(q.get('id'), 0)} |")
    L += [f"| Snowball | Top-cited references | — | {sm['snowball_additions']} |",
          f"| **Total** | | **{sm.get('total_raw_results', 0)}** | **{n}** |", "",
          f"DOI coverage: {sm.get('doi_coverage')}",
          f"Source overlap rate: {round(100 * overlap / n) if n else 0}%", "",
          "### Per source", "", "| Source | Unique |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sm["sources"].items()]
    if sm["source_failures"]:
        L += ["", "### Source failures", ""] + [f"- {f}" for f in sm["source_failures"]]
    L += ["", "## Hub Papers", ""]
    pid = {p.get("id"): p for p in raw.get("papers") or []}
    hubs = sorted((pid[h] for h in sm["hub_papers"] if h in pid), key=lambda p: (-p["citation_network"]["in_degree"], p["id"]))
    for i, p in enumerate(hubs, 1):
        fa = _last_name((p.get("authors") or ["Unknown"])[0])
        deg = p["citation_network"]["in_degree"]
        L.append(f"{i}. \"{_cell(p.get('title'))}\" ({fa}, {p.get('year')}) — in_degree: {deg} — cited by {deg} papers in this collection")
    if not hubs:
        L.append("No hub papers (in_degree ≥ 3) detected: the search step records no reference lists (A3.b fetches "
                 "them; see the Hub Paper Summary of step3_screening_results.md).")
    L += ["", "## Citation Clusters", ""]
    L += [f"- **{c['name']}** ({len(c['paper_ids'])} papers) — top terms: {c['theme']}" for c in sm["clusters"]] or \
         ["- No internal citation clusters detected."]
    if n < 20:
        en = (f"Low yield: only {n} unique papers. Consider broadening the weakest queries, extending the timeframe, or "
              "dropping population/outcome constraints; the topic may genuinely be under-explored.")
    elif n > 80:
        en = f"High yield: {n} unique papers. Screening in Step 3 will filter; expect a larger borderline set."
    else:
        en = (f"Yield within the expected 30–60 range ({n} papers) after deduplication across {len(sources)} sources "
              f"with {sm['snowball_additions']} snowball additions.")
    L += ["", "## Yield Assessment", "", en]
    fields = {"session_id": raw.get("session_id") or session_id_of(cfg), "topic": cfg.get("topic"),
              "date": str(raw.get("search_timestamp") or "")[:10], "step": 2}
    return wrap(view, fields, L)


def screening_md(view: str, cfg: dict, out: dict, excluded: list) -> str:
    """`out`: step3_shortlist.json as written (with the legacy fields); `excluded`: it_screen's (paper, screening or
    None, code, why) tuples."""
    sl = out
    sm, w = sl["summary"], (sl.get("screening_config") or {}).get("weights") or {}
    thr, bt = sl["screening_config"]["threshold"], sl["screening_config"]["borderline_threshold"]
    papers = sl["papers"]
    inc = [p for p in papers if p["screening"]["category"] == "included"]
    bord = [p for p in papers if p["screening"]["category"] == "borderline"]
    n = sm.get("total_screened") or (len(papers) + len(excluded))
    pct = lambda k: f"{round(100 * k / n) if n else 0}%"  # noqa: E731
    crit = (cfg.get("protocol") or {}).get("criteria") or {}

    def row(p, hub=False):
        s = p["screening"]
        au = p.get("authors") or []
        fa = f"{_last_name(au[0])} et al." if len(au) > 1 else (au[0] if au else "—")
        comp = s.get("composite")
        cells = [p.get("id"), _cell(_trunc(p.get("title"), 90)), _cell(fa), str(p.get("year") or ""), str(s.get("relevance")),
                 str(s.get("quality")), str(s.get("recency_impact")), f"**{comp:.2f}**" if isinstance(comp, (int, float)) else "—",
                 _cell(s.get("rationale"))]
        if hub:
            cells.append("Yes" if p["citation_network"]["is_hub"] else "—")
        return "| " + " | ".join(cells) + " |"
    head = ("| ID | Title | Authors | Year | Rel | Qual | Rec | **Composite** | Rationale |\n"
            "|----|-------|---------|------|-----|------|-----|---------------|-----------|")
    L = ["## Screening Criteria", "", "### Inclusion"] + [f"- {c.get('text')}" for c in crit.get("inclusion") or []]
    L += ["", "### Exclusion"] + [f"- {c.get('text')}" for c in crit.get("exclusion") or []]
    L += ["", "## Summary", "", "| Category | Count | Percentage |", "|-----------------|-------------|-------------------|",
          f"| **Included** | **{len(inc)}** | **{pct(len(inc))}** |", f"| Borderline | {len(bord)} | {pct(len(bord))} |",
          f"| Excluded | {len(excluded)} | {pct(len(excluded))} |", "",
          f"Composite formula: `composite = relevance × {w.get('relevance', 0):.2f} + quality × {w.get('quality', 0):.2f} + "
          f"recency_impact × {w.get('recency_impact', 0):.2f}` (computed by code). Borderline papers (tier 4) are "
          "included in this pipeline's shortlist."]
    for tier, name, rng in ((1, "core", "Score >= 4.5"), (2, "strong supporting", "Score 4.0–4.49"),
                            (3, "contextual", f"Score {thr}–3.99")):
        rows = [row(p) for p in inc if p["screening"].get("tier") == tier]
        L += ["", f"## Tier {tier}: {name} ({rng})", "", head] + (rows or ["| — | (none) | | | | | | | |"])
    L += ["", "---", "", f"## Borderline Papers (Score {bt}–{round(thr - 0.01, 2)})", "",
          "| ID | Title | Authors | Year | Rel | Qual | Rec | **Composite** | Rationale | Hub? |",
          "|----|-------|---------|------|-----|------|-----|---------------|-----------|------|"]
    L += [row(p, hub=True) for p in bord] or ["| — | (none) | | | | | | | | |"]
    L += ["", "---", "", f"## Excluded Papers (Score < {bt})", "",
          "| ID | Title | Year | Rel | Qual | Rec | **Composite** | Exclusion Reason |",
          "|----|-------|------|-----|------|-----|---------------|---------------------------|"]
    for p, s, code, why in excluded:
        s = s or {}
        comp = s.get("composite")
        L.append(f"| {p.get('id')} | {_cell(_trunc(p.get('title'), 90))} | {p.get('year') or ''} | {s.get('relevance', '—')} | "
                 f"{s.get('quality', '—')} | {s.get('recency_impact', '—')} | "
                 f"{f'**{comp:.2f}**' if isinstance(comp, (int, float)) else '—'} | {_cell(f'{code}: {why}')} |")
    if not excluded:
        L.append("| — | (none) | | | | | | |")
    hubs = [p for p in papers if p["citation_network"]["is_hub"]]
    L += ["", "---", "", "## Hub Paper Summary", "", "| ID | Title | In-Degree | Cluster | Status | Note |",
          "|----|-------|-----------|---------|--------|------|"]
    for p in hubs:
        cn = p["citation_network"]
        L.append(f"| {p['id']} | {_cell(_trunc(p.get('title'), 80))} | {cn['in_degree']} | {cn.get('cluster') or '—'} | "
                 f"{p['screening']['category'].capitalize()} | Hub paper: cited by {cn['in_degree']} papers in this collection |")
    if not hubs:
        L.append("| — | (no hub papers) | | | | |")
    if sm.get("manually_included"):
        L += ["", f"Manually included: {sm['manually_included']}"]
    fields = {"session_id": sl.get("session_id") or session_id_of(cfg), "topic": cfg.get("topic"),
              "date": str(sl.get("screening_timestamp") or "")[:10], "step": 3, "threshold": thr,
              "weights": ", ".join(f"{k}={v:.2f}" for k, v in w.items())}
    return wrap(view, fields, L)


def citation_keys_md(view: str, cfg: dict, sl: dict, date: str) -> str:
    papers = [p for p in sl.get("papers") or [] if p.get("citation_key")]
    papers.sort(key=lambda p: (-float((p.get("screening") or {}).get("composite") or 0), p.get("id") or ""))
    L = ["## Citation Keys (archived layout)", "", f"> Topic: {cfg.get('topic')}", f"> Total: {len(papers)} papers", "",
         "| Citation Key | Citation | Short Title | Year | Tier |",
         "|----------------------|----------------|-------------------|------------|------|"]
    L += [f"| `{p['citation_key']}` | {_cell(in_text(p))} | {_cell(_trunc(p.get('title'), 60))} | {p.get('year') or ''} | "
          f"{(p.get('screening') or {}).get('tier') or '—'} |" for p in papers]
    first = papers[0] if papers else None
    L += ["", "## Usage", "", "In downstream steps, cite papers using the citation key:",
          f"- In SOTA review: `{in_text(first) if first else '(Author, Year)'}` or `Author (Year)`",
          f"- In LaTeX: `\\cite{{{first['citation_key'] if first else 'AuthorYear'}}}`"]
    fields = {"session_id": sl.get("session_id") or session_id_of(cfg), "topic": cfg.get("topic"), "date": date, "step": 4}
    return wrap(view, fields, L)


def access_log_md(view: str, cfg: dict, sl: dict, fetch_log: dict, rd: Path) -> str:
    rows = [p for p in sl.get("papers") or [] if p.get("citation_key")]
    rows.sort(key=lambda p: (-float((p.get("screening") or {}).get("composite") or 0), p.get("id") or ""))
    n = len(rows)
    levels = Counter(p.get("access_level") or "abstract-only" for p in rows)
    ft = n - levels.get("abstract-only", 0)
    pct = lambda k: f"{round(100 * k / n) if n else 0}%"  # noqa: E731
    attempts = (fetch_log or {}).get("attempts") or {}
    L = ["## Summary", "", "| Access Level | Count | Percentage |", "|------------------------|-------------|-------------------|"]
    L += [f"| {lv} | {levels.get(lv, 0)} | {pct(levels.get(lv, 0))} |" for lv in
          dict.fromkeys(["full-text", "full-text-plain", "pdf-only", "abstract-only", *levels])]
    L += ["", f"Full-text retrieval rate: **{pct(ft)}** ({ft}/{n} papers)", "", "## Extraction Quality", "",
          "| Citation Key | Method | Chars | Sections | Flag |", "|---|---|---|---|---|"]
    for p in rows:
        lv = p.get("access_level") or "abstract-only"
        if lv in ("full-text", "full-text-plain"):
            md = Path(rd) / "step5_full_text" / f"{p['citation_key']}.md"
            text = md.read_text(encoding="utf-8") if md.is_file() else ""
            method = "pdf2md (marker)" if lv == "full-text" else "pdftotext"
            flag = "ok" if lv == "full-text" else "⚠️ pdftotext fallback: tables and equations degraded"
            L.append(f"| `{p['citation_key']}` | {method} | {len(text)} | {len(re.findall(r'(?m)^#{1,6} ', text))} | {flag} |")
    L += ["", "## Successfully Retrieved", "", "| # | Citation Key | Title | Source | Access Level |",
          "|---|---------------------|-------------|--------------|-------------------|"]
    k = 0
    for p in rows:
        if (p.get("access_level") or "abstract-only") != "abstract-only":
            k += 1
            ok = [a for a in attempts.get(p["citation_key"]) or [] if a.get("status") not in ("failed", "error")]
            src = (ok[-1].get("source") or ok[-1].get("route")) if ok else "pdfs/ (placed by hand or fetched)"
            L.append(f"| {k} | `{p['citation_key']}` | {_cell(_trunc(p.get('title'), 70))} | {_cell(src)} | {p.get('access_level')} |")
    L += ["", "## Abstract Only — Action Required", "",
          "> These papers could not be accessed through open channels. If you have institutional access, save the PDF as "
          "`pdfs/<citation key>.pdf` and re-run `pdf2md.sh` and `fulltext-status`.", "",
          "| # | Citation Key | Title | DOI | Suggested Action |", "|---|---------------------|-------------|-----|--------------------------|"]
    k = 0
    for p in rows:
        if (p.get("access_level") or "abstract-only") == "abstract-only":
            k += 1
            doi = f"[{p['doi']}](https://doi.org/{p['doi']})" if p.get("doi") else "—"
            L.append(f"| {k} | `{p['citation_key']}` | {_cell(_trunc(p.get('title'), 70))} | {doi} | Try institutional proxy |")
    L += ["", "## Access Attempts Detail", ""]
    for p in rows:
        L.append(f"### {p['citation_key']}: {_trunc(p.get('title'), 70)}")
        for a in attempts.get(p["citation_key"]) or []:
            L.append(f"- **{a.get('route') or a.get('source') or 'attempt'}**: {a.get('status')} {a.get('reason') or ''}".rstrip())
        L += [f"- **Final status**: {p.get('access_level') or 'abstract-only'}", ""]
    stamps = sorted(a.get("at") for v in attempts.values() for a in v or [] if a.get("at"))
    fields = {"session_id": sl.get("session_id") or session_id_of(cfg), "topic": cfg.get("topic"),
              "date": (stamps[-1] if stamps else str(sl.get("screening_timestamp") or ""))[:10], "step": 5}
    return wrap(view, fields, L)


def _evidence_line(e: dict) -> str:
    year = f" ({e['year']})" if e.get("year") else ""
    return f"- **{e['citation_key']}{year}**: {e['explanation_en']}"


def gap_analysis_md(view: str, cfg: dict, doc: dict) -> str:
    """`doc`: step7_gaps.json as written (with the legacy fields)."""
    w = doc["weights"]
    ranked = sorted((g for g in doc["gaps"] if g.get("rank")), key=lambda g: g["rank"])
    sm = doc["summary"]
    L = ["## Executive Summary", "", sm["executive_en"], "", "---"]
    for r in ranked:
        g = r["gap"]
        typ = (g.get("gap_type") or "") + (f" ({g['secondary_type']})" if g.get("secondary_type") else "")
        L += ["", f"## {r['id']}: {g['title_en']}", "", f"**Type:** {typ}", f"**Priority Rank:** #{r['rank']}", "",
              "### Description", "", g["description_en"], "", "### Supporting Evidence", ""]
        L += [x for e in g["supporting_evidence"] for x in (_evidence_line(e), "")]
        L += ["### Counter-Evidence", ""]
        L += [x for e in g["counter_evidence"] for x in (_evidence_line(e), "")]
        if not g["counter_evidence"]:
            L += ["> No papers in the collection address this gap, even partially.", ""]
        sev, nov, fea = g.get("severity") or 0, g.get("novelty") or 0, g.get("feasibility") or 0
        a, b, c = round(sev * w["severity"], 2), round(nov * w["novelty"], 2), round(fea * w["feasibility"], 2)
        L += ["### Why It Matters", "", g["why_it_matters_en"], "", "### Priority Score", "", "| Axis | Score | Rationale |",
              "|--------------|-------------|-----------------|", f"| Severity | {sev} | {_cell(g['severity_rationale_en'])} |",
              f"| Novelty | {nov} | {_cell(g['novelty_rationale_en'])} |",
              f"| Feasibility | {fea} | {_cell(g['feasibility_rationale_en'])} |", "",
              f"**Composite:** {sev} × {w['severity']:.2f} + {nov} × {w['novelty']:.2f} + {fea} × {w['feasibility']:.2f} = "
              f"{a:.2f} + {b:.2f} + {c:.2f} = **{(r.get('composite') or 0):.2f}**", "", "---"]
    L += ["", "## Priority Ranking", "", "| Rank | Gap ID | Title | Type | Severity | Novelty | Feasibility | **Composite** |",
          "|------------|--------|-------------|-----------|-----------------|----------------|--------------------|-----------------------|"]
    L += [f"| {r['rank']} | {r['id']} | {_cell(r['gap']['title_en'])} | {r['gap']['gap_type']} | {r['gap']['severity']} | "
          f"{r['gap']['novelty']} | {r['gap']['feasibility']} | **{(r.get('composite') or 0):.2f}** |" for r in ranked]
    L += ["", "---", "", "## Gap Landscape Summary", "", "### Coverage Strength", "", sm["coverage_en"], "",
          "### Methodology Distribution", "", sm["methodology_en"], "", "### Cross-Gap Patterns", "", sm["patterns_en"]]
    fields = {"session_id": doc.get("session_id") or session_id_of(cfg), "topic": doc.get("topic") or cfg.get("topic"),
              "date": str(doc.get("at") or "")[:10], "step": 7, "gaps_identified": len(ranked),
              "priority_weights": ", ".join(f"{k}={v:.2f}" for k, v in w.items())}
    return wrap(view, fields, L)


# ========================================================================================================== check
# The archived format as data: what a reader of the old files relies on. JSON: path -> allowed JSON types (from the
# archived pydantic schemas, schemas/session_config.py, paper.py, llm_outputs.py); `[]` is "each item of the array",
# `{*}` "each value of the map". Markdown: heading templates (case, punctuation and an H1's subtitle folded; a
# title after "GAP_N:", "Theme N:", "Tier N:", "N." or a citation key is free) and the column sets of its tables.
STR, NUM, INT, BOOL, ARR, OBJ, NULL = "string", "number", "integer", "boolean", "array", "object", "null"
_PAPER = {"id": [STR], "title": [STR], "authors": [ARR], "authors[]": [STR], "year": [INT, NULL], "journal": [STR, NULL],
          "doi": [STR, NULL], "url": [STR, NULL], "abstract": [STR, NULL], "citation_count": [INT, NULL],
          "sources_found_in": [ARR], "semantic_scholar_id": [STR, NULL], "openalex_id": [STR, NULL],
          "pubmed_id": [STR, NULL], "pmc_id": [STR, NULL], "arxiv_id": [STR, NULL], "references": [ARR],
          "references[]": [STR], "cited_by": [ARR], "cited_by[]": [STR], "is_seed_paper": [BOOL], "found_via": [STR],
          "language": [STR, NULL], "venue_type": [STR, NULL], "volume": [STR, NULL], "issue": [STR, NULL],
          "pages": [STR, NULL], "arxiv_primary_class": [STR, NULL], "citation_network": [OBJ],
          "citation_network.in_degree": [INT], "citation_network.out_degree": [INT],
          "citation_network.is_hub": [BOOL], "citation_network.cluster": [STR, NULL]}
_EVIDENCE = {"citation_key": [STR], "year": [INT, NULL], "explanation_en": [STR]}
JSON_SPEC = {
    "step0_session_config.json": {
        "session_id": [STR], "topic": [STR], "topic_original": [STR], "topic_slug": [STR], "timestamp": [STR],
        "current_step": [INT], "pico": [OBJ],
        **{f"pico.{k}": [STR] for k in ("population", "intervention", "comparison", "outcome", "setting", "timeframe")},
        "source_urls": [ARR], "source_urls[]": [STR], "queries": [ARR],
        **{f"queries[].{k}": [STR] for k in ("id", "strategy", "query", "rationale")},
        "field_type": [STR], "engine": [OBJ], "engine.version": [STR], "engine.llm_model": [STR],
        "engine.llm_temperature": [NUM]},
    "step2_raw_papers.json": {
        "session_id": [STR], "topic": [STR], "search_timestamp": [STR], "search_summary": [OBJ],
        **{f"search_summary.{k}": [INT] for k in ("total_raw_results", "after_dedup", "snowball_additions", "final_count")},
        "search_summary.sources": [OBJ], "search_summary.sources.{*}": [INT],
        **{f"search_summary.sources.{k}": [INT] for k in ARCHIVED_SOURCES}, "search_summary.queries": [OBJ],
        "search_summary.queries.{*}": [INT], "search_summary.doi_coverage": [STR], "search_summary.hub_papers": [ARR],
        "search_summary.hub_papers[]": [STR], "search_summary.clusters": [ARR], "search_summary.clusters[].name": [STR],
        "search_summary.clusters[].paper_ids": [ARR], "search_summary.clusters[].paper_ids[]": [STR],
        "search_summary.clusters[].theme": [STR], "search_summary.source_failures": [ARR],
        "search_summary.source_failures[]": [STR], "papers": [ARR], **{f"papers[].{k}": v for k, v in _PAPER.items()}},
    "step3_shortlist.json": {
        "session_id": [STR], "topic": [STR], "screening_timestamp": [STR], "screening_config": [OBJ],
        "screening_config.threshold": [NUM], "screening_config.borderline_threshold": [NUM],
        "screening_config.weights": [OBJ], "screening_config.weights.{*}": [NUM], "summary": [OBJ],
        **{f"summary.{k}": [INT] for k in ("total_screened", "included", "borderline", "excluded", "manually_included")},
        "summary.inclusion_rate": [STR], "papers": [ARR], **{f"papers[].{k}": v for k, v in _PAPER.items()},
        "papers[].screening": [OBJ],
        # archived: integers 1-5; this pipeline's recency_impact is A3.b's computed score to one decimal (4.6) - kept
        **{f"papers[].screening.{k}": [NUM, NULL] for k in ("relevance", "quality", "recency_impact")},
        "papers[].screening.composite": [NUM], "papers[].screening.tier": [INT, NULL],
        "papers[].screening.category": [STR], "papers[].screening.rationale": [STR],
        "papers[].screening.exclusion_reason": [STR, NULL], "papers[].screening.no_abstract": [BOOL],
        "papers[].manually_included": [BOOL]},
    "step3_screening_all.json": {     # archived ScreeningRecord
        "session_id": [STR], "criteria_inclusion": [ARR], "criteria_inclusion[].en": [STR],
        "criteria_exclusion": [ARR], "criteria_exclusion[].en": [STR], "tier_names": [ARR], "tier_names[].tier": [INT],
        "tier_names[].en": [STR], "papers": [ARR], **{f"papers[].{k}": v for k, v in _PAPER.items()},
        "papers[].screening": [OBJ],
        **{f"papers[].screening.{k}": [NUM, NULL] for k in ("relevance", "quality", "recency_impact")},
        # archived: always a number; null here for a paper excluded before it was scored (gate, criterion, duplicate)
        "papers[].screening.composite": [NUM, NULL], "papers[].screening.tier": [INT, NULL],
        "papers[].screening.category": [STR], "papers[].screening.rationale": [STR],
        "papers[].screening.exclusion_reason": [STR, NULL], "papers[].screening.no_abstract": [BOOL],
        "papers[].manually_included": [BOOL]},
    "step7_gaps.json": {
        "session_id": [STR], "weights": [OBJ], **{f"weights.{k}": [NUM] for k in GAP_WEIGHTS}, "gaps": [ARR],
        "gaps[].id": [STR], "gaps[].rank": [INT], "gaps[].composite": [NUM], "gaps[].gap": [OBJ],
        **{f"gaps[].gap.{k}": [STR] for k in ("title_en", "gap_type", "description_en", "why_it_matters_en",
                                             "severity_rationale_en", "novelty_rationale_en", "feasibility_rationale_en")},
        "gaps[].gap.secondary_type": [STR, NULL],
        **{f"gaps[].gap.{k}": [INT] for k in ("severity", "novelty", "feasibility")},
        "gaps[].gap.supporting_evidence": [ARR], "gaps[].gap.counter_evidence": [ARR],
        **{f"gaps[].gap.{side}[].{k}": v for side in ("supporting_evidence", "counter_evidence") for k, v in _EVIDENCE.items()},
        "summary": [OBJ], **{f"summary.{k}": [STR] for k in ("executive_en", "coverage_en", "methodology_en", "patterns_en")}},
}
# `model`: written by the model under the rules (research-cycle.md §2, §7), not by code - a gap there is a WARN;
# `skill`: a file the archived engine did not write (the legacy skill's format, as its runs write it)
MD_SPEC = {
    "step2_search_summary.md": {
        "front": ["session_id", "topic", "date", "step"],
        "headings": ["# search summary", "## results", "### per source", "## hub papers", "## citation clusters",
                     "## yield assessment"],
        "tables": [["Query", "Strategy", "Raw", "Unique"], ["Source", "Unique"]]},
    "step3_screening_results.md": {
        "front": ["session_id", "topic", "date", "step", "threshold", "weights"],
        "headings": ["# screening results", "## screening criteria", "### inclusion", "### exclusion", "## summary",
                     "## tier n", "## borderline papers", "## excluded papers", "## hub paper summary"],
        "tables": [["Category", "Count", "Percentage"],
                   ["ID", "Title", "Authors", "Year", "Rel", "Qual", "Rec", "Composite", "Rationale"],
                   ["ID", "Title", "Authors", "Year", "Rel", "Qual", "Rec", "Composite", "Rationale", "Hub?"],
                   ["ID", "Title", "Year", "Rel", "Qual", "Rec", "Composite", "Exclusion Reason"],
                   ["ID", "Title", "In-Degree", "Cluster", "Status", "Note"]]},
    "step4_citation_keys.md": {
        "front": ["session_id", "topic", "date", "step"],
        "headings": ["# citation keys", "## usage"],
        "tables": [["Citation Key", "Citation", "Short Title", "Year", "Tier"]]},
    "step5_full_text/_access_log.md": {
        "front": ["session_id", "topic", "date", "step"],
        "headings": ["# full text access log", "## summary", "## extraction quality", "## successfully retrieved",
                     "## abstract only action required", "## access attempts detail"],
        "tables": [["Access Level", "Count", "Percentage"], ["Citation Key", "Method", "Chars", "Sections", "Flag"],
                   ["#", "Citation Key", "Title", "Source", "Access Level"],
                   ["#", "Citation Key", "Title", "DOI", "Suggested Action"]]},
    "step6_sota_review.md": {
        "model": True,
        "front": ["session_id", "topic", "date", "step", "total_papers", "themes", "full_text_papers",
                  "abstract_only_papers"],
        "headings": ["# state of the art review", "## executive summary", "## methodology legend", "## theme n",
                     "### consensus", "### debates", "### dominant methods", "### key results", "## cross theme analysis",
                     "### methodological trends over time", "### converging findings", "### diverging findings",
                     "### theme interactions", "## paper theme mapping"],
        "tables": [["Color", "Methodology", "Count"], ["Study", "N", "Method", "Primary Outcome", "Result"],
                   ["Citation Key", "Theme", "Methodology", "Bridge?"]]},
    "step7_gap_analysis.md": {
        "front": ["session_id", "topic", "date", "step", "gaps_identified", "priority_weights"],
        "headings": ["# gap analysis", "## executive summary", "## gap n", "### description", "### supporting evidence",
                     "### counter evidence", "### why it matters", "### priority score", "## priority ranking",
                     "## gap landscape summary", "### coverage strength", "### methodology distribution",
                     "### cross gap patterns"],
        "tables": [["Axis", "Score", "Rationale"],
                   ["Rank", "Gap ID", "Title", "Type", "Severity", "Novelty", "Feasibility", "Composite"]]},
    "gen_*/step8_journal_recommendations.md": {
        "model": True,
        "front": ["session_id", "topic", "date", "step", "journals_recommended"],
        "headings": ["# journal recommendations", "## selection criteria", "## recommended journals", "### n",
                     "## journal comparison", "## submission strategy"],
        "tables": [["Field", "Details"], ["Rank", "Journal", "IF", "Scope Fit", "Review Time", "OA Cost", "Strategy"]]},
    # files the archived engine did not write: the sections the rules fix for them (research-cycle.md §4 and
    # planning/P2-design.md; knowledge-templates.md "prescriptive Body"), as the legacy skill's runs write them
    "gen_*/step8_hypothesis.md": {
        "model": True, "skill": True, "front": [],
        "headings": ["## selected gap summary", "## research questions", "## hypotheses", "## rival explanations",
                     "## operational definitions", "## scope", "## conceptual framework", "## risk assessment",
                     "## by construction check", "## external check", "## power", "## traceability"],
        "tables": [["Risk", "Likelihood", "Impact", "Mitigation"], ["Element", "Source", "Evidence"]]},
    "gen_*/body/B_draft_*.md": {
        "model": True, "skill": True, "front": ["id", "type", "body_role", "based_on", "gap", "angle"],
        "headings": ["## q1 core goal of the plan", "## q2 main work items", "## q3 ordering what precedes what",
                     "## q4 input output of each stage", "## q5 cross stage influence", "## q6 feedback loops",
                     "## q7 what real problem does it solve", "## risks and alternative paths", "## target outputs"],
        "tables": [["Risk", "Likelihood", "Impact", "Mitigation"]]},
}


def spec_key(rel: str) -> str | None:
    """The MD_SPEC entry a research-folder path falls under (gen_1/body/B_draft_x.md -> gen_*/body/B_draft_*.md)."""
    import fnmatch
    return next((k for k in MD_SPEC if fnmatch.fnmatch(rel, k)), None)


def _jtype(v) -> str:
    if v is None:
        return NULL
    if isinstance(v, bool):
        return BOOL
    if isinstance(v, int):
        return INT
    return {float: NUM, str: STR, list: ARR, dict: OBJ}.get(type(v), type(v).__name__)


def _walk(v, parts: list[str]):
    """The values at a spec path split into parts: `key`, `key[]` (each item of the array), `{*}` (each map value)."""
    if not parts:
        yield v
        return
    head, rest = parts[0], parts[1:]
    if head == "{*}":
        for x in (v.values() if isinstance(v, dict) else []):
            yield from _walk(x, rest)
        return
    each = head.endswith("[]")
    key = head[:-2] if each else head
    if not isinstance(v, dict) or key not in v:
        yield KeyError(key)
        return
    v = v[key]
    if each:
        for x in (v if isinstance(v, list) else []):
            yield from _walk(x, rest)
    else:
        yield from _walk(v, rest)


def check_json(name: str, doc) -> list[str]:
    """The archived fields `doc` lacks or holds with another type (an empty array or map is not a loss)."""
    out = []
    for path, types in JSON_SPEC[name].items():
        for v in _walk(doc, path.split(".")):
            if isinstance(v, KeyError):
                out.append(f"{name}: {path} missing")
                break
            t = _jtype(v)
            if not (t in types or (t == INT and NUM in types)):
                out.append(f"{name}: {path} is {t}, archived {'|'.join(types)}")
                break
    return out


def heading_template(h: str) -> str:
    level, _, text = h.partition(" ")
    t = text.strip()
    m = re.match(r"^(GAP_\d+|Tier \d+|Theme \d+|\d+\.)", t, re.I)
    if m:
        t = re.sub(r"\d+", "n", m.group(1).rstrip("."))
    elif re.match(r"^[A-Za-z][A-Za-z0-9]*\d{4}[a-z]?\s*:", t):
        t = "<key>"
    return f"{level} {re.sub(r'[^a-z0-9<>]+', ' ', t.lower()).strip()}"


def check_md(name: str, text: str) -> list[str]:
    """The archived front-matter keys, sections and table columns the view `text` lacks."""
    spec, out = MD_SPEC[name], []
    fm = re.match(r"^---\n(.*?)\n---", text, re.S)
    keys = set(re.findall(r"(?m)(?:^|\s)([A-Za-z_]+):", fm.group(1))) if fm else set()
    out += [f"{name}: front matter lacks {k}" for k in spec["front"] if k not in keys]
    heads, tables, fence = set(), [], False
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            fence = not fence
        if fence:
            continue
        if re.match(r"^#{1,6} ", ln):
            heads.add(heading_template(ln))
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|?$", lines[i + 1]):
            tables.append({c.strip().strip("*` ").lower() for c in ln.strip().strip("|").split("|")})
    for h in spec["headings"]:
        if not any(x == h or x.startswith(h + " ") for x in heads):
            out.append(f"{name}: no '{h}' section")
    for cols in spec["tables"]:
        want = {c.lower() for c in cols}
        if not any(want <= t for t in tables):
            out.append(f"{name}: no table with columns {' | '.join(cols)}")
    return out


def check(rd: Path) -> dict:
    """{file: [problems]} for every file of the archived format that exists in the research folder `rd`."""
    rd, res = Path(rd), {}
    for name in JSON_SPEC:
        if (rd / name).is_file():
            res[name] = check_json(name, read_json(rd / name))
    for name in MD_SPEC:
        for p in sorted(rd.glob(name)):
            res[p.relative_to(rd).as_posix()] = check_md(name, p.read_text(encoding="utf-8"))
    return res


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3 or sys.argv[1] != "check":
        sys.exit("usage: it_legacy.py check <research_dir>   (the archived engine's format, file by file)")
    bad = 0
    for f, probs in check(Path(sys.argv[2])).items():
        model = MD_SPEC.get(spec_key(f) or "", {}).get("model")
        print(f"{'ok  ' if not probs else 'WARN' if model else 'FAIL'} {f}" + "".join(f"\n       {x}" for x in probs))
        bad += bool(probs) and not model
    sys.exit(1 if bad else 0)
