"""Unit tests for the deterministic (pure-code) layers."""
from __future__ import annotations

import itertools
import random
from decimal import Decimal
from pathlib import Path

import pytest

from scholar_research.cache import Cache, CacheMissError
from scholar_research.providers.arxiv import ArXiv, to_arxiv_query
from scholar_research.providers.openalex import reconstruct_abstract
from scholar_research.providers.pubmed import PubMed
from scholar_research.providers.records import Hit
from scholar_research.schemas.paper import ScreenedPaper, Screening
from scholar_research.steps.s2_search import Collection, plain_query
from scholar_research.steps.s3_screen import classify, composite_score, tier_of
from scholar_research.steps.s4_export import apa_authors, build_entries, citation_keys, sentence_case, split_name, validate
from scholar_research.steps.s7_gaps import gap_composite
from scholar_research.steps.s9_write import parse_bib, validate_citations, word_count
from scholar_research.utils import last_name, normalize_doi, slugify, word_overlap

W = {"relevance": 0.50, "quality": 0.30, "recency_impact": 0.20}


# ----------------------------- screening arithmetic ----------------------- #
def test_composite_exhaustive_all_125_combos_match_decimal():
    for r, q, c in itertools.product(range(1, 6), repeat=3):
        exp = Decimal(r) * Decimal("0.5") + Decimal(q) * Decimal("0.3") + Decimal(c) * Decimal("0.2")
        assert composite_score(r, q, c, W) == float(exp.quantize(Decimal("0.01")))


def test_composite_property_random_1000():
    rng = random.Random(42)
    for _ in range(1000):
        r, q, c = (rng.randint(1, 5) for _ in range(3))
        comp = composite_score(r, q, c, W)
        assert 1.0 <= comp <= 5.0
        assert comp == composite_score(r, q, c, W)  # identical axes → identical composite
        cat = classify(comp, 3.5, 3.0)
        assert (cat == "included") == (comp >= 3.5)
        assert (cat == "borderline") == (3.0 <= comp < 3.5)
        assert (cat == "excluded") == (comp < 3.0)


def test_classification_edges():
    assert classify(3.50, 3.5, 3.0) == "included"
    assert classify(3.49, 3.5, 3.0) == "borderline"
    assert classify(2.90, 3.5, 3.0) == "excluded"
    assert tier_of(4.5, [4.5, 4.0], 3.5) == 1
    assert tier_of(4.49, [4.5, 4.0], 3.5) == 2
    assert tier_of(3.5, [4.5, 4.0], 3.5) == 3
    assert tier_of(3.4, [4.5, 4.0], 3.5) is None


def test_gap_composite_example_from_skill():
    assert gap_composite(5, 4, 3, {"severity": 0.4, "novelty": 0.3, "feasibility": 0.3}) == 4.10


# ----------------------------- utils ------------------------------------- #
def test_slug_and_doi():
    assert slugify("EEG-based cognitive training for elderly!!") == "eeg-based-cognitive-training-for-elderly"
    assert len(slugify("x" * 100)) <= 40
    assert normalize_doi("https://doi.org/10.1234/ABC") == "10.1234/abc"
    assert normalize_doi("doi:10.1/x") == "10.1/x"
    assert last_name("Chunqiu Steven Xia") == "Xia"
    assert last_name("García-López, María") == "García-López"
    assert word_overlap("Deep learning for EEG denoising", "deep learning for eeg denoising.") == 1.0


# ----------------------------- cache ------------------------------------- #
def test_cache_modes(tmp_path: Path):
    c = Cache(tmp_path, "read-write")
    calls = []
    rec = c.get_or_fetch("http", {"u": 1}, lambda: (calls.append(1), {"status": 200})[1])
    assert rec["_cache"]["hit"] is False and len(calls) == 1
    rec = c.get_or_fetch("http", {"u": 1}, lambda: (calls.append(1), {"status": 200})[1])
    assert rec["_cache"]["hit"] is True and len(calls) == 1
    ro = Cache(tmp_path, "read-only")
    assert ro.get_or_fetch("http", {"u": 1}, lambda: {})["status"] == 200
    with pytest.raises(CacheMissError):
        ro.get_or_fetch("http", {"u": 2}, lambda: {})
    rf = Cache(tmp_path, "refresh")
    rf.get_or_fetch("http", {"u": 1}, lambda: (calls.append(1), {"status": 201})[1])
    assert len(calls) == 2 and Cache(tmp_path, "read-only").get_or_fetch("http", {"u": 1}, lambda: {})["status"] == 201


