"""Write the hillclimb's final params: tier0_v1's chain and emission plus the selected dead-ball rule.

    PYTHONPATH=. python experiments/hillclimb-2026-10-24/freeze.py RUN TRIM CLOSE [--dead-outside-m M]
        [--q-logit A B C] [--handover-lag L] [--dead-still MPS FRAMES] [--dead-pace-still MPS] [--spell-merge FRAMES]
        [--spell-push MPS FRAMES UNSEEN] [--switch-penalty LAMBDA] [--spell-flip P FRAMES SEEN]
        [--spell-logit A W...] --out PATH

Every value except the dead-ball fields (dead_still_* among them), handover_lag and the emission's q_logit terms
is copied from
params/tier0_v1.json, so v1's public-window history is inherited and restated in the provenance word for word.
"""
import argparse
import dataclasses
import json
import shlex
import sys
from pathlib import Path

from possession import bench, dropout
from possession.decoder import SPELL_FEATURES, Decoder

V1 = Path("params/tier0_v1.json")
SELECTION = ("Pre-registered rule v2 (.audit/hillclimb-2026-10-24.tsv): candidates are v1's chain with dead_min_run "
             "{101, 126} x dead_trim {0, 12, 25, 37, 50} x dead_close {0, 100, 150, 200, 300}. Synthetic groups "
             "(Metrica m0, h1p3, h3p3 and IDSSE m0, m2 at generator dead_bias 1, 2.6, 4, seeds 0-4) only veto: a "
             "candidate's seed-mean pooled spellF1 margin over baseline_smooth50 must be at least the incumbent "
             "101/50/0's minus 0.003 in every group, because the renewal generator switches masks at label "
             "boundaries. The minimum over native PFF m0 and m2 on odd-indexed games ranks; ties within 0.003 go "
             "to the higher synthetic minimum. Even-indexed PFF games and seeds 15-24 only confirm. Game indices count "
             "from 1: the odd-indexed games are pff.GAMES[0::2].")
GEOMETRY = ("dead_outside_m was added after the dead rule, judged on native PFF only: it had to raise both "
            "odd-game margins and keep a 90% per-game lower bound above 0 on even games.")
LOGIT = ("The q_logit terms come from pre-registered experiment E5: logit(q) = a + b ln(1 + nearest_m) + "
         "c ln(1 + min(margin_m, 30)), a logistic fit of P(token == labelled team) on the frames PFF's tracker saw "
         "in live play on the odd-indexed games (probes.py fit_logit, 1,869,449 frames). The fitted emission "
         "replaced the constant q at v1's temper after passing the synthetic veto (at least tier0_v3's margin "
         "minus 0.003 in every group) and ranking first on the odd-game PFF minimum among tempers "
         "{0.03, 0.05, 0.1, 0.2}; even-indexed PFF games and seeds 15-24 only confirm.")
STILL = ("dead_still_mps and dead_still_frames come from pre-registered experiment E11: on frames PFF's tracker "
         "saw in the odd-indexed games, a ball under 1 m/s inside a slow run of 50-100 frames is dead 87% of the time "
         "and 98% beyond 100 (probes.py still). Candidates were 0.5 or 1 m/s over 25, 50 or 100 frames; all passed "
         "the synthetic veto (at least tier0_v5's margin minus 0.003 in every group), and the odd-game PFF minimum "
         "with the tie rule (within 0.003, the longer run first) chose 1 m/s over 50 frames; even-indexed PFF games "
         "and seeds 15-24 only confirm.")
PACE = ("dead_pace_still_mps comes from pre-registered experiment E13: on the odd-indexed PFF games, frames whose "
        "median player speed is under 0.5 m/s are dead 94% of the time (probes.py motion). Candidates crossed a live "
        "override {off, 1.5, 2, 2.5, 3} m/s with a still threshold {off, 0.5, 0.75} m/s; every live override lost, and "
        "the odd-game PFF minimum with the tie rule (within 0.003, the smaller still threshold first) chose 0.5 m/s "
        "alone; even-indexed PFF games and seeds 15-24 only confirm.")
MERGE = ("spell_merge_frames comes from pre-registered experiment E22: after the dead-run rule and before the lag, "
         "a possession shorter than 50 frames whose two neighbours are possessions joins them (decoder._merge_spells). "
         "Candidates were 25, 50, 75 or 100 frames, and 25 or 50 with tails. Under rule v3 the IDSSE m0 synthetic groups "
         "vetoed 50 frames (0.0064 below tier0_v7). Rule v4, adopted after E21 and E22 were seen because CHALLENGE.md "
         "asks for controlled possession and says a touch without control does not change it, widens the IDSSE m0 veto "
         "to 0.010. Under it the odd-game minimum over PFF m0, PFF m2 and StatsBomb-on-PFF m0, with the tie rule "
         "(fewer frames first, interior before tails), chose 50 frames, interior only; even-indexed games of both "
         "conventions and seeds 15-24 only confirm.")
