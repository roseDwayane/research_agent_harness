---
topic: "Pre-putt EEG and putting outcome with a dry-electrode headset"   generation: 3   gap: GAP_003   angle: "event definition: stroke onset versus ball contact as time zero"   date: 2026-10-09
move: perspective
study: analytic
---
# Problem and question — the same putts have never been analysed under both time-zero definitions
## 1. Common ground
Pre-shot EEG studies compare their outcome effects across papers as findings about one preparation period: less high-alpha before holed putts (Cooke et al., 2014) [cookeetal2014], central beta and frontal theta effects (Carey et al., 2024) [careyetal2024]. Laboratory studies lock the EEG to movement initiation detected at the putter [cookeetal2014#E1], [gallicchioring2018#E1]; mobile recording on a green locks it to ball contact [careyetal2024#E1].
## 2. Condition
`perspective`: the two time frames are treated as interchangeable, yet the studies that use them disagree — [cookeetal2014] find the outcome effect in alpha, [careyetal2024] find none in alpha and one in central beta — and differ in reference, baseline, skill and hole size as well, so the disagreement cannot be attributed. No study analyses the same putts under both locks; [gallicchioring2018] record both events and analyse one. The change of the hit-minus-miss contrast between locks has (no reported number: this is an absence); the nearest numbers are the two studies' effects (partial eta2 .24-.27 for alpha; eta2 0.093 for beta).
## 3. Consequence — So-what ladder
Q1 Does the hit-minus-miss contrast of band power in the last second differ between stroke-onset-locked and ball-contact-locked epochs of the same putts?
  → because Q1 is unanswered, Q2 cannot be answered: do the alpha findings of movement-locked studies and the beta/theta findings of contact-locked studies contradict each other or describe different moments.        evidence: `Disagrees with:` lines of the reading notes of [cookeetal2014] and [careyetal2024]; open debate D_draft_OutcomeBandAndTimeZero; stated limitation of [careyetal2024] ("the choice of trigger has limitations").
  → Q3 Which event should field studies without a putter sensor report their EEG against?        evidence: (TBD)
## 4. Three-step sentence
I am studying the time-zero definition of pre-putt EEG epochs because I want to find out how the hit-minus-miss contrast changes between stroke-onset-locked and ball-contact-locked epochs of the same putts, in order to help readers understand whether movement-locked and contact-locked studies can be compared.
## 5. Research question
How does the hit-minus-miss contrast in pre-putt band power change when the same putts are time-locked to stroke onset instead of ball contact?
## 6. Screens
| Screen | Result | Basis |
|---|---|---|
| Is the answer already settled in the literature? | no | `raw` lookup over 462 records: '"movement initiation" "impact"' 0, 'time-locked putt' 0, '"stroke duration"' 0, 'time-locking EEG "movement onset"' 0; '"backswing"' 6 hits, all on gaze or kinematics (titles and abstracts only). Matrix rows bearing on it: gallicchioring2018#E1 (both events recorded, one analysed), careyetal2024#E1 (contact lock, limitation stated), cookeetal2014#E1 (movement lock). None varies the lock. |
| Can the answer be derived from textbook knowledge, the definitions involved or a few lines of algebra? | partly | The last second before contact and the last second before stroke onset are different stretches of time whenever the stroke lasts longer than zero, so band power itself must differ between locks. Whether the hit-minus-miss contrast differs does not follow: both contrasts may be zero, or equal. The derivable part is used as an instrument check only. |
| Could data on this machine settle it? | yes | 12 keyed PilotDataV2 recordings with a front video (30 fps, per-frame LSL time) from which both ball contact and stroke onset can be located, and a head accelerometer as a second onset detector; `cv2`, mne, pyxdf import (the probe looks for a module named `opencv`). |
| Does the answer feed a larger question that someone other than you has asked? | yes | Q2: the two reading notes' disagreement and the stated limitation of [careyetal2024]. |
## 7. Key terms
stroke onset · ball contact · time-locked · hit-minus-miss · band power
## 8. Definitions
- **Ball contact**: first frame in which the ball is displaced in the front video (motion-peak frame minus 3), mapped to EEG time by the frame's LSL stamp. Others: acoustic trigger [careyetal2024]; piezo sensor on the putter [gallicchioring2018].
- **Stroke onset**: the last moment before ball contact at which frame-difference motion in the putter region of the front video rises above its address-stillness level (median plus 3 robust SD of the 2 s before) and stays above it until contact. Second detector: the same rule on head-accelerometer jerk. Others: infrared beam broken by the putter head at backswing initiation [gallicchioring2018]; "movement initiation" [cookeetal2014].
- **Time-locked epochs**: for each lock, the last-second window is the 1 s ending at the event; the baseline is the same absolute second for both locks, -4 to -3 s before ball contact.
- **Hit-minus-miss contrast**: median over participants of the median over recordings of (median of hit trials minus median of miss trials) of a band-power feature in dB relative to the baseline; 12 features (four ROIs x theta 4-7, alpha 8-12, beta 13-30 Hz).
