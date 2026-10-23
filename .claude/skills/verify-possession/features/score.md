# Score decoders

`score` scores one or more params files, and optionally the published smoothing baselines, on Metrica dev worlds and on the public window. It prints one table row per world, model and case, and writes the table to a CSV. With `--paired` it also prints the paired bootstrap spellF1 difference of each later model against the first params file.

## Sub-features

- `score-dev` scores on dev worlds built from label rules, dead_bias values and seeds.
- `score-public` scores on the public 5-minute window.
- `score-baseline` scores `starter/baseline.py`'s majority vote at the given windows beside the params files.
- `score-paired` prints paired deltas with 5th and 95th percentiles.
- `score-csv` writes the table to `<data dir>/derived/runs/<name>.csv`.

## How to get to it (user POV)

- Run `.venv/bin/python -m possession score --params <a.json> [<b.json> ...] [--baseline WINDOW ...] --dev --public [--paired] [--rule KEY ...] [--dead-bias X ...] [--seed N ...] [--name NAME]`.

## Driving it with run.sh

Preconditions:

- The doctor reports `Metrica sample data 9/9 files`.

- **Score.** Run `$V/run.sh "$RUN_ID" score .venv/bin/python -m possession score --params params/tier0_v0.json params/tier0_v1.json --dev --public --paired --rule h3p3 --dead-bias 1 --name verify-$RUN_ID-score`. Exit code is `0`. In `score.out`, the `h3p3_r1` rows on `dev_pooled` show spellF1 `0.3360` for `tier0_v0` and `0.3398` for `tier0_v1`, with `overall` `0.4124`. The public rows show spellF1 `0.4118` for `tier0_v0` and `0.3100` for `tier0_v1`. The paired table shows public `tier0_v1` minus `tier0_v0` as `-0.1018 -0.1665 -0.0406` and `h3p3_r1 dev_pooled` as `0.0038 -0.0100 0.0180`.
- **Baselines.** Run `$V/run.sh "$RUN_ID" score-baseline .venv/bin/python -m possession score --params params/tier0_v0.json --baseline 0 25 50 125 --public --name verify-$RUN_ID-baseline`. Exit code is `0`. The public rows for `baseline_raw`, `baseline_smooth25`, `baseline_smooth50` and `baseline_smooth125` show spellF1 `0.0378`, `0.2868`, `0.3256` and `0.4242`, with `131`, `36`, `26` and `16` predicted possessions. Those are the README board's values.
- **Read back.** Run `$V/run.sh "$RUN_ID" score-csv bash -c "wc -l data/derived/runs/verify-$RUN_ID-score.csv"`. stdout reads `11 data/derived/runs/verify-$RUN_ID-score.csv`: a header and 10 rows (2 models on `dev_g1`, `dev_g2`, `dev_g3` and `dev_pooled`, plus 2 public rows).

## Gotchas

- Without `--dev` or `--public`, `score` exits with an argparse error.
- `--baseline` takes half-widths in frames (25 is one second each side), and 0 is `baseline_raw`. `--params` is still required, and the first params file is the reference for `--paired`. On BAR-ATH the bench's smoother equals the committed `baseline_*.csv` files on every graded frame (`selfcheck.smoother_matches_published_baselines`). On dev worlds it labels pre-kickoff frames too, as the published files do.
- `--rule` takes keys, not numbers. `m0` is the raw rule, `m2` merges spells under 2 s, and `h3p3` is controlled possession at 3 s or 3 passes. A merge rule and a controlled rule cannot be combined in one key.
- The dropout columns on the public row cover only the 7,500 graded frames, so `overall` reads about `0.118`, not the decode-window `0.411`.
- `--dead-bias` defaults to the measured point `2.6` (`dropout.CALIBRATION.dead_bias`), so without the flag the worlds are keyed `h3p3_r2.6`. The recipe passes `--dead-bias 1` to keep the 11-line CSV.
- The dev numbers depend on the generator's defaults. They moved when the target rate became the decode-window `0.4110` (the paired dev delta was `-0.0063 -0.0184 0.0060` at target `0.407`). Both intervals cover zero, so the move is draw noise. The public numbers do not depend on the generator.
- The paired interval resamples GT possessions inside one dropout draw. It does not include the draw-to-draw spread. Add more `--seed` values before trusting a gap under about 0.01.
