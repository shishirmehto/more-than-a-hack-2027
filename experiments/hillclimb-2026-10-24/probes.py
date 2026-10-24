"""Diagnostic probes behind the 2026-10-24 hillclimb report. Run from the repo root:

    PYTHONPATH=. python experiments/hillclimb-2026-10-24/probes.py <probe> [args]

oracle PARAMS        headroom: perfect dead ball or perfect team calls on top of PARAMS (dev labels only)
geometry             how the nearest-team token and dead ball depend on geometry, on Metrica and IDSSE labels
barath-geometry      the same geometry, match-wide on BAR-ATH's ATD, with no labels read
close PARAMS         PARAMS with short live gaps between dead runs closed, on the 7-group objective
deadrule PARAMS      every (dead_min_run, dead_trim, close gap) on PARAMS's chain, decoded once per world,
                     on the 7-group objective (equal to fit-dev's numbers, much faster)
chain PARAMS         a grid of chain constants on top of PARAMS, each decoded once, under a few dead rules
confirm CSV          a `score` run table: per-group margins over smooth50 for every model, and paired
                     per-game differences with 90% t intervals on the native PFF games

Oracle rows read other games' labels and are diagnostics, never candidates. Nothing here reads a BAR-ATH
label or the public window.
"""
import argparse
import itertools

import numpy as np
import pandas as pd

from possession import bench, challenge, idsse, metrica, score
from possession.decoder import Decoder, _missing_run_dead
from possession.half import D, H

SEARCH = ["m0", "h1p3", "h3p3", "idsse:m0", "idsse:m2"]
NATIVE = ["pff:m0:native", "pff:m2:native"]
SEEDS = [0, 1, 2, 3, 4]
CHUNK = 20000


def ffill_team(codes, fallback):
    """D replaced by the last H/A before it, or by fallback where there is none."""
    idx = np.where(codes != D, np.arange(len(codes)), -1)
    np.maximum.accumulate(idx, out=idx)
    filled = np.where(idx >= 0, codes[np.maximum(idx, 0)], fallback)
    return np.where(codes == D, filled, codes).astype(np.int8)


def oracle(params):
    model, s50 = Decoder.load(params), bench.Smoother(50)
    rows = []
    for world, cases in bench.dev_worlds(SEARCH, [2.6], seeds=SEEDS).items():
        case = bench.pooled(cases)
        runs = score.valid_runs(case.gt)
        per = {}
        for half, gt in zip(case.halves, case.layout.cut(case.gt)):
            mine, floor = model.decode(half).codes, s50.decode(half).codes
            team = ffill_team(mine, np.where(floor == D, H, floor))
            variants = {"model": mine, "s50": floor,
                        "s50D_modelteam": np.where(floor == D, D, team),
                        "oracleD_modelteam": np.where(gt == D, D, team),
                        "modelD_oracleteam": np.where(mine == D, D, np.where(gt == D, team, gt))}
            for name, codes in variants.items():
                per.setdefault(name, []).append(codes.astype(np.int8))
        for name, preds in per.items():
            f1, n = score.spell_f1(case.layout, case.gt, preds, runs)
            rows.append({"group": bench.group(world), "variant": name, "spell_f1": f1, "n_pred": n})
    t = pd.DataFrame(rows)
    print(t.pivot_table(index="variant", columns="group", values="spell_f1").round(4).to_string())


def features(g):
    """Per frame: nearest-player distance and team, team margin (|nearest away - nearest home|, m), and the
    ball's distance to the nearest pitch line (negative outside)."""
    n = g.n
    d_near, margin = np.full(n, np.nan), np.full(n, np.nan)
    team = np.full(n, -1, np.int8)
    for lo in range(0, n, CHUNK):
        ball = g.ball_xy[lo:lo + CHUNK].astype(np.float64)
        p = g.players_xy[lo:lo + CHUNK].astype(np.float64)
        d = np.sqrt(((p - ball[:, None, :]) ** 2).sum(-1))
        d = np.where(np.isnan(d), np.inf, d)
        dh = np.where(g.slot_team[None, :] == 0, d, np.inf).min(1)
        da = np.where(g.slot_team[None, :] == 1, d, np.inf).min(1)
        d_near[lo:lo + CHUNK] = np.minimum(dh, da)
        team[lo:lo + CHUNK] = np.where(dh <= da, 0, 1)
        with np.errstate(invalid="ignore"):
            margin[lo:lo + CHUNK] = np.abs(da - dh)
    L, W = g.pitch_m
    x, y = g.ball_xy[:, 0].astype(np.float64), g.ball_xy[:, 1].astype(np.float64)
    return pd.DataFrame({"d_near": d_near, "team": team, "margin": margin,
                         "to_line": np.minimum.reduce([x, L - x, y, W - y])})


