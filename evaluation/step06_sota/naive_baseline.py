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
    python evaluation/step06_sota/naive_baseline.py --batch ... --variant fulltext     # B2, see below

Writes eval/{topic}/naive/review.md and naive/meta.json   (variant abstract = B0, the default).

Variant `fulltext` (B2 of the with/without-harness comparison): the same prompt, the same papers, the same model and the
same abstracts as B0, and for every paper that was read from a full text, excerpts of that full text are added after its
abstract - the 120-word windows that share most words with the topic, in document order, windows that repeat the abstract
left out. The prompt template (NAIVE_SURVEY_PROMPT) is not changed; only the paper list under it is longer. The excerpts
share what is left of the context after the abstracts (an equal share per paper with a full text, at most
--max-fulltext-chars each), so B2's prompt is B0's prompt plus excerpts and nothing else. Papers without a full text are
as in B0, so a topic with no full text gives B0 exactly (meta.json says so). Writes eval/{topic}/naive_fulltext/.

Variant `compare` (B2c): B2's prompt, papers, excerpts and model, plus one paragraph before the last line of the prompt that
asks the model to compare the papers: where they agree, where they disagree and what the difference rests on, the conditions a
finding holds under, and assumptions the papers share but none tests (COMPARE_INSTRUCTION). It is the baseline given the
same task as the fusion block's collisions. NAIVE_SURVEY_PROMPT is not edited. Writes eval/{topic}/naive_fulltext_compare/.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # evaluation/: eval_common, run_batch

import fulltext_retrieval
from autosurvey_common import OllamaChat, load_papers, step6_survey, strip_fence
from autosurvey_prompts import NAIVE_SURVEY_PROMPT, fill
from eval_common import batch_paths, ollama_digest, read_json, read_runs, write_json

CHARS_PER_TOKEN = 3.5     # conservative for English abstracts; the real count is checked after the call
PROMPT_OVERHEAD = 1500    # tokens for the instructions around the paper list


# B2c: B2's prompt with one paragraph added before the last line. AutoSurvey's NAIVE_SURVEY_PROMPT itself is not edited.
COMPARE_INSTRUCTION = '''Before you write, compare the papers with one another. In the survey, say explicitly, and cite the papers involved:
- where two or more papers agree, and on what;
- where papers reach different or opposing results on the same question, and what the difference rests on (population, method, dose, data, definition, time);
- the conditions under which a finding holds or does not hold, as far as the papers show them;
- assumptions that several papers share but none of them tests.
State a disagreement only when the papers themselves support it; if the papers cannot be compared, say so.

'''
LAST_LINE = "Return only the survey."
VARIANT_DIRS = {"abstract": "naive", "fulltext": "naive_fulltext", "compare": "naive_fulltext_compare"}


def paper_block(papers: dict[str, dict], abstract_chars: int) -> str:
    lines = []
    for key, p in papers.items():
        abstract = p["abstract"]
        if len(abstract) > abstract_chars:
            abstract = abstract[:abstract_chars].rsplit(" ", 1)[0] + " …"
        lines.append(f"[{key}] {p['title']} ({p['year']})\n{abstract or '(no abstract available)'}")
    return "\n\n".join(lines)


