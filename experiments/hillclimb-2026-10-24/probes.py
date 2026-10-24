"""Diagnostic probes behind the 2026-10-24 hillclimb report. Run from the repo root:

    PYTHONPATH=. python experiments/hillclimb-2026-10-24/probes.py <probe> [args]

oracle PARAMS        headroom: perfect dead ball or perfect team calls on top of PARAMS (dev labels only)
geometry             how the nearest-team token and dead ball depend on geometry, on Metrica and IDSSE labels
pff-geometry         token reliability by nearest-player distance and team margin on native PFF frames the
                     tracker saw (no held balls), plus P(dead) off the pitch
barath-geometry      the same geometry, match-wide on BAR-ATH's ATD, with no labels read
close PARAMS         PARAMS with short live gaps between dead runs closed, on the 7-group objective
deadrule PARAMS --out CSV
                     every (dead_min_run, dead_trim, close gap) on PARAMS's chain, decoded once per world;
                     native PFF worlds split into odd (A, selection) and even (B, held-out) games
chain PARAMS         a grid of chain constants on top of PARAMS, each decoded once, under a few dead rules
edges PARAMS --out CSV
                     like deadrule, with separate start and end trims on each dead run
logit PARAMS --out CSV
                     fit logit(q) = a + b ln(1+d) + c ln(1+m) on PFF-A seen alive frames, then grid temper
                     for PARAMS's decoder with the constant q and with the fitted q
speed                does ball speed explain token reliability beyond distance and margin: 2-fold log loss
                     inside the PFF A games, q by speed band, and the speed distribution on PFF and BAR-ATH
spells PARAMS        where PARAMS loses possessions: GT and predicted counts, precision and recall per IoU, recall
                     by GT length and precision by predicted length (dev labels only)
lag PARAMS --out CSV
                     PARAMS's codes with every team-to-team hand-over moved L frames later (E6); held-out B games
                     are not decoded
snap PARAMS --out CSV
                     E7: each team-to-team hand-over moved to the receiving team's first close frame (snap radius),
                     then lagged; held-out B games are not decoded
chain5 PARAMS --out CSV
                     E8: temper x poss_mean_s and stride variants of PARAMS, each decoded in full; held-out B games
                     are not decoded
speedlogit PARAMS --out CSV
                     E9: refit the logistic emission with ball speed terms on PFF-A, then grid it against PARAMS's
                     emission across hand-over lags; held-out B games are not decoded
masked PARAMS --out CSV
                     E10: the chain decoded with the final dead-run mask as hard evidence, across p_flip_after_dead
                     and hand-over lags; held-out B games are not decoded
still                P(dead) by ball speed on frames PFF's tracker saw in the A games, inside runs of slow frames,
                     and the slow-run lengths on BAR-ATH (no labels)
stillgrid PARAMS --out CSV
                     E11: PARAMS with slow-ball runs counted as missing by the dead-run stage; held-out B games are
                     not decoded
dead6 PARAMS --out CSV
                     E12: dead_min_run x dead_trim x dead_close on PARAMS's other fields, as stillgrid does
motion               P(dead) by the median player speed on the PFF A games, overall and inside ball-missing runs by
                     run length, and the same speed on BAR-ATH (no labels)
pacegrid PARAMS --out CSV
                     E13: the median-player-speed knobs of the dead-run stage on PARAMS, as stillgrid does
push                 P(home possession) by the teams' push toward the goal they attack (median per-player x
                     velocity, signed by the attacking direction at kick-off) on PFF A games, ball seen or not
lag7 PARAMS --out CSV
                     E17: handover_lag on PARAMS, as stillgrid does
deadlogit PARAMS --out CSV
                     E18: a logistic P(dead) per frame fitted on PFF-A replaces the dead-run finder's flags; B games
                     are not decoded
pick SYNTH PFF BASE --prefer V...
                     the selection every experiment from E8 on registers: synthetic groups veto (each margin at least
                     BASE's minus VETO_SLACK), the PFF-A minimum ranks, and a tie within VETO_SLACK goes to BASE, then
                     to the variants in --prefer order (the registered tie order), then to the higher PFF-A minimum
combo PARAMS --out CSV
                     E19: the near-miss settings of E11, E12, E13 and E17 crossed on PARAMS, as stillgrid does
select CSV...        apply the pre-registered final rule (decision log, rule v2) to deadrule tables
confirm CSV          a `score` run table: per-group margins over smooth50 for every model, and paired
                     per-game differences with 90% t intervals on the native PFF games

Oracle rows read other games' labels and are diagnostics, never candidates. Nothing here reads a BAR-ATH
label or the public window.
"""
import argparse
import dataclasses
import itertools

import numpy as np
import pandas as pd

from possession import bench, challenge, idsse, metrica, score
from possession.decoder import Decoder, _missing_run_dead
from possession.half import FPS, D, H

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


def oracle(params, rhos=(2.6,), items=SEARCH):
    model, s50 = Decoder.load(params), bench.Smoother(50)
    rows = []
    for world, cases in bench.dev_worlds(items, rhos, seeds=SEEDS).items():
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


