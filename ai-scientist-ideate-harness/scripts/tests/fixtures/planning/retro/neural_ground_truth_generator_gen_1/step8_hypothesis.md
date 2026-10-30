# Hypothesis — generation 1

## Selected gap summary
GAP_001 (measurement; move `confirm-assumed`; priority 4.60). Quality indices are read as measures of contamination, on the strength of references that are cleaned recordings [zhangetal2021b; bindrapanwar2026]. On recordings, neural state and contamination cannot be varied separately, and quality metrics stay associated with a spectral parameter after ICA cleaning [trondlelanger2026]. A generator with zero non-neural content allows the state to be changed alone.

## Research questions
- **RQ1.** How large is the false-alarm rate of EEG signal-quality indices on an artifact-free simulated EEG whose neural state alone has changed, and to what dose of contamination is that change equivalent?
- RQ2. At which dose of each contaminant class does each index first respond on a signal known to be clean, and does the changed state mask contamination?
- RQ3. Does an artifact-free simulated EEG receive a better score than recordings from the indices that are calibrated on recordings?

## Hypotheses (revised in round 2)
**H1 (primary; mode test).** Although signal-quality indices are read as measures of contamination, in an artifact-free simulated EEG a change of neural state of eyes-closed/eyes-open size raises the false-alarm rate of the four composite indices, thresholded on the baseline state, to at least 0.20 on average (nominal 0.05), because these indices compare each epoch with a reference or with the other channels of the recording, both of which a state change alters with no contamination added.
- Expected direction, before data: above 0.05 for the potato distance — settled: a distance from a baseline covariance grows when the covariance leaves the baseline. For the three self-referential indices nothing predicts a direction. Whether the average reaches 0.20 is open. Hence a magnitude test, one-sided.
- Smallest effect of interest: FA = 0.20 (design choice: four times nominal; one clean epoch in five rejected for a reason that is not contamination).
- H0: FA < 0.20. Test: one-sided 95% bootstrap bound over 24 simulated subjects. Supported if the lower bound ≥ 0.20; refuted if the upper bound < 0.20; otherwise undecided.
- Power: n = 24, one-sided → d ≥ 0.51 at 80% power (rough, n < 30); no literature effect → marginal.

**H2 (secondary; mode estimate).** Per index and contaminant class: the dose–response of the detection rate, the smallest dose with detection rate 0.5, the state-equivalent dose, and the detection rate of the same doses added to the changed state — to within one step of a nine-step dose grid. `size-open:` the direction is settled by design, the doses are unknown.

**H3 (secondary; mode test).** Although a signal without contamination should receive the best score, at least one index calibrated on recordings rates the artifact-free simulated EEG worse than the median recording, because such an index measures distance from the typical recording. Expected direction: unknown. Refuted if every reference-calibrated index rates the simulated EEG better than the median recording (one-sided Mann–Whitney, 24 simulated vs 60 recorded, α = 0.05, Holm-corrected).

## Operational definitions
As in `step7b_problem.md` part 8 (false-alarm rate, state-equivalent dose, calibration). Composite set K_c: Riemannian-potato z-distance (reference covariance and threshold from baseline-state epochs, separate seeds), PREP-style bad-channel percentage, FASTER-style composite z, Layer-Q composite (self-referential within the recording; threshold from baseline-state epochs). Single-feature set K_s (reported, not in the decision): peak-to-peak rejection rate, mean absolute kurtosis, high-frequency power ratio.

## Scope
| IN | |
|---|---|
| Data | Simulated 64-channel EEG from `clean_eeg_sim` (68 parcels, fsaverage BEM lead field, biosemi64), 24 simulated subjects (seed sets), 30 s per condition; recorded: ds004148 (60 adults, eyes-closed and eyes-open rest), ds003478 (30 adults, rest, EOG channels), ds004784 (phantom head with ocular, muscle and motion artifacts) |
| Manipulation | state A → B through thalamic background drive, alpha ratio matched to ds004148 EC/EO; contamination: recorded ocular and muscle waveforms (ds003478 EOG-locked components; ds004784 phantom) scaled by a ∈ {0, 0.03, 0.06, 0.1, 0.2, 0.3, 0.5, 0.7, 1}; synthetic 50 Hz line and electrode pops |
| Comparison | same simulated subject: baseline state A (thresholds), state B (unmatched; RMS-matched and gain-only arms reported), A′, A + a·artifact over the dose grid |
| Primary outcome | FA = false-alarm rate of state-B epochs against baseline thresholds, mean over K_c |
| Secondary | a*, dose monotonicity (H2); rank of simulated vs recorded (H3) |
| Setting / design | 14 CPU cores; within-subject, simulated; decision rules fixed before analysis |