PUSH = ("spell_push_mps, spell_push_frames and spell_push_unseen come from pre-registered experiments E25 and E26: "
        "after the dead-run rule and before the merge and the lag, a possession shorter than spell_push_frames whose "
        "frames are at least spell_push_unseen without a token, and whose mean push toward its own team (median player "
        "x velocity toward the goal it attacks, home minus away) is at most -spell_push_mps, goes to the other team "
        "(decoder._push_flip). E25 judged every short possession and was vetoed on IDSSE m0. E26, designed after that "
        "veto, added the no-token gate on the inference (never measured) that push trails a turnover, over gates "
        "{0.5, 0.8} x (2 m/s, 125 frames), (2, 250), (3, 250), the points E25 ranked highest. Rule v2 (synthetic "
        "veto at tier0_v7 minus 0.003 in every group; the odd-game minimum over PFF m0 "
        "and m2 ranks; ties within 0.003 to the base, then the fewest changed fields, then the higher minimum) chose "
        "2 m/s over 250 frames at 0.5, by 0.00004 over 3 m/s; even-indexed PFF games and seeds 15-24 only confirm. "
        "The gate makes the stage fire rarely in the synthetic worlds, so the veto says little about per-touch "
        "labels. No StatsBomb data entered this selection.")
SWITCH = ("switch_penalty comes from pre-registered experiment E27 on tier0_v9: the chain's block posterior is "
          "decoded by the label path that maximises the summed log posterior minus switch_penalty per change of team "
          "(decoder._penalized_path), so an island of one team inside the other survives only when its summed block "
          "log-odds reach twice the penalty. A design fan-out proposed 2, 4, 8, 16 and 32, with a waiver at dead "
          "frames for 8 and 16; the registrant added 1 ahead of them before any result, because temper 0.1 flattens "
          "the posterior. Rule v2 (synthetic veto at tier0_v9 minus 0.003 in every group; the odd-game minimum over "
          "PFF m0 and m2 ranks; ties within 0.003 to the base, then the smaller penalty) chose 1, the only candidate "
          "the IDSSE m0 groups did not veto (2 missed by 0.0010); even-indexed PFF games and seeds 15-24 only "
          "confirm. The fan-out's own kill gate, that posterior confidence separate matched from unmatched short "
          "possessions by 0.10 beyond length, was demoted to a diagnostic before any result and then failed (0.04 "
          "and 0.06), so under the fan-out's registration the result would be no change, and the penalty acts as a "
          "cut of the shortest weak islands. No StatsBomb data entered this selection.")
SPELL = ("spell_flip_p and spell_logit come from pre-registered experiment E29 on tier0_v10. A label-reading oracle "
         "(probes.py flipruns) put the ceiling of giving short possessions to the other team at +0.041 on PFF-A m0 "
         "for runs with a token on half their frames or more. A ridge-1 Newton logistic over decoder.SPELL_FEATURES "
         "(label-free: length, token shares, closest own approach, ball speed, own margin, push, the chain's "
         "log-odds and the neighbours) was fitted on the PFF-A m0 labels (pff.GAMES[0::2]) to say when giving one "
         "short possession away alone raises the half's matched possessions minus F/2 per predicted spell; the "
         "weights are that fit on all A games, rounded to 4 places. Candidates, registered before the first gate: "
         "base and token share 0.5+ or all runs at P 0.8, 0.65 and 0.5, ranked on 2-fold game-OOF PFF-A margins; "
         "the tie order (higher cut first, token-gated before all) was fixed after the first-gate numbers by "
         "structure. Rule v2 (synthetic veto at tier0_v10 minus 0.003 in every group with the all-A weights; the "
         "odd-game OOF minimum over PFF m0 and m2 ranks; ties within 0.003 to the base, then the tie order) chose "
         "token share 0.5+ at P 0.8; the 0.65 and 0.5 cuts failed the IDSSE m0 groups. Even-indexed PFF games and "
         "seeds 15-24 only confirm. The weights are PFF-derived numbers. No StatsBomb data entered this selection.")
NO_SEEN = ("E30 refitted the same model with the token-share feature left out (its weight 0) after tier0_v11, the E29 "
           "winner, passed PFF-B and seeds 15-24 and was then stopped by its registered BAR-ATH check: the median "
           "token share of BAR-ATH's short runs (1.000) sat above PFF-A's 90th percentile (0.946). That design used a "
           "label-free match-wide BAR-ATH statistic, under the team's unconfirmed reading of RULES.md; the weights "
           "are still fitted only on PFF-A labels. Same arms, tie order and rule v2 chose token share 0.5+ at P 0.8 "
           "again, and the BAR-ATH check, over the features with a non-zero weight, passed before this file was "
           "frozen. That pass was certain once the one feature outside PFF-A's range was left out, because the "
           "check's medians do not depend on the weights, so it is no evidence of transfer.")
LEAD = ("dead_lead_cut and dead_out_lead_cut come from pre-registered experiment E32 on tier0_v12. Label-reading "
        "oracles on PFF-A (probes.py deadedges, deadstarts) put +0.021 at the start edges of stoppages the dead rule "
        "already marks, because dead_trim cuts every dead run's start; where the ball is seen more than "
        "dead_outside_m outside the pitch near the run's start, the cue starts a median 5 frames before the "
        "labelled stoppage. Candidates, registered before any result: out-only cuts 25, 40, 50 and lead cuts 10 to "
        "50 with out variants (probes.py LEAD_GRID). Rule v2 (synthetic veto at tier0_v12 minus 0.003 in every "
        "group; the odd-game minimum over PFF m0 and m2 ranks; ties within 0.003 to the base, then the registered "
        "order: out-only cuts smallest first, then lead cuts 10 to 50, each plain before its out variants) chose "
        "this file's values. Even-indexed PFF games and seeds 15-24 only confirm. No BAR-ATH statistic was read. "
        "No StatsBomb data entered this selection.")
