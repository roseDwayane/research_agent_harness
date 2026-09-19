"""Test doubles: a fake httpx client routed by URL, and a fake LLM responder.

Together they let the whole 9-step pipeline run offline, and let the replay
test prove that a second run (cache read-only) reproduces every byte.
"""
from __future__ import annotations

import json
import re
from typing import Any

# --------------------------------------------------------------------------- #
# canned academic data
# --------------------------------------------------------------------------- #
PAPERS = {
    "A": {"title": "EEG neurofeedback training improves working memory in older adults with mild cognitive impairment", "authors": ["Ann Lee", "Bob Chan", "Cy Dee"], "year": 2023, "doi": "10.1000/a", "abstract": "A randomized controlled trial of EEG neurofeedback cognitive training in older adults with mild cognitive impairment showed improved working memory and attention.", "cc": 40, "s2": "s2A", "oa": "W1", "journal": "Journal of Neuro Aging"},
    "B": {"title": "Sham-controlled trial of theta neurofeedback for elderly cognition", "authors": ["Dan Wu", "Eve Li"], "year": 2022, "doi": "10.1000/b", "abstract": "Sham-controlled neurofeedback protocol in elderly participants; theta training improved executive function.", "cc": 25, "s2": "s2B", "oa": "W2", "journal": "Clinical Neurophysiology", "pmid": "111"},
    "C": {"title": "A systematic review of neurofeedback in aging populations", "authors": ["Fay Ng", "Gil Hu", "Hal Ip", "Ian Jo"], "year": 2021, "doi": "10.1000/c", "abstract": "Systematic review and meta-analysis of neurofeedback cognitive training in aging populations.", "cc": 60, "s2": "s2C", "oa": "W3", "journal": "Ageing Research Reviews"},
    "D": {"title": "Transformer models for EEG decoding in cognitive training", "authors": ["Kai Lo", "Liu Mo"], "year": 2024, "doi": None, "abstract": "We propose a transformer architecture for EEG decoding to personalise neurofeedback cognitive training.", "cc": 5, "s2": "s2D", "arxiv": "2401.00001", "journal": None},
    "E": {"title": "Brain plasticity and alpha oscillations in aging: a mechanistic account", "authors": ["Nia Ong"], "year": 2020, "doi": "10.1000/e", "abstract": "Mechanistic review of brain plasticity, alpha and theta oscillations and neurofeedback in aging.", "cc": 80, "oa": "W5", "journal": "Neuroscience Reviews", "refs_oa": ["W1", "W3"]},
    "F": {"title": "Rodent model of neurofeedback: hippocampal theta entrainment", "authors": ["Pat Qu", "Rae Su"], "year": 2022, "doi": "10.1000/f", "abstract": "Neurofeedback in rats; hippocampal theta entrainment; no human participants.", "cc": 3, "pmid": "222", "journal": "J Rodent Neuro"},
    "G": {"title": "Brain-computer interface for cognitive rehabilitation: a survey", "authors": ["Tao Vu", "Uma Wei", "Vic Xu"], "year": 2023, "doi": None, "abstract": "Survey of brain-computer interface and non-invasive neuromodulation approaches for cognitive rehabilitation in aging.", "cc": 12, "arxiv": "2302.00002", "journal": None},
    "H": {"title": "Home-based EEG neurofeedback feasibility in community-dwelling older adults", "authors": ["Wen Yu", "Xia Zhao"], "year": 2021, "doi": "10.1000/h", "abstract": "Feasibility pilot of home-based EEG neurofeedback cognitive training in community-dwelling older adults with mild cognitive impairment.", "cc": 9, "s2": "s2H", "journal": "Frontiers in Aging Neuroscience"},
}
BY_QUERY = {"Q1": ["A", "B"], "Q2": ["B", "C"], "Q3": ["E", "A"], "Q4": ["C", "F"], "Q5": ["D", "G"]}


def s2_paper(k: str) -> dict[str, Any]:
    p = PAPERS[k]
    ext = {}
    if p.get("doi"):
        ext["DOI"] = p["doi"].upper()
    if p.get("arxiv"):
        ext["ArXiv"] = p["arxiv"]
    if p.get("pmid"):
        ext["PubMed"] = p["pmid"]
    return {"paperId": p.get("s2", f"s2{k}"), "title": p["title"], "authors": [{"name": a} for a in p["authors"]], "year": p["year"], "abstract": p["abstract"], "externalIds": ext, "citationCount": p["cc"], "journal": {"name": p["journal"]} if p["journal"] else None, "url": f"https://www.semanticscholar.org/paper/s2{k}", "publicationTypes": ["JournalArticle"] if p["journal"] else None}


