# Hypothesis — generation 3 (GAP_003, time zero)

## Selected gap summary
GAP_003 · methodological · `perspective` · 3.70. Movement-locked and contact-locked studies disagree on the outcome band [cookeetal2014] vs [careyetal2024]; no study analyses the same putts under both locks; [gallicchioring2018] record both events and analyse one.

## Research questions
- RQ1. How does the hit-minus-miss contrast in pre-putt band power change when the same putts are time-locked to stroke onset instead of ball contact?
- RQ2. Does the interval from stroke onset to ball contact differ between hit and miss putts?
- RQ3. How far apart are the experimenter's key, stroke onset and ball contact, and what are the contrasts under each?

## Hypotheses
- **H1 (primary, test).** Although movement-locked and contact-locked studies are compared as accounts of one preparation period, the hit-minus-miss contrast of band power in the last second differs between epochs time-locked to stroke onset and to ball contact for the same putts, which we conjecture is because the last second before ball contact contains the stroke.
  H0: the two contrasts are equal for every feature. Statistic: T = max over 12 features of |c_onset - c_contact| (dB); the claim is unsigned — it asserts a difference, not its sign — so an absolute value is used. Null: 5,000 circular shifts of the label sequence within recording, applied to both locks together. Expected direction: a difference exists; basis contested — [cookeetal2014] and [careyetal2024] report different bands under different locks, but they also differ in reference, baseline and sample, and nothing isolates the lock. Decision rule: refuted if T is at or below the 95th percentile of its null, or below 0.5 dB (a design-choice floor; the nearest reported difference between outcome classes is 0.484 dB [careyetal2024]).
  Power: 4 participants; `power --mode paired --n 4 --sided 1` → d >= 1.24 (worse in truth). A permutation statement about these recordings.