ADJ = ("spell_flip_adjacent and spell_flip_p 0.75 come from pre-registered experiment E40 on tier0_v13. A "
       "label-reading check on PFF-A (probes.py flippairs) found that 419 of the 936 short runs whose flip alone "
       "helps sit next to another such run, and keeping only the higher of each adjacent group lifts that ceiling "
       "from +0.035 to +0.046 over no flip; the decoder's own flips sit next to another flip on 6.8% of runs at cut "
       "0.8 and 10.2% at 0.75. Candidates, registered before any result: the rule at cuts 0.8, 0.75, 0.7 and 0.65 "
       "with the weights unchanged (probes.py ADJ_GRID). Rule v2 (synthetic veto at tier0_v13 minus 0.003 in every "
       "group; the odd-game minimum over PFF m0 and m2 ranks; ties within 0.003 of the best to the base, then the "
       "registered order: higher cut first) chose this file's values: cut 0.7 passed the veto by 0.0004 and led "
       "the odd-game minimum, which put tier0_v13 outside the tie band, and cut 0.75, inside that band and earlier "
       "in the order, was chosen by pick() as it ran then; on its own it is +0.0024 over tier0_v13 there. After the "
       "cross-model review, E32's registered clause (no change unless an arm clears the base by more than 0.003) "
       "was written into pick(), under which this file is a near-tie and not the recommendation; the adjacency "
       "rule is nearly inert at 0.75. Even-indexed PFF games and seeds 15-24 only confirm. No BAR-ATH statistic "
       "was read. No StatsBomb data entered this selection.")
LINE = ("dead_line_m, dead_line_min_run and dead_line_lead_cut come from pre-registered experiment E42c on "
        "tier0_v13. A label-reading check on PFF-A (scratch probe F3 from the community scan) found ball-missing gaps "
        "that start with the ball seen near a line are dead 48-60% of the time against 5-10% elsewhere. E42 (a "
        "shorter dead length alone, probes.py LINE_GRID) and E42b (plus a 25-frame lead cut, LINE_LEAD_GRID) tied "
        "the base under E32's clause, because dead_trim swallows short runs. E42c's candidates were chosen after "
        "reading E42b's result and registered before E42c ran (three sequential variants of one idea on PFF-A, 14 "
        "arms in all): dead_line_m {1, 2} x dead_line_min_run {75, 50} with the whole 50-frame start trim removed "
        "(LINE_FULL_GRID). Rule v2 with E32's clause (synthetic veto at tier0_v13 minus 0.003 in every group; the "
        "odd-game minimum over PFF m0 and m2 ranks; ties within 0.003 of the best to the registered order, m 1 "
        "before 2 and run 75 before 50; no change unless the pick clears the base by more than 0.003) chose this "
        "file's values: +0.0038 on the odd-game minimum. Confirmation, never used to choose: even-indexed PFF "
        "games m0 +0.0035 [+0.0026, +0.0044] 28 of 32 won, m2 +0.0038 [+0.0028, +0.0047] 29 of 32; seeds 15-24 "
        "above tier0_v13 in all 15 groups (+0.0008 to +0.0171, largest on IDSSE) and the worst-group margin over "
        "baseline_smooth50 0.1211 against 0.1110. No BAR-ATH statistic was read. No StatsBomb data entered this "
        "selection.")
LINE_ALT = " A confirmed alternative, not the recommendation: the user kept tier0_v13 on 2026-10-25."
E54 = ("handover_lag 20 with the dead_line fields comes from pre-registered experiment E54 on tier0_v13 under rule "
       "v2b, whose PFF-A minimum is over m0 and m2 in native and bridged modes (bridged: unseen runs under 125 "
       "frames count as seen, since BAR-ATH's ATD has about one such gap where PFF has about 211 per game). E52 "
       "(lag 8, 22, 30) and E53 (lag 18, 20, 25) found a plateau at 18 to 22 frames, +0.0014 to +0.0022 on that "
       "minimum, inside E32's clause. A label-reading oracle on PFF-A (scratch probe P3) put most of the remaining "
       "headroom in team calls with the ball seen, away from the labelled hand-overs. E54's arms, registered before "
       "it ran, crossed the near-misses: lag 20, the dead_line fields, E44's shape_own spell-logit refit, alone and "
       "together (6 arms). Every component had been read on PFF-A in an earlier experiment, so the combination "
       "reuses the selection half. Rule v2b with E32's clause (synthetic veto at tier0_v13 minus 0.003 in every "
       "group; ties within 0.003 of the best to the base, then the fewest fields changed; no change unless the "
       "pick clears the base by more than 0.003) chose the dead_line fields with lag 20: 0.1359 against 0.1317. "
       "The arm with shape_own as well scored 0.1371 and tied. Held-out results, never used to choose, paired per "
       "game over tier0_v13 on the even-indexed PFF games with 90% t intervals: m0 native +0.0046 [+0.0034, "
       "+0.0057] 27 of 32 won, m0 bridged +0.0044 [+0.0034, +0.0054] 29 of 32, m2 native +0.0055 [+0.0042, "
       "+0.0067] 29 of 32, m2 bridged +0.0056 [+0.0044, +0.0068] 29 of 32, each within 0.0006 of the odd-indexed "
       "games. Most of that is tier0_v15's dead_line gain, already read on these games in E42c: over tier0_v15 the "
       "lag adds m0 native +0.0011 [+0.0004, +0.0017] 20 of 32 won and m2 native +0.0017 [+0.0009, +0.0024] 23 of "
       "32, inside E32's clause, and a 20-frame lag missed these games before (experiment 33). On seeds 15-24 it "
       "is below tier0_v15 in all six Metrica groups (-0.0012 to -0.0019) and above it on h3p3 and IDSSE (+0.0014 "
       "to +0.0029), and above tier0_v13 in 13 of 15 groups, where earlier files were confirmed only when above "
       "their predecessor in all 15. So tier0_v16 is a near-tie over tier0_v15, as tier0_v14 is over tier0_v13, "
       "and not a recommendation. Besides the dev worlds' calibration every file inherits, the bridged mode rests "
       "on one label-free match-wide BAR-ATH statistic, the ATD's count of short ball gaps (experiment 90); no "
       "other BAR-ATH statistic was read. No StatsBomb data entered this selection.")
