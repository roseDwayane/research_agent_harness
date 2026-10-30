# Hypothesis — generation 1 (GAP_001, angle: token geometry of the quantizer input: fixed versus learned front end at matched reconstruction) — revised in round 2

## Selected gap summary
GAP_001, methodological / integration, move apply-wider, priority 4.00. A frozen analytic front end reconstructs as well as a learned convolution yet yields a less diverse codebook (project record, one seed). The account that the variance structure of what is quantized limits usable codebook dimension was tested only on learned image and speech encoders [zhaoetal2026]; EEG work attributes usage differences to targets [maetal2025], [cuietal2026]; the front end was varied only without a codebook [xieetal2026].

## Research questions
- RQ1: Can the codebook perplexity deficit of a frozen filter-bank front end against a learned convolution in an EEG tokenizer be at least halved without training the front end by a fixed whitening of its tokens, and does whitening gain more than rank-matched noise does?
- RQ2: Does the deficit replicate over seeds at CPU scale, and how large is it?
- RQ3: Which part of whitening carries a gain — removing the mean token, or flattening the variances?

## Hypotheses
**H1 (primary, mode: test, kind: cause).** Although the codebook perplexity deficit of a frozen filter-bank front end against a learned convolution is read as the price of not training it, a fixed whitening of its tokens closes at least half of that deficit and more of it than rank-matched noise does, which we conjecture is because the encoder cannot use signal directions that are small beside the tokens' dominant modes.
- What is tested is sufficiency of a fixed map; the conjectured reason is not tested beyond the noise control and is listed as a limit.
- Expected direction, before data: whitening raises perplexity. Basis — contested: [zhaoetal2026] (strong modes of what is quantized suppress low-variance modes) predicts a gain; the project record's reading and [andersonetal2023] (a non-moving front end is an optimisation failure) predict that training is what is missing; a 12-layer encoder may re-shape any input geometry.
- Statistic (signed): per seed s, G_s = P_W,s − P_F,s, D_s = P_L,s − P_F,s, H_s = P_W,s − P_N,s, with P the codebook perplexity of held-out code assignments averaged over steps 10,000, 12,000, 14,000 and 16,000.
- Decision rule (revised after restatement 2), three-way, on one-sided 95% confidence bounds over 5 seeds. E2 decides: mean(G − 0.5 D) is read on the four-point mean and at step 16,000 alone; H1 is refuted if the upper bound is below 0 on both, or if a guard fails (W's validation loss above F's by more than the larger of 1% and twice the between-seed SD of F's; W's code informativeness — share of held-out Fourier-amplitude target variance explained by the assigned code's mean target — below F's by more than twice its between-seed SD); supported if the lower bound is above 0 on both readings and the guards hold; undecided otherwise. E4: per-seed H − 0.25 D with the same three-way reading. E6 is descriptive (2 seeds).
- Precondition (E1): mean D > 0 at one-sided paired p < 0.05; otherwise the study reports non-replication of the deficit at this scale and H1 is undecided.
- Power: 5 seeds, paired, one-sided: d ≥ 1.11 at 80% power (normal approximation; worse in truth at n = 5); between-seed SD of perplexity unreported anywhere: verdict marginal.

**H2 (secondary, mode: estimate).** The size of the deficit D over 5 seeds with its 95% CI. Why an estimate — size-open: the direction is the project record's single-seed observation; its size and spread at this scale are unknown.

**H3 (secondary, mode: estimate).** For the five arms (L, F, W, N, C) the token statistics (effective rank, signal-subspace rank, mean pairwise cosine), the effective rank of the quantizer input, and the share of the whitening gain reached by centring alone (P_C − P_F over 3 seeds). Why an estimate — descriptive: an ordering of five arms and one ratio at n = 3.

## Claims set aside at B4
- "The effect holds for other bank configurations (12 poles, 26 oscillators)" — dropped for budget. A reader cannot tell whether the result is specific to the most anisotropic bank.
(The centring-only arm, set aside at B4, was restored in round 2 as arm C.)

## Operational definitions
As in step7b_problem.md part 8. Tokenizer: `vqnsp_encoder_base_decoder_native`, 12-layer encoder, 3-layer decoder, 12.3 M parameters, patch 250 samples, 4 patches per window, codebook 12,288 x 64, cosine lookup, EMA 0.99, k-means initialisation, batch 32, peak learning rate 1.25e-5 after a 2,000-step warm-up, fp32 on CPU, 16,000 steps.

## Scope
| IN | |
|---|---|
| Data | ISRUC-Sleep (6 channels) and Sleep-EDF telemetry (2 channels) pretraining HDF5 files of the project, 250 Hz, about 55 h; flat windows (SD < 1e-6) excluded; corpus order as in the project. Second dataset: EEGBCI, 109 subjects, 6 channels, resampled to 250 Hz, band-pass 0.5–100 Hz, no ASR. |
| Method | L learned convolution; F frozen filter bank; W = F + fixed whitening; N = F + rank-matched noise; C = F + centring only. |
| Outcome | Codebook perplexity of held-out code assignments, mean of four evaluation points; validation loss at the same points. |
| Design | Seeds as units, paired across arms; 5 seeds for L, F, W, N; 3 for C. |
| OUT | Rationale |
| Stage-2 masked pretraining and downstream accuracy | several hours per arm and seed on this CPU; the codebook is the outcome the gap is about |
| The trainable structured front end | its parameters receive 1/40–1/360 of the gradient (project record); "trained" would be confounded with "starved" |
| Other bank configurations, dead-code revival, other quantizers | budget; comparability with the project record |
Licences: ISRUC-Sleep (licence unverified); Sleep-EDF (licence unverified); EEGBCI (licence unverified).

