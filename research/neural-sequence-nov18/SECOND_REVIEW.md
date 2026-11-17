# Independent second methodology review — final neural candidate

Reviewed 2026-11-17 UTC, within the final research window. Scope: `quality_sequence`, frozen weights SHA256 `8b99077c9d9a27643f724deced7ec55fd303587e4b296e4f2fa8e259387c53b1`. This review inspected the research and exported inference code, training/source audits, recorded PFF rows, and actual CSV bytes. No new model trial was run.

**Recommendation: retain the existing tier0_v20 submission under the declared acceptance rule. Keep this neural model as a reproducible, promising research candidate. It improves both observed PFF scores, but does not pass the predeclared joint gain gate, and this reused validation set cannot establish a new statistically significant winner.**

## Verified results

I independently recomputed the means, paired deltas, 50,000-resample game bootstrap (seed 77121), and wins from `local/neural-sequence-target-nov17/pff-rows.json`. Each world contains 32 distinct games. The two worlds use the same games, so they are not 64 independent matches.

| World | Neural spellF1 | tier0_v20 | Gain | Paired lower bound | Games won | Fixed numeric gate |
|---|---:|---:|---:|---:|---:|---|
| m0 | 0.528864069 | 0.512602901 | +0.016261168 | +0.004794307 | 25/32 | Fail |
| m2 | 0.581368013 | 0.555322913 | +0.026045100 | +0.014256849 | 26/32 | Pass |

The gate requires mean gain at least 0.01 and the paired lower bound strictly greater than 0.005 in **both** worlds. The m0 bound misses by 0.000205693; rounding it to 0.005 or relaxing the gate after seeing the result would be invalid. Both lower bounds are positive for this fixed comparison, but these are exploratory bounds on an adaptively reused set, not a fresh-test significance guarantee.

The evaluation uses the same PFF-B cases, native visibility, scoring implementation, per-game averaging, and tagged-development adapter for the candidate and control. The reproduced v20 reference scores match the supplied benchmark to numerical precision. The adapter uses pseudo-restart tags; the challenge uses its actual automatic Smart Tagging input. This is a transfer limitation rather than a metric-comparison mismatch.

## Material methodology findings

1. **Selection bias remains.** The alternative plan was written before this alternative's scores and froze its existing weights. Nevertheless its own reason explicitly cites the earlier blended model's PFF result. Many preceding approaches were also evaluated against PFF-B. PFF-B is now a reused validation set. The bootstrap addresses variation among these 32 games for a fixed candidate; it does not adjust for the adaptive research search. Do not call this an untouched held-out test or promise generalization to the unseen challenge tracker.

2. **New fitted components exclude PFF; the whole pipeline is not wholly tracker-held-out.** The new network/scaler/transition fits use 30 external games: 3 Metrica, 20 SkillCorner, 7 IDSSE. Audits list disjoint held-out tracker games, and the held-out neural fits reuse verified parent training arrays. However, baseline H50 features and fallback depend on inherited v22 heads previously fitted on Metrica/IDSSE, and v22 retains historical PFF-informed heuristic constants from v20. Thus the accurate claim is “new neural and transition weights fitted without PFF”; not “all pipeline choices were independent of PFF” or “complete model was cross-tracker held out.” This review makes no new legal interpretation of the dataset terms.

3. **External source robustness is useful but limited.** Metrica/IDSSE development uses synthetic visibility variants and label conventions; native SkillCorner differs from PFF and from the challenge tracker. The 80 development cases arise from 30 games, not 80 independent games. Team-swap augmentation likewise does not add independent matches. Large Metrica/IDSSE gains cannot by themselves certify target-tracker performance. Missing movement/shape correctly causes exact H50 fallback; available quality features do not guarantee a familiar target distribution.

4. **Decoder change has a coherent mechanism.** Untempered neural log likelihoods plus a fitted transition prior avoid the earlier classifier's excessive smoothing. The baseline-only sequence control fails the development gate, whereas the quality-routed neural sequence passes all source gates. This supports the neural contribution rather than attributing the gain merely to another smoother. Features use future context and the decoder uses the full sequence: the implementation is an offline full-match estimator.

## Reproduction and release checks

- Export and research inference match exactly on one 88,439-frame tagged PFF half for both neural modes, according to `local/quality-neural-nov17/inference-parity.json`. I inspected both implementations; their sustained-pace override, feature construction, team-swap averaging, quality routing, sequence decoding and restart fill agree. This is a narrow parity check, not exhaustive coverage of every match.
- I independently compared the actual research challenge CSVs from fresh rebuild A and B: **full bytes identical**, SHA256 `a0c7a8d5cf90786e736936ccaac6ebf37e27afae30adea1733123eb62695ca68`. These are frozen-weight rebuilds; they do not demonstrate bit-identical model retraining or cross-platform floating-point identity.
- The builder uses challenge tracking and automatic tags, and does not call challenge public-label evaluation or load match video. It verifies the frozen model and base-parameter hashes when the plan is present. It does not enforce every recorded inference/network/decoder code hash; an archived source version and complete artifact manifest remain necessary for a publishable rebuild package.
- The neural weights and experimental code are currently local research artifacts. Publishing a model would require bundling the exact weights, source/dependency pins, rebuild command and data provenance; a local CSV alone is not the requested reproducible public repository submission.
- Existing tier0_v20 CSV remains unchanged: SHA256 `2214a07626dda7c6ce5bca5356548df36b01f4aab534636be5031226bd685a6f`.

## Final decision

The neural candidate is the strongest observed new result and deserves preservation. It is **not approved as a significantly better replacement under the existing gate**. Keep tier0_v20 for submission unless the team explicitly elects to accept this unresolved model-selection risk; do not quietly redefine success. Stop experimentation at the agreed time and reserve the remaining deadline buffer for review and submission integrity. Deadline: 17 November 23:59 CET = 18 November 04:29 IST.