E60 = ("q_logit_goal and the refitted q_logit_a, q_logit_dist and q_logit_margin come from pre-registered experiment "
       "E60 on tier0_v13 under rule v2b. Two label-reading probes on PFF-A came first. P6: on tier0_v13's wrong-team "
       "frames with the ball seen and more than 25 frames from a labelled hand-over, the nearest-team token agrees "
       "with the labels only 18% to 40% of the time, against 85% to 90% on its right frames, so the token itself "
       "points the wrong way there. P7: the token is right 91% to 93% of the time when the ball is slow, 65% when "
       "it travels at 5 to 10 m/s toward the goal the token's team defends, and 45% above 10 m/s. The new term is "
       "h sign(u) ln(1 + |u|) on BallGeometry.goal_mps, the ball's x velocity over frames t-2 to t+2 signed toward "
       "the goal the nearest player's team defends, with each team's attack direction from its slots in the first "
       "second after kickoff, as in Half.push_mps. The logistic was refitted with it on the 1,869,449 seen live "
       "frames of the odd-indexed PFF games (probes.py fit_logit goal=True). Arms, registered before the run: "
       "base, the refit, and the refit with handover_lag 10 or 5 (probes.py e60grid). Rule v2b with E32's clause "
       "(synthetic veto at tier0_v13 minus 0.003 in every group; the minimum over PFF m0 and m2 in native and "
       "bridged modes on the odd-indexed games ranks; ties within 0.003 of the best to the base, then the fewest "
       "fields changed; no change unless the pick clears the base by more than 0.003) chose the refit at lag 15: "
       "0.1561 against 0.1317, with the synthetic minimum 0.1446 against 0.1099. Held-out results, never used to "
       "choose, paired per game over tier0_v13 on the even-indexed PFF games with 90% t intervals: m0 native "
       "+0.0046 [+0.0010, +0.0082] 19 of 32 won, m2 native +0.0027 [-0.0013, +0.0068] 17 of 32, m0 bridged "
       "+0.0192 [+0.0152, +0.0232] 29 of 32, m2 bridged +0.0221 [+0.0173, +0.0269] 29 of 32. Rule v2b's "
       "confirmation clause needs both lower bounds above 0 in each mode, so this file misses it on native m2. "
       "The native gains are smaller than on the odd-indexed games (+0.0083, +0.0058). About two thirds of the "
       "bridged gain sits on frames where PFF's ball is ESTIMATED, so native is the floor and bridged the "
       "ceiling. On seeds 15-24 (renewal worlds, a weak test) it sits above tier0_v13 in all 15 groups (+0.025 "
       "to +0.055) and on all 150 seed worlds (smallest +0.015); its worst-group margin over baseline_smooth50 "
       "is 0.1470 against 0.1110. Before "
       "the run one label-free BAR-ATH statistic was read to check reach and chose nothing: 15.7% of its seen "
       "frames have goal_mps over 5 m/s, against 12.6% on native PFF-A. No StatsBomb data entered this selection. "
       "Whether it replaces tier0_v13 as the recommendation is the user's decision, open on 2026-10-27.")
E61 = ("With the dead_line fields, this file is tier0_v15 plus E60's frozen emission, from pre-registered experiment "
       "E61 (probes.py e61grid; no refit, since fit_logit reads seen live frames and does not depend on the dead "
       "rules). Rule v2b with E32's clause on base tier0_v15 chose it: PFF-A minimum 0.1582 against 0.1338, "
       "synthetic minimum 0.1553 against 0.1203. Held-out results, never used to choose: on seeds 15-24 it sits "
       "above tier0_v15 in all 15 groups and on all 150 seed worlds (smallest +0.015), and above tier0_v17 in all "
       "15 groups and on 146 of 150 worlds; its worst-group margin over baseline_smooth50 is 0.1568. Paired per "
       "game on the even-indexed PFF games with 90% t intervals, over tier0_v15: m0 bridged +0.0192 [+0.0151, "
       "+0.0233] 29 of 32 won, m2 bridged +0.0220 [+0.0171, +0.0269] 29 of 32, m0 native +0.0045 [+0.0008, "
       "+0.0081] 18 of 32, m2 native +0.0026 [-0.0015, +0.0066] 15 of 32, so it misses rule v2b's clause on native "
       "m2 over tier0_v15 as tier0_v17 does over tier0_v13; over tier0_v17: m0 bridged +0.0021 "
       "[+0.0012, +0.0030] 27 of 32, m2 bridged +0.0023 [+0.0014, +0.0033] 27 of 32, m0 native +0.0034 "
       "[+0.0025, +0.0043] 27 of 32, m2 native +0.0036 [+0.0026, +0.0046] 28 of 32.")