## Conceptual framework
```
1 s patch ─► front end ─► token t (256) ─► [W: s·C^-1/2 (t−m) | C: t−m | N: t+noise] ─► 12-layer encoder ─► z (64) ─► cosine EMA codebook ─► decoder
             L learned conv / F frozen bank                                              (trained in every arm)       held-out code histogram ─► P
```

## Risk assessment
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The deficit does not replicate at this scale | medium | H1 undecided | E1 precondition; non-replication reported |
| Seed spread large relative to the deficit | medium | undecided outcome | three-way rule; paired design |
| Whitening destabilises training | medium | W fails the validation guard | shrinkage 0.1; norm-matched scaling |
| About 19 CPU-hours overruns | medium | fewer seeds for C and E6 | 4 runs in parallel |

## Rival explanations
| Explanation | How it would arise here | Ruled out by | Main? |
|---|---|---|---|
| rank inflation by noise (other) | whitening amplifies low-variance token directions that carry noise; codes spread over noise and perplexity rises without the encoder gaining usable signal | E4: arm N reaches W's token rank with pure noise; the rule requires W to beat N by a quarter of the deficit, and E2 requires W's validation loss within the guard | yes |
| chance | five seeds | E2: one-sided 95% bounds over paired seeds, three-way outcome | |
| bias | evaluation points or guard chosen after seeing curves | design: evaluation points, guard and thresholds fixed in this file | |
| reverse cause | — | design: the factor is assigned | |
| confounding | whitening changes the token scale, hence the effective step size | design: s matches the mean squared token norm; arm C separates mean removal | |
| leakage | whitening statistics or the outcome computed on fitted data | design: m and C from training patches only; perplexity from held-out patches | |
| selection | the bank configuration is the most anisotropic in the project record | (not addressed) | |

## By-construction check (H1, redone for the revised claim)
1. Predictor: t'_i = s · C_shrunk^(-1/2) (t_i − m). Outcome: P = exp(−Σ_k q_k ln q_k), q_k the share of 20,000 held-out patches assigned to code k, averaged over four evaluation points; statistics G − 0.5 D and H.
2. Shared terms: none — t, m, C, s are at the encoder's input; q_k is read at the codebook.
3. Substitution: q_k depends on the encoder trained for 16,000 steps under each arm; no existing data give it. Computable without the experiment: no. (That W's tokens have a higher rank than F's is algebra; that N's rank equals W's is by construction of N; neither is in the rule.)
4. Manipulation: the 256-dimensional token of every patch. Measure: the code histogram after 12 trained layers. Can it come out otherwise: yes — G may be near 0 (the encoder re-shapes any input), negative (codes spent on directions the EMA update abandons), or H may be near 0 (rank alone suffices). Free quantity: how the jointly trained encoder and EMA codebook transmit input geometry to code usage.
5. Controls through the statistic (signed differences of means, no absolute value, rank or clip). Positive control (E1): D; the project record gives +109 on EMA usage at 15 patches, one seed; with held-out assignments at 4 patches the size is unknown and the sign expected positive; the statistic returns a difference unchanged. Negative control (E4): under H1, H > 0.25 mean D; under the main rival H ≈ 0. Noise term: all differences are within seed (same initial weights of the shared modules, same data order).
6. Existing predictor: none.

## External check
Real EEG throughout. One data pool carries E1–E5; E6 repeats L, F, W on EEGBCI (independent, awake, another amplifier, no ASR), 2 seeds, descriptive. Inventory as in argument.json.

## Traceability
| Element | Source | Evidence |
|---|---|---|
| RQ1 | GAP_001 | [zhaoetal2026], [maetal2025], [cuietal2026], [xieetal2026]; project record |
| Thresholds 0.5 and 0.25 | design choices | half of the deficit: below it training remains the larger factor; a quarter over noise: below it rank alone explains most of the gain |
| Validation guard | design choice | max(1%, 2 SD of F over seeds); the project's gap was 0.4% |
| E0 → instrument | arms, whitening statistics, manipulation check, timing, plan committed before the first run |
| E1 → H2; positive control of H1 | D over 5 seeds |
| E2 → tests H1 (decides) | G − 0.5 D; validation guard |
| E3 → H3 (descriptive) | token statistics and z rank per arm |
| E4 → control of H1, with its own rule | H against 0.25 D, 5 seeds |
| E5 → H3 (descriptive) | centring-only arm, 3 seeds |
| E6 → tests H1 on a second dataset | refuted there if mean G < 0.5 mean D (2 seeds, reported, not tested) |
| Scope of H1 | one tokenizer, one bank configuration, 16,000 steps, 4 patches, sleep EEG; code usage, not downstream accuracy |
