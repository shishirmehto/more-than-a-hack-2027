---
name: verify-possession
description: Drive and prove the possession labeller CLI (`python -m possession`) in the More than a Hack 2027 repo. Use it to check that a change still builds a valid, byte-identical submission, passes the self-checks, and scores as expected on the public window and the Metrica dev worlds, with saved command, output and exit-code evidence.
---

# Verify the possession labeller

The user-facing surface is a command-line tool. `python -m possession` builds the submission CSV, runs the invariant checks, scores decoders, searches decoder settings, and prints the match-wide measurements behind the generator's constants. The secondary surfaces are `python -m possession.metrica`, which prints the dev-label acceptance tables, and the organisers' scripts `evaluation/validate_submission.py` and `evaluation/run_evaluation.py`, which judge a submission file. Every command is short-lived. There is no server to keep alive.

Read `features/README.md` before you drive anything. Each feature file there is the recipe for one user path.

## Launch

1. Work from the repo root (`git rev-parse --show-toplevel`). Always call `.venv/bin/python`. Bare `python` is not on PATH on this machine, and the system Python is 3.14.
2. If `.venv` is missing or broken, recreate it with the command in `CLAUDE.md`: `uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements-starter.txt`.
3. Pick a run ID for this verification, for example `RUN_ID=$(date +%Y%m%d-%H%M%S)-<short-purpose>`. Every command of the run uses the same ID.
4. The dev features need the Metrica sample data under `$MTAH_DATA_DIR/metrica_sample` (default `data/metrica_sample`). If the doctor reports it missing, run `.venv/bin/python -m possession fetch-metrica`. It downloads about 183 MB from GitHub at a pinned commit and checks every sha256.

The checkout is ready when the doctor prints no `FAIL` line.

## Doctor

Run `.claude/skills/verify-possession/scripts/doctor.sh` first, and again whenever a result looks wrong. It is read-only. It checks the Python version, the imports, the committed inputs (`baseline_raw.csv`, the public GT, `params/tier0_v0.json`, `params/tier0_v1.json`, the Metrica manifest) and reports the HEAD commit, the dirty path count, the data folder, how many of the 9 Metrica files are present, and how many of the 3 tactical files (`BAR-ATH_tactical_atd.txt`, `BAR-ATH_tactical_atd.xml`, `BAR-ATH_tactical_smart_tagging.xml`) are present. It exits 0 when no check fails. A `skip` line for Metrica data means only the dev features are unavailable. A `skip` line for the tactical files means `measure`'s real-match sections and two self-checks skip.

If you are inside a `.claude/worktrees/...` worktree, the doctor reports that worktree's HEAD. The data folder still defaults to that worktree's own `data/`, which is usually empty, so set `MTAH_DATA_DIR=/Users/shishirmehto/git/more-than-a-hack-2027/data` there.

## Drive

Run every command through `scripts/run.sh` so that its proof is saved:

```bash
.claude/skills/verify-possession/scripts/run.sh "$RUN_ID" <label> .venv/bin/python -m possession <subcommand> [flags]
```

`run.sh` runs the command from the repo root, writes `<label>.cmd`, `<label>.out`, `<label>.err` and `<label>.exit` into the evidence folder, writes `meta.txt` (time, HEAD, dirty count, Python version, data folder) once per run, prints one summary line and exits with the command's own exit code. Use a different label for each command of a run.

The subcommands are `make-submission`, `selfcheck`, `measure`, `score`, `fit-dev`, `sweep` and `fetch-metrica`. `measure` takes no flags. `score`, `fit-dev` and `sweep` take world flags as lists: `--rule` (label rule keys such as `m0`, `m2`, `h3p3`), `--dead-bias` and `--seed`. The feature files give exact invocations.

Isolation rules for parallel runs:

- Write every output file (`--out` of `make-submission` and `fit-dev`) into this run's evidence folder, never into a shared path.
- Give `score` the flag `--name verify-$RUN_ID-<label>`. `score` always writes `<data dir>/derived/runs/<name>.csv`, and the default name collides between runs.
- Never write into `evaluation/results/`. `run_evaluation.py` scores every CSV there, and `baseline_*.csv` files there are committed.
- Run `run_evaluation.py` only with both `--results <folder holding only the CSVs to score>` and `--out <evidence folder>`. Without `--out` it writes `evaluation/scoreboard.csv` and `evaluation/reports/`.

## Evidence

The evidence folder is `<data dir>/derived/verify/<RUN_ID>/`, which is `data/derived/verify/<RUN_ID>/` by default. `data/` is gitignored. Never commit it, because the repo is public and the data must stay private.

Proof standards:

- Drive the real user path, `python -m possession ...` or the organisers' scripts. Do not call package functions from a Python prompt as proof.
- Keep the command, stdout, stderr and exit code for every step. `run.sh` does this.
- Check the side effects, not only the printed text. For a submission that means the file's sha256, `validate_submission.py` on the file, and a public-window score from `run_evaluation.py`. For `fit-dev` it means a params JSON that `make-submission` accepts and a grid CSV with the expected row count.
- Compare numbers against literal expected values written in the feature file. A run that only shows "no error" proves nothing.
- Claude never produces or edits labels. Every label in a CSV must come from the code, and no match data may be sent to any network service.

## Cleanup

Nothing keeps running after a command exits, so there is nothing to kill. Run `.claude/skills/verify-possession/scripts/cleanup.sh "$RUN_ID"` at the end. It deletes only the `verify-$RUN_ID*.csv` files that `score --name verify-$RUN_ID-...` wrote under `<data dir>/derived/runs/`, then lists the evidence folder it kept. It never deletes the evidence folder. Delete an evidence folder by hand only when its proof is no longer needed.

## Helpers

- `scripts/doctor.sh` is the read-only health check. Run it with no arguments.
- `scripts/run.sh <run-id> <label> <command> [args...]` runs one command and saves its proof.
- `scripts/cleanup.sh <run-id>` removes the run's score files outside the evidence folder and lists the evidence.