TOUCH = ("spell_flip_p 0.75 and these spell_logit weights come from pre-registered experiments E69 and E70 on "
         "tier0_v13 under rule v2, after the PFF loader fix (experiment 113): PFF's 29.97 fps tracking repeats each "
         "position for two frames, so the old nearest-frame resample made ball velocity jitter, and E31's touch "
         "features (touch_own, touch_other: the largest change of ball speed between frames t - 5 and t + 5 within "
         "1.5 m of a player, over the run's own-token frames and the other team's within 25 frames) had been fitted "
         "on that jitter. E69 refitted E30's recipe with them (probes.py spellflip --drop seen rel_own shape_own "
         "held_own on tier0_v10, PFF-A only): out-of-fold lift at seen>=0.8 +0.0112 [+0.0083, +0.0140], 29 of 32 "
         "games, against +0.0073 without them; at tier0_v13's cut it gained +0.0026 on the native PFF-A minimum, "
         "inside E32's clause, and lifted all 15 synthetic groups, IDSSE m0 included. E70, registered after that, "
         "put the same weights at spell_flip_p 0.8, 0.75, 0.7 and 0.65 (probes.py e70grid). Rule v2 (synthetic veto "
         "at tier0_v13 minus 0.003 in every group; the minimum over native PFF m0 and m2 on the odd-indexed games "
         "ranks; ties within 0.003 of the best to the base, then the higher cut; no change unless the pick clears "
         "the base by more than 0.003) chose 0.75: 0.1575 against 0.1529, every synthetic group above tier0_v13 "
         "(veto slack 0.0047); 0.7 led at 0.1595 and tied, and 0.65 failed the veto on IDSSE m0. The weights and "
         "the ranking both read PFF-A, as in E30. Held-out results, never used to choose, paired per game over "
         "tier0_v13 on the even-indexed PFF games with 90% t intervals: m0 native +0.0059 [+0.0033, +0.0085] 27 of "
         "32 won, m2 native +0.0072 [+0.0043, +0.0100] 27 of 32. On seeds 15-24 it sits above tier0_v13 in all 15 "
         "groups (IDSSE m0 +0.0012 to +0.0023) and on 145 of 150 worlds; its worst-group margin over "
         "baseline_smooth50 is 0.1123 against 0.1110. E30's registered BAR-ATH check passes: every feature with a "
         "non-zero weight has its BAR-ATH median inside PFF-A's 10th-90th range (touch_own 1.596 inside 0 to "
         "2.641). Read label-free as information, not a gate: the flip takes 15.3% of BAR-ATH's 274 candidate runs "
         "against 9.2% on PFF-A (tier0_v13: 8.0% and 6.2%), consistent with BAR-ATH's smoother ball giving smaller "
         "touch values. No bridged-mode number and no lead from another team's fork entered this selection; it "
         "reads the fixed loader, whose lineage the user has not ruled on (REPORT, Fork lineage). No StatsBomb data "
         "entered this selection. A confirmed alternative: whether it replaces tier0_v13 is the user's decision.")
E81 = ("dead_end_cut 20 and stoppage_fill come from pre-registered experiment E81 on tier0_v19 under rule v2, a bundle "
       "of two near-misses that act on different errors. E72 (dead_end_cut 10, 20, 30, 40) found tier0_v19's dead "
       "runs end a median 15 frames before the labelled restart and gained +0.0026 at 20 on the native PFF-A minimum, "
       "inside E32's clause. E80's T2 (stoppage_fill) gives D from the start of a Smart Tagging throw-in or goal kick "
       "tag to the kick where the codes have under 20% D on [-5 s, +10 s) around it; on dev, pseudo-tags from each "
       "source's set-piece events, kept at BAR-ATH's tag recall per kind and started at its tag lead, stand in for "
       "the tags. It gained +0.0020, inside the clause. Its window, share and kick speeds are the T2 proposal's and "
       "were never gridded. The proposal's 134-frame fallback, BAR-ATH's median tag lead, was dropped so that no "
       "BAR-ATH statistic sets a decoder constant: a tag whose kick ball speed does not find adds nothing, which "
       "leaves every BAR-ATH act unchanged. Rule v2 (synthetic veto at tier0_v19 minus 0.003 in every group; the "
       "minimum over native PFF m0 and m2 on the odd-indexed games ranks; ties within 0.003 to the base, then the "
       "registered preference; no change unless the pick clears the base by more than 0.003) chose the bundle: "
       "0.1622 against 0.1575, every synthetic group above tier0_v19 (veto slack 0.0089). Both parts had been picked "
       "on PFF-A, so the held-out games decided. Paired per game over tier0_v19 on the even-indexed PFF games, which "
       "neither E72 nor E80 read, with 90% t intervals: m0 native +0.0034 [+0.0014, +0.0054] 20 of 32 won, m2 "
       "native +0.0027 [+0.0007, +0.0047] 21 of 32. On seeds 15-24 it sits above tier0_v19 in all 15 groups; its "
       "worst-group margin over baseline_smooth50 is 0.1177 against 0.1123. Dev halves carry no tags, so possession "
       "score --dev shows only the end cut; probes.py e81grid and e81score with pseudo-tags are the dev evidence, and "
       "probes.py t2identity shows this decoder's step equals the one E81 ran. On BAR-ATH, label-free, it turns 4,006 "
       "graded frames to D and changes possessions from 160 and 184 to 161 and 182 by half. T2 transfers only as far "
       "as BAR-ATH's automatic tags mark real stoppages. A confirmed alternative: whether it replaces tier0_v13 is "
       "the user's decision.")
