#!/usr/bin/env python3
"""Measure whether the INSTALLED skill triggers, by watching for the real Skill tool call.

skill-creator's run_eval.py registers a temporary clone of the skill and counts only calls to the clone. When the skill
under test is already installed in the project, the model calls the real one, so that harness reports 0% recall whatever
the description says. This test looks for `Skill {"skill": "<name>"}` instead.

A model often opens the file the user mentioned BEFORE choosing a skill, so up to MAX_PRELUDE look-around calls are
tolerated; stopping at the first tool call under-counts triggers badly (2/10 vs the real figure).

Safety: a triggered session would start executing the skill, so Bash/Write/Edit are disallowed and the process is killed
as soon as the Skill call is seen.

  python trigger_test.py --eval-set trigger_eval.json --skill ai-scientist-ideate --model claude-sonnet-4-5 [--runs 2]
"""
import argparse, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
MAX_PRELUDE = 4  # look-around tool calls tolerated before we conclude the skill was not chosen


def one(query: str, skill: str, model: str, timeout: int) -> str:
    """-> 'skill:<name>' for the first Skill call, 'tool:<name>' for another first tool, 'none', or 'error'."""
    cmd = ["claude", "-p", query, "--output-format", "stream-json", "--verbose",
           "--disallowedTools", "Bash", "Write", "Edit", "NotebookEdit"]
    if model:
        cmd += ["--model", model]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=ROOT, env=env, text=True)
    start, verdict, before = time.time(), "none", []
    try:
        for line in proc.stdout:
            if time.time() - start > timeout:
                verdict = "timeout"
                break
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("type") == "result" and e.get("is_error"):
                verdict = "error"
                break
            if e.get("type") == "assistant":
                for c in e.get("message", {}).get("content", []):
                    if c.get("type") == "tool_use":
                        name = c.get("name")
                        if name == "Skill":
                            verdict = f"skill:{(c.get('input') or {}).get('skill')}" + (f" (after {'+'.join(before)})" if before else "")
                            raise StopIteration
                        # Opening the file the user mentioned before picking a skill is normal, so a few harmless
                        # look-around calls are allowed (nothing that writes or executes is permitted anyway).
                        before.append(name)
                        verdict = "tools:" + "+".join(before)
                        if len(before) >= MAX_PRELUDE:
                            raise StopIteration
    except StopIteration:
        pass
    finally:
        proc.kill()
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-set", required=True); ap.add_argument("--skill", required=True)
    ap.add_argument("--model", default=None); ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--workers", type=int, default=5); ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-prelude", type=int, default=4, help="look-around tool calls tolerated before giving up")
    a = ap.parse_args()
    global MAX_PRELUDE
    MAX_PRELUDE = a.max_prelude
    items = json.loads(Path(a.eval_set).read_text())
    jobs = [(i, r) for i in range(len(items)) for r in range(a.runs)]
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda j: (j[0], one(items[j[0]]["query"], a.skill, a.model, a.timeout)), jobs))
    rows = []
    tp = fp = fn = tn = err = 0
    for i, it in enumerate(items):
        vs = [v for k, v in res if k == i]
        err += sum(v in ("error", "timeout") for v in vs)
        hits = sum(v.split(" ")[0] == f"skill:{a.skill}" for v in vs)
        fired = hits * 2 > len(vs)
        ok = fired == it["should_trigger"]
        tp += fired and it["should_trigger"]; fn += (not fired) and it["should_trigger"]
        fp += fired and not it["should_trigger"]; tn += (not fired) and not it["should_trigger"]
        rows.append({"query": it["query"], "should_trigger": it["should_trigger"], "hits": hits, "runs": len(vs),
                     "verdicts": vs, "correct": ok})
        print(f"[{'PASS' if ok else 'FAIL'}] {hits}/{len(vs)} expected={it['should_trigger']!s:<5} {vs}  {it['query'][:70]}")
    n = len(items)
    print(f"\naccuracy {tp + tn}/{n} | recall {tp}/{tp + fn} | false triggers {fp}/{fp + tn} | errored/timed-out calls {err}/{len(jobs)}")
    if a.out:
        Path(a.out).write_text(json.dumps({"model": a.model, "skill": a.skill, "summary": {"tp": tp, "fn": fn, "fp": fp, "tn": tn, "errors": err}, "rows": rows}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
