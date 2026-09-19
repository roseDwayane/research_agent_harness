"""Step 6 — research-sota.  LLM synthesis (structured) + code-built Obsidian canvas.

Long-context strategy (plan §9): ``context_strategy="summary"`` (default) first
makes one structured digest per paper (cached, so re-running the synthesis
prompt never re-reads papers), then synthesises from the digests.  ``"full"``
passes truncated full texts directly.
"""
from __future__ import annotations

import json
from typing import Any

from ..render.step6 import render_sota_review
from ..schemas.llm_outputs import S6PaperNote, S6Sota
from ..schemas.paper import Shortlist
from ..utils import dump_json, load_json, parse_frontmatter, truncate, write_text
from .base import Context, StepOutput

METHOD_COLOR = {"experimental": "1", "computational": "2", "review": "3", "observational": "4", "engineering": "5", "theoretical": "6"}


def run(ctx: Context) -> StepOutput:
    s = ctx.session
    sc = s.load_config()
    sl = Shortlist.model_validate(load_json(s.path("step3_shortlist.json")))
    keys = load_json(s.path("step4_citation_keys.json"))
    date = ctx.date(6)
    ft_dir = s.path("step5_full_text")
    papers = sorted(sl.papers, key=lambda p: (-p.screening.composite, p.id))
    key_of = {p.id: keys[p.id]["key"] for p in papers if p.id in keys}
    papers = [p for p in papers if p.id in key_of]

    # ---- gather per-paper text ----
    texts: dict[str, tuple[str, str]] = {}  # key → (access_level, text)
    n_full = 0
    for p in papers:
        k = key_of[p.id]
        f = ft_dir / f"{k}.md"
        if f.exists():
            raw = f.read_text(encoding="utf-8")
            fm = parse_frontmatter(raw)
            level = fm.get("access_level", "abstract-only")
            body = raw.split("---", 2)[-1] if raw.startswith("---") else raw
            texts[k] = (level, body.strip())
            if level != "abstract-only":
                n_full += 1
        else:
            texts[k] = ("abstract-only", f"# {p.title}\n\n## Abstract\n\n{p.abstract or '(no abstract)'}")
    abstract_only = n_full == 0

    # ---- per-paper digests (summary strategy) ----
    budget = ctx.config.llm.per_paper_char_budget
    notes_blob: list[str] = []
    digests: dict[str, S6PaperNote] = {}
    if ctx.config.llm.context_strategy == "summary":
        for p in papers:
            k = key_of[p.id]
            level, text = texts[k]
            d = ctx.llm.structured("s6_note", S6PaperNote, {"citation_key": k, "access_level": level, "text": text[: budget * 3]}, step=6, tag=k)
            d.citation_key = k
            digests[k] = d
            notes_blob.append(f"### {k} — {p.title} ({p.year}) [{level}] cluster={p.citation_network.cluster or '-'}\nProblem: {d.problem}\nMethod: {d.method}\nSample/dataset: {d.sample_or_dataset}\nResults: " + " | ".join(d.key_results) + "\nLimitations: " + " | ".join(d.limitations) + "\nFuture work: " + " | ".join(d.future_work) + f"\nMethodology: {d.methodology}")
        dump_json(s.path("step6_paper_digests.json"), {k: v.model_dump() for k, v in digests.items()})
    else:
        for p in papers:
            k = key_of[p.id]
            level, text = texts[k]
            notes_blob.append(f"### {k} — {p.title} ({p.year}) [{level}] cluster={p.citation_network.cluster or '-'}\n{text[:budget]}")

    clusters = "\n".join(f"- {c}: {', '.join(key_of[pid] for pid in ids if pid in key_of)}" for c, ids in _clusters(papers).items()) or "- (none detected)"
    note = "\n- IMPORTANT: no full texts were available; synthesis is abstract-only. Weight claims accordingly." if abstract_only else ""
    sota = ctx.llm.structured("s6_sota", S6Sota, {"topic": sc.topic, "population": sc.pico.population, "intervention": sc.pico.intervention, "comparison": sc.pico.comparison, "outcome": sc.pico.outcome, "clusters": clusters, "n": len(papers), "keys": ", ".join(key_of[p.id] for p in papers), "notes": "\n\n".join(notes_blob), "abstract_only_note": note}, step=6, tag="synthesis")

    # ---- code-side validation & repair of the map ----
    all_keys = [key_of[p.id] for p in papers]
    sota = _repair(sota, all_keys, digests)
    dump_json(s.path("step6_sota.json"), sota.model_dump())

    md = render_sota_review(sc, sota, papers, key_of, date, n_full, abstract_only)
    write_text(s.path("step6_sota_review.md"), md)
    canvas = build_canvas(sota, all_keys, s.name, ft_dir.exists() and any(ft_dir.glob("*.md")), ctx.config.paths.vault_root, s.dir, {key_of[p.id]: (truncate(p.title, 70), p.year) for p in papers})
    (s.path("step6_knowledge_graph.canvas")).write_text(json.dumps(canvas, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    meth = {m: sum(1 for x in sota.paper_map if x.methodology == m) for m in METHOD_COLOR}
    return StepOutput(files=[s.path("step6_sota_review.md"), s.path("step6_knowledge_graph.canvas"), s.path("step6_sota.json")], notes=["abstract-only synthesis"] if abstract_only else [], summary={"papers": len(papers), "full_text": n_full, "themes": [(t.number, t.title_en, len(t.paper_keys)) for t in sota.themes], "methodology": meth, "edges": len(sota.edges)})


def _clusters(papers) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in papers:
        if p.citation_network.cluster:
            out.setdefault(p.citation_network.cluster, []).append(p.id)
    return dict(sorted(out.items()))


def _repair(sota: S6Sota, all_keys: list[str], digests: dict[str, S6PaperNote]) -> S6Sota:
    valid = set(all_keys)
    theme_nums = {t.number for t in sota.themes}
    mapped = {m.citation_key: m for m in sota.paper_map if m.citation_key in valid and m.theme_number in theme_nums}
    # every paper exactly one theme; unmapped → theme of largest cluster of same methodology or theme 1
    first = sorted(theme_nums)[0]
    for k in all_keys:
        if k not in mapped:
            meth = digests[k].methodology if k in digests else "computational"
            from ..schemas.llm_outputs import S6PaperMap

            mapped[k] = S6PaperMap(citation_key=k, theme_number=first, methodology=meth, is_bridge=False)
    sota.paper_map = [mapped[k] for k in all_keys]
    for t in sota.themes:
        t.paper_keys = [k for k in all_keys if mapped[k].theme_number == t.number]
    sota.edges = [e for e in sota.edges if e.from_key in valid and e.to_key in valid and e.from_key != e.to_key]
    seen = set()
    uniq = []
    for e in sota.edges:
        sig = (e.from_key, e.to_key)
        if sig not in seen:
            seen.add(sig)
            uniq.append(e)
    sota.edges = uniq
    return sota


def build_canvas(sota: S6Sota, all_keys: list[str], session_name: str, has_files: bool, vault_root: str | None, session_dir, titles: dict[str, tuple[str, Any]]) -> dict[str, Any]:
    """Deterministic grid layout: overview on top, theme groups in a grid, papers stacked."""
    rel_prefix = _vault_relative(vault_root, session_dir)
    W, H, GAP, PAD = 320, 70, 30, 50
    nodes: list[dict[str, Any]] = [{"id": "overview", "type": "file", "file": f"{rel_prefix}step6_sota_review.md", "x": -225, "y": -300, "width": 450, "height": 100, "color": "6"}]
    meth = {m.citation_key: m.methodology for m in sota.paper_map}
    cols = 3
    gw = W + 2 * PAD
    x0 = -((min(cols, len(sota.themes)) * (gw + 200)) // 2)
    row_h = 0
    y = 0
    for i, t in enumerate(sorted(sota.themes, key=lambda t: t.number)):
        keys = [k for k in all_keys if k in t.paper_keys]
        gh = PAD * 2 + max(1, len(keys)) * (H + GAP) - GAP + 40
        col = i % cols
        if col == 0 and i > 0:
            y += row_h + 200
            row_h = 0
        gx = x0 + col * (gw + 200)
        nodes.append({"id": f"theme-{t.number}", "type": "group", "x": gx, "y": y, "width": gw, "height": gh, "label": f"{t.title_en} / {t.title_zh}", "color": "0"})
        for j, k in enumerate(keys):
            node = {"id": k, "x": gx + PAD, "y": y + PAD + 40 + j * (H + GAP), "width": W, "height": H, "color": METHOD_COLOR.get(meth.get(k, "computational"), "2")}
            if has_files:
                node.update({"type": "file", "file": f"{rel_prefix}step5_full_text/{k}.md"})
            else:
                title, year = titles.get(k, ("", ""))
                node.update({"type": "text", "text": f"**{k}**\n{title} ({year})"})
            nodes.append(node)
        row_h = max(row_h, gh)
    theme_of = {m.citation_key: m.theme_number for m in sota.paper_map}
    edges = []
    for e in sota.edges:
        same = theme_of.get(e.from_key) == theme_of.get(e.to_key)
        edges.append({"id": f"edge-{e.from_key}-{e.to_key}", "fromNode": e.from_key, "fromSide": "bottom" if same else "right", "toNode": e.to_key, "toSide": "top" if same else "left", "label": e.label})
    return {"nodes": nodes, "edges": edges}


def _vault_relative(vault_root: str | None, session_dir) -> str:
    from pathlib import Path

    if vault_root:
        try:
            return str(Path(session_dir).resolve().relative_to(Path(vault_root).resolve())).replace("\\", "/") + "/"
        except ValueError:
            pass
    return f"10_Research/{Path(session_dir).name}/"
