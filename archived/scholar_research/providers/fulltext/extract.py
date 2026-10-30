"""Deterministic text extraction helpers: HTML → markdown-ish, PDF → text, PMC XML → markdown.

No LLM anywhere in this module (plan §4.3).  Every extractor returns an
``Extraction`` with quality metrics computed by code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$", re.M)


@dataclass
class Extraction:
    text: str
    method: str  # arxiv-html | pmc-xml | pdf-pymupdf | pdf-pdftotext | html-generic
    char_count: int = 0
    section_count: int = 0
    sections: list[str] = field(default_factory=list)
    sha256: str | None = None
    notes: list[str] = field(default_factory=list)

    def finalize(self) -> "Extraction":
        self.text = self.text.strip()
        self.char_count = len(self.text)
        self.sections = [m.group(2).strip() for m in HEADING_RE.finditer(self.text)]
        self.section_count = len(self.sections)
        return self


# --------------------------------------------------------------------------- #
# HTML (arXiv HTML / generic)
# --------------------------------------------------------------------------- #
def html_to_markdown(html: str) -> str:
    """Very small HTML→markdown that keeps headings, paragraphs, lists, tables and captions."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:  # pragma: no cover
        return _strip_tags(html)
    soup = BeautifulSoup(html, "lxml") if _has_lxml() else BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg", "button", "form"]):
        tag.decompose()
    # arXiv HTML (ar5iv/LaTeXML) main article; PMC main
    body = soup.find("article") or soup.find("main") or soup.body or soup
    lines: list[str] = []

    def walk(node) -> None:  # noqa: ANN001
        name = getattr(node, "name", None)
        if name is None:
            return
        if name in ("h1", "h2", "h3", "h4"):
            level = int(name[1])
            txt = _clean(node.get_text(" "))
            if txt:
                lines.append("\n" + "#" * min(level, 4) + " " + txt + "\n")
            return
        if name == "p":
            txt = _clean(node.get_text(" "))
            if txt:
                lines.append(txt + "\n")
            return
        if name in ("figcaption", "caption"):
            txt = _clean(node.get_text(" "))
            if txt:
                lines.append(f"> **{txt}**\n")
            return
        if name == "table":
            lines.append(_table_to_md(node) + "\n")
            return
        if name in ("ul", "ol"):
            for i, li in enumerate(node.find_all("li", recursive=False), 1):
                txt = _clean(li.get_text(" "))
                if txt:
                    lines.append(f"- {txt}" if name == "ul" else f"{i}. {txt}")
            lines.append("")
            return
        if name in ("math",):
            alt = node.get("alttext")
            if alt:
                lines.append(f"${alt}$")
            return
        for child in node.children:
            walk(child)

    walk(body)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _has_lxml() -> bool:
    try:
        import lxml  # noqa: F401

        return True
    except ImportError:  # pragma: no cover
        return False


def _clean(s: str) -> str:
    return re.sub(r"[ \t]+", " ", s.replace("\xa0", " ")).strip()


def _table_to_md(table) -> str:  # noqa: ANN001
    rows = []
    for tr in table.find_all("tr"):
        cells = [_clean(td.get_text(" ")).replace("|", "\\|") for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _strip_tags(html: str) -> str:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S | re.I)
    text = re.sub(r"<h([1-4])[^>]*>(.*?)</h\1>", lambda m: "\n" + "#" * int(m.group(1)) + " " + re.sub(r"<[^>]+>", "", m.group(2)) + "\n", text, flags=re.S | re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\n{3,}", "\n\n", _clean_multiline(text))


def _clean_multiline(t: str) -> str:
    return "\n".join(_clean(line) for line in t.splitlines())


# --------------------------------------------------------------------------- #
# PMC XML (efetch db=pmc) → markdown
# --------------------------------------------------------------------------- #
def pmc_xml_to_markdown(xml_text: str) -> str:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_text)
    lines: list[str] = []

    def text_of(el) -> str:  # noqa: ANN001
        return _clean("".join(el.itertext()))

    art = root.find(".//article") or root
    title = art.find(".//front//article-title")
    if title is not None:
        lines.append(f"# {text_of(title)}\n")
    abstract = art.find(".//front//abstract")
    if abstract is not None:
        lines.append("## Abstract\n")
        for p in abstract.iter("p"):
            lines.append(text_of(p) + "\n")

    def walk_sec(sec, level: int) -> None:  # noqa: ANN001
        t = sec.find("title")
        if t is not None and text_of(t):
            lines.append("\n" + "#" * min(level, 4) + " " + text_of(t) + "\n")
        for child in sec:
            tag = child.tag.split("}")[-1]
            if tag == "p":
                lines.append(text_of(child) + "\n")
            elif tag == "sec":
                walk_sec(child, level + 1)
            elif tag in ("fig", "table-wrap"):
                cap = child.find(".//caption")
                lab = child.find("label")
                if cap is not None:
                    lines.append(f"> **{text_of(lab) + ': ' if lab is not None else ''}{text_of(cap)}**\n")
            elif tag == "list":
                for li in child.iter("list-item"):
                    lines.append(f"- {text_of(li)}")
                lines.append("")

    body = art.find(".//body")
    if body is not None:
        for sec in body:
            if sec.tag.split("}")[-1] == "sec":
                walk_sec(sec, 2)
            elif sec.tag.split("}")[-1] == "p":
                lines.append(text_of(sec) + "\n")
    refs = art.findall(".//back//ref-list//ref")
    if refs:
        lines.append("\n## References\n")
        for i, ref in enumerate(refs, 1):
            lines.append(f"{i}. {text_of(ref)}")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# --------------------------------------------------------------------------- #
