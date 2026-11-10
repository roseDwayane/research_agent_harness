#!/usr/bin/env python3
"""Probe: are the citation claims a judge calls unsupported lost to the evidence retrieval?

autosurvey_eval.py judges a claim against, for each cited paper, its abstract plus the three 120-word windows of the full
text that overlap the claim most. For a claim that compares two papers ("A shortened waits while B lengthened them") the
windows are chosen by the whole claim, and a window can be the wrong half. This probe takes the claims judged
unsupported (full-text evidence) and judges them again with the cited papers' WHOLE full text as the source (no retrieval,
each paper cut at --max-chars). A claim that stays unsupported is not lost to the retrieval; one that becomes supported was.

    python evaluation/step06_sota/ab_evidence_probe.py --batch evaluation/runs/ab_dev --review review_173 [--judge gemma4:31b]

Reads eval/{review}/autosurvey/{system}.json (the expanded citations for the harness arm: one citation per paper), writes
eval/{review}/autosurvey/evidence_probe.json (+ probe_calls.jsonl, the cached judge calls). A diagnostic, not a metric:
the same judge, the same NLI prompt (autosurvey_prompts.NLI_PROMPT), only the evidence differs. Papers without a full text
keep their abstract and cannot be rescued; they are counted apart.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fulltext_retrieval  # noqa: E402
from autosurvey_common import OllamaChat, load_papers  # noqa: E402
from autosurvey_eval import CachedCalls, nli  # noqa: E402
from eval_common import batch_paths, read_json, write_json  # noqa: E402

SYSTEMS = ("step6", "naive", "naive_fulltext")


def whole_evidence(session: Path, papers: dict, key: str, max_chars: int) -> tuple[str, bool]:
    """(abstract + the whole full text cut at max_chars, whether there is a full text)."""
    abstract = papers[key]["abstract"] or papers[key]["title"]
    body = fulltext_retrieval.body_text(str(session / "step5_full_text" / f"{key}.md"))
    if not body.strip():
        return abstract, False
    return f"{abstract}\n\n{body[:max_chars]}", True


def probe(batch_dir: Path, review: str, judge: str, max_chars: int, max_papers: int, num_ctx: int) -> dict:
    eval_dir = batch_paths(batch_dir)["eval"] / review
    runs = [json.loads(line) for line in (batch_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    session = batch_dir / next(r["session_dir"] for r in runs if r["id"] == review)
    papers = load_papers(session)
    calls = CachedCalls(eval_dir / "autosurvey" / "probe_calls.jsonl", {judge: OllamaChat(judge, num_ctx, think=False)})
    out: dict = {"judge": judge, "max_chars_per_paper": max_chars, "systems": {}}
    for system in SYSTEMS:
        path = eval_dir / "autosurvey" / f"{system}.json"
        if not path.exists():
            continue
        result = read_json(path)
        block = (result.get("citations_expanded") or {}).get("fulltext") or (result.get("citations") or {}).get("fulltext")
        if not block:
            continue
        claims = [c for c in block["claims"] if c["keys"]]
        failing = [c for c in claims if not c.get("supported") and all(k in papers for k in c["keys"])]
        rows = []
        for c in failing:
            if len(c["keys"]) > max_papers:
                rows.append({"claim": c["claim"], "n_papers": len(c["keys"]), "skipped": f"more than {max_papers} papers"})
                continue
            ev = [whole_evidence(session, papers, k, max_chars) for k in c["keys"]]
            supported, raw = nli(calls, judge, c["claim"], [e[0] for e in ev])
            rows.append({"claim": c["claim"], "keys": c["keys"], "n_papers": len(c["keys"]),
                         "all_have_full_text": all(e[1] for e in ev), "supported_with_whole_papers": supported, "raw": raw[:40]})
        judged = [r for r in rows if "skipped" not in r]
        by_n = {}
        for n in sorted({r["n_papers"] for r in judged}):
            g = [r for r in judged if r["n_papers"] == n]
            by_n[str(n)] = {"failing_claims": len(g), "rescued": sum(r["supported_with_whole_papers"] for r in g),
                            "with_full_text_for_every_paper": sum(r["all_have_full_text"] for r in g),
                            "rescued_among_those": sum(r["supported_with_whole_papers"] for r in g if r["all_have_full_text"])}
        out["systems"][system] = {
            "cited_claims": len(claims), "failing_with_retrieved_evidence": len(failing), "judged_again": len(judged),
            "rescued": sum(r["supported_with_whole_papers"] for r in judged),
            "recall_retrieved": block.get("recall"),
            "recall_if_rescued_count_as_supported": round((len(claims) - len(failing) + sum(r["supported_with_whole_papers"] for r in judged)
                                                         + 0) / len(claims), 4) if claims else None,
            "by_papers_per_claim": by_n, "rows": rows}
    write_json(eval_dir / "autosurvey" / "evidence_probe.json", out)
    return out


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--review", required=True)
    ap.add_argument("--judge", default="gemma4:31b")
    ap.add_argument("--max-chars", type=int, default=16000, help="most characters of one paper's full text")
    ap.add_argument("--max-papers", type=int, default=3, help="claims citing more papers are skipped (the prompt would not fit)")
    ap.add_argument("--num-ctx", type=int, default=32768)
    args = ap.parse_args()
    out = probe(args.batch.resolve(), args.review, args.judge, args.max_chars, args.max_papers, args.num_ctx)
    for system, s in out["systems"].items():
        print(f"{system:<16} cited claims {s['cited_claims']:>3} | unsupported with retrieved evidence {s['failing_with_retrieved_evidence']:>3} "
              f"| judged again {s['judged_again']:>3} | supported with whole papers {s['rescued']:>3} | by papers per claim {s['by_papers_per_claim']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