E83 = ("broadcast_ball comes from pre-registered experiment E83 on tier0_v20, a candidate outside rule v2. The "
       "broadcast ATD (FAQ.md lets participants use it and leaves the mapping to them) is mapped onto tactical rows at "
       "runtime: 60 broadcast frames evenly spaced over those with a valid homography and 12 or more players go to the "
       "tactical row whose players sit nearest them, and each half's offset is the median over the confident ones, "
       "computed on every build and never written in. A row whose tactical ball is missing takes the broadcast ball "
       "when the mapped frame has a valid homography, a seen ball and 6 or more players within a mean 1.5 m of the "
       "tactical ones; these are generic tolerances, never tuned. On BAR-ATH, label-free, it fills 4,000 graded rows "
       "and, on tier0_v20, changes 244 frames to D, 2,755 from D and 939 between teams; 13 of 132 D runs of 2 s or "
       "more reopen. No dev source has a second camera, so the field changes nothing on any rule v2 world and cannot "
       "pass rule v2. Its dev evidence is E83's reveal worlds: on the five standard rules at dead_bias 2.6, seeds 0-4, "
       "revealing 6.2% of the masked rows inside labelled-alive stretches gains +0.028 to +0.037 spellF1 and inside "
       "labelled-D stretches costs 0.011 to 0.017, so the fill helps while under 0.68 to 0.73 of the filled rows are "
       "dead (0.61 to 0.69 with the broadcast error doubled). On BAR-ATH, v19's and v20's own D cover 0.51 and 0.60 "
       "of the filled rows. A candidate outside rule v2: whether it ships is the user's decision.")
E83_PUBLIC = ("Two later reads, on 27 October, scored tier0_v19 alone at 07:03 IST and tier0_v20_pfffree, tier0_v20, "
              "tier0_v13 and tier0_v19 at 19:24 IST; broadcast_ball came after both, and this file has not been scored "
              "on the public window.")
