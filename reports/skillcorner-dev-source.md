# SkillCorner Open Data as a dev source

2026-10-27. `possession/skillcorner/` loads SkillCorner Open Data
([github.com/SkillCorner/opendata](https://github.com/SkillCorner/opendata), MIT, commit `4340d27`):
20 A-League 2024/25 matches of broadcast tracking at 10 fps. The loader plugs into the bench in the same
way as `possession/idsse/`, under the world key `skillcorner:m0`. The bench uses SkillCorner only when a
run names it. It is not in rule v2's veto or ranking lists. Adding it there is the team's decision.
No SkillCorner file, frame-level export or BAR-ATH label is in this commit.

## What the loader does

- **Files.** It reads `{id}_tracking_extrapolated.jsonl`, `{id}_phases_of_play.csv` and `{id}_match.json`
  for each match. It checks all 60 files against `possession/skillcorner/manifest.json`, the same sha256
  values as the fetch script at `d6b7de2`, and caches them as `.npz` under `<data dir>/derived/skillcorner`.
- **Halves.** It uses periods 1 and 2, taken from each tracking row's `period` field. Rows with a null
  period (before kickoff, at half-time, after the end) are dropped.
- **Labels, at 10 fps.**
  - `D` outside every phase of play. The README says phases are "only defined when the ball is in play".
  - Inside a phase, `H` for `possession.group == "home team"` and `A` for `"away team"`.
  - Inside a phase with a null group, `X`, because no label is defined there. A Case's ground truth
    leaves `X` unscored, so `CleanHalf` now accepts `X`. No other source emits it.
  - Phase spans are half-open `[frame_start, frame_end)`. On every row, `duration == (end - start) / 10`,
    and abutting phases share the boundary frame.
  - A phase counts only on frames of its own period. In 16 of the 20 matches, the last first-half phase
    runs past half-time into frames the tracking already marks as period 2 (881 frames in total).
- **Kickoff and block.** Kickoff is the first in-phase frame, and the block ends after the last one, as
  for PFF.
- **Rules.** The loader takes `m0` only. A merge rule would merge across the in-play `X` frames, and the
  controlled rules need Metrica's events.
- **Resampling from 10 to 25 fps.** This reuses `pff.ticks` and `pff.at_ticks`. Tick `k` sits at `k/25` s.
  - Labels and detection flags come from the nearest source frame.
  - Positions are linear between the two source frames around the tick. Where either of the two is
    missing, the nearest frame is used, so a missing ball or player is never invented.
  - `pff.undouble` is not applied. Only 0.24% of consecutive ball positions repeat, so SkillCorner does
    not hold positions over two frames as PFF's tracker does.
- **Coordinates.** The source origin is the centre spot with y up. The loader shifts it to the top-left
  corner with y down, as for IDSSE.
- **Player slots.** There is one slot per roster player present in the period: home, then away, each
  sorted by id. An unknown player id or a null `is_detected` raises.
- **Version check.** No file carries a spec version. The `game_interruption_before`/`_after` inversion in
  older spec versions concerns `dynamic_events.csv`, which the loader never reads.

## Extrapolated ball and players

- **Ball.** SkillCorner's README documents `is_detected` for players only, but `ball_data.is_detected` is
  in every row. A ball counts as seen only when it has a position and `is_detected` is true.
  `is_detected: false` with a position is an extrapolated ball. A null `x` means no ball at all.
  - Inside play, over 630,230 frames at 10 fps: 93.0% detected, 5.4% extrapolated, 1.7% no position.
  - `native_seen` exposes the detected mask, so `--mode native` works for `--source skillcorner`.
  - The geometry keeps the extrapolated ball and holds the last position through frames with none.
- **Players.** Off-camera players are extrapolated.
  - 43.2% of player positions are extrapolated over the periods, and 35.9% inside play.
  - The loader keeps them in `players_xy`, because dropping them would leave about 14 players a frame,
    which no tracker in the challenge produces. Each half's provenance records the share.

## Summary (labels are SkillCorner's; no BAR-ATH data)

| | SkillCorner | IDSSE | PFF |
|---|---|---|---|
| halves | 40 | 14 | 128 |
| possessions (D or X ends one) | 6,481 (162 per half) | 3,061 (219) | 17,782 (139) |
| possession length, median / mean | 5.5 s / 9.4 s | 3.7 s / 7.2 s | 7.0 s / 12.9 s |
| shorter than 2 s | 24% | 30% | 14% |
| live frames with the ball unseen (native flag) | 7.0% | 0% | 35.3% |
| unseen-ball runs per half, median / p90 length | 52, 1.2 s / 4.5 s | — | 363, 0.7 s / 4.4 s |

- **Label coverage, over 40 periods at 10 fps.**
  - 53.3% of frames are inside a phase.
  - Inside play, 97.1% of frames are H or A and 2.9% are X.
  - The X frames form 1,597 runs with a median of 0.7 s (p90 2.1 s).
  - If X carried the previous team instead, there would be 6,358 possessions with a median of 5.9 s.
- **Cross-check.** Inside phases, `possession.group` names the phase's `team_in_possession_id` on 83.7%
  of labelled frames. A phase can hold possession changes, such as a "chaotic" phase, so this is a sanity
  check, not a convention test.
- **Ball-missing structure.** In its native form, SkillCorner's ball is far easier than BAR-ATH's (41%
  missing on graded frames) or PFF's. The default `renewal` worlds, which the score command uses, run the
  calibrated BAR-ATH dropout over it like every other source. `native` mode is the wrong choice for ranking.

## Scores

`python -m possession score --rule skillcorner:m0 --params params/tier0_v13.json params/tier0_v19.json --baseline 50 --dev --name skillcorner-check`
(renewal dropout at the calibrated dead_bias, seed 0, dev_pooled over 40 halves):

| model | spellF1 | macroF1 | predicted possessions (GT 6,481) | mean length (GT 9.4 s) |
|---|---|---|---|---|
| tier0_v13 | 0.3154 | 0.7096 | 6,391 | 9.5 s |
| tier0_v19 | 0.3181 | 0.7100 | 6,254 | 9.7 s |
| baseline_smooth50 | 0.2287 | 0.6540 | 10,561 | 6.4 s |

- **v13 against smooth50.** v13 beats smooth50 on all 20 matches.
- **v19 against v13.** v19 beats v13 on 14 of 20 matches. The per-match mean difference is +0.0026
  (sd 0.0044).
- **Dropout.** This world's dropout leaves the ball missing on 51.7% of frames from kickoff on.
- **Native mode.** `--rule skillcorner:m0:native` hides only the balls SkillCorner did not detect, which is
  40.4% of frames from kickoff on, mostly dead time. It gives v13 0.3546, v19 0.3593 and smooth50 0.2610.
  That run shows native mode works. It is not a realistic world.

One seed and one world under a convention that neither v13 nor v19 was tuned on. Treat it as a
check that the source runs, not as a ranking.
