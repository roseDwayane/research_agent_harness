#!/usr/bin/env python3
"""Score MetaSyn fixed-input Step 6 reviews against the source review's Key Insights and direction.

Per review (``eval/review_{id}/`` from metasyn_prepare.py):

1. classify   each ground-truth Key Insight → synthesis | pooled_estimate | meta_analysis_specific | external,
              with a number-free restatement ("claim") for synthesis items. Written once to
              ``insight_classes.json`` and reused afterwards, so it can be checked and corrected by hand.
2. digest     for every synthesis claim: is the evidence in the Step 6 per-paper digests?
              (supported | partial | not_supported) → "answerable" = supported or partial.
3. coverage   for every synthesis claim: does the review state it?
              (covered 1 | partial 0.5 | not_covered 0 | contradicted 0), with an exact quote that is checked.
4. official   MetaSyn's own prompts, verbatim: conclusion direction (+ accuracy) and the holistic
              0–1 insights_consistency, for comparison with their published numbers.

Main score = mean coverage over answerable synthesis claims. With ``--controls`` the review is also
scored in damaged forms (half the themes removed, Executive Summary only, another topic's review);
coverage must drop for the score to be trusted.

    python evaluation/step06_sota/metasyn_eval.py --batch evaluation/runs/metasyn_smoke [--judge gemma4:31b] [--controls]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # evaluation/: eval_common, run_batch

from autosurvey_common import OllamaChat, step6_survey  # noqa: E402
from autosurvey_eval import CachedCalls  # noqa: E402
from eval_common import RUNS_ROOT, ollama_digest, read_json, write_json  # noqa: E402
from metasyn_prompts import (  # noqa: E402
    CLASSIFY_PROMPT, COVERAGE_PROMPT, DIGEST_PROMPT, OFFICIAL_EXTRACT_PROMPT, OFFICIAL_INSIGHTS_PROMPT,
)

CATEGORIES = ("synthesis", "pooled_estimate", "meta_analysis_specific", "external", "generic")
COVERAGE_SCORE = {"covered": 1.0, "partial": 0.5, "not_covered": 0.0, "contradicted": 0.0}
DIGEST_VERDICTS = ("supported", "partial", "not_supported")
DIRECTIONS = ("Positive", "Negative", "Mixed")
DEFAULT_OFFTOPIC = RUNS_ROOT / "smoke1" / "sessions"
METASYN_RESULTS = "https://raw.githubusercontent.com/THUIR/MetaSyn/main/generation_results"


def parse_json(text: str | None) -> dict | None:
    """Last JSON object in the reply: judges sometimes answer, then post a corrected answer."""
    text, decoder, last, pos = text or "", json.JSONDecoder(), None, 0
    while (start := text.find("{", pos)) != -1:
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            pos = start + 1
            continue
        if isinstance(value, dict):
            last = value
        pos = end  # skip nested objects of a top-level match
    return last


def norm(text: str) -> str:
    """Letters and digits only, so markdown emphasis and punctuation spacing do not break quote matching."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def gt_items(key_insights: str) -> list[str]:
    """Same item split as MetaSyn's evaluator (lines longer than 20 characters), bullet removed."""
    return [re.sub(r"^\s*[-*•]\s*", "", s).strip() for s in key_insights.split("\n") if s.strip() and len(s) > 20]


# --------------------------------------------------------------------------- #
# texts
# --------------------------------------------------------------------------- #
def sections(text: str) -> list[tuple[str, str]]:
    out, head, buf = [], "", []
    for line in text.splitlines():
        if re.match(r"^##\s", line):
            if head or buf:
                out.append((head, "\n".join(buf)))
            head, buf = line[3:].strip(), [line]
        else:
            buf.append(line)
    out.append((head, "\n".join(buf)))
    return out


def damaged(text: str) -> dict[str, str]:
    secs = sections(text)
    themes = [i for i, (h, _) in enumerate(secs) if re.match(r"Theme\s+\d+", h, re.I)]
    drop = set(themes[1::2])
    summary = [b for h, b in secs if h.lower().startswith("executive summary")]
    return {
        "half_themes_removed": "\n".join(b for i, (_, b) in enumerate(secs) if i not in drop),
        "summary_only": "\n".join(summary),
    }


def offtopic_text(path: Path | None, own_session: Path) -> str | None:
    if path is None:
        candidates = sorted(DEFAULT_OFFTOPIC.glob("*/step6_sota_review.md")) if DEFAULT_OFFTOPIC.exists() else []
        candidates = [p for p in candidates if p.parent != own_session]
        path = candidates[0] if candidates else None
    return step6_survey(path.read_text(encoding="utf-8")) if path and path.exists() else None


def baseline_report(review_dir: Path, config: str, review_id: int) -> str:
    """A MetaSyn baseline's original report for this review, downloaded once into baselines/."""
    path = review_dir / "baselines" / f"{config}.md"
    if not path.exists():
        r = requests.get(f"{METASYN_RESULTS}/{config}/review_{review_id}/report.md", timeout=60)
        r.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(r.text, encoding="utf-8")
    return path.read_text(encoding="utf-8")


