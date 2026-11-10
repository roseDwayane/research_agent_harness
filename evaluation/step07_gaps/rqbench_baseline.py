#!/usr/bin/env python3
"""Baseline for the RQ-Bench pilot: the same model reads the same cited papers in ONE prompt and lists the gaps and the
research questions.

    python evaluation/step07_gaps/rqbench_baseline.py --batch evaluation/runs/rq_dev --id rq_2501_01329_rq0

The harness arm reads the cited papers through a long pipeline (per-paper deconstruction, alignment, collisions, gaps,
questions). This is what it is compared with: no pipeline, one call, the model and the sampling settings of the harness arm
(batch.json), the topic of the harness's topic file, and the same papers. The papers are far longer than the model's
context (three cited papers are 70k-160k characters each), so each is cut to an equal share of the prompt: its abstract,
then the sections most likely to state what is left open (introduction, limitations, discussion, conclusion, future work,
related work, threats) and then the remaining sections in order, every section cut at the same length. The prompt is ours:
RQ-Bench does not prescribe one.

Writes eval/<id>/baseline/{output.md, meta.json, prompt.txt}.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "step06_sota"))

from autosurvey_common import OllamaChat, load_papers  # noqa: E402
from eval_common import batch_paths, ollama_digest, read_json, read_runs, write_json  # noqa: E402

CHARS_PER_TOKEN = 3.5
PROMPT_OVERHEAD = 1200
PRIORITY = re.compile(r"introduction|limitation|discussion|conclusion|future|related work|threat|background|motivation", re.I)

PROMPT = '''You are a researcher reading [N] papers that a later study builds on. Topic: [TOPIC].

Each paper is given with its citation key, title and text (its abstract, then excerpts of its sections).
---
[PAPERS]
---

Do two things.

1. GAPS. List up to [G] research gaps that these papers leave open: a limitation of the existing work, or a question
that none of them settles, which a new study could take up. One or two sentences each; say which papers it concerns by
citation key.

2. QUESTIONS. Propose [K] research questions that a new study could investigate, ordered from the one that follows best
from the gaps. Each question is a single specific sentence that a study could answer.

Answer in exactly this form:
GAPS
1. ...
QUESTIONS
1. ...
'''


def sections_of(md: str) -> list[tuple[str, str]]:
    out, head, buf = [], "", []
    for line in md.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            if head or buf:
                out.append((head, "\n".join(buf).strip()))
            head, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    out.append((head, "\n".join(buf).strip()))
    return [(h, t) for h, t in out if t]


def paper_text(md: str, abstract: str, budget: int, per_section: int = 3500) -> str:
    """The abstract, then priority sections, then the others, in order, each cut at `per_section`, up to `budget` characters."""
    text = [abstract[:2000]] if abstract else []
    used = len(text[0]) if text else 0
    secs = [(h, t) for h, t in sections_of(md) if h.lower() not in ("abstract", "")]
    ordered = [s for s in secs if PRIORITY.search(s[0])] + [s for s in secs if not PRIORITY.search(s[0])]
    for h, t in ordered:
        take = min(len(t), per_section, budget - used - len(h) - 12)
        if take < 400:
            break
        text.append(f"[{h}] {t[:take]}")
        used += take + len(h) + 12
    return "\n".join(text)


def build_prompt(topic: str, papers: dict[str, dict], texts: dict[str, str], input_tokens: int, gaps: int, questions: int) -> tuple[str, int]:
    budget_total = int((input_tokens - PROMPT_OVERHEAD) * CHARS_PER_TOKEN)
    per_paper = budget_total // max(len(papers), 1) - 200
    blocks = []
    for key, p in papers.items():
        blocks.append(f"[{key}] {p['title']}\n{paper_text(texts[key], p['abstract'], per_paper)}")
    body = (PROMPT.replace("[N]", str(len(papers))).replace("[TOPIC]", topic).replace("[G]", str(gaps))
            .replace("[K]", str(questions)).replace("[PAPERS]", "\n\n".join(blocks)))
    return body, per_paper


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--gaps", type=int, default=5)
    ap.add_argument("--questions", type=int, default=5)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    batch = args.batch.resolve()
    out_dir = batch_paths(batch)["eval"] / args.id / "baseline"
    if (out_dir / "output.md").exists() and not args.force:
        print("baseline exists (use --force)")
        return 0
    session = batch / next(r["session_dir"] for r in read_runs(batch) if r["id"] == args.id)
    llm = read_json(batch_paths(batch)["batch"])["protocol"]["config"]["llm"]
    cfg = read_json(session / "step0_session_config.json")
    papers = load_papers(session)
    texts = {k: (session / "step5_full_text" / f"{k}.md").read_text(encoding="utf-8") for k in papers}
    max_tokens = int(llm.get("max_tokens", 8192))
    prompt, per_paper = build_prompt(cfg["topic"], papers, texts, int(llm["num_ctx"]) - max_tokens, args.gaps, args.questions)
    chat = OllamaChat(llm["model"], int(llm["num_ctx"]), think=llm.get("think"), base_url=llm.get("base_url", "http://127.0.0.1:11434"),
                      timeout=float(llm.get("request_timeout", 1800)))
    res = chat(prompt, num_predict=max_tokens, temperature=float(llm.get("temperature", 0.0)))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "output.md").write_text(res["text"].strip() + "\n", encoding="utf-8")
    (out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json(out_dir / "meta.json", {
        "model": llm["model"], "ollama_digest": ollama_digest(llm["model"]), "num_ctx": llm["num_ctx"], "max_tokens": max_tokens,
        "temperature": llm.get("temperature", 0.0), "n_papers": len(papers), "chars_per_paper": per_paper,
        "full_text_chars": {k: len(t) for k, t in texts.items()}, "prompt_chars": len(prompt),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "prompt_tokens": res["prompt_tokens"],
        "output_tokens": res["output_tokens"], "done_reason": res["done_reason"]})
    print(f"{args.id}: {len(papers)} papers, {per_paper} chars each of {sum(len(t) for t in texts.values())} in total; "
          f"{res['prompt_tokens']} prompt tokens, {res['output_tokens']} output tokens, {res['done_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
