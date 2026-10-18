#!/usr/bin/env python3
"""Phase B2 — AutoSurvey-style evaluation of Step 6 and of the naive baseline.

Follows AutoSurvey (NeurIPS 2024) evaluation.py / src/agents/judge.py; prompts and rubrics
are copied verbatim in autosurvey_prompts.py.

Content quality — Coverage, Structure, Relevance, 1–5
    the whole English survey in one prompt per criterion, temperature 0 (AutoSurvey intends 0;
    its client puts the field inside the message, where the API ignores it). Several --judges
    give AutoSurvey's "mixture": the mean of the judges' valid scores. A reply is a score only
    if it is a bare 1–5 (AutoSurvey takes the first integer anywhere in the reply, so
    "On a scale of 1-5 …" becomes 1); anything else is ``no_result`` and is not counted.
    Structure_section (not in AutoSurvey; Step 6 only): the same Structure prompt on each review
    section (Executive Summary, each Theme, Cross-Theme Analysis), mean over sections. Whole-survey
    Structure misses local damage; per section it tracks it (autosurvey_controls.py --level section).

Citation quality — AutoSurvey's NLI-by-LLM
    claims = sentences (and Key Results table rows) that carry a citation, citations removed.
    source (--citation-sources, default fulltext):
        fulltext  the cited paper's abstract + its 3 best-matching full-text windows
                  (fulltext_retrieval.py, frozen on the dev reviews) — the Step 6 citation measure
        abstract  the abstract only, as in AutoSurvey (for comparability; it underestimates
                  support for claims citing full-text papers)
    recall     share of cited claims whose sources, together, support the claim
    precision  share of all citations that are relevant: on a supported claim, a citation is
               relevant if it supports the claim alone, or if the claim's other citations
               without it do not (AutoSurvey Judge.__relevant); other citations count as irrelevant
    by_n_citations  recall / precision for claims citing 1, 2, 3+ keys (precision is harder to
               earn with many keys, and the systems differ in how many they cite per claim)
    Also reported, not in AutoSurvey:
    citation_density     cited claims / all claim sentences
    all_sentence_recall  supported claims / all claim sentences — the ALCE-style denominator
                         (uncited statements count as unsupported)
    invalid_citations    cited keys not in the session's .bib (count as unsupported / irrelevant)
    controls (--citation-controls), same source: citations swapped for random other keys of the
    same .bib (recall must collapse), numbers / direction words changed in the claim (recall must drop).

Coverage here is AutoSurvey's LLM Coverage, reported for comparability only: on Step 6 the
LLM judges did not lower coverage when themes were removed (README); the deterministic
contract coverage_rate stays the coverage measure.

    python evaluation/step06_sota/autosurvey_eval.py --batch evaluation/runs/<batch_id> [--judges gemma4:31b qwen3.6:35b]

Writes eval/{topic}/autosurvey/{system}.json (+ {system}_survey.md, the judged text),
eval/autosurvey_summary.json and .md. Every LLM call is cached in
eval/{topic}/autosurvey/calls.jsonl, so an interrupted run resumes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # evaluation/: eval_common, run_batch

import fulltext_retrieval
from autosurvey_common import OllamaChat, load_papers, step6_sections, step6_survey
from autosurvey_prompts import CRITERIA, CRITERIA_BASED_JUDGING_PROMPT, NLI_PROMPT, fill
from eval_common import METASYN_DEV, batch_paths, ollama_digest, read_json, read_runs, write_json
from step6_common import extract_citations, is_table_row, is_table_separator

SYSTEMS = ("step6", "naive")
CITATION_SOURCES = ("fulltext", "abstract")
N_CITATION_STRATA = ("1", "2", "3+")
SCORE_RE = re.compile(r"^\W*(?:score\W*)?([1-5])(?:\s*/\s*5)?\W*$", re.IGNORECASE)
ABBREV_END_RE = re.compile(r"(?:\bet al|\be\.g|\bi\.e|\bvs|\bcf|\bFig|\bapprox|\bca|\bNo)\.$", re.IGNORECASE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[\"'“])")
PAREN_RE = re.compile(r"\s*[（(][^()（）]*[)）]")
MIN_CLAIM_WORDS = 4
# perturbation control: the first of these pairs found in a claim is flipped (numbers are always changed)
FLIP = [("increased", "decreased"), ("increase", "decrease"), ("higher", "lower"), ("greater", "smaller"),
        ("more", "less"), ("improved", "worsened"), ("reduced", "raised"), ("positive", "negative"),
        ("significant", "non-significant"), ("associated with", "unrelated to"), ("risk", "protection")]

Source = Callable[[str, str], str]  # (claim text, key) → evidence text


# --------------------------------------------------------------------------- #
# cached LLM calls
# --------------------------------------------------------------------------- #
class CachedCalls:
    """Every (model, prompt) → reply, appended to calls.jsonl as soon as it returns."""

    def __init__(self, path: Path, chats: dict[str, OllamaChat]):
        self.path, self.chats = path, chats
        self.memo: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self.memo[entry["id"]] = entry

    def __call__(self, model: str, prompt: str, num_predict: int) -> dict:
        call_id = hashlib.sha256(f"{model}\0{num_predict}\0{prompt}".encode()).hexdigest()
        if call_id not in self.memo:
            entry = {"id": call_id, "model": model, **self.chats[model](prompt, num_predict=num_predict)}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.memo[call_id] = entry
        return self.memo[call_id]


# --------------------------------------------------------------------------- #
# content quality
# --------------------------------------------------------------------------- #
def parse_score(text: str | None) -> int | None:
    match = SCORE_RE.match((text or "").strip())
    return int(match.group(1)) if match else None


def judging_prompt(topic: str, survey: str, criterion: str) -> str:
    c = CRITERIA[criterion]
    return fill(CRITERIA_BASED_JUDGING_PROMPT, {
        "TOPIC": topic, "SURVEY": survey, "Criterion Description": c["description"],
        **{f"Score {i} Description": c[f"score{i}"] for i in range(1, 6)},
    })


def judge_content(calls: CachedCalls, model: str, topic: str, survey: str, criteria: list[str]) -> dict[str, dict]:
    out = {}
    for criterion in criteria:
        reply = calls(model, judging_prompt(topic, survey, criterion), num_predict=32)
        score = parse_score(reply["text"])
        out[criterion] = {"status": "valid" if score else "no_result", "score": score, "raw": reply["text"],
                          "prompt_tokens": reply["prompt_tokens"], "done_reason": reply["done_reason"]}
    return out


def judge_sections(calls: CachedCalls, model: str, topic: str, survey: str) -> dict[str, Any]:
    """Structure on every Step 6 section; the score is the mean of the valid section scores."""
    units = [{"section": title, **judge_content(calls, model, topic, text, ["Structure"])["Structure"]}
             for title, text in step6_sections(survey)]
    valid = [u["score"] for u in units if u["status"] == "valid"]
    return {"score": round(mean(valid), 4) if valid else None, "min": min(valid) if valid else None,
            "n_valid": len(valid), "n_sections": len(units), "units": units}


def mixture(content: dict[str, dict[str, dict]], criteria: list[str]) -> dict[str, float | None]:
    """AutoSurvey's multi-LLM judge: mean over judges, valid scores only."""
    result = {}
    for criterion in criteria:
        scores = [per[criterion]["score"] for per in content.values() if per[criterion]["status"] == "valid"]
        result[criterion] = round(mean(scores), 4) if scores else None
    return result


