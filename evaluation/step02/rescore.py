"""Offline re-evaluation of frozen LitSearch sessions; never invokes APIs or LLMs."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

from .match import match_gold
from .rank import score_ranking, summarise_rank
from .runner import score_question


def ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def jsonl(path):
    return {r["qid"]: r for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() for r in [json.loads(line)]} if path.exists() else {}


def evaluate(question, id_map, raw, trace, screened, shortlist, config, *, step2_complete, step3_complete):
    papers = (raw or {}).get("papers", []) if step2_complete else []
    screen = screened if step3_complete else None
    row = score_ranking(question, papers, id_map, 0, 9999, screen)
    trace_rows = {str(g["corpusId"]): g for g in (trace or {}).get("golds", [])}
    traced = score_question(question, papers, id_map, 0, 9999, trace_rows)
    for gold, tg in zip(row["gold"], traced["gold"]):
        gold["retrieval_lost_at"] = tg["lost_at"] if step2_complete else "step2_not_completed"
        gold["trace"] = tg.get("trace")
        if not gold["found"]:
            gold["lost_at"] = gold["retrieval_lost_at"]
        elif not step3_complete:
            gold["lost_at"] = "step3_not_completed"
    summary = (raw or {}).get("search_summary", {})
    direct = (trace or {}).get("direct_papers")
    evidence = "recorded_snapshot"
    if direct is None and step2_complete and all("found_via" in p for p in papers):
        direct = [p for p in papers if p["found_via"] != "snowball"]
        evidence = "reconstructed_from_found_via_with_enriched_final_metadata"
    if direct is None:
        evidence = "unavailable"
    if not step2_complete:
        direct = []
        evidence = "not_completed_counted_as_zero"
    direct_hits = None
    if direct is not None:
        direct_hits = 0
        for g in row["gold"]:
            t = trace_rows.get(str(g["corpusId"]))
            found = bool(t["direct_before_snowball"]) if t is not None and "direct_before_snowball" in t else (
                g["mapped"] and match_gold(id_map[str(g["corpusId"])], direct)[0] is not None)
            direct_hits += int(found)
    total, mapped = row["n_gold"], row["n_mapped"]
    found = sum(g["found"] for g in row["gold"])
    retained_ids = {p["id"] for p in (shortlist or [])} if step3_complete else set()
    retained = sum(g["found"] and g.get("paper_id") in retained_ids for g in row["gold"])
    categories = Counter()
    by_id = {p["id"]: p for p in screen or []}
    for g in row["gold"]:
        category = ((by_id.get(g.get("paper_id")) or {}).get("screening") or {}).get("category")
        categories[category or ("not_scored" if g["found"] else "not_retrieved")] += 1
    counts = {"mapping_coverage": ratio(mapped, total), "final_set_recall": ratio(found, total),
              "mapped_only_recall": ratio(found, mapped),
              "direct_search_recall": ratio(direct_hits, total) if direct_hits is not None else None,
              "snowball_gain": ratio(found - direct_hits, total) if direct_hits is not None else None,
              "shortlist_recall": ratio(retained, total), "gold_retention": ratio(retained, found),
              "candidate_retention": ratio(len(retained_ids), len(papers))}
    queries = (trace or {}).get("provider_queries")
    provider_evidence = "recorded_query_outcomes"
    if queries is None:
        # Infer search outcomes only from persisted failures and the frozen query plan.
        # Mark explicitly: this cannot detect a process interrupted before writing output.
        provider_evidence = "inferred_from_completed_output_and_source_failures"
        sources = list(summary.get("sources", {}))
        failures = summary.get("source_failures", [])
        queries = [{"provider": src, "query_id": q["id"],
                    "success": not any(f.startswith(f"{src}/{q['id']}:") for f in failures)}
                   for src in sources for q in (config or {}).get("queries", [])] if step2_complete else []
        if not step2_complete:
            provider_evidence = "unavailable_for_incomplete_question"
    providers = {}
    for src in sorted({q["provider"] for q in queries}):
        qs = [q for q in queries if q["provider"] == src]
        success = sum(bool(q["success"]) for q in qs)
        providers[src] = {"success": ratio(success, len(qs)), "failure": ratio(len(qs)-success, len(qs))}
    row.update(metrics=counts, n_unmapped=total-mapped, step2_complete=step2_complete,
               step3_complete=step3_complete, direct_set_size=len(direct) if direct is not None else None,
               direct_evidence=evidence, final_set_size=len(papers), shortlist_size=len(retained_ids),
               gold_categories=dict(categories), providers=providers, provider_evidence=provider_evidence)
    return row


DEFINITIONS = {
    "mapping_coverage": "mapped gold / all original gold",
    "direct_search_recall": "gold found after year filtering, dedup and DOI enrichment, before snowball / all original gold",
    "final_set_recall": "gold found in final Step 2 set / all original gold",
    "mapped_only_recall": "gold found in final Step 2 set / mapped gold; diagnostic only",
    "snowball_gain": "(final gold hits - direct gold hits) / all original gold",
    "shortlist_recall": "gold present in actual shortlist / all original gold",
    "gold_retention": "gold present in actual shortlist / gold found in Step 2; undefined if no hit",
    "candidate_retention": "shortlist papers / final Step 2 papers; undefined if empty",
    "R@k": "original gold present in top k / all original gold",
    "MRR": "1 / rank of first original gold, or zero; NOT divided by gold count",
    "nDCG@10": "binary DCG over top 10 / ideal DCG for min(10, all original gold count)",
    "completion": "completed questions / all frozen questions, including miss/failure/skip",
    "aggregation": "macro = arithmetic mean over questions; defined-only diagnostics state their question denominator; micro = summed numerators / summed denominators",
    "provider_success": "successful search API queries / attempted search queries, per provider; excludes DOI/reference lookups",
}


def summarise(rows):
    result = summarise_rank(rows, mode="full-gold-v2")
    result["definitions"] = DEFINITIONS
    result["completion"] = {s: ratio(sum(r[f"{s}_complete"] for r in rows), len(rows)) for s in ("step2", "step3")}
    result["step3_execution_states"] = dict(Counter(r.get("step3_status", "completed" if r["step3_complete"] else "not_completed") for r in rows))
    result["metrics"] = {}
    for name in rows[0]["metrics"] if rows else []:
        valid = [r["metrics"][name] for r in rows if r["metrics"][name] is not None and r["metrics"][name]["value"] is not None]
        result["metrics"][name] = {"macro": ratio(sum(v["value"] for v in valid), len(valid)),
                                   "micro": ratio(sum(v["numerator"] for v in valid), sum(v["denominator"] for v in valid)),
                                   "unavailable_questions": len(rows)-len(valid)}
    result["unmapped_gold"] = sum(r["n_unmapped"] for r in rows)
    result["retrieval_loss_counts"] = dict(Counter(g["retrieval_lost_at"] or "found" for r in rows for g in r["gold"]))
    result["loss_reason_availability"] = {
        "gold_with_trace": sum(bool(g.get("trace")) for r in rows for g in r["gold"]),
        "all_original_gold": sum(r["n_gold"] for r in rows),
        "required_reasons": ["unmapped_gold", "provider_miss", "year_filter", "dedup_merge",
                             "snowball_year", "snowball_no_abstract", "snowball_overlap"],
        "note": "Absent reasons mean no recorded observations, not proof of zero losses; missing traces stay not_in_step2_set."}
    result["gold_categories"] = dict(sum((Counter(r["gold_categories"]) for r in rows), Counter()))
    result["set_sizes"] = {}
    for key in ("direct_set_size", "final_set_size", "shortlist_size"):
        vals = [r[key] for r in rows if r[key] is not None]
        result["set_sizes"][key] = {"n_available": len(vals), "mean": statistics.mean(vals) if vals else None,
                                    "median": statistics.median(vals) if vals else None}
    providers = {}
    for r in rows:
        for src, values in r["providers"].items():
            c = providers.setdefault(src, [0, 0])
            c[0] += values["success"]["numerator"]
            c[1] += values["success"]["denominator"]
    result["providers"] = {src: {"success": ratio(a,b), "failure": ratio(b-a,b)} for src,(a,b) in providers.items()}
    result["evidence"] = {key: dict(Counter(r[key] for r in rows)) for key in ("direct_evidence", "provider_evidence")}
    result["note"] = "Frozen-output re-evaluation; no API/LLM calls. Full original gold denominators, unresolved gold counted as no confirmed hit. All questions retained. Missing stage data is null, never fabricated as zero."
    return result


def run(source, subset, mapping, out):
    questions = read(subset)["questions"]
    id_map = read(mapping)
    old = jsonl(source / "results.jsonl")
    old_rank = jsonl(source / "rank.jsonl")
    rows, hashes = [], {}
    def tracked(path, default=None):
        if path.exists():
            hashes[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
        return read(path, default)
    tracked(subset); tracked(mapping)
    if (source / "results.jsonl").exists():
        path = source / "results.jsonl"
        hashes[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    for q in questions:
        prior = old.get(q["qid"], {})
        name = prior.get("session")
        folder = source / "sessions" / name if name else source / "__missing__"
        raw = tracked(folder / "step2_raw_papers.json")
        config = tracked(folder / "step0_session_config.json", {})
        trace = tracked(folder / "step2_gold_trace.json", {})
        screening = tracked(folder / "step3_screening_all.json")
        shortlist = tracked(folder / "step3_shortlist.json")
        complete2 = raw is not None and not prior.get("error") and not prior.get("skipped")
        complete3 = (complete2 and bool(screening and screening.get("papers")) and shortlist is not None
                     and {p["id"] for p in screening["papers"]} == {p["id"] for p in raw["papers"]})
        row = evaluate(q, id_map, raw, trace, (screening or {}).get("papers"),
                       (shortlist or {}).get("papers"), config, step2_complete=complete2, step3_complete=complete3)
        row["session"] = name
        prior_rank = old_rank.get(q["qid"], {})
        row["step3_status"] = ("completed" if complete3 else "skipped_step2_miss" if not any(g["found"] for g in row["gold"])
                               else "failed" if prior_rank.get("error") else "explicitly_skipped" if prior_rank.get("skipped")
                               else "not_completed")
        rows.append(row)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in rows), encoding="utf-8")
    summary = summarise(rows)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# LitSearch full-gold evaluation", "", summary["note"], "",
             f"Original gold: {sum(r['n_gold'] for r in rows)} across {len(rows)} questions. Unmapped: {summary['unmapped_gold']}.", ""]
    for name, definition in DEFINITIONS.items():
        lines.append(f"- **{name}**: {definition}.")
    lines.extend(["", "## Results", ""])
    for step, v in summary["completion"].items():
        lines.append(f"{step} completion: {v['numerator']}/{v['denominator']} = {v['value']:.6f}.")
    for name, v in summary["metrics"].items():
        a, b = v["macro"], v["micro"]
        lines.append(f"{name}: macro sum of per-question values / defined questions = {a['numerator']}/{a['denominator']} = {a['value']}; micro summed counts = {b['numerator']}/{b['denominator']} = {b['value']}; undefined/unavailable questions = {v['unavailable_questions']}.")
    for kind in ("relevance", "composite"):
        lines.append(f"{kind} overall ({len(rows)} questions, failures/skips retained): {json.dumps(summary['overall'][kind])}.")
    lines.extend(["", f"Set sizes: {json.dumps(summary['set_sizes'])}",
                  f"Gold retrieval losses (counts, not question counts): {json.dumps(summary['retrieval_loss_counts'])}",
                  f"Loss-reason evidence coverage: {json.dumps(summary['loss_reason_availability'])}",
                  f"Gold screening categories: {json.dumps(summary['gold_categories'])}",
                  f"Provider query outcomes: {json.dumps(summary['providers'])}",
                  f"Evidence availability: {json.dumps(summary['evidence'])}", "",
                  "Historical direct sets were reconstructed from found_via with final enriched metadata. Provider outcomes were inferred from persisted source_failures and the completed query plan; no raw API responses were re-requested. Newly generated Step 2 traces record the exact pre-snowball snapshot and query outcomes.",
                  "Shortlist and retention metrics count unexecuted/failed Step 3 as zero; unscored gold are labelled not_scored rather than excluded. Candidate retention excludes empty Step 2 sets because 0/0 is undefined."])
    (out / "report.md").write_text("\n\n".join(lines)+"\n", encoding="utf-8")
    (out / "provenance.json").write_text(json.dumps({"source": str(source.resolve()), "input_sha256": hashes,
        "method": "offline-frozen-output-rescore-v2", "api_calls": 0, "llm_calls": 0}, indent=2), encoding="utf-8")
    print(json.dumps({"source": str(source), "questions": len(rows), "completion": summary["completion"],
                      "metrics": summary["metrics"], "evidence": summary["evidence"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "subset", "mapping", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.subset, args.mapping, args.out)
