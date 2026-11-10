"""Download official LitSearch inputs and build frozen Step 2/3 task files.

Optional dependencies: datasets, huggingface_hub, nltk, numpy, rank_bm25.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .adapter import read_json, write_json

DATASET = "princeton-nlp/LitSearch"
# The revision already used by the project's earlier official-corpus evaluation.
DEFAULT_REVISION = "9573fb284a1026c998df47024b888a163f0f0e25"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_queries(rows, limit: int | None = None) -> list[dict]:
    """Keep gold IDs in the evaluation-side task file, never in a research folder."""
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    tasks = []
    for index, row in enumerate(rows, 1):
        if limit is not None and len(tasks) >= limit:
            break
        query = str(row.get("query") or "").strip()
        gold = [str(value) for value in row.get("corpusids") or []]
        if not query or not gold:
            raise ValueError(f"official query {index} lacks query or corpusids")
        tasks.append({"qid": f"ls_{index:03d}", "session": f"ls_{index:03d}",
                      "query": query, "corpusids": gold,
                      "query_set": row.get("query_set"), "specificity": row.get("specificity"),
                      "quality": row.get("quality")})
    if not tasks:
        raise ValueError("official query dataset is empty")
    return tasks


def _revision(revision: str) -> str:
    from huggingface_hub import HfApi
    return HfApi().dataset_info(DATASET, revision=revision).sha


def _load(config: str, revision: str, cache: Path):
    from datasets import load_dataset
    return load_dataset(DATASET, config, split="full", revision=revision, cache_dir=str(cache))


def _verify_existing(out: Path, kind: str, revision: str, limit: int | None, top_k: int) -> dict | None:
    manifest = out / "data_manifest.json"
    if not manifest.is_file():
        return None
    doc = read_json(manifest)
    expected = {"kind": kind, "dataset": DATASET, "revision": revision, "limit": limit, "top_k": top_k}
    if any(doc.get(key) != value for key, value in expected.items()):
        raise ValueError("existing LitSearch download has different settings; use a new --out directory")
    for name, digest in doc["sha256"].items():
        if not (out / name).is_file() or _sha(out / name) != digest:
            raise ValueError(f"frozen LitSearch file changed: {name}")
    return doc


def _tokenizer(out: Path):
    import nltk
    nltk_dir = out / ".cache" / "nltk_data"
    nltk_dir.mkdir(parents=True, exist_ok=True)
    nltk.data.path.insert(0, str(nltk_dir))
    resources = [("punkt", "tokenizers/punkt"), ("stopwords", "corpora/stopwords")]
    if tuple(int(part) for part in nltk.__version__.split(".")[:2]) >= (3, 9):
        resources.append(("punkt_tab", "tokenizers/punkt_tab"))
    for resource, probe in resources:
        try:
            nltk.data.find(probe)
        except LookupError:
            if not nltk.download(resource, download_dir=str(nltk_dir), quiet=True):
                raise RuntimeError(f"NLTK resource download failed: {resource}")
    stop = set(nltk.corpus.stopwords.words("english"))
    stem = nltk.stem.PorterStemmer().stem
    return lambda value: [stem(token) for token in nltk.word_tokenize(value.lower()) if token not in stop]


def bm25_top_k(tasks: list[dict], corpus: list[dict], out: Path, top_k: int = 100) -> list[dict]:
    """Match LitSearch's title/abstract text, NLTK preprocessing, BM25Okapi, and NumPy ordering."""
    import numpy as np
    from rank_bm25 import BM25Okapi
    tokenize = _tokenizer(out)
    # The official index uses text as a dict key; duplicate text keeps its final corpus ID.
    pairs = {f"Title: {paper['title']}\nAbstract: {paper['abstract']}": str(paper["corpusid"])
             for paper in corpus}
    ids, texts = list(pairs.values()), list(pairs)
    if len(ids) < top_k:
        raise ValueError(f"corpus has only {len(ids)} distinct title/abstract records")
    print(f"Tokenizing {len(texts)} LitSearch corpus papers...", flush=True)
    index = BM25Okapi([tokenize(text) for text in texts], k1=1.5, b=0.75, epsilon=0.25)
    result = []
    for number, task in enumerate(tasks, 1):
        scores = index.get_scores(tokenize(task["query"]))
        order = np.argsort(scores)[::-1][:top_k]
        result.append({**task, "bm25_top100": [ids[int(pos)] for pos in order]})
        if number % 20 == 0 or number == len(tasks):
            print(f"BM25: {number}/{len(tasks)} questions", flush=True)
    return result


def download(out: Path, *, kind: str, revision: str = DEFAULT_REVISION,
             limit: int | None = None, top_k: int = 100) -> dict:
    """kind=step0203 downloads queries; kind=step03 also downloads corpus and builds BM25."""
    if kind not in ("step0203", "step03"):
        raise ValueError("kind must be step0203 or step03")
    if top_k != 100:
        raise ValueError("current Step 3 contract requires exactly 100 BM25 candidates")
    out = Path(out)
    existing = _verify_existing(out, kind, revision, limit, top_k)
    if existing:
        return existing
    out.mkdir(parents=True, exist_ok=True)
    pinned = _revision(revision)
    print(f"Downloading {DATASET} query at {pinned}...", flush=True)
    queries = [dict(row) for row in _load("query", pinned, out / ".cache" / "hf")]
    tasks = normalize_queries(queries, limit)
    _write_jsonl(out / "queries.jsonl", queries)
    files = ["queries.jsonl"]
    corpus_count = None
    if kind == "step03":
        print("Downloading corpus_clean (the official Parquet includes full text)...", flush=True)
        corpus = [{key: row[key] for key in ("corpusid", "title", "abstract")}
                  for row in _load("corpus_clean", pinned, out / ".cache" / "hf")]
        corpus_count = len(corpus)
        if not corpus:
            raise ValueError("official corpus_clean is empty")
        _write_jsonl(out / "corpus_title_abstract.jsonl", corpus)
        files.append("corpus_title_abstract.jsonl")
        tasks = bm25_top_k(tasks, corpus, out, top_k)
    _write_jsonl(out / "tasks.jsonl", tasks)
    files.append("tasks.jsonl")
    manifest = {"schema": "litsearch-download/1", "kind": kind, "dataset": DATASET,
                "revision": revision, "resolved_revision": pinned, "limit": limit, "top_k": top_k,
                "query_count": len(queries), "task_count": len(tasks), "corpus_count": corpus_count,
                "bm25": {"text": "Title: {title}\\nAbstract: {abstract}", "tokenizer": "NLTK word_tokenize, English stopwords, PorterStemmer",
                         "method": "rank_bm25.BM25Okapi", "k1": 1.5, "b": 0.75, "epsilon": 0.25,
                         "sort": "numpy.argsort(scores)[::-1]"} if kind == "step03" else None,
                "sha256": {name: _sha(out / name) for name in files}}
    write_json(out / "data_manifest.json", manifest)
    return manifest