# --------------------------------------------------------------------------- #
# claims
# --------------------------------------------------------------------------- #
def split_sentences(text: str) -> list[str]:
    pieces = SENTENCE_SPLIT_RE.split(text)
    sentences: list[str] = []
    for piece in pieces:
        if sentences and ABBREV_END_RE.search(sentences[-1]):
            sentences[-1] += " " + piece
        else:
            sentences.append(piece)
    return [s.strip() for s in sentences if s.strip()]


def strip_citations(text: str) -> str:
    text = PAREN_RE.sub(lambda m: "" if extract_citations(m.group(0)) else m.group(0), text)
    for citation in extract_citations(text):  # narrative keys ("SmithEtAl2024 showed …")
        text = text.replace(citation.raw, "")
    return re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s{2,}", " ", text)).strip()


def extract_claims(survey: str, legal: set[str]) -> list[dict[str, Any]]:
    """Statements in the judged text: prose sentences and table body rows, with the keys they cite."""
    lines = survey.splitlines()
    claims = []
    for i, line in enumerate(lines):
        text = line.strip()
        if not text or text.startswith(("#", ">")) or is_table_separator(text):
            continue
        if is_table_row(text):
            if i + 1 < len(lines) and is_table_separator(lines[i + 1]):
                continue  # header row
            cells = [c.strip() for c in text.strip("|").split("|")]
            units = ["; ".join(c for c in cells if c and not (extract_citations(c) and not strip_citations(c)))]
            raw_units, kind = [text], "table_row"
        else:
            text = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", text)
            raw_units = split_sentences(text)
            units, kind = [strip_citations(s) for s in raw_units], "sentence"
        for raw, claim in zip(raw_units, units):
            if len(claim.split()) < MIN_CLAIM_WORDS:
                continue
            keys = list(dict.fromkeys(c.key for c in extract_citations(raw)))
            claims.append({"kind": kind, "claim": claim, "raw": raw, "keys": keys,
                           "invalid_keys": [k for k in keys if k not in legal]})
    return claims