# ----------------------------- providers --------------------------------- #
def test_openalex_abstract_reconstruction():
    assert reconstruct_abstract({"is": [1], "This": [0], "abstract": [3], "an": [2]}) == "This is an abstract"
    assert reconstruct_abstract(None) is None


def test_arxiv_query_conversion():
    q = to_arxiv_query('"brain-computer interface" AND (EEG OR neurofeedback) NOT rats')
    assert q == 'all:"brain-computer interface" AND ( all:EEG OR all:neurofeedback ) ANDNOT all:rats'
    assert plain_query('"Neurofeedback"[MeSH] OR "EEG biofeedback" AND (elderly OR aged)') == "Neurofeedback EEG biofeedback elderly aged"


PUBMED_XML = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Neurofeedback in MCI</ArticleTitle>
<Abstract><AbstractText Label="BACKGROUND">Bg.</AbstractText><AbstractText Label="RESULTS">Good.</AbstractText></Abstract>
<AuthorList><Author><LastName>Smith</LastName><ForeName>John</ForeName></Author><Author><LastName>Lee</LastName><ForeName>Ann</ForeName></Author></AuthorList>
<Journal><Title>J Neuro</Title><JournalIssue><Volume>12</Volume><Issue>3</Issue><PubDate><Year>2023</Year></PubDate></JournalIssue></Journal><Pagination><MedlinePgn>10-20</MedlinePgn></Pagination></Article></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/ABC</ArticleId><ArticleId IdType="pmc">PMC99</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""


def test_pubmed_parse():
    h = PubMed.parse(PUBMED_XML, "Q1")[0]
    assert h.pubmed_id == "123" and h.doi == "10.1/abc" and h.pmc_id == "PMC99" and h.year == 2023
    assert h.authors == ["John Smith", "Ann Lee"] and h.abstract == "BACKGROUND: Bg. RESULTS: Good." and h.pages == "10-20"


