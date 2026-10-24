"""Diagnostic probes behind the 2026-10-24 hillclimb report. Run from the repo root:

    PYTHONPATH=. python experiments/hillclimb-2026-10-24/probes.py <probe> [args]

oracle PARAMS        headroom: perfect dead ball or perfect team calls on top of PARAMS (dev labels only)
geometry             how the nearest-team token and dead ball depend on geometry, on Metrica and IDSSE labels
barath-geometry      the same geometry, match-wide on BAR-ATH's ATD, with no labels read
close PARAMS         PARAMS with short live gaps between dead runs closed, on the 7-group objective
deadrule PARAMS --out CSV
                     every (dead_min_run, dead_trim, close gap) on PARAMS's chain, decoded once per world;
                     native PFF worlds split into odd (A, selection) and even (B, held-out) games
chain PARAMS         a grid of chain constants on top of PARAMS, each decoded once, under a few dead rules
edges PARAMS --out CSV
                     like deadrule, with separate start and end trims on each dead run
select CSV...        apply the pre-registered final rule (decision log, rule v2) to deadrule tables
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
T90 = 1.69  # two-sided 90% t quantile for about 32 games; 1.67 at 64
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


RUNS = (101, 126)
TRIMS = (0, 12, 25, 37, 50)
GAPS = (0, 100, 150, 200, 300)


def scored_cases(worlds):
    """(group, pooled Case) per world; a native world becomes two cases, its odd-indexed games ("_A",
    the selection half) and its even-indexed games ("_B", held out)."""
    for world, cases in worlds.items():
        case = bench.pooled(cases)
        if not world.endswith("_native"):
            yield bench.group(world), world, case
            continue
        games = list(dict.fromkeys(h.id.match for h in case.halves))
        labels = case.layout.cut(case.gt)
        for tag, keep in (("A", set(games[0::2])), ("B", set(games[1::2]))):
            idx = [i for i, h in enumerate(case.halves) if h.id.match in keep]
            sub = bench._dev_cases([labels[i] for i in idx], [case.halves[i] for i in idx])
            yield f"{world}_{tag}", f"{world}_{tag}", bench.pooled(sub)


def deadrule(params, out, rhos, items):
    chain, s50 = Decoder.load(params).replace(dead_min_run=0, dead_trim=0, dead_close=0, dead_outside_m=0.0), bench.Smoother(50)
    rows = []
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
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
                    rows.append({"group": group, "world": world, "run": run, "trim": trim, "gap": gap,
                                 "spell_f1": f1, "floor": floor, "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    t = pd.DataFrame(rows)
    t.to_csv(out, index=False, float_format="%.6f")
    m = t.pivot_table(index=["run", "trim", "gap"], columns="group", values="margin")
    select = [c for c in m.columns if not c.endswith("_B")]
    m["J_select"], m["mean_select"] = m[select].min(axis=1), m[select].mean(axis=1)
    m["min_B"] = m[[c for c in m.columns if c.endswith("_B")]].min(axis=1)
    print(m.sort_values(["J_select", "mean_select"], ascending=False).round(4).head(25).to_string())
    print(out)


CHAIN = {"temper": (0.05, 0.1, 0.2), "poss_mean_s": (3.0, 4.5, 6.0, 9.0),
         "p_dead_after_poss": (0.1, 0.3)}
DEAD_RULES = ((101, 0, 150), (126, 0, 150), (151, 0, 150), (101, 25, 200))


def chain_grid(params):
    base, s50 = Decoder.load(params).replace(dead_min_run=0, dead_trim=0, dead_close=0, dead_outside_m=0.0), bench.Smoother(50)
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
    print("\nnative PFF, paired per game: mean difference [90% t interval], games won; "
          "A = odd-indexed games (selection), B = even-indexed (held out)")
    for world, w in wide.groupby(level="world"):
        order = list(dict.fromkeys(games[games.world == world].case))
        split = {"all": order, "A": order[0::2], "B": order[1::2]}
        for a, b in itertools.permutations(models + ["baseline_smooth50"], 2):
            if a == "baseline_smooth50" or (b != "baseline_smooth50" and a > b):
                continue
            cells = []
            for tag, keep in split.items():
                d = (w[a] - w[b]).loc[world].loc[keep].to_numpy()
                h = T90 * d.std(ddof=1) / np.sqrt(len(d))
                cells.append(f"{tag} {d.mean():+.4f} [{d.mean() - h:+.4f}, {d.mean() + h:+.4f}] "
                             f"{(d > 0).sum()}/{len(d)}")
            print(f"  {world} {a} - {b}: " + "; ".join(cells))


EDGE_RUNS = (101, 126)
EDGE_START = (0, 25, 50)
EDGE_END = (0, 25, 50, 75, 100)
EDGE_GAPS = (150, 200)


def edge_dead(codes, half, run, start_trim, end_trim):
    """decoder._missing_run_dead with dead_trim split into a start and an end trim (dead_close applied after)."""
    kickoff, n = half.id.kickoff, half.n
    team = codes.copy()
    called = np.flatnonzero(team != D)
    if len(called):
        last = np.maximum.accumulate(np.where(team != D, np.arange(n), -1))
        team = np.where(last >= 0, team[np.maximum(last, 0)], team[called[0]]).astype(np.int8)
    missing = np.concatenate(([False], half.nearest_team == -1, [False]))
    edges = np.flatnonzero(np.diff(missing.view(np.int8)))
    dead = np.zeros(n + 1, dtype=np.int32)
    for start, stop in zip(edges[::2], edges[1::2]):
        lo = start + start_trim if start > 0 else -run
        hi = stop - end_trim if stop < n else n + run
        if hi - lo >= run - start_trim - end_trim and min(hi, n) > max(lo, 0):
            dead[max(lo, 0)] += 1
            dead[min(hi, n)] -= 1
    out = np.where(np.cumsum(dead[:n]) > 0, D, team).astype(np.int8)
    out[:kickoff] = D
    return out


def edges_grid(params, out, rhos, items):
    chain = Decoder.load(params).replace(dead_min_run=0, dead_trim=0, dead_close=0, dead_outside_m=0.0)
    s50, rows = bench.Smoother(50), []
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        runs = score.valid_runs(case.gt)
        codes = [chain.decode(h).codes for h in case.halves]
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        for run, a, b in itertools.product(EDGE_RUNS, EDGE_START, EDGE_END):
            dead = [edge_dead(c, h, run, a, b) for c, h in zip(codes, case.halves)]
            for gap in EDGE_GAPS:
                preds = [close_dead(c, gap, h.id.kickoff) for c, h in zip(dead, case.halves)]
                f1, n = score.spell_f1(case.layout, case.gt, preds, runs)
                rows.append({"group": group, "world": world, "run": run, "trim": f"{a}/{b}", "gap": gap,
                             "spell_f1": f1, "floor": floor, "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out)


INCUMBENT = (101, 50, 0)
VETO_SLACK = 0.003


def select(paths):
    """Rule v2: synthetic groups veto (each margin >= the incumbent's minus VETO_SLACK), the minimum over the
    PFF-A groups ranks, the synthetic minimum breaks ties within VETO_SLACK. PFF-B is shown, never used."""
    t = pd.concat([pd.read_csv(path) for path in paths], ignore_index=True)
    t = t[t.run.isin(RUNS) & t.trim.isin(TRIMS) & t.gap.isin(GAPS)]
    m = t.pivot_table(index=["run", "trim", "gap"], columns="group", values="margin")
    synth = [c for c in m.columns if "_native" not in c]
    pff_a = [c for c in m.columns if c.endswith("_native_A")]
    pff_b = [c for c in m.columns if c.endswith("_native_B")]
    print(f"{len(m)} candidates; synthetic groups {len(synth)}: {', '.join(synth)}")
    floor = m.loc[INCUMBENT, synth] - VETO_SLACK
    m["vetoed_by"] = (m[synth] < floor).apply(lambda r: ",".join(c for c, v in r.items() if v), axis=1)
    m["synth_min"], m["pff_a_min"], m["pff_b_min"] = m[synth].min(axis=1), m[pff_a].min(axis=1), m[pff_b].min(axis=1)
    ok = m[m.vetoed_by == ""].sort_values("pff_a_min", ascending=False)
    best = ok.pff_a_min.iloc[0]
    tied = ok[ok.pff_a_min >= best - VETO_SLACK].sort_values("synth_min", ascending=False)
    cols = ["synth_min", "pff_a_min", "pff_b_min"]
    print(f"\n{len(ok)} pass the veto; top by PFF-A minimum:")
    print(ok[cols].head(12).round(4).to_string())
    print(f"\nwithin {VETO_SLACK} of the best PFF-A minimum, by synthetic minimum:")
    print(tied[cols].round(4).to_string())
    print(f"\nincumbent {INCUMBENT}:", m.loc[INCUMBENT, cols].round(4).to_dict())
    print("vetoed examples:", m[m.vetoed_by != ""].sort_values("pff_a_min", ascending=False)[["pff_a_min", "vetoed_by"]]
          .head(6).round(4).to_string())
    print("\nSELECTED", tied.index[0])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("probe", choices=("oracle", "geometry", "barath-geometry", "close", "deadrule", "chain", "confirm", "select", "edges"))
    ap.add_argument("params", nargs="*")
    ap.add_argument("--out", help="deadrule: where to write the full grid table (CSV)")
    ap.add_argument("--dead-bias", type=float, nargs="+", default=[2.6], help="deadrule: generator dead_bias worlds")
    ap.add_argument("--rule", nargs="+", default=SEARCH + NATIVE, help="deadrule: [source:]rule[:mode] items")
    a = ap.parse_args()
    one = a.params[0] if a.params else None
    {"oracle": lambda: oracle(one), "geometry": geometry, "barath-geometry": barath_geometry,
     "close": lambda: close(one), "deadrule": lambda: deadrule(one, a.out, a.dead_bias, a.rule),
     "chain": lambda: chain_grid(one), "confirm": lambda: confirm(one), "select": lambda: select(a.params),
     "edges": lambda: edges_grid(one, a.out, a.dead_bias, a.rule)}[a.probe]()