# --------------------------------------------------------------------------- #
# citation quality (AutoSurvey Judge.citation_quality)
# --------------------------------------------------------------------------- #
def citation_source(kind: str, session: Path, papers: dict[str, dict]) -> Source:
    def abstract(key: str) -> str:
        return papers[key]["abstract"] or papers[key]["title"]

    if kind == "abstract":
        return lambda claim, key: abstract(key)
    return lambda claim, key: fulltext_retrieval.retrieve(str(session / "step5_full_text" / f"{key}.md"), claim, abstract(key))


def nli(calls: CachedCalls, model: str, claim: str, sources: list[str]) -> tuple[int, str]:
    reply = calls(model, fill(NLI_PROMPT, {"SOURCE": "\n".join(sources), "CLAIM": claim}), num_predict=8)
    return int("yes" in reply["text"].lower()), reply["text"]


def n_citation_stratum(claim: dict) -> str:
    n = len(claim["keys"])
    return "1" if n == 1 else "2" if n == 2 else "3+"


def citation_quality(calls: CachedCalls, model: str, claims: list[dict], papers: dict[str, dict], source: Source,
                     max_claims: int = 0) -> dict[str, Any]:
    """``claims`` are annotated in place (supported / relevant): pass copies to score them twice."""
    cited = [c for c in claims if c["keys"]]
    judged = cited[:max_claims] if max_claims else cited
    unparsed = 0
    citation_num = relevant = supported = 0
    for claim in judged:
        legal_keys = [k for k in claim["keys"] if k in papers]
        citation_num += len(claim["keys"])
        claim["supported"], raw = (nli(calls, model, claim["claim"], [source(claim["claim"], k) for k in legal_keys])
                                   if legal_keys else (0, ""))
        unparsed += bool(legal_keys) and not re.search(r"\b(yes|no)\b", raw, re.IGNORECASE)
        supported += claim["supported"]
        claim["relevant"] = {}
        if not claim["supported"]:
            continue
        for key in claim["keys"]:
            if key not in papers:
                claim["relevant"][key] = 0
                continue
            alone, _ = nli(calls, model, claim["claim"], [source(claim["claim"], key)])
            if not alone:
                others, _ = nli(calls, model, claim["claim"], [source(claim["claim"], k) for k in legal_keys if k != key])
                alone = int(not others)
            claim["relevant"][key] = alone
            relevant += alone

    by_n = {}
    for stratum in N_CITATION_STRATA:
        group = [c for c in judged if n_citation_stratum(c) == stratum]
        n_cit = sum(len(c["keys"]) for c in group)
        by_n[stratum] = {"n_claims": len(group),
                         "recall": round(mean(c["supported"] for c in group), 4) if group else None,
                         "precision": round(sum(sum(c["relevant"].values()) for c in group) / n_cit, 4) if n_cit else None}

    n_all = len(claims) if not max_claims else None  # all-sentence metrics only when every cited claim was judged
    return {
        "nli_model": model,
        "n_claims": len(claims),
        "n_cited_claims": len(cited),
        "n_judged_claims": len(judged),
        "n_citations": citation_num,
        "n_invalid_citations": sum(len(c["invalid_keys"]) for c in judged),
        "n_unparsed_nli": unparsed,
        "citation_density": round(len(cited) / len(claims), 4) if claims else None,
        "recall": round(supported / len(judged), 4) if judged else None,
        "precision": round(relevant / citation_num, 4) if citation_num else None,
        "all_sentence_recall": round(supported / n_all, 4) if n_all else None,
        "by_n_citations": by_n,
        "claims": claims,
    }


