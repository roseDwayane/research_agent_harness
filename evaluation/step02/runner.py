"""Run LitSearch Mode A: one Step 2 session per question, no LLM."""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from scholar_research.config import Config
from scholar_research.pipeline import run_range
from scholar_research.session import Session, now_iso
from scholar_research.steps.base import Context
from scholar_research.utils import dump_json, load_json
from .fixtures import lock_eval_retrieval, mode_a_config, timeframe_for
from .ids import years_for
from .match import lost_at_from_trace, match_gold
from .metrics import TABLE7, mean, set_recall


def eval_config(root: Path, cache_mode: str = "read-write") -> Config:
    cfg = Config.load(None)
    cfg.paths.research_root = str(root)
    cfg.cache_mode = cache_mode  # type: ignore[assignment]
    cfg.search.sources = ["semantic_scholar", "openalex", "arxiv"]
    cfg.search.results_per_query = 100
    # Step 1 PICO+Q1–Q5 is a small JSON object; 32k ctx / 8k tokens made qwen3.8 stall for tens of minutes.
    if cfg.llm.provider == "ollama":
        cfg.llm.think = False
        if cfg.llm.num_ctx > 8192:
            cfg.llm.num_ctx = 8192
        if cfg.llm.max_tokens > 3072:
            cfg.llm.max_tokens = 3072
        if cfg.llm.request_timeout > 300:
            cfg.llm.request_timeout = 300.0
    return cfg


def session_id_for(qid: str, prefix: str = "20260924") -> str:
    n = "".join(ch for ch in qid if ch.isdigit()) or "0"
    return f"{prefix}{int(n):03d}"


def _eval_gold_list(question: dict[str, Any], id_map: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cid in question.get("corpusids") or []:
        rec = id_map.get(str(cid))
        if rec and rec.get("ok"):
            out.append(rec)
    return out


def _gold_trace_map(session: Session) -> dict[str, dict[str, Any]]:
    if not session.has("step2_gold_trace.json"):
        return {}
    data = load_json(session.path("step2_gold_trace.json")) or {}
    return {str(g.get("corpusId")): g for g in (data.get("golds") or []) if g.get("corpusId") is not None}


def score_question(question: dict[str, Any], papers: list[dict[str, Any]], id_map: dict[str, Any], y0: int, y1: int, gold_trace: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    gold_hits = []
    found_keys: list[str] = []
    for cid in question.get("corpusids") or []:
        rec = id_map.get(str(cid)) or {"corpusId": cid, "ok": False}
        if not rec.get("ok"):
            gold_hits.append({"corpusId": cid, "mapped": False, "found": False, "lost_at": "unmapped_gold", "method": None})
            continue
        paper, method = match_gold(rec, papers)
        year = rec.get("year")
        trace = (gold_trace or {}).get(str(cid))
        if paper is not None:
            lost = None
            found_keys.append(str(cid))
        elif trace:
            lost = lost_at_from_trace(trace)
        elif isinstance(year, int) and not (y0 <= year <= y1):
            lost = "year_filter"
        else:
            lost = "not_in_step2_set"
        gold_hits.append(
            {
                "corpusId": cid,
                "mapped": True,
                "found": paper is not None,
                "lost_at": lost,
                "method": method,
                "paper_id": None if paper is None else paper.get("id"),
                "year": year,
                "trace": trace,
            }
        )
    mapped = [g for g in gold_hits if g["mapped"]]
    gold_ids = [str(cid) for cid in question.get("corpusids") or []]
    return {
        "qid": question["qid"],
        "split": question.get("split"),
        "query_set": question.get("query_set"),
        "quality": question.get("quality"),
        "n_gold": len(question.get("corpusids") or []),
        "n_mapped": len(mapped),
        "set_size": len(papers),
        "set_recall": set_recall(gold_ids, found_keys),
        "mapped_only_recall": len(found_keys) / len(mapped) if mapped else None,
        "mapping_coverage": len(mapped) / len(gold_ids) if gold_ids else 0.0,
        "n_unmapped": len(gold_ids) - len(mapped),
        "gold": gold_hits,
    }


def summarise(rows: list[dict[str, Any]], *, mode: str = "A") -> dict[str, Any]:
    def bucket(pred):
        xs = [r for r in rows if pred(r)]
        return {
            "n": len(xs),
            "set_recall": round(mean([r["set_recall"] for r in xs]), 3),
            "mean_set_size": round(mean([float(r["set_size"]) for r in xs]), 1),
        }

    lost = Counter()
    for r in rows:
        for g in r.get("gold") or []:
            lost[g.get("lost_at") or "found"] += 1
    by_split = {k: bucket(lambda r, key=k: r.get("split") == key) for k in ("inline", "author")}
    by_qual = {str(k): bucket(lambda r, key=k: r.get("quality") == key) for k in (1, 2)}
    return {
        "n_questions": len(rows),
        "overall": bucket(lambda _r: True),
        "by_split": by_split,
        "by_quality": by_qual,
        "funnel": dict(lost),
        "table7_commercial_R@5": TABLE7,
        "mode": mode,
        "note": (
            "Mode A reports set recall, not R@5. Table 7 is the closest published open-corpus baseline and is not directly comparable."
            if mode == "A"
            else "Mode B = Step 1 PICO+Q1–Q5 then Step 2. Set recall, not R@5. A vs B isolates Step 1 query formulation (same widened timeframe)."
        ),
    }


def _should_skip(prev: dict[str, Any] | None) -> bool:
    if not prev:
        return False
    if prev.get("skipped"):
        return True
    fails = (prev.get("search_summary") or {}).get("source_failures") or []
    infra_miss = (prev.get("set_size") or 0) == 0
    oa_throttled = any("openalex" in str(f) and "429" in str(f) for f in fails)
    return not infra_miss and not oa_throttled and not prev.get("error")


def _write_results(results_path: Path, done: dict[str, dict[str, Any]]) -> None:
    results_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in done.values()),
        encoding="utf-8",
    )


