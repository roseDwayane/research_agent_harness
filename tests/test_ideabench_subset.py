"""IdeaBench subset: cutoffs, ref filters, extract schema, offline extract."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from scholar_research.cache import Cache
from scholar_research.cli import main
from scholar_research.config import LLMConfig
from evaluation.step08.ideabench.cutoffs import (
    MODEL_REGISTRY,
    latest_cutoff,
    safe_start_after_cutoffs,
    validate_target_window,
)
from evaluation.step08.ideabench.extract import IdeaBenchTargetIdea, extract_target_idea
from evaluation.step08.ideabench.s2 import filter_references, is_non_primary, pick_low_resource
from evaluation.step08.ideabench.targets import filter_openalex_references, to_target_card
from scholar_research.llm.client import FakeBackend, LLMClient
from scholar_research.llm.ledger import Ledger


def test_cutoff_safe_start_and_window():
    assert safe_start_after_cutoffs(["cloud_gpt_4o"]).isoformat() == "2023-11-01"
    assert safe_start_after_cutoffs(["local_qwen_3.8B"]).isoformat() == "2024-11-01"
    assert latest_cutoff(["local_qwen_3.8B", "cloud_qwen_max"]).isoformat() == "2025-03-31"
    assert safe_start_after_cutoffs(["local_qwen_3.8B", "cloud_qwen_max"]).isoformat() == "2025-04-01"
    ok = validate_target_window(["local_qwen_3.8B"], "2026-01-01", "2026-06-30")
    assert ok["safe_start"] == "2024-11-01"
    with pytest.raises(ValueError, match="contamination"):
        validate_target_window(["cloud_qwen_max"], "2025-01-01", "2025-06-30")
    with pytest.raises(KeyError):
        validate_target_window(["no_such_model"], "2026-01-01", "2026-06-30")
    assert "local_qwen_3.8B" in MODEL_REGISTRY


def test_filter_references_ideabench_rules():
    refs = [
        {"paperId": "a", "title": "A", "abstract": "abs", "citationCount": 10, "publicationTypes": ["JournalArticle"]},
        {"paperId": "b", "title": "B", "abstract": "abs", "citationCount": 3, "publicationTypes": ["JournalArticle"]},
        {"paperId": "c", "title": "C", "abstract": "abs", "citationCount": 50, "publicationTypes": ["Review"]},
        {"paperId": "d", "title": "D", "abstract": "", "citationCount": 20, "publicationTypes": ["JournalArticle"]},
        {"paperId": "e", "title": "E", "abstract": "abs", "citationCount": 8, "publicationTypes": ["Editorial"]},
    ]
    kept = filter_references(refs)
    assert [p["paperId"] for p in kept] == ["a"]
    assert is_non_primary(["Review"])
    assert not is_non_primary(["JournalArticle"])


def test_filter_openalex_references_ideabench_rules():
    refs = [
        {"paperId": "oa:a", "title": "A", "abstract": "abs", "citationCount": 10, "openalex_type": "article"},
        {"paperId": "oa:b", "title": "B", "abstract": "abs", "citationCount": 3, "openalex_type": "article"},
        {"paperId": "oa:c", "title": "C", "abstract": "abs", "citationCount": 50, "openalex_type": "review"},
        {"paperId": "oa:d", "title": "D", "abstract": "", "citationCount": 20, "openalex_type": "article"},
        {"paperId": "oa:e", "title": "", "abstract": "abs", "citationCount": 20, "openalex_type": "article"},
    ]
    kept = filter_openalex_references(refs)
    assert [p["paperId"] for p in kept] == ["oa:a"]


def test_to_target_card_keeps_provider_fields():
    card = to_target_card(
        {
            "source": "openalex",
            "paperId": "openalex:W123",
            "title": "Target",
            "abstract": "Abstract",
            "year": 2026,
            "publicationDate": "2026-02-03",
            "venue": "Nature Medicine",
            "citationCount": 12,
            "publicationTypes": ["JournalArticle"],
            "doi": "10.1/x",
            "pmid": "123",
            "url": "https://doi.org/10.1/x",
            "openalex_id": "W123",
            "referenced_works": ["W1", "W2"],
            "venue_filter": "top_venue",
        }
    )
    assert card["paperId"] == "openalex:W123"
    assert card["openalex_id"] == "W123"
    assert card["referenced_works"] == ["W1", "W2"]
    assert card["venue_filter"] == "top_venue"


def test_pick_low_resource_deterministic():
    refs = [
        {
            "paperId": f"p{i}",
            "title": str(i),
            "abstract": "x",
            "citationCount": 10,
            "publicationTypes": ["JournalArticle"],
        }
        for i in range(10)
    ]
    a = pick_low_resource(refs, 5, seed=0)
    b = pick_low_resource(refs, 5, seed=0)
    c = pick_low_resource(refs, 5, seed=1)
    assert [p["paperId"] for p in a] == [p["paperId"] for p in b]
    assert len(a) == 5
    assert [p["paperId"] for p in a] != [p["paperId"] for p in c]


def test_extract_schema_and_prompt(tmp_path: Path):
    with pytest.raises(ValidationError):
        IdeaBenchTargetIdea(summary="We study something without the required prefix.")
    ok = IdeaBenchTargetIdea(
        summary="Given that aging strains care systems, we propose optimizing home-health routing."
    )
    assert ok.summary.startswith("Given that ")

    cache = Cache(tmp_path / "c", "read-write")
    ledger = Ledger(tmp_path / "ledger.jsonl")
    cfg = LLMConfig(model="extractor", provider="ollama")

    def responder(tool, messages):
        assert tool == "emit_ideabench_target_idea"
        user = messages[0]["content"]
        assert "Please begin the paragraph with" in user
        assert "Hypothesis:" in user and "Given that" in user
        assert "ABSTRACT TEXT HERE" in user
        return {"summary": "Hypothesis: We will test a concise idea without numbers."}

    client = LLMClient(cfg, cache, ledger, backend=FakeBackend(responder))
    text = extract_target_idea(client, "ABSTRACT TEXT HERE")
    assert text.startswith("Hypothesis:")


def test_cli_list_cutoffs():
    r = CliRunner()
    out = r.invoke(main, ["eval", "ideabench-build", "--list-cutoffs"])
    assert out.exit_code == 0, out.output
    assert "local_qwen_3.8B" in out.output
    assert "safe_start" in out.output


def test_cli_accepts_openalex_source_with_list_cutoffs():
    r = CliRunner()
    out = r.invoke(main, ["eval", "ideabench-build", "--source", "openalex", "--list-cutoffs"])
    assert out.exit_code == 0, out.output
    assert "safe_start" in out.output