def perturb(claim: str) -> str:
    """Change every number (years kept) and flip the first direction word found."""
    def num(m: re.Match) -> str:
        s = m.group(0)
        if "." in s:
            return f"{float(s) * 2.7 + 0.4:.{len(s.split('.')[1])}f}"
        v = int(s)
        return s if 1900 <= v <= 2030 else str(v * 3 + 7)
    out = re.sub(r"(?<![A-Za-z])\d+(?:\.\d+)?", num, claim)
    for a, b in FLIP:
        pat = re.compile(rf"\b({re.escape(a)}|{re.escape(b)})\b", re.IGNORECASE)
        if pat.search(out):
            out = pat.sub(lambda m: b if m.group(1).lower() == a else a, out, count=1)
            break
    return out


def citation_controls(calls: CachedCalls, model: str, judged: list[dict], papers: dict[str, dict], source: Source) -> dict:
    """Validity controls on the judged cited claims (already scored by citation_quality)."""
    def recall(items: list[tuple[str, list[str]]]) -> float | None:
        hits = [nli(calls, model, claim, [source(claim, k) for k in keys if k in papers])[0]
                if any(k in papers for k in keys) else 0 for claim, keys in items]
        return round(mean(hits), 4) if hits else None

    rng = random.Random(0)
    swapped = []
    for c in judged:
        pool = [k for k in papers if k not in c["keys"]]
        swapped.append((c["claim"], rng.sample(pool, min(len(c["keys"]), len(pool)))))
    changed = [c for c in judged if perturb(c["claim"]) != c["claim"]]
    return {
        "swap": {"n": len(swapped), "recall": recall([s for s in swapped if s[1]])},
        "perturb": {"n": len(changed), "recall": recall([(perturb(c["claim"]), c["keys"]) for c in changed]),
                    "recall_original_same_claims": round(mean(c["supported"] for c in changed), 4) if changed else None},
    }


# --------------------------------------------------------------------------- #
# per topic
# --------------------------------------------------------------------------- #
def system_texts(record: dict, batch_dir: Path, systems: list[str]) -> dict[str, str]:
    session = batch_dir / record["session_dir"]
    out = {}
    if "step6" in systems and (session / "step6_sota_review.md").exists():
        out["step6"] = step6_survey((session / "step6_sota_review.md").read_text(encoding="utf-8"))
    naive = batch_paths(batch_dir)["eval"] / record["id"] / "naive" / "review.md"
    if "naive" in systems and naive.exists():
        out["naive"] = naive.read_text(encoding="utf-8")
    return out


