# Three-seed neural ensemble — separate review candidate

Shishir: choose between v20, PR3 and this candidate. This branch does not replace FlickGPT.csv or alter the default build. It is an option for review, not a certified fresh-test winner.

| Same32 PFF-B games, spellF1 | v20 | PR3 neural | Three-seed mean |
|---|---:|---:|---:|
| m0 | 0.512603 | 0.528864 | 0.537771 |
| m2 | 0.555323 | 0.581368 | 0.591662 |

Gains versus PR3: +0.008907 / +0.010294; wins23/32 and24/32. Descriptive paired lower bounds:0.003599 /0.004569. Both observed scores improve. The original numeric threshold (gain>=.01 and lower>.005 in both conditions) passes against v20, but NOT against PR3. Thresholds were not relaxed. PFF-B has been reused adaptively across the research search. These bounds do not correct for that search or establish fresh-test significance. User explicitly raised validation-overfitting concerns; further PFF-driven trials were stopped. Read SECOND_REVIEW.md before deciding.

## Exact method and controlled ablations

Arithmetic mean of class probabilities from three independently seeded147-input,64-tanh,3-output networks. Seeds98117/98118/98119 fixed before ensemble evaluation. Each uses the same30 external games, source/game balance,600 Adam steps,batch1024. Team-swap averaging, same quality fallback and same sequence decoder as PR3. No PFF labels fit new weights. Mean/geometric/median ensembles were compared on external tracker-excluded cases; only the external-selected mean was then scored on PFF. No PFF seed ranking selected individual weights.

The data-size ablation varied only nested per-source training-game fractions25/50/75/100%, with three seeds and fixed600-step compute:36 fits. Full data beats quarter data on each tracker average; gains plateau around50–75% for some trackers. This does NOT prove larger data always helps or establish a causal variance-reduction mechanism. The ensemble beats each constituent on external source-average spellF1, supporting predictive complementarity. Three seeds are insufficient for strong claims about training variance.

New-component training uses3 Metrica,20 SkillCorner and7 IDSSE games. Entire evaluated tracker excluded from new neural/scaler/transition fits. Inherited v22 heads remain fixed and saw Metrica/IDSSE; historical heuristic constants were PFF-informed. Synthetic visibility masks and mirrored samples are not independent matches. Source URLs/revisions and exclusions follow the previous candidate, with exact game IDs in tracker-exclusion-audit.json and data-size-ablation/fits.json.

Sources: https://github.com/metrica-sports/sample-data ; https://github.com/SkillCorner/opendata (4340d274572876239c154c90bc507a9b3250a656); https://huggingface.co/datasets/pysport/idsse-data/tree/a715a38dfbaf5f58e431727c2b78d174101a703c . Supplied challenge labels/video were not used for selection. External data and its permitted use must remain documented in the team technical submission.

## Rebuild

Base commit:b67a2837467327f2cbbd489963cf2cc72151e4c2. Tested Python3.11.15/macOS ARM, NumPy2.4.6,pandas3.0.6. Challenge files arranged according to repository README; no external training datasets needed for frozen inference.

```sh
python3.11 -m venv .venv-neural
.venv-neural/bin/pip install -r research/neural-seed-ensemble-nov18/requirements.lock
.venv-neural/bin/python research/neural-seed-ensemble-nov18/rebuild.py --data /absolute/path/to/data --out /tmp/NeuralEnsemble.csv
```

Wrapper verifies all packaged and inherited code hashes, loads three frozen networks, validates official CSV format and checks exact expected output. Two independent local process builds match:199,319 rows, SHA256 c21c56cd76c1da343613c2c5367f60ad6a47d671395b6425dcd5117ec83bac03. Export parity checked on both PFF conventions for one physical half. No cross-platform exactness or bit-identical retraining claim. Challenge raw data and external tracking are not included.