def digest_text(digests: dict[str, dict]) -> str:
    blocks = []
    for key, d in digests.items():
        blocks.append("\n".join([
            f"### {key}",
            f"Problem: {d.get('problem', '')}",
            f"Sample/dataset: {d.get('sample_or_dataset', '')}",
            "Results: " + " | ".join(d.get("key_results", [])),
            "Limitations: " + " | ".join(d.get("limitations", [])),
        ]))
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- #
# judging
# --------------------------------------------------------------------------- #
class Judge:
    def __init__(self, calls: CachedCalls, model: str):
        self.calls, self.model = calls, model

    def ask(self, prompt: str, num_predict: int) -> tuple[dict | None, dict]:
        reply = self.calls(self.model, prompt, num_predict)
        return parse_json(reply["text"]), {"call_id": reply["id"], "done_reason": reply.get("done_reason")}

    def classify(self, question: str, insight: str) -> dict:
        parsed, meta = self.ask(CLASSIFY_PROMPT.format(question=question, insight=insight), 400)
        cat = (parsed or {}).get("category")
        if cat not in CATEGORIES:
            return {"insight": insight, "category": None, "claim": "", "status": "no_result", **meta}
        return {"insight": insight, "category": cat, "claim": (parsed.get("claim") or "").strip() if cat == "synthesis" else "",
                "reason": parsed.get("reason", ""), "status": "valid", **meta}

    def digest(self, claim: str, text: str) -> dict:
        parsed, meta = self.ask(DIGEST_PROMPT.format(claim=claim, text=text), 500)
        verdict = (parsed or {}).get("verdict")
        if verdict not in DIGEST_VERDICTS:
            return {"verdict": None, "status": "no_result", **meta}
        return {"verdict": verdict, "keys": parsed.get("keys", []), "reason": parsed.get("reason", ""), "status": "valid", **meta}

    def coverage(self, question: str, claim: str, text: str) -> dict:
        parsed, meta = self.ask(COVERAGE_PROMPT.format(question=question, claim=claim, text=text), 500)
        verdict = (parsed or {}).get("verdict")
        if verdict not in COVERAGE_SCORE:
            return {"verdict": None, "score": None, "status": "no_result", **meta}
        quote = (parsed.get("quote") or "").strip()
        return {"verdict": verdict, "score": COVERAGE_SCORE[verdict], "quote": quote,
                "quote_found": (norm(quote) in norm(text)) if quote else None,
                "reason": parsed.get("reason", ""), "status": "valid", **meta}

    def official(self, text: str, gt_insights: str, gt_direction: str) -> dict:
        parsed, meta = self.ask(OFFICIAL_EXTRACT_PROMPT.format(report_text=text), 3000)
        direction = (parsed or {}).get("conclusion_direction")
        insights = [x for x in (parsed or {}).get("key_insights", []) if isinstance(x, str) and x.strip()]
        out: dict[str, Any] = {"direction": direction if direction in DIRECTIONS else None, "extracted_insights": insights, "extract": meta}
        out["direction_accuracy"] = int(direction == gt_direction) if out["direction"] and gt_direction in DIRECTIONS else None
        items = [s.strip() for s in gt_insights.split("\n") if s.strip() and len(s) > 20]
        if not insights:
            out["insights_consistency"] = 0.0 if parsed is not None else None
            return out
        parsed2, meta2 = self.ask(OFFICIAL_INSIGHTS_PROMPT.format(gt_text="\n".join(items), extracted_text="\n".join(insights)), 400)
        score = (parsed2 or {}).get("consistency_score")
        out["insights_consistency"] = float(score) if isinstance(score, (int, float)) and 0 <= score <= 1 else None
        out["insights_reason"], out["consistency"] = (parsed2 or {}).get("reason", ""), meta2
        return out