def evaluate_topic(record: dict, batch_dir: Path, args: argparse.Namespace, chats: dict[str, OllamaChat]) -> dict:
    if "session_dir" not in record:
        return {"status": "no_session"}
    session = batch_dir / record["session_dir"]
    out_dir = batch_paths(batch_dir)["eval"] / record["id"] / "autosurvey"
    texts = system_texts(record, batch_dir, args.systems)
    if not texts:
        return {"status": "no_survey"}
    topic = read_json(session / "step0_session_config.json")["topic"]
    papers = load_papers(session)
    calls = CachedCalls(out_dir / "calls.jsonl", chats)

    summary = {}
    for system, survey in texts.items():
        (out_dir / f"{system}_survey.md").parent.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{system}_survey.md").write_text(survey, encoding="utf-8")
        content = {model: judge_content(calls, model, topic, survey, args.criteria) for model in args.judges}
        result: dict[str, Any] = {
            "system": system, "topic": topic, "survey_words": len(survey.split()),
            "survey_sha256": hashlib.sha256(survey.encode()).hexdigest(),
            "content": content, "mixture": mixture(content, args.criteria),
        }
        if system == "step6" and not args.skip_sections:
            sections = {model: judge_sections(calls, model, topic, survey) for model in args.judges}
            scores = [s["score"] for s in sections.values() if s["score"] is not None]
            result["sections"] = sections
            result["mixture"]["Structure_section"] = round(mean(scores), 4) if scores else None
        if not args.skip_citations:
            claims = extract_claims(survey, set(papers))
            result["citations"] = {}
            for kind in args.citation_sources:
                source = citation_source(kind, session, papers)
                quality = citation_quality(calls, args.nli_model, [dict(c) for c in claims], papers, source, args.max_claims)
                if args.citation_controls:
                    judged = [c for c in quality["claims"] if c["keys"]][:quality["n_judged_claims"]]
                    quality["controls"] = citation_controls(calls, args.nli_model, judged, papers, source)
                result["citations"][kind] = {"source": kind, **({"retrieval": fulltext_retrieval.VERSION} if kind == "fulltext" else {}),
                                             **quality}
        write_json(out_dir / f"{system}.json", result)
        summary[system] = {"mixture": result["mixture"], "words": result["survey_words"],
                           "citations": {kind: {k: v for k, v in q.items() if k != "claims"}
                                         for kind, q in result.get("citations", {}).items()}}
    return {"status": "ok", "systems": summary}


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #
CITATION_METRICS = ("recall", "precision", "citation_density", "all_sentence_recall")