# PDF → text
# --------------------------------------------------------------------------- #
SECTION_LINE = re.compile(r"^(?:(\d{1,2}(?:\.\d{1,2})*)\.?\s+)?([A-Z][A-Za-z][A-Za-z &\-/:,]{2,80})$")
KNOWN_SECTIONS = {"abstract", "introduction", "background", "related work", "methods", "method", "materials and methods", "results", "discussion", "conclusion", "conclusions", "references", "acknowledgments", "acknowledgements", "experiments", "evaluation", "limitations", "future work", "appendix"}


def pdf_to_text(data: bytes) -> tuple[str, str]:
    """Returns (text, method). Prefers PyMuPDF; falls back to pdftotext CLI."""
    try:
        import fitz  # type: ignore

        doc = fitz.open(stream=data, filetype="pdf")
        pages = [page.get_text("text") for page in doc]
        doc.close()
        return "\n\f".join(pages), "pdf-pymupdf"
    except ImportError:
        pass
    import shutil
    import subprocess
    import tempfile

    exe = shutil.which("pdftotext") or ("/opt/homebrew/bin/pdftotext" if __import__("os").path.exists("/opt/homebrew/bin/pdftotext") else None)
    if not exe:
        raise RuntimeError("neither PyMuPDF nor pdftotext is available (pip install pymupdf)")
    with tempfile.TemporaryDirectory() as td:
        pdf = f"{td}/in.pdf"
        with open(pdf, "wb") as fh:
            fh.write(data)
        out = subprocess.run([exe, "-layout", pdf, "-"], capture_output=True, text=True, timeout=120)
        return out.stdout, "pdf-pdftotext"


def pdf_text_to_markdown(raw: str) -> str:
    """Heuristic clean-up: drop page headers/numbers, mark section headings, join wrapped lines."""
    pages = raw.split("\f")
    # detect repeated header/footer lines
    from collections import Counter

    counter: Counter[str] = Counter()
    for p in pages:
        seen = set()
        for line in p.splitlines()[:3] + p.splitlines()[-3:]:
            s = line.strip()
            if s and s not in seen:
                counter[s] += 1
                seen.add(s)
    repeated = {s for s, c in counter.items() if c >= max(3, len(pages) // 2) and len(s) < 120}
    out: list[str] = []
    for p in pages:
        for line in p.splitlines():
            s = line.strip()
            if not s or s in repeated or re.fullmatch(r"\d{1,4}", s):
                if not s:
                    out.append("")
                continue
            m = SECTION_LINE.match(s)
            if m and (m.group(1) or s.lower() in KNOWN_SECTIONS) and len(s.split()) <= 10:
                level = 2 if not m.group(1) or m.group(1).count(".") == 0 else 3
                out.append("\n" + "#" * level + " " + s + "\n")
            else:
                out.append(s)
    # join wrapped lines inside paragraphs, de-hyphenate
    text = "\n".join(out)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"(?<!\n)\n(?!\n|#|>|\||- |\d+\. )", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