def oa_work(k: str) -> dict[str, Any]:
    p = PAPERS[k]
    words = p["abstract"].split()
    inv: dict[str, list[int]] = {}
    for i, w in enumerate(words):
        inv.setdefault(w, []).append(i)
    return {"id": f"https://openalex.org/{p['oa']}", "doi": f"https://doi.org/{p['doi']}" if p.get("doi") else None, "title": p["title"], "publication_year": p["year"], "authorships": [{"author": {"display_name": a}} for a in p["authors"]], "primary_location": {"source": {"display_name": p["journal"], "type": "journal"}}, "abstract_inverted_index": inv, "cited_by_count": p["cc"] + 1, "referenced_works": [f"https://openalex.org/{w}" for w in p.get("refs_oa", [])], "ids": {}, "biblio": {"volume": "12", "issue": "3", "first_page": "100", "last_page": "110"}, "type": "article"}


def pubmed_xml(keys: list[str]) -> str:
    arts = []
    for k in keys:
        p = PAPERS[k]
        authors = "".join(f"<Author><LastName>{a.split()[-1]}</LastName><ForeName>{a.split()[0]}</ForeName></Author>" for a in p["authors"])
        doi = f'<ArticleId IdType="doi">{p["doi"]}</ArticleId>' if p.get("doi") else ""
        arts.append(f"<PubmedArticle><MedlineCitation><PMID>{p['pmid']}</PMID><Article><ArticleTitle>{p['title']}</ArticleTitle><Abstract><AbstractText>{p['abstract']}</AbstractText></Abstract><AuthorList>{authors}</AuthorList><Journal><Title>{p['journal']}</Title><JournalIssue><PubDate><Year>{p['year']}</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation><PubmedData><ArticleIdList>{doi}</ArticleIdList></PubmedData></PubmedArticle>")
    return "<PubmedArticleSet>" + "".join(arts) + "</PubmedArticleSet>"


def arxiv_atom(keys: list[str]) -> str:
    entries = []
    for k in keys:
        p = PAPERS[k]
        authors = "".join(f"<author><name>{a}</name></author>" for a in p["authors"])
        entries.append(f'<entry><id>http://arxiv.org/abs/{p["arxiv"]}v1</id><title>{p["title"]}</title><summary>{p["abstract"]}</summary><published>{p["year"]}-03-01T00:00:00Z</published>{authors}<arxiv:primary_category term="cs.LG"/></entry>')
    return '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">' + "".join(entries) + "</feed>"


ARXIV_HTML = "<html><body><article><h1>Transformer models for EEG decoding</h1><h2>Abstract</h2><p>" + "We propose a transformer. " * 40 + "</p><h2>1 Introduction</h2><p>" + "Intro text about EEG decoding and neurofeedback. " * 60 + "</p><h2>2 Methods</h2><p>" + "Method details with N=40 participants. " * 60 + "</p><table><tr><th>Model</th><th>Acc</th></tr><tr><td>Ours</td><td>0.91</td></tr></table><h2>3 Results</h2><p>" + "Accuracy 0.91 vs 0.85 baseline. " * 60 + "</p><h2>4 Discussion</h2><p>" + "Limitations: small sample. " * 60 + "</p><h2>References</h2><p>[1] Lee 2023.</p></article></body></html>"


class FakeResponse:
    def __init__(self, status: int, text: str = "", content: bytes | None = None, url: str = "", ctype: str = "application/json"):
        self.status_code, self.text, self.url = status, text, url
        self.content = content if content is not None else text.encode()
        self.headers = {"content-type": ctype}


