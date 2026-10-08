"""Step 5 — research-fulltext.  Code fetches (cached, sha256'd); no LLM calls.

Replaces the WebFetch path with the explicit fallback chain in
``providers/fulltext/sources.py``.  There is no "summarized" status any more:
extraction is verbatim by construction, and quality is measured by code
(char_count / section_count).
"""
from __future__ import annotations

import re
from typing import Any

from ..providers.fulltext.sources import FulltextFetcher, FulltextResult
from ..schemas.paper import ScreenedPaper, Shortlist
from ..utils import dump_json, frontmatter, load_json, md_cell, truncate, write_text
from .base import Context, StepOutput


def run(ctx: Context) -> StepOutput:
    s, fcfg = ctx.session, ctx.config.fulltext
    sc = s.load_config()
    sl = Shortlist.model_validate(load_json(s.path("step3_shortlist.json")))
    keys = load_json(s.path("step4_citation_keys.json"))
    date = ctx.date(5)
    out_dir = s.path("step5_full_text")
    out_dir.mkdir(exist_ok=True)
    fetcher = FulltextFetcher(ctx.http, s.cache, ctx.config.api.unpaywall_email, ctx.config.api.ncbi_api_key, fcfg.min_chars_full, fcfg.min_sections_full)

    queue = sorted(sl.papers, key=lambda p: (-p.screening.composite, p.id))
    results: list[dict[str, Any]] = []
    files = []
    for i, p in enumerate(queue, 1):
        key = keys.get(p.id, {}).get("key")
        if not key:
            continue
        md_path = out_dir / f"{key}.md"
        res = fetcher.fetch(p.model_dump(), prefer_published=fcfg.prefer_published)
        text = render_paper_md(p, key, res, date)
        write_text(md_path, text)
        files.append(md_path)
        row = {
            "paper_id": p.id,
            "citation_key": key,
            "title": p.title,
            "doi": p.doi,
            "access_level": res.access_level,
            "source": res.source,
            "extraction_method": res.extraction.method if res.extraction else None,
            "char_count": res.extraction.char_count if res.extraction else 0,
            "section_count": res.extraction.section_count if res.extraction else 0,
            "pdf_sha256": res.pdf_sha256,
            "attempts": [a.__dict__ for a in res.attempts],
            "quality_notes": res.extraction.notes if res.extraction else [],
        }
        results.append(row)
        if i % 5 == 0:
            ft = sum(1 for r in results if r["access_level"] != "abstract-only")
            ctx.say(f"  {i}/{len(queue)} done — {ft} full-text, {i - ft} abstract-only")
    dump_json(out_dir / "_access_log.json", {"session_id": sc.session_id, "date": date, "papers": results})
    log = render_access_log(sc, results, date)
    write_text(out_dir / "_access_log.md", log)
    files += [out_dir / "_access_log.md", out_dir / "_access_log.json"]
    counts = _counts(results)
    return StepOutput(files=files, summary={"papers": len(results), **counts, "abstract_only": [r["citation_key"] for r in results if r["access_level"] == "abstract-only"]})


def _counts(results: list[dict[str, Any]]) -> dict[str, int]:
    c = {"full-text-pdf": 0, "full-text-html": 0, "partial-text-html": 0, "abstract-only": 0}
    for r in results:
        c[r["access_level"]] = c.get(r["access_level"], 0) + 1
    return c


