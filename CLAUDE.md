# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This is our fork of Metrica Sports' starter repo for **More than a Hack 2027, Phase 1: Ball Possession**.
The task: label every frame of one LaLiga match (Barcelona = home `H`, Athletic = away `A`) with who has
the ball, as a `frame,label` CSV of exactly 199,319 rows using `H` / `A` / `D` (dead ball) / `X`
(abstain). Our solution code, its submission file and the technical document all live here, and the
repo must stay public and reproduce the submitted file exactly.

## The AI-model boundary: Claude helps build the algorithm, never labels

The competition terms restrict giving the match data to cloud-hosted AI models. The organisers
clarified to us on 2026-10-21 where the line is. A cloud model must not produce or score the
possession labels. Claude may inspect the data as a coding partner to improve the algorithm.
Therefore:

- Claude may read and analyse files under `data/` (or `$MTAH_DATA_DIR`) to learn formats, debug
  alignment, study failure cases and design features. Pull only what the question needs, such as
  summaries, small samples or specific frame ranges, never bulk dumps.
- Claude never produces labels. No model, including Claude, decides possession for frames, whether
  by reading tracking rows or by looking at video. Every label in a submission must come from code
  in this repo. This is also rule 1 in `RULES.md`, which bans hand annotation and frame-by-frame
  hand correction.
- The pipeline must never send match data to a cloud LLM or vision API at runtime. Use local models
  only.
- Never commit `data/` or anything that reconstructs it, such as frame-level tracking exports or
  clips. The repo is public. `.gitignore` already excludes `data/*`, `*.mp4`, and
  `evaluation/results/*.csv` (except the baselines).
- Never use the private full-match ground truth.

## Commands

The environment is `.venv`, on Python 3.11. The scorer is tested on Python 3.8 and 3.11, and system
Python here is 3.14.

```bash
source .venv/bin/activate
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements-starter.txt   # recreate

python evaluation/run_evaluation.py                      # score every CSV in evaluation/results/ vs the public 5 minutes
python evaluation/run_evaluation.py --bootstrap 1000     # confidence intervals; use before trusting any gap
python evaluation/run_evaluation.py --results <dir>      # score only the CSVs in <dir> (score one file by putting it alone there)
python evaluation/validate_submission.py <file>.csv      # the exact checks the official scorer runs
python starter/baseline.py [--window 25 50]              # rebuild baselines from the ATD (needs data/)
python starter/make_dummy_submission.py                  # trivial valid submissions; needs no data
```

There is no test suite or linter. The sanity check is the scorer reproducing the README board on a
clean checkout: `baseline_smooth125` scores macroF1 0.5812 and spellF1 0.4242 on the public window.
The scorer writes `evaluation/scoreboard.csv` and `evaluation/reports/`, both gitignored.

## Architecture

- **`games.py`** is the single source of truth for match constants and asset paths, and uses only
  the standard library. Every filename comes from `asset_paths()` and `require()`. Never hard-code
  a data path. `MTAH_DATA_DIR` relocates the whole bundle.
- **`evaluation/`** is the organisers' official scorer, unmodified. `possession_metrics.py` is the
  metric specification, and it wins wherever it disagrees with `EVALUATION.md`. Don't edit
  `evaluation/` or `games.py`: local scores must match what the organisers compute. Pull their fixes
  from `upstream` instead. The scorer depends only on numpy and pandas.
- **`starter/`** holds the loaders and the baseline. `load_atd.py` uses kloppy, `load_smart_tagging.py`
  is stdlib-only, `load_homography.py` provides `load()` and `project()`, and `baseline.py` parses
  the raw ATD with numpy alone. The notebooks are `01_` to `03_`.
- **`evaluation/results/`** is where submissions go. Each CSV is scored under its filename.

### Frame alignment

Submission row `i` is tactical-video frame `i` (`0 … 199318`). Everything else maps onto it:

| source | to a submission row |
|---|---|
| ATD `frame_id` (`1 … 199319`) | `frame_id - 1` |
| Smart Tagging `<start>`/`<end>` seconds | `round(seconds * 25)` |
| homography `frame` | already a row |
| broadcast video, ATD, homography | **no mapping**: separate 164,488-frame timeline with cuts and replays |

The per-half `offsets` in `games.py` (about 1.7M) belong to the ground truth's internal IdFrame
counter. Participant code doesn't need them. A file with about 164k rows was indexed off the
broadcast by mistake.

Graded frames are `11185–90651` and `110808–190197` (`games.half_video_blocks`). The second half is
graded from 110,808 but kicks off at 113,742, so those 2,934 graded frames are all `D`. Ungraded
frames should be `X`.

## What the metric rewards

- **The ranking metric is `spellF1`.** A possession is a maximal run of `H` or of `A`, and `D` is a
  stoppage. Predicted possessions are matched one-to-one by temporal IoU, and F1 is averaged over
  IoU thresholds 0.3 to 0.7. `macroF1` over H/A/D breaks ties. Per-frame flicker splits possessions
  and destroys `spellF1` even when `macroF1` looks fine.
- **On graded frames, `X` is forward-filled** with the last label in that half before `spellF1` is
  computed, and it counts as a miss for `macroF1`. Abstain through occlusions inside a possession.
  Guess at hand-overs.
- **The public window has only 17 possessions.** Use it to check correctness: alignment, file
  format, label meaning. Don't use it for model selection. `smooth125` wins on the public window
  but loses to `smooth50` on the full match. spellF1 noise is about ±0.04.
- **The floor to beat is `baseline_smooth50`**, at full-match spellF1 0.2433.
- **Data traps:**
  - The ball is missing on 41% of graded frames.
  - There are 46 anonymous track slots and no player identity.
  - Smart Tagging is automatic, its intervals are phases rather than possessions, and `Team` is
    `N/A` on every throw-in.
  - Tag columns are title case, so match tag strings case-insensitively.

## Submission

Submission instructions arrive by email by Nov 14, and the deadline is **Nov 17, 2026, 23:59 CET**.
There are three deliverables:

- `<team_name>.csv`
- this public repo, which must regenerate that CSV byte-for-byte (seed everything)
- a short technical document, `<team_name>.pdf` or `.md`, covering:
  - the approach
  - the assets used and the ones dropped
  - the possession rules
  - limitations
  - reproduction steps

`*.pdf` is gitignored. All team members must register under the same team name before Nov 10.

## Git

- `origin` is the `shishirmehto` fork over HTTPS, pushed through a repo-local credential helper
  (`gh auth token --user shishirmehto`).
- `upstream` is `metrica-sports/more-than-a-hack-2027`. Sync with
  `git fetch upstream && git merge upstream/main`.
- Commits use the repo-local personal identity that is already configured. Don't change the repo's
  git config, use the global or work identity, or run `gh auth switch`.
