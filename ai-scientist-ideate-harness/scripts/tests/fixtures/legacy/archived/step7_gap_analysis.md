---
session_id: "20261026"
topic: "EEG neurofeedback for mild cognitive impairment (MCI)"
date: "2026-10-26"
step: 7
gaps_identified: 3
priority_weights: "severity=0.40, novelty=0.30, feasibility=0.30"
---

# Gap Analysis

> Topic: EEG neurofeedback for mild cognitive impairment (MCI)
> Papers analyzed: 15 (from SOTA review)
> Gaps identified: 3
> Date: 2026-10-26

## Executive Summary

The collection shows that EEG neurofeedback in MCI yields promising but fragile, domain-specific cognitive gains from small and mostly uncontrolled studies. Three gaps stand out: (1) responder prediction and personalization have been studied only in healthy, middle-aged or subjective-decline samples, never in MCI; (2) no sham-controlled MCI trial has shown that the trained EEG feature actually changes and mediates the cognitive benefit; and (3) no completed MCI trial follows patients beyond about one month or measures clinical progression.

---

## GAP_001: Baseline-EEG prediction of NF responders and responder-adaptive protocols untested in MCI

**Type:** population (integration)
**Priority Rank:** #1

### Description

Baseline resting-EEG predictors of self-regulation success (e.g., resting beta1 relative power and alpha node strength) and personalized/adaptive protocols have been studied only in healthy adults aged 41-75 and in subjective cognitive decline. No study has tested, in amnestic MCI, whether pre-registered baseline EEG markers predict who learns to modulate the target band, or whether responder status moderates cognitive benefit versus sham.

### Supporting Evidence

- **MarcosMartinezEtAl2026 (2026)**: 48.3% non-responders and baseline beta1 power / alpha node strength predicted self-regulation, but only in healthy 65-75 year olds; authors call for further biomarkers of non-responsiveness.

- **PabanEtAl2024 (2024)**: Identified a non-learner group needing about 5 more sessions and found individualized protocols no better than standard, in SCD rather than MCI.

- **JiangEtAl2022 (2022)**: Review names non-response ('BCI illiteracy') as a central unsolved issue and explicitly calls for NF research in MCI.

- **RogalaEtAl2026 (2026)**: DNN-personalized NF beat sham, but in healthy adults aged 41-64 (abstract-only).

### Counter-Evidence

- **JirayucharoensakEtAl2019 (2019)**: Used per-session calibration and adaptive thresholds in aMCI, but did not analyse responders or predictors of learning.

- **LavyEtAl2021 (2021)**: Individualized the band to each patient's PAF, yet reported no learning or responder analysis and no change in PAF.

### Why It Matters

If roughly half of older trainees fail to self-regulate, average-effect RCTs in MCI will be diluted and appear null; identifying responders from baseline EEG would allow enrichment, stratified trials and clinically targeted prescription of NF to the MCI patients most likely to benefit.

### Priority Score

| Axis | Score | Rationale |
|--------------|-------------|-----------------|
| Severity | 4 | Non-response plausibly explains inconsistent efficacy across trials, but it is not the sole barrier to establishing efficacy. |
| Novelty | 5 | No MCI study in the collection examines responder prediction or responder-moderated outcomes. |
| Feasibility | 4 | Requires only baseline resting EEG and session logs added to a standard NF trial; assumes MCI recruitment of about 60-90 patients at a memory clinic. |

**Composite:** 4 × 0.40 + 5 × 0.30 + 4 × 0.30 = 1.60 + 1.50 + 1.20 = **4.30**

---

## GAP_002: No sham-controlled MCI trial verifies target engagement of the trained EEG feature

**Type:** methodological (measurement)
**Priority Rank:** #2

### Description

Controlled MCI trials report cognitive benefit without showing that the trained EEG feature changed (no PAF or upper-alpha change after sham-controlled alpha NF) or without reporting EEG at all; no study tests whether within-session learning of the target band statistically mediates cognitive change versus sham.

### Supporting Evidence

- **LavyEtAl2021 (2021)**: Memory improved versus sham but PAF (9.32 to 9.36 Hz) and upper-alpha power did not change; authors note the study was underpowered for EEG.

- **JirayucharoensakEtAl2019 (2019)**: Reports CANTAB effects but no analysis of change in the trained beta/alpha ratio.

- **PabanEtAl2024 (2024)**: Learned modulation was not frequency-specific and resting EEG did not change, questioning the specificity assumed by protocols.

- **TrambaiolliEtAl2021 (2021)**: Calls for reporting self-regulation success and its link to clinical outcomes, which included studies rarely did.

### Counter-Evidence

