#!/usr/bin/env python3
"""Score the gaps and the research questions of the harness arm and of the baseline against RQ-Bench's ground truth.

    python evaluation/step07_gaps/rqbench_eval.py --batch evaluation/runs/rq_dev --id rq_2501_01329_rq0 [--judge gemma4:31b]

RQ-Bench gives a held-out research question and, per cited paper, the limitation the target paper took up. It prescribes
no metric, and its authors report that LLM judges contradicted themselves on it, so the two measures below are ours, are
read with that caution, and carry a validity control each.

  gap coverage      for every annotated gap: does any candidate gap say the same thing (same limitation or open
                    problem, worded differently)? yes / no -> the share of annotated gaps covered. Recall only: the
                    annotated gaps are the ones the target paper happened to take up, not all that exist, so a gap a
                    system lists that is not annotated is not wrong.
  question match    for every candidate question: how closely does it ask the reference question (1-5)? The mean, and the
                    best of the candidates.

Control: the same judge scores the same candidates against the reference of OTHER development items (their annotated gaps,
their questions). A judge that gives those a high score cannot tell a match from a topical neighbour.

Candidates: the harness arm = the gaps of step7_gaps.json (B3) and the research question of every questions/Q_*.md
(B3.5; the file is read whether or not the harness accepted it - the report says if it did not); the baseline =
eval/<id>/baseline/output.md (rqbench_baseline.py). The judge prompts are ours.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "step06_sota"))

from autosurvey_common import OllamaChat  # noqa: E402
from autosurvey_eval import CachedCalls  # noqa: E402
from eval_common import batch_paths, ollama_digest, read_json, read_runs, write_json  # noqa: E402

DATA = HERE.parents[2] / "data" / "rq-bench"

GAP_PROMPT = '''A reference research gap and a numbered list of candidate gaps.

Reference gap:
[REF]

Candidate gaps:
[CANDIDATES]

Does any candidate state the same gap as the reference - the same limitation of existing work or the same open problem,
even if it is worded differently or is more general or more specific? A candidate that is only on the same topic does not
count. Answer on one line: "yes N" with the number N of the best matching candidate, or "no".'''

QUESTION_PROMPT = '''Two research questions.

Reference question:
[REF]

Candidate question:
[CAND]

How closely does the candidate ask the same research question as the reference?
5 = the same question; 4 = the same problem and aim, a different angle or scope; 3 = the same area and a related aim;
2 = the same area, a different aim; 1 = unrelated.
Answer with a single integer from 1 to 5.'''


def numbered(items: list[str]) -> str:
    return "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1))


def parse_items(block: str) -> list[str]:
    items, cur = [], None
    for line in block.splitlines():
        m = re.match(r"^\s*(?:\d+[.)]|[-*])\s+(.*\S)\s*$", line)
        if m:
            cur = m.group(1)
            items.append(cur)
        elif cur is not None and line.strip():
            items[-1] += " " + line.strip()
    return items


def baseline_candidates(path: Path) -> tuple[list[str], list[str]]:
    text = path.read_text(encoding="utf-8")
    g = re.search(r"^\s*GAPS\s*$", text, re.M)
    q = re.search(r"^\s*QUESTIONS\s*$", text, re.M)
    gaps = parse_items(text[g.end():q.start()] if g and q and g.end() < q.start() else (text[g.end():] if g else ""))
    questions = parse_items(text[q.end():] if q else "")
    return gaps, questions


def harness_candidates(session: Path) -> tuple[list[str], list[str], dict]:
    gaps = []
    p = session / "step7_gaps.json"
    if p.exists():
        for g in json.loads(p.read_text(encoding="utf-8")).get("gaps") or []:
            gaps.append(f"{g['title']}. {g.get('description', '')}".strip())
    questions, notes = [], {"question_files": 0}
    for f in sorted((session / "questions").glob("Q_*.md")) if (session / "questions").is_dir() else []:
        t = f.read_text(encoding="utf-8")
        m = re.search(r"^##\s*5\.\s*Research question\s*\n+(.*?)(?=\n##\s)", t, re.S | re.M)
        if m and m.group(1).strip():
            questions.append(" ".join(m.group(1).split()))
            notes["question_files"] += 1
    return gaps, questions, notes


def other_items(d: Path, rq_id: str, k: int) -> list[dict]:
    split = json.loads((d / "split.json").read_text(encoding="utf-8"))
    rows = {r["rq_id"]: r for r in (json.loads(x) for x in (d / "rq_dataset.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())}
    out = []
    for i in split["dev"]:                        # development items only
        if i == rq_id or len(out) >= k:
            continue
        refs = rows[i]["grounded_in_refs"]
        refs = refs if isinstance(refs, list) else ast.literal_eval(refs)
        out.append({"rq_id": i, "question": rows[i]["question"],
                    "gaps": [g["limitation"] for r in refs for g in (r.get("gaps") or [])]})
    return out


class Judge:
    def __init__(self, calls: CachedCalls, model: str):
        self.calls, self.model = calls, model

    def gap_covered(self, ref: str, candidates: list[str]) -> tuple[int, int]:
        if not candidates:
            return 0, 0
        prompt = GAP_PROMPT.replace("[REF]", ref).replace("[CANDIDATES]", numbered(candidates))
        text = self.calls(self.model, prompt, 24)["text"].strip().lower()
        m = re.match(r"^\W*yes\W*(\d+)?", text)
        return (1, int(m.group(1) or 0)) if m else (0, 0)

    def question_score(self, ref: str, cand: str) -> int | None:
        text = self.calls(self.model, QUESTION_PROMPT.replace("[REF]", ref).replace("[CAND]", cand), 8)["text"]
        m = re.match(r"^\W*([1-5])\W*$", text.strip())
        return int(m.group(1)) if m else None


def score_system(judge: Judge, gt: dict, gaps: list[str], questions: list[str]) -> dict:
    annotated = [(r["arxiv_id"], g["limitation"]) for r in gt["refs"] for g in r["gaps"]]
    cov = []
    for aid, lim in annotated:
        hit, idx = judge.gap_covered(lim, gaps)
        cov.append({"paper": aid, "annotated_gap": lim, "covered": hit, "matched_candidate": idx or None,
                    "candidate": gaps[idx - 1] if idx and idx <= len(gaps) else None})
    qs = [{"question": q, "score": judge.question_score(gt["question"], q)} for q in questions]
    valid = [x["score"] for x in qs if x["score"]]
    return {"n_candidate_gaps": len(gaps), "n_annotated_gaps": len(annotated),
            "gap_coverage": round(mean(c["covered"] for c in cov), 4) if cov else None, "gaps": cov,
            "n_candidate_questions": len(questions), "question_mean": round(mean(valid), 3) if valid else None,
            "question_best": max(valid) if valid else None, "questions": qs}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--judge", default="gemma4:31b")
    ap.add_argument("--controls", type=int, default=3, help="other development items used as the control")
    ap.add_argument("--data-dir", type=Path, default=DATA)
    ap.add_argument("--num-ctx", type=int, default=16384)
    args = ap.parse_args()
    batch = args.batch.resolve()
    eval_dir = batch_paths(batch)["eval"] / args.id
    session = batch / next(r["session_dir"] for r in read_runs(batch) if r["id"] == args.id)
    gt = read_json(eval_dir / "ground_truth.json")
    out_dir = eval_dir / "rqbench"
    judge = Judge(CachedCalls(out_dir / "calls.jsonl", {args.judge: OllamaChat(args.judge, args.num_ctx, think=False)}), args.judge)

    h_gaps, h_questions, notes = harness_candidates(session)
    b_gaps, b_questions = baseline_candidates(eval_dir / "baseline" / "output.md")
    result = {"rq_id": gt["rq_id"], "judge": args.judge, "reference_question": gt["question"],
              "harness": score_system(judge, gt, h_gaps, h_questions), "baseline": score_system(judge, gt, b_gaps, b_questions),
              "harness_notes": notes}
    # control: the same candidates against the references of other development items - they should not match
    ctrl = []
    for other in other_items(args.data_dir, gt["rq_id"], args.controls):
        fake = {"question": other["question"], "refs": [{"arxiv_id": "other", "gaps": [{"limitation": g} for g in other["gaps"]]}]}
        for name, gaps, qs in (("harness", h_gaps, h_questions), ("baseline", b_gaps, b_questions)):
            s = score_system(judge, fake, gaps, qs)
            ctrl.append({"other_item": other["rq_id"], "system": name, "gap_coverage": s["gap_coverage"], "question_mean": s["question_mean"],
                         "question_best": s["question_best"]})
    result["control_other_items"] = ctrl
    result["control_summary"] = {name: {"gap_coverage": round(mean(c["gap_coverage"] for c in ctrl if c["system"] == name and c["gap_coverage"] is not None), 3),
                                        "question_mean": round(mean(c["question_mean"] for c in ctrl if c["system"] == name and c["question_mean"] is not None), 3)}
                                 for name in ("harness", "baseline") if any(c["system"] == name and c["gap_coverage"] is not None for c in ctrl)}
    write_json(out_dir / "scores.json", result)

    lines = [f"# RQ-Bench {gt['rq_id']} (judge {args.judge})", "", f"Reference question: {gt['question']}", "",
             "| | candidate gaps | gap coverage (of the annotated) | candidate questions | question match mean / best (1-5) |", "|---|---|---|---|---|"]
    for name in ("harness", "baseline"):
        s = result[name]
        lines.append(f"| {name} | {s['n_candidate_gaps']} | {s['gap_coverage']} ({sum(g['covered'] for g in s['gaps'])}/{s['n_annotated_gaps']}) | "
                     f"{s['n_candidate_questions']} | {s['question_mean']} / {s['question_best']} |")
    lines += ["", f"Control (same candidates against other development items' references): {result['control_summary']}", "",
              "The harness's questions are read from questions/Q_*.md; check the run's ERRORS.md for whether B3.5 accepted them.", ""]
    for name in ("harness", "baseline"):
        lines += [f"## {name}: annotated gaps", ""]
        lines += [f"- {'COVERED' if g['covered'] else 'not covered'}: {g['annotated_gap'][:160]}" + (f"  <- {g['candidate'][:120]}" if g["candidate"] else "")
                  for g in result[name]["gaps"]]
        lines += ["", f"## {name}: questions", ""] + [f"- {q['score']}: {q['question'][:200]}" for q in result[name]["questions"]] + [""]
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:9]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
