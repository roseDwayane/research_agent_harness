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
    click.echo("## Research Pipeline Status / 研究流程狀態\n")
    click.echo(f"**Session / 工作階段**: {st['session']}")
    click.echo(f"**Topic / 研究主題**: {st['topic']}")
    cur = st["last_completed"]
    click.echo(f"**Current Step / 目前步驟**: {cur} — {STEP_NAMES.get(cur, 'not started')}")
    click.echo(f"**Cache mode**: {st['cache_mode']}\n")
    click.echo("| Step | Name | Status | Files |\n|------|------|--------|-------|")
    for r in st["steps"]:
        click.echo(f"| {r['step']} | {r['name']} | {'Done' if r['done'] else 'Pending'} | {', '.join(r['files']) or '—'} |")
    nxt = cur + 1
    click.echo(f"\n**Next action / 下一步**: {'pipeline complete' if nxt > 9 else f'run step {nxt} ({STEP_NAMES[nxt]})'}")
    cp = st["pending_checkpoint"]
    click.echo(f"**Checkpoint status / 檢查點狀態**: {'Checkpoint ' + str(cp) + ' pending' if cp else 'none pending'}")


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
