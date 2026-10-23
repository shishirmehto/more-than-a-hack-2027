# Possession labeller verification map

This folder is the maintained source for verifying what a user of the `possession` CLI can do. Read this index first, then use the matching feature file as the recipe.

## Baseline preconditions

- Run from the repo root with `.venv/bin/python` (Python 3.11).
- `.claude/skills/verify-possession/scripts/doctor.sh` prints no `FAIL` line.
- `V=.claude/skills/verify-possession/scripts` and `RUN_ID` are set for this run, and every command goes through `$V/run.sh "$RUN_ID" <label> ...`.
- The dev features (`score --dev`, `fit-dev`, `sweep`, `python -m possession.metrica`) need the doctor to report `Metrica sample data 9/9 files`.
- `measure` and the full `selfcheck` also need the doctor to report `tactical ATD and Smart Tagging 3/3 files`.

## Driving conventions

- Treat every command as literal. Keep flags and file names unchanged.
- Write outputs into `data/derived/verify/$RUN_ID/` (or under `$MTAH_DATA_DIR/derived/verify/$RUN_ID/`). Call that folder `$EV` below.
- Never write into `evaluation/results/`, and never run `run_evaluation.py` without `--results` and `--out`.
- Expected numbers below were measured at commit `4832bf7`, except `measure.md`, `selfcheck.md`, `fit-dev.md` and the dev numbers in `score.md`, which were measured at `c47c308`. If a later commit changes a number on purpose, the change belongs in `possession/DESIGN.md` and in this map in the same commit.

## Proof and skip reporting

- CLI proof is the `.cmd`, `.out`, `.err` and `.exit` files that `run.sh` writes.
- File proof is a sha256, a validator result or a second command that reads the file back.
- Record the feature ID with every claim, for example `submission-stable`.
- If a precondition is missing (no Metrica data, no network for `fetch-metrica`), report the feature as not verified with the unmet precondition. Do not report it as verified through another path.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behaviour. It then uses exactly four H2 sections in this order: `Sub-features`, `How to get to it (user POV)`, `Driving it with run.sh`, and `Gotchas`.

## Features

- [Build the submission](./make-submission.md) covers building, byte-stable rebuilds, validation, the public-window score and refused file names.
- [Run the self-checks](./selfcheck.md) covers the invariant checks with and without the Metrica data.
- [Score decoders](./score.md) covers dev-world and public-window scoring and the paired comparison.
- [Search decoder settings](./fit-dev.md) covers the grid search and its params and grid outputs.
- [Prepare the Metrica dev data](./metrica-dev-data.md) covers the pinned download and the label acceptance tables.
- [Measure the match observation](./measure.md) covers the match-wide aggregates behind the generator's constants and the counted decoder constants.

Not yet mapped: `sweep` (the generator dead_bias by decoder belief table). Its worlds and beliefs default to `1 1.8 3` (`dropout.CALIBRATION.surface`).