def _load_done(results_path: Path) -> dict[str, dict[str, Any]]:
    done: dict[str, dict[str, Any]] = {}
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["qid"]] = row
    return done


def run_mode_a(
    questions: list[dict[str, Any]],
    id_map: dict[str, Any],
    run_dir: Path,
    cfg: Config,
    *,
    shared_cache: Path,
    say: Callable[[str], None] = print,
    skip_existing: bool = True,
) -> list[dict[str, Any]]:
    sessions_root = run_dir / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"
    done = _load_done(results_path)
    out: list[dict[str, Any]] = []
    for q in questions:
        qid = q["qid"]
        prev = done.get(qid)
        if skip_existing and _should_skip(prev):
            say(f"  skip {qid} (already scored)")
            out.append(prev)  # type: ignore[arg-type]
            continue
        sid = session_id_for(qid)
        years = years_for(q, id_map)
        s = Session.create(sessions_root, q["query"], cfg, session_id=sid, cache_dir=shared_cache)
        sc = mode_a_config(qid, q["query"], years, sid, now_iso())
        s.save_config(sc)
        s.state["topic_original"] = q["query"]
        s.state["session_id"] = sid
        s.state["eval_gold"] = _eval_gold_list(q, id_map)
        s.save_state()
        y0, y1 = sc.year_range()
        say(f"\n>> {qid} [{q.get('split')} qual={q.get('quality')}] {q['query'][:90]}")
        t0 = time.time()
        ctx = Context(s, cfg)
        ctx.checkpoint_mode = "auto"
        ctx.ui_print = say
        run_range(ctx, 2, 2)
        raw = load_json(s.path("step2_raw_papers.json"))
        row = score_question(q, raw.get("papers") or [], id_map, y0, y1, gold_trace=_gold_trace_map(s))
        row["mode"] = "A"
        row["session"] = s.name
        row["timeframe"] = sc.pico.timeframe
        row["wall_seconds"] = round(time.time() - t0, 1)
        row["search_summary"] = raw.get("search_summary")
        done[qid] = row
        _write_results(results_path, done)
        say(f"  set_recall={row['set_recall']:.2f}  |S|={row['set_size']}  {row['wall_seconds']}s")
        out.append(row)
    dump_json(run_dir / "summary.json", summarise(out, mode="A"))
    return out