class FakeHttpx:
    """Drop-in for httpx.Client: routes by URL, counts calls."""

    calls: list[str] = []

    def __init__(self, *a, **k):
        pass

    def close(self):
        pass

    def request(self, method, url, params=None, headers=None, content=None):
        params = params or {}
        FakeHttpx.calls.append(url)
        if "api.semanticscholar.org" in url:
            if url.endswith("/paper/search"):
                q = params["query"].lower()
                keys = [k for k in PAPERS if any(w in PAPERS[k]["title"].lower() for w in q.split()[:2])]
                keys = keys[:4] or ["A"]
                return FakeResponse(200, json.dumps({"total": len(keys), "data": [s2_paper(k) for k in keys]}))
            if "/references" in url:
                pid = url.split("/paper/")[1].split("/")[0]
                refs = ["H", "A"] if pid in ("s2C", "s2E", "DOI:10.1000/e") else ["H"]
                if "fields" in params and params["fields"] == "paperId":
                    return FakeResponse(200, json.dumps({"data": [{"citedPaper": {"paperId": PAPERS[r].get("s2", f"s2{r}")}} for r in refs]}))
                return FakeResponse(200, json.dumps({"data": [{"citedPaper": s2_paper(r)} for r in refs]}))
            if "/paper/search/match" in url:
                return FakeResponse(404, "{}")
            if "/paper/ARXIV:2401.00001" in url:
                return FakeResponse(200, json.dumps({"paperId": "s2D", "externalIds": {"DOI": "10.1000/d", "ArXiv": "2401.00001"}}))
            if "/paper/" in url:
                return FakeResponse(404, "{}")
        if "api.openalex.org/works" in url and "search" in params:
            q = params["search"].lower()
            keys = [k for k in PAPERS if PAPERS[k].get("oa") and any(w in PAPERS[k]["title"].lower() for w in q.split()[:2])][:3] or ["A"]
            return FakeResponse(200, json.dumps({"results": [oa_work(k) for k in keys]}))
        if "api.openalex.org/works" in url:
            return FakeResponse(200, json.dumps({"results": []}))
        if "esearch.fcgi" in url:
            return FakeResponse(200, json.dumps({"esearchresult": {"idlist": ["111", "222"]}}))
        if "efetch.fcgi" in url and params.get("db") == "pubmed":
            return FakeResponse(200, pubmed_xml(["B", "F"]), ctype="text/xml")
        if "efetch.fcgi" in url and params.get("db") == "pmc":
            return FakeResponse(404, "")
        if "export.arxiv.org" in url:
            return FakeResponse(200, arxiv_atom(["D", "G"]), ctype="application/atom+xml")
        if url == "https://arxiv.org/html/2401.00001":
            return FakeResponse(200, ARXIV_HTML, ctype="text/html")
        if "arxiv.org/html" in url:
            return FakeResponse(404, "")
        if "arxiv.org/pdf" in url:
            return FakeResponse(404, "", b"")
        if "idconv" in url:
            return FakeResponse(200, json.dumps({"records": [{}]}))
        if "doi.org/" in url:
            return FakeResponse(200, "<html><body><p>Abstract only. Buy now.</p></body></html>", ctype="text/html")
        return FakeResponse(404, "")


# --------------------------------------------------------------------------- #
# fake LLM
# --------------------------------------------------------------------------- #
def _user_text(messages: list[dict[str, Any]]) -> str:
    m = messages[0]["content"]
    return m if isinstance(m, str) else json.dumps(m)