def render_paper_md(p: ScreenedPaper, key: str, res: FulltextResult, date: str) -> str:
    fm: dict[str, Any] = {"citation_key": key, "title": p.title, "authors": ", ".join(p.authors), "year": p.year or "", "doi": p.doi or "", "source": res.source, "access_level": res.access_level, "retrieved_date": date}
    if p.arxiv_id:
        fm["arxiv_id"] = p.arxiv_id
    if res.extraction:
        fm["extraction_method"] = res.extraction.method
        fm["char_count"] = res.extraction.char_count
        fm["section_count"] = res.extraction.section_count
        if res.pdf_sha256:
            fm["pdf_sha256"] = res.pdf_sha256
        if res.extraction.char_count > 120000:
            fm["long_paper"] = True
    if p.language and p.language != "en":
        fm["language"] = p.language
    head = frontmatter(fm)
    if res.access_level == "abstract-only" or not res.extraction:
        doi_line = f"`https://doi.org/{p.doi}`" if p.doi else "(no DOI)"
        return "\n".join([head, "", f"# {p.title}", "", f"**Authors**: {', '.join(p.authors)}", f"**Year**: {p.year}", f"**DOI**: {p.doi or '—'}", "", f"> **Note**: Full text not available through open access. Abstract included below from screening metadata. Try institutional access: {doi_line}", "", "---", "", "## Abstract", "", p.abstract or "(no abstract available)"])
    body = res.extraction.text
    # drop the extractor's own H1 (the title line we write is canonical)
    body = re.sub(r"^#\s+[^\n]*\n+", "", body, count=1) if body.startswith("# ") else body
    parts = [head, "", f"# {p.title}", ""]
    if res.extraction.notes:
        parts += ["> [!warning] Extraction quality", *(f"> {n}" for n in res.extraction.notes), ""]
    if not re.search(r"^#{1,3}\s+abstract", body, re.I | re.M) and p.abstract:
        parts += ["## Abstract", "", p.abstract, ""]
    parts.append(body)
    return "\n".join(parts)


def render_access_log(sc, results: list[dict[str, Any]], date: str) -> str:
    n = len(results)
    c = _counts(results)
    ft = n - c["abstract-only"]
    pct = lambda k: f"{round(100 * k / n) if n else 0}%"  # noqa: E731
    lines = [
        frontmatter({"session_id": sc.session_id, "topic": sc.topic, "date": date, "step": 5}),
        "",
        "# Full Text Access Log",
        "",
        f"> Topic: {sc.topic}",
        f"> Total papers: {n}",
        f"> Date: {date}",
        "",
        "## Summary",
        "",
        "| Access Level | Count | Percentage |",
        "|------------------------|-------------|-------------------|",
        f"| full-text-pdf | {c['full-text-pdf']} | {pct(c['full-text-pdf'])} |",
        f"| full-text-html | {c['full-text-html']} | {pct(c['full-text-html'])} |",
        f"| partial-text-html | {c['partial-text-html']} | {pct(c['partial-text-html'])} |",
        f"| abstract-only | {c['abstract-only']} | {pct(c['abstract-only'])} |",
        "",
        f"Full-text retrieval rate: **{pct(ft)}** ({ft}/{n} papers)",
        "",
        "## Extraction Quality",
        "",
        "| Citation Key | Method | Chars | Sections | Flag |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        if r["access_level"] != "abstract-only":
            flag = "⚠️ " + "; ".join(r["quality_notes"]) if r["quality_notes"] else "ok"
            lines.append(f"| `{r['citation_key']}` | {r['extraction_method']} | {r['char_count']} | {r['section_count']} | {md_cell(flag)} |")
    lines += ["", "## Successfully Retrieved", "", "| # | Citation Key | Title | Source | Access Level |", "|---|---------------------|-------------|--------------|-------------------|"]
    k = 0
    for r in results:
        if r["access_level"] != "abstract-only":
            k += 1
            lines.append(f"| {k} | `{r['citation_key']}` | {md_cell(truncate(r['title'], 70))} | {md_cell(r['source'])} | {r['access_level']} |")
    lines += ["", "## Abstract Only — Action Required", "", "> These papers could not be accessed through open channels. If you have institutional access, you can retrieve them via the DOI links below.", "", "| # | Citation Key | Title | DOI | Suggested Action |", "|---|---------------------|-------------|-----|--------------------------|"]
    k = 0
    for r in results:
        if r["access_level"] == "abstract-only":
            k += 1
            doi = f"[{r['doi']}](https://doi.org/{r['doi']})" if r["doi"] else "—"
            lines.append(f"| {k} | `{r['citation_key']}` | {md_cell(truncate(r['title'], 70))} | {doi} | Try institutional proxy |")
    lines += ["", "## Access Attempts Detail", ""]
    for r in results:
        lines += [f"### {r['citation_key']}: {truncate(r['title'], 70)}"]
        for a in r["attempts"]:
            lines.append(f"- **{a['level']}**: {a['status']} {a['detail']}".rstrip())
        lines += [f"- **Final status**: {r['access_level']}", ""]
    lines += ["---", "", f"Files: `step5_full_text/` directory with {n} paper files + this access log", "Next step: `/research-sota`"]
    return "\n".join(lines)