BINS_D = [0, 0.5, 1, 1.5, 2, 3, 4, 6, 10, 1e9]
BINS_M = [0, 0.25, 0.5, 1, 2, 3, 5, 1e9]
BINS_LINE = [-1e9, -2, 0, 1, 2, 5, 10, 1e9]


def geometry():
    frames = []
    for name, load in (("metrica", metrica.load), ("idsse", idsse.load)):
        for c in load(metrica.RuleV2.parse("m0")):
            f = features(c.geometry).assign(label=c.labels, src=name)
            frames.append(f[np.arange(c.geometry.n) >= c.id.kickoff])
    t = pd.concat(frames, ignore_index=True)
    alive = t[t.label != D].assign(agree=lambda f: f.team == f.label)
    for src, f in alive.groupby("src"):
        print(f"\n== {src}: alive frames {len(f)}, overall q {f.agree.mean():.3f}")
        for col, bins in (("d_near", BINS_D), ("margin", BINS_M)):
            g = f.groupby(pd.cut(f[col], bins, include_lowest=True), observed=False)
            print(pd.DataFrame({"share": g.size() / len(f), "q": g.agree.mean()}).round(3).T.to_string())
    for src, f in t.groupby("src"):
        print(f"\n== {src}: P(dead | bin), base {(f.label == D).mean():.3f}")
        for col, bins in (("to_line", BINS_LINE), ("d_near", BINS_D)):
            g = f.groupby(pd.cut(f[col], bins), observed=False)
            print(pd.DataFrame({"share": g.size() / len(f),
                                "p_dead": g.label.apply(lambda s: (s == D).mean())}).round(3).T.to_string())


def barath_geometry():
    for g, hid in zip(challenge.load_geometry(), challenge._half_ids()):
        f = features(g)[np.arange(g.n) >= hid.kickoff]
        s = f[np.isfinite(f.d_near)]
        print(f"half {hid.half}: pitch {g.pitch_m}, frames {len(f)}, ball seen {len(s) / len(f):.3f}")
        for col, bins in (("to_line", BINS_LINE), ("d_near", [0, 1, 2, 4, 10, 1e9]),
                          ("margin", [0, 0.5, 1, 2, 5, 1e9])):
            share = pd.cut(s[col], bins, include_lowest=True).value_counts(normalize=True, sort=False)
            print(f"  {col}:", {str(k): round(v, 3) for k, v in share.items()})


def close_dead(codes, gap, kickoff):
    """D on every non-D run shorter than gap frames with D on both sides."""
    out = codes.copy()
    live = np.concatenate(([0], (out != D).view(np.int8), [0]))
    edges = np.flatnonzero(np.diff(live))
    for start, stop in zip(edges[::2], edges[1::2]):
        if start > kickoff and stop < len(out) and stop - start < gap:
            out[start:stop] = D
    return out


def close(params):
    model, s50 = Decoder.load(params), bench.Smoother(50)
    rows = []
    for world, cases in bench.dev_worlds(SEARCH + NATIVE, [2.6], seeds=SEEDS).items():
        case = bench.pooled(cases)
        runs = score.valid_runs(case.gt)
        base = [model.decode(h).codes for h in case.halves]
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        for gap in (0, 13, 25, 50, 75, 100, 150):
            f1, n = score.spell_f1(case.layout, case.gt,
                                   [close_dead(c, gap, h.id.kickoff) for c, h in zip(base, case.halves)], runs)
            rows.append({"group": bench.group(world), "gap": gap, "margin": f1 - floor, "n_pred": n})
    t = pd.DataFrame(rows)
    m = t.pivot_table(index="gap", columns="group", values="margin")
    m["min"], m["mean"] = m.min(1), m.mean(1)
    print(m.round(4).to_string())
    print(t.pivot_table(index="gap", columns="group", values="n_pred").round(0).to_string())


RUNS = (76, 101, 126, 151, 201, 251)
TRIMS = (0, 25, 50)
GAPS = (0, 50, 100, 150, 200, 300, 450)


