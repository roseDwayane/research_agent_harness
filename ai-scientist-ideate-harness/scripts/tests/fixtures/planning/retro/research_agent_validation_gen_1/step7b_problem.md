---
topic: "Stage-wise validation of an LLM literature-research agent"   generation: 1   gap: GAP_001   angle: "retrieval side: query formulation under a matched result budget"   date: 2026-10-06
move: cause
study: analytic
---
# Problem and question — low recall of live scholarly search is blamed on the engine although the query form and the budget were never separated from it

## 1. Common ground
Literature-search systems are compared by recall against annotated target papers, and on that score live search engines are held to do poorly on natural-language literature questions: typed in as they are, 80 LitSearch questions give Recall@5 of 17.5-62.5 against 74.8 for a dense retriever (Ajith et al., 2024) [ajithetal2024]. LLM-written query expansions are held to help retrieval (Wang et al., 2023) [wangetal2023].

## 2. Condition
Move `cause`: the low score is attributed to the engine, but in the source the engine received the question verbatim, once, and five results were read (ajithetal2024#E2). Query form, number of queries and number of results were never varied, so the comparison cannot say whether the engine, the wording or the budget produces the score. The one paper that locates the loss — exposure, zero-exposure 17.4-56.1% (dingetal2026a#E1) — calls its funnel descriptive. Nearest reported number for a query-form effect on a keyword scholarly API: (no reported number: this is an absence within a contradiction).

## 3. Consequence — So-what ladder
Q1 Does an LLM-written query set add at least 0.10 set recall on a keyword scholarly API beyond a deterministic keyword query set with the same number of queries and results?
  → because Q1 is unanswered, Q2 cannot be answered: is the exposure loss of literature agents a property of the search backend or of the queries the agent writes?   evidence: [dingetal2026a] states that causal attribution of its funnel needs intervention; D_draft_WhatCountsAsFound (open debate).
  → Q3: which stage of a literature agent should be changed first to raise what it finds?   evidence: (TBD) — only this study's reading of the two papers above.

## 4. Three-step sentence
I am studying query formulation for keyword scholarly-search APIs because I want to find out how much of the recall gain of LLM-written queries over the verbatim question remains once a deterministic keyword query set is given the same result budget, in order to help readers who evaluate literature agents understand whether low recall is a property of the backend or of the queries.

## 5. Research question
Does an LLM-written query set add at least 0.10 set recall on a keyword scholarly-search API beyond a deterministic keyword query set at a matched result budget?
(A *whether* question. Yes: the first stage of a literature agent needs the model and cannot become pure code without losing recall. No: the gain attributed to LLM query generation is mostly reproduced by a keyword rule, and verbatim probes of keyword search understate it.)

## 6. Screens
| Screen | Result | Basis |
|---|---|---|
| Is the answer already settled in the literature? | no | `raw` lookup (358 records): "keyword query" 3, "query formulation" 1, "search string" 1, "openalex" 0, "query length" 0, "budget retrieval query" 0 — none compares query forms on a scholarly API. Matrix rows whose `claim_tested` bears on it: ajithetal2024#E2 (engines, verbatim only), dingetal2026a#E1 (agents, no query intervention). LLM expansion vs a raw query is tested only on closed corpora [wangetal2023] (abstract). |
| Can the answer be derived from textbook knowledge, the definitions involved or a few lines of algebra? | partly | If the API matches all query terms, a long question matches fewer documents than a subset of its words, so verbatim ≤ keyword subset in candidates returned: the direction of *verbatim vs keyword* is derivable. Whether an LLM adds anything beyond the question's own words depends on which terms the gold paper's title and abstract contain — not derivable. The derivable part is kept as an estimate (C2), never the primary claim. |
| Could data on this machine settle it? | yes | LitSearch questions and gold ids (public download; not cached — probe lists no Hugging Face dataset cache); OpenAlex API (keyless); `requests`, `pandas`, `scikit-learn`, `torch`, `transformers` installed per probe; a small instruct model must be downloaded (probe: no LLM cached, no Ollama). |
| Does the answer feed a larger question that someone other than you has asked? | yes | Q2: the intervention [dingetal2026a] says its funnel needs; the open debate D_draft_WhatCountsAsFound. |

## 7. Key terms
query set · set recall · result budget · keyword scholarly-search API · deterministic keyword query

## 8. Definitions
- **Query set**: the K query strings issued for one question by one method. Other usage: a single expanded query [wangetal2023]. This one because literature agents issue several queries per need.
- **Set recall**: for one question, 1 if at least one annotated gold paper is in the union of results of its query set, else 0; averaged over questions. Other definitions: Recall@k over a ranked list [ajithetal2024]; graded gain [dingetal2026a]. This one because Step 2 of the harness produces an unranked set.
- **Result budget**: K queries × R results per query, the same K and R for every method; the verbatim arm reads the first K × R results of its single query.
- **Keyword scholarly-search API**: OpenAlex `works?search=` over title, abstract and full text where available; relevance-ranked, term matching as the service implements it (measured in E1, not assumed).
- **Deterministic keyword query**: a query built from the question's own words by a fixed rule (stop-word removal, inverse-document-frequency ranking over the LitSearch corpus, then five fixed 3- or 4-word combinations of the six highest-ranked words), with no model and no randomness.
