# Hypothesis specification — generation 1 (GAP_001, angle: retrieval side: query formulation under a matched result budget)

## Selected gap summary
GAP_001 · methodological / measurement · move `cause` · priority 4.30. Live scholarly search is reported to "perform poorly" on natural-language literature questions (Ajith et al., 2024) [ajithetal2024], but the engines received the question verbatim, once (ajithetal2024#E2). Exposure is the largest observed loss for search agents and its attribution is said to need intervention (Ding et al., 2026) [dingetal2026a]. Nobody has varied the query form with the budget held equal.

## Research questions
- **RQ1** Does an LLM-written query set add at least 0.10 set recall on a keyword scholarly-search API beyond a deterministic keyword query set at a matched result budget?
- RQ2 How much of the gap between the verbatim question and an LLM-written query set does the deterministic keyword query set already close?
- RQ3 How does set recall change with the number of keywords per query and the number of queries?
- RQ4 How large is the run-to-run spread of the LLM arm and of the API, compared with the difference in RQ1?

## Hypotheses
**H1 (primary; mode: test).** Although the recall gain of LLM-written queries over the verbatim question could come from shortening alone, an LLM-written query set exceeds a deterministic keyword query set by at least 0.10 set recall at a matched result budget, because the LLM supplies terms that are not in the question.
- H0: Δ = mean over questions of (h_LLM − h_DET) < 0.10.
- Expected direction and basis: LLM ≥ DET. Basis **contested**: LLM-written expansions are reported to improve sparse retrieval (Wang et al., 2023) [wangetal2023] (abstract; closed corpus, one expanded query), which predicts a positive increment; the conjunctive-matching account — a long question over-constrains a keyword API, so any shortening recovers the loss — predicts an increment near zero. No shortlisted paper measures it.
- Smallest effect of interest: 0.10 absolute set recall — a design choice: an increment below ten questions in a hundred would not justify an LLM call and its nondeterminism in a pipeline stage that can otherwise be pure code. It is not a literature value. (The topic file's own preliminary numbers motivated the question; they are not used as an expected magnitude.)
- Test: paired bootstrap over questions (10,000 resamples), one-sided at α = 0.05, i.e. the limits of the two-sided 90% interval of Δ.
- Decision rule (E2): **supported** if the lower limit ≥ 0.10; **refuted** if the upper limit < 0.10; otherwise undecided. Against the threshold, at 80% power a true increment is separated from 0.10 when it differs by at least 2.49 × SD / √550 — 0.064 at SD 0.6 — so increments up to about 0.04 are refuted, from about 0.16 supported, and between them the design returns undecided (revised in round 2 after the reader's doubt 1).
- Power: `power --mode paired --n 550 --sided 1` → d ≥ 0.11 SD at 80% power; with `--effect 0.10`, detectable only if the SD of the paired difference is at most 0.94. A difference of two 0/1 outcomes has SD ≤ 1 and is below 0.94 unless nearly every question is discordant, so the design can detect 0.10. Literature effect: (TBD) → verdict **marginal** by rule.

**H2 (secondary; mode: estimate; `size-open`).** The gain in set recall of the deterministic keyword query set over the verbatim question, with its 95% interval. The direction follows from conjunctive matching (screen 2); only the size is open.

**H3 (secondary; mode: estimate; `descriptive`).** Set recall as a function of keywords per query (m = 2..6) and of the number of queries (K = 1, 2, 5), per arm.

**H4 (secondary; mode: estimate; `descriptive`).** The spread of the LLM arm's set recall over 3 sampling seeds, and of every arm over two API dates, to be compared with Δ.

## Claims set aside at B4
- *"A deterministic keyword query beats the verbatim question" as a test* — set aside by the derivability screen (direction follows from conjunctive matching). Kept as estimate H2 (`size-open`). The reader loses a pass/fail statement on it and gets an interval.
- *The LLM arm run with the harness's own generator (`qwen3.8` under Ollama)* — set aside for data: no Ollama and no such model on this machine (probe). The LLM arm uses a small open instruct model with the harness's Step 1 prompt, verbatim. The reader loses a direct statement about the deployed generator; E5 accepts recorded Step 1 query sets if they are supplied.
- *Ranked metrics (Recall@5, MRR) after Step 3 screening* — set aside: they need an LLM relevance scorer per candidate and belong to the ranking side, not to this angle.

## Operational definitions
As in `step7b_problem.md` section 8: query set, set recall (per question 0/1, any gold in the union), result budget (K = 5 queries × R = 25 results; the verbatim arm reads its first 125 results), keyword scholarly-search API (OpenAlex `works?search=`), deterministic keyword query (the question's own words, stop words removed, ranked by inverse document frequency over the LitSearch corpus titles and abstracts; with w1..w6 the six highest-ranked words, the five queries are {w1 w2 w3}, {w1 w2 w3 w4}, {w1 w2 w4}, {w1 w3 w5}, {w2 w3 w6}, each in question order — non-nested since round 2; the nested top-m rule is a descriptive arm of E4).

## Scope
| IN | |
|---|---|
| Data | LitSearch, 597 questions with gold S2ORC ids [ajithetal2024]; questions whose gold cannot be resolved to an OpenAlex work are reported and excluded. Second set: TREC-COVID topics (50; question, human keyword query, relevance judgments). |
| Methods compared | VERB (question as typed), DET (5 deterministic non-nested keyword queries), LLM (5 queries from the harness's `s1_init` prompt, small open instruct model, greedy decoding) |
| Comparison | paired per question, same K and R |
| Primary outcome | Δ set recall, LLM − DET |
| Secondary | DET − VERB; recall by m and K; spread over seeds and dates; overlap of result sets; loss funnel (not indexed / not returned) |
| Setting | laptop, CPU / MPS; OpenAlex keyless API with a content-addressed response cache |
| Design | within-question comparison of query-construction methods; controls: oracle title query, mismatched-question keywords |
| Timeframe | no year filter (gold papers may be old) |

Licence line: LitSearch — no human subjects; (licence unverified). TREC-COVID — no human subjects; (licence unverified).

| OUT | Why |
|---|---|
| Dense retrievers and rerankers | closed-corpus methods already compared in [ajithetal2024]; the question is about the query sent to a keyword API |
| Google Scholar, Elicit | no API; manual probing is not reproducible |
| Judge-accepted alternatives to the gold | needs an LLM judge validated against humans [sharonhope2026]; single-gold bias affects all arms alike within a question |
| Steps 3-9 of the harness | another angle |

## Conceptual framework
```
question x_q ──► f_VERB ─► 1 query ──┐
            ──► f_DET  ─► 5 queries ─┼─► OpenAlex search (R per query; 125 total) ─► S_q ─► h_q = 1[G_q ∩ S_q ≠ ∅]
            ──► f_LLM  ─► 5 queries ─┘                                                    Δ = mean_q(h_LLM − h_DET)
controls:  oracle title of the gold ─► ceiling of h      |   keywords of another question ─► floor of h
```

## Risk assessment
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The small local model writes poor or malformed queries, so the LLM arm understates what an LLM adds | Medium | High | Structured output with the harness schema; report parse failures as zeros and separately; E5 accepts recorded query sets from the deployed generator |
| OpenAlex does not index some gold papers | Medium | Medium | Oracle title query (E1) gives the ceiling; excluded questions reported |
| API results drift between dates | Medium | Low | Response cache; E5 re-queries a subset on a second date |
| LitSearch questions or papers are in the model's training data | Medium | Medium | Stratify by inline-citation vs author-written questions; cannot be removed |
| Rate limits | Low | Low | Polite pool, cache, about 10^4 calls in total (estimated) |

## Rival explanations
| Explanation | How it would arise here | Ruled out by | Main? |
|---|---|---|---|
| Confounding by budget | more queries or more results return more papers, so recall rises whatever the wording | design: K and R equal in every arm; E3 mismatched-question keywords with the same K and R | **main** |
| Query diversity | five free LLM queries return more varied results than five queries from one word list | E4: unique results per arm; Δ among questions with matched diversity | |
| Chance | 0/1 outcome per question | paired bootstrap interval in E2 | |
| Incorporation | DET queries are subsets of the question's words and the LLM may copy the same words, so the two arms can issue the same queries and Δ is zero on those questions by construction | design: the queries are the manipulation; E4 reports the share of questions with identical result sets and Δ outside them | |
| Leakage | the model has seen the gold paper and writes its title words | (not addressed) — stratified report only | |
| Selection | dropping questions whose gold is not in OpenAlex keeps the easier ones | E1 reports the dropped share and their composition | |
| Bias in the gold | unlabelled relevant papers count as misses [sharonhope2026] | (not addressed) — affects all arms within a question alike | |

## By-construction check (H1)
1. Predictor: `u_qk = f_arm(x_q), k = 1..K` — the K query strings that method `arm` builds from question `x_q`. Outcome: `h_q = 1[G_q ∩ ⋃_k A(u_qk, R) ≠ ∅]`, `Δ = mean_q(h_q^LLM − h_q^DET)`, where `A(u, R)` is the API's first R results for string u and `G_q` the gold set.
2. Shared terms: `u_qk` (the queries are the manipulation and enter the outcome through the API — the causal path under test), `x_q`, `f_arm`. No term of the gold enters the predictor.
3. Substitution: `h_q = 1[G_q ∩ ⋃_k A(f_arm(x_q), R) ≠ ∅]`. `A(·)` is an external service and `f_LLM` a model: neither can be evaluated from existing tables. Computable without the experiment: **no** — `u_qk` and `x_q` stay inside `A(·)`, whose response is the free quantity.
4. Could each result come out otherwise? E2: the manipulation acts on the query strings; the measure is computed on API results for those strings; Δ can be negative, zero or positive → can fail. E6 is descriptive. Free quantity: which documents the API returns for each string, and which words the gold paper's metadata contains.
5. Controls through the statistic (`h` is a 0/1 indicator, the mean is taken with its sign; no absolute value, rank or clip): positive control — the gold's exact title as the query returns h = 1 whenever the work is indexed and the title search ranks it within R; expected mean ≥ 0.95 on resolved questions, and it is the ceiling for every arm. Negative control — DET keywords of another question, same K and R, in two versions (another LitSearch question: same field, conservative floor; a TREC-COVID topic: unrelated field, clean floor): expected mean h close to 0 for the unrelated-field version (a hit needs the gold of q among results for an unrelated question); the value is reported, and a value above 0.05 means budget alone produces hits. Noise term: the bootstrap resamples questions, which carry the same API date and budget in both arms.
6. Existing predictor: the deterministic keyword query set is the cheaper existing route; the decision rule is the increment over it, not over the verbatim question.

## External check
Evidence is from real questions and a real index, not simulated. One dataset carries the primary hypothesis (LitSearch) → **E6** repeats the contrast on TREC-COVID (biomedical, multi-gold, human keyword query available). Inventory of the disk: `~/mne_data`: EEG recordings, no text retrieval data; `~/.cache/huggingface/hub`: speech and EEG models only, no instruct LLM and no dataset; `~/.cache/torch`: hub checkpoints only; `$RD/datasets/`: does not exist. Both sets must be downloaded.

## Traceability
| Element | Source | Evidence |
|---|---|---|
| RQ1 | GAP_001 | ajithetal2024#E2 (verbatim, one query); dingetal2026a#E1 (no intervention) |
| H1 direction | contested | [wangetal2023] vs conjunctive-matching account |
| H1 threshold 0.10 | design choice | this file |
| LitSearch, Recall protocol | field convention | ajithetal2024#E1 |
| E0 | instrument | data, id mapping, cache, fixed rules |
| E1 | control for H1 (positive) | oracle title |
| E2 | tests H1 (deciding) | Δ, paired bootstrap |
| E3 | control for H1 (negative, main rival) | mismatched keywords |
| E4 | descriptive: H2, H3 | DET − VERB; m and K curves; overlap; funnel |
| E5 | descriptive: H4 | seeds, dates, a second larger open model on a subset, recorded query sets |
| E6 | descriptive: H1 on a second set | TREC-COVID has many relevant documents per topic, so the outcome there is the per-topic share of judged-relevant documents returned within the budget; the paired LLM − DET difference is reported with its interval and its sign compared with E2; no pass/fail rule, because the 0.10 threshold is defined on a 0/1 outcome and does not carry over |
| Scope of H1 | LitSearch questions, OpenAlex, one small model | E0-E2 |
Path to the number: API result ids per query → union per question and arm → h_q (0/1) → per-question difference → mean over questions → bootstrap limits.
