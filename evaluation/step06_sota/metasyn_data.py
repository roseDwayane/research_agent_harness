#!/usr/bin/env python3
"""Reading the MetaSyn dataset (https://huggingface.co/datasets/THUIR/MetaSyn), shared by metasyn_prepare.py (archived
engine) and metasyn_adopt.py (fusion-block harness). No dependency on either pipeline.

Layout of the data dir: {train,test}.parquet (one row per source review) and corpus/*.parquet (one row per article).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.dataset as ds
import requests

GROUND_TRUTH_FIELDS = (
    "Title", "Topic", "Research_Question", "Population", "Intervention", "Exposure", "Comparison", "Outcome",
    "Effect_Direction", "Statistical_Significance", "Effect_Size_Category", "Conclusion_Summary", "Key_Insights",
    "inclusion_criteria", "exclusion_criteria", "search_start_date", "search_end_date", "study_count",
    "matched_ref_count", "source",
)
# What a system under test must never read: the source review's findings and everything that states them.
# (Title and Abstract of the source review are included: the abstract of a review states its conclusion.)
ANSWER_FIELDS = (
    "Title", "Abstract", "Introduction", "Effect_Direction", "Statistical_Significance", "Effect_Size_Category",
    "Effect_Size_Type", "Effect_Size_Value", "CI_Lower", "CI_Upper", "P_Value", "I2_Value", "Q_Value", "Tau2_Value",
    "Heterogeneity_Level", "Total_Sample_Size", "Key_Insights", "Conclusion_Summary", "conclusion_paragraph",
)
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EMPTY = {"", "none", "nr", "na", "n/a", "not reported", "not stated", "nan"}


def _str(v: Any) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def has_value(v: Any) -> bool:
    """A field MetaSyn filled in (it writes 'None' / 'NR' for an absent one)."""
    return _str(v).lower() not in EMPTY


def _year(v: Any) -> int | None:
    s = _str(v)[:4]
    return int(s) if s.isdigit() else None


def load_review(data_dir: Path, review_id: int, split: str = "test") -> dict[str, Any]:
    df = pd.read_parquet(Path(data_dir) / f"{split}.parquet")
    rows = df[df["ID"] == review_id]
    if rows.empty:
        raise SystemExit(f"review {review_id} is not in the {split} split")
    return rows.iloc[0].to_dict()


def load_articles(data_dir: Path, ids: list[int]) -> list[dict[str, Any]]:
    table = ds.dataset(Path(data_dir) / "corpus", format="parquet").to_table(filter=ds.field("ID").isin(ids))
    by_id = {int(r["ID"]): r for r in table.to_pylist()}
    return [by_id[i] for i in ids if i in by_id]


def reference_ids(review: dict[str, Any]) -> tuple[list[int], set[int]]:
    """(the corpus ids a system is given, the source review's own ids that are left out)."""
    src = review.get("source_review_corpus_ids")
    source_ids = {int(x) for x in (src if src is not None else [])}
    return [int(x) for x in review["matched_corpus_ids"] if int(x) not in source_ids], source_ids


def pubmed_authors(pmid: str) -> list[str]:
    r = requests.get(EFETCH, params={"db": "pubmed", "id": pmid, "retmode": "xml"}, timeout=30)
    r.raise_for_status()
    out = []
    for a in ET.fromstring(r.content).iter("Author"):
        fn, ln = a.findtext("ForeName") or "", a.findtext("LastName") or ""
        if ln:
            out.append(f"{fn} {ln}".strip())
        elif a.findtext("CollectiveName"):
            out.append(a.findtext("CollectiveName"))
    return out


def article_text(a: dict[str, Any]) -> tuple[str, str]:
    """→ (access_level, markdown body): the abstract, then the PMC sections when the corpus has them."""
    abstract = _str(a.get("abstract"))
    sections = [s for s in (a.get("sections") or []) if _str(s.get("text"))]
    parts = ["## Abstract", "", abstract or "(no abstract available)", ""]
    for s in sections:
        parts += [f"## {_str(s.get('heading')).title() or 'Section'}", "", _str(s["text"]), ""]
    return ("full-text-html" if sections else "abstract-only"), "\n".join(parts).rstrip() + "\n"


def ngrams(text: str, n: int = 6) -> set[tuple[str, ...]]:
    t = re.findall(r"[a-z0-9]+", _str(text).lower())
    return {tuple(t[i:i + n]) for i in range(len(t) - n + 1)}


FINDING_CUES = re.compile(
    r"\b(studies|trials|reviews?|articles|papers|analys[ei]s|meta-analys[ei]s)\s+(included|identified|found|showed|reported|"
    r"demonstrated|revealed|suggest)|\b(we|this\s+(?:scoping\s+|systematic\s+)?(?:review|meta-analysis|study))\s+"
    r"(found|identified|concluded|showed|demonstrated|reports?)|\bpooled\b|\b\d+(?:\.\d+)?\s*%\s+(fewer|more|lower|higher)",
    re.IGNORECASE)


def clean_criteria(text: Any, answers: dict[str, Any], max_words: int = 120) -> tuple[str | None, str]:
    """(text to use or None, why not). A MetaSyn criteria field is used only if it reads as criteria: some rows hold a
    finding there (review 173's exclusion_criteria is a sentence of results), and a finding must not reach the
    system under test."""
    s = _str(text)
    if not has_value(s):
        return None, "empty"
    if len(s.split()) > max_words:
        return None, f"{len(s.split())} words: not a criteria list"
    if FINDING_CUES.search(s):
        return None, "reads as a finding, not a criterion"
    grams = ngrams(s)
    for name in ("Conclusion_Summary", "Key_Insights", "conclusion_paragraph", "Abstract"):
        other = ngrams(answers.get(name, ""))
        if grams and len(grams & other) / len(grams) >= 0.2:
            return None, f"shares text with {name}"
    return s, "used"