| OUT | Rationale |
|---|---|
| Deep-learning quality classifiers | none installed; need labelled training data |
| Movement artifacts as a decision class | phantom only; reported descriptively |
| Other state changes (sleep, drugs) | the generator has no validated parameter path for them |
| Source-level or single-channel indices | the question is about multichannel recording-level scores |

Datasets: ds004148, ds003478, ds004784 — CC0 (local `dataset_description.json`); public release for reuse; consent wording not checked beyond the licence file.

## Conceptual framework
```
 thalamic drive g_T ──► generator G(theta) ──► s_A , s_B (RMS-matched, zero non-neural content)
                                                  │                         │
 recorded artifact w_c × a ──► s_A + a·A_c        │                         │
                 │                                ▼                         ▼
                 └────────► Q_k(s_A + a_0 A_c) − Q_k(s_A) = Δart_k     Q_k(s_B) − Q_k(s_A) = Δstate_k
                                                  └──────────── R_k = Δstate_k / Δart_k ──► M = median_k |R_k|
```

## Risk assessment
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The generator cannot reach the EC/EO alpha ratio by thalamic drive alone | medium | high | E0 scans drive and corticothalamic gain; if unreachable, the largest reachable ratio is used and stated, and R is reported per dB of alpha change |
| Identical patches and a flat aperiodic slope make the simulated state change unlike a real one | high | high | E6 repeats the ratio on recordings (high- vs low-alpha epochs; blink vs blink-free epochs) |
| An index implemented here differs from its reference implementation | medium | medium | E1 unit tests against published definitions; pyprep / autoreject are not installed, so no cross-check against them |
| Denominator Δart near zero for an insensitive index | medium | medium | orientation / sensitivity check first; insensitive indices leave the median and are listed |

## Rival explanations
| Explanation | How it would arise here | Ruled out by | Main? |
|---|---|---|---|
| bias | the response to the state change is a property of this simulator (identical patches, flat slope, 20 Hz harmonic), not of EEG | E6 (same ratio on recordings) | **yes** |
| chance | two realisations of the same state differ in the indices by sampling alone | E3 (A vs A′ noise floor) | |
| confounding | the drive change alters total power or spatial rank besides alpha, and the indices respond to those | design: B is RMS-matched to A; E3 gain-only arm | |
| reverse-cause | — | design: the factor is assigned | |
| incorporation | s_A is the baseline of both differences in R_k; single-feature indices are functions of the band power that the manipulation sets | E3 for the shared baseline; design: the single-feature indices are outside the decision statistic | |
| leakage | a calibrated index's reference computed on the segments it scores | design: reference from separate seeds (H1) or separate recordings (H3) | |

## By-construction check (H1, redone for the round-2 claim)
1. Predictor: `s_B = G(theta_A with g_T -> g_T')`, `P_alpha(s_B) / P_alpha(s_A) = rho_ECEO`. Outcome: `FA = mean over k in K_c and epochs e of 1[ Q_k(s_B, e) > tau_k ]`, `tau_k = q95 over epochs of Q_k(s_A)`.
2. Shared terms: `s_B` (the manipulated signal is what the outcome scores) and `s_A` (the state departed from; the source of tau_k).
3. Substitution: Q_k(s_B, e) for k in K_c depends on the epoch-wise 64 × 64 covariance (potato) and on between-channel robust statistics (PREP, FASTER, Layer-Q) of s_B; none is a function of rho_ECEO. `no` for K_c; `partly` overall, because for K_s (P_hf / P_total) the shift follows from rho_ECEO and the spectrum of s_A — excluded from FA, named in Short Hypothesis sentence 4. s_A: what the shared baseline alone produces is the false-alarm rate of a second realisation of A (E3), expected 0.05.
4. E2: the manipulation acts on thalamic drive in all patches; the indices are computed per 2-s epoch on 64 channels. Can fail: yes — if baseline epoch-to-epoch spread covers the state change, FA ≈ 0.05; the self-referential criteria may not move. Free quantity: whether the baseline spread covers the change.
5. Positive control (E4): half the A′ epochs replaced by contaminated epochs at a saturated dose → FA = 0.5·1 + 0.5·0.05 = 0.525; the indicator returns 1 per flagged epoch whatever the size, so the planted value returns only in the saturated range (E5 shows it first); at detection rate p the value is 0.5·p + 0.025. Negative control (E3): A′ → 0.05. Both are fresh 30-s simulations, exposed to the same sampling variation as the contrast.
6. No existing predictor: not applicable.
Derivability screen for the new claim: `partly` — direction for the potato distance follows from its definition; the rate, and the three self-referential indices, do not.