def run_mode_b(
    questions: list[dict[str, Any]],
    id_map: dict[str, Any],
    run_dir: Path,
    cfg: Config,
    *,
    shared_cache: Path,
    say: Callable[[str], None] = print,
    skip_existing: bool = True,
    llm_backend: Any | None = None,
) -> list[dict[str, Any]]:
    """Step 1 (PICO + Q1–Q5) then Step 2. Timeframe/field locked like Mode A."""
    from scholar_research.pipeline import PipelineError

    sessions_root = run_dir / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"
    done = _load_done(results_path)
    out: list[dict[str, Any]] = []
    n_todo = sum(1 for q in questions if not (skip_existing and _should_skip(done.get(q["qid"]))))
    n_skip = len(questions) - n_todo
    if n_skip:
        say(f"skip {n_skip} already scored; running {n_todo} remaining")
    n_run = 0
    for q in questions:
        qid = q["qid"]
        prev = done.get(qid)
        if skip_existing and _should_skip(prev):
            out.append(prev)  # type: ignore[arg-type]
            continue
        n_run += 1
        sid = session_id_for(qid, prefix="20260925")
        years = years_for(q, id_map)
        s = Session.create(sessions_root, q["query"], cfg, session_id=sid, cache_dir=shared_cache)
        s.state["topic_original"] = q["query"]
        s.state["session_id"] = sid
        s.state["eval_gold"] = _eval_gold_list(q, id_map)
        s.save_state()
        say(f"\n>> {qid} [{n_run}/{n_todo}] [{q.get('split')} qual={q.get('quality')}] {q['query'][:90]}")
        t0 = time.time()
        row: dict[str, Any]
        try:
            ctx1 = Context(s, cfg, llm_backend=llm_backend)
            ctx1.checkpoint_mode = "auto"
            ctx1.ui_print = say
            run_range(ctx1, 1, 1)
            sc = lock_eval_retrieval(s.load_config(), years)
            s.save_config(sc)
            y0, y1 = sc.year_range()
            ctx2 = Context(s, cfg, llm_backend=llm_backend)
            ctx2.checkpoint_mode = "auto"
            ctx2.ui_print = say
            run_range(ctx2, 2, 2)
            raw = load_json(s.path("step2_raw_papers.json")) if s.has("step2_raw_papers.json") else {}
            row = score_question(q, raw.get("papers") or [], id_map, y0, y1, gold_trace=_gold_trace_map(s))
            row["queries"] = [{"id": qq.id, "query": qq.query, "strategy": qq.strategy} for qq in sc.queries]
            row["field_type"] = sc.field_type
            row["pico"] = sc.pico.model_dump()
            row["timeframe"] = sc.pico.timeframe
            row["search_summary"] = raw.get("search_summary")
            row["error"] = None
        except (PipelineError, Exception) as e:  # noqa: BLE001
            y0s, y1s = (int(x) for x in timeframe_for(years).split("-"))
            row = score_question(q, [], id_map, y0s, y1s)
            row["queries"] = []
            row["timeframe"] = timeframe_for(years)
            row["error"] = f"{type(e).__name__}: {e}"
            say(f"  ERROR {qid}: {row['error']}")
        row["mode"] = "B"
        row["session"] = s.name
        row["wall_seconds"] = round(time.time() - t0, 1)
        done[qid] = row
        _write_results(results_path, done)
        say(f"  set_recall={row['set_recall']:.2f}  |S|={row['set_size']}  {row['wall_seconds']}s  scored={len(done)} remaining={len(questions) - len(done)}")
        out.append(row)
    dump_json(run_dir / "summary.json", summarise(out, mode="B"))
    return out


def _should_skip_rank(prev: dict[str, Any] | None) -> bool:
    if not prev:
        return False
    return not prev.get("error")


