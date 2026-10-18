#!/usr/bin/env python3
"""Numeric attestation for Step 6 (and Step 7 evidence), spec L2 §4.4.

Every citable claim (a sentence or Key Results row that cites >=1 legal key) containing a
number must have that number, literally or after rounding, in step5_full_text/{key}.md of
one of the keys that claim cites. Only full-text sources can attest numbers.
numeric_attestation = attested claims / numeric citable claims; passes at >= threshold.
"""

from __future__ import annotations

import argparse
import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from step6_common import (
    PAREN_GROUP_RE,
    TEX_CITE_RE,
    KEY_TOKEN_RE,
    extract_citations,
    is_heading,
    is_papers_inventory,
    is_table_row,
    is_table_separator,
    load_access_levels,
    load_manifest,
    parse_bib_keys,
    sections,
    split_frontmatter,
    table_cells,
)


DEFAULT_SUPPORT_LEVELS = ["full-text-pdf", "full-text-html", "partial-text-html"]
EXCLUDED_REVIEW_SECTIONS = re.compile(r"^(?:Paper[–-]Theme\s+Mapping|Limitations\b)", re.IGNORECASE)
# Claim numbers: not glued to a preceding letter/digit/dot/hyphen (v2, GPT-4, GPT-5.4, o1)
# and not followed by a letter (142k, 3D).
CLAIM_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![A-Za-z0-9_])(\s*%|\s*percent)?"
)
SOURCE_NUMBER_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\d])")
ABBREVIATIONS = ("et al.", "e.g.", "i.e.", "vs.", "cf.", "Fig.", "approx.", "No.", "Eq.")
EN_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[“\"~<>≥≤+\-−])")


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

def claim_numbers(text: str) -> list[dict]:
    """Numbers worth attesting: decimals, percentages, or integers >= 10 that are not years."""
    numbers = []
    for match in CLAIM_NUMBER_RE.finditer(text):
        integer, decimals, percent = match.group(1), match.group(2), match.group(3)
        has_comma = "," in integer
        value = Decimal(integer.replace(",", "") + (f".{decimals}" if decimals else ""))
        if not decimals and not percent:
            if value < 10:
                continue
            if not has_comma and 1900 <= value <= 2099:
                continue
        numbers.append({
            "text": match.group(0).strip(),
            "value": value,
            "decimals": len(decimals) if decimals else 0,
        })
    return numbers


def source_numbers(text: str) -> set[Decimal]:
    values = set()
    for match in SOURCE_NUMBER_RE.finditer(text):
        integer, decimals = match.group(1), match.group(2)
        values.add(Decimal(integer.replace(",", "") + (f".{decimals}" if decimals else "")))
    return values


def attested(number: dict, values: set[Decimal]) -> bool:
    """Literal value match, or a more precise source value that rounds to the claimed value."""
    target = number["value"]
    if target in values:
        return True
    quantum = Decimal(1).scaleb(-number["decimals"])
    for value in values:
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > number["decimals"]:
            if value.quantize(quantum, rounding=ROUND_HALF_UP) == target:
                return True
    return False


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

def clean_markup(text: str) -> str:
    return text.replace("**", "").replace("*", "").replace("`", "").replace("\\$", "$")


def strip_citations(text: str) -> str:
    """Remove citation keys so their years never count as claim numbers."""
    text = TEX_CITE_RE.sub(" ", text)
    text = PAREN_GROUP_RE.sub(lambda m: " " if extract_citations(m.group(0)) else m.group(0), text)
    return KEY_TOKEN_RE.sub(" ", text)


def split_sentences(line: str) -> list[str]:
    protected = line
    for abbreviation in ABBREVIATIONS:
        protected = protected.replace(abbreviation, abbreviation.replace(".", "\x00"))
    parts = EN_SPLIT_RE.split(protected)
    return [part.replace("\x00", ".").strip() for part in parts if part.strip()]


def make_claim(text: str, line: int, keys: set[str], kind: str) -> dict | None:
    numbers = claim_numbers(strip_citations(clean_markup(text)))
    if not numbers:
        return None
    return {"line": line, "kind": kind, "keys": sorted(keys), "text": text.strip()[:400], "numbers": numbers}


def review_claims(body: list[str], offset: int, legal: set[str]) -> tuple[list[dict], int]:
    """Citable numeric claims from Step 6: sentences in prose, rows in tables."""
    excluded = set()
    for section in sections(body, 2):
        if EXCLUDED_REVIEW_SECTIONS.match(section.title):
            excluded.update(range(section.start, section.end))
    claims, uncited = [], 0
    for index, line in enumerate(body):
        stripped = line.strip()
        if index in excluded or not stripped or is_heading(stripped) or is_papers_inventory(stripped):
            continue
        if is_table_separator(stripped):
            continue
        number = index + offset + 1
        if is_table_row(stripped):
            if index + 1 < len(body) and is_table_separator(body[index + 1]):
                continue  # header row
            units = [(" | ".join(table_cells(stripped)), "table_row")]
        else:
            units = [(sentence, "sentence") for sentence in split_sentences(stripped)]
        for text, kind in units:
            keys = {c.key for c in extract_citations(text)} & legal
            if not keys:
                uncited += bool(claim_numbers(strip_citations(clean_markup(text))))
                continue
            claim = make_claim(text, number, keys, kind)
            if claim:
                claims.append(claim)
    return claims, uncited