def mean_or_none(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(mean(vals), 4) if vals else None


def score_text(judge: Judge, question: str, claims: list[dict], text: str) -> dict:
    items = [{**c, **judge.coverage(question, c["claim"], text)} for c in claims]
    answerable = [i for i in items if i["answerable"]]
    return {
        "coverage_answerable": mean_or_none([i["score"] for i in answerable]),
        "coverage_all": mean_or_none([i["score"] for i in items]),
        "n_answerable": len(answerable), "n_claims": len(items),
        "contradicted": sum(1 for i in items if i["verdict"] == "contradicted"),
        "quotes_not_found": sum(1 for i in items if i.get("quote_found") is False),
        "no_result": sum(1 for i in items if i["status"] != "valid"),
        "items": items,
    }


# --------------------------------------------------------------------------- #
def evaluate_review(review_dir: Path, batch_dir: Path, judge: Judge, args: argparse.Namespace) -> dict:
    gt = read_json(review_dir / "ground_truth.json")
    report = read_json(review_dir / "input_report.json")
    session = batch_dir / report["session_dir"]
    review_md = (session / "step6_sota_review.md").read_text(encoding="utf-8")
    survey = step6_survey(review_md)
    digests = read_json(session / "step6_paper_digests.json")
    question = gt.get("Research_Question") or gt["Topic"]

    classes_path = review_dir / "insight_classes.json"
    if classes_path.exists():
        classes = read_json(classes_path)["items"]
    else:
        classes = [judge.classify(question, s) for s in gt_items(gt["Key_Insights"])]
        write_json(classes_path, {"review_id": gt["review_id"], "classified_by": judge.model, "frozen": False,
                                  "note": "edit category/claim by hand if needed, then set frozen=true", "items": classes})

    dtext = digest_text(digests)
    claims = []
    for i, c in enumerate(classes):
        if c.get("category") != "synthesis":
            continue
        # Judge against the original insight: the number-free restatement can soften it (review 255:
        # "cannot be considered state-of-the-art" became "not the superior standard of care").
        d = judge.digest(c["insight"], dtext)
        claims.append({"index": i, "claim": c["insight"], "restated": c.get("claim", ""), "digest": d,
                       "answerable": d["verdict"] in ("supported", "partial")})

    texts = {"step6": survey}
    if args.controls:
        texts.update(damaged(survey))
        off = offtopic_text(args.offtopic, session)
        if off:
            texts["offtopic"] = off
    naive = review_dir / "naive" / "review.md"
    if args.naive and naive.exists():
        texts["naive"] = naive.read_text(encoding="utf-8")
    baselines = {f"baseline:{c}": baseline_report(review_dir, c, gt["review_id"]) for c in args.baselines}
    texts.update(baselines)
    systems = {name: score_text(judge, question, claims, text) for name, text in texts.items()}
    for name in ["step6", *(["naive"] if "naive" in texts else []), *baselines]:
        systems[name]["official"] = judge.official(texts[name], gt["Key_Insights"], gt["Effect_Direction"])
    for name, text in texts.items():
        systems[name]["words"] = len(text.split())

    return {
        "review_id": gt["review_id"], "topic": gt["Topic"], "gt_direction": gt["Effect_Direction"],
        "insights": {"total": len(classes), **{c: sum(1 for x in classes if x.get("category") == c) for c in CATEGORIES},
                     "unclassified": sum(1 for x in classes if x.get("category") is None)},
        "classes_frozen": bool(read_json(classes_path).get("frozen")),
        "systems": systems,
    }


def print_review(r: dict) -> None:
    ins = r["insights"]
    print(f"\n== review {r['review_id']}: {r['topic']}")
    print(f"   insights {ins['total']}: synthesis {ins['synthesis']}, pooled {ins['pooled_estimate']}, "
          f"MA-specific {ins['meta_analysis_specific']}, external {ins['external']}, generic {ins['generic']}, unclassified {ins['unclassified']}"
          f"{'' if r['classes_frozen'] else '  (classes not frozen)'}")
    for name, s in r["systems"].items():
        print(f"   {name:<20} coverage answerable={s['coverage_answerable']} ({s['n_answerable']}/{s['n_claims']})  "
              f"all={s['coverage_all']}  contradicted={s['contradicted']}  quotes_not_found={s['quotes_not_found']}  words={s['words']}")
    for name, s in r["systems"].items():
        if "official" in s:
            off = s["official"]
            print(f"   official {name:<45} direction={off['direction']} (gt {r['gt_direction']}, acc={off['direction_accuracy']})  "
                  f"insights_consistency={off['insights_consistency']}")
    for item in r["systems"]["step6"]["items"]:
        print(f"   [{item['index']}] digest={str(item['digest']['verdict']):<13} review={str(item['verdict']):<13} {item['claim'][:90]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--reviews", nargs="*", type=int, help="review ids (default: every eval/review_*)")
    ap.add_argument("--judge", default="gemma4:31b")
    ap.add_argument("--num-ctx", type=int, default=32768)
    ap.add_argument("--controls", action="store_true", help="also score damaged forms of each review")
    ap.add_argument("--offtopic", type=Path, default=None, help="step6_sota_review.md used as the off-topic control")
    ap.add_argument("--naive", action="store_true", help="also score eval/review_*/naive/review.md (naive_baseline.py)")
    ap.add_argument("--baselines", nargs="*", default=[],
                    help="MetaSyn generation_results configs to score with the same judge, e.g. gptresearcher__gpt-5.4__ma_retriever")
    args = ap.parse_args()

    batch_dir = args.batch
    review_dirs = sorted((batch_dir / "eval").glob("review_*"))
    if args.reviews:
        review_dirs = [d for d in review_dirs if int(d.name.split("_")[1]) in args.reviews]
    results = {}
    for review_dir in review_dirs:
        out_dir = review_dir / "metasyn"
        judge = Judge(CachedCalls(out_dir / "calls.jsonl", {args.judge: OllamaChat(args.judge, num_ctx=args.num_ctx, think=False)}), args.judge)
        r = evaluate_review(review_dir, batch_dir, judge, args)
        r["judge"] = {"model": args.judge, "ollama_digest": ollama_digest(args.judge), "num_ctx": args.num_ctx, "think": False}
        write_json(out_dir / f"{args.judge.replace(':', '_')}.json", r)
        results[r["review_id"]] = r
        print_review(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