def boot_ci(diffs: list[float], n: int = 10_000) -> tuple[float, float]:
    rng = random.Random(0)
    means = sorted(mean(rng.choices(diffs, k=len(diffs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def is_dev(topic_id: str) -> bool:
    match = re.fullmatch(r"review_(\d+)", topic_id)
    return bool(match) and int(match.group(1)) in METASYN_DEV


def write_summary(batch_dir: Path, topics: dict[str, dict], meta: dict) -> None:
    sources = meta.get("citation_sources", [])
    rows = []
    for topic_id, status in topics.items():
        for system, s in status.get("systems", {}).items():
            row = {"topic": topic_id, "system": system, "words": s.get("words"), **s["mixture"]}
            for kind in sources:
                q = s["citations"].get(kind, {})
                row.update({f"{kind}/{m}": q.get(m) for m in CITATION_METRICS})
                for stratum in N_CITATION_STRATA:
                    cell = q.get("by_n_citations", {}).get(stratum, {})
                    row.update({f"{kind}/recall@{stratum}": cell.get("recall"), f"{kind}/precision@{stratum}": cell.get("precision"),
                                f"{kind}/n@{stratum}": cell.get("n_claims")})
                for ctrl in ("swap", "perturb"):
                    row[f"{kind}/{ctrl}_recall"] = q.get("controls", {}).get(ctrl, {}).get("recall")
                row[f"{kind}/perturb_original"] = q.get("controls", {}).get("perturb", {}).get("recall_original_same_claims")
            rows.append(row)
    content = [*meta["criteria"], *(["Structure_section"] if meta.get("sections") else [])]
    citation = [f"{kind}/{m}" for kind in sources for m in CITATION_METRICS]
    metrics = ["words", *content, *citation]
    paired = {t for t, s in topics.items() if set(SYSTEMS) <= set(s.get("systems", {}))}
    has_dev = any(is_dev(t) for t in topics)
    scopes = [("all", lambda t: True)] + ([("held-out", lambda t: not is_dev(t))] if has_dev else [])

    def avg(sel: list[dict], m: str) -> float | None:
        vals = [r[m] for r in sel if r.get(m) is not None]
        return round(mean(vals), 4) if vals else None

    columns = [m for m in dict.fromkeys(k for r in rows for k in r) if m not in ("topic", "system")]
    means, diffs_out = {}, {}
    for scope, keep in scopes:
        for system in SYSTEMS:
            sel = [r for r in rows if r["system"] == system and keep(r["topic"])]
            means[f"{system}/{scope}"] = {m: avg(sel, m) for m in columns} | {"n": len(sel)}
        for m in metrics:
            pairs = [(a[m], b[m]) for t in sorted(paired) if keep(t)
                     for a in rows if a["topic"] == t and a["system"] == "step6"
                     for b in rows if b["topic"] == t and b["system"] == "naive"
                     if a.get(m) is not None and b.get(m) is not None]
            if len(pairs) >= 3:
                d = [a - b for a, b in pairs]
                lo, hi = boot_ci(d)
                diffs_out[f"{scope}/{m}"] = {"diff": round(mean(d), 4), "ci95": [round(lo, 4), round(hi, 4)], "n": len(d)}
    write_json(batch_paths(batch_dir)["eval"] / "autosurvey_summary.json",
               {"meta": meta, "topics": topics, "rows": rows, "means": means, "paired_step6_minus_naive": diffs_out})

    def fmt(v):
        return "–" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))

    lines = ["# AutoSurvey-style evaluation", "",
             f"- judges: {', '.join(f'`{m}`' for m in meta['judges'])} (mixture = mean of valid scores); NLI: `{meta['nli_model']}`",
             f"- prompts / rubrics: AutoSurvey verbatim (`autosurvey_prompts.py`); citation sources: {', '.join(sources) or '—'}"
             + (" (fulltext = abstract + 3 retrieved windows, `fulltext_retrieval.py`)" if "fulltext" in sources else ""),
             "- Coverage is AutoSurvey's LLM coverage, for comparability only — see README; use contract `coverage_rate`.",
             "- Structure_section: Step 6 only, mean Structure over its sections.", ""]
    for scope, keep in scopes:
        lines += [f"## Means and paired step6 − naive, {scope} (bootstrap 95% CI over topics)", "",
                  "| metric | step6 | naive | step6 − naive [95% CI] | n pairs |", "|---|---|---|---|---|"]
        for m in metrics:
            d = diffs_out.get(f"{scope}/{m}")
            lines.append(f"| {m} | {fmt(means.get(f'step6/{scope}', {}).get(m))} | {fmt(means.get(f'naive/{scope}', {}).get(m))} | "
                         + (f"{d['diff']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}] | {d['n']}" if d else "– | –") + " |")
        lines.append("")
    for kind in sources:
        lines += [f"## Citation ({kind}) by citations per claim, {scopes[-1][0]} (macro means)", "",
                  "| system | " + " | ".join(f"recall@{s} | precision@{s}" for s in N_CITATION_STRATA) + " |",
                  "|---|" + "---|---|" * len(N_CITATION_STRATA)]
        for system in SYSTEMS:
            mm = means.get(f"{system}/{scopes[-1][0]}", {})
            lines.append(f"| {system} | " + " | ".join(f"{fmt(mm.get(f'{kind}/recall@{s}'))} | {fmt(mm.get(f'{kind}/precision@{s}'))}"
                                                     for s in N_CITATION_STRATA) + " |")
        if meta.get("citation_controls"):
            lines += ["", f"Controls ({kind}, {scopes[-1][0]}): " + "; ".join(
                f"{system} swap recall {fmt(means.get(f'{system}/{scopes[-1][0]}', {}).get(f'{kind}/swap_recall'))}, "
                f"perturb {fmt(means.get(f'{system}/{scopes[-1][0]}', {}).get(f'{kind}/perturb_original'))} → "
                f"{fmt(means.get(f'{system}/{scopes[-1][0]}', {}).get(f'{kind}/perturb_recall'))}" for system in SYSTEMS)]
        lines.append("")
    lines += ["## Per topic", "", "| topic | system | " + " | ".join(metrics) + " |", "|---|---|" + "---|" * len(metrics)]
    lines += [f"| {r['topic']}{' (dev)' if is_dev(r['topic']) else ''} | {r['system']} | " + " | ".join(fmt(r.get(m)) for m in metrics) + " |"
              for r in rows]
    failed = {t: s["status"] for t, s in topics.items() if s.get("status") != "ok"}
    if failed:
        lines += ["", "## Not evaluated", "", *[f"- {t}: {s}" for t, s in failed.items()]]
    (batch_paths(batch_dir)["eval"] / "autosurvey_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--only", nargs="+")
    parser.add_argument("--systems", nargs="+", choices=SYSTEMS, default=list(SYSTEMS))
    parser.add_argument("--judges", nargs="+", default=["gemma4:31b"], help="content judges; >1 = AutoSurvey mixture")
    parser.add_argument("--nli-model", default=None, help="citation NLI model (default: first judge)")
    parser.add_argument("--criteria", nargs="+", choices=list(CRITERIA), default=list(CRITERIA))
    parser.add_argument("--skip-sections", action="store_true", help="no per-section Structure for Step 6")
    parser.add_argument("--skip-citations", action="store_true")
    parser.add_argument("--citation-sources", nargs="+", choices=CITATION_SOURCES, default=["fulltext"],
                        help="evidence for the citation NLI (default fulltext; add abstract for AutoSurvey's original)")
    parser.add_argument("--citation-controls", action="store_true", help="also run the swap / perturb validity controls")
    parser.add_argument("--max-claims", type=int, default=0, help="judge only the first N cited claims (0 = all; smoke runs)")
    parser.add_argument("--num_ctx", type=int, default=32768)
    parser.add_argument("--think", choices=["on", "off", "default"], default="off")
    args = parser.parse_args()
    args.nli_model = args.nli_model or args.judges[0]

    think = {"on": True, "off": False}.get(args.think)
    models = list(dict.fromkeys([*args.judges, args.nli_model]))
    digests = {m: ollama_digest(m) for m in models}
    missing = [m for m, d in digests.items() if d is None]
    if missing:
        raise SystemExit(f"not on the Ollama server: {', '.join(missing)} (is `ollama serve` running?)")
    chats = {m: OllamaChat(m, args.num_ctx, think=think) for m in models}

    batch_dir = Path(args.batch).resolve()
    meta = {"judges": args.judges, "nli_model": args.nli_model, "ollama_digests": digests, "criteria": args.criteria,
            "sections": not args.skip_sections, "systems": args.systems, "num_ctx": args.num_ctx, "think": args.think,
            "temperature": 0.0, "max_claims": args.max_claims,
            "citation_sources": [] if args.skip_citations else args.citation_sources,
            "fulltext_retrieval": fulltext_retrieval.VERSION, "citation_controls": args.citation_controls}
    summary_path = batch_paths(batch_dir)["eval"] / "autosurvey_summary.json"
    topics = read_json(summary_path)["topics"] if summary_path.exists() else {}
    runs = [r for r in read_runs(batch_dir) if not args.only or r["id"] in args.only]
    for i, record in enumerate(runs, 1):
        print(f"[{i}/{len(runs)}] {record['id']} …", flush=True)
        try:
            topics[record["id"]] = evaluate_topic(record, batch_dir, args, chats)
        except Exception as exc:  # noqa: BLE001 — recorded per topic
            topics[record["id"]] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        print(f"  → {json.dumps(topics[record['id']], ensure_ascii=False)[:400]}", flush=True)
        write_summary(batch_dir, topics, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