def pff_geometry():
    from possession import pff
    frames = []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        seen = pff.native_seen(c)
        f = features(c.geometry).assign(label=c.labels)
        frames.append(f[seen & (np.arange(c.geometry.n) >= c.id.kickoff)])
    t = pd.concat(frames, ignore_index=True)
    alive = t[t.label != D].assign(agree=lambda f: f.team == f.label)
    print(f"native PFF seen frames {len(t)}, alive {len(alive)}, overall q {alive.agree.mean():.3f}")
    for col, bins in (("d_near", BINS_D), ("margin", BINS_M)):
        g = alive.groupby(pd.cut(alive[col], bins, include_lowest=True), observed=False)
        print(pd.DataFrame({"share": g.size() / len(alive), "q": g.agree.mean()}).round(3).T.to_string())
    g = alive.groupby([pd.cut(alive.d_near, [0, 1.5, 3, 1e9]), pd.cut(alive.margin, [0, 1, 3, 1e9], include_lowest=True)],
                      observed=False)
    print(pd.DataFrame({"share": g.size() / len(alive), "q": g.agree.mean()}).round(3).to_string())
    g = t.groupby(pd.cut(t.to_line, BINS_LINE), observed=False)
    print(pd.DataFrame({"share": g.size() / len(t), "p_dead": g.label.apply(lambda s: (s == D).mean())}).round(3).T.to_string())


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


MARGIN_CAP_M = 30.0
TEMPERS = (0.03, 0.05, 0.1, 0.2)


def _logit_features(nearest_m, margin_m):
    return np.stack([np.ones_like(nearest_m), np.log1p(nearest_m), np.log1p(np.minimum(margin_m, MARGIN_CAP_M))], 1)


def fit_logit(speed=False):
    """Logistic fit of P(token == labelled team) on native PFF seen alive frames of the A games (games[0::2]
    in pff.load order, the same split as scored_cases). speed adds ln(1+v) and ln(1+d)ln(1+v), v the decoder's
    BallGeometry.speed_mps capped at 40."""
    from possession import challenge, pff
    games, xs, ys = [], [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        h = challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id)
        keep = (h.nearest_team != -1) & (c.labels != D) & (np.arange(h.n) >= h.id.kickoff)
        x = _logit_features(h.geometry.nearest_m[keep].astype(np.float64), h.geometry.margin_m[keep].astype(np.float64))
        if speed:
            lv = np.log1p(np.minimum(h.geometry.speed_mps[keep].astype(np.float64), 40.0))
            x = np.column_stack([x, lv, x[:, 1] * lv])
        xs.append(x)
        ys.append((h.nearest_team[keep] == c.labels[keep]).astype(np.float64))
    x, y = np.concatenate(xs), np.concatenate(ys)
    w = _newton(x, y)
    p = np.clip(1 / (1 + np.exp(-x @ w)), 1e-9, 1 - 1e-9)
    print(f"fit on {len(y)} frames of {len(games[0::2])} A games: weights {w.tolist()}, mean q {y.mean():.3f}, "
          f"log loss {-np.mean(y * np.log(p) + (1 - y) * np.log1p(-p)):.5f}")
    return w


@dataclasses.dataclass(frozen=True)
class LogitEmission:
    """Probe-only: Tier0Emission with q per seen frame from the fitted logistic."""
    base: object
    w: tuple

    def loglik(self, half):
        out = self.base.loglik(half).astype(np.float64)
        g, tok = half.geometry, half.nearest_team
        where = tok != -1
        q = 1 / (1 + np.exp(-_logit_features(g.nearest_m[where].astype(np.float64),
                                              g.margin_m[where].astype(np.float64)) @ np.asarray(self.w)))
        q0 = self.base.q
        seen_row = (out[where, 0] + out[where, 1] - np.log(q0) - np.log1p(-q0)) / 2
        home = tok[where] == 0
        out[where, 0] = np.where(home, np.log(q), np.log1p(-q)) + seen_row
        out[where, 1] = np.where(home, np.log1p(-q), np.log(q)) + seen_row
        return out.astype(np.float32)


