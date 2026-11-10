#!/usr/bin/env python3
"""Numeric attestation for Step 6 (and Step 7 evidence) in the fusion-block architecture.

    python evaluation/step06_sota/check_numeric_claims.py --session <research folder> [--output numeric.json]

A claim is a sentence or a table row that cites at least one id (collision, exp_id / unit id, Point, Line, Plane, bare
paper key) and contains a number worth checking: a decimal, a percentage, or an integer >= 10 that is not a year. Ids are
stripped first, so the digits in `X0019` or `galt2019#E1` never count.

Each id resolves to the papers it rests on (step6_world.World.papers_of): an exp_id or unit id to its paper, a collision
to the papers on its sides, a Point or Line to its source papers, a Plane to its member papers. The number must appear,
literally or after rounding, in the SOURCE TEXT of one of those papers:

    full-text    step5_full_text/{key}.md          (only when the paper was read from a full text)
    abstract     the abstract in step2_raw_papers.json / step2b_snowball_papers.json

A number that appears only in the decon record (knowledge/decon/{key}.json, a model's reading of the source) is reported
as `extraction-only`: it is not attested - that is exactly the failure this check exists to find. A claim whose cited
papers have no source text at all (title-only records) cannot be attested.

numeric_attestation = attested claims / numeric claims; passes at >= 0.9. Everything is reported by tier, so an
abstract-only run is not read as a full-text one. Exit 1 when it does not pass.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from step6_common import (
    is_heading,
    is_table_row,
    is_table_separator,
    sections,
    split_frontmatter,
    table_cells,
)
from step6_cites import CiteFinder
from step6_world import TBD, World, ids_in, load_world, strip_ids

THRESHOLD = 0.9
EXCLUDED_SECTIONS = re.compile(r"^(?:Methodology\s+Legend|Paper[–-]Theme\s+Mapping)\b", re.IGNORECASE)
# Claim numbers: not glued to a preceding letter/digit/dot/hyphen (v2, GPT-4, o1) and not followed by a letter (142k).
CLAIM_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![A-Za-z0-9_])(\s*%|\s*percent)?"
)
SOURCE_NUMBER_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\d])")
ABBREVIATIONS = ("et al.", "e.g.", "i.e.", "vs.", "cf.", "Fig.", "approx.", "No.", "Eq.")
EN_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9(\[“\"~<>≥≤+\-−])")


# ------------------------------------------------------------------------------------------------ numbers
def claim_numbers(text: str) -> list[dict]:
    """Numbers worth attesting: decimals, percentages, or integers >= 10 that are not years."""
    numbers = []
    for match in CLAIM_NUMBER_RE.finditer(text):
        integer, decimals, percent = match.group(1), match.group(2), match.group(3)
        value = Decimal(integer.replace(",", "") + (f".{decimals}" if decimals else ""))
        if not decimals and not percent:
            if value < 10:
                continue
            if "," not in integer and 1900 <= value <= 2099:
                continue
        numbers.append({"text": match.group(0).strip(), "value": value, "decimals": len(decimals) if decimals else 0})
    return numbers


_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen".split())}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def _alt(words) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


NUMBER_WORD_RE = re.compile(
    r"(?<![A-Za-z])(?:(" + _alt(_TENS) + r")(?:[-\s](" + _alt(list(_UNITS)[1:10]) + r"))?|(" + _alt(_UNITS) + r"))(?![A-Za-z])",
    re.IGNORECASE)


def number_words(text: str) -> set[Decimal]:
    """'Fourteen' -> 14, 'twenty-one' -> 21: sources spell out small counts, claims write them as digits."""
    values = set()
    for m in NUMBER_WORD_RE.finditer(text):
        tens, unit, single = (g.lower() if g else None for g in m.groups())
        if tens:
            values.add(Decimal(_TENS[tens] + (_UNITS[unit] if unit else 0)))
        elif single:
            values.add(Decimal(_UNITS[single]))
    return values


def source_numbers(text: str) -> set[Decimal]:
    values = number_words(text)
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


# ------------------------------------------------------------------------------------------------ claims
def clean_markup(text: str) -> str:
    return text.replace("**", "").replace("*", "").replace("`", "").replace("\\$", "$")


def split_sentences(line: str) -> list[str]:
    protected = line
    for abbreviation in ABBREVIATIONS:
        protected = protected.replace(abbreviation, abbreviation.replace(".", "\x00"))
    return [p.replace("\x00", ".").strip() for p in EN_SPLIT_RE.split(protected) if p.strip()]


def numbers_of(text: str) -> list[dict]:
    return claim_numbers(strip_ids(clean_markup(text)).replace(TBD, " "))


def make_claim(text: str, line: int, ids: list[str], kind: str, w: World) -> dict | None:
    numbers = numbers_of(text)
    if not numbers:
        return None
    papers = sorted(set().union(*(w.papers_of(i) for i in ids)) if ids else set())
    return {"line": line, "kind": kind, "ids": ids, "papers": papers, "text": text.strip()[:400], "numbers": numbers}


def review_claims(body: list[str], offset: int, w: World, skip_computed: bool = False,
                  finder: CiteFinder | None = None) -> tuple[list[dict], list[dict]]:
    """Cited numeric claims (sentences in prose, rows in tables) and numeric sentences that cite nothing."""
    excluded: set[int] = set()
    for section in sections(body, 2):
        if EXCLUDED_SECTIONS.match(section.title):
            excluded.update(range(section.start, section.end))
    claims, uncited = [], []
    for index, line in enumerate(body):
        stripped = line.strip()
        if index in excluded or not stripped or is_heading(stripped) or is_table_separator(stripped):
            continue
        number = index + offset + 1
        if skip_computed and (is_table_row(stripped) or re.match(r"^-\s*\*\*(Priority score|Novelty basis)", stripped)):
            continue  # Step 7's ranking table and score lines are computed by the harness, not read from a paper
        if is_table_row(stripped):
            if index + 1 < len(body) and is_table_separator(body[index + 1]):
                continue  # header row
            units = [(" | ".join(table_cells(stripped)), "table_row")]
        else:
            units = [(s, "sentence") for s in split_sentences(stripped)]
        for text, kind in units:
            ids = sorted({i for i in finder.ids(text) if w.kind(i)} if finder else {i for i, _ in ids_in(text, w) if w.kind(i)})
            claim = make_claim(text, number, ids, kind, w)
            if claim is None:
                continue
            if ids and claim["papers"]:
                claims.append(claim)
            else:
                uncited.append({"line": number, "text": text.strip()[:200]})
    return claims, uncited


# ------------------------------------------------------------------------------------------------ attestation
def decon_text(w: World, key: str) -> str:
    rec = w.decon.get(key)
    return json.dumps(rec, ensure_ascii=False) if rec else ""


def attest_claims(claims: list[dict], uncited: list[dict], w: World) -> dict:
    cache: dict[tuple[str, str], set[Decimal]] = {}

    def values(key: str, tier: str) -> set[Decimal]:
        if (key, tier) not in cache:
            text = {"full-text": w.fulltext.get(key, "") if w.paper_basis(key) == "full-text" else "",
                    "abstract": w.abstracts.get(key, ""),
                    "extraction": decon_text(w, key)}[tier]
            cache[(key, tier)] = source_numbers(text)
        return cache[(key, tier)]

    passed = number_total = number_passed = 0
    tiers = {"full-text": 0, "abstract": 0, "extraction-only": 0, "not-found": 0}
    for claim in claims:
        claim["papers_with_source_text"] = [k for k in claim["papers"] if k in w.abstracts or
                                            (k in w.fulltext and w.paper_basis(k) == "full-text")]
        for number in claim["numbers"]:
            found = None
            for tier in ("full-text", "abstract"):
                hit = [k for k in claim["papers"] if attested(number, values(k, tier))]
                if hit:
                    found = (tier, hit)
                    break
            if found:
                number["tier"], number["found_in"] = found
            elif any(attested(number, values(k, "extraction")) for k in claim["papers"]):
                number["tier"], number["found_in"] = "extraction-only", []
            else:
                number["tier"], number["found_in"] = "not-found", []
            number["attested"] = number["tier"] in ("full-text", "abstract")
            tiers[number["tier"]] += 1
            number_total += 1
            number_passed += number["attested"]
            number["value"] = str(number["value"])
        claim["pass"] = all(n["attested"] for n in claim["numbers"])
        if not claim["pass"]:
            claim["reason"] = ("no source text for the cited papers (title-only record)"
                               if not claim["papers_with_source_text"]
                               else "number not in the cited papers' source text"
                               + (" (only in the decon extraction)" if any(n["tier"] == "extraction-only"
                                                                           for n in claim["numbers"]) else ""))
        passed += claim["pass"]

    rate = passed / len(claims) if claims else 1.0
    return {
        "numeric_claims": len(claims),
        "attested_claims": passed,
        "numeric_attestation": round(rate, 4),
        "threshold": THRESHOLD,
        "pass": rate >= THRESHOLD,
        "numbers_total": number_total,
        "numbers_attested": number_passed,
        "numbers_by_tier": tiers,
        "numeric_sentences_without_citation": len(uncited),
        "uncited_examples": uncited[:5],
        "failures": [c for c in claims if not c["pass"]],
        "claims": claims,
    }


def run_checks(rd: Path, review_file: Path | None = None) -> dict:
    """`review_file`: attest another text against the same papers (a baseline's review) instead of step6_sota_review.md;
    its keys are read in any case (a baseline may write DuffyEtAl2022 for duffyetal2022). Step 7 is skipped then."""
    rd = Path(rd).resolve()
    w = load_world(rd)
    review = Path(review_file) if review_file else rd / "step6_sota_review.md"
    _, body, offset = split_frontmatter(review.read_text(encoding="utf-8"))
    claims6, uncited6 = review_claims(body, offset, w, finder=CiteFinder(rd, w.bib_keys))
    step6 = {"path": str(review), **attest_claims(claims6, uncited6, w)}

    step7_path = rd / "step7_gap_analysis.md"
    if step7_path.exists() and review_file is None:
        _, body7, offset7 = split_frontmatter(step7_path.read_text(encoding="utf-8"))
        claims7, uncited7 = review_claims(body7, offset7, w, skip_computed=True)
        step7 = {"path": str(step7_path), **attest_claims(claims7, uncited7, w)}
    else:
        step7 = {"status": "skipped", "reason": f"missing {step7_path}", "pass": True}

    sources = {"papers": len(w.evidence_papers()),
               "with_full_text": sum(1 for k in w.evidence_papers() if w.paper_basis(k) == "full-text"),
               "with_abstract": sum(1 for k in w.evidence_papers() if k in w.abstracts)}
    result = {
        "rules": "Ids are stripped before numbers are read. Integers < 10 and bare years (1900-2099) are ignored; signs "
                 "are ignored; a claim passes only if every number is in the source text (full text or abstract) of a "
                 "paper its ids rest on. A number found only in the decon extraction is not attested.",
        "source_coverage": sources,
        "step6": step6,
        "step7": step7,
    }
    result["overall_pass"] = step6["pass"] and step7["pass"]
    result["summary"] = {
        "step6_numeric_attestation": step6["numeric_attestation"],
        "step6_claims": f"{step6['attested_claims']}/{step6['numeric_claims']}",
        "step6_numbers_by_tier": step6["numbers_by_tier"],
        "step7_numeric_attestation": step7.get("numeric_attestation"),
        "step7_claims": f"{step7.get('attested_claims')}/{step7.get('numeric_claims')}",
        "overall_pass": result["overall_pass"],
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", type=Path, required=True, help="research folder")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--review-file", type=Path, help="attest this text (e.g. a baseline's review.md) instead of step6_sota_review.md")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    result = run_checks(args.session, args.review_file)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