def run_mode_a3(
    questions: list[dict[str, Any]],
    id_map: dict[str, Any],
    run_dir: Path,
    cfg: Config,
    *,
    shared_cache: Path,
    say: Callable[[str], None] = print,
    skip_existing: bool = True,
    llm_backend: Any | None = None,
    mode: str = "A3",
) -> list[dict[str, Any]]:
    """Reuse existing Step 2 sessions. Misses → R@k=0. Hits → Step 3 then rank."""
    from scholar_research.pipeline import PipelineError
    from .rank import rank_from_step2_miss, score_ranking, summarise_rank

    sessions_root = run_dir / "sessions"
    step2_path = run_dir / "results.jsonl"
    rank_path = run_dir / "rank.jsonl"
    step2 = _load_done(step2_path)
    done = _load_done(rank_path)
    out: list[dict[str, Any]] = []
    n_todo = sum(1 for q in questions if not (skip_existing and _should_skip_rank(done.get(q["qid"]))))
    n_skip = len(questions) - n_todo
    if n_skip:
        say(f"skip {n_skip} already ranked; running {n_todo} remaining")
    n_run = 0
    for q in questions:
        qid = q["qid"]
        prev = done.get(qid)
        if skip_existing and _should_skip_rank(prev):
            out.append(prev)  # type: ignore[arg-type]
            continue
        n_run += 1
        s2 = step2.get(qid)
        say(f"\n>> {qid} [{n_run}/{n_todo}] [{q.get('split')} qual={q.get('quality')}]")
        t0 = time.time()
        if not s2:
            row = rank_from_step2_miss(score_question(q, [], id_map, 1990, 2026))
            row["error"] = "missing_step2_row"
            row["mode"] = mode
            say(f"  ERROR {qid}: missing Step 2 row")
        elif s2.get("skipped") or (s2.get("set_recall") or 0) == 0:
            row = rank_from_step2_miss(s2)
            row["error"] = None
            row["mode"] = mode
            say(f"  skip Step 3 (set_recall={s2.get('set_recall')}) R@k=0")
        else:
            try:
                session_name = s2.get("session")
                if not session_name:
                    raise PipelineError("Step 2 row has no session name")
                s = Session(sessions_root / session_name, cfg, cache_dir=shared_cache)
                if not s.has("step2_raw_papers.json"):
                    raise PipelineError(f"missing step2_raw_papers.json in {session_name}")
                if not s.has("step3_screening_all.json"):
                    ctx = Context(s, cfg, llm_backend=llm_backend)
                    ctx.checkpoint_mode = "auto"
                    ctx.ui_print = say
                    run_range(ctx, 3, 3)
                raw = load_json(s.path("step2_raw_papers.json"))
                screened = (load_json(s.path("step3_screening_all.json")) or {}).get("papers") or []
                sc = s.load_config()
                y0, y1 = sc.year_range()
                row = score_ranking(q, raw.get("papers") or [], id_map, y0, y1, screened)
                row["error"] = None
                row["session"] = s.name
                row["timeframe"] = sc.pico.timeframe
                rel = row["relevance"]
                comp = row["composite"]
                say(
                    f"  relevance  R@5={rel['R@5']:.2f}  R@20={rel['R@20']:.2f}  MRR={rel['MRR']:.3f}  nDCG@10={rel['nDCG@10']:.3f}"
                    f"  rank={row['gold'][0].get('rank_relevance')}"
                )
                say(
                    f"  composite  R@5={comp['R@5']:.2f}  R@20={comp['R@20']:.2f}  MRR={comp['MRR']:.3f}  nDCG@10={comp['nDCG@10']:.3f}"
                    f"  rank={row['gold'][0].get('rank_composite')}  |S|={row['set_size']}"
                )
            except (PipelineError, Exception) as e:  # noqa: BLE001
                row = rank_from_step2_miss(s2)
                row["error"] = f"{type(e).__name__}: {e}"
                say(f"  ERROR {qid}: {row['error']}")
        row["mode"] = mode
        row["wall_seconds"] = round(time.time() - t0, 1)
        done[qid] = row
        _write_results(rank_path, done)
        out.append(row)
    dump_json(run_dir / "rank_summary.json", summarise_rank(out, mode=mode))
    return out

