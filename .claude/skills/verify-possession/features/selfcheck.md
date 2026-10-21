# Run the self-checks

`selfcheck` runs the package's invariant checks and prints one line per check with `ok`, `skip` or `FAIL`, then a summary line. Checks that need the Metrica sample data skip cleanly when it is absent.

## Sub-features

- `selfcheck-data` runs every check with the Metrica data present.
- `selfcheck-nodata` runs with no Metrica data and skips only the data checks.

## How to get to it (user POV)

- Run `.venv/bin/python -m possession selfcheck`.

## Driving it with run.sh

Preconditions:

- The doctor prints no `FAIL` line.

- **With data.** Run `$V/run.sh "$RUN_ID" selfcheck .venv/bin/python -m possession selfcheck`. Exit code is `0`. The last line of `selfcheck.out` reads `17 ok, 0 skip, 0 FAIL` at commit `4832bf7`.
- **Without data.** Run `$V/run.sh "$RUN_ID" selfcheck-nodata env MTAH_DATA_DIR=/nonexistent .venv/bin/python -m possession selfcheck`. Exit code is `0`. The last line reads `14 ok, 3 skip, 0 FAIL` at commit `4832bf7`, and every `skip` line names the missing `metrica_sample` folder.

## Gotchas

- Put `env MTAH_DATA_DIR=/nonexistent` after the label, never before `$V/run.sh`. Set before it, the variable also moves the evidence folder to `/nonexistent`, and the run fails.
- The pass criterion is `0 FAIL` with the expected skips. The check count changes when a commit adds or removes a check, so compare the names in `selfcheck.out` with the previous run before trusting a new count.
- `submission_is_byte_stable` builds two submissions and takes about 1.5 s. The whole run takes about 6 s with data.