def deadrule(params):
    chain, s50 = Decoder.load(params).replace(dead_min_run=0, dead_trim=0), bench.Smoother(50)
    rows = []
    for world, cases in bench.dev_worlds(SEARCH + NATIVE, [2.6], seeds=SEEDS).items():
        case = bench.pooled(cases)
        runs = score.valid_runs(case.gt)
        codes = [chain.decode(h).codes for h in case.halves]
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        for run in RUNS:
            for trim in (t for t in TRIMS if 2 * t < run):
                p = chain.replace(dead_min_run=run, dead_trim=trim).params
                dead = [_missing_run_dead(c, h, p) for c, h in zip(codes, case.halves)]
                for gap in GAPS:
                    preds = [close_dead(c, gap, h.id.kickoff) for c, h in zip(dead, case.halves)]
                    f1, n = score.spell_f1(case.layout, case.gt, preds, runs)
                    rows.append({"group": bench.group(world), "run": run, "trim": trim, "gap": gap,
                                 "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    t = pd.DataFrame(rows)
    m = t.pivot_table(index=["run", "trim", "gap"], columns="group", values="margin")
    m["min"], m["mean"] = m.min(1), m.mean(1)
    print(m.sort_values(["min", "mean"], ascending=False).round(4).head(25).to_string())
    print(m["min"].unstack("trim").round(4).to_string())


CHAIN = {"temper": (0.05, 0.1, 0.2), "poss_mean_s": (3.0, 4.5, 6.0, 9.0),
         "p_dead_after_poss": (0.1, 0.3), "dead_mean_s": (8.0, 15.0)}
DEAD_RULES = ((101, 50, 0), (101, 25, 0), (151, 25, 0), (151, 0, 0))


def chain_grid(params):
    base, s50 = Decoder.load(params).replace(dead_min_run=0, dead_trim=0), bench.Smoother(50)
    keys = list(CHAIN)
    candidates = [dict(zip(keys, v)) for v in itertools.product(*CHAIN.values())]
    rows = []
    for world, cases in bench.dev_worlds(SEARCH + NATIVE, [2.6], seeds=SEEDS).items():
        case = bench.pooled(cases)
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        for values in candidates:
            model = base.replace(**values)
            codes = [model.decode(h).codes for h in case.halves]
            for run, trim, gap in DEAD_RULES:
                p = model.replace(dead_min_run=run, dead_trim=trim).params
                preds = [close_dead(_missing_run_dead(c, h, p), gap, h.id.kickoff) for c, h in zip(codes, case.halves)]
                f1, n = score.spell_f1(case.layout, case.gt, preds, runs)
                rows.append({"group": bench.group(world), **values, "run": run, "trim": trim, "gap": gap,
                             "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    t = pd.DataFrame(rows)
    m = t.pivot_table(index=keys + ["run", "trim", "gap"], columns="group", values="margin")
    m["min"], m["mean"] = m.min(1), m.mean(1)
    print(m.sort_values(["min", "mean"], ascending=False).round(4).head(30).to_string())


def confirm(path):
    t = pd.read_csv(path)
    pooled = t[t.case == "dev_pooled"].assign(group=lambda f: f.world.map(bench.group))
    spell = pooled.pivot_table(index=["group", "world"], columns="model", values="spell_f1")
    margin = spell.sub(spell["baseline_smooth50"], axis=0).groupby("group").mean()
    print("seed-mean pooled margin over smooth50 per group")
    print(margin.T.assign(min=margin.T.min(1), mean=margin.T.mean(1)).sort_values("min", ascending=False)
          .round(4).to_string())
    games = t[(t.case != "dev_pooled") & t.world.str.endswith("_native")]
    if games.empty:
        return
    wide = games.pivot_table(index=["world", "case"], columns="model", values="spell_f1")
    models = [m for m in wide.columns if m != "baseline_smooth50"]
    print("\nnative PFF, paired per game: mean difference [90% t interval], games won")
    for world, w in wide.groupby(level="world"):
        for a, b in itertools.permutations(models + ["baseline_smooth50"], 2):
            if a == "baseline_smooth50" or (b != "baseline_smooth50" and a > b):
                continue
            d = (w[a] - w[b]).to_numpy()
            h = 1.669 * d.std(ddof=1) / np.sqrt(len(d))
            print(f"  {world} {a} - {b}: {d.mean():+.4f} [{d.mean() - h:+.4f}, {d.mean() + h:+.4f}] "
                  f"won {(d > 0).sum()}/{len(d)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("probe", choices=("oracle", "geometry", "barath-geometry", "close", "deadrule", "chain", "confirm"))
    ap.add_argument("params", nargs="?")
    a = ap.parse_args()
    {"oracle": lambda: oracle(a.params), "geometry": geometry, "barath-geometry": barath_geometry,
     "close": lambda: close(a.params), "deadrule": lambda: deadrule(a.params),
     "chain": lambda: chain_grid(a.params), "confirm": lambda: confirm(a.params)}[a.probe]()
