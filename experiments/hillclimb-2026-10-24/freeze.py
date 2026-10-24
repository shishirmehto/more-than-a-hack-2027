"""Write the hillclimb's final params: tier0_v1's chain and emission plus the selected dead-ball rule.

    PYTHONPATH=. python experiments/hillclimb-2026-10-24/freeze.py RUN TRIM CLOSE [--dead-outside-m M]
        [--q-logit A B C] [--handover-lag L] --out PATH

Every value except the dead-ball fields, handover_lag and the emission's q_logit terms is copied from
params/tier0_v1.json, so v1's public-window history is inherited and restated in the provenance word for word.
"""
import argparse
import dataclasses
import json
import shlex
import sys
from pathlib import Path

from possession import bench, dropout
from possession.decoder import Decoder

V1 = Path("params/tier0_v1.json")
SELECTION = ("Pre-registered rule v2 (.audit/hillclimb-2026-10-24.tsv): candidates are v1's chain with dead_min_run "
             "{101, 126} x dead_trim {0, 12, 25, 37, 50} x dead_close {0, 100, 150, 200, 300}. Synthetic groups "
             "(Metrica m0, h1p3, h3p3 and IDSSE m0, m2 at generator dead_bias 1, 2.6, 4, seeds 0-4) only veto: a "
             "candidate's seed-mean pooled spellF1 margin over baseline_smooth50 must be at least the incumbent "
             "101/50/0's minus 0.003 in every group, because the renewal generator switches masks at label "
             "boundaries. The minimum over native PFF m0 and m2 on odd-indexed games ranks; ties within 0.003 go "
             "to the higher synthetic minimum. Even-indexed PFF games and seeds 15-24 only confirm.")
GEOMETRY = ("dead_outside_m was added after the dead rule, judged on native PFF only: it had to raise both "
            "odd-game margins and keep a 90% per-game lower bound above 0 on even games.")
LOGIT = ("The q_logit terms come from pre-registered experiment E5: logit(q) = a + b ln(1 + nearest_m) + "
         "c ln(1 + min(margin_m, 30)), a logistic fit of P(token == labelled team) on the frames PFF's tracker saw "
         "in live play on the odd-indexed games (probes.py fit_logit, 1,869,449 frames). The fitted emission "
         "replaced the constant q at v1's temper after passing the synthetic veto (at least tier0_v3's margin "
         "minus 0.003 in every group) and ranking first on the odd-game PFF minimum among tempers "
         "{0.03, 0.05, 0.1, 0.2}; even-indexed PFF games and seeds 15-24 only confirm.")
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
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    v1_doc = json.loads(V1.read_text())
    model = Decoder.load(V1).replace(dead_min_run=a.run, dead_trim=a.trim, dead_close=a.close,
                                     dead_outside_m=a.dead_outside_m, q_logit_a=a.q_logit[0],
                                     q_logit_dist=a.q_logit[1], q_logit_margin=a.q_logit[2],
                                     handover_lag=a.handover_lag)
    logit = any(a.q_logit)
    changed = ("dead_min_run, dead_trim, dead_close, dead_outside_m and the emission's q_logit_a, q_logit_dist and "
               "q_logit_margin" if logit else "dead_min_run, dead_trim, dead_close and dead_outside_m")
    if a.handover_lag:
        changed = changed.replace("dead_outside_m and", "dead_outside_m, handover_lag and")
    pins = {k: v for source in bench.SOURCES.values() for k, v in source.pin.items()}
    model.save(a.out, {
        "command": shlex.join(["python", "experiments/hillclimb-2026-10-24/freeze.py", *argv]),
        "base": f"{V1} (every chain value and the rest of the emission)" if logit
                else f"{V1} (every emission and chain value)",
        "selection": SELECTION + (" " + GEOMETRY if a.dead_outside_m else "") + (" " + LOGIT if logit else "") +
                     (" " + LAG if a.handover_lag else ""),
        "evidence": "experiments/hillclimb-2026-10-24/REPORT.md; data/derived/runs/hc/deadrule-split-v1.csv and "
                    "deadrule-r1r4-v1.csv" + (", logit-synth.csv and logit-pff.csv" if logit else "") +
                    (", snap-synth.csv and snap-pff.csv" if a.handover_lag else "") +
                    " (local, gitignored)",
        "dropout_calibration": dataclasses.asdict(dropout.CALIBRATION),
        **pins,
        "public_window": f"The hillclimb did not read the public window; it changed only {changed}. Inherited "
                         "from tier0_v1: " + v1_doc["provenance"]["public_window"],
    })
    print(a.out.read_text())


if __name__ == "__main__":
    main(sys.argv[1:])
