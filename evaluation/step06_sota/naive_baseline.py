#!/usr/bin/env python3
"""Phase A2 — naive RAG baseline survey per topic (AutoSurvey's "Naive RAG-based LLM" baseline).

Same papers, same model as the batch's Steps 1–6: every paper in the session's
step4_references.bib (title, year, abstract from step5_full_text) goes into ONE prompt that
asks for a whole survey (autosurvey_prompts.NAIVE_SURVEY_PROMPT). No outline, no per-section
writing, no digests. Same papers and model as Step 6; what differs is Step 6's method (per-paper
digests of the full text, then synthesis by theme) versus one prompt over abstracts only.

* model / num_ctx / temperature / think come from batch.json, so the baseline uses the
  pipeline's model; max_tokens likewise;
* abstracts are cut to an equal per-paper length so the prompt fits num_ctx - max_tokens;
* the requested length is the Step 6 English review's word count (AutoSurvey compares at
  matched lengths); topics whose Step 6 failed get --default-words.

    python evaluation/step06_sota/naive_baseline.py --batch evaluation/runs/<batch_id> [--only <topic_id> ...]

Writes eval/{topic}/naive/review.md and naive/meta.json.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # evaluation/: eval_common, run_batch

from autosurvey_common import OllamaChat, load_papers, step6_survey, strip_fence
from autosurvey_prompts import NAIVE_SURVEY_PROMPT, fill
from eval_common import batch_paths, ollama_digest, read_json, read_runs, write_json

CHARS_PER_TOKEN = 3.5     # conservative for English abstracts; the real count is checked after the call
PROMPT_OVERHEAD = 1500    # tokens for the instructions around the paper list


def paper_block(papers: dict[str, dict], abstract_chars: int) -> str:
    lines = []
    for key, p in papers.items():
        abstract = p["abstract"]
        if len(abstract) > abstract_chars:
            abstract = abstract[:abstract_chars].rsplit(" ", 1)[0] + " …"
        lines.append(f"[{key}] {p['title']} ({p['year']})\n{abstract or '(no abstract available)'}")
    return "\n\n".join(lines)


def build_prompt(topic: str, papers: dict[str, dict], words: int, input_tokens: int, max_abstract_chars: int) -> tuple[str, int]:
    budget_chars = int((input_tokens - PROMPT_OVERHEAD) * CHARS_PER_TOKEN)
    header_chars = sum(len(k) + len(p["title"]) + 12 for k, p in papers.items())
    abstract_chars = max(200, min(max_abstract_chars, (budget_chars - header_chars) // max(len(papers), 1)))
    prompt = fill(NAIVE_SURVEY_PROMPT, {"TOPIC": topic, "N": str(len(papers)), "WORDS": str(words),
                                        "PAPERS": paper_block(papers, abstract_chars)})
    return prompt, abstract_chars


def run_topic(record: dict, batch_dir: Path, llm: dict, args: argparse.Namespace) -> dict:
    out_dir = batch_paths(batch_dir)["eval"] / record["id"] / "naive"
    if "session_dir" not in record:
        return {"status": "no_session"}
    session = batch_dir / record["session_dir"]
    if not (session / "step4_references.bib").exists() or not (session / "step5_full_text").is_dir():
        return {"status": "no_step5"}
    if (out_dir / "review.md").exists() and (out_dir / "meta.json").exists() and not args.force:
        meta = read_json(out_dir / "meta.json")
        return {"status": "ok", "reused": True, "words": meta["output_words"], "target": meta["target_words"],
                "done_reason": meta["done_reason"]}

    config = read_json(session / "step0_session_config.json")
    papers = load_papers(session)
    step6 = session / "step6_sota_review.md"
    words = len(step6_survey(step6.read_text(encoding="utf-8")).split()) if step6.exists() else args.default_words
    max_tokens = int(llm.get("max_tokens", 8192))
    prompt, abstract_chars = build_prompt(config["topic"], papers, words, int(llm["num_ctx"]) - max_tokens,
                                          args.max_abstract_chars)

    chat = OllamaChat(llm["model"], int(llm["num_ctx"]), think=llm.get("think"), base_url=llm.get("base_url", "http://127.0.0.1:11434"),
                      timeout=float(llm.get("request_timeout", 1800)))
    result = chat(prompt, num_predict=max_tokens, temperature=float(llm.get("temperature", 0.0)))
    review = strip_fence(result["text"]).strip() + "\n"

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "review.md").write_text(review, encoding="utf-8")
    meta = {
        "topic": config["topic"], "model": llm["model"], "ollama_digest": ollama_digest(llm["model"]),
        "num_ctx": llm["num_ctx"], "max_tokens": max_tokens, "temperature": llm.get("temperature", 0.0),
        "think": llm.get("think"), "n_papers": len(papers),
        "n_papers_without_abstract": sum(not p["abstract"] for p in papers.values()),
        "abstract_chars_per_paper": abstract_chars, "target_words": words,
        "target_words_from": "step6_english" if step6.exists() else "default",
        "output_words": len(review.split()), "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt_tokens": result["prompt_tokens"], "output_tokens": result["output_tokens"],
        "done_reason": result["done_reason"], "truncated": result["done_reason"] == "length",
    }
    write_json(out_dir / "meta.json", meta)
    (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    return {"status": "ok", "words": meta["output_words"], "target": words, "done_reason": meta["done_reason"]}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--only", nargs="+")
    parser.add_argument("--default-words", type=int, default=2500)
    parser.add_argument("--max-abstract-chars", type=int, default=1500)
    parser.add_argument("--force", action="store_true", help="regenerate existing baselines")
    args = parser.parse_args()

    batch_dir = Path(args.batch).resolve()
    llm = read_json(batch_paths(batch_dir)["batch"])["protocol"]["config"]["llm"]
    if llm.get("provider") != "ollama":
        raise SystemExit(f"naive_baseline.py only drives Ollama; batch uses {llm.get('provider')!r}")
    runs = [r for r in read_runs(batch_dir) if not args.only or r["id"] in args.only]
    status_path = batch_paths(batch_dir)["eval"] / "naive_status.json"
    status = read_json(status_path) if status_path.exists() else {}
    for i, record in enumerate(runs, 1):
        print(f"[{i}/{len(runs)}] {record['id']} …", flush=True)
        try:
            status[record["id"]] = run_topic(record, batch_dir, llm, args)
        except Exception as exc:  # noqa: BLE001 — one topic's failure is recorded, not fatal
            status[record["id"]] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        print(f"  → {status[record['id']]}", flush=True)
        write_json(status_path, status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
