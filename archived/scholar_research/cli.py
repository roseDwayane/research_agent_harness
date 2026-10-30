"""scholar-research CLI (click).

    scholar-research new "EEG neurofeedback for MCI" [--config research.toml]
    scholar-research run --session 20260919_eeg-nf-mci --until 3 [--auto | --decisions d.toml]
    scholar-research step 3 --session …
    scholar-research status --session …
    scholar-research replay --session … --from 3
    scholar-research checkpoint 3 --lock GAP_001 --drop GAP_002
    scholar-research diff --session … [--a run1 --b run2]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import ENGINE_VERSION
from .config import Config
from .session import STEP_NAMES, Session


def _config(config_path: str | None, model: str | None, root: str | None) -> Config:
    cfg = Config.load(config_path)
    if model:
        cfg.llm.model = model
    if root:
        cfg.paths.research_root = root
    return cfg


def _ctx(session: Session, cfg: Config, mode: str, decisions: str | None):
    from .checkpoints import load_decisions
    from .steps.base import Context

    ctx = Context(session, cfg)
    ctx.checkpoint_mode = "file" if decisions else mode
    ctx.decisions = load_decisions(decisions)
    ctx.ui_print = lambda m: click.echo(m)
    return ctx


common = [
    click.option("--config", "config_path", default=None, help="research.toml path (default ./research.toml if present)"),
    click.option("--root", default=None, help="research root folder (default 10_Research)"),
    click.option("--model", default=None, help="override LLM model id"),
    click.option("--cache", "cache_mode", type=click.Choice(["read-write", "read-only", "refresh", "off"]), default=None),
    click.option("--refresh", is_flag=True, help="shortcut for --cache refresh (re-hit every external API)"),
]


def add_options(opts):
    def deco(f):
        for o in reversed(opts):
            f = o(f)
        return f

    return deco


@click.group()
@click.version_option(ENGINE_VERSION, prog_name="scholar-research")
def main() -> None:
    """Standalone, reproducible engine for the SCHOLAR /research pipeline."""


# ------------------------------------------------------------------------- #
@main.command()
@click.argument("topic")
@click.option("--session-id", default=None, help="YYYYMMDD (default today)")
@click.option("--no-run", is_flag=True, help="create the folder only; do not run Step 1")
@click.option("--auto", is_flag=True, help="auto-approve Checkpoint 1")
@click.option("--decisions", default=None, help="decisions.toml with [checkpointN] sections")
@add_options(common)
def new(topic, session_id, no_run, auto, decisions, config_path, root, model, cache_mode, refresh):
    """Start a new session from TOPIC and run Step 1 (research-init)."""
    cfg = _config(config_path, model, root)
    mode = "refresh" if refresh else cache_mode
    s = Session.create(Path(cfg.paths.research_root), topic, cfg, session_id, mode)
    click.echo(f"session: {s.dir}")
    if no_run:
        return
    from .pipeline import run_range

    ctx = _ctx(s, cfg, "auto" if auto else "interactive", decisions)
    run_range(ctx, 1, 1)
    _hint(s)


@main.command()
@click.option("--session", "needle", default=None, help="session folder name or substring (default: most recent)")
@click.option("--from", "first", type=int, default=None, help="first step to run (default: next incomplete)")
@click.option("--until", type=int, default=9, help="last step to run (default 9)")
@click.option("--auto", is_flag=True, help="resolve checkpoints with default rules")
@click.option("--decisions", default=None, help="decisions.toml with [checkpointN] sections")
@add_options(common)
def run(needle, first, until, auto, decisions, config_path, root, model, cache_mode, refresh):
    """Continue the pipeline (resume from the next incomplete step)."""
    cfg = _config(config_path, model, root)
    s = Session.find(Path(cfg.paths.research_root), needle, cfg, "refresh" if refresh else cache_mode)
    start = first or (s.last_completed() + 1)
    if start > 9:
        click.echo("pipeline already complete")
        return
    from .pipeline import run_range

    ctx = _ctx(s, cfg, "auto" if auto else "interactive", decisions)
    run_range(ctx, start, max(start, until))
    _hint(s)


@main.command()
@click.argument("n", type=int)
@click.option("--session", "needle", default=None)
@click.option("--auto", is_flag=True)
@click.option("--decisions", default=None)
@add_options(common)
def step(n, needle, auto, decisions, config_path, root, model, cache_mode, refresh):
    """Re-run a single step N (downstream outputs may become stale)."""
    cfg = _config(config_path, model, root)
    s = Session.find(Path(cfg.paths.research_root), needle, cfg, "refresh" if refresh else cache_mode)
    from .pipeline import run_range

    ctx = _ctx(s, cfg, "auto" if auto else "interactive", decisions)
    run_range(ctx, n, n)
    _hint(s)


@main.command()
@click.option("--session", "needle", default=None)
@click.option("--json", "as_json", is_flag=True)
@add_options(common)
def status(needle, as_json, config_path, root, model, cache_mode, refresh):
    """Show which steps are done, which files exist, and any pending checkpoint."""
    cfg = _config(config_path, model, root)
    s = Session.find(Path(cfg.paths.research_root), needle, cfg)
    st = s.status()
    if as_json:
        click.echo(json.dumps(st, indent=2, ensure_ascii=False))
        return
    click.echo("## Research Pipeline Status\n")
    click.echo(f"**Session**: {st['session']}")
    click.echo(f"**Topic**: {st['topic']}")
    cur = st["last_completed"]
    click.echo(f"**Current Step**: {cur} — {STEP_NAMES.get(cur, 'not started')}")
    click.echo(f"**Cache mode**: {st['cache_mode']}\n")
    click.echo("| Step | Name | Status | Files |\n|------|------|--------|-------|")
    for r in st["steps"]:
        click.echo(f"| {r['step']} | {r['name']} | {'Done' if r['done'] else 'Pending'} | {', '.join(r['files']) or '—'} |")
    nxt = cur + 1
    click.echo(f"\n**Next action**: {'pipeline complete' if nxt > 9 else f'run step {nxt} ({STEP_NAMES[nxt]})'}")
    cp = st["pending_checkpoint"]
    click.echo(f"**Checkpoint status**: {'Checkpoint ' + str(cp) + ' pending' if cp else 'none pending'}")


@main.command()
@click.argument("n", type=int)
@click.option("--session", "needle", default=None)
@click.option("--approve/--reject", default=True, help="checkpoints 1 and 4")
@click.option("--include", multiple=True, help="checkpoint 2: paper ids to rescue")
@click.option("--lock", default=None, help="checkpoint 3: gap id to lock")
@click.option("--drop", multiple=True, help="checkpoint 3: gap ids to drop")
@click.option("--constraint", default="", help="checkpoint 3: design constraint")
@click.option("--journal", default=None, help="checkpoint 4: override target journal")
@click.option("--note", default="")
@add_options(common)
def checkpoint(n, needle, approve, include, lock, drop, constraint, journal, note, config_path, root, model, cache_mode, refresh):
    """Record a human decision for checkpoint N (non-interactive alternative to stdin)."""
    from .checkpoints import apply, normalize

    cfg = _config(config_path, model, root)
    s = Session.find(Path(cfg.paths.research_root), needle, cfg)
    raw = {1: {"approved": approve, "note": note}, 2: {"include": list(include)}, 3: {"lock": lock, "drop": list(drop), "constraint": constraint}, 4: {"approved": approve, "journal": journal, "note": note}}[n]
    decision = normalize(n, raw)
    s.record_checkpoint(n, "cli", decision, note)
    apply(_ctx(s, cfg, "auto", None), n, decision)
    click.echo(f"recorded checkpoint {n}: {json.dumps(decision, ensure_ascii=False)}")


@main.command()
@click.option("--session", "needle", default=None)
@click.option("--from", "first", type=int, default=1)
@click.option("--until", type=int, default=None, help="default: last completed step")
@add_options(common)
def replay(needle, first, until, config_path, root, model, cache_mode, refresh):
    """Re-run steps from cache only (read-only) and verify outputs are byte-identical."""
    cfg = _config(config_path, model, root)
    s = Session.find(Path(cfg.paths.research_root), needle, cfg, "read-only")
    last = until or s.last_completed()
    from .pipeline import run_range, snapshot

    before = snapshot(s, list(range(first, last + 1)))
    ctx = _ctx(s, cfg, "auto", None)  # decisions already in checkpoints.json
    try:
        run_range(ctx, first, last, run_id=f"replay-{__import__('time').strftime('%Y%m%dT%H%M%S')}", stop_at_checkpoint=False)
    except Exception as e:  # noqa: BLE001
        click.echo(f"replay FAILED: {e}")
        if "cache miss" in str(e):
            click.echo("→ a cache miss means this step was never run with these exact inputs/prompts; run without replay to (re)generate.")
        sys.exit(2)
    after = snapshot(s, list(range(first, last + 1)))
    changed = [f for f in sorted(set(before) | set(after)) if before.get(f) != after.get(f)]
    if changed:
        click.echo(f"replay produced {len(changed)} changed file(s):")
        for f in changed:
            click.echo(f"  ✗ {f}")
        sys.exit(1)
    click.echo(f"replay OK — {len(after)} output files byte-identical (steps {first}–{last}), 0 cache misses")


@main.command()
@click.option("--session", "needle", default=None)
@click.option("--a", "run_a", default=None, help="run id (in .runs/) — default: second most recent")
@click.option("--b", "run_b", default=None, help="run id — default: most recent")
@add_options(common)
def diff(needle, run_a, run_b, config_path, root, model, cache_mode, refresh):
    """Diff two run manifests: which inputs, prompts, config or outputs changed."""
    from .manifest import diff_manifests

    cfg = _config(config_path, model, root)
    s = Session.find(Path(cfg.paths.research_root), needle, cfg)
    runs = sorted((s.dir / ".runs").glob("*.json"))
    if len(runs) < 2 and not (run_a and run_b):
        click.echo("need at least two runs in .runs/")
        sys.exit(1)
    a = s.dir / ".runs" / f"{run_a}.json" if run_a else runs[-2]
    b = s.dir / ".runs" / f"{run_b}.json" if run_b else runs[-1]
    click.echo(json.dumps(diff_manifests(a, b), indent=2, ensure_ascii=False))


@main.command()
def prompts():
    """List prompt files and versions (part of every LLM cache key)."""
    from .llm.prompts import list_prompts, load_prompt

    for n in list_prompts():
        p = load_prompt(n)
        click.echo(f"{n:<16} v{p.version:<8} tool={p.tool_name}")


@main.group("eval")
def eval_cmd() -> None:
    """Published-benchmark evals. Writes ``eval_runs/``, never mutates a research session."""


@eval_cmd.command("litsearch")
@click.option("--mode", type=click.Choice(["A", "B", "A3", "B3"]), default="A", help="A/B: set recall. A3/B3: Step 3 ranks on existing Step 2")
@click.option("--smoke", is_flag=True, help="run 2 questions (1 inline + 1 author) from the frozen subset")
@click.option("--limit", type=int, default=None, help="only the first N questions of the subset")
@click.option("--qid", "qid_only", default=None, help="run a single frozen qid (e.g. ls_071)")
@click.option("--freeze", "freeze_only", is_flag=True, help="download HuggingFace queries and freeze subset_v1.json")
@click.option("--map-only", is_flag=True, help="build/update gold CorpusId map, do not search")
@click.option("--subset", "subset_path", default=None, type=click.Path(exists=True), help="override frozen subset JSON")
@click.option("--run-dir", default=None, help="default eval_runs/litsearch/modeA, modeB, or modeA_s2 for A3")
@add_options(common)
def litsearch_eval(mode, smoke, limit, qid_only, freeze_only, map_only, subset_path, run_dir, config_path, root, model, cache_mode, refresh):
    """LitSearch Mode A/B set recall; A3 ranks existing Mode A Step 2 sessions."""
    from pathlib import Path

    from evaluation.step02.data import dump_subset, load_frozen_subset, load_hf_queries, stratified_table7
    from evaluation.step02.ids import build_gold_id_map, dump_map, load_map, unique_corpusids
    from evaluation.step03.rank import summarise_rank
    from evaluation.step02.runner import eval_config, run_mode_a, run_mode_b, summarise
    from evaluation.step03.runner import run_mode_a3

    _default_dir = {"A": "modeA", "B": "modeB", "A3": "modeA_s2", "B3": "modeB"}[mode]
    if run_dir:
        run = Path(run_dir)
    else:
        run = (Path(root) if root else Path(".")) / "eval_runs" / "litsearch" / _default_dir
    run.mkdir(parents=True, exist_ok=True)
    from evaluation.step02 import data as litsearch_data
    bundled = Path(litsearch_data.__file__).with_name("subset_v1.json")
    subset_file = Path(subset_path) if subset_path else (bundled if bundled.exists() else run / "subset_v1.json")

    if freeze_only:
        click.echo("loading princeton-nlp/LitSearch query split …")
        rows = stratified_table7(load_hf_queries())
        dump_subset(bundled, rows)
        dump_subset(run / "subset_v1.json", rows)
        n_in = sum(1 for r in rows if r["split"] == "inline")
        n_au = sum(1 for r in rows if r["split"] == "author")
        click.echo(f"froze {len(rows)} questions ({n_in} inline / {n_au} author) → {bundled}")
        return

    questions = load_frozen_subset(subset_file if subset_file.exists() else None)
    if smoke and mode == "A3":
        step2_done: dict = {}
        rp = run / "results.jsonl"
        if rp.exists():
            for line in rp.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    step2_done[row["qid"]] = row
        by_qid = {q["qid"]: q for q in questions}
        hit = next((by_qid[r["qid"]] for r in step2_done.values() if (r.get("set_recall") or 0) > 0 and r["qid"] in by_qid), None)
        miss = next((by_qid[r["qid"]] for r in step2_done.values() if (r.get("set_recall") or 0) == 0 and r["qid"] in by_qid), None)
        questions = [q for q in (hit, miss) if q]
        if not questions:
            raise click.ClickException("A3 --smoke needs Mode A results.jsonl with at least one scored question")
    elif smoke:
        inline = next(q for q in questions if q["split"] == "inline")
        author = next(q for q in questions if q["split"] == "author")
        questions = [inline, author]
    elif qid_only:
        hit = next((q for q in questions if q["qid"] == qid_only), None)
        if not hit:
            raise click.ClickException(f"qid {qid_only} not in frozen subset")
        questions = [hit]
    elif limit is not None:
        questions = questions[:limit]
    click.echo(f"subset: {len(questions)} questions  mode={mode}")

    cfg = eval_config(run / "sessions", "refresh" if refresh else (cache_mode or "read-write"))
    if model:
        cfg.llm.model = model
    if mode in ("B", "A3", "B3"):
        if cfg.llm.provider != "ollama" and not cfg.api.anthropic_api_key:
            raise click.ClickException(
                f"Mode {mode} needs an LLM. Set SCHOLAR_LLM_PROVIDER=ollama SCHOLAR_LLM_BASE_URL=… SCHOLAR_LLM_MODEL=… in .env"
            )
    if root:
        # eval_config already set research_root to sessions; keep API keys from env/toml
        pass
    map_path = run / "gold_id_map.json"
    id_map = load_map(map_path)
    if not id_map:
        for cand in (Path("eval_runs/litsearch/modeA_s2/gold_id_map.json"), Path("eval_runs/litsearch/modeA/gold_id_map.json")):
            if cand.exists():
                id_map = load_map(cand)
                click.echo(f"reused gold id map from {cand}")
                break
    cids = unique_corpusids(questions)
    click.echo(f"gold id map: {sum(1 for v in id_map.values() if v.get('ok'))}/{len(cids)} resolved")
    id_map = build_gold_id_map(cids, run / ".cache", cfg.api.semantic_scholar_key, id_map)
    dump_map(map_path, id_map)
    n_ok = sum(1 for v in id_map.values() if v.get("ok"))
    click.echo(f"gold id map: {n_ok}/{len(cids)} resolved → {map_path}")
    if n_ok == 0:
        click.echo("WARNING: 0 gold papers resolved. Semantic Scholar is likely rate-limiting (no S2_API_KEY). Mode A can still search; matching will fall back to unmapped_gold.")
    if map_only:
        return

    def _echo(msg: str) -> None:
        try:
            click.echo(msg)
        except UnicodeEncodeError:
            click.echo(msg.encode("ascii", "replace").decode("ascii"))

    if mode == "B":
        rows = run_mode_b(questions, id_map, run, cfg, shared_cache=run / ".cache", say=_echo)
        summary = summarise(rows, mode=mode)
    elif mode in ("A3", "B3"):
        rows = run_mode_a3(questions, id_map, run, cfg, shared_cache=run / ".cache", say=_echo, mode=mode)
        summary = summarise_rank(rows, mode=mode)
    else:
        rows = run_mode_a(questions, id_map, run, cfg, shared_cache=run / ".cache", say=_echo)
        summary = summarise(rows, mode=mode)
    title = f"## Mode {mode} summary" + ("" if mode in ("A3", "B3") else " (set recall, not R@k)")
    try:
        click.echo(f"\n{title}")
        click.echo(json.dumps(summary, indent=2, ensure_ascii=False))
    except UnicodeEncodeError:
        click.echo(json.dumps(summary, indent=2, ensure_ascii=True))
    if mode == "B":
        a_sum = Path("eval_runs/litsearch/modeA_s2/summary.json")
        if a_sum.exists():
            a = json.loads(a_sum.read_text(encoding="utf-8"))
            click.echo(
                f"\nA vs B set recall: A {a.get('overall', {}).get('set_recall')} → B {summary['overall']['set_recall']} "
                f"(A |S|={a.get('overall', {}).get('mean_set_size')} B |S|={summary['overall']['mean_set_size']})"
            )


@eval_cmd.command("step8-rubric")
@click.option("--session", "needle", default=None, help="session folder name or substring (default: most recent)")
@click.option("--only", multiple=True, help="metric id(s) to score, e.g. problem.clarity (default: all 10 Problem/Method metrics)")
@click.option("--judge-model", default=None, help="override [judge].model / SCHOLAR_JUDGE_MODEL")
@click.option("--judge-provider", type=click.Choice(["anthropic", "ollama"]), default=None)
@click.option("--allow-same-model", is_flag=True, help="allow judge.model == [llm].model (diagnostics only)")
@click.option("--list-metrics", is_flag=True, help="print the 10 metric ids and exit")
@add_options(common)
def step8_rubric(needle, only, judge_model, judge_provider, allow_same_model, list_metrics, config_path, root, model, cache_mode, refresh):
    """Score an existing Step 8 hypothesis with 10 ResearchAgent-derived Problem/Method metrics.

    Reads ``step8_hypothesis.json`` (does not re-run Step 8). Uses an independent
    ``[judge]`` LLM client. Writes ``step8_rubric_scores.json`` + ``step8_rubric_report.md``
    next to the spec; scores never feed Steps 8/9.
    """
    from evaluation.step08 import METRICS, run_step8_rubric

    if list_metrics:
        for m in METRICS:
            click.echo(f"{m.id:<28} {m.category:<10} {m.name}")
        return

    cfg = _config(config_path, model, root)
    if judge_model:
        cfg.judge.model = judge_model
    if judge_provider:
        cfg.judge.provider = judge_provider  # type: ignore[assignment]
    mode = "refresh" if refresh else cache_mode
    s = Session.find(Path(cfg.paths.research_root), needle, cfg, mode)
    try:
        payload = run_step8_rubric(
            s,
            cfg,
            only=list(only) or None,
            allow_same_model=allow_same_model,
            say=lambda m: click.echo(m),
        )
    except (RuntimeError, FileNotFoundError, KeyError) as e:
        raise click.ClickException(str(e)) from e
    means = payload["means"]
    categories = '  '.join(f'{category} {mean:.2f}' for category, mean in means['by_category'].items())
    click.echo(f"\noverall {means['overall']:.2f}  {categories}")
    click.echo(f"files: {s.path('step8_rubric_scores.json')}  {s.path('step8_rubric_report.md')}")


@eval_cmd.command("ideabench-build")
@click.option("--out", "out_dir", default=None, help="default eval_runs/ideabench/subset_v1")
@click.option("--m", "m_targets", type=int, default=20, help="number of target papers")
@click.option("--start", "target_start", default="2026-01-01", help="publicationDateOrYear start (inclusive)")
@click.option("--end", "target_end", default="2026-06-30", help="publicationDateOrYear end (inclusive)")
@click.option(
    "--eval-model",
    "eval_models",
    multiple=True,
    default=["local_qwen_3.8B"],
    help="MODEL_REGISTRY key(s) whose cutoffs must precede --start (repeatable)",
)
@click.option("--low-k", type=int, default=5, help="low-resource reference count after filtering")
@click.option("--seed", type=int, default=0)
@click.option(
    "--source",
    type=click.Choice(["openalex", "pubmed", "pubmed+openalex", "s2"]),
    default="openalex",
    help="where to find target papers (default openalex; s2 is legacy)",
)
@click.option("--skip-extract", is_flag=True, help="fetch targets+refs only; skip Figure-5 idea extraction")
@click.option("--list-cutoffs", is_flag=True, help="print MODEL_REGISTRY and exit")
@add_options(common)
def ideabench_build(out_dir, m_targets, target_start, target_end, eval_models, low_k, seed, source, skip_extract, list_cutoffs, config_path, root, model, cache_mode, refresh):
    """Build an IdeaBench-style biomedical target/ref subset (cutoff-safe window).

    Writes ``targets.jsonl``, ``refs/{id}/{{all,filtered,lowK}}.json``, optional
    ``ideas/{id}.txt`` via the paper's Figure-5 extract prompt. Does not run P1/P2
    or Insight Score ranking yet.
    """
    from evaluation.step08.ideabench import MODEL_REGISTRY, build_subset
    from evaluation.step08.ideabench.cutoffs import safe_start_after_cutoffs

    if list_cutoffs:
        for name, d in sorted(MODEL_REGISTRY.items()):
            click.echo(f"{name:<24} cutoff={d}")
        models = list(eval_models) or ["local_qwen_3.8B"]
        click.echo(f"safe_start({models}) = {safe_start_after_cutoffs(models).isoformat()}")
        return

    cfg = _config(config_path, model, root)
    if refresh:
        cfg.cache_mode = "refresh"
    elif cache_mode:
        cfg.cache_mode = cache_mode  # type: ignore[assignment]
    run = Path(out_dir) if out_dir else (Path(root) if root else Path(".")) / "eval_runs" / "ideabench" / "subset_v1"
    models = list(eval_models) or ["local_qwen_3.8B"]
    try:
        manifest = build_subset(
            run,
            cfg,
            models=models,
            target_start=target_start,
            target_end=target_end,
            m=m_targets,
            low_k=low_k,
            seed=seed,
            source=source,
            skip_extract=skip_extract,
            say=lambda m: click.echo(m),
        )
    except (ValueError, KeyError, RuntimeError) as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"\nmanifest: {run / 'manifest.json'}")
    click.echo(f"kept {manifest['m_kept']}/{manifest['m_requested']} targets (source={manifest.get('target_source')})")


@eval_cmd.command("ideabench-run")
@click.option("--dataset", type=click.Path(exists=True, file_okay=False, path_type=Path), default="eval_runs/ideabench/subset_v1", show_default=True)
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default="eval_runs/ideabench/experiment_v1", show_default=True)
@click.option("--limit", type=click.IntRange(min=1), default=None, help="Run only the first N tasks for a smoke test.")
@click.option("--phase", type=click.Choice(["all", "generate", "rank", "rubric"]), default="all")
@click.option("--metric", "metrics", multiple=True, type=click.Choice(["novelty", "feasibility", "significance", "clarity"]), help="Default: novelty and feasibility.")
@click.option("--seed", type=int, default=0)
@click.option("--rubric", is_flag=True, help="Also score each P2 spec with 10 independent Problem/Method rubric metrics.")
@click.option("--judge-model", default=None)
@click.option("--max-tokens", type=click.IntRange(min=1), default=None, help="Override generator output budget for this experiment only.")
@click.option("--num-ctx", type=click.IntRange(min=1), default=None, help="Override Ollama generator context window for this experiment only.")
@add_options(common)
def ideabench_run(dataset, out_dir, limit, phase, metrics, seed, rubric, judge_model, max_tokens, num_ctx, config_path, root, model, cache_mode, refresh):
    """Run P1/P2 on frozen refs, then independently rank and compute Insight Scores.

    P2: Steps 3/4/6/7 -> one Step 8 spec per actual gap. P1 generates
    the same number of ideas on each task. Step 5 is abstract-only.
    Balanced presentation orders per metric. Scores never feed generation.
    Resume with the same command and output directory; changed contracts fail.
    """
    from evaluation.step08.ideabench.experiment import run_experiment

    cfg = _config(config_path, model, root)
    if judge_model:
        cfg.judge.model = judge_model
    if max_tokens:
        cfg.llm.max_tokens = max_tokens
    if num_ctx:
        cfg.llm.num_ctx = num_ctx
    cfg.cache_mode = "refresh" if refresh else (cache_mode or cfg.cache_mode)
    try:
        summary = run_experiment(dataset, out_dir, cfg, limit=limit, phase=phase,
                                 metrics=list(metrics) or None, seed=seed, rubric=rubric, say=click.echo)
    except (ValueError, RuntimeError, KeyError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(summary, ensure_ascii=True, indent=2))
    click.echo(f"Results: {out_dir}")
    if summary.get("status") == "incomplete" or summary.get("generation_errors") or summary.get('n_specs_failed') or summary.get('rubric', {}).get('n_specs_failed'):
        raise click.ClickException("Some tasks failed or were excluded; review task errors before interpreting scores.")


def _hint(s: Session) -> None:
    cp = s.pending_checkpoint()
    nxt = s.last_completed() + 1
    if cp:
        click.echo(f"\nnext: resolve Checkpoint {cp}, then `scholar-research run --session {s.name}`")
    elif nxt <= 9:
        click.echo(f"\nnext: `scholar-research run --session {s.name}` (step {nxt}: {STEP_NAMES[nxt]})")
    else:
        click.echo("\npipeline complete ✓")


if __name__ == "__main__":  # pragma: no cover
    main()