ARXIV_XML = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"><entry><id>http://arxiv.org/abs/2401.12345v2</id>
<title>Transformer  EEG\n denoising</title><summary>An abstract.</summary><published>2024-01-15T00:00:00Z</published><author><name>A Author</name></author>
<arxiv:primary_category term="cs.LG"/></entry></feed>"""


def test_arxiv_parse():
    h = ArXiv.parse(ARXIV_XML, "Q5")[0]
    assert h.arxiv_id == "2401.12345" and h.title == "Transformer EEG denoising" and h.year == 2024 and h.arxiv_primary_class == "cs.LG"


# ----------------------------- dedup ------------------------------------- #
def test_collection_dedup_by_doi_and_title():
    col = Collection(0.85)
    a = Hit(source="semantic_scholar", query_id="Q1", title="Deep learning for EEG denoising", authors=["Ann Lee"], year=2023, doi="10.1/A", abstract="short", citation_count=5, semantic_scholar_id="s1")
    b = Hit(source="openalex", query_id="Q2", title="Deep Learning for EEG Denoising.", authors=["Ann Lee"], year=2023, doi="https://doi.org/10.1/a", abstract="a much longer abstract text here", citation_count=9, openalex_id="W1")
    c = Hit(source="arxiv", query_id="Q3", title="Deep learning for EEG denoising", authors=["Ann Lee"], year=2024, arxiv_id="2301.1")
    d = Hit(source="arxiv", query_id="Q3", title="Deep learning for EEG denoising", authors=["Bob Chan"], year=2023, arxiv_id="2301.2")
    for h in (a, b, c, d):
        col.add(h)
    assert len(col.papers) == 2  # a+b+c merged (same author, ±1 year); d differs by first author
    p = col.papers[0]
    assert p["sources_found_in"] == ["semantic_scholar", "openalex", "arxiv"]
    assert p["citation_count"] == 9  # OpenAlex preferred for citation counts
    assert p["abstract"] == "short"  # S2 preferred for abstracts
    assert p["arxiv_id"] == "2301.1" and p["openalex_id"] == "W1"
    assert col.raw_count == 4 and col.per_source_unique["arxiv"] == 2


# ----------------------------- export ------------------------------------ #
def _sp(pid, title, authors, year, journal=None, doi=None, arxiv=None, venue=None, comp=4.0):
    return ScreenedPaper(id=pid, title=title, authors=authors, year=year, journal=journal, doi=doi, arxiv_id=arxiv, venue_type=venue, screening=Screening(relevance=4, quality=4, recency_impact=4, composite=comp, tier=2))


def test_names_and_apa():
    assert split_name("Chunqiu Steven Xia") == ("Xia", "Chunqiu Steven")
    assert split_name("Ludwig van Beethoven") == ("van Beethoven", "Ludwig")
    assert apa_authors(["Chunqiu Steven Xia", "Lingming Zhang"]) == "Xia, C. S., & Zhang, L."
    assert apa_authors(["A B", "C D", "E F"]) == "B, A., D, C., & F, E."
    assert sentence_case("Keep the Conversation Going: Fixing 162 Bugs Using ChatGPT and EEG") == "Keep the conversation going: Fixing 162 bugs using ChatGPT and EEG"


def test_citation_keys_and_disambiguation():
    ps = [_sp("paper_001", "Beta study", ["Qi Zhang"], 2024), _sp("paper_002", "Alpha study", ["Qi Zhang"], 2024), _sp("paper_003", "Two authors", ["C S Xia", "L Zhang"], 2024), _sp("paper_004", "Many", ["I Bouzenia", "P Devanbu", "M Pradel"], 2025), _sp("paper_005", "Solo", ["Wei Li"], 2023)]
    keys = citation_keys(ps)
    assert keys == {"paper_001": "Zhang2024b", "paper_002": "Zhang2024a", "paper_003": "XiaZhang2024", "paper_004": "BouzeniaEtAl2025", "paper_005": "Li2023"}


def test_entries_validate_and_bib():
    ps = [_sp("paper_001", "A journal paper on X", ["Ann Lee", "Bob Chan"], 2023, journal="Journal of Things", doi="10.1/x"), _sp("paper_002", "A conf paper", ["Ann Lee"], 2024, journal="Proceedings of the 1st Conf", doi="10.2/y", venue="conference"), _sp("paper_003", "A preprint on LLMs", ["Cy Dee", "Ed Fox", "Gil Hu"], 2024, arxiv="2401.1")]
    entries, skipped = build_entries(ps)
    assert not skipped and validate(entries) == []
    by = {e.key: e for e in entries}
    assert by["LeeChan2023"].entry_type == "article" and by["LeeChan2023"].apa.startswith("Lee, A., & Chan, B. (2023). A journal paper on X. *Journal of Things*. https://doi.org/10.1/x")
    assert by["Lee2024"].entry_type == "inproceedings" and "In *Proceedings of the 1st Conf*" in by["Lee2024"].apa
    assert by["DeeEtAl2024"].entry_type == "misc" and "@misc{DeeEtAl2024" in by["DeeEtAl2024"].bibtex and "{LLMs}" in by["DeeEtAl2024"].bibtex
    parsed = parse_bib("\n".join(e.bibtex for e in entries))
    assert set(parsed) == {"LeeChan2023", "Lee2024", "DeeEtAl2024"}


# ----------------------------- write validation -------------------------- #
def test_phantom_citation_stripping():
    tex, ph, used = validate_citations(r"Known \cite{A2020} and mixed \cite{A2020, Ghost2021} and phantom \cite{Nope2022}.", {"A2020"})
    assert ph == ["Ghost2021", "Nope2022"] and used == {"A2020"}
    assert r"\cite{A2020, Ghost2021}" not in tex and "TODO: citation needed" in tex and r"\cite{Nope2022}" not in tex
    assert word_count(r"\section{Intro} Hello world \cite{A2020} 3 words % comment") >= 3
