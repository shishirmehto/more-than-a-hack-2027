# Independent second review: three-seed neural ensemble

**Decision: appropriate to share as a separate review-only candidate, with the uncertainty below. This review does not approve automatic submission or establish a statistically significant new winner. Stop further PFF-driven trials.**

Reviewed the frozen plan, selection, development/target rows and summaries, constituent and data-size ablations, research/export code, inference-parity evidence, and both actual rebuilt CSV files. No model trial or new target metric evaluation was performed for this review; existing per-game scores were independently aggregated and bootstrapped to check the claims.

## Results and claims

| PFF world | Ensemble | PR3 neural | v20 | Gain vs PR3 | Lower vs PR3 | Gain vs v20 | Lower vs v20 |
|---|---:|---:|---:|---:|---:|---:|---:|
| m0 | 0.537771316 | 0.528864069 | 0.512602901 | +0.008907247 | +0.003599270 | +0.025168415 | +0.014049792 |
| m2 | 0.591661889 | 0.581368013 | 0.555322913 | +0.010293875 | +0.004568899 | +0.036338975 | +0.024136115 |

I independently reproduced these paired 50,000-resample lower bounds from `pff-rows.json` using seed 77125 and quantile 0.0125. Each world contains 32 distinct games; m0 and m2 share the same matches and are not 64 independent games.

The old numeric gate (mean gain at least 0.01 and lower bound strictly greater than 0.005 in both worlds) **passes against v20**. It **does not pass against PR3**: m0 mean gain is below 0.01 and both PR3-relative lower bounds are below 0.005. The ensemble protocol declared a development-selection rule, not a new successful statistical acceptance threshold against PR3. Do not conflate the two reference comparisons or change their thresholds afterward.

The user's concern about overfitting is justified as a methodological risk, not proof that the model has failed. PFF-B has repeatedly informed research choices. Although this ensemble was selected using external tracker development before its own target scores, the overall research program was adaptive to previous PFF results. These bootstrap bounds describe variation among the existing games for this fixed comparison; they do not account for the search or supply a fresh-test guarantee. “Best observed reused-validation score” is supportable. “Proven generalization gain,” “independent holdout winner,” and a fresh-test statistical significance claim are not.

## Protocol and data checks

- Seeds 98117/98118/98119 and mean/geometric/median combinations were recorded in the plan before this ensemble's scored results. Only the arithmetic mean passed the declared external source gate. All three seeds entered the ensemble; there is no evidence here of selecting a favorable individual seed using PFF results.
- The ensemble plan and the data-size plan retain script hashes matching the current `run.py` files. Recorded creation times and the code's refusal to overwrite an existing plan support the sequence, but are local records rather than an externally timestamped preregistration. The ensemble plan openly arose after inspecting the first learning-curve seed; it should not be described as a wholly prespecified research program.
- All three selected weight hashes match the actual artifacts. Full-data target fits use the same 30 external games and 144,000 sampled/augmented rows. There are not 90 independent games or 432,000 independent observations: the three models reuse the same data with different optimization seeds.
- The 36 data-size fits have disjoint training-game and held-out-tracker lists. Full-size training counts are 23 games when IDSSE is held out, 27 for Metrica, and 10 for SkillCorner. Fractions are rounded separately by source; for the first seed, quarter-size counts are 6/7/3 respectively. The fixed 600-step budget makes this a fixed-compute, new-component learning curve, not equal epochs or an estimate of the best achievable performance at every size.
- New scaler/network/transition weights exclude the held-out tracker during external development and exclude PFF during fitting. Inherited v22 baseline heads were fitted on Metrica/IDSSE and retain historical PFF-informed heuristic constants. Whole-pipeline tracker independence is therefore incomplete. Synthetic Metrica/IDSSE visibility variants and repeated conventions do not add independent matches.
- The external ensemble improves over the best individual source-average score by approximately 0.000990 Metrica, 0.003247 SkillCorner, and 0.000798 IDSSE. This is useful evidence of predictive complementarity across these models. With three seeds and reused development data it does not prove that variance reduction is the causal mechanism. Individual full-data seeds were not all separately evaluated on PFF, so do not claim the ensemble beats the best individual PFF seed.
- This ensemble uses three networks and more total fitting/inference compute than PR3. Its comparison should be described as an ensemble experiment, not solely a gain from more training data.

## Inference and reproduction

The exported ensemble reproduces the research arithmetic mean of team-symmetrized probabilities followed by the same quality-gated sequence decoder, H50 fallback, and restart fill. The loader verifies each selected weight hash and asserts equal stored transition matrices. It uses challenge tracking/automatic tags without calling challenge label evaluation or reading match video.

Recorded parity checks are exact for m0 and m2 cases of **the same 88,439-frame physical half**. This is a narrow implementation parity check, not all PFF halves or extra generalization evidence.

I independently compared the two actual challenge CSVs: full bytes identical, SHA256 **`c21c56cd76c1da343613c2c5367f60ad6a47d671395b6425dcd5117ec83bac03`**. The recorded rebuild proof reports 199,319 rows and preservation of v20 and PR3. These are frozen-artifact rebuilds, not proof of bit-identical retraining or cross-platform inference.

The exported loader pins network weights but does not itself pin the inherited base JSON or imported network/decoder source. A review PR should bundle the exact weights, base/source and dependency versions, input provenance, rebuild command and verified CSV hash. This is a release-integrity requirement; it is not a reason for another model trial. Before any submission, review the actual PR bundle against those requirements and keep the existing submission unchanged until the team makes its decision.

## Sharing recommendation

Share this as a separate, reproducible candidate with the table and validation caveat prominent. Its observed gains and frozen pre-target ensemble selection justify review. They do not resolve adaptive-validation bias or establish performance on the challenge's unseen tracker. Keep PR3 and v20 available, make no automatic replacement, and preserve time for the team's final review and submission checks.
