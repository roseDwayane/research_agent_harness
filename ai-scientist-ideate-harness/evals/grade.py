#!/usr/bin/env python3
"""Mechanical grader for ai-scientist-ideate eval runs.

  python grade.py <run_dir> --domain {biomed,ml}      # <run_dir> contains outputs/ ; writes <run_dir>/grading.json

Every assertion is checked from files on disk, never from the agent's own claims.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "scripts" / "ideate_tools.py"
IDEA_KEYS = ["Name", "Title", "Short Hypothesis", "Related Work", "Abstract", "Experiments", "Risk Factors and Limitations"]


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--domain", choices=["biomed", "ml"], required=True)
    ap.add_argument("--ideas", type=int, default=1, help="how many ideas the prompt asked for")
    ap.add_argument("--depth", choices=["quick", "standard", "deep"], default="quick")
    a = ap.parse_args()
    out = Path(a.run_dir) / "outputs"
    rd = out / "topic_research"
    results = []

    def check(text, passed, evidence):
        results.append({"text": text, "passed": bool(passed), "evidence": str(evidence)[:400]})

    # --- the downstream contract -------------------------------------------------------------------------------
    ideas = load(out / "topic.json")
    ok = isinstance(ideas, list) and len(ideas) == a.ideas and all(isinstance(i, dict) for i in ideas)
    check(f"topic.json holds exactly the {a.ideas} idea(s) that were asked for", ok,
          f"type={type(ideas).__name__}, n={len(ideas) if isinstance(ideas, list) else '-'}")
    all_ideas = ideas if ok else []
    idea = all_ideas[0] if all_ideas else {}
    r = subprocess.run([sys.executable, str(TOOLS), "validate", str(out / "topic.json")], capture_output=True, text=True)
    check("Idea satisfies the 7-key contract (keys+order, Name format, ~250-word abstract, list fields)",
          r.returncode == 0, (r.stdout + r.stderr).strip().replace("\n", " | "))
    n_exps = [len(i.get("Experiments")) if isinstance(i.get("Experiments"), list) else 0 for i in all_ideas]
    check("Every idea has at least 3 concrete Experiments entries", bool(n_exps) and min(n_exps) >= 3, f"entries per idea={n_exps}")
    blob = " ".join(e for i in all_ideas for e in (i.get("Experiments") if isinstance(i.get("Experiments"), list) else [])).lower()
    gpu_heavy = re.findall(r"\b(a100|h100|v100|multi-gpu|gpu-days|8\s*gpus?|tpu)\b", blob)
    check("Experiments stay within the CPU / Apple MPS budget (no GPU-cluster requirements)", not gpu_heavy, gpu_heavy or "none found")

    # --- literature search: the five handoff checks, in the order the block runs ----------------------------------
    raw = load(rd / "step2_raw_papers.json") or {}
    papers = raw.get("papers") or []
    check("Literature search retrieved at least 25 papers to disk", len(papers) >= 25, f"{len(papers)} papers in step2_raw_papers.json")
    cfg = load(rd / "step0_session_config.json") or {}
    srcs = cfg.get("sources") or []
    want = {"biomed": {"pubmed"}, "ml": {"arxiv", "ieee"}}[a.domain]
    check(f"Sources were chosen from the topic's domain ({'/'.join(sorted(want))} for a {a.domain} topic)",
          bool(want & set(srcs)), f"sources={srcs}")
    for label, cmd in (("A1 frame (protocol, strategy, probe, evaluation, context)", ["frame", "check"]),
                       ("A2 search (instances, merge, relevance verdicts)", ["a2-check"]),
                       ("A3 screen (bibliometrics, gate, scores, shortlist)", ["a3-check"]),
                       ("A5 snowball (routes, thresholds, rounds)", ["a5-check"]),
                       ("A4 export (keys, bibliography)", ["a4-check"])):
        r = subprocess.run([sys.executable, str(TOOLS), *cmd, str(rd), "--json"], capture_output=True, text=True)
        try:
            fs = json.loads(r.stdout)
        except json.JSONDecodeError:
            fs = [{"level": "ERROR", "code": "-", "msg": (r.stdout + r.stderr).strip()[:300]}]
        err = [f for f in fs if f.get("level") == "ERROR"]
        check(f"{label} passes its handoff checks (`{' '.join(cmd)}`)", r.returncode == 0 and not err,
              "; ".join(f"{f['code']} {f['msg']}" for f in err[:5]) or "OK")
    ident = (raw.get("search_summary") or {}).get("identification") or {}
    dead = sorted(src for src, d in ident.items() if not d.get("queries"))
    check("No chosen source failed on every query", bool(ident) and not dead, f"sources without an answer={dead}")
    shortlist = (load(rd / "step3_shortlist.json") or {}).get("papers") or []
    keys = {p.get("citation_key") for p in shortlist if p.get("citation_key")}

    # --- knowledge base ----------------------------------------------------------------------------------------
    pts = list((rd / "knowledge" / "points").glob("P_draft_*.md")) if (rd / "knowledge").exists() else []
    pls = list((rd / "knowledge" / "planes").glob("F_draft_*.md")) if (rd / "knowledge").exists() else []
    check("Knowledge base has at least 5 Point cards and 3 Plane cards", len(pts) >= 5 and len(pls) >= 3, f"{len(pts)} points, {len(pls)} planes")
    six = ["Source", "Purpose", "Core claim", "Method", "Findings", "Inspiration"]
    full = sum(1 for f in pts if all(re.search(rf"^##?\s.*{s}", f.read_text(encoding='utf-8'), re.M | re.I) or
                                      (s == "Core claim" and "Core claim" in f.read_text(encoding='utf-8')) for s in six))
    check("Point cards carry all six required fields", pts and full == len(pts), f"{full}/{len(pts)} complete")
    idx = load(rd / "knowledge" / "concept_index.json") or {}
    dang = (idx.get("signals") or {}).get("dangling_references")
    check("concept_index.json exists and has no dangling references", idx and dang == [], f"dangling={dang}")

    # --- Pass M: method & experiment-design matrix -------------------------------------------------------------
    mm = load(rd / "knowledge" / "methods_matrix.json") or {}
    rows = mm.get("experiments") or []
    covered = {r.get("citation_key") for r in rows}
    check("Pass M wrote knowledge/methods_matrix.json with a row for every keyed shortlist paper",
          bool(rows) and keys and keys <= covered, f"{len(rows)} rows, {len(keys - covered)} keyed papers without a row")
    ft_keys = {f.stem for f in (rd / "step5_full_text").glob("*.md") if not f.name.startswith("_")} \
        if (rd / "step5_full_text").exists() else set()
    nr_on_abstract = [r["exp_id"] for r in rows if r.get("evidence") != "full-text"
                      and any(str(v).strip().upper().startswith("(NR)") for v in r.values() if isinstance(v, str))]
    wrong_ev = [r["exp_id"] for r in rows if r.get("evidence") == "full-text" and r.get("citation_key") not in ft_keys]
    check("Matrix evidence levels are honest: no (NR) on abstract rows, no full-text row without a full text",
          bool(rows) and not nr_on_abstract and not wrong_ev, f"NR on abstract={nr_on_abstract[:5]}, full-text w/o file={wrong_ev[:5]}")
    ms = ((idx.get("signals") or {}).get("methods") or {})
    check("concept_index.json carries the Pass M signals", ms.get("available") is True, f"methods.available={ms.get('available')}")

    # --- research cycle (every generation) -------------------------------------------------------------------
    need = ["step6_sota_review.md", "step7_gap_analysis.md", "step8_hypothesis.md", "step8_journal_recommendations.md",
            "reflection_log.md", "idea.json"]
    gens = [rd / f"gen_{k}" for k in range(1, a.ideas + 1)]
    missing = [f"{g.name}/{n}" for g in gens for n in need if not (g / n).exists()]
    check("Every generation has its SOTA review, gap analysis, hypothesis, reflection log, idea.json and journal recommendations",
          not missing, f"missing={missing}")
    # Auditable means the three weighted terms are visible: either "4 x 0.40 + ..." or the addends "1.60 + 1.20 + 1.50 = 4.30".
    # A bare total with no terms does not count.
    DERIV = re.compile(r"\d(?:\.\d+)?\s*[×x*]\s*0\.40?|\d\.\d{2}\s*\+\s*\d\.\d{2}\s*\+\s*\d\.\d{2}\s*=")
    n_gap = [sum(1 for ln in (g / "step7_gap_analysis.md").read_text(encoding="utf-8").splitlines() if DERIV.search(ln))
             if (g / "step7_gap_analysis.md").exists() else 0 for g in gens]
    check("Gap priorities show their arithmetic (severity x 0.40 + novelty x 0.30 + feasibility x 0.30)",
          bool(n_gap) and min(n_gap) >= 2, f"derivations per generation={n_gap}")
    ledger = cfg.get("consumed") or []
    names = [i.get("Name") for i in all_ideas]
    check("The (gap, angle) ledger has one entry per idea, each naming its idea",
          len(ledger) == a.ideas and sorted(e.get("idea") for e in ledger) == sorted(names), f"ledger={ledger}")
    pairs = [(e.get("gap"), str(e.get("angle", "")).strip().lower()) for e in ledger]
    check("No two ideas consumed the same (gap, angle) pair", len(pairs) == len(set(pairs)) and bool(pairs), f"pairs={pairs}")
    bodies = [b.name for g in gens for b in ((g / "body").glob("B_draft_*.md") if (g / "body").exists() else [])]
    check("A prescriptive Body card was written for every idea", len(bodies) >= a.ideas, bodies)
    # B2 reads designs from the matrix: every SOTA review must cite matrix rows by exp_id (key#E<n>) that exist.
    exp_ids = {r.get("exp_id") for r in rows}
    cited = [set(re.findall(r"\b([a-z0-9]+#E\d+)", (g / "step6_sota_review.md").read_text(encoding="utf-8")))
             if (g / "step6_sota_review.md").exists() else set() for g in gens]
    check("Every SOTA review builds its experimental designs from the methods matrix (cites >= 5 existing exp_ids, none unknown)",
          bool(cited) and all(len(c & exp_ids) >= 5 and not (c - exp_ids) for c in cited),
          f"per generation: {[(len(c & exp_ids), sorted(c - exp_ids)[:3]) for c in cited]}")
    desc = list((rd / "knowledge" / "body").glob("B_draft_*descriptive*.md")) if (rd / "knowledge" / "body").exists() else []
    based = [b for g in gens for b in ((g / "body").glob("B_draft_*.md") if (g / "body").exists() else [])
             if desc and desc[0].stem in b.read_text(encoding="utf-8")]
    check("A descriptive Body exists and every prescriptive Body is based_on it",
          bool(desc) and len(based) >= a.ideas, f"descriptive={[d.name for d in desc]}, based_on it={len(based)}/{a.ideas}")

    # --- planning inputs -------------------------------------------------------------------------------------
    le = cfg.get("local_environment") or {}
    check("The local environment was inspected and recorded before planning experiments",
          isinstance(le, dict) and any(le.get(k) for k in le), f"local_environment keys with content={[k for k in le if le.get(k)]}")
    if a.depth != "quick":
        ft = list((rd / "step5_full_text").glob("*.md")) if (rd / "step5_full_text").exists() else []
        ft = [f for f in ft if not f.name.startswith("_")]
        check("At least 8 papers were obtained and converted to full text", len(ft) >= 8, f"{len(ft)} full texts in step5_full_text/")
        lines = list((rd / "knowledge" / "lines").glob("[EDA]_draft_*.md")) if (rd / "knowledge").exists() else []
        check("Pass 2 produced standalone Line cards and the index treats the structure as reliable",
              bool(lines) and idx.get("structure_reliable") is True, f"{len(lines)} Line cards, structure_reliable={idx.get('structure_reliable')}")
        notes = list((rd / "knowledge" / "_notes").glob("*.md")) if (rd / "knowledge" / "_notes").exists() else []
        check("Reading notes were kept for the papers read in full", len(notes) >= min(8, len(ft)) and bool(ft), f"{len(notes)} notes for {len(ft)} full texts")

    # --- grounding: every cited paper was retrieved ------------------------------------------------------------
    # Test the property, not a format: a citation counts as grounded when it resolves to a record that was actually
    # retrieved to disk - either by an explicit [citation_key] or by (first-author surname, year).
    # Surname parsing is shared with the exporter, so the grader and the citation keys cannot disagree about who the
    # first author is (Scopus writes "Saha S.", other sources "Simanto Saha"; some records use a unicode hyphen).
    sys.path.insert(0, str(TOOLS.parent))
    from it_common import last_name as _family
    fold = lambda s: _family(str(s)).lower()
    by_author_year = {}
    for p in shortlist:
        first = (p.get("authors") or [""])[0]   # not `a`: that name is the argparse namespace
        by_author_year.setdefault((fold(first), str(p.get("year"))), []).append(p.get("citation_key"))
    rw = " ".join(str(i.get("Related Work", "")) for i in all_ideas)
    key_cites = set(re.findall(r"\[([a-z][a-z0-9\-]*\d{4}[a-z]?)\]", rw))
    # A citation is a parenthesised "(Author[ et al.| & Other], Year)" or a narrative "Author et al. (Year)". Matching any
    # capitalised word near a year mistook codec names for authors ("CCSDS Rice and JPEG-2000" -> "Rice 2000").
    A = r"[A-Z][A-Za-z\-']+"
    forms = [rf"\(({A})(?:\s+et al\.?|\s*(?:&|and)\s*{A})?,?\s+((?:19|20)\d{{2}})[a-z]?\)",
             rf"\b({A})(?:\s+et al\.?|\s*(?:&|and)\s*{A})?\s+\(((?:19|20)\d{{2}})[a-z]?\)"]
    # The skill tells the agent to NAME a classic the search missed and say so in words, never to cite it as if read.
    # Such a disclosure is honest, not a fabrication - but only when the same clause really says it was not retrieved.
    DISCLOSED = re.compile(r"\b(?:not|never|was not|were not|could not be)\s+(?:retrieved|recovered|obtained|found|read)\b|\bunretrieved\b", re.I)
    prose, disclosed = set(), set()
    for f in forms:
        for m in re.finditer(f, rw):
            cite = (_family(m.group(1)).lower(), m.group(2))
            clause = re.split(r";|(?<!al)(?<!vs)(?<!e\.g)(?<!i\.e)\.\s", rw[max(0, m.start() - 260): m.end() + 200])
            here = next((c for c in clause if m.group(0)[:12] in c), "")
            (disclosed if DISCLOSED.search(here) and cite not in by_author_year else prose).add(cite)
    grounded = {k for k in key_cites if k in keys} | {c for c in prose if c in by_author_year}
    ungrounded = {k for k in key_cites if k not in keys} | {c for c in prose if c not in by_author_year}
    total = len(key_cites) + len(prose)
    check("Related Work cites at least 3 papers that resolve to retrieved records on disk",
          len(grounded) >= 3, f"{len(grounded)} of {total} citations resolve to the shortlist")
    check("Every citation in Related Work resolves to a retrieved record (nothing cited from memory)",
          total > 0 and not ungrounded,
          (f"unresolved={sorted(map(str, ungrounded))[:6]}; explicitly disclosed as not retrieved={sorted(map(str, disclosed))}"
           if total else "no citations found"))
    ambiguous = sorted(f"{a} {y}" for (a, y) in prose if len(by_author_year.get((a, y), [])) > 1 and not key_cites)
    check("Citations are unambiguous (an explicit [citation_key] wherever author+year matches several papers)",
          total > 0 and not ambiguous, f"ambiguous author-year citations={ambiguous}" if ambiguous else "none ambiguous")

    passed = sum(r["passed"] for r in results)
    grading = {"expectations": results,
               "summary": {"passed": passed, "failed": len(results) - passed, "total": len(results),
                           "pass_rate": round(passed / len(results), 2)}}
    (Path(a.run_dir) / "grading.json").write_text(json.dumps(grading, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in results:
        print(("PASS " if r["passed"] else "FAIL ") + r["text"] + "  ::  " + r["evidence"][:140])
    print(f"\n{passed}/{len(results)} passed")


if __name__ == "__main__":
    main()
