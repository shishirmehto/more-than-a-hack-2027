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
           "frozen.")
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
    ap.add_argument("--q-logit", type=float, nargs=3, default=(0.0, 0.0, 0.0), metavar=("A", "B", "C"))
    ap.add_argument("--handover-lag", type=int, default=0)
    ap.add_argument("--dead-still", type=float, nargs=2, default=(0.0, 0), metavar=("MPS", "FRAMES"))
    ap.add_argument("--dead-pace-still", type=float, default=0.0, metavar="MPS")
    ap.add_argument("--spell-merge", type=int, default=0, metavar="FRAMES")
    ap.add_argument("--spell-push", type=float, nargs=3, default=(0.0, 0, 0.0), metavar=("MPS", "FRAMES", "UNSEEN"))
    ap.add_argument("--switch-penalty", type=float, default=0.0, metavar="LAMBDA")
    ap.add_argument("--spell-flip", type=float, nargs=3, default=(0.0, 0, 0.0), metavar=("P", "FRAMES", "SEEN"))
    ap.add_argument("--spell-logit", type=float, nargs=1 + len(SPELL_FEATURES), default=None,
                    metavar="W", help="the intercept, then one weight per decoder.SPELL_FEATURES name in order")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    v1_doc = json.loads(V1.read_text())
    model = Decoder.load(V1).replace(dead_min_run=a.run, dead_trim=a.trim, dead_close=a.close,
                                     dead_outside_m=a.dead_outside_m, q_logit_a=a.q_logit[0],
                                     q_logit_dist=a.q_logit[1], q_logit_margin=a.q_logit[2],
                                     handover_lag=a.handover_lag, dead_still_mps=a.dead_still[0],
                                     dead_still_frames=int(a.dead_still[1]), dead_pace_still_mps=a.dead_pace_still,
                                     spell_merge_frames=a.spell_merge, spell_push_mps=a.spell_push[0],
                                     spell_push_frames=int(a.spell_push[1]), spell_push_unseen=a.spell_push[2],
                                     switch_penalty=a.switch_penalty, spell_flip_p=a.spell_flip[0],
                                     spell_flip_frames=int(a.spell_flip[1]), spell_flip_seen=a.spell_flip[2],
                                     spell_logit=dict(zip(("a",) + SPELL_FEATURES, a.spell_logit or ())))
    logit = any(a.q_logit)
    no_seen = bool(a.spell_logit) and a.spell_logit[1 + SPELL_FEATURES.index("seen")] == 0
    changed = ("dead_min_run, dead_trim, dead_close, dead_outside_m and the emission's q_logit_a, q_logit_dist and "
               "q_logit_margin" if logit else "dead_min_run, dead_trim, dead_close and dead_outside_m")
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
    pins = {k: v for name in ("metrica", "idsse", "pff") for k, v in bench.SOURCES[name].pin.items()}
    model.save(a.out, {
        "command": shlex.join(["python", "experiments/hillclimb-2026-10-24/freeze.py", *argv]),
        "base": f"{V1} (every chain value and the rest of the emission)" if logit
                else f"{V1} (every emission and chain value)",
        "selection": SELECTION + (" " + GEOMETRY if a.dead_outside_m else "") + (" " + LOGIT if logit else "") +
                     (" " + LAG if a.handover_lag else "") + (" " + STILL if a.dead_still[0] else "") +
                     (" " + PACE if a.dead_pace_still else "") + (" " + MERGE if a.spell_merge else "") +
                     (" " + PUSH if a.spell_push[0] else "") + (" " + SWITCH if a.switch_penalty else "") +
                     (" " + SPELL if a.spell_flip[0] else "") + (" " + NO_SEEN if no_seen else ""),
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
                    " (local, gitignored)",
        "dropout_calibration": dataclasses.asdict(dropout.CALIBRATION),
        **pins,
        "public_window": f"The hillclimb changed only {changed}. It scored files on the public window as a "
                         "correctness check, never inside a selection rule: tier0_v2, tier0_v7 and tier0_v0 at 09:32 "
                         "and 09:36 IST on 2026-10-24, and tier0_v8 at 11:40 IST. Every experiment from E17 on, "
                         "selection rules v3 and v4, spell_merge_frames, the spell_push fields, switch_penalty and "
                         "the spell_flip fields came after the "
                         "first read. Inherited from "
                         "tier0_v1: " + v1_doc["provenance"]["public_window"],
    })
    print(a.out.read_text())


if __name__ == "__main__":
    main(sys.argv[1:])