## Claims set aside at B4
- A test of the state response of the single-feature spectral indices (K_s): derivable from their definitions (step 3) → reported descriptively in E2, not tested. A reader loses a decision for these three indices; their response is still shown.

## External check
Evidence for H1 is simulated (`synthetic: true`). Real-data tie: **E6** computes the same false-alarm rate on the recorded eyes-closed → eyes-open change of ds004148 (thresholds from each subject's eyes-closed epochs; eyes-open epochs without a detected ocular event; held-out eyes-closed epochs as nominal check). Datasets carrying the simulated contrast: one generator → second "dataset" is the recordings of E6.
Inventory (probe roots): ~/openneuro_data/ds004148 — serves (EC/EO rest, 60 adults); ds003478 — serves (rest with EOG); ds004784 — serves the contamination library (phantom); ds007176 — reserve for E6 (rest, 45 adults); ds003775 — reserve (rest, 111 adults; no EOG); ds003810, ds006801, ds007222, ds007406, ds007558 — do not serve (few channels, task or walking); ~/mne_data — fsaverage serves the lead field; the task datasets do not serve; ~/.cache/huggingface/hub and ~/.cache/torch — models only, no data.

## Traceability
| Element | Source | Evidence |
|---|---|---|
| RQ1 | GAP_001 | zhangetal2021b; bindrapanwar2026 Sec. 2.3; trondlelanger2026#E1 |
| H1 direction / magnitude | algebra of covariance-based indices; threshold = design choice | step 3 above |
| dose grid, segment design | trondlelanger2026#E3; zhangetal2021b#E1 | graded contamination conventions |
| E0 instrument: states, calibration, rules fixed | — | — |
| E1 instrument: indices + unit tests | — | — |
| E2 tests H1 (C1) | raw: 64-ch epoch (2 s) → index per epoch → indicator above tau_k → fraction per subject and index → mean over K_c → mean over subjects | — |
| E3 control C1 (noise floor, gain-only) | chance, confounding rivals | — |
| E4 control C1 (positive) | step 5 | — |
| E5 descriptive C2 (H2) | dose–response | — |
| E6 tests C1 on recordings | external check | — |
| E7 tests C3 (H3) | ceiling | — |
| E8 release | — | — |
| scope of C1 | 24 simulated subjects, one generator, one state path, two contaminant classes | — |

## Revision record (round 2)
Primary claim replaced after blind restatement 1: ratio at a_0 = 0.3 (threshold 0.25, unsigned, median) → false-alarm rate against baseline thresholds (threshold 0.20, one-sided, mean). E0: simulated subjects get jittered parameters; go/no-go on the reachable alpha ratio. E1: pyprep / autoreject installed for cross-checks. E6: recorded EC → EO change. See `argument.json` tradeoffs and reader_doubts.

## Revision record (round 4, forced by the coherence gate after restatement 2)
Decision set: the three within-recording composite indices (PREP-style, FASTER-style, Layer-Q); statistic FA2 = second-largest per-index false-alarm rate; the potato distance is reported only (its rise follows from its definition). Expected direction for the decision set: unknown (a change common to all patches may cancel in within-recording comparisons or change their scale) → `contestable`. Thresholds from a separate 60-s calibration run A0, 1-s epochs; A′ and B 40 s each. E3 adds an 18–22 Hz notch arm. By-construction steps for this claim: predictor `s_B = G(theta_A with g_T -> g_T')`; outcome `FA2 = second largest over k of mean_e 1[Q_k(s_B, e) > tau_k]`, `tau_k = q95 Q_k(s_A0)`; shared: `s_B`; substitution: robust-z statistics of s_B are not functions of rho_ECEO → `no` for the decision set, `partly` overall (potato and single-feature indices, excluded); can fail: yes; positive control returns 0.525 per index at a saturated dose, and the second-largest of three equal rates is that rate; negative control returns 0.05.
