---
session_id: "20261026"
topic: "EEG neurofeedback for mild cognitive impairment (MCI)"
date: "2026-10-26"
step: 6
total_papers: 15
themes: 4
full_text_papers: 14
abstract_only_papers: 1
---

# State-of-the-Art Review

> Topic: EEG neurofeedback for mild cognitive impairment (MCI)
> Papers synthesized: 15
> Themes identified: 4
> Date: 2026-10-26

## Executive Summary

EEG neurofeedback (NF) for mild cognitive impairment (MCI) is a small but growing field whose evidence base consists mainly of pilot studies, a handful of controlled trials and several reviews. Controlled studies report domain-specific benefits — memory after individual upper-alpha upregulation versus sham (LavyEtAl2021) and sustained attention and spatial working memory after game-based beta/alpha NF versus exergame and care as usual (JirayucharoensakEtAl2019) — while uncontrolled pilots report broad gains in MoCA and memory (MarlatsEtAl2020; JangEtAl2019; SuEtAl2025). Reviews converge that results are promising but inconclusive because RCTs are scarce, sham controls and blinding are rare and protocols are heterogeneous (TrambaiolliEtAl2021; TsaiEtAl2025; Tazaki2024). A key unresolved problem is the dissociation between behavioural gains and change in the trained EEG feature (LavyEtAl2021; PabanEtAl2024), compounded by high non-responder rates in older adults (MarcosMartinezEtAl2026; JiangEtAl2022). The field is moving towards personalized, AI-supervised and network-level protocols (RogalaEtAl2026; SuEtAl2025; PabanEtAl2024), but no adequately powered, sham-controlled RCT in MCI with mechanistic EEG endpoints and long-term follow-up exists in this collection.

## Methodology Legend

| Color | Methodology | Count |
|-------------|---------------------|-------------|
| 🔴 Red | Experimental | 9 |
| 🟠 Orange | Computational | 0 |
| 🟡 Yellow | Review | 6 |
| 🟢 Green | Observational | 0 |
| 🔵 Cyan | Engineering | 0 |
| 🟣 Purple | Theoretical | 0 |

---

## Theme 1: Controlled efficacy trials of EEG neurofeedback in MCI

**Papers:** JirayucharoensakEtAl2019, LavyEtAl2021, MarlatsEtAl2019

### Consensus

