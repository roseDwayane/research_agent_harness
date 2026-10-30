---
topic: "A biophysical ground-truth generator for neuroimaging analysis"   generation: 1   gap: GAP_001   angle: "measurement side - what an EEG signal-quality index responds to: contamination versus neural state"   date: 2026-10-11
move: confirm-assumed
study: analytic
---
# Problem and question — quality scores are assumed to respond to contamination, not to neural state

## 1. Common ground
A signal-quality index is read as a measure of non-neural contamination, and "clean" is defined operationally: ICA-cleaned, visually inspected recordings serve as "ground-truth clean EEG" (Zhang et al., 2021) [zhangetal2021b]; "pure" EEG is eyes-closed data "carefully inspected" (Klados & Bamidis, 2016) [kladosbamidis2016]. Indices are validated against expert ratings or detected artifacts on recordings [wesierskietal2023; barthelemy2019; lvetal2026] (abstracts).

## 2. Condition
`confirm-assumed`: the premise that a quality index is specific to contamination is stated or relied on and not tested. On recordings it cannot be: neural state and contamination change together (eyes opening brings blinks; drowsiness brings slow eye movements), and no reference of known neural origin exists — "segments labeled as 'clean' are treated as ground truth" [bindrapanwar2026, Sec. 2.3]. The contamination side was tested only on recordings, by swapping segments [trondlelanger2026#E3]; there, data-quality metrics stay associated with a spectral parameter after full ICA cleaning (β +0.24 to +0.30) [trondlelanger2026#E1]. For the state side: (no reported number: this is an absence).

## 3. Consequence — So-what ladder
Q1 How often does a quality index flag a signal as contaminated when only the neural state has changed, and what dose of contamination does that equal?
  → because Q1 is unanswered, Q2 cannot be answered: when quality differs between conditions, groups or sessions, is that a difference in recording quality or in the brain?        evidence: [[D_draft_WhatCountsAsClean]] (open debate); future-work call to re-examine published group differences after controlling for artifacts [trondlelanger2026]
  → Q3 Can quality-based exclusion or weighting be applied without selecting on the neural variable under study?        evidence: (TBD) — no shortlisted paper asks this

## 4. Three-step sentence
I am studying how EEG signal-quality indices respond to artifact-free changes of neural state in a simulated EEG, because I want to find out how often a state change alone is flagged as contamination and what dose of real contamination it equals, in order to help readers of neural-engineering and neuroimaging-methods journals understand whether a difference in a quality score can be read as a difference in recording quality.

## 5. Research question
How large is the false-alarm rate of EEG signal-quality indices on an artifact-free simulated EEG whose neural state alone has changed, and to what dose of contamination is that change equivalent?

## 6. Screens
| Screen | Result | Basis |
|---|---|---|
| Is the answer already settled in the literature? | partly | `raw --grep 'quality index'` 43 hits, `'quality simulated'` 12 hits: none varies neural state at zero contamination. `list-methods --family signal-quality-index`: 10 rows, all on recordings. Contamination side: partly: tested only on recordings by segment swapping [trondlelanger2026#E3]. |
| Can the answer be derived from textbook knowledge, the definitions involved or a few lines of algebra? | partly | An index that is a closed-form function of band power (e.g. high-frequency / total power) changes by a computable amount when alpha power changes by a given ratio — derivable, and excluded from the decision. For indices calibrated on a reference or combining several criteria (covariance distance, robust-z unions, ensembles) the size of the response relative to the contamination response does not follow from the definitions: it depends on how the state change redistributes covariance across channels. |
| Could data on this machine settle it? | yes | `ai_scientist/ideas/clean_eeg_sim/` (probe: runs at ~1 s CPU per simulated second per patch, timed); real artifact waveforms and resting recordings in `~/openneuro_data` (ds003478, ds004148, ds004784 phantom, ds007176); pyriemann 0.12 and mne 1.12.1 installed. |
| Does the answer feed a larger question that someone other than you has asked? | yes | Q2: [[D_draft_WhatCountsAsClean]] and the future-work call of [trondlelanger2026]. |

## 7. Key terms
signal-quality indices · neural state · artifact-free simulated EEG · false-alarm rate · contamination

## 8. Definitions
- **Signal-quality index**: a scalar computed from a multichannel EEG segment, oriented so that larger = worse, here seven: Riemannian-potato z-distance (after [barthelemy2019]); PREP-style percentage of bad channels (robust deviation, correlation, high-frequency noise); FASTER-style composite z; peak-to-peak rejection rate; mean absolute kurtosis; high-frequency power ratio; the Layer-Q composite of `ai_scientist/ideas/EEG_signal_quality_E1_formulas_v2.md`. Other definitions: expert rating; artifact event duration [wesierskietal2023]; classifier probability [lvetal2026]. This one: computable without labels, on simulated and recorded data alike.
- **Neural state**: a setting of the generator's parameters with zero non-neural sources; two states A and B differ in thalamic drive so that the 8–13 Hz power ratio equals the eyes-closed / eyes-open ratio measured in ds004148. Other definitions: vigilance stage; task condition. This one: it is the best-documented large state change in resting EEG and the generator has a parameter for it.
- **Contamination**: a recorded non-neural waveform (ocular, muscle) added at the sensors, scaled by a (a = 1: amplitude as recorded relative to the background EEG of its source recording).
- **False-alarm rate** FA: the fraction of clean 1-s epochs of state B whose index exceeds tau_k, the 95th percentile of that index over clean epochs of the baseline state A (separate seeds, same simulated subject); nominal value 0.05. Other definitions: false positives against expert labels. This one: on a signal with zero non-neural content every flagged epoch is a false alarm by construction of the signal, not by a rater's judgement.
- **State-equivalent dose** D_k: the contamination dose whose detection rate (fraction of contaminated state-A epochs above tau_k) equals the false-alarm rate of state B, read from the dose-response curve.
- **Calibration**: each index is used as its authors use it - the Riemannian potato with a reference covariance from a baseline period (reported only); PREP-style and FASTER-style criteria and Layer-Q are computed within the recording and need only the threshold tau_k, taken from a separate baseline-state calibration run (60 one-second epochs).
