# Decoder hillclimb, 2026-10-24

A six-hour autonomous run (05:58 to about 12:00 IST) to improve the possession decoder's spellF1 on other
games' labels. Every step, its reason, its evidence and its outcome is a row in
`.audit/hillclimb-2026-10-24.tsv`. The probes behind the numbers are in `probes.py` in this folder, and the
final params are written by `freeze.py`.

## Result

Two new params files, both v1's chain with a dead-ball stage that v1 did not have:

| params | change from tier0_v1 | builds from | sha256 of the CSV |
|---|---|---|---|
| `params/tier0_v2.json` | `dead_min_run` 126, `dead_trim` 50, `dead_close` 150 | committed inputs only | `1c384b352b0fe52b…` |
| `params/tier0_v3.json` | tier0_v2 plus `dead_outside_m` 0.5 | the gated ATD on disk | `79dbf0ec7be9484d…` |

Held-out results, never used to choose anything (spellF1 margin over `baseline_smooth50`; PFF numbers are
the 32 even-indexed games with 90% per-game t intervals):

| world | tier0_v1 | 101/50/0 (smooth50's dead ball) | tier0_v2 | tier0_v3 |
|---|---|---|---|---|
| PFF native m0 (real tracker gaps) | -0.003 | +0.073 | **+0.090** [+0.082, +0.099], 32/32 games | **+0.094** [+0.086, +0.103], 32/32 |
| PFF native m2 | +0.026 | +0.089 | **+0.115** [+0.105, +0.125], 32/32 | **+0.120** [+0.110, +0.129], 32/32 |
| worst synthetic group, seeds 15-24, dead_bias 1 to 4 | -0.005 | +0.016 | +0.017 | not meaningful (see below) |

- tier0_v2 beats 101/50/0 on the held-out PFF games by +0.017 [+0.014, +0.020] and +0.026 [+0.022, +0.030].
- tier0_v3 adds +0.004 [+0.003, +0.005] and +0.0045 [+0.004, +0.005] on top of tier0_v2 there.
- On BAR-ATH, tier0_v3 changes 1,311 frames against tier0_v2 and adds 3 dead runs (122 to 125). That
  comparison reads two automatic CSVs and no labels.

My recommendation is tier0_v3, if the team is comfortable that building the CSV needs the gated ATD files on
disk. Otherwise tier0_v2. The choice of submission decoder is the team's, so neither file is wired into
anything yet.

## Rules this run kept

- Every choice was made on other games' labels: the three Metrica samples, the seven IDSSE (DFL) matches
  and the 64 PFF FC World Cup 2022 games.
- Nothing read the BAR-ATH public window, the README's full-match scores or any BAR-ATH label. The final
  params were committed before any public-window correctness check.
- BAR-ATH's ATD was read only as match-wide summaries of automatic inputs: the ball-seen share, the ball's
  distance to the lines, the team-margin distribution, and the two-CSV comparison above.
- PFF data has no licence file and its specs say proprietary, so it is treated as all rights reserved. It is
  used for local dev scoring only. Only digests and aggregate numbers are committed.

## How the objective evolved

The run started with a frozen objective `J`: the worst group margin over smooth50, where a group is one label
convention under one ball-gap generator, seed-averaged. It ended with a stricter, pre-registered rule. Each
change has its own row in the decision log.

1. **Five synthetic groups at dead_bias 2.6** (Metrica m0, h1p3, h3p3; IDSSE m0, m2). Ball gaps come from the
   renewal generator, which draws gap runs from BAR-ATH's own run pool.
2. **Plus native PFF m0 and m2**, after the synthetic optimum collapsed on real tracker gaps (experiment 4).
3. **PFF games split** into a selection half (A, `games[0::2]`) and a held-out half (B), because all 64 games
   had been in the search set.
4. **Rule v2**, written after an independent review: candidates are v1's chain with run {101, 126}, trim
   {0, 12, 25, 37, 50} and close {0, 100, 150, 200, 300}. The synthetic groups at dead_bias 1, 2.6 and 4 only
   **veto**: a candidate must stay within 0.003 of the incumbent 101/50/0 in every group. The minimum over
   PFF-A **ranks**. Seeds 15-24 and PFF-B **confirm**, pass/fail only.

Why synthetic worlds were demoted from ranking to veto: the renewal generator draws one mask for live frames
and one for dead frames and switches between them exactly at each label boundary
(`possession/dropout.py:227`). Gap edges therefore line up with true stoppage edges far more often than real
gaps do, which rewards a trim of 0. Real gaps run past the restart. On BAR-ATH the ball is missing 61% of the
time in the 5 s after a Smart Tagging restart.

## Experiments

| # | change | why | result | verdict |
|---|---|---|---|---|
| 1 | oracle probes on v1 | find the headroom before tuning | perfect dead ball +0.2 spellF1, perfect team calls +0.2 to +0.4 | work on dead ball and team evidence |
| 2 | v1's chain plus smooth50's dead ball (101/50) | smooth50 finds dead ball far better (f1_d 0.52 against 0.24), v1 calls teams better | J +0.0203 against v1's +0.0015; all 5 groups better | became the incumbent |
| 3 | grid run length and trim | 101/50 was inherited from smooth50 | on synthetic gaps, trim 0 and short runs win (51/0 J +0.0429) | superseded by 4 |
| 4 | 51/0 on native PFF gaps | synthetic gaps are placed independently of play | -0.040 and -0.043 below smooth50, while 101/50 is +0.070 and +0.087 | rejected; PFF joins the objective |
| 5 | fit-idsse-m0 (temper 0.1, poss 3 s, dead 10 s) on 30 seeds | check the earlier IDSSE grid winner | wins IDSSE m0 and m1, loses on IDSSE m2, m3 and every Metrica convention | dropped; the hybrid dominates it |
| 6 | `dead_close`: close short live gaps between dead runs | a ball sighting inside a stoppage splits it into two and leaves a spurious possession | under 101/50, gaps below 100 frames are no-ops; 150 frames lifts all 7 groups | kept as a decoder option |
| 7 | run x trim x close on 7 groups at dead_bias 2.6 | choose the dead rule jointly | 101/0/150 J +0.0465 | withdrawn after 8 and the review |
| 8 | confirm 101/0/150 on seeds 5-14 at dead_bias 1, 2.6, 4 | the pick came from about 160 points | wins at 2.6 and 4, loses to 101/50/0 on PFF (-0.005, 25 of 64 games) and at dead_bias 1 | showed the synthetic bias |
| 9 | team-margin q(m) emission (subagent) | q rose with team margin in a probe | loses on every group, PFF included | rejected |
| 10 | off-pitch D bonuses (subagent) | an off-pitch ball is usually dead | no effect, because the dead-run stage overrides the chain's D | rejected |
| 11 | `dead_outside_m`: a ball seen off the pitch counts as missing | puts the off-pitch cue where it reaches the codes | +0.004 on held-out PFF games | kept in tier0_v3 |
| 12 | rule v2 selection over 50 candidates | pre-registered after the review | 16 pass the veto; 126/50/150 picked (PFF-A +0.084 against +0.069) | tier0_v2 |
| 13 | chain constants (temper, possession mean, dead probability) under the dead rule | maybe the chain wants new constants now | best setting adds +0.0014 J, within noise | v1's chain kept |
| 14 | separate start and end trims | the gap may outlast the restart | no asymmetric trim beats 50/50 without a veto | rejected |
| 15 | posterior fill for chain-D frames | the review found they take the pre-stoppage team | 1.4% of live frames differ, and dev labels agree with each fill equally often | no change |
| 16 | logistic token emission fitted on PFF-A | team calls hold the largest headroom (below) | *pending* | *pending* |

## What did not work, and why

- **Short dead runs and trim 0** looked best on synthetic worlds and failed on real gaps. The synthetic
  generator copies label boundaries into gap edges (see above).
- **Geometry cues measured on synthetic worlds.** Every dev source fills a native ball gap by holding the last
  seen position, often just over a line, and renewal dropout leaves part of that held ball visible. 95 to
  96% of off-pitch dev frames are such held fills. My first geometry probe read them and printed
  P(dead | off pitch) 0.99. On frames PFF's tracker saw, it is 0.78 to 0.95.
- **Team-margin q(m).** On clean PFF frames, token reliability does depend on geometry: 0.98 when the ball is
  within 1.5 m of a player and the teams' nearest players are more than 3 m apart, 0.53 when the ball is
  far and contested. But a q that rises with margin flattened the evidence at hand-overs, where margins are
  small, and lost at v1's temper.
- **Chain constants.** Once the dead-run stage owns D, temper, the possession mean and the dead probability
  move the objective by less than its noise.

## Where the headroom is now

The oracle on tier0_v2 (other games' labels, diagnostic only):

| group | tier0_v2 | perfect dead ball | perfect team calls |
|---|---|---|---|
| IDSSE m0 (synthetic gaps) | 0.281 | 0.431 | 0.652 |
| PFF native m0 | 0.437 | 0.533 | 0.703 |

Team calls are now worth two to three times as much as dead ball.

## Limitations

- The synthetic generator's boundary switch biases any dead rule toward trim 0. A fix (a random lag at the
  switch, or a mask drawn independently of the labels) belongs after the hillclimb.
- PFF's tracker misses more of the ball than BAR-ATH's (58% against 41% of frames), and frames PFF marks
  ESTIMATED count as missing. Runs of 151 frames and over were excluded from the final candidates for that
  reason.
- The dead-run constants are integers on a coarse grid, and the final tie-break between 126/50/150 and
  126/50/200 was a 0.0001 difference in the synthetic minimum.
- v1's chain carries public-window history from 2026-10-21 (its temper grid and its dead_bias belief). The
  hillclimb changed only the dead-ball fields. `freeze.py` copies v1's disclosure into both new files word
  for word.
- dead_bias 2.6 and the generator's run pool are match-wide statistics of BAR-ATH's automatic inputs. The
  organisers have not confirmed that such statistics are allowed.

## For the technical document

- **Other-game labels.** Metrica (3 games, events turned into per-frame H/A/D by rule v2), IDSSE (7 DFL
  matches, CC BY 4.0, BallStatus and BallPossession; whether a human corrected them is undocumented) and PFF
  (64 games, event-derived by kloppy's reading). None is about BAR-ATH.
- **The AI assistant.** Claude ran this search and its subagents. It read BAR-ATH only as the aggregates
  listed above, and it never produced or scored a BAR-ATH label.

## Reproduce

```bash
source .venv/bin/activate
export MTAH_DATA_DIR=<data dir with metrica_sample, external/idsse, external/pff and the gated BAR-ATH files>
python -m possession selfcheck
PYTHONPATH=. python experiments/hillclimb-2026-10-24/freeze.py 126 50 150 --out params/tier0_v2.json
PYTHONPATH=. python experiments/hillclimb-2026-10-24/freeze.py 126 50 150 --dead-outside-m 0.5 --out params/tier0_v3.json
python -m possession make-submission --params params/tier0_v2.json --out tier0_v2.csv
python -m possession make-submission --params params/tier0_v3.json --out tier0_v3.csv
PYTHONPATH=. python experiments/hillclimb-2026-10-24/probes.py deadrule params/tier0_v1.json --out deadrule.csv
PYTHONPATH=. python experiments/hillclimb-2026-10-24/probes.py deadrule params/tier0_v1.json --dead-bias 1 4 --rule m0 h1p3 h3p3 idsse:m0 idsse:m2 --out deadrule-r1r4.csv
PYTHONPATH=. python experiments/hillclimb-2026-10-24/probes.py select deadrule.csv deadrule-r1r4.csv
```

The selection's `deadrule.csv` came from `RUNS (101, 126, 151, 201)`. `select` filters it to the rule-v2
candidates.