Controlled designs show benefits that are domain-specific rather than global. Individual upper-alpha (PAF to PAF+2 Hz) training at Pz improved composite memory versus sham (89.76 to 101.25, p=0.003), and only memory survived Bonferroni correction (LavyEtAl2021). Game-based beta/alpha NF improved sustained attention (RVP A' F=45.02, p<0.001) and spatial working memory versus exergame and CAU, but not pattern-recognition memory (JirayucharoensakEtAl2019). Both trials report that effects are specific to particular domains rather than general cognition.

### Debates

Which cognitive domain responds is protocol-dependent: memory with posterior upper-alpha training (LavyEtAl2021) versus attention and executive function with frontal beta/alpha training, with no effect on aMCI memory hallmarks (JirayucharoensakEtAl2019). This supports the hypothesis that frontal beta1/theta targets attention while central SMR/delta targets memory (MarlatsEtAl2019), which remains untested. The appropriate control is also debated: sham with genuine feedback from random sites (LavyEtAl2021) versus active alternatives such as exergame (JirayucharoensakEtAl2019) or video-based psycho-pedagogy (MarlatsEtAl2019).

### Dominant Methods

Small parallel-group trials (n of about 30 to 119) with 10 to 30 sessions; computerized batteries (NeuroTrax, CANTAB) or TMT-B as primary outcome; short follow-up (30 days at most in completed trials) (LavyEtAl2021; JirayucharoensakEtAl2019). Planned trials add power calculations (n=60 for 80% power) and 3-month follow-up (MarlatsEtAl2019).

### Key Results

| Study | N | Method | Primary Outcome | Result |
|---|---|---|---|---|
| LavyEtAl2021 | 30 MCI | Upper-alpha NF vs sham RCT, 10 sessions | NeuroTrax composite memory | 89.76 to 101.25 (p=0.003); sham n.s.; maintained at 30 days; no PAF change |
| JirayucharoensakEtAl2019 | 119 (65 aMCI) | Game-based beta/alpha NF vs exergame vs CAU, 20 sessions | CANTAB | RVP A' F=45.02 p<0.001; SWM strategy F=8.53 p=0.004; no PRM/DMS effect |
| MarlatsEtAl2019 | planned 60 MCI | SMR/delta vs beta1/theta vs control (protocol) | TMT-B | No results (NCT03526692) |

---

## Theme 2: Uncontrolled pilots and neural mechanisms of NF in MCI

**Papers:** SuEtAl2025, MarlatsEtAl2020, JangEtAl2019

### Consensus

Single-arm studies consistently report improved global cognition after NF in MCI: MoCA F=4.78, p=0.012 after SMR/theta training (MarlatsEtAl2020); MoCA-K 19.4 to 25.6 after frontal beta enhancement (JangEtAl2019); short-term MoCA improvement in 92.9% after game-based NFT (SuEtAl2025). All three also report EEG change — increased resting theta and alpha power (MarlatsEtAl2020), session-wise beta increase r=0.746 (JangEtAl2019) and band-specific connectivity reorganization (SuEtAl2025).

### Debates

The direction of EEG change is inconsistent with the slowing model of MCI: resting theta rose although theta was inhibited (MarlatsEtAl2020), and delta connectivity rose while faster bands declined (SuEtAl2025). Whether this reflects beneficial reorganization (SuEtAl2025) or non-specific effects is unresolved. Effect robustness is contested: MoCA-K post-hoc tests did not survive Bonferroni correction (JangEtAl2019), and graph metrics were not significant (SuEtAl2025).

### Dominant Methods

Open-label pre/post designs (n=5 to 28) with 10 to 20 sessions, single-channel or few-channel feedback (Cz, F6), and 16- to 19-channel resting EEG with spectral (MarlatsEtAl2020) or graph-theoretic and dynamic connectivity analysis (SuEtAl2025); occasional fNIRS (JangEtAl2019).

### Key Results

| Study | N | Method | Primary Outcome | Result |
|---|---|---|---|---|
| MarlatsEtAl2020 | 20 MCI | SMR up / theta & high-beta down at Cz, 20 sessions | MoCA, RAVLT | MoCA F=4.78 p=0.012; RAVLT delayed F=3.675 p=0.032; theta and alpha power up |
| JangEtAl2019 | 5 MCI | Beta (12-15 Hz) up at F6, 16 sessions | MoCA-K | 19.4 to 25.6 (Friedman p=0.016; post-hoc n.s.) |
| SuEtAl2025 | 28 aMCI | Game NFT, 10 days | MoCA, EEG networks | MoCA improved in 92.9%; delta connectivity up, beta down; graph metrics n.s. |

---

## Theme 3: Evidence syntheses and methodological quality

**Papers:** TrambaiolliEtAl2021, Tazaki2024, TsaiEtAl2025, VilouEtAl2023, GkintoniEtAl2025

### Consensus

All reviews conclude that NF is promising but not established. Most included studies report improvement on some cognitive test (TrambaiolliEtAl2021; Tazaki2024; VilouEtAl2023), yet RCT data are scarce and evidence is inconclusive (TrambaiolliEtAl2021: 10 studies, 208 experimental vs 81 control participants), and successful trials are biased by randomization and outcome measurement (TsaiEtAl2025: 16 studies). Placebo control is rarely attempted (Tazaki2024; TsaiEtAl2025).

### Debates

Narrative reviews stress that protocol choice and session number do not appear to limit effectiveness (VilouEtAl2023), whereas systematic reviews attribute positive findings to design bias (TsaiEtAl2025; TrambaiolliEtAl2021). Broad neurotechnology reviews rank cognitive training and neuromodulation (tDCS 62%, TMS 58% response) above EEG NF, positioning EEG mainly as a biomarker tool (GkintoniEtAl2025).

### Dominant Methods

Two PRISMA systematic reviews with risk-of-bias or reporting-quality appraisal (TrambaiolliEtAl2021; TsaiEtAl2025), one broad PRISMA review of 34 studies (GkintoniEtAl2025) and narrative reviews (Tazaki2024; VilouEtAl2023). No meta-analysis of EEG NF in MCI exists in this collection.

### Key Results

TrambaiolliEtAl2021: 10/1,912 studies included; 4 of 10 lacked baseline screening scores; 1 reported AD biomarkers. TsaiEtAl2025: 16 studies (2010-2024), several without control groups. Tazaki2024: 13 studies since 2016, uniformly positive. VilouEtAl2023: gains maintained at 30 days in some studies. GkintoniEtAl2025: EEG-based SVM predicted dementia conversion with 81% sensitivity and 79% specificity.

---

## Theme 4: Self-regulation, non-responders and personalized protocols

**Papers:** JiangEtAl2022, RogalaEtAl2026, MarcosMartinezEtAl2026, PabanEtAl2024

### Consensus

A large share of older adults fail to learn EEG self-regulation: 48.3% non-responders in motor-imagery NF (MarcosMartinezEtAl2026), a distinct non-learner group needing about 5 more sessions (PabanEtAl2024), and non-response ('BCI illiteracy') as a recognised problem (JiangEtAl2022). Personalization is proposed as the remedy (PabanEtAl2024; RogalaEtAl2026; JiangEtAl2022).

### Debates

Evidence on personalization conflicts: individualized protocols were no better than standard PAF training and modulation was not frequency-specific (PabanEtAl2024), whereas DNN-personalized NF outperformed sham on reasoning (each p<.03) (RogalaEtAl2026, abstract-only). Rigorous double-blind trials in healthy older adults found no NF-specific cognitive benefit (MarcosMartinezEtAl2026), contrasting with mostly positive reports (JiangEtAl2022).

### Dominant Methods

Double-blind, placebo-controlled RCTs (MarcosMartinezEtAl2026), learning-criterion designs with transfer runs (PabanEtAl2024), DNN-supervised closed loops (RogalaEtAl2026), and k-means classification of responders with baseline EEG predictors such as resting beta1 power and alpha node strength (MarcosMartinezEtAl2026).

### Key Results

| Study | N | Method | Primary Outcome | Result |
|---|---|---|---|---|
| MarcosMartinezEtAl2026 | 92 healthy 65-75 | MI-NF vs placebo vs cognitive stimulation | Neuropsychological battery | No NF-specific benefit; 48.3% non-responders |
| PabanEtAl2024 | 36 SCD | Individualized vs standard PAF NF | EEG and questionnaires | About 16% target amplitude gain in learners, not band-specific; no questionnaire effect |
| RogalaEtAl2026 | 57 healthy 41-64 | DNN-personalized NF vs sham | Reasoning task | Training > sham on all conditions (p<.03) |

---

## Cross-Theme Analysis

### Methodological Trends Over Time

2019-2021 work used single-site pilots and small trials with classic band protocols (beta, SMR/theta, upper alpha) (JangEtAl2019; MarlatsEtAl2020; LavyEtAl2021; JirayucharoensakEtAl2019), followed by reviews highlighting bias (TrambaiolliEtAl2021; TsaiEtAl2025). Since 2024, studies shift towards learning criteria and non-responder analysis (PabanEtAl2024; MarcosMartinezEtAl2026), network-level outcomes (SuEtAl2025) and AI-personalized feedback (RogalaEtAl2026).

### Converging Findings

Studies converge on (i) domain-specific rather than global effects in controlled designs (LavyEtAl2021; JirayucharoensakEtAl2019), (ii) the scarcity of sham-controlled RCTs in MCI (TrambaiolliEtAl2021; TsaiEtAl2025; Tazaki2024), and (iii) high inter-individual variability in self-regulation ability (MarcosMartinezEtAl2026; PabanEtAl2024; JiangEtAl2022).

### Diverging Findings

Findings diverge on whether the trained EEG feature changes: no PAF or upper-alpha change despite memory gains (LavyEtAl2021) and no pre/post resting change (PabanEtAl2024), versus increased beta during sessions (JangEtAl2019) and resting theta/alpha increases (MarlatsEtAl2020). Uncontrolled pilots report broad MoCA gains (MarlatsEtAl2020; SuEtAl2025) while controlled healthy-aging trials find no specific benefit (MarcosMartinezEtAl2026).

### Theme Interactions

MarlatsEtAl2020 and MarlatsEtAl2019 bridge themes 1 and 2 (the pilot that informed the RCT protocol). TrambaiolliEtAl2021 and TsaiEtAl2025 appraise the trials of themes 1-2. PabanEtAl2024 links the self-regulation theme to the PAF/alpha protocols of LavyEtAl2021, providing a mechanistic explanation (non-specific modulation) for behaviour-EEG dissociation.

---

## Paper–Theme Mapping

| Citation Key | Theme | Methodology | Bridge? |
|----------------------|-------------|---------------------|------------------|
| `JirayucharoensakEtAl2019` | theme_1 | experimental | — |
| `LavyEtAl2021` | theme_1 | experimental | Yes |
| `TrambaiolliEtAl2021` | theme_3 | review | — |
| `Tazaki2024` | theme_3 | review | — |
| `SuEtAl2025` | theme_2 | experimental | — |
| `MarlatsEtAl2020` | theme_2 | experimental | Yes |
| `TsaiEtAl2025` | theme_3 | review | — |
| `JangEtAl2019` | theme_2 | experimental | — |
| `JiangEtAl2022` | theme_4 | review | — |
| `VilouEtAl2023` | theme_3 | review | — |
| `MarlatsEtAl2019` | theme_1 | experimental | Yes |
| `GkintoniEtAl2025` | theme_3 | review | — |
| `RogalaEtAl2026` | theme_4 | experimental | — |
| `MarcosMartinezEtAl2026` | theme_4 | experimental | — |
| `PabanEtAl2024` | theme_4 | experimental | Yes |

---

Files: `step6_sota_review.md`, `step6_knowledge_graph.canvas`
Next step: `/research-gaps`
