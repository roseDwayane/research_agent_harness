"""Step 4 — research-export.  **Pure code**: APA 7 list, citation keys, BibTeX.

Formatting rules are the ones research-export/SKILL.md spells out; they are
implemented once here so they are applied identically every run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..schemas.paper import ScreenedPaper, Shortlist
from ..utils import ascii_fold, bibtex_escape, dump_json, frontmatter, last_name, load_json, md_cell, truncate, write_text
from .base import Context, StepOutput

CONF_MARKERS = ("proceedings", "conference", "symposium", "workshop", "icse", "issta", "fse", "ase ", "neurips", "nips", "icml", "iclr", "acl", "emnlp", "cvpr", "iccv", "eccv", "aaai", "ijcai", "kdd", "sigir", "www ", "chi ", "embc", "miccai", "interspeech")
ACRONYM_KEEP = re.compile(r"^[A-Z0-9][A-Z0-9\-\.]+$|[a-z][A-Z]|^[A-Z]{2,}|^[A-Z]$")


@dataclass
class Entry:
    paper: ScreenedPaper
    key: str
    entry_type: str  # article | inproceedings | misc
    apa: str
    bibtex: str
    in_text: str
    todos: list[str]


# --------------------------------------------------------------------------- #
# names
# --------------------------------------------------------------------------- #
def split_name(author: str) -> tuple[str, str]:
    """→ (last, given).  Handles 'Last, First' and 'First M. Last'."""
    a = " ".join(author.replace(" ", " ").split())
    if "," in a:
        last, given = [x.strip() for x in a.split(",", 1)]
        return last, given
    parts = a.split(" ")
    if len(parts) == 1:
        return parts[0], ""
    last = last_name(a)
    given = a[: len(a) - len(last)].strip()
    # keep particles (van, de, von) with the last name
    gp = given.split(" ")
    while len(gp) > 1 and gp[-1].lower() in {"van", "de", "der", "den", "von", "da", "del", "di", "le", "la", "du"}:
        last = gp.pop() + " " + last
    return last, " ".join(gp)


def initials(given: str) -> str:
    if not given:
        return ""
    toks = re.split(r"[\s]+", given.strip())
    out = []
    for t in toks:
        if not t:
            continue
        if "-" in t:
            out.append("-".join(f"{p[0]}." for p in t.split("-") if p))
        else:
            out.append(f"{t[0]}.")
    return " ".join(out)


def apa_author(author: str) -> str:
    last, given = split_name(author)
    if not given:
        return last
    return f"{last}, {initials(given)}"


def apa_authors(authors: list[str]) -> str:
    names = [apa_author(a) for a in authors if a.strip()]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]}, & {names[1]}"
    if len(names) <= 20:
        return ", ".join(names[:-1]) + f", & {names[-1]}"
    return ", ".join(names[:19]) + f", ... {names[-1]}"


def in_text(authors: list[str], year: Any) -> str:
    lasts = [split_name(a)[0] for a in authors if a.strip()]
    y = year if year else "n.d."
    if not lasts:
        return f"(Anonymous, {y})"
    if len(lasts) == 1:
        return f"({lasts[0]}, {y})"
    if len(lasts) == 2:
        return f"({lasts[0]} & {lasts[1]}, {y})"
    return f"({lasts[0]} et al., {y})"


# --------------------------------------------------------------------------- #
# titles
# --------------------------------------------------------------------------- #
def sentence_case(title: str) -> str:
    """APA sentence case: keep first word, first after ':'/'?'/'.', acronyms and mixed-case tokens."""
    t = " ".join(title.split())
    words = t.split(" ")
    out = []
    cap_next = True
    for w in words:
        core = w.strip("()[]\"'“”‘’,.;:!?")
        if not core:
            out.append(w)
            continue
        keep = bool(ACRONYM_KEEP.search(core)) and not (core.isupper() and len(core) > 12)
        if cap_next:
            out.append(w if keep else w[0].upper() + w[1:].lower() if core == w else w[0] + core[0].upper() + core[1:].lower() + w[len(core) + 1 :])
            cap_next = False
        elif keep:
            out.append(w)
        else:
            out.append(w.lower())
        if w.endswith((":", "?", ".", "!", "—")):
            cap_next = True
    return " ".join(out)


def protect_case(title: str) -> str:
    """BibTeX: brace acronyms / mixed-case words so BibTeX styles keep them."""
    out = []
    for w in title.split(" "):
        core = w.strip("()[]\"',.;:!?")
        if core and ACRONYM_KEEP.search(core) and not core.isupper() or (core.isupper() and 2 <= len(core) <= 12):
            out.append(w.replace(core, "{" + core + "}"))
        else:
            out.append(w)
    return " ".join(out)


# --------------------------------------------------------------------------- #
def citation_keys(papers: list[ScreenedPaper]) -> dict[str, str]:
    base: dict[str, str] = {}
    for p in papers:
        lasts = [ascii_fold(split_name(a)[0]).replace(" ", "").replace("'", "") for a in p.authors if a.strip()]
        lasts = [re.sub(r"[^A-Za-z\-]", "", x) for x in lasts]
        lasts = [x for x in lasts if x]
        y = str(p.year) if p.year else "nd"
        if not lasts:
            key = f"Anon{y}"
        elif len(lasts) == 1:
            key = f"{lasts[0]}{y}"
        elif len(lasts) == 2:
            key = f"{lasts[0]}{lasts[1]}{y}"
        else:
            key = f"{lasts[0]}EtAl{y}"
        base[p.id] = _pascal(key)
    groups: dict[str, list[ScreenedPaper]] = {}
    for p in papers:
        groups.setdefault(base[p.id], []).append(p)
    final: dict[str, str] = {}
    for key, group in groups.items():
        if len(group) == 1:
            final[group[0].id] = key
        else:
            for i, p in enumerate(sorted(group, key=lambda x: (x.title.lower(), x.id))):
                final[p.id] = f"{key}{chr(ord('a') + i)}"
    return final


def _pascal(key: str) -> str:
    parts = re.split(r"[-\s]+", key)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


# --------------------------------------------------------------------------- #
def entry_type(p: ScreenedPaper) -> str:
    j = (p.journal or "").lower()
    if p.venue_type == "conference" or any(m in j for m in CONF_MARKERS):
        return "inproceedings"
    if p.arxiv_id and (not p.journal or "arxiv" in j or p.venue_type == "preprint") and not p.doi:
        return "misc"
    if p.arxiv_id and not p.journal:
        return "misc"
    return "article"


def format_apa(p: ScreenedPaper, et: str) -> str:
    au = apa_authors(p.authors) or "Anonymous"
    y = p.year if p.year else "n.d."
    title = sentence_case(p.title)
    link = f"https://doi.org/{p.doi}" if p.doi else (f"https://arxiv.org/abs/{p.arxiv_id}" if p.arxiv_id else (p.url or ""))
    if et == "misc":
        body = f"{au} ({y}). {title}. *arXiv preprint*."
    elif et == "inproceedings":
        pages = f" (pp. {p.pages.replace('-', '–')})" if p.pages else ""
        body = f"{au} ({y}). {title}. In *{p.journal}*{pages}."
    else:
        vol = f", *{p.volume}*" if p.volume else ""
        iss = f"({p.issue})" if p.issue and p.volume else ""
        pages = f", {p.pages.replace('-', '–')}" if p.pages else ""
        body = f"{au} ({y}). {title}. *{p.journal or 'Unpublished manuscript'}*{vol}{iss}{pages}."
    return f"{body} {link}".strip()


def format_bibtex(p: ScreenedPaper, key: str, et: str, todos: list[str]) -> str:
    authors = " and ".join(f"{split_name(a)[0]}, {split_name(a)[1]}".rstrip(", ") if split_name(a)[1] else "{" + split_name(a)[0] + "}" for a in p.authors if a.strip()) or "{Anonymous}"
    fields: list[tuple[str, str]] = [("author", authors), ("title", bibtex_escape(protect_case(p.title)))]
    if et == "article":
        fields.append(("journal", bibtex_escape(p.journal or "")))
    elif et == "inproceedings":
        fields.append(("booktitle", bibtex_escape(p.journal or "")))
    fields.append(("year", str(p.year) if p.year else ""))
    if et == "article":
        if p.volume:
            fields.append(("volume", p.volume))
        if p.issue:
            fields.append(("number", p.issue))
    if et in ("article", "inproceedings") and p.pages:
        fields.append(("pages", p.pages.replace("–", "--").replace("-", "--").replace("----", "--")))
    if et == "misc":
        fields += [("eprint", p.arxiv_id or ""), ("archiveprefix", "arXiv")]
        if p.arxiv_primary_class:
            fields.append(("primaryclass", p.arxiv_primary_class))
        fields.append(("url", f"https://arxiv.org/abs/{p.arxiv_id}"))
    else:
        if p.doi:
            fields += [("doi", p.doi), ("url", f"https://doi.org/{p.doi}")]
        elif p.url:
            fields.append(("url", p.url))
        if p.arxiv_id:
            fields.append(("eprint", p.arxiv_id))
    fields = [(k, v) for k, v in fields if v]
    width = max(len(k) for k, _ in fields)
    body = ",\n".join(f"  {k.ljust(width)} = {{{v}}}" for k, v in fields)
    comment = "".join(f"\n  % TODO: {t}" for t in todos)
    return f"@{et}{{{key},\n{body}{comment}\n}}"


def build_entries(papers: list[ScreenedPaper]) -> tuple[list[Entry], list[str]]:
    keys = citation_keys(papers)
    entries, skipped = [], []
    for p in papers:
        todos = []
        if not p.authors:
            skipped.append(f"{p.id}: no authors — skipped")
            continue
        if not p.year:
            skipped.append(f"{p.id}: no year — skipped")
            continue
        if not p.title:
            skipped.append(f"{p.id}: no title — skipped")
            continue
        if any(len(a.split()) == 1 and "," not in a for a in p.authors):
            todos.append("verify author name (single-token author)")
        if not p.doi and not p.url and not p.arxiv_id:
            todos.append("missing DOI/URL — verify manually")
        et = entry_type(p)
        entries.append(Entry(paper=p, key=keys[p.id], entry_type=et, apa=format_apa(p, et), bibtex=format_bibtex(p, keys[p.id], et, todos), in_text=in_text(p.authors, p.year), todos=todos))
    return entries, skipped


def validate(entries: list[Entry]) -> list[str]:
    problems = []
    keys = [e.key for e in entries]
    if len(set(keys)) != len(keys):
        problems.append("duplicate citation keys")
    suffixed = {}
    for k in keys:
        m = re.match(r"^(.*\d{4})([a-z])$", k)
        if m:
            suffixed.setdefault(m.group(1), []).append(k)
    for base, ks in suffixed.items():
        if len(ks) < 2:
            problems.append(f"lone suffixed key {ks[0]}")
    for e in entries:
        n = len([a for a in e.paper.authors if a.strip()])
        if n >= 2 and e.apa.count("&") != 1:
            problems.append(f"{e.key}: ampersand count {e.apa.count('&')} for {n} authors")
        if "doi:" in e.apa or re.search(r"\b10\.\d{4,}/\S+", e.apa) and "https://doi.org/" not in e.apa:
            problems.append(f"{e.key}: DOI not in https://doi.org/ form")
    return problems


# --------------------------------------------------------------------------- #
def run(ctx: Context) -> StepOutput:
    s = ctx.session
    sc = s.load_config()
    sl = Shortlist.model_validate(load_json(s.path("step3_shortlist.json")))
    date = ctx.date(4)
    # dedup by DOI/title after manual inclusion (edge case in SKILL)
    seen: set[str] = set()
    papers: list[ScreenedPaper] = []
    for p in sl.papers:
        k = p.doi or p.title.lower()
        if k in seen:
            continue
        seen.add(k)
        papers.append(p)
    entries, skipped = build_entries(papers)
    problems = validate(entries)
    if problems:
        raise RuntimeError("export cross-validation failed: " + "; ".join(problems))
    n = len(entries)
    apa_sorted = sorted(entries, key=lambda e: (ascii_fold(split_name(e.paper.authors[0])[0]).lower(), e.paper.year or 0, e.paper.title.lower()))
    fm = {"session_id": sc.session_id, "topic": sc.topic, "date": date, "step": 4}
    apa_md = "\n".join([frontmatter({**fm, "total_references": n}), "", "# References (APA 7th Edition) / 參考文獻", "", f"> Topic / 研究主題: {sc.topic}", f"> Total references / 參考文獻總數: {n}", f"> Generated / 產生日期: {date}", "", "---", ""] + [e.apa + "\n" for e in apa_sorted] + ["---", "", "Files / 檔案: `step4_references_apa.md`, `step4_citation_keys.md`, `step4_references.bib`", "Next step / 下一步: `/research-fulltext`"])
    key_rows = [f"| `{e.key}` | {e.in_text} | {md_cell(truncate(e.paper.title, 60))} | {e.paper.year} | {e.paper.screening.tier or '—'} |" for e in sorted(entries, key=lambda e: (-e.paper.screening.composite, e.paper.id))]
    keys_md = "\n".join([frontmatter(fm), "", "# Citation Keys / 引用鍵值對照表", "", f"> Topic / 研究主題: {sc.topic}", f"> Total / 總數: {n} papers", "", "| Citation Key / 引用鍵 | Citation / 引用 | Short Title / 簡稱 | Year / 年份 | Tier |", "|----------------------|----------------|-------------------|------------|------|"] + key_rows + ["", "---", "", "## Usage / 使用方式", "", "In downstream steps, cite papers using the citation key:", f"- In SOTA review: `{entries[0].in_text if entries else '(Author, Year)'}` or `Author (Year)`", f"- In LaTeX: `\\cite{{{entries[0].key if entries else 'AuthorYear'}}}`", "", "---", "", "Files / 檔案: `step4_references_apa.md`, `step4_citation_keys.md`, `step4_references.bib`", "Next step / 下一步: `/research-fulltext`"])
    bib = "\n".join([f"% Auto-generated BibTeX — Research Agent Pipeline Step 4", f"% Session: {sc.session_id} | Topic: {sc.topic}", f"% Generated: {date}", f"% Total entries: {n}", ""] + [e.bibtex + "\n" for e in apa_sorted])
    write_text(s.path("step4_references_apa.md"), apa_md)
    write_text(s.path("step4_citation_keys.md"), keys_md)
    write_text(s.path("step4_references.bib"), bib)
    # machine-readable key map for downstream steps (avoids re-parsing markdown)
    dump_json(s.path("step4_citation_keys.json"), {e.paper.id: {"key": e.key, "in_text": e.in_text, "entry_type": e.entry_type} for e in entries})
    types = {t: sum(1 for e in entries if e.entry_type == t) for t in ("article", "inproceedings", "misc")}
    return StepOutput(files=[s.path("step4_references_apa.md"), s.path("step4_citation_keys.md"), s.path("step4_references.bib"), s.path("step4_citation_keys.json")], notes=skipped, summary={"references": n, "types": types, "skipped": skipped, "sample": [e.apa for e in apa_sorted[:3]]})