def build_prompt(topic: str, papers: dict[str, dict], words: int, input_tokens: int, max_abstract_chars: int,
                 excerpts: dict[str, str] | None = None, compare: bool = False) -> tuple[str, int]:
    """`excerpts` ({key: text}) are appended after a paper's abstract (variant fulltext); None gives B0 unchanged.
    `compare` adds COMPARE_INSTRUCTION before the last line (variant compare = B2c)."""
    budget_chars = int((input_tokens - PROMPT_OVERHEAD) * CHARS_PER_TOKEN)
    header_chars = sum(len(k) + len(p["title"]) + 12 for k, p in papers.items())
    abstract_chars = max(200, min(max_abstract_chars, (budget_chars - header_chars) // max(len(papers), 1)))
    block = paper_block(papers, abstract_chars)
    if excerpts:
        block = paper_block_with_excerpts(papers, abstract_chars, excerpts)
    prompt = fill(NAIVE_SURVEY_PROMPT, {"TOPIC": topic, "N": str(len(papers)), "WORDS": str(words), "PAPERS": block})
    if compare:
        assert prompt.count(LAST_LINE) == 1
        prompt = prompt.replace(LAST_LINE, COMPARE_INSTRUCTION + LAST_LINE)
    return prompt, abstract_chars


# --------------------------------------------------------------------------- #
# B2: full-text excerpts
# --------------------------------------------------------------------------- #
FULLTEXT_LEVELS = ("full-text-pdf", "full-text-html", "partial-text-html", "full-text")
EXCERPT_OVERLAP_WITH_ABSTRACT = 0.6   # a window sharing more of its words with the abstract repeats it


def paper_block_with_excerpts(papers: dict[str, dict], abstract_chars: int, excerpts: dict[str, str]) -> str:
    """paper_block (B0's text, unchanged) with `Excerpts from the full text:` after the abstract of papers that have any."""
    lines = []
    for key, p in papers.items():
        abstract = p["abstract"]
        if len(abstract) > abstract_chars:
            abstract = abstract[:abstract_chars].rsplit(" ", 1)[0] + " …"
        text = f"[{key}] {p['title']} ({p['year']})\n{abstract or '(no abstract available)'}"
        if excerpts.get(key):
            text += f"\nExcerpts from the full text:\n{excerpts[key]}"
        lines.append(text)
    return "\n\n".join(lines)


def fulltext_excerpt(session: Path, key: str, topic: str, abstract: str, chars: int) -> str:
    """The non-overlapping 120-word windows of the paper's full text that share most words with the topic, in document
    order, up to `chars` characters; windows that mostly repeat the abstract are skipped. '' if there is no full text."""
    wins = fulltext_retrieval.windows(str(session / "step5_full_text" / f"{key}.md"))[::2]  # stride 60 -> 120: no overlap
    if not wins or chars <= 0:
        return ""
    query = set(fulltext_retrieval.tokens(topic))
    abs_tokens = set(fulltext_retrieval.tokens(abstract))
    scored = []
    for i, w in enumerate(wins):
        toks = fulltext_retrieval.tokens(w)
        uniq = set(toks)
        if uniq and len(uniq & abs_tokens) / len(uniq) > EXCERPT_OVERLAP_WITH_ABSTRACT:
            continue
        scored.append((-sum(t in query for t in toks), i))
    picked, used = [], 0
    for _, i in sorted(scored):
        cost = len(wins[i]) + 6
        if used + cost > chars:
            continue
        picked.append(i)
        used += cost
    return "\n".join(f"… {wins[i]} …" for i in sorted(picked))


def plan_excerpts(session: Path, topic: str, papers: dict[str, dict], input_tokens: int, max_abstract_chars: int,
                  max_fulltext_chars: int) -> dict[str, str]:
    """An equal share of the context left after B0's prompt, for every paper read from a full text."""
    budget_chars = int((input_tokens - PROMPT_OVERHEAD) * CHARS_PER_TOKEN)
    header_chars = sum(len(k) + len(p["title"]) + 12 for k, p in papers.items())
    abstract_chars = max(200, min(max_abstract_chars, (budget_chars - header_chars) // max(len(papers), 1)))
    used = header_chars + sum(min(len(p["abstract"]), abstract_chars) + 30 for p in papers.values())
    have = [k for k, p in papers.items() if (p.get("access_level") or "") in FULLTEXT_LEVELS]
    if not have:
        return {}
    share = min(max_fulltext_chars, max(0, (budget_chars - used) // len(have)) - 40)
    return {k: fulltext_excerpt(session, k, topic, papers[k]["abstract"], share) for k in have}


def run_topic(record: dict, batch_dir: Path, llm: dict, args: argparse.Namespace) -> dict:
    out_dir = batch_paths(batch_dir)["eval"] / record["id"] / VARIANT_DIRS[args.variant]
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
    input_tokens = int(llm["num_ctx"]) - max_tokens
    excerpts = (plan_excerpts(session, config["topic"], papers, input_tokens, args.max_abstract_chars, args.max_fulltext_chars)
                if args.variant in ("fulltext", "compare") else None)
    prompt, abstract_chars = build_prompt(config["topic"], papers, words, input_tokens, args.max_abstract_chars, excerpts,
                                          compare=args.variant == "compare")

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
        "variant": args.variant,
    }
    if args.variant in ("fulltext", "compare"):
        meta.update({
            "n_papers_with_fulltext": sum(1 for p in papers.values() if (p.get("access_level") or "") in FULLTEXT_LEVELS),
            "n_papers_with_excerpt": sum(1 for t in (excerpts or {}).values() if t),
            "excerpt_chars_total": sum(len(t) for t in (excerpts or {}).values()),
            "identical_to_abstract_variant": not any((excerpts or {}).values()),
        })
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
    parser.add_argument("--variant", choices=list(VARIANT_DIRS), default="abstract",
                        help="abstract = B0 (default); fulltext = B2, the same prompt with excerpts of the full texts added; "
                             "compare = B2c, B2 plus a paragraph asking to compare the papers (agreement, disagreement, conditions, "
                             "untested shared assumptions)")
    parser.add_argument("--max-fulltext-chars", type=int, default=6000, help="variant fulltext: most excerpt characters per paper")
    args = parser.parse_args()

    batch_dir = Path(args.batch).resolve()
    llm = read_json(batch_paths(batch_dir)["batch"])["protocol"]["config"]["llm"]
    if llm.get("provider") != "ollama":
        raise SystemExit(f"naive_baseline.py only drives Ollama; batch uses {llm.get('provider')!r}")
    runs = [r for r in read_runs(batch_dir) if not args.only or r["id"] in args.only]
    status_path = batch_paths(batch_dir)["eval"] / f"{VARIANT_DIRS[args.variant]}_status.json"
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
