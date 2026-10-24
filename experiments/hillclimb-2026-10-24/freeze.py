"""Write the hillclimb's final params: tier0_v1's chain and emission plus the selected dead-ball rule.

    PYTHONPATH=. python experiments/hillclimb-2026-10-24/freeze.py RUN TRIM CLOSE [--dead-outside-m M] --out PATH

Every value except the dead-ball fields is copied from params/tier0_v1.json, so v1's public-window history is
inherited and restated in the provenance word for word.
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


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=int)
    ap.add_argument("trim", type=int)
    ap.add_argument("close", type=int)
    ap.add_argument("--dead-outside-m", type=float, default=0.0)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    v1_doc = json.loads(V1.read_text())
    model = Decoder.load(V1).replace(dead_min_run=a.run, dead_trim=a.trim, dead_close=a.close,
                                     dead_outside_m=a.dead_outside_m)
    pins = {k: v for source in bench.SOURCES.values() for k, v in source.pin.items()}
    model.save(a.out, {
        "command": shlex.join(["python", "experiments/hillclimb-2026-10-24/freeze.py", *argv]),
        "base": f"{V1} (every emission and chain value)",
        "selection": SELECTION + (" " + GEOMETRY if a.dead_outside_m else ""),
        "evidence": "experiments/hillclimb-2026-10-24/REPORT.md; data/derived/runs/hc/deadrule-split-v1.csv and "
                    "deadrule-r1r4-v1.csv (local, gitignored)",
        "dropout_calibration": dataclasses.asdict(dropout.CALIBRATION),
        **pins,
        "public_window": "The hillclimb did not read the public window; it changed only dead_min_run, dead_trim, "
                         "dead_close and dead_outside_m. Inherited from tier0_v1: " + v1_doc["provenance"]["public_window"],
    })
    print(a.out.read_text())


if __name__ == "__main__":
    main(sys.argv[1:])
