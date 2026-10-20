"""Markdown report for Step 8 absolute rubric scores."""
from __future__ import annotations

from typing import Any


def render_rubric_report(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    means = payload["means"]
    lines: list[str] = [
        "# Step 8 Absolute Rubric / 假說規格絕對評分",
        "",
        f"- Session: `{meta['session']}`",
        f"- Locked gap: `{meta.get('locked_gap')}`",
        f"- Generator model: `{meta.get('generator_model')}`",
        f"- Judge model: `{meta['judge_model']}` (provider `{meta['judge_provider']}`)",
        f"- Prompt: `{meta['prompt']}` v{meta['prompt_version']}",
        f"- Field type: `{meta.get('field_type')}`",
        f"- Scored at: {meta.get('scored_at')}",
        "",
        "> Independent judge only. Scores are **not** inputs to Step 8 or Step 9.",
        "> 獨立評審分數；不會回寫假說規格，也不會進入 Step 9。",
        "",
        "## Summary / 摘要",
        "",
        f"| Category | Mean (1–5) |",
        f"|----------|------------|",
    ]
    for cat, mean in means['by_category'].items():
        lines.append(f"| {cat} | {mean:.2f} |")
    lines += [
        f"| **Overall** | **{means['overall']:.2f}** |",
        "",
        "## Per-metric scores / 分項",
        "",
        "| Id | Category | Metric | Rating |",
        "|----|----------|--------|--------|",
    ]
    for row in payload["ratings"]:
        lines.append(f"| `{row['id']}` | {row['category']} | {row['name']} | {row['rating']} |")
    lines += ["", "## Reviews / 評語", ""]
    for row in payload["ratings"]:
        lines += [
            f"### {row['category']} · {row['name']} (`{row['id']}`) — {row['rating']}/5",
            "",
            f"**Review:** {row['review']}",
            "",
            f"**Feedback:** {row['feedback']}",
            "",
        ]
    lines += [
        "---",
        "",
        "Files: `step8_rubric_scores.json`, `step8_rubric_report.md`",
        "Source: `step8_hypothesis.json` (read-only)",
    ]
    return "\n".join(lines) + "\n"