- **H2 (secondary, test).** Although outcome contrasts are attributed to preparation, the interval from stroke onset to ball contact separates hit from miss putts within a recording (AUC different from 0.5). Expected direction: unknown — no source reports stroke duration by outcome. Refuted if |AUC - 0.5|, hierarchical median, is inside the circular-shift null.
- **H3 (secondary, estimate).** The hit-minus-miss contrast of 36 window band-power features under three locks (experimenter's P key, stroke onset, ball contact), each with a bootstrap interval over recordings. Why an estimate — descriptive: a map of contrasts; no ordering asserted.
- **H4 (secondary, estimate).** The distributions of P key minus ball contact and of stroke onset minus ball contact, per recording and by outcome. Why an estimate — descriptive.

## Operational definitions
As in step7b part 8. Pseudo-onset lock: ball contact minus the recording's median onset-to-contact interval (a constant shift with no trial-specific information).

## Scope
| IN | |
|---|---|
| data | PilotDataV2, 12 keyed recordings, 4 participants, CGX Quick-32r dry headset, front video; (licence unverified), unpublished laboratory recordings |
| factor | time-zero definition: stroke onset, ball contact (and descriptively the P key) |
| comparison | the same putts and the same baseline second under both locks |
| primary outcome | T = max |difference of hit-minus-miss contrasts| over 12 features |
| setting | laptop CPU; video decoding estimated 30 min |

| OUT | why |
|---|---|
| explaining the Cooke-Carey disagreement itself | their data are not on this machine; this study shows whether the lock alone can produce such a difference |
| wet-electrode recordings | none available |
| slow potentials (readiness potential) | 1 Hz high-pass in the pipeline |

## Conceptual framework
```
address ──────────── stroke onset ──(interval d, varies by putt)── ball contact ──► outcome
   onset lock:   [onset-1, onset]                  contact lock: [contact-1, contact]  (contains the stroke when d > 0)
   same baseline second for both: [contact-4, contact-3]
   H1: contrast(onset lock) ≠ contrast(contact lock)     H2: d differs by outcome     E3: pseudo-onset = contact − median d
```

## Risk assessment
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Stroke onset from 30 fps video is noisy or biased | high | blurs the onset lock | second detector (accelerometer jerk); agreement reported in E1; E4 repeats H1 with it |
| Novices start and stop before the stroke | medium | wrong onsets | rule requires motion to stay above threshold until contact; putts without a clear onset are counted and dropped |
| Both contrasts are noise | medium | T inside null | that is the refuting outcome; reported with the size detectable (E6) |
| Four participants | certain | no population inference | scope limited to these recordings |

## Rival explanations
| Explanation | How it would arise here | Ruled out by | Main? |
|---|---|---|---|
| bias | onset detection errs differently for hit and miss putts (e.g. hesitant strokes), so the onset-locked windows of the two classes cover different phases | E4 (accelerometer-based onsets) and E1 (detection quality by outcome) | yes |
| chance | 12 features, two noisy contrasts | E2 circular-shift null on the maximum | |
| confounding | the two windows differ in generic signal quality (movement artifact in the contact window), so the contrast differs for a non-neural reason | (not addressed) | |
| selection | putts without a detectable onset are dropped, more often in one class | E1 reports drops by outcome; E2 repeated with pseudo-onsets for dropped putts | |

## By-construction check (H1)
1. Factor: the lock (stroke onset or ball contact) of each putt's last-second window. Number read: T = max over 12 features of |c_onset - c_contact|.
2. Shared terms: both contrasts use the same labels, the same trials and the same baseline second; these are common to both sides by design and cancel in the difference only if the last-second powers behave alike under both locks.
3. Substitution: c_onset - c_contact = contrast of [P(onset window) - P(contact window)]; with interval d = 0 for every putt the windows coincide and T = 0 exactly; with d > 0, T depends on how band power between onset and contact differs by outcome — not computable from any existing table. Computable without the experiment: no.
4. E2: the factor acts on which second is analysed; the measure is computed on those seconds; it can equal the null if outcome is unrelated to what happens between the two events. Free quantity: the outcome dependence of band power during the interval between stroke onset and ball contact.
5. Positive control: +1 dB planted in one feature of the onset-locked window of hit putts. Through the absolute value, |d0 + 1| - |d0| equals 1 only when the unplanted difference d0 of that feature is not negative; the feature with the smallest |d0| is used and the detection is read as T exceeding the null and 0.5 dB. Negative control: the same statistic on the window 3 to 2 s before each event (far from the stroke under both locks): expected inside the null; its null is built the same way.
6. No existing predictor.

## Claims set aside at B4
- "The lock explains the disagreement between [cookeetal2014] and [careyetal2024]" — not testable without their data; a reader loses a direct resolution of that disagreement and gets a demonstration on one data set of whether the lock alone can change the contrast.

## External check
Real recordings. One data set. Second data set: none on this machine — `~/mne_data` and `~/openneuro_data` hold no putting or aiming task with two movement events; the Carey et al. (2024) OSF set is contact-locked only (backswing "could not be detected") and not on disk.

## Traceability
| Element | Source | Evidence |
|---|---|---|
| RQ1 | GAP_003 | reading-note disagreement; [careyetal2024] limitation |
| 0.5 dB floor | design choice | nearest number 0.484 dB [careyetal2024] |
| E0 instrument | — | trial table, contact and onset detection, rules fixed |
| E1 descriptive H4 | H4 | timing distributions, detector agreement |
| E2 tests H1 | H1 | T vs null and 0.5 dB |
| E3 control H1 | because-clause | pseudo-onset (constant shift) |
| E4 control H1 | main rival | accelerometer onsets |
| E5 control H1 | negative control | far window |
| E6 control H1 | positive control | planted 1 dB |
| E7 tests H2 | H2 | AUC of interval vs outcome |
| E8 descriptive H3 | H3 | contrasts under three locks |


## Round-2 revision (after restatement 1)
Baseline moved to -5 to -4 s before ball contact; putts with an onset-to-contact interval above 2 s dropped; recordings with unequal onset loss (more than 10 percentage points between outcomes) excluded; negative-control window now 2 to 1 s before each event; E3 has a classification rule (0.8); E6 plants 1 dB and 0.5 dB in frontal alpha fixed in advance; E9 (regression on head acceleration) added and the confounding rival now points to it. H1's statement and decision rule are unchanged. Coverage: the test covers whether the contrast changes; which bands, direction and size are estimated by H3.
