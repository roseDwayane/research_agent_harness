# A4 export — name the papers

**Export** is the last phase of the literature search ([README.md](README.md)), run once on the **final** shortlist —
after A5 and A3's screening of its additions. It decides what each paper is called from now on and what its reference
entry says.

| Unit | Decides | Writes (through the tool only) |
|---|---|---|
| [A4.k keys](#a4k) | nothing by judgement — it names each shortlisted paper, for good | `step4_citation_keys.jsonl`, `step4_citation_keys.md`, `citation_key` in `step3_shortlist.json` |
| [A4.b bibliography](#a4b) | nothing by judgement — it completes each entry from Crossref | `step4_references.bib`, `step4_bib_metadata.json` |

The key names every PDF (`pdfs/<key>.pdf`), every full text (`step5_full_text/<key>.md`), every citation in the
ideation documents and the writeup's `.bib`. A key that changed would silently re-point every file named after it —
so a key is minted once and never changes.

---

<a id="a4k"></a>
## A4.k — citation keys

### Purpose
Give every shortlisted paper one citation key for good, minted from its most complete author list.

### Inputs
`step3_shortlist.json` (A3 passes), `step3_bibliometrics.json` (`authors_full`), `step4_citation_keys.jsonl`, and A5's
check (A5 passes).

### Method

1. **Scheme**: one author `zhang2024`, two `xiazhang2024`, three or more `bouzeniaetal2025`; no year → `…nd`. Lower case
   on purpose: the writeup's `bib_tools.py` lower-cases every key it caches, so mixed-case keys would stop matching the
   keys cited in the ideation documents.
2. **From the most complete author list**: the longer of the search record's list and OpenAlex's authorships (A3.b).
   Some sources name only the first author (Scopus's standard view), which would key a five-author paper `smith2020`;
   the log records which list was used (`authors_basis`, `n_authors`).
3. **Append-only.** `step4_citation_keys.jsonl` holds one line per minted key. A paper keeps its first key; a collision
   takes the next unused suffix (`…a`, `…b`); a key whose paper left the shortlist is **retired** — listed in
   `step4_citation_keys.md` and never handed out again.
4. **Projection.** The shortlist's `citation_key` is copied from the log on every `export`; it is never edited by hand.
   A re-run mints only for papers the log does not hold.

Cite papers downstream as `(Author et al., Year) [citation_key]`: a shortlist routinely holds two different
"Zhang et al., 2025", and only the key says which one supports a claim.

### Outputs
`step4_citation_keys.jsonl` (`{id, key, at, authors_basis, n_authors}` per minted key), `step4_citation_keys.md`
(active and retired keys), `citation_key` on every shortlisted paper with authors and a title.

### Done when
`a4-check --unit A4.k` passes (K01–K05): every shortlisted paper with authors and a title has a key; no key changed or
is held by two papers; keys are lower-case author + year (or `nd`) + optional suffix; the shortlist equals the log.

### When something fails
A paper with no authors and no title on record gets no key (listed). No OpenAlex authorships: the search record's
authors (`authors_basis: search`). `export` refuses before A3 and A5 pass; `export --no-snowball "<reason>"` mints keys
on a shortlist without the snowball and writes the reason into `step4_citation_keys.md` — for a deliberate early
hand-off only.

### Commands
```bash
SK=.claude/skills/ai-scientist-ideate; PY=<interpreter with mcp>; RD=<topic>_research
$PY $SK/scripts/ideate_tools.py export $RD [--no-snowball "<reason>"]
```

---

<a id="a4b"></a>
## A4.b — bibliography

### Purpose
Write one complete BibTeX entry per active key, so the writeup starts from a ready `.bib` instead of repeating the
literature search.

### Inputs
`step4_citation_keys.jsonl`, `step3_shortlist.json`, `step3_bibliometrics.json` (`authors_full`).

### Method
1. **Crossref by DOI**, 40 DOIs per request, recorded under `_state/net/http/`: entry type (`journal-article` →
   `@article`, `proceedings-article` → `@inproceedings`, `posted-content` → `@misc`, book chapters, books, theses,
   reports), authors as `Family, Given`, venue, volume, issue, pages, year, DOI.
2. **Otherwise the search record**, with the same author list A4.k used — for a paper without a DOI, one Crossref does
   not know, a failed batch, or `--offline`.
3. `step4_bib_metadata.json` says per key where the entry came from and why (`no DOI`, `not in Crossref`, `offline`),
   and records the hashes of the key log and the shortlist it was built on.

### Outputs
`step4_references.bib`, `step4_bib_metadata.json` (schema `ideate-bib/1`). The writeup seeds its citation cache from
`step4_references.bib` through the run's `ideation_source.json`.

### Done when
`a4-check --unit A4.b` passes (L01–L04): one entry per active key and no other; the metadata describes exactly the
active keys; built on the current keys and shortlist (a later `export` makes it stale); an offline build is a warning.

### When something fails
Crossref unreachable or rate-limited: those papers keep their search-record entry (`crossref_failed_batches`).
`bibliography` refuses before A4.k passes.

### Commands
```bash
$PY $SK/scripts/mcp_bridge.py bibliography $RD [--offline]
$PY $SK/scripts/ideate_tools.py a4-check $RD             # every A4 check; exit 1 on an ERROR
```

No inventory or CSV is written here; that is `/ai-scientist-ideate-report`'s job.
