from __future__ import annotations

import xml.etree.ElementTree as ET

from .base import HttpClient
from .records import Hit

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMed:
    name = "pubmed"

    def __init__(self, http: HttpClient, api_key: str | None = None):
        self.http = http
        self.api_key = api_key
        http.limiter.intervals["eutils.ncbi.nlm.nih.gov"] = 0.11 if api_key else 0.34

    def search(self, query: str, query_id: str, year_from: int, year_to: int, limit: int = 30) -> list[Hit]:
        r = self.http.get(f"{BASE}/esearch.fcgi", params={"db": "pubmed", "term": query, "retmax": limit, "retmode": "json", "mindate": year_from, "maxdate": year_to, "datetype": "pdat", "api_key": self.api_key})
        if not r.ok:
            raise RuntimeError(f"pubmed esearch HTTP {r.status}")
        ids = (r.json().get("esearchresult") or {}).get("idlist") or []
        if not ids:
            return []
        return self.fetch(ids, query_id)

    def fetch(self, pmids: list[str], query_id: str) -> list[Hit]:
        r = self.http.get(f"{BASE}/efetch.fcgi", params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml", "api_key": self.api_key})
        if not r.ok:
            raise RuntimeError(f"pubmed efetch HTTP {r.status}")
        return self.parse(r.text or "", query_id)

    @staticmethod
    def parse(xml_text: str, query_id: str) -> list[Hit]:
        out: list[Hit] = []
        if not xml_text.strip():
            return out
        root = ET.fromstring(xml_text)
        for art in root.iter("PubmedArticle"):
            mc = art.find("MedlineCitation")
            if mc is None:
                continue
            pmid = (mc.findtext("PMID") or "").strip()
            a = mc.find("Article")
            if a is None:
                continue
            title = "".join(a.find("ArticleTitle").itertext()) if a.find("ArticleTitle") is not None else ""
            abstract_parts = []
            for at in a.findall("./Abstract/AbstractText"):
                label = at.get("Label")
                txt = "".join(at.itertext()).strip()
                abstract_parts.append(f"{label}: {txt}" if label else txt)
            abstract = " ".join(abstract_parts) or None
            authors = []
            for au in a.findall("./AuthorList/Author"):
                ln, fn, coll = au.findtext("LastName"), au.findtext("ForeName"), au.findtext("CollectiveName")
                if ln:
                    authors.append(f"{fn} {ln}".strip() if fn else ln)
                elif coll:
                    authors.append(coll)
            journal = a.findtext("./Journal/Title")
            year = a.findtext("./ArticleDate/Year") or a.findtext("./Journal/JournalIssue/PubDate/Year") or (a.findtext("./Journal/JournalIssue/PubDate/MedlineDate") or "")[:4]
            volume = a.findtext("./Journal/JournalIssue/Volume")
            issue = a.findtext("./Journal/JournalIssue/Issue")
            pages = a.findtext("./Pagination/MedlinePgn")
            doi = pmc = None
            for aid in art.findall("./PubmedData/ArticleIdList/ArticleId"):
                if aid.get("IdType") == "doi":
                    doi = (aid.text or "").strip()
                elif aid.get("IdType") == "pmc":
                    pmc = (aid.text or "").strip()
            lang = a.findtext("Language")
            out.append(
                Hit(
                    source="pubmed",
                    query_id=query_id,
                    title=title,
                    authors=authors,
                    year=int(year) if year and year.isdigit() else None,
                    journal=journal,
                    doi=doi,
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
                    abstract=abstract,
                    pubmed_id=pmid or None,
                    pmc_id=pmc,
                    venue_type="journal",
                    volume=volume,
                    issue=issue,
                    pages=pages,
                    language=lang,
                )
            )
        return out