LAG = ("handover_lag comes from pre-registered experiment E7: matched dev possessions showed the hand-overs "
       "between the teams 10 to 22 frames early on every label source (median, probes.py spells), because the "
       "nearest-team token flips while a pass is in the air. Candidates were lag {0, 5, ..., 30} crossed with "
       "a snap to the receiver's first frame within {0.5, 1, 1.5, 2, 3} m; the synthetic veto (at least "
       "tier0_v4's margin minus 0.003 in every group) and the odd-game PFF minimum chose lag 15, the smallest "
       "change within 0.003 of the best; even-indexed PFF games and seeds 15-24 only confirm.")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=int)
    ap.add_argument("trim", type=int)
    ap.add_argument("close", type=int)
    ap.add_argument("--dead-outside-m", type=float, default=0.0)
    ap.add_argument("--q-logit", type=float, nargs="+", default=(0.0, 0.0, 0.0), metavar="W",
                    help="a, distance and margin weights, and optionally the goal weight (E60)")
    ap.add_argument("--handover-lag", type=int, default=0)
    ap.add_argument("--dead-still", type=float, nargs=2, default=(0.0, 0), metavar=("MPS", "FRAMES"))
    ap.add_argument("--dead-pace-still", type=float, default=0.0, metavar="MPS")
    ap.add_argument("--spell-merge", type=int, default=0, metavar="FRAMES")
    ap.add_argument("--spell-push", type=float, nargs=3, default=(0.0, 0, 0.0), metavar=("MPS", "FRAMES", "UNSEEN"))
    ap.add_argument("--switch-penalty", type=float, default=0.0, metavar="LAMBDA")
    ap.add_argument("--spell-flip", type=float, nargs=3, default=(0.0, 0, 0.0), metavar=("P", "FRAMES", "SEEN"))
    ap.add_argument("--dead-lead-cut", type=int, nargs=2, default=(0, 0), metavar=("ALL", "OUT"))
    ap.add_argument("--spell-flip-adjacent", action="store_true")
    ap.add_argument("--dead-line", type=float, nargs=3, default=(0.0, 0, 0), metavar=("M", "RUN", "CUT"))
    ap.add_argument("--dead-end-cut", type=int, default=0, metavar="CUT", help="E72's end cut (E81)")
    ap.add_argument("--stoppage-fill", action="store_true", help="T2 at Smart Tagging throw-ins and goal kicks (E81)")
    ap.add_argument("--broadcast-ball", action="store_true", help="the broadcast ATD's ball in tactical gaps (E83)")
    ap.add_argument("--spell-logit", type=float, nargs="+", default=None, metavar="W",
                    help="the intercept, then one weight per decoder.SPELL_FEATURES name in order; trailing "
                         "features left out weigh 0 and are not written")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    e54 = bool(a.dead_line[0]) and a.handover_lag == 20
    if len(a.q_logit) not in (3, 4):
        ap.error("--q-logit takes 3 or 4 values")
    goal = len(a.q_logit) == 4 and a.q_logit[3] != 0
    if a.spell_logit and len(a.spell_logit) > 1 + len(SPELL_FEATURES):
        ap.error(f"--spell-logit takes at most {1 + len(SPELL_FEATURES)} values")
    v1_doc = json.loads(V1.read_text())
    model = Decoder.load(V1).replace(dead_min_run=a.run, dead_trim=a.trim, dead_close=a.close,
                                     dead_outside_m=a.dead_outside_m, q_logit_a=a.q_logit[0],
                                     q_logit_dist=a.q_logit[1], q_logit_margin=a.q_logit[2],
                                     q_logit_goal=a.q_logit[3] if goal else 0.0,
                                     handover_lag=a.handover_lag, dead_still_mps=a.dead_still[0],
                                     dead_still_frames=int(a.dead_still[1]), dead_pace_still_mps=a.dead_pace_still,
                                     spell_merge_frames=a.spell_merge, spell_push_mps=a.spell_push[0],
                                     spell_push_frames=int(a.spell_push[1]), spell_push_unseen=a.spell_push[2],
                                     switch_penalty=a.switch_penalty, spell_flip_p=a.spell_flip[0],
                                     spell_flip_frames=int(a.spell_flip[1]), spell_flip_seen=a.spell_flip[2],
                                     spell_logit=dict(zip(("a",) + SPELL_FEATURES, a.spell_logit or ())),
                                     dead_lead_cut=a.dead_lead_cut[0], dead_out_lead_cut=a.dead_lead_cut[1],
                                     spell_flip_adjacent=a.spell_flip_adjacent, dead_line_m=a.dead_line[0],
                                     dead_line_min_run=int(a.dead_line[1]), dead_line_lead_cut=int(a.dead_line[2]),
                                     dead_end_cut=a.dead_end_cut, stoppage_fill=a.stoppage_fill,
                                     broadcast_ball=a.broadcast_ball)
    e81 = bool(a.dead_end_cut) and a.stoppage_fill
    if bool(a.dead_end_cut) != a.stoppage_fill:
        ap.error("--dead-end-cut and --stoppage-fill come from E81 together")
    if a.broadcast_ball and not e81:
        ap.error("--broadcast-ball was tested on tier0_v20 (E83), which carries E81's fields")
    lead = any(a.dead_lead_cut)
    logit = any(a.q_logit)
    no_seen = bool(a.spell_logit) and a.spell_logit[1 + SPELL_FEATURES.index("seen")] == 0
    i_touch = 1 + SPELL_FEATURES.index("touch_own")
    touch = bool(a.spell_logit) and len(a.spell_logit) > i_touch and a.spell_logit[i_touch] != 0
    changed = ("dead_min_run, dead_trim, dead_close, dead_outside_m and the emission's q_logit_a, q_logit_dist and "
               "q_logit_margin" if logit else "dead_min_run, dead_trim, dead_close and dead_outside_m")
    if goal:
        changed = changed.replace("q_logit_dist and q_logit_margin", "q_logit_dist, q_logit_margin and q_logit_goal")
    if a.handover_lag:
        changed = changed.replace("dead_outside_m and", "dead_outside_m, handover_lag and")
    if a.dead_still[0]:
        changed = changed.replace("dead_outside_m,", "dead_outside_m, dead_still_mps, dead_still_frames,")
    if a.dead_pace_still:
        changed = changed.replace("dead_still_frames,", "dead_still_frames, dead_pace_still_mps,")
    if a.spell_merge:
        changed = changed.replace("handover_lag and", "handover_lag, spell_merge_frames and")
    if a.spell_push[0]:
        changed = changed.replace("handover_lag", "handover_lag, spell_push_mps, spell_push_frames, spell_push_unseen", 1)
    if a.switch_penalty:
        changed = changed.replace("handover_lag", "handover_lag, switch_penalty", 1)
    if a.spell_flip[0]:
        changed = changed.replace("handover_lag", "handover_lag, spell_flip_p, spell_flip_frames, spell_flip_seen, "
                                  "spell_logit", 1)
    if lead:
        changed = changed.replace("dead_close,", "dead_close, dead_lead_cut, dead_out_lead_cut,", 1)
    if a.dead_line[0]:
        changed = changed.replace("dead_close,", "dead_close, dead_line_m, dead_line_min_run, dead_line_lead_cut,", 1)
    if a.spell_flip_adjacent:
        changed = changed.replace("spell_logit", "spell_logit, spell_flip_adjacent", 1)
    if e81:
        changed = changed.replace("dead_close,", "dead_close, dead_end_cut,", 1).replace(
            "spell_logit", "spell_logit, stoppage_fill", 1)
    after = ("the spell_flip, dead_lead and dead_line fields and handover_lag 20" if e54 else
             "the spell_flip, dead_lead and dead_line fields and the q_logit_goal term" if goal and a.dead_line[0] else
             "the spell_flip, dead_lead and dead_line fields" if a.dead_line[0] else
             "the spell_flip and dead_lead fields and the q_logit_goal term" if goal else
             "the spell_flip and dead_lead fields")
    if e81:
        after = after.replace(" and dead_lead fields", ", dead_lead, dead_end_cut and stoppage_fill fields").replace(
            " and dead_line fields", ", dead_line, dead_end_cut and stoppage_fill fields")
    if a.broadcast_ball:
        changed = changed.replace("stoppage_fill", "stoppage_fill, broadcast_ball", 1)
        after = after.replace(" and stoppage_fill fields", ", stoppage_fill and broadcast_ball fields")
    pins = {k: v for name in ("metrica", "idsse", "pff") for k, v in bench.SOURCES[name].pin.items()}
    model.save(a.out, {
        "command": shlex.join(["python", "experiments/hillclimb-2026-10-24/freeze.py", *argv]),
        "base": f"{V1} (every chain value and the rest of the emission)" if logit
                else f"{V1} (every emission and chain value)",
        "selection": SELECTION + (" " + GEOMETRY if a.dead_outside_m else "") + (" " + LOGIT if logit else "") +
                     (" " + LAG if a.handover_lag else "") + (" " + STILL if a.dead_still[0] else "") +
                     (" " + PACE if a.dead_pace_still else "") + (" " + MERGE if a.spell_merge else "") +
                     (" " + PUSH if a.spell_push[0] else "") + (" " + SWITCH if a.switch_penalty else "") +
                     (" " + SPELL if a.spell_flip[0] else "") + (" " + NO_SEEN if no_seen else "") +
                     (" " + LEAD if lead else "") + (" " + TOUCH if touch else "") +
                     (" " + ADJ if a.spell_flip_adjacent else "") +
                     (" " + LINE if a.dead_line[0] else "") + (LINE_ALT if a.dead_line[0] and not e54 and not goal else "") +
                     (" " + E54 if e54 else "") + (" " + E60 if goal else "") +
                     (" " + E61 if goal and a.dead_line[0] else "") + (" " + E81 if e81 else "") +
                     (" " + E83 if a.broadcast_ball else ""),
        "evidence": "experiments/hillclimb-2026-10-24/REPORT.md; data/derived/runs/hc/deadrule-split-v1.csv and "
                    "deadrule-r1r4-v1.csv" + (", logit-synth.csv and logit-pff.csv" if logit else "") +
                    (", snap-synth.csv and snap-pff.csv" if a.handover_lag else "") +
                    (", still-synth.csv and still-pff.csv" if a.dead_still[0] else "") +
                    (", pace-synth.csv and pace-pff.csv" if a.dead_pace_still else "") +
                    (", merge-synth.csv and merge-pff.csv" if a.spell_merge else "") +
                    (", spellpush-v7b.out, pushflip-*.csv and pushunseen-*.csv" if a.spell_push[0] else "") +
                    (", switchpen-pff.csv, switchpen-synth.csv, select-e27.out and spellmass-v9.out"
                     if a.switch_penalty else "") +
                    (", flipruns-v10.out, spellflip-v10.out, e29-spellflip.out, e29-pff.csv, e29-synth.csv and "
                     "select-e29.out" if a.spell_flip[0] else "") +
                    (", barath-spell-v11.out, spellseen-v11.out, e30-spellflip.out, e30-pff.csv, e30-synth.csv, "
                     "select-e30.out and barath-spell-e30.out" if no_seen else "") +
                    (", deadsplit-v12.out, deadcensus-v12.out, deadedges-v12.out, deadstarts-v12.out, e32-pff.csv, "
                     "e32-synth.csv and select-e32.out" if lead else "") +
                    (", e68-spell.out, e69-spell.out, e69-synth.csv, e69-pff.csv, e69-pick.out, e69-barath-spell.out, "
                     "e70-synth.csv, e70-pff.csv, e70-pick.out, e70-confirm.out, e70-confirm-synth.out, "
                     "e70-flipshare.out, hc-confirm-e70-pff.csv and hc-confirm-e70-synth.csv" if touch else "") +
                    (", flipindep-v13.out, flippairs-v13.out, e40-pff.csv, e40-synth.csv and select-e40.out"
                     if a.spell_flip_adjacent else "") +
                    (", e42-*.csv, e42b-*.csv, e42c-*.csv, hc-confirm-e42c-pff.csv and hc-confirm-e42c-synth.csv"
                     if a.dead_line[0] else "") +
                    (", p3-oracle.out, e52-*.csv, e53-*.csv, e54-*.csv, e54-pick.out, e54-confirm.out, "
                     "hc-confirm-e54-pff.csv and hc-confirm-e54-synth.csv" if e54 else "") +
                    (", p6-seenerr.out, p7-direction.out, e60-synth.csv, e60-pff.csv, e60-pick.out, e60-confirm.out, "
                     "hc-confirm-e60-pff.csv and hc-confirm-e60-synth.csv" if goal else "") +
                    (", e61-synth.csv, e61-pff.csv, e61-pick.out, e61-confirm.out, hc-confirm-e61-pff.csv and "
                     "hc-confirm-e61-synth.csv" if goal and a.dead_line[0] else "") +
                    (", e72-synth.csv, e72-pff.csv, e72-pick.out, stoppagedose-v19.out, e80-synth.csv, e80-pff.csv, "
                     "e80-pick.out, e81-synth.csv, e81-pff.csv, e81-pick.out, e81-confirm-pff.csv, e81-confirm-pff.out, "
                     "e81-confirm-synth.csv, e81-confirm-synth.out, barathdiff-e81.out and t2identity.out" if e81 else "") +
                    (", e83-dose.out, e83-fill.npz, e83-reveal.out, e83-reveal-x2.out, e83-reveal-x3.out and "
                     "broadcast-state-v20.out" if a.broadcast_ball else "") +
                    " (local, gitignored)",
        "dropout_calibration": dataclasses.asdict(dropout.CALIBRATION),
        **pins,
        "public_window": f"The hillclimb changed only {changed}. It scored files on the public window as a "
                         "correctness check, never inside a selection rule: tier0_v2, tier0_v7 and tier0_v0 at 09:32 "
                         "and 09:36 IST on 2026-10-24, and tier0_v8 at 11:40 IST. Every experiment from E17 on, "
                         "selection rules v3 and v4, spell_merge_frames, the spell_push fields, switch_penalty and " +
                         after + " came after the first read." + (" " + E83_PUBLIC if a.broadcast_ball else "") +
                         " Inherited from tier0_v1: " + v1_doc["provenance"]["public_window"],
    })
    print(a.out.read_text())


if __name__ == "__main__":
    main(sys.argv[1:])
