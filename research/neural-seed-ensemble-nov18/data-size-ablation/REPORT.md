# Data-size ablation

Only the number of training games changes within each seed block. New scaler, network and transition parameters are refitted on that subset. Architecture,600 optimizer steps,decoder algorithm,evaluation games and visibility variants are fixed. Three seeds; no PFF access.

| Fraction | Held-out tracker | Mean spellF1 | Seed min | Seed max |
|---|---|---:|---:|---:|
| 25% | idsse | 0.522352 | 0.516190 | 0.531822 |
| 25% | metrica | 0.628597 | 0.617429 | 0.649328 |
| 25% | skillcorner | 0.356275 | 0.347570 | 0.362974 |
| 50% | idsse | 0.534584 | 0.528143 | 0.538294 |
| 50% | metrica | 0.636072 | 0.622367 | 0.650460 |
| 50% | skillcorner | 0.368211 | 0.364893 | 0.372090 |
| 75% | idsse | 0.543751 | 0.538391 | 0.547359 |
| 75% | metrica | 0.645610 | 0.638101 | 0.659488 |
| 75% | skillcorner | 0.365879 | 0.357299 | 0.372206 |
| 100% | idsse | 0.547202 | 0.546751 | 0.547441 |
| 100% | metrica | 0.644895 | 0.636452 | 0.649558 |
| 100% | skillcorner | 0.365146 | 0.363551 | 0.367492 |

This is a fixed-compute learning curve, not a guarantee that more data helps. Rounded source counts and actual games/rows are recorded in fits.json. Seed spread measures training sensitivity; it is not a fresh-test confidence interval. Inherited v22 heads are fixed rather than retrained; only new-component training data scales.


Actual full-fraction training game counts: IDSSE held out:23; Metrica held out:27; SkillCorner held out:10. No held-out tracker games enter new-component fitting.

The average curve improves mainly before75%; extra data is useful but does not help every tracker monotonically. Full versus quarter descriptive game-bootstrap comparisons are in paired-size-comparison.json; seed spread above separately shows training/subset sensitivity.
