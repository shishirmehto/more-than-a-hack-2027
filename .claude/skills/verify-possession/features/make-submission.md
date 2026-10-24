# Build the submission

`make-submission` turns the committed `evaluation/results/baseline_raw.csv` and a params JSON into a 199,319-row `frame,label` CSV that the organisers' validator accepts. The same inputs must give the same bytes on every run, because the repo has to regenerate the submitted file exactly.

## Sub-features

- `submission-build` writes the CSV from a params file.
- `submission-stable` rebuilds it byte for byte.
- `submission-valid` passes `evaluation/validate_submission.py`.
- `submission-public` scores on the public 5-minute window with `evaluation/run_evaluation.py`.
- `submission-refuse` refuses output names matching `baseline_*.csv` or `*_possession_gt*`.

## How to get to it (user POV)

- Run `.venv/bin/python -m possession make-submission --params <params.json> --out <file.csv>`.
- Judge the file with `.venv/bin/python evaluation/validate_submission.py <file.csv>` and `.venv/bin/python evaluation/run_evaluation.py --results <folder> --out <folder>`.

## Driving it with run.sh

Preconditions:

- The doctor prints no `FAIL` line. Metrica data is not needed.
- `EV=data/derived/verify/$RUN_ID` and `mkdir -p "$EV/sub"`.

- **Build.** Run `$V/run.sh "$RUN_ID" build-v0 .venv/bin/python -m possession make-submission --params params/tier0_v0.json --out "$EV/sub/tier0_v0.csv"`. Exit code is `0` and stdout is the output path.
- **Rebuild.** Run `$V/run.sh "$RUN_ID" rebuild-v0 .venv/bin/python -m possession make-submission --params params/tier0_v0.json --out "$EV/tier0_v0_again.csv"`. Then run `$V/run.sh "$RUN_ID" sha bash -c "shasum -a 256 $EV/sub/tier0_v0.csv $EV/tier0_v0_again.csv"`. Both lines show `c471a9b4fe3255c6ca61b741de0b9755765f623879325ee0fe972e7274623def`. For `params/tier0_v1.json` the hash is `0b429a4c74376ae7d186074266e6592eca29976604e51825bfdea273e6635bb7`. For `params/tier0_v2.json` it is `1c384b352b0fe52b02b7ada76d572dff90571e2b215b1ea9941f702972356d8d`. `params/tier0_v3.json` needs the gated ATD on disk and hashes to `79dbf0ec7be9484d7c1ede7ca42c7b6ddcab8c46812eb535f727cc76bb74c8de`, `params/tier0_v4.json`, also gated, to `134851b7a8326e796794fa23c2ee5427e7690b02c6b97c37ff49cb7500a55616`, `params/tier0_v5.json`, also gated, to `a74c545140b43b8cc996fcb2cfac35bfe9e243b1e507c6330c2058d8dbe9fcbd`, `params/tier0_v6.json`, also gated, to `02125f8c5d93a4676f75cd3b7ea7d04375c0e65f1a3431380e3c5d03e919a042`, and `params/tier0_v7.json`, also gated, to `554e4e5b06f3328bb035dab6000abfba9e6390a313aacbf7ba4ae1778499637b`; with `MTAH_DATA_DIR=/nonexistent` its build stops with the `games.require` IOError.
- **Validate.** Run `$V/run.sh "$RUN_ID" validate .venv/bin/python evaluation/validate_submission.py "$EV/sub/tier0_v0.csv"`. Exit code is `0`. stdout starts with `OK    tier0_v0.csv`, reports `199319 rows, frame 0..199318`, and includes the line starting `Valid.`
- **Public score.** Run `$V/run.sh "$RUN_ID" public .venv/bin/python evaluation/run_evaluation.py --results "$EV/sub" --out "$EV/eval"`. The row for `tier0_v0` shows macroF1 `0.5898`, spellF1 `0.4118` and `17` predicted possessions. `$EV/eval/scoreboard.csv` exists.
- **Refuse.** Run `$V/run.sh "$RUN_ID" refuse .venv/bin/python -m possession make-submission --params params/tier0_v0.json --out "$EV/baseline_x.csv"`. Exit code is `1`, stderr ends with `ValueError: refusing to write baseline_x.csv: matches 'baseline_*.csv'`, and no `baseline_x.csv` exists in `$EV`.

## Gotchas

- `run_evaluation.py` scores every CSV in `--results`. Keep only the files you mean to score in that folder. That is why the rebuild goes to `$EV`, not `$EV/sub`.
- The public window has 17 possessions. Use it to prove correctness (alignment, format, label meaning), never to rank two configs.
- A different sha256 for `tier0_v0` means the submission path changed. Treat that as a failure unless the commit says it changed on purpose.
- `make-submission` reads only committed inputs. It needs no Metrica data and no RNG, so a failure here is never a data problem.