def logit_grid(params, out, rhos, items):
    from possession.decoder import Decoder as Dec
    w = tuple(fit_logit())
    base, s50, rows = Decoder.load(params), bench.Smoother(50), []
    variants = {}
    for temper in TEMPERS:
        m = base.replace(temper=temper)
        variants[("const", temper)] = m
        variants[("logit", temper)] = Dec(LogitEmission(m.emission, w), m.params)
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        for (kind, temper), model in variants.items():
            f1, n = score.spell_f1(case.layout, case.gt, [model.decode(h).codes for h in case.halves], runs)
            rows.append({"group": group, "world": world, "emission": kind, "temper": temper,
                         "spell_f1": f1, "floor": floor, "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out, "w", w)


SPEED_BINS = [0, 1, 2, 4, 8, 15, 25, 1e9]


def ball_speed(ball, k):
    """m/s from the displacement between frames t-k and t+k, else between t and t+-k; NaN with no seen
    neighbour at distance k."""
    b, n = ball.astype(np.float64), len(ball)
    pad = np.full((k, 2), np.nan)
    back, fwd = np.vstack([pad, b[:-k]]), np.vstack([b[k:], pad])
    both = np.hypot(*(fwd - back).T) / (2 * k)
    one = np.fmax(np.hypot(*(b - back).T), np.hypot(*(fwd - b).T)) / k
    return np.where(np.isnan(both), one, both) * FPS


def _newton(x, y):
    w = np.zeros(x.shape[1])
    for _ in range(25):
        p = 1 / (1 + np.exp(-x @ w))
        w = w + np.linalg.solve((x * (p * (1 - p))[:, None]).T @ x, x.T @ (y - p))
    return w


def speed_probe():
    from possession import pff
    games, parts = [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        h = challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id)
        keep = (h.nearest_team != -1) & (c.labels != D) & (np.arange(h.n) >= h.id.kickoff)
        parts.append(pd.DataFrame({"fold": len(games) // 2 % 2, "d": h.geometry.nearest_m[keep],
                                   "m": np.minimum(h.geometry.margin_m[keep], MARGIN_CAP_M),
                                   "v1": ball_speed(ball, 1)[keep], "v2": ball_speed(ball, 2)[keep],
                                   "agree": h.nearest_team[keep] == c.labels[keep]}))
    t = pd.concat(parts, ignore_index=True)
    print(f"{len(t)} frames, speed NaN share v1 {t.v1.isna().mean():.3f} v2 {t.v2.isna().mean():.3f}")
    base = ["one", "ld", "lm"]
    t = t.assign(one=1.0, ld=np.log1p(t.d), lm=np.log1p(t.m))
    for k in ("v1", "v2"):
        v = t[k].fillna(t[k].median()).clip(upper=40)
        t[f"l{k}"], t[f"n{k}"] = np.log1p(v), t[k].isna().astype(float)
    sets = {"d+m": base, "d+m+v1": base + ["lv1", "nv1"], "d+m+v2": base + ["lv2", "nv2"],
            "d+m+v2+dxv": base + ["lv2", "nv2", "dxv"]}
    t["dxv"] = t.ld * t.lv2
    y = t.agree.to_numpy(float)
    for name, cols in sets.items():
        loss = []
        for fold in (0, 1):
            tr, te = t.fold != fold, t.fold == fold
            w = _newton(t.loc[tr, cols].to_numpy(), y[tr])
            p = np.clip(1 / (1 + np.exp(-t.loc[te, cols].to_numpy() @ w)), 1e-6, 1 - 1e-6)
            loss.append(-np.mean(y[te] * np.log(p) + (1 - y[te]) * np.log1p(-p)))
        w = _newton(t[cols].to_numpy(), y)
        print(f"{name:12s} 2-fold log loss {np.mean(loss):.5f}  full-A weights {np.round(w, 4).tolist()}")
    g = t.groupby([pd.cut(t.d, [0, 1.5, 3, 1e9]), pd.cut(t.v2, SPEED_BINS, include_lowest=True)], observed=False)
    print(pd.DataFrame({"share": g.size() / len(t), "q": g.agree.mean()}).round(3).unstack(0).to_string())
    for name, v in (("PFF A seen alive", t.v2),):
        print(name, "v2 speed percentiles 10/50/90/99:", np.nanpercentile(v, [10, 50, 90, 99]).round(2).tolist())
    for g_, hid in zip(challenge.load_geometry(), challenge._half_ids()):
        v = ball_speed(g_.ball_xy, 2)[hid.kickoff:]
        v = v[np.isfinite(g_.ball_xy[hid.kickoff:, 0]) & np.isfinite(v)]
        print(f"BAR-ATH half {hid.half} seen frames v2 percentiles 10/50/90/99:",
              np.percentile(v, [10, 50, 90, 99]).round(2).tolist(),
              "share by band", np.round(np.histogram(v, SPEED_BINS)[0] / len(v), 3).tolist())


LEN_BANDS = [0, 25, 50, 100, 200, 400, 1e9]


def pm_greedy(overlaps, threshold):
    """Per GT spell, the index of the prediction the official greedy match pairs it with at threshold, else -1."""
    n_gt = 1 + max((i for _, i, _ in overlaps), default=-1)
    out, used = np.full(n_gt, -1), set()
    for iou, i, j in overlaps:
        if iou < threshold:
            break
        if out[i] >= 0 or j in used:
            continue
        out[i] = j
        used.add(j)
    return out


def spells_probe(params, rhos, items):
    from evaluation import possession_metrics as pm
    model, s50 = Decoder.load(params), bench.Smoother(50)
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        runs = score.valid_runs(case.gt)
        gt_sp = pm.possession_spells(case.gt, runs)
        for name, dec in (("model", model), ("s50", s50)):
            pred = pm.fill_abstentions(score._assemble_checked(case.layout, case.gt, [dec.decode(h).codes for h in case.halves]), runs)
            pr_sp = pm.possession_spells(pred, runs)
            ov = pm.spell_overlaps(gt_sp, pr_sp)
            line = []
            for iou in (0.3, 0.5, 0.7):
                g = pm.matched_gt_flags(ov, len(gt_sp), iou)
                line.append(f"iou{iou} P {g.sum() / max(len(pr_sp), 1):.3f} R {g.mean():.3f}")
            print(f"{world:22s} {name:5s} gt {len(gt_sp):6d} pred {len(pr_sp):6d}  " + "  ".join(line))
            if name != "model":
                continue
            g = pm.matched_gt_flags(ov, len(gt_sp), 0.5)
            pf = np.zeros(len(pr_sp), bool)
            done = set()
            for iou, i, j in ov:
                if iou < 0.5:
                    break
                if i in done or pf[j]:
                    continue
                done.add(i); pf[j] = True
            pairs = [(i, j) for i, j in enumerate(pm_greedy(ov, 0.3)) if j >= 0]
            for side, k in (("start", 0), ("end", 1)):
                off = {"after D": [], "after team": []}
                for i, j in pairs:
                    f = gt_sp[i][k] - 1 if k == 0 else gt_sp[i][k]
                    if 0 <= f < len(case.gt) and case.gt[f] in (D, 1 - gt_sp[i][2]):
                        off["after D" if case.gt[f] == D else "after team"].append(pr_sp[j][k] - gt_sp[i][k])
                print(f"    {side} offset pred-GT frames, matched@0.3:", {t: (len(v), np.percentile(v, [25, 50, 75]).round(0).tolist())
                                                                       for t, v in off.items() if v})
            gl = np.array([b - a for a, b, _ in gt_sp]); pl = np.array([b - a for a, b, _ in pr_sp])
            gb, pb = pd.cut(gl, LEN_BANDS), pd.cut(pl, LEN_BANDS)
            print("    GT by length (frames): share", pd.Series(gl).groupby(gb, observed=False).size().div(len(gl)).round(3).tolist(),
                  "recall@0.5", pd.Series(g).groupby(gb, observed=False).mean().round(3).tolist())
            print("    pred by length:        share", pd.Series(pl).groupby(pb, observed=False).size().div(len(pl)).round(3).tolist(),
                  "precision@0.5", pd.Series(pf).groupby(pb, observed=False).mean().round(3).tolist())


LAGS = (0, 5, 10, 15, 20, 25, 30)


def lag_handovers(codes, lag):
    """Inside each maximal run of H/A frames, team[t] = team[max(t - lag, run start)]: every hand-over
    between the teams moves lag frames later, and the run's edges stay put."""
    live = (codes == H) | (codes == 1 - H)
    idx = np.arange(len(codes))
    start = np.where(live & ~np.r_[False, live[:-1]], idx, 0)
    np.maximum.accumulate(start, out=start)
    out = codes.copy()
    out[live] = codes[np.maximum(idx - lag, start)[live]]
    return out


SNAPS = (None, 0.5, 1.0, 1.5, 2.0, 3.0)


def snap_handovers(codes, tok, near, radius):
    """Each hand-over between the teams moves to the first frame of the new team's segment where the token is
    that team at nearest_m < radius; the old team keeps the frames before it. No such frame: no move."""
    live = (codes == H) | (codes == 1 - H)
    with np.errstate(invalid="ignore"):
        close = (tok >= 0) & (near < radius)
    out = codes.copy()
    turns = np.flatnonzero(live[1:] & live[:-1] & (codes[1:] != codes[:-1])) + 1
    ends = np.r_[turns[1:], len(codes)]
    for t, e in zip(turns, ends):
        y = codes[t]
        stop = t + np.argmax(codes[t:e] != y) if (codes[t:e] != y).any() else e
        hit = np.flatnonzero(close[t:stop] & (tok[t:stop] == y))
        if hit.size and hit[0] > 0:
            out[t:t + hit[0]] = out[t - 1]
    return out


def snap_grid(params, out, rhos, items):
    model, s50, rows = Decoder.load(params), bench.Smoother(50), []
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        codes = [model.decode(h).codes for h in case.halves]
        for radius in SNAPS:
            snapped = codes if radius is None else [
                snap_handovers(c, h.nearest_team, h.geometry.nearest_m, radius) for c, h in zip(codes, case.halves)]
            for lag in LAGS:
                f1, n = score.spell_f1(case.layout, case.gt, [lag_handovers(c, lag) for c in snapped], runs)
                rows.append({"group": group, "world": world, "snap": radius if radius else 0.0, "lag": lag,
                             "spell_f1": f1, "floor": floor, "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out)


CHAIN5 = [{"temper": t, "poss_mean_s": m} for t in (0.07, 0.1, 0.14) for m in (4.5, 6.0, 9.0)] + \
    [{"stride": 1}, {"stride": 2}]


def chain5_grid(params, out, rhos, items):
    base, s50, rows = Decoder.load(params), bench.Smoother(50), []
    variants = {tuple(sorted(v.items())): base.replace(**v) for v in CHAIN5}
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        for key, model in variants.items():
            f1, n = score.spell_f1(case.layout, case.gt, [model.decode(h).codes for h in case.halves], runs)
            rows.append({"group": group, "world": world, "variant": " ".join(f"{k}={v}" for k, v in key),
                         "spell_f1": f1, "floor": floor, "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out)


def speedlogit_grid(params, out, rhos, items):
    a, b, c, e, f = fit_logit(speed=True)
    base, s50, rows = Decoder.load(params), bench.Smoother(50), []
    fast = base.replace(q_logit_a=a, q_logit_dist=b, q_logit_margin=c, q_logit_speed=e, q_logit_dist_speed=f)
    variants = {(kind, lag): m.replace(handover_lag=lag) for kind, m in (("base", base), ("speed", fast))
                for lag in (10, 15, 20)}
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        for (kind, lag), model in variants.items():
            f1, n = score.spell_f1(case.layout, case.gt, [model.decode(h).codes for h in case.halves], runs)
            rows.append({"group": group, "world": world, "variant": f"{kind} lag={lag}", "spell_f1": f1,
                         "floor": floor, "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out, "speed weights", [a, b, c, e, f])


MASK_PENALTY = 50.0


def dead_mask(half, p):
    return _missing_run_dead(np.full(half.n, H, np.int8), half, p) == D


@dataclasses.dataclass(frozen=True)
class MaskedEmission:
    """Probe-only: base emission plus a large penalty on H and A inside the dead mask and on D outside it."""
    base: object
    rule: object

    def loglik(self, half):
        out = self.base.loglik(half).astype(np.float64)
        dead = dead_mask(half, self.rule)
        out[dead, :2] -= MASK_PENALTY
        out[~dead, 2] -= MASK_PENALTY
        return out.astype(np.float32)


def masked_codes(base, half, p_flip, lag):
    from possession.decoder import Decoder as Dec, _lag_handovers
    chain = dataclasses.replace(base.params, dead_min_run=0, dead_trim=0, dead_close=0, dead_outside_m=0.0,
                                handover_lag=0, p_flip_after_dead=p_flip)
    post = Dec(MaskedEmission(base.emission, base.params), chain).decode(half).posterior
    team = np.where(np.round(post[:, 1], 9) > np.round(post[:, 0], 9), 1 - H, H)
    return _lag_handovers(np.where(dead_mask(half, base.params), D, team).astype(np.int8), lag)


def masked_grid(params, out, rhos, items):
    base, s50, rows = Decoder.load(params), bench.Smoother(50), []
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        variants = {"base lag=15": [base.decode(h).codes for h in case.halves]}
        for p_flip in (0.5, 0.73, 0.85):
            for lag in (10, 15, 20):
                variants[f"masked p_flip={p_flip} lag={lag}"] = [masked_codes(base, h, p_flip, lag) for h in case.halves]
        for name, codes in variants.items():
            f1, n = score.spell_f1(case.layout, case.gt, codes, runs)
            rows.append({"group": group, "world": world, "variant": name, "spell_f1": f1, "floor": floor,
                         "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out)


STILL_BINS = [0, 0.25, 0.5, 1, 1.5, 2, 3, 5, 1e9]


def _runs(flag):
    edges = np.flatnonzero(np.diff(np.r_[0, flag.astype(np.int8), 0]))
    return edges[::2], edges[1::2]


def still_probe():
    from possession import pff
    games, parts = [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        h = challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id)
        v = h.geometry.speed_mps
        run_len = np.zeros(h.n)
        for a, b in zip(*_runs((h.nearest_team != -1) & (v < 1.0))):
            run_len[a:b] = b - a
        keep = (h.nearest_team != -1) & (np.arange(h.n) >= h.id.kickoff)
        parts.append(pd.DataFrame({"v": v[keep], "slow_run": run_len[keep], "dead": c.labels[keep] == D}))
    t = pd.concat(parts, ignore_index=True)
    print(f"{len(t)} seen frames after kick-off in the A games, P(dead) {t.dead.mean():.3f}")
    g = t.groupby(pd.cut(t.v, STILL_BINS, include_lowest=True), observed=False)
    print(pd.DataFrame({"share": g.size() / len(t), "p_dead": g.dead.mean()}).round(3).T.to_string())
    g = t[t.v < 1].groupby(pd.cut(t.slow_run[t.v < 1], [0, 5, 12, 25, 50, 100, 1e9]), observed=False)
    print("frames under 1 m/s by the length of their slow run (frames):")
    print(pd.DataFrame({"share": g.size() / len(t), "p_dead": g.dead.mean()}).round(3).T.to_string())
    for g_, hid in zip(challenge.load_geometry(), challenge._half_ids()):
        h = challenge.observe(g_, hid)
        a, b = _runs((h.nearest_team != -1) & (h.geometry.speed_mps < 1.0))
        lengths = (b - a)[a >= hid.kickoff]
        print(f"BAR-ATH half {hid.half}: slow runs >= 25 frames {(lengths >= 25).sum()}, >= 50 {(lengths >= 50).sum()}, "
              f">= 100 {(lengths >= 100).sum()}; frames in runs >= 50: {lengths[lengths >= 50].sum()}")


STILL_GRID = [{}] + [{"dead_still_mps": v, "dead_still_frames": f} for v in (0.5, 1.0) for f in (25, 50, 100)]
PACE_GRID = [{"dead_pace_live_mps": lv, "dead_pace_still_mps": sv} for lv in (0.0, 1.5, 2.0, 2.5, 3.0)
             for sv in (0.0, 0.5, 0.75)]
LAG7_GRID = [{"handover_lag": lag} for lag in (10, 15, 20, 25)]
COMBO_GRID = [{"handover_lag": lag, "dead_trim": trim, "dead_pace_still_mps": sv, "dead_still_frames": sf}
              for lag in (15, 20) for trim in (50, 37) for sv in (0.5, 0.75) for sf in (50, 25)]
DEAD6_GRID = [{"dead_min_run": r, "dead_trim": t, "dead_close": c}
              for r in (101, 126) for t in (12, 25, 37, 50) for c in (100, 150, 200)]


def rulegrid(params, out, rhos, items, grid):
    """PARAMS's chain decoded once per half, then each grid entry's dead-run and lag fields applied on top;
    held-out B games are not decoded."""
    from possession.decoder import _lag_handovers
    base, s50, rows = Decoder.load(params), bench.Smoother(50), []
    chain = base.replace(dead_min_run=0, dead_trim=0, dead_close=0, dead_outside_m=0.0, dead_still_mps=0.0,
                         dead_still_frames=0, dead_pace_still_mps=0.0, dead_pace_live_mps=0.0, handover_lag=0)
    rules = {" ".join(f"{k}={v}" for k, v in g.items()) or "base": dataclasses.replace(base.params, **g) for g in grid}
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        chained = [chain.decode(h).codes for h in case.halves]
        for name, p in rules.items():
            codes = [_lag_handovers(_missing_run_dead(c, h, p), p.handover_lag) for c, h in zip(chained, case.halves)]
            if p == base.params:
                assert all(np.array_equal(c, base.decode(h).codes) for c, h in zip(codes[:2], case.halves))
            f1, n = score.spell_f1(case.layout, case.gt, codes, runs)
            rows.append({"group": group, "world": world, "variant": name, "spell_f1": f1,
                         "floor": floor, "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out)


MOTION_K = 12
MOTION_BINS = [0, 0.5, 1, 1.5, 2, 3, 1e9]


def centroid_speed(g):
    """Mean over the two teams of each team centroid's speed in m/s, from frames t-K to t+K; NaN at the edges."""
    out = np.zeros(g.n)
    for team in (0, 1):
        c = np.nanmean(g.players_xy[:, g.slot_team == team].astype(np.float64), axis=1)
        k = MOTION_K
        v = np.full(g.n, np.nan)
        v[k:-k] = np.hypot(*(c[2 * k:] - c[:-2 * k]).T) / (2 * k) * FPS
        out += v / 2
    return out


def player_pace(g):
    """Median over slots present at both t-K and t+K of the slot's speed in m/s; NaN where no slot is."""
    k, out = MOTION_K, np.full(g.n, np.nan)
    for lo in range(k, g.n - k, CHUNK):
        hi = min(lo + CHUNK, g.n - k)
        a = g.players_xy[lo - k:hi - k].astype(np.float64)
        b = g.players_xy[lo + k:hi + k].astype(np.float64)
        v = np.hypot(*(b - a).transpose(2, 0, 1)) / (2 * k) * FPS
        with np.errstate(all="ignore"):
            out[lo:hi] = np.nanmedian(np.where(np.isfinite(v), v, np.nan), axis=1)
    return out


def motion_probe():
    from possession import pff
    games, parts = [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        run_len = np.zeros(c.geometry.n)
        for a, b in zip(*_runs(~seen)):
            run_len[a:b] = b - a
        keep = np.arange(c.geometry.n) >= c.id.kickoff
        parts.append(pd.DataFrame({"cv": player_pace(c.geometry)[keep], "miss_run": run_len[keep],
                                   "dead": c.labels[keep] == D}))
    t = pd.concat(parts, ignore_index=True).dropna()
    print(f"{len(t)} frames after kick-off in the A games, P(dead) {t.dead.mean():.3f}")
    g = t.groupby(pd.cut(t.cv, MOTION_BINS, include_lowest=True), observed=False)
    print(pd.DataFrame({"share": g.size() / len(t), "p_dead": g.dead.mean()}).round(3).T.to_string())
    m = t[t.miss_run > 0]
    g = m.groupby([pd.cut(m.miss_run, [0, 25, 50, 126, 250, 1e9]), pd.cut(m.cv, [0, 0.75, 1.5, 1e9], include_lowest=True)],
                  observed=False)
    print("ball-missing frames by missing-run length and centroid speed:")
    print(pd.DataFrame({"share": g.size() / len(t), "p_dead": g.dead.mean()}).round(3).unstack(1).to_string())
    for g_, hid in zip(challenge.load_geometry(), challenge._half_ids()):
        cv = player_pace(g_)[hid.kickoff:]
        seen = np.isfinite(g_.ball_xy[hid.kickoff:, 0])
        print(f"BAR-ATH half {hid.half}: centroid speed percentiles 10/50/90 on seen frames",
              np.nanpercentile(cv[seen], [10, 50, 90]).round(2).tolist(), "on missing frames",
              np.nanpercentile(cv[~seen], [10, 50, 90]).round(2).tolist())


def team_push(g, kickoff):
    """Per team, the median over its slots present at t-K and t+K of the x velocity in m/s, signed so that
    positive is toward the goal the team attacks (it starts the half in the other half of the pitch)."""
    k, out = MOTION_K, np.full((g.n, 2), np.nan)
    length = g.pitch_m[0]
    for team in (0, 1):
        slots = g.slot_team == team
        own_x = np.nanmean(g.players_xy[kickoff, slots, 0])
        sign = 1.0 if own_x < length / 2 else -1.0
        x = g.players_xy[:, slots, 0].astype(np.float64)
        dx = (x[2 * k:] - x[:-2 * k]) / (2 * k) * FPS
        with np.errstate(all="ignore"):
            out[k:-k, team] = sign * np.nanmedian(dx, axis=1)
    return out


def push_probe():
    from possession import pff
    games, parts = [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        push = team_push(c.geometry, c.id.kickoff)
        seen = pff.native_seen(c)
        keep = (np.arange(c.geometry.n) >= c.id.kickoff) & (c.labels != D)
        parts.append(pd.DataFrame({"diff": (push[:, 0] - push[:, 1])[keep], "seen": seen[keep],
                                   "home": c.labels[keep] == H}))
    t = pd.concat(parts, ignore_index=True).dropna()
    print(f"{len(t)} live frames after kick-off in the A games, P(home) {t.home.mean():.3f}")
    bins = [-1e9, -3, -2, -1, -0.5, 0, 0.5, 1, 2, 3, 1e9]
    for name, f in (("all", t), ("ball missing", t[~t.seen]), ("ball seen", t[t.seen])):
        g = f.groupby(pd.cut(f["diff"], bins), observed=False)
        print(name, "home push minus away push (m/s):")
        print(pd.DataFrame({"share": g.size() / len(f), "p_home": g.home.mean()}).round(3).T.to_string())
    x = np.column_stack([np.ones(len(t)), t["diff"].clip(-5, 5)])
    w = _newton(x, t.home.to_numpy(float))
    print("logistic P(home) = sigmoid(a + b * diff):", w.round(4).tolist())


DEAD_TAUS = (-1.0, -0.5, 0.0, 0.5, 1.0)


def dead_features(h):
    """Per frame: [1, unseen, unseen ln(1+run), ln(1+pace), seen ln(1+speed), seen off-pitch, seen slow run]."""
    unseen = h.nearest_team == -1
    run_len = np.zeros(h.n)
    for a, b in zip(*_runs(unseen)):
        run_len[a:b] = b - a
    g = h.geometry
    speed = np.nan_to_num(g.speed_mps.astype(np.float64), nan=0.0)
    slow = np.zeros(h.n)
    for a, b in zip(*_runs(~unseen & (speed < 1.0))):
        if b - a >= 50:
            slow[a:b] = 1.0
    pace = h.pace_mps.astype(np.float64)
    pace = np.where(np.isfinite(pace), pace, 1.2)
    seen = (~unseen).astype(float)
    return np.column_stack([np.ones(h.n), unseen, unseen * np.log1p(run_len), np.log1p(pace),
                            seen * np.log1p(speed), seen * (np.nan_to_num(g.outside_m, nan=0.0) > 0.5), seen * slow])


def fit_dead_logit():
    from possession import pff
    games, xs, ys = [], [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        h = challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id)
        keep = np.arange(h.n) >= h.id.kickoff
        xs.append(dead_features(h)[keep])
        ys.append((c.labels[keep] == D).astype(float))
    x, y = np.concatenate(xs), np.concatenate(ys)
    w = _newton(x, y)
    p = np.clip(1 / (1 + np.exp(-x @ w)), 1e-9, 1 - 1e-9)
    print(f"dead logit on {len(y)} frames: weights {np.round(w, 4).tolist()}, P(dead) {y.mean():.3f}, "
          f"log loss {-np.mean(y * np.log(p) + (1 - y) * np.log1p(-p)):.4f}", flush=True)
    return w


def flagged_half(h, mask):
    """A copy of h whose token (and ball geometry) is missing exactly where mask is set, for the dead finder."""
    from possession.half import BallGeometry, Half
    tok = np.where(mask, -1, np.where(h.nearest_team == -1, 0, h.nearest_team)).astype(np.int8)
    g = h.geometry
    fill = lambda a: np.where(mask, np.nan, np.nan_to_num(a, nan=0.0)).astype(np.float32)
    geo = BallGeometry(fill(g.margin_m), fill(g.nearest_m), fill(g.outside_m), fill(g.speed_mps))
    return Half(h.id, tok, geo, pace_mps=h.pace_mps)


def deadlogit_grid(params, out, rhos, items):
    from possession.decoder import _lag_handovers
    w = fit_dead_logit()
    base, s50, rows = Decoder.load(params), bench.Smoother(50), []
    chain = base.replace(dead_min_run=0, dead_trim=0, dead_close=0, dead_outside_m=0.0, dead_still_mps=0.0,
                         dead_still_frames=0, dead_pace_still_mps=0.0, handover_lag=0)
    plain = dataclasses.replace(base.params, dead_outside_m=0.0, dead_still_mps=0.0, dead_still_frames=0,
                                dead_pace_still_mps=0.0)
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        chained = [chain.decode(h).codes for h in case.halves]
        logits = [dead_features(h) @ w for h in case.halves]
        variants = {"base": [base.decode(h).codes for h in case.halves]}
        for tau in DEAD_TAUS:
            variants[f"tau={tau}"] = [_lag_handovers(_missing_run_dead(c, flagged_half(h, z > tau), plain), base.params.handover_lag)
                                      for c, h, z in zip(chained, case.halves, logits)]
        for name, codes in variants.items():
            f1, n = score.spell_f1(case.layout, case.gt, codes, runs)
            rows.append({"group": group, "world": world, "variant": name, "spell_f1": f1, "floor": floor,
                         "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out)


def lag_grid(params, out, rhos, items):
    model, s50, rows = Decoder.load(params), bench.Smoother(50), []
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        codes = [model.decode(h).codes for h in case.halves]
        for lag in LAGS:
            f1, n = score.spell_f1(case.layout, case.gt, [lag_handovers(c, lag) for c in codes], runs)
            rows.append({"group": group, "world": world, "lag": lag, "spell_f1": f1, "floor": floor,
                         "margin": f1 - floor, "n_pred": n})
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


def pick(synth_csv, pff_csv, base, prefer):
    sm = pd.read_csv(synth_csv).groupby(["group", "variant"]).margin.mean().unstack("group")
    pm = pd.read_csv(pff_csv).groupby(["group", "variant"]).margin.mean().unstack("group")
    slack = sm.sub(sm.loc[base] - VETO_SLACK, axis=1)
    t = pd.DataFrame({"synth_min": sm.min(axis=1), "pff_a_min": pm.min(axis=1), "pff_m0_A": pm.iloc[:, 0],
                      "pff_m2_A": pm.iloc[:, 1], "worst_group": slack.idxmin(axis=1), "veto_slack": slack.min(axis=1)})
    t["passes"] = t.veto_slack >= 0
    print(t.sort_values("pff_a_min", ascending=False).round(4).to_string())
    ok = t[t.passes]
    tied = ok[ok.pff_a_min >= ok.pff_a_min.max() - VETO_SLACK]
    order = [base] + [v for v in prefer if v != base]
    rank = {v: i for i, v in enumerate(order)}
    chosen = sorted(tied.index, key=lambda v: (rank.get(v, len(order)), -tied.pff_a_min[v]))[0]
    print(f"\n{int(t.passes.sum())} of {len(t)} pass the veto; tied within {VETO_SLACK}: {sorted(tied.index)}")
    print("SELECTED", chosen)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("probe", choices=("oracle", "geometry", "pff-geometry", "barath-geometry", "close", "deadrule", "chain", "confirm", "select", "edges", "logit", "speed", "spells", "lag", "snap", "chain5", "speedlogit", "masked", "still", "stillgrid", "dead6", "motion", "pacegrid", "push", "lag7", "deadlogit", "pick", "combo"))
    ap.add_argument("params", nargs="*")
    ap.add_argument("--prefer", nargs="+", default=[], help="pick: the registered tie order after the base")
    ap.add_argument("--out", help="deadrule: where to write the full grid table (CSV)")
    ap.add_argument("--dead-bias", type=float, nargs="+", default=[2.6], help="deadrule: generator dead_bias worlds")
    ap.add_argument("--rule", nargs="+", default=SEARCH + NATIVE, help="deadrule: [source:]rule[:mode] items")
    a = ap.parse_args()
    one = a.params[0] if a.params else None
    {"oracle": lambda: oracle(one, a.dead_bias, a.rule), "geometry": geometry, "pff-geometry": pff_geometry, "barath-geometry": barath_geometry,
     "close": lambda: close(one), "deadrule": lambda: deadrule(one, a.out, a.dead_bias, a.rule),
     "chain": lambda: chain_grid(one), "confirm": lambda: confirm(one), "select": lambda: select(a.params),
     "edges": lambda: edges_grid(one, a.out, a.dead_bias, a.rule),
     "logit": lambda: logit_grid(one, a.out, a.dead_bias, a.rule), "speed": speed_probe,
     "spells": lambda: spells_probe(one, a.dead_bias, a.rule),
     "lag": lambda: lag_grid(one, a.out, a.dead_bias, a.rule),
     "snap": lambda: snap_grid(one, a.out, a.dead_bias, a.rule),
     "chain5": lambda: chain5_grid(one, a.out, a.dead_bias, a.rule),
     "speedlogit": lambda: speedlogit_grid(one, a.out, a.dead_bias, a.rule),
     "masked": lambda: masked_grid(one, a.out, a.dead_bias, a.rule), "still": still_probe,
     "stillgrid": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, STILL_GRID),
     "dead6": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, DEAD6_GRID), "motion": motion_probe,
     "pacegrid": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, PACE_GRID), "push": push_probe,
     "lag7": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, LAG7_GRID),
     "deadlogit": lambda: deadlogit_grid(one, a.out, a.dead_bias, a.rule),
     "pick": lambda: pick(*a.params, a.prefer),
     "combo": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, COMBO_GRID)}[a.probe]()
