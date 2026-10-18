#!/usr/bin/env python3
"""Shared parsing helpers for the deterministic Step 6 / Step 7 checks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


BIB_KEY_RE = re.compile(r"@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,")
# Source keys such as YamadaEtAl2025, VermaLandrum2026, DArcyEtAl2024, LiEtAl2025a.
# At least one lowercase letter is required so venue tokens like ICLR2025 are ignored.
KEY_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Z][A-Za-z]*[a-z][A-Za-z]*(?:19|20)\d{2}[a-z]?)(?![A-Za-z0-9])"
)
TEX_CITE_RE = re.compile(r"\\cite\w*\s*\{([^}]+)\}")
PAREN_GROUP_RE = re.compile(r"[（(]([^()（）]*?(?:19|20)\d{2}[a-z]?)\s*[)）]")
# One author-year item inside a parenthetical group; the comma is required (APA style),
# which keeps "(ICLR 2025)" or "(GPT-4 2023)" from being read as citations.
AUTHOR_YEAR_ITEM_RE = re.compile(
    r"(?P<first>[A-Z][A-Za-z'’\-]*[a-z][A-Za-z'’\-]*)"
    r"(?:\s+et\s+al\.?|\s*(?:&|and)\s*(?P<second>[A-Z][A-Za-z'’\-]*[a-z][A-Za-z'’\-]*))?"
    r"\s*,\s*(?P<year>(?:19|20)\d{2}[a-z]?)\s*$"
)
TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Citation:
    key: str
    raw: str
    line: int
    form: str  # "key" | "author_year" | "tex"


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def load_manifest(path: Path) -> tuple[dict, Path]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    project = (path.parent / manifest["project_dir"]).resolve()
    return manifest, project


def parse_bib_keys(text: str) -> set[str]:
    return set(BIB_KEY_RE.findall(text))


def split_frontmatter(text: str) -> tuple[dict[str, str], list[str], int]:
    """Return (frontmatter fields, body lines, number of lines consumed by frontmatter)."""
    lines = text.splitlines()
    meta: dict[str, str] = {}
    if not lines or lines[0].strip() != "---":
        return meta, lines, 0
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            for raw in lines[1:index]:
                if ":" in raw:
                    name, value = raw.split(":", 1)
                    meta[name.strip()] = value.strip().strip('"').strip("'")
            return meta, lines[index + 1:], index + 1
    return meta, lines, 0


def load_access_levels(full_text_dir: Path) -> dict[str, str | None]:
    """Map citation key -> frontmatter access_level for every step5 Markdown file."""
    levels: dict[str, str | None] = {}
    for path in sorted(full_text_dir.glob("*.md")):
        if path.name.startswith("_"):  # e.g. _access_log.md
            continue
        meta, _, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        levels[meta.get("citation_key") or path.stem] = meta.get("access_level")
    return levels


def as_level_list(value) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------

def normalize_author_year(first: str, second: str | None, et_al: bool, year: str) -> str:
    clean = lambda name: re.sub(r"['’\-\s]", "", name)
    if et_al:
        return f"{clean(first)}EtAl{year}"
    if second:
        return f"{clean(first)}{clean(second)}{year}"
    return f"{clean(first)}{year}"


def extract_citations(line: str, line_number: int = 0) -> list[Citation]:
    """Extract bare keys, \\cite{} keys and normalized (Author et al., Year) citations."""
    found: list[Citation] = []
    for group in TEX_CITE_RE.findall(line):
        for key in group.split(","):
            if key.strip():
                found.append(Citation(key.strip(), key.strip(), line_number, "tex"))
    for match in KEY_TOKEN_RE.finditer(line):
        found.append(Citation(match.group(1), match.group(1), line_number, "key"))
    for group in PAREN_GROUP_RE.findall(line):
        for item in re.split(r"[;；]", group):
            match = AUTHOR_YEAR_ITEM_RE.search(item.strip())
            if not match:
                continue
            et_al = bool(re.search(r"\set\s+al", match.group(0)))
            key = normalize_author_year(match.group("first"), match.group("second"), et_al, match.group("year"))
            found.append(Citation(key, match.group(0).strip(), line_number, "author_year"))
    return found


def cited_keys(lines: list[str]) -> set[str]:
    keys: set[str] = set()
    for line in lines:
        keys.update(c.key for c in extract_citations(line))
    return keys


# ---------------------------------------------------------------------------
# Markdown structure
# ---------------------------------------------------------------------------

def is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1


def is_table_separator(line: str) -> bool:
    return bool(TABLE_SEPARATOR_RE.match(line.strip()))


def is_heading(line: str) -> bool:
    return bool(HEADING_RE.match(line.strip()))


def is_papers_inventory(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("**Papers (") or stripped.startswith("**Papers:")


def table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


@dataclass
class Section:
    title: str
    level: int
    start: int  # index of heading line in body
    end: int  # exclusive

    def lines(self, body: list[str]) -> list[str]:
        return body[self.start + 1:self.end]


def sections(body: list[str], level: int, start: int = 0, end: int | None = None) -> list[Section]:
    """Split body[start:end] into headings of exactly ``level``; each ends at the next heading of <= level."""
    end = len(body) if end is None else end
    heads = []
    for index in range(start, end):
        match = HEADING_RE.match(body[index].strip())
        if match and len(match.group(1)) <= level:
            heads.append((index, len(match.group(1)), match.group(2).strip()))
    result = []
    for position, (index, head_level, title) in enumerate(heads):
        if head_level != level:
            continue
        stop = next((i for i, lv, _ in heads[position + 1:] if lv <= level), end)
        result.append(Section(title, level, index, stop))
    return result


def content_lines(lines: list[str]) -> list[str]:
    """Non-blank lines that are not headings, table separators, rules or inventories."""
    kept = []
    for line in lines:
        stripped = line.strip()
        if not stripped or is_heading(stripped) or is_table_separator(stripped):
            continue
        if stripped.startswith("---") or stripped.startswith("```") or is_papers_inventory(stripped):
            continue
        kept.append(line)
    return kept


def tables(lines: list[str]) -> list[dict]:
    """Return each Markdown table as {"header": [...], "rows": [[...], ...]}."""
    found = []
    index = 0
    while index < len(lines):
        if is_table_row(lines[index]) and index + 1 < len(lines) and is_table_separator(lines[index + 1]):
            header = table_cells(lines[index])
            rows = []
            index += 2
            while index < len(lines) and is_table_row(lines[index]):
                rows.append(table_cells(lines[index]))
                index += 1
            found.append({"header": header, "rows": rows})
        else:
            index += 1
    return found