- **JangEtAl2019 (2019)**: Showed session-wise beta increase (r=0.746) but in an uncontrolled n=5 pilot, so mediation versus sham cannot be tested.

- **MarlatsEtAl2020 (2020)**: Reported resting theta and alpha changes but no control group, and theta moved opposite to the trained direction.

### Why It Matters

Without target engagement, cognitive gains in MCI could be placebo or practice effects, undermining the mechanistic rationale of reversing EEG slowing.

### Priority Score

| Axis | Score | Rationale |
|--------------|-------------|-----------------|
| Severity | 5 | Attribution of effect to NF is the fundamental validity question for the whole field. |
| Novelty | 3 | Recognised in reviews but not yet addressed empirically in MCI; partially examined in other populations. |
| Feasibility | 4 | Standard EEG and mediation analysis; requires adequate sample size and a credible sham. |

**Composite:** 5 × 0.40 + 3 × 0.30 + 4 × 0.30 = 2.00 + 0.90 + 1.20 = **4.10**

---

## GAP_003: No long-term follow-up or clinical-progression outcomes after NF in MCI

**Type:** temporal
**Priority Rank:** #3

### Description

Completed MCI studies assess outcomes immediately after training or at about 30 days; none tracks cognition beyond 3 months or measures conversion to dementia, functional decline or biomarker trajectories after EEG NF.

### Supporting Evidence

- **LavyEtAl2021 (2021)**: Longest controlled follow-up is 30 days.

- **MarlatsEtAl2020 (2020)**: 1-month follow-up only; MoCA gains did not persist.

- **JirayucharoensakEtAl2019 (2019)**: No follow-up beyond the post-test; authors call for testing effects on progression of aMCI.

- **VilouEtAl2023 (2023)**: Review identifies missing long-term effects as a key weakness.

### Counter-Evidence

- **MarlatsEtAl2019 (2019)**: Planned 3-month follow-up in a protocol, but results are not reported and 3 months remains far from conversion timescales.

### Why It Matters

The clinical rationale for NF in MCI is delaying dementia, which cannot be evaluated with 1-month endpoints.

### Priority Score

| Axis | Score | Rationale |
|--------------|-------------|-----------------|
| Severity | 4 | Determines clinical value, but is premature until short-term efficacy is established. |
| Novelty | 4 | No study in the collection attempts it. |
| Feasibility | 2 | Conversion endpoints require multi-year, large cohorts and substantial funding. |

**Composite:** 4 × 0.40 + 4 × 0.30 + 2 × 0.30 = 1.60 + 1.20 + 0.60 = **3.40**

---

## Priority Ranking

| Rank | Gap ID | Title | Type | Severity | Novelty | Feasibility | **Composite** |
|------------|--------|-------------|-----------|-----------------|----------------|--------------------|-----------------------|
| 1 | GAP_001 | Baseline-EEG prediction of NF responders and responder-adaptive protocols untested in MCI | population | 4 | 5 | 4 | **4.30** |
| 2 | GAP_002 | No sham-controlled MCI trial verifies target engagement of the trained EEG feature | methodological | 5 | 3 | 4 | **4.10** |
| 3 | GAP_003 | No long-term follow-up or clinical-progression outcomes after NF in MCI | temporal | 4 | 4 | 2 | **3.40** |

---

## Gap Landscape Summary

### Coverage Strength

Well covered: short-term cognitive effects of classic band protocols (alpha, beta, SMR/theta) in MCI (LavyEtAl2021; JirayucharoensakEtAl2019; MarlatsEtAl2020), multiple systematic and narrative reviews (TrambaiolliEtAl2021; TsaiEtAl2025; Tazaki2024; VilouEtAl2023), and emerging work on self-regulation failure in aging (MarcosMartinezEtAl2026; PabanEtAl2024).

### Methodology Distribution

9 experimental and 6 review papers; there are no computational, observational, engineering or theoretical papers. Experimental work is dominated by single-arm pilots and small trials; only one sham-controlled RCT in MCI (LavyEtAl2021).

### Cross-Gap Patterns

All three gaps stem from small, short, single-site designs that report averaged cognitive outcomes. Responder prediction (gap 1) and target-engagement mediation (gap 2) can be addressed jointly in one sham-controlled trial, which is a prerequisite for the long-term progression studies of gap 3.

---

> **Checkpoint 3: Gap Selection**
>
> Review the gaps above. Select which gap to pursue based on your lab's capabilities, budget, ethics timeline, and equipment access.
>
> To proceed, specify: "Lock GAP_{N}, drop GAP_{N}" — then I'll generate a hypothesis from the selected gap.

---

Files: `step7_gap_analysis.md`
Next step: `/research-hypothesis`