def gap_claims(body: list[str], offset: int, legal: set[str]) -> tuple[list[dict], int]:
    """Citable numeric claims from Step 7; lines of an evidence bullet inherit its label keys."""
    claims, uncited = [], 0
    label_keys: set[str] = set()
    for index, line in enumerate(body):
        stripped = line.strip()
        if not stripped:
            continue
        if is_heading(stripped) or (not line.startswith((" ", "\t", "- "))):
            label_keys = set()
        if line.startswith("- "):
            label = " ".join(re.findall(r"\*\*(.+?)\*\*", line.split(":", 1)[0] + ":"))
            label_keys = {c.key for c in extract_citations(label)} & legal
        if is_heading(stripped) or is_table_row(stripped) or is_table_separator(stripped):
            continue
        for sentence in split_sentences(stripped):
            keys = ({c.key for c in extract_citations(sentence)} & legal) | label_keys
            if not keys:
                uncited += bool(claim_numbers(strip_citations(clean_markup(sentence))))
                continue
            claim = make_claim(sentence, index + offset + 1, keys, "evidence" if label_keys else "sentence")
            if claim:
                claims.append(claim)
    return claims, uncited


def attest_claims(claims, uncited, access, full_text_dir, support_levels, threshold) -> dict:
    cache: dict[str, set[Decimal]] = {}

    def values_for(key: str) -> set[Decimal]:
        if key not in cache:
            path = full_text_dir / f"{key}.md"
            cache[key] = source_numbers(path.read_text(encoding="utf-8")) if path.exists() else set()
        return cache[key]

    passed = 0
    number_total = number_passed = 0
    for claim in claims:
        support = [key for key in claim["keys"] if access.get(key) in support_levels]
        claim["support_keys"] = support
        claim["unsupported_keys"] = [key for key in claim["keys"] if key not in support]
        for number in claim["numbers"]:
            number["found_in"] = [key for key in support if attested(number, values_for(key))]
            number["attested"] = bool(number["found_in"])
            number_total += 1
            number_passed += number["attested"]
            number["value"] = str(number["value"])
        claim["pass"] = all(number["attested"] for number in claim["numbers"])
        if not support:
            claim["reason"] = "no full-text source among cited keys (abstract-only/condensed cannot attest numbers)"
        elif not claim["pass"]:
            claim["reason"] = "number not found in the cited keys' full text"
        passed += claim["pass"]

    rate = passed / len(claims) if claims else 1.0
    return {
        "numeric_citable_claims": len(claims),
        "attested_claims": passed,
        "numeric_attestation": round(rate, 4),
        "threshold": threshold,
        "pass": rate >= threshold,
        "numbers_total": number_total,
        "numbers_attested": number_passed,
        "numeric_sentences_without_citation": uncited,
        "failures": [claim for claim in claims if not claim["pass"]],
        "claims": claims,
    }


def line_samples(manifest: dict, claims: list[dict]) -> list[dict]:
    """Regression check for the hand-picked LINE samples kept in the manifest."""
    samples = []
    for sample in manifest.get("numeric_claims", []):
        patterns = [re.compile(p, re.IGNORECASE) for p in sample["review_patterns"]]
        hits = [
            claim for claim in claims
            if sample["citation_key"] in claim["keys"] and any(p.search(claim["text"]) for p in patterns)
        ]
        samples.append({
            "id": sample["id"],
            "label": sample["label"],
            "citation_key": sample["citation_key"],
            "matched_claims": [{"line": c["line"], "pass": c["pass"]} for c in hits],
            "pass": bool(hits) and all(c["pass"] for c in hits),
        })
    return samples


def main() -> int:
    parser = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    parser.add_argument("--manifest", default=str(here / "step6_source_manifest.json"))
    parser.add_argument("--output", default=str(here / "step6_numeric_results.json"))
    args = parser.parse_args()

    manifest, project = load_manifest(Path(args.manifest).resolve())
    review_path = project / manifest["review"]
    full_text_dir = project / manifest["full_text_dir"]
    step7_path = project / manifest.get("gap_analysis", "step7_gap_analysis.md")
    legal = parse_bib_keys((project / manifest["bibliography"]).read_text(encoding="utf-8"))
    access = load_access_levels(full_text_dir)
    support_levels = manifest.get("numeric_support_levels", DEFAULT_SUPPORT_LEVELS)
    threshold = float(manifest.get("numeric_attestation_threshold", 0.9))

    _, body, offset = split_frontmatter(review_path.read_text(encoding="utf-8"))
    claims6, uncited6 = review_claims(body, offset, legal)
    step6 = {"path": str(review_path),
             **attest_claims(claims6, uncited6, access, full_text_dir, support_levels, threshold)}

    if step7_path.exists():
        _, body7, offset7 = split_frontmatter(step7_path.read_text(encoding="utf-8"))
        claims7, uncited7 = gap_claims(body7, offset7, legal)
        step7 = {"path": str(step7_path),
                 **attest_claims(claims7, uncited7, access, full_text_dir, support_levels, threshold)}
    else:
        step7 = {"status": "skipped", "reason": f"missing {step7_path}", "pass": True}

    result = {
        "support_levels": support_levels,
        "rules": "Search is limited to the keys the claim itself cites. Integers < 10 and bare years "
                 "(1900–2099) are ignored; signs are ignored; a claim passes only if all its numbers attest.",
        "step6": step6,
        "step7": step7,
        "line_samples": line_samples(manifest, claims6),
    }
    result["overall_pass"] = step6["pass"] and step7["pass"]
    summary = {
        "step6_numeric_attestation": step6["numeric_attestation"],
        "step6_claims": f"{step6['attested_claims']}/{step6['numeric_citable_claims']}",
        "step7_numeric_attestation": step7.get("numeric_attestation"),
        "step7_claims": f"{step7.get('attested_claims')}/{step7.get('numeric_citable_claims')}",
        "line_samples": {s["id"]: s["pass"] for s in result["line_samples"]},
        "overall_pass": result["overall_pass"],
    }
    result["summary"] = summary
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
