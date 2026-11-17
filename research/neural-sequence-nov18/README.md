# Neural candidate for Shishir’s submission decision

This PR offers `quality_sequence` as an alternative; it does not replace FlickGPT.csv or change the default submission. Shishir should choose which model to submit.

| Same 32 PFF-B games, spellF1 | tier0_v20 | Neural | Gain | Games won |
|---|---:|---:|---:|---:|
| m0 | 0.512603 | 0.528864 | +0.016261 | 25/32 |
| m2 | 0.555323 | 0.581368 | +0.026045 | 26/32 |

Ashwin’s preference is to consider the neural candidate because both observed scores improve. Independent second review recommends retaining v20 under the original strict gate. The m0 paired-bootstrap lower bound is 0.004794307, below the required >0.005; m2 is 0.014256849. The gate was NOT changed or passed. PFF-B was reused adaptively: these exploratory bounds do not establish fresh-test significance. The same games under m0/m2 are not 64 independent matches.

## Method and provenance

NumPy MLP, 147 temporal features over ±15 seconds, 64 tanh units, 3 outputs (home/away/dead), untempered sequence decoding. Exact H50 rule fallback where movement or shape is missing. New network, normalization and transition weights fitted on 30 external games: 3 Metrica, 20 SkillCorner, 7 IDSSE; no PFF labels fit those weights. Inherited v22 heads were fitted on Metrica/IDSSE, and heuristic constants have historical PFF-informed provenance, so whole-pipeline tracker independence is NOT claimed. Development includes synthetic visibility variants, not 80 independent games. No challenge labels/video selected this model.

Exact training-source IDs and exclusions are in tracker-exclusion-audit.json. Metrica source: https://github.com/metrica-sports/sample-data ; SkillCorner source: https://github.com/SkillCorner/opendata (4340d274572876239c154c90bc507a9b3250a656); IDSSE source: https://huggingface.co/datasets/pysport/idsse-data/tree/a715a38dfbaf5f58e431727c2b78d174101a703c . Inherited base: params/tier0_v22_pfffree.json. Full second-review findings are in SECOND_REVIEW.md.

## Rebuild the CSV

Source base commit: b67a2837467327f2cbbd489963cf2cc72151e4c2. Tested with Python 3.11.15, NumPy 2.4.6 and pandas 3.0.6 on macOS ARM. Challenge files must be arranged as described in the repository README; pass that data root below. No external training datasets are needed for frozen inference.

```sh
python3.11 -m venv .venv-neural
.venv-neural/bin/pip install -r research/neural-sequence-nov18/requirements.lock
.venv-neural/bin/python research/neural-sequence-nov18/rebuild.py --data /absolute/path/to/data --out /tmp/FrozenNeural.csv
```

The wrapper verifies all packaged hashes, then the builder verifies weights/base hashes, runs inference, validates official CSV format and checks the resulting bytes. Expected 199,319 rows, SHA256 `a0c7a8d5cf90786e736936ccaac6ebf37e27afae30adea1733123eb62695ca68`. Two independent local process rebuilds already matched. Exact bytes on other numerical platforms are not yet demonstrated. No bit-identical retraining claim; frozen weights are published here.

Deadline reported to the team: 17 November 23:59 CET = 18 November 04:29 IST. Please make the final submission choice. Existing v20 remains unchanged.
