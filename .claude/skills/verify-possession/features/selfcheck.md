# Run the self-checks

`selfcheck` runs the package's invariant checks and prints one line per check with `ok`, `skip` or `FAIL`, then a summary line. Checks that need the Metrica sample data or the tactical ATD skip cleanly when it is absent.

## Sub-features

- `selfcheck-data` runs every check with the Metrica sample and the tactical ATD present.
- `selfcheck-nodata` runs with no data and skips only the data checks.

## How to get to it (user POV)

- Run `.venv/bin/python -m possession selfcheck`.

## Driving it with run.sh

Preconditions:

- The doctor prints no `FAIL` line.

- **With data.** Run `$V/run.sh "$RUN_ID" selfcheck .venv/bin/python -m possession selfcheck`. Exit code is `0`. The last line of `selfcheck.out` reads `22 ok, 0 skip, 0 FAIL` at the commit that adds `idsse_reproduces_feed_counts`. It needs the Metrica sample, the IDSSE files, the tactical ATD and Smart Tagging under `MTAH_DATA_DIR`.
- **Without data.** Run `$V/run.sh "$RUN_ID" selfcheck-nodata env MTAH_DATA_DIR=/nonexistent .venv/bin/python -m possession selfcheck`. Exit code is `0`. The last line reads `16 ok, 6 skip, 0 FAIL` at the same commit. Three `skip` lines name the missing `metrica_sample` folder and one names the missing `external/idsse` folder. `atd_reproduces_baseline_raw` and `measure_pins_calibration` name the missing `tactical` folder.

## Gotchas

- Put `env MTAH_DATA_DIR=/nonexistent` after the label, never before `$V/run.sh`. Set before it, the variable also moves the evidence folder to `/nonexistent`, and the run fails.
- The pass criterion is `0 FAIL` with the expected skips. The check count changes when a commit adds or removes a check, so compare the names in `selfcheck.out` with the previous run before trusting a new count.
- `submission_is_byte_stable` builds two submissions and takes about 1 s. The whole run takes about 8 s with data.
- `measure_pins_calibration` compares the real ATD and Smart Tagging with literal counts and with `dropout.CALIBRATION`. A failure there after a re-export of the gated files means the generator's constants need a new measurement, not a looser check.