def fake_llm(tool: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    text = _user_text(messages)
    if tool == "emit_pico_queries":
        return {"topic_en": "EEG neurofeedback for MCI", "field_type": "biomedical", "population": "Older adults with mild cognitive impairment", "intervention": "EEG neurofeedback cognitive training", "comparison": "Sham neurofeedback", "outcome": "Working memory, attention", "setting": "Clinical or home-based", "timeframe": "2019-2026", "population_zh": "輕度認知障礙長者", "intervention_zh": "EEG 神經回饋認知訓練", "comparison_zh": "假神經回饋", "outcome_zh": "工作記憶、注意力", "setting_zh": "臨床或居家", "queries": [{"id": f"Q{i}", "strategy": s, "strategy_zh": z, "query": q, "rationale": f"r{i}", "rationale_zh": f"理由{i}"} for i, (s, z, q) in enumerate([("Core terms + Population", "核心", "EEG neurofeedback older adults"), ("Synonyms + MeSH", "同義", '"Neurofeedback"[MeSH] OR "EEG biofeedback" AND elderly'), ("Mechanism + Theory", "機制", "brain plasticity alpha oscillations aging"), ("Methodology + Design", "方法", "systematic review neurofeedback aging"), ("Cross-disciplinary", "跨域", "transformer brain-computer interface cognitive rehabilitation")], 1)]}
    if tool == "emit_screening_criteria":
        return {"inclusion": [{"en": "Human older adults", "zh": "人類長者"}, {"en": "EEG neurofeedback intervention", "zh": "EEG 神經回饋"}, {"en": "Cognitive outcomes", "zh": "認知結果"}], "exclusion": [{"en": "Animal studies", "zh": "動物研究"}, {"en": "No original data", "zh": "無原始資料"}, {"en": "Off-topic hardware", "zh": "離題硬體"}], "tier_names": [{"tier": 1, "en": "Core RCTs", "zh": "核心試驗"}, {"tier": 2, "en": "Strong supporting", "zh": "強支持"}, {"tier": 3, "en": "Contextual", "zh": "脈絡"}]}
    if tool == "emit_paper_scores":
        ids = re.findall(r"\[(paper_\d{3})\]", text)
        out = []
        for pid in ids:
            block = text.split(f"[{pid}]", 1)[1].split("\n[paper_", 1)[0].lower()
            if "rats" in block:
                sc = (1, 3, 2, "Population mismatch: studies rats, not humans")
            elif "transformer" in block:
                sc = (3, 3, 4, None)
            elif "survey" in block:
                sc = (2, 3, 3, None)
            elif "systematic" in block:
                sc = (4, 4, 4, None)
            elif "feasibility" in block:
                sc = (4, 3, 3, None)
            else:
                sc = (5, 4, 5, None)
            out.append({"paper_id": pid, "relevance": sc[0], "quality": sc[1], "recency_impact": sc[2], "rationale": f"auto rationale for {pid}", "exclusion_reason": sc[3]})
        return {"scores": out}
    if tool == "emit_paper_digest":
        key = re.search(r"Citation key: (\S+)", text).group(1)
        meth = "review" if "review" in text.lower() or "survey" in text.lower() else ("computational" if "transformer" in text.lower() else "experimental")
        return {"citation_key": key, "problem": "p", "method": "m", "key_results": ["+18% (p<0.01)"], "limitations": ["small N"], "future_work": ["longitudinal"], "methodology": meth, "sample_or_dataset": "N=40"}
    if tool == "emit_sota_review":
        keys = re.search(r"citation keys you may use: (.*)", text).group(1).split(", ")
        keys = [k.strip() for k in keys if k.strip()]
        half = max(1, len(keys) // 2)
        t1, t2 = keys[:half], keys[half:] or keys[:1]
        theme = lambda n, ks, title: {"number": n, "title_en": title, "title_zh": f"主題{n}", "paper_keys": ks, "consensus_en": f"Consensus ({ks[0]}).", "consensus_zh": "共識", "debates_en": "Debate.", "debates_zh": "爭議", "methods_en": "RCTs.", "methods_zh": "方法", "key_results_en": "| Study | N | Method | Primary Outcome | Result |\n|---|---|---|---|---|\n| " + ks[0] + " | 40 | NF | WM | +18% |", "key_results_zh": "結果"}  # noqa: E731
        pm = [{"citation_key": k, "theme_number": 1 if k in t1 else 2, "methodology": "experimental" if i % 2 else "review", "is_bridge": i == 0} for i, k in enumerate(keys)]
        edges = [{"from_key": keys[i], "to_key": keys[i + 1], "label": "shared: neurofeedback protocol"} for i in range(len(keys) - 1)] + [{"from_key": "Ghost2020", "to_key": keys[0], "label": "phantom"}]
        return {"executive_summary_en": "Summary.", "executive_summary_zh": "摘要", "themes": [theme(1, t1, "Clinical neurofeedback trials"), theme(2, t2, "Mechanisms and decoding")], "trends_en": "t", "trends_zh": "趨", "converging_en": "c", "converging_zh": "匯", "diverging_en": "d", "diverging_zh": "分", "interactions_en": "i", "interactions_zh": "交", "paper_map": pm, "edges": edges}
    if tool == "emit_gap_analysis":
        keys = re.search(r"Valid citation keys: (.*)", text).group(1).split(", ")
        ev = lambda k: {"citation_key": k, "year": 2023, "explanation_en": f"{k} stops short", "explanation_zh": "止步"}  # noqa: E731
        gap = lambda t, typ, s, n, f: {"title_en": t, "title_zh": "缺口", "gap_type": typ, "secondary_type": None, "description_en": "No study tracked effects beyond 3 months.", "description_zh": "無研究追蹤超過三個月。", "supporting_evidence": [ev(keys[0]), ev(keys[1 % len(keys)])], "counter_evidence": [], "why_it_matters_en": "matters", "why_it_matters_zh": "重要", "severity": s, "novelty": n, "feasibility": f, "severity_rationale_en": "s", "severity_rationale_zh": "嚴", "novelty_rationale_en": "n", "novelty_rationale_zh": "新", "feasibility_rationale_en": "f", "feasibility_rationale_zh": "可"}  # noqa: E731
        return {"executive_summary_en": "E", "executive_summary_zh": "總", "gaps": [gap("Long-term follow-up", "temporal", 4, 4, 3), gap("Home-based delivery", "population", 5, 4, 3), gap("Decoding-in-the-loop", "integration", 3, 5, 2)], "coverage_strength_en": "c", "coverage_strength_zh": "覆", "methodology_distribution_en": "m", "methodology_distribution_zh": "方", "cross_gap_patterns_en": "x", "cross_gap_patterns_zh": "跨"}
    if tool == "emit_hypothesis_spec":
        dims = ["Population", "Intervention / Method", "Comparison / Control", "Primary Outcome", "Secondary Outcome", "Setting", "Design", "Timeframe"]
        return {"executive_summary_en": "E", "executive_summary_zh": "總", "gap_summary_en": "G", "gap_summary_zh": "缺", "gap_selection_rationale_en": "chosen", "gap_selection_rationale_zh": "選", "research_questions": [{"id": "RQ1", "focus": "Feasibility", "question_en": "Can it work?", "question_zh": "可行嗎", "elaboration_en": "e", "elaboration_zh": "說"}, {"id": "RQ2", "focus": "Primary", "question_en": "Effect?", "question_zh": "效果", "elaboration_en": "e", "elaboration_zh": "說"}], "hypotheses": [{"id": "H1", "label_en": "Primary", "label_zh": "主要", "h0_en": "No difference", "h0_zh": "無顯著差異", "h1_en": "Home NF improves WM by >=10%", "h1_zh": "將改善", "direction_magnitude_en": "based on LeeEtAl2023", "direction_magnitude_zh": "依據", "statistical_approach_en": "paired t-test", "statistical_approach_zh": "配對 t 檢定"}], "scope_in": [{"dimension_en": d, "dimension_zh": "維度", "spec_en": "spec", "spec_zh": "規格"} for d in dims], "scope_out": [{"exclusion_en": f"ex{i}", "exclusion_zh": "排除", "rationale_en": "why", "rationale_zh": "理由"} for i in range(3)], "scope_rationale_en": "r", "scope_rationale_zh": "邏", "conceptual_framework_en": "```\nA -> B\n```", "conceptual_framework_zh": "框架", "risks": [{"risk": f"r{i}", "likelihood": "Medium", "impact": "High", "mitigation": "m"} for i in range(3)], "traceability": [{"element": "RQ1", "source": "GAP_001", "evidence": "e"}], "journals": [{"name": "Frontiers in Aging Neuroscience", "impact_factor": "~4.1 (2024)", "scope_fit_en": "fit", "scope_fit_zh": "契合", "review_timeline": "~3 months", "open_access": "Yes, APC", "why_en": "w", "why_zh": "因", "strategy_en": "Best fit", "strategy_zh": "最佳", "papers_from_collection": []}, {"name": "NeuroImage", "impact_factor": "~4.7", "scope_fit_en": "f", "scope_fit_zh": "契", "review_timeline": "~4 months", "open_access": "Yes", "why_en": "w", "why_zh": "因", "strategy_en": "Aspirational", "strategy_zh": "挑戰", "papers_from_collection": []}, {"name": "J Neural Eng", "impact_factor": "~3.7", "scope_fit_en": "f", "scope_fit_zh": "契", "review_timeline": "~2 months", "open_access": "Hybrid", "why_en": "w", "why_zh": "因", "strategy_en": "Solid", "strategy_zh": "穩健", "papers_from_collection": []}], "journal_selection_criteria_en": "c", "journal_selection_criteria_zh": "準", "submission_strategy_en": "s", "submission_strategy_zh": "策"}
    if tool == "emit_manuscript_sections":
        keys = re.search(r"VALID CITATION KEYS \(\d+\): (.*)", text).group(1).split(", ")
        k0, k1 = keys[0], keys[1 % len(keys)]
        intro = "\\section{Introduction}\n\\label{sec:intro}\n" + (("Cognitive decline matters \\cite{" + k0 + "}. ") * 30) + "\n\nPrior work \\cite{" + k1 + ", Phantom2099} found 18\\% gains. \\cite{Fake2000} Section~\\ref{sec:related}.\n\\begin{itemize}\\item We propose X.\\end{itemize}"
        rw = "\\section{Related Work}\n\\label{sec:related}\n\\subsection{Trials}\\label{sec:related:trials}\n" + " ".join("\\cite{" + k + "}" for k in keys) + " progression."
        return {"intro_latex": intro, "relatedwork_latex": rw, "target_journal": "Frontiers in Aging Neuroscience"}
    raise AssertionError(f"unexpected tool {tool}")
