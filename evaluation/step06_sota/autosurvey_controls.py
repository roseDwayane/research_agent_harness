#!/usr/bin/env python3
"""Do the AutoSurvey criteria track quality? Judge each whole Step 6 survey again in damaged forms.

Same judge call as autosurvey_eval.py (verbatim AutoSurvey prompt, whole survey, strict 1–5
parsing, shared calls.jsonl cache). Damage is deterministic (SEED):

    original            the English Step 6 survey as autosurvey_eval.py judges it
    themes_reversed     Theme sections in reverse order                       Structure (mild)
    theme_repeated      Theme 1 appears again after the last Theme            Structure ("without redundancy")
    one_theme_shuffled  sentences of Theme 1 only shuffled, its subheadings   Structure (is local damage diluted?)
                        removed
    all_shuffled        every sentence / row of the survey shuffled,          Structure (severe)
                        all ##/### headings removed
    half_themes         every second Theme removed                            Coverage
    summary_only        title + Executive Summary only                        Coverage (severe)
    foreign_theme       Theme 2 replaced by a Theme from another topic's      Relevance
                        Step 6 review (next topic in the batch)

A judge that discriminates scores each damaged form lower on its target criterion.

--level section judges each review section (Executive Summary, Theme N, Cross-Theme Analysis,
split from the same English survey) with the AutoSurvey prompt unchanged (default criterion
Structure), in these forms:

    original            the section as written
    no_subheadings      ### subheadings removed, content in the original order        (mild)
    repeated            every paragraph appears twice
    shuffled            sentences / table rows randomly reordered, subheadings removed (severe)

These section forms (and SEED) were first written for the retired Prometheus judge controls
(judge_controls.py, see README "History") and are kept unchanged so results stay comparable.

    python evaluation/step06_sota/autosurvey_controls.py --batch evaluation/runs/<batch_id> [--judge gemma4:31b]

Writes eval/{topic}/controls/autosurvey[_section]/{judge}/controls.json and
eval/autosurvey[_section]_controls_{judge}.md.
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # evaluation/: eval_common, run_batch

from autosurvey_common import OllamaChat, step6_sections, step6_survey
from autosurvey_eval import CachedCalls, judge_content
from autosurvey_prompts import CRITERIA
from eval_common import batch_paths, ollama_digest, read_json, read_runs, write_json

SEED = 20261003
VARIANTS = ["original", "themes_reversed", "theme_repeated", "one_theme_shuffled", "all_shuffled",
            "half_themes", "summary_only", "foreign_theme"]
SECTION_VARIANTS = ["original", "no_subheadings", "repeated", "shuffled"]
TARGET = {"themes_reversed": "Structure", "theme_repeated": "Structure", "one_theme_shuffled": "Structure",
          "all_shuffled": "Structure", "half_themes": "Coverage", "summary_only": "Coverage",
          "foreign_theme": "Relevance",
          # --level section
          "no_subheadings": "Structure", "repeated": "Structure", "shuffled": "Structure"}
THEME_RE = re.compile(r"^##\s+Theme\s+(\d+)\b")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")


def blocks(survey: str) -> list[str]:
    """[preamble, '## A\\n…', '## B\\n…', …] — joining them gives the survey back."""
    return re.split(r"(?m)^(?=##\s)", survey)


# --------------------------------------------------------------------------- #
# damage to one section
# --------------------------------------------------------------------------- #
def _split(section: str) -> tuple[str, list[str]]:
    lines = section.strip().splitlines()
    return lines[0], lines[1:]


def no_subheadings(section: str) -> str:
    head, body = _split(section)
    return "\n".join([head, *[line for line in body if not line.lstrip().startswith("###")]]) + "\n"


def repeated(section: str) -> str:
    head, body = _split(section)
    out, paragraph = [head], []
    for line in body + [""]:
        if line.strip() and not line.lstrip().startswith(("#", "|")):
            paragraph.append(line)
            continue
        if paragraph:
            out += paragraph + [""] + paragraph
            paragraph = []
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def shuffled(section: str, seed: int) -> str:
    head, body = _split(section)
    units = []
    for line in body:
        text = line.strip()
        if not text or text.startswith("#") or re.match(r"^\|?\s*:?-{3,}", text):
            continue
        units += [text] if text.startswith("|") else SENTENCE_RE.split(text)
    random.Random(seed).shuffle(units)
    paragraphs = [" ".join(units[i:i + 3]) for i in range(0, len(units), 3)]
    return "\n\n".join([head, *paragraphs]) + "\n"


def section_forms(section: str, seed: int) -> dict[str, str]:
    return {"original": section, "no_subheadings": no_subheadings(section),
            "repeated": repeated(section), "shuffled": shuffled(section, seed)}


def compare(rows: list[dict], variants: list[str]) -> dict[str, Any]:
    """Per variant: mean valid score, and how often the original beats it on the same unit."""
    by_unit: dict[str, dict[str, int | None]] = {}
    for row in rows:
        by_unit.setdefault(row["unit"], {})[row["variant"]] = row["score"]
    out = {}
    for variant in variants:
        scores = [r["score"] for r in rows if r["variant"] == variant and r["score"] is not None]
        entry = {"mean": round(mean(scores), 3) if scores else None, "n_valid": len(scores),
                 "n": sum(r["variant"] == variant for r in rows)}
        if variant != "original":
            pairs = [(u["original"], u[variant]) for u in by_unit.values()
                     if u.get("original") is not None and u.get(variant) is not None]
            entry.update({
                "pairs": len(pairs),
                "original_higher": sum(o > d for o, d in pairs),
                "tied": sum(o == d for o, d in pairs),
                "original_lower": sum(o < d for o, d in pairs),
                "mean_drop": round(mean(o - d for o, d in pairs), 3) if pairs else None,
            })
        out[variant] = entry
    return out


# --------------------------------------------------------------------------- #
# damage to the whole survey
# --------------------------------------------------------------------------- #

def theme_indices(parts: list[str]) -> list[int]:
    return [i for i, b in enumerate(parts) if THEME_RE.match(b)]


def ensure_break(block: str) -> str:
    return block if block.endswith("\n\n") else block.rstrip("\n") + "\n\n"


def damaged_forms(survey: str, foreign_survey: str | None) -> dict[str, str]:
    parts = blocks(survey)
    themes = theme_indices(parts)
    first, last = themes[0], themes[-1]
    forms = {"original": survey}

    reordered = list(parts)
    for slot, src in zip(themes, reversed(themes)):
        reordered[slot] = ensure_break(parts[src])
    forms["themes_reversed"] = "".join(reordered)

    forms["theme_repeated"] = "".join(parts[:last] + [ensure_break(parts[last]), ensure_break(parts[first])]
                                      + parts[last + 1:])

    one = list(parts)
    one[first] = ensure_break(shuffled(parts[first], SEED))
    forms["one_theme_shuffled"] = "".join(one)

    title, _, rest = survey.partition("\n")
    forms["all_shuffled"] = shuffled(f"{title}\n{rest}", SEED)

    dropped = set(themes[1::2])
    forms["half_themes"] = "".join(b for i, b in enumerate(parts) if i not in dropped)

    summary = next((b for b in parts if re.match(r"##\s+Executive Summary", b, re.IGNORECASE)), "")
    forms["summary_only"] = parts[0] + summary

    if foreign_survey is not None and len(themes) > 1:
        foreign_parts = blocks(foreign_survey)
        foreign = foreign_parts[theme_indices(foreign_parts)[0]]
        number = THEME_RE.match(parts[themes[1]]).group(1)
        swapped = list(parts)
        swapped[themes[1]] = ensure_break(re.sub(r"^(##\s+Theme\s+)\d+", rf"\g<1>{number}", foreign, count=1))
        forms["foreign_theme"] = "".join(swapped)
    return forms


def render(report: dict[str, Any]) -> str:
    fmt = lambda v: "—" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))  # noqa: E731
    level = report.get("level", "whole")
    lines = [f"# AutoSurvey criteria — discrimination controls, {level} level (`{report['judge']}`)", "",
             f"AutoSurvey prompt verbatim; judged unit: {'whole survey' if level == 'whole' else 'one review section'}. "
             "Each unit is judged as written and in damaged forms; a judge that tracks quality scores a damaged form lower, above all on its target "
             "criterion (★). Pairs = units with a valid score for both forms.", ""]
    for criterion, comp in report["comparison"].items():
        lines += [f"## {criterion}", "", "| Variant | Target | Mean | Valid | Original higher / tied / lower | Mean drop |",
                  "|---|---|---|---|---|---|"]
        for variant, c in comp.items():
            star = "★" if TARGET.get(variant) == criterion else ""
            pairs = "—" if variant == "original" else f"{c['original_higher']} / {c['tied']} / {c['original_lower']}"
            lines.append(f"| {variant} | {star} | {fmt(c['mean'])} | {c['n_valid']}/{c['n']} | {pairs} | {fmt(c.get('mean_drop'))} |")
        lines.append("")
    lines += ["## Raw scores", "", "| Unit | Variant | words | " + " | ".join(report["criteria"]) + " |",
              "|---|---|---|" + "---|" * len(report["criteria"])]
    for row in report["rows"]:
        cells = [str(row["scores"][c]["score"]) if row["scores"][c]["status"] == "valid"
                 else f"{row['scores'][c]['status']} ({row['scores'][c]['raw']!r})" for c in report["criteria"]]
        lines.append(f"| {row['unit']} | {row['variant']} | {row['words']} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def whole_units(batch_dir: Path, records: list[dict], surveys: dict[str, str]) -> list[dict]:
    ids = list(surveys)
    units = []
    for k, topic_id in enumerate(ids):
        foreign = surveys[ids[(k + 1) % len(ids)]] if len(ids) > 1 else None
        for variant, text in damaged_forms(surveys[topic_id], foreign).items():
            units.append({"topic": topic_id, "unit": topic_id, "variant": variant, "text": text})
    return units


def section_units(surveys: dict[str, str]) -> list[dict]:
    """Every judged section of every survey in SECTION_VARIANTS forms."""
    units = []
    for topic_id, survey in surveys.items():
        for index, (title, text) in enumerate(step6_sections(survey)):
            for variant, form in section_forms(text, SEED + index).items():
                units.append({"topic": topic_id, "unit": f"{topic_id} / {title}", "variant": variant, "text": form})
    return units


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--only", nargs="+")
    parser.add_argument("--level", choices=["whole", "section"], default="whole",
                        help="whole: damaged whole surveys; section: damaged review sections")
    parser.add_argument("--judge", default="gemma4:31b")
    parser.add_argument("--criteria", nargs="+", choices=list(CRITERIA),
                        help="default: all three (whole), Structure (section)")
    parser.add_argument("--num_ctx", type=int, default=32768)
    parser.add_argument("--think", choices=["on", "off", "default"], default="off")
    args = parser.parse_args()
    args.criteria = args.criteria or (list(CRITERIA) if args.level == "whole" else ["Structure"])
    if ollama_digest(args.judge) is None:
        raise SystemExit(f"judge {args.judge!r} not on the Ollama server")
    chats = {args.judge: OllamaChat(args.judge, args.num_ctx, think={"on": True, "off": False}.get(args.think))}
    tag = re.sub(r"[^A-Za-z0-9.]+", "-", args.judge.split("/")[-1]).strip("-")

    batch_dir = Path(args.batch).resolve()
    eval_dir = batch_paths(batch_dir)["eval"]
    # MetaSyn batches (metasyn_prepare.register) do not record step6_present: look for the file itself
    records = [r for r in read_runs(batch_dir)
               if "session_dir" in r and (batch_dir / r["session_dir"] / "step6_sota_review.md").exists()]
    topics = {r["id"]: read_json(batch_dir / r["session_dir"] / "step0_session_config.json")["topic"] for r in records}
    surveys = {r["id"]: step6_survey((batch_dir / r["session_dir"] / "step6_sota_review.md").read_text(encoding="utf-8"))
               for r in records}
    if args.level == "whole":
        units, variants, folder = whole_units(batch_dir, records, surveys), VARIANTS, "autosurvey"
    else:
        units, variants, folder = section_units(surveys), SECTION_VARIANTS, "autosurvey_section"
    units = [u for u in units if not args.only or u["topic"] in args.only]

    rows = []
    for topic_id in dict.fromkeys(u["topic"] for u in units):
        calls = CachedCalls(eval_dir / topic_id / "autosurvey" / "calls.jsonl", chats)
        topic_rows = []
        for u in (u for u in units if u["topic"] == topic_id):
            scores = judge_content(calls, args.judge, topics[topic_id], u["text"], args.criteria)
            topic_rows.append({"topic": topic_id, "unit": u["unit"], "variant": u["variant"],
                               "words": len(u["text"].split()), "scores": scores})
            print(f"{u['unit'][:60]:60} {u['variant']:20} " + " ".join(
                f"{c}={s['score'] if s['status'] == 'valid' else s['status']}" for c, s in scores.items()), flush=True)
        out = eval_dir / topic_id / "controls" / folder / tag
        write_json(out / "controls.json", {"topic": topic_id, "judge": args.judge, "level": args.level, "seed": SEED,
                                           "rows": topic_rows})
        if args.level == "whole":
            for u in (u for u in units if u["topic"] == topic_id):
                (out / f"{u['variant']}.md").write_text(u["text"], encoding="utf-8")
        rows += topic_rows

    comparison = {}
    for criterion in args.criteria:
        flat = [{"unit": r["unit"], "variant": r["variant"], "score": r["scores"][criterion]["score"]} for r in rows]
        comparison[criterion] = compare(flat, [v for v in variants if any(r["variant"] == v for r in rows)])
    report = {"judge": args.judge, "level": args.level, "criteria": args.criteria, "comparison": comparison, "rows": rows}
    name = f"autosurvey_controls_{tag}" if args.level == "whole" else f"autosurvey_section_controls_{tag}"
    write_json(eval_dir / f"{name}.json", report)
    (eval_dir / f"{name}.md").write_text(render(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
