# Search decoder settings

`fit-dev` grid-searches decoder settings on Metrica dev worlds and keeps the candidate whose worst pooled spellF1 across the worlds is highest. It writes the chosen decoder as a params JSON and the whole grid as `<stem>_grid.csv` next to it, and prints the top rows.

## Sub-features

- `fit-grid` crosses the axis lists into candidates and scores each on every world.
- `fit-params` writes a params JSON that `make-submission` accepts.
- `fit-table` writes one grid row per candidate, ranked.

## How to get to it (user POV)

- Run `.venv/bin/python -m possession fit-dev --out <params.json> [--rule KEY ...] [--dead-bias X ...] [--seed N ...] [--temper ...] [--poss-mean-s ...] [--dead-mean-s ...] [--belief ...] [--q ...] [--p-dead-after-poss ...] [--p-flip-after-dead ...] [--map-temper ...]`.

## Driving it with run.sh

Preconditions:

- The doctor reports `Metrica sample data 9/9 files`.
- `EV=data/derived/verify/$RUN_ID` and `mkdir -p "$EV/fit"`.

- **Small grid.** Run `$V/run.sh "$RUN_ID" fit .venv/bin/python -m possession fit-dev --rule h3p3 h5p3 --dead-bias 1 --seed 0 --temper 0.05 0.1 --poss-mean-s 6 --dead-mean-s 10 --belief 1 --map-temper --out "$EV/fit/probe.json"`. Exit code is `0` in a few seconds. The last line of `fit.out` reads `2 candidates x 2 worlds in <n> s`.
- **Outputs.** `$EV/fit/probe.json` and `$EV/fit/probe_grid.csv` exist. The grid CSV has a header and 2 rows, with `rank` 1 and 2.
- **Provenance.** Run `$V/run.sh "$RUN_ID" fit-provenance .venv/bin/python -c "import json, sys; print(json.load(open(sys.argv[1]))['provenance']['dropout_calibration'])" "$EV/fit/probe.json"`. stdout reads `{'dead_bias': 2.6, 'dead_bias_bracket': [1.0, 4.0], 'prekickoff_frames': 2934, 'prekickoff_missing': 564, 'window_frames': 155923, 'window_missing': 64079}`.
- **Params load.** Run `$V/run.sh "$RUN_ID" fit-load .venv/bin/python -m possession make-submission --params "$EV/fit/probe.json" --out "$EV/fit/probe_submission.csv"`. Exit code is `0`.

## Gotchas

- Every axis takes a list. Omitting `--q`, `--p-dead-after-poss` or `--p-flip-after-dead` keeps v0's value (0.78, 0.25, 0.7). Omitting `--temper`, `--poss-mean-s`, `--dead-mean-s` or `--belief` searches its default grid. Give one value to hold an axis fixed.
- `--map-temper` with no values skips the MAP sub-grid. Its default adds a second sub-grid that doubles the run time or more.
- The defaults (`--rule m0 m2`, 4 tempers, 4 possession means, 3 dead means, 2 beliefs, and MAP) build 288 candidates and take minutes. Run large grids in the background.
- `--dead-bias` defaults to the measured bracket `1 4` (`dropout.CALIBRATION.dead_bias_bracket`), and the params JSON records the whole calibration under `provenance.dropout_calibration`.
- The params JSON records the command and the sweep time. Its bytes change between reruns. Its decoder fields do not.
- Never write `--out` into `params/`. That folder holds committed decoders.
