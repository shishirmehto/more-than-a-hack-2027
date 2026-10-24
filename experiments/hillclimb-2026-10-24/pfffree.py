"""Write params/tier0_v13_pfffree.json: tier0_v13 with its two fitted weight sets refitted on IDSSE and Metrica.

    PYTHONPATH=. python experiments/hillclimb-2026-10-24/pfffree.py --out params/tier0_v13_pfffree.json

A fallback for the open PFF licence question, not a recommendation. It reads no PFF file. q_logit is E5's
logistic of P(token == labelled team) on alive frames after kickoff of IDSSE and Metrica m0. spell_logit is E30's
target and features (seen, touch_own and touch_other left out) on IDSSE m0 and Metrica m0 renewal worlds at
generator dead_bias 2.6, seeds 0-4, decoded by tier0_v10 carrying the new q_logit. Every other value is
tier0_v13's, and those were chosen by ranking on PFF-A, so the file is free of PFF-fitted weights but not of
PFF-informed selection.
"""
import argparse
import json
import shlex
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import probes  # noqa: E402
from possession import bench, challenge, idsse, metrica, score  # noqa: E402
from possession.decoder import SPELL_FEATURES, Decoder, _lag_handovers, _spell_runs  # noqa: E402
from possession.half import D  # noqa: E402

V10, V13 = Path("params/tier0_v10.json"), Path("params/tier0_v13.json")
DROP = ("seen", "touch_own", "touch_other")


def fit_q_logit():
    """E5's model on IDSSE and Metrica m0: every frame is seen there, so all alive frames after kickoff count."""
    xs, ys = [], []
    for load in (metrica.load, idsse.load):
        for c in load(metrica.RuleV2.parse("m0")):
            h = challenge.observe(c.geometry, c.id)
            keep = (h.nearest_team != -1) & (c.labels != D) & (np.arange(h.n) >= h.id.kickoff)
            xs.append(probes._logit_features(h.geometry.nearest_m[keep].astype(np.float64),
                                             h.geometry.margin_m[keep].astype(np.float64)))
            ys.append((h.nearest_team[keep] == c.labels[keep]).astype(np.float64))
    w = probes._newton(np.concatenate(xs), np.concatenate(ys))
    return dict(q_logit_a=round(float(w[0]), 6), q_logit_dist=round(float(w[1]), 6),
                q_logit_margin=round(float(w[2]), 6))


def fit_spell_logit(base):
    """E30's flip-helps target on synthetic IDSSE and Metrica worlds, fitted where the token share is 0.5 or more."""
    p, chain = base.params, probes._rules_off(base)
    rows = []
    for _, cases in sorted(bench.dev_worlds(["m0", "idsse:m0"], (2.6,), seeds=(0, 1, 2, 3, 4)).items()):
        case = bench.pooled(cases)
        runs = score.valid_runs(case.gt)
        f_base, _ = score.spell_f1(case.layout, case.gt, [base.decode(h).codes for h in case.halves], runs)
        for h, lab in zip(case.halves, case.layout.cut(case.gt)):
            pre, logodds = probes._pre_lag(base, chain, h)

            def value(codes):
                s = score.pm.spell_scores(lab, codes, [(0, len(lab))])
                return np.mean([v["n_matched"] for v in s["per_iou"].values()]) - f_base / 2 * s["n_pred"]

            v0 = value(_lag_handovers(pre, p.handover_lag))
            for a, b, team, x in _spell_runs(pre, h, 250, logodds):
                trial = pre.copy()
                trial[a:b] = 1 - team
                rows.append([1.0, *x, float(value(_lag_handovers(trial, p.handover_lag)) > v0)])
    t = np.array(rows)
    seen = t[:, 1 + SPELL_FEATURES.index("seen")] >= probes.SPELL_SEEN["seen"]
    w = probes._spell_weights(t[seen, :-1], t[seen, -1], DROP)
    return {k: v for k, v in w.items() if k not in DROP}, int(seen.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    q = fit_q_logit()
    spell, n_runs = fit_spell_logit(Decoder.load(V10).replace(**q))
    v13 = json.loads(V13.read_text())["provenance"]
    model = Decoder.load(V13).replace(**q, spell_logit=spell)
    provenance = {
        "base": "params/tier0_v13.json (every value except q_logit_a, q_logit_dist, q_logit_margin and spell_logit)",
        "command": "PYTHONPATH=. python experiments/hillclimb-2026-10-24/pfffree.py --out " + shlex.quote(str(args.out)),
        "purpose": "Fallback if PFF's terms forbid fitting models on its data. Not the recommendation: tier0_v13 is.",
        "fitted": (f"q_logit: E5's logistic of P(token == labelled team) on alive frames after kickoff of IDSSE and "
                   f"Metrica m0 (probes._newton). spell_logit: E30's flip-helps target and features without "
                   f"{', '.join(DROP)}, a ridge-1 Newton logistic over {n_runs} candidate runs with token share 0.5 or "
                   "more on IDSSE m0 and Metrica m0 renewal worlds at dead_bias 2.6, seeds 0-4, decoded by tier0_v10 "
                   "with the new q_logit; weights rounded to 4 places. No PFF or StatsBomb file is read."),
        "inherited_selection": ("Every other value is tier0_v13's and was selected by ranking on PFF-A labels under "
                                "rule v2 (see params/tier0_v13.json provenance.selection). This file removes "
                                "PFF-fitted weights, not PFF-informed selection."),
        "evaluation": ("Scored once after the refit, never used to choose it. Against tier0_v13 on held-out PFF-B: "
                       "m0 -0.0079 [-0.0107, -0.0051], 6 of 32 games won; m2 -0.0070 [-0.0094, -0.0046], 8 of 32. "
                       "Synthetic seeds 15-24: below tier0_v13 in 12 of 15 groups by 0.005 to 0.010 (IDSSE m0 and m2, "
                       "Metrica m0 and h1p3) and above it in the 3 Metrica h3p3 groups by 0.003 to 0.012; worst-group "
                       "margin over baseline_smooth50 0.1038 against 0.1110. Above baseline_smooth50 in every group "
                       "and on all 64 PFF games."),
        "evidence": "data/derived/runs/pfffree-pff.csv, pfffree-synth.csv; .audit/hillclimb-2026-10-24.tsv",
        "dropout_calibration": v13["dropout_calibration"],
        "idsse_revision": v13["idsse_revision"],
        "sample_data_commit": v13["sample_data_commit"],
        "public_window": "Inherited from tier0_v13 unchanged; this refit never read the public window. " + v13["public_window"],
    }
    print(model.save(args.out, provenance))


if __name__ == "__main__":
    main()
