"""E89: learned frame evidence for the possession decoder, numpy only. Run from the repo root:

    PYTHONPATH=. python experiments/hillclimb-2026-10-24/learned.py <stage> [args]

selftest             the gradient-boosted trees on synthetic data: a known function recovered, two fits byte-identical
rows --out NPZ [--gaps renewal|transplant]
                     E89's training rows (features, targets, weights, game folds) from the dev worlds, no BAR-ATH;
                     transplant swaps the renewal worlds for label-blind ones (E89d)
fit ROWS --fold F --out NPZ
                     both models (R: token reliability, Dm: dead ball) on the rows outside fold F (F = all: every row)
fitsw ROWS --fold F --out NPZ
                     E90's Sw (a change of team within 2 frames of an alive frame) on the rows outside fold F
e90check M ALL       E90's decode with a constant cost against Decoder.decode at that switch_penalty, on a few halves
stagea M0 M1         OOF frame accuracy on native PFF-A m0, argmax of the two models, beside tier0_v20's codes
stageb M0 M1 ALL --out CSV [--arms b|c|e90 [--sw SW0 SW1]]
                     the registered grid through the chain: native PFF-A (OOF) and the synthetic veto worlds; arms b
                     decode with every rule off (E89b), arms c with tier0_v20's team rules on (E89c), arms e90 with
                     Sw's per-block switch costs (E90, ranked against E89b's t0.3_s3)
transplant M0 M1 --out CSV [--gaps transplant|bridged]
                     information only: every E89b and E89c arm against tier0_v20 on label-blind transplant worlds,
                     or on native PFF-A with short gaps bridged as BAR-ATH's tracker bridges them
cohort M0 M1 --out CSV --arm NAME [--arm NAME ...]
                     OOF per-game spellF1 of tier0_v20 and each arm on Codex's source cohort (Metrica g3, the last four
                     IDSSE games), renewal dead_bias 2.6, seeds 0 and 15 to 24
stagec ALL ARM [--sw SWALL --out CSV]
                     one PFF-B read of the all-source fit at ARM (a stage B model name such as t0.1_s1), paired
                     against tier0_v20 and, for an E90 arm, against E89b's t0.3_s3

Two models from one learner. R gives P(token team = labelled team) on seen alive frames from features measured
relative to the token's team, so it is the same for either team. Dm gives P(labelled D) on every graded frame from
team-free features, one of them tier0_v20's own D mask. The emission adds Dm's log-odds over its training prior to D
against both teams, and R's team split on seen frames, then tier0_v20's chain decodes with every rule off.
E90 adds a third model, Sw, whose hazard of a change of team prices each block's change in the penalized path.
"""
import argparse
import dataclasses
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from possession import bench, score  # noqa: E402
from possession.decoder import Decoder  # noqa: E402
from possession.half import AWAY, HOME, NO_TEAM, A, D, H  # noqa: E402

V20 = "params/tier0_v20.json"
TREES, RATE, DEPTH, BINS, RIDGE, MIN_LEAF = 200, 0.1, 6, 64, 1.0, 100
TRAIN_ITEMS = ("pff:m0:native", "pff:m0", "m0", "idsse:m0")
TRANSPLANT_ITEMS = ("pff:m0:native", "pff:m0:transplant", "m0:transplant", "idsse:m0:transplant")
STEP = {"pff": 10, "metrica": 4, "idsse": 5}
SYNTH = ("m0", "h1p3", "h3p3", "idsse:m0", "idsse:m2")
GRID = [(t, s) for t in (0.03, 0.1, 0.3) for s in (0.0, 1.0, 3.0)]
E90_GRID = [(t, k) for t in (0.1, 0.3) for k in (0.4, 0.8, 1.6)]
E89B = "t0.3_s3"
CAP = 750.0


# ---- gradient-boosted trees ---------------------------------------------------------------------------------

def _edges(col, bins):
    """At most BINS - 2 increasing cut points: unique quantiles of COL's finite values."""
    v = col[np.isfinite(col)]
    if not len(v):
        return np.zeros(0)
    return np.unique(np.quantile(v.astype(np.float64), np.linspace(0, 1, bins - 1)[1:-1]))


def _bin(x, edges):
    """uint8 [F, n]: 0 for NaN, else 1 + the number of cut points at or below the value (inf goes to the top)."""
    out = np.zeros((x.shape[1], x.shape[0]), np.uint8)
    for j, e in enumerate(edges):
        col = x[:, j]
        ok = ~np.isnan(col)
        out[j, ok] = np.searchsorted(e, col[ok], side="right") + 1
    return out


def _walk(feat, thr, value, xb, depth):
    """One tree's leaf values for binned rows XB [F, n]."""
    n = xb.shape[1]
    cols, pos = np.arange(n), np.zeros(n, np.int64)
    for _ in range(depth):
        fp = feat[pos]
        leaf = fp < 0
        if leaf.all():
            break
        go = xb[np.maximum(fp, 0), cols] > thr[pos]
        pos = np.where(leaf, pos, 2 * pos + 1 + go)
    return value[pos]


@dataclasses.dataclass(frozen=True)
class Trees:
    """A fitted binary logistic model: per-feature cut points and heap-ordered trees (child of node i at 2i + 1 and
    2i + 2; feat -1 marks a leaf, a row goes right when its bin exceeds thr)."""
    edges: tuple
    feat: np.ndarray
    thr: np.ndarray
    value: np.ndarray
    base: float
    depth: int

    def raw(self, x):
        xb = _bin(np.asarray(x, np.float64), self.edges)
        out = np.full(xb.shape[1], self.base)
        for f, t, v in zip(self.feat, self.thr, self.value):
            out += _walk(f, t, v, xb, self.depth)
        return out

    def prob(self, x):
        return 1 / (1 + np.exp(-self.raw(x)))

    def save(self, prefix):
        return {f"{prefix}_edges": np.concatenate([np.r_[len(e), e] for e in self.edges]),
                f"{prefix}_feat": self.feat, f"{prefix}_thr": self.thr, f"{prefix}_value": self.value,
                f"{prefix}_base": np.array([self.base, self.depth])}

    @classmethod
    def load(cls, z, prefix):
        flat, edges, k = z[f"{prefix}_edges"], [], 0
        while k < len(flat):
            m = int(flat[k])
            edges.append(flat[k + 1:k + 1 + m])
            k += 1 + m
        base, depth = z[f"{prefix}_base"]
        return cls(tuple(edges), z[f"{prefix}_feat"], z[f"{prefix}_thr"], z[f"{prefix}_value"], float(base), int(depth))


def fit_trees(x, y, w, trees=TREES, rate=RATE, depth=DEPTH, bins=BINS, ridge=RIDGE, min_leaf=MIN_LEAF, log=None):
    """Level-wise histogram boosting of the weighted logistic loss. Deterministic: bincount sums in row order and
    ties go to the lowest feature, then the lowest bin."""
    x, y, w = np.asarray(x, np.float64), np.asarray(y, np.float64), np.asarray(w, np.float64)
    edges = tuple(_edges(x[:, j], bins) for j in range(x.shape[1]))
    xb, (n_feat, n) = _bin(x, edges), x.shape[::-1]
    base = float(np.log((w * y).sum() / (w * (1 - y)).sum()))
    raw, nodes = np.full(n, base), 2 ** (depth + 1) - 1
    feat = np.full((trees, nodes), -1, np.int16)
    thr, value = np.zeros((trees, nodes), np.uint8), np.zeros((trees, nodes))
    for t in range(trees):
        p = 1 / (1 + np.exp(-raw))
        g, h = w * (p - y), w * p * (1 - p)
        node, active = np.zeros(n, np.int64), np.ones(n, bool)
        for level in range(depth + 1):
            first, k = 2 ** level - 1, 2 ** level
            idx = np.flatnonzero(active)
            if not len(idx):
                break
            loc, gi, hi = node[idx] - first, g[idx], h[idx]
            gn, hn = np.bincount(loc, gi, k), np.bincount(loc, hi, k)
            cn = np.bincount(loc, minlength=k)
            heap = first + np.arange(k)
            if level == depth:
                leaf = cn > 0
                value[t, heap[leaf]] = -rate * gn[leaf] / (hn[leaf] + ridge)
                break
            parent = gn ** 2 / (hn + ridge)
            best, bf, bb = np.zeros(k), np.full(k, -1), np.zeros(k, np.int64)
            for j in range(n_feat):
                key = loc * bins + xb[j, idx]
                hg = np.bincount(key, gi, k * bins).reshape(k, bins).cumsum(axis=1)[:, :-1]
                hh = np.bincount(key, hi, k * bins).reshape(k, bins).cumsum(axis=1)[:, :-1]
                hc = np.bincount(key, minlength=k * bins).reshape(k, bins).cumsum(axis=1)[:, :-1]
                gain = hg ** 2 / (hh + ridge) + (gn[:, None] - hg) ** 2 / (hn[:, None] - hh + ridge) - parent[:, None]
                gain[(hc < min_leaf) | (cn[:, None] - hc < min_leaf)] = -np.inf
                b = gain.argmax(axis=1)
                gb = gain[np.arange(k), b]
                better = gb > best + 1e-12
                best[better], bf[better], bb[better] = gb[better], j, b[better]
            split = bf >= 0
            feat[t, heap[split]], thr[t, heap[split]] = bf[split], bb[split]
            leaf = ~split & (cn > 0)
            value[t, heap[leaf]] = -rate * gn[leaf] / (hn[leaf] + ridge)
            moving = split[loc]
            rows = idx[moving]
            go = xb[bf[loc[moving]], rows] > bb[loc[moving]]
            node[rows] = 2 * node[rows] + 1 + go
            active[idx[~moving]] = False
        raw += _walk(feat[t], thr[t], value[t], xb, depth)
        if log and (t + 1) % 50 == 0:
            p = np.clip(1 / (1 + np.exp(-raw)), 1e-12, 1 - 1e-12)
            log(f"  tree {t + 1}: weighted log loss {-(w * (y * np.log(p) + (1 - y) * np.log1p(-p))).sum() / w.sum():.5f}")
    return Trees(edges, feat, thr, value, base, depth)


def selftest():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(20000, 4))
    x[rng.random(20000) < 0.1, 2] = np.nan
    z = 1.5 * x[:, 0] - 2.0 * (x[:, 1] > 0.3) + np.where(np.isnan(x[:, 2]), 1.0, 0.0)
    y = (rng.random(20000) < 1 / (1 + np.exp(-z))).astype(float)
    w = np.ones(20000)
    a = fit_trees(x[:15000], y[:15000], w[:15000], trees=100, depth=3, min_leaf=50)
    b = fit_trees(x[:15000], y[:15000], w[:15000], trees=100, depth=3, min_leaf=50)
    same = all(np.array_equal(getattr(a, k), getattr(b, k)) for k in ("feat", "thr", "value"))
    p = a.prob(x[15000:])
    truth = 1 / (1 + np.exp(-z[15000:]))
    print(f"two fits byte-identical: {same}; held-out corr(p, true p) {np.corrcoef(p, truth)[0, 1]:.3f}; "
          f"log loss {-(y[15000:] * np.log(p) + (1 - y[15000:]) * np.log1p(-p)).mean():.4f} against the true "
          f"model's {-(y[15000:] * np.log(truth) + (1 - y[15000:]) * np.log1p(-truth)).mean():.4f}; feature 3 "
          f"(noise) splits {(a.feat == 3).sum()} of {(a.feat >= 0).sum()}")
    z2 = Trees.load(np.load(_save_tmp(a)), "m")
    print(f"save and load give identical predictions: {np.array_equal(z2.raw(x), a.raw(x))}")


def _save_tmp(model):
    import io
    buf = io.BytesIO()
    np.savez(buf, **model.save("m"))
    buf.seek(0)
    return buf


# ---- features -----------------------------------------------------------------------------------------------

def _csum(x):
    return np.concatenate(([0.0], np.cumsum(x, dtype=np.float64)))


def _past(c, w):
    t = np.arange(len(c) - 1)
    return c[t + 1] - c[np.maximum(t + 1 - w, 0)]


def _fut(c, w):
    n, t = len(c) - 1, np.arange(len(c) - 1)
    return c[np.minimum(t + w, n)] - c[t]


def _last(flag):
    return np.maximum.accumulate(np.where(flag, np.arange(len(flag)), -1))


def _next(flag):
    n = len(flag)
    return np.minimum.accumulate(np.where(flag, np.arange(n), n)[::-1])[::-1]


def _at(x, i):
    """X at index I, NaN where I is out of range."""
    ok = (i >= 0) & (i < len(x))
    out = np.full(len(i), np.nan)
    out[ok] = x[i[ok]]
    return out


def _share(num, den):
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / np.maximum(den, 1), np.nan)


def _geo(h, name):
    v = getattr(h.geometry, name)
    return np.full(h.n, np.nan) if v is None else v.astype(np.float64)


def _opt(v, n):
    return np.full(n, np.nan) if v is None else v.astype(np.float64)


REL_FEATURES = ("near", "margin", "speed", "rel", "goal", "outside", "line", "press", "push", "shape", "pace",
                "same5p", "same5f", "same25p", "same25f", "same75p", "same75f", "close25p", "close25f", "close75p",
                "close75f", "since_diff", "until_diff", "since_gap", "until_gap", "seen25")
DEAD_FEATURES = ("seen", "seen5p", "seen5f", "seen25p", "seen25f", "seen75p", "seen75f", "seen250p", "seen250f",
                 "seen750p", "seen750f", "since_seen", "until_seen", "gap", "out_last", "out_next", "line_last",
                 "line_next", "speed_last", "speed_next", "return", "pace", "pace25p", "pace25f", "pace125p",
                 "pace125f", "pace375p", "pace375f", "bspeed25p", "bspeed25f", "bspeed125p", "bspeed125f", "near",
                 "margin", "outside", "line", "press_abs", "push_abs", "v20", "v20_25", "v20_125")


def features(h, v20_codes):
    """(REL [n, len(REL_FEATURES)], DEAD [n, len(DEAD_FEATURES)]) float64 for every frame of half H, label-free.
    REL is measured relative to the token's team and is NaN-free only where the ball is seen."""
    n, tok = h.n, h.nearest_team
    seen = tok != NO_TEAM
    near, margin = _geo(h, "nearest_m"), np.minimum(_geo(h, "margin_m"), 30.0)
    speed, outside, line = _geo(h, "speed_mps"), _geo(h, "outside_m"), _geo(h, "line_m")
    sign = np.where(tok == HOME, 1.0, np.where(tok == AWAY, -1.0, np.nan))
    press, push, shape = _opt(h.press_mps, n), _opt(h.push_mps, n), _opt(h.shape_lo, n)
    pace = _opt(h.pace_mps, n)
    home, away = (tok == HOME).astype(float), (tok == AWAY).astype(float)
    with np.errstate(invalid="ignore"):
        close = near < 1.5
    ch, ca, cs = _csum(home), _csum(away), _csum(seen.astype(float))
    cch, cca = _csum(home * close), _csum(away * close)
    rel = {"near": near, "margin": margin, "speed": speed, "rel": _geo(h, "rel_mps"), "goal": _geo(h, "goal_mps"),
           "outside": outside, "line": line, "press": press * sign, "push": push * sign, "shape": shape * sign,
           "pace": pace}
    for w in (5, 25, 75):
        for side, f in (("p", _past), ("f", _fut)):
            hw, aw = f(ch, w), f(ca, w)
            rel[f"same{w}{side}"] = _share(np.where(tok == HOME, hw, aw), hw + aw)
    for w in (25, 75):
        for side, f in (("p", _past), ("f", _fut)):
            hw, aw = f(cch, w), f(cca, w)
            rel[f"close{w}{side}"] = _share(np.where(tok == HOME, hw, aw), hw + aw)
    t = np.arange(n)
    other_last = np.where(tok == HOME, _last(tok == AWAY), _last(tok == HOME))
    other_next = np.where(tok == HOME, _next(tok == AWAY), _next(tok == HOME))
    rel["since_diff"] = np.where(other_last >= 0, np.minimum(t - other_last, CAP), CAP)
    rel["until_diff"] = np.minimum(other_next - t, CAP)
    rel["since_gap"] = np.where(_last(~seen) >= 0, np.minimum(t - _last(~seen), CAP), CAP)
    rel["until_gap"] = np.minimum(_next(~seen) - t, CAP)
    rel["seen25"] = (_past(cs, 25) + _fut(cs, 25)) / 50
    r = np.column_stack([rel[k] for k in REL_FEATURES])
    r[~seen] = np.nan

    last, nxt = _last(seen), _next(seen)
    dead = {"seen": seen.astype(float)}
    for w in (5, 25, 75, 250, 750):
        dead[f"seen{w}p"], dead[f"seen{w}f"] = _past(cs, w) / w, _fut(cs, w) / w
    dead["since_seen"] = np.where(last >= 0, np.minimum(t - last, 4 * CAP), 4 * CAP)
    dead["until_seen"] = np.minimum(nxt - t, 4 * CAP)
    dead["gap"] = np.minimum(dead["since_seen"] + dead["until_seen"], 4 * CAP)
    for name, x in (("out", outside), ("line", line), ("speed", speed)):
        dead[f"{name}_last"], dead[f"{name}_next"] = _at(x, last), _at(x, nxt)
    dead["return"] = _opt(h.return_m, n)
    ok = np.isfinite(pace)
    cp, cn = _csum(np.where(ok, pace, 0.0)), _csum(ok.astype(float))
    dead["pace"] = pace
    for w in (25, 125, 375):
        dead[f"pace{w}p"], dead[f"pace{w}f"] = _share(_past(cp, w), _past(cn, w)), _share(_fut(cp, w), _fut(cn, w))
    ok = np.isfinite(speed)
    cv, cvn = _csum(np.where(ok, speed, 0.0)), _csum(ok.astype(float))
    for w in (25, 125):
        dead[f"bspeed{w}p"], dead[f"bspeed{w}f"] = _share(_past(cv, w), _past(cvn, w)), _share(_fut(cv, w), _fut(cvn, w))
    dead.update(near=near, margin=margin, outside=outside, line=line, press_abs=np.abs(press), push_abs=np.abs(push))
    vd = (v20_codes == D).astype(float)
    cd = _csum(vd)
    dead["v20"] = vd
    for w in (25, 125):
        dead[f"v20_{w}"] = (_past(cd, w) + _fut(cd, w)) / (2 * w)
    return r, np.column_stack([dead[k] for k in DEAD_FEATURES])


# ---- data -----------------------------------------------------------------------------------------------------

def _source(world):
    return "pff" if world.startswith("pff") else "idsse" if world.startswith("idsse") else "metrica"


def _game_cases(world, cases, part="A"):
    """WORLD's per-game cases plus a "dev_pooled" case over them, as bench builds a world. PFF keeps its A games
    (every other game, as probes.native_a splits them), or with PART "B" the others."""
    if _source(world) != "pff":
        return list(cases)
    pooled = bench.pooled(cases)
    order = list(dict.fromkeys(h.id.match for h in pooled.halves))
    keep = set(order[0::2] if part == "A" else order[1::2])
    labels = pooled.layout.cut(pooled.gt)
    idx = [i for i, h in enumerate(pooled.halves) if h.id.match in keep]
    return bench._dev_cases([labels[i] for i in idx], [pooled.halves[i] for i in idx])


def _games(cases):
    return [c for c in cases if c.name != "dev_pooled"]


def folds(worlds):
    """match -> 0 or 1, alternating by game within each source in the order the worlds list them."""
    out, by_source = {}, {}
    for world, cases in worlds.items():
        for c in _games(_game_cases(world, cases)):
            m = c.halves[0].id.match
            lst = by_source.setdefault(_source(world), [])
            if m not in lst:
                lst.append(m)
    for lst in by_source.values():
        out.update({m: i % 2 for i, m in enumerate(sorted(lst))})
    return out


def _v20():
    from probes import dev_model
    return dev_model(Decoder.load(V20))


def _switch_target(lab, k0):
    """1 on alive frames within 2 frames of a change of team: an alive frame after kickoff whose team differs from
    the team of the last alive frame before it, across any D between them."""
    alive = np.flatnonzero((lab == H) | (lab == A))
    alive = alive[alive >= k0]
    change = np.zeros(len(lab))
    change[alive[1:][lab[alive[1:]] != lab[alive[:-1]]]] = 1.0
    near = np.convolve(change, np.ones(5), mode="same") > 0
    out = np.zeros(len(lab), np.int8)
    out[alive] = near[alive]
    return out


def rows(out, gaps="renewal"):
    """E89's training rows from TRAIN_ITEMS at dead_bias 2.6, seed 0 (or TRANSPLANT_ITEMS): every STEP-th graded
    frame after kickoff."""
    items = {"renewal": TRAIN_ITEMS, "transplant": TRANSPLANT_ITEMS}[gaps]
    worlds = bench.dev_worlds(list(items), (2.6,), seeds=(0,))
    fold, v20, parts = folds(worlds), _v20(), []
    for world, cases in worlds.items():
        src = _source(world)
        for c in _games(_game_cases(world, cases)):
            for h, lab in zip(c.halves, c.layout.cut(c.gt)):
                r, d = features(h, v20.decode(h).codes)
                k0 = h.id.kickoff
                pick = np.arange(k0, h.n, STEP[src])
                pick = pick[lab[pick] != 3]
                parts.append(dict(r=r[pick], d=d[pick], lab=lab[pick], tok=h.nearest_team[pick],
                                  sw=_switch_target(lab, k0)[pick],
                                  src=np.full(len(pick), ("pff", "metrica", "idsse").index(src), np.int8),
                                  fold=np.full(len(pick), fold[h.id.match], np.int8)))
        print(world, sum(len(p["lab"]) for p in parts), flush=True)
    np.savez(out, **{k: np.concatenate([p[k] for p in parts]) for k in parts[0]})


def _weights(src, mask):
    """Equal total weight per source among the rows in MASK, mean 1."""
    w = np.zeros(len(src))
    for s in np.unique(src[mask]):
        m = mask & (src == s)
        w[m] = 1.0 / m.sum()
    return w * mask.sum() / w.sum()


def fit(rows_path, fold, out):
    z = np.load(rows_path)
    train = np.ones(len(z["lab"]), bool) if fold == "all" else z["fold"] != int(fold)
    alive = train & (z["lab"] != D) & (z["tok"] != NO_TEAM)
    t0 = time.time()
    print(f"R on {alive.sum()} seen alive rows", flush=True)
    rel = fit_trees(z["r"][alive], (z["tok"][alive] == z["lab"][alive]).astype(float),
                    _weights(z["src"], alive)[alive], log=print)
    print(f"Dm on {train.sum()} rows ({time.time() - t0:.0f} s so far)", flush=True)
    w = _weights(z["src"], train)
    y = (z["lab"][train] == D).astype(float)
    dead = fit_trees(z["d"][train], y, w[train], log=print)
    prior = float((w[train] * y).sum() / w[train].sum())
    np.savez(out, **rel.save("rel"), **dead.save("dead"), prior=np.array([prior]))
    print(f"saved {out}: D prior {prior:.4f}, {time.time() - t0:.0f} s", flush=True)


def fit_switch(rows_path, fold, out):
    """E90's Sw on the alive rows outside FOLD, from R's and Dm's features side by side."""
    z = np.load(rows_path)
    train = np.ones(len(z["lab"]), bool) if fold == "all" else z["fold"] != int(fold)
    alive = train & (z["lab"] != D)
    t0 = time.time()
    print(f"Sw on {alive.sum()} alive rows, {z['sw'][alive].mean():.4f} near a change", flush=True)
    sw = fit_trees(np.hstack([z["r"], z["d"]])[alive], z["sw"][alive].astype(float), _weights(z["src"], alive)[alive],
                   log=print)
    np.savez(out, **sw.save("sw"))
    print(f"saved {out}: {time.time() - t0:.0f} s", flush=True)


# ---- emission and decoding ------------------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Models:
    rel: Trees
    dead: Trees
    prior: float

    @classmethod
    def load(cls, path):
        z = np.load(path)
        return cls(Trees.load(z, "rel"), Trees.load(z, "dead"), float(z["prior"][0]))

    def parts(self, h, v20_codes):
        """(q, p_dead) per frame: q = P(token team = true team) where the ball is seen (NaN elsewhere)."""
        return self.split(h, *features(h, v20_codes))

    def split(self, h, r, d):
        seen = h.nearest_team != NO_TEAM
        q = np.full(h.n, np.nan)
        if seen.any():
            q[seen] = self.rel.prob(r[seen])
        return q, self.dead.prob(d)


def loglik(h, q, p_dead, prior):
    """Scaled likelihoods [n, 3]: D gets log p_dead - log prior, each team log(1 - p_dead) - log(1 - prior) plus
    the log of its share of the alive mass (q or 1 - q by the token on seen frames, 1/2 elsewhere) over 1/2."""
    tok = h.nearest_team
    pd_ = np.clip(p_dead, 1e-4, 1 - 1e-4)
    qq = np.clip(np.where(np.isnan(q), 0.5, q), 1e-3, 1 - 1e-3)
    ph = np.where(tok == HOME, qq, np.where(tok == AWAY, 1 - qq, 0.5))
    alive = np.log1p(-pd_) - np.log1p(-prior)
    out = np.empty((h.n, 3))
    out[:, H] = alive + np.log(ph) - np.log(0.5)
    out[:, A] = alive + np.log1p(-ph) - np.log(0.5)
    out[:, D] = np.log(pd_) - np.log(prior)
    return out.astype(np.float32)


@dataclasses.dataclass(frozen=True)
class Fixed:
    ev: np.ndarray
    needs_geometry: bool = False

    def loglik(self, half):
        return self.ev


def chain_params(temper, switch):
    from probes import _rules_off
    return _rules_off(Decoder.load(V20)).params.__class__(
        **{**dataclasses.asdict(_rules_off(Decoder.load(V20)).params), "temper": temper, "switch_penalty": switch})


TEAM_RULES = ("handover_lag", "spell_merge_frames", "spell_merge_tails", "spell_push_mps", "spell_push_frames",
              "spell_push_between", "spell_push_unseen", "spell_flip_p", "spell_flip_frames", "spell_flip_seen",
              "spell_logit", "spell_flip_adjacent")


def team_params(temper, switch):
    """chain_params with tier0_v20's team rules back on; every D rule stays off."""
    v20 = Decoder.load(V20).params
    return dataclasses.replace(chain_params(temper, switch), **{k: getattr(v20, k) for k in TEAM_RULES})


def arm_params(name):
    """Params of a grid arm named t<temper>_s<switch> (E89b) or team_t<temper>_s<switch> (E89c), or for
    sw_t<temper>_k<scale> (E90) the pair (params, scale)."""
    if name.startswith("sw_"):
        t, k = (float(v[1:]) for v in name.removeprefix("sw_").split("_"))
        return chain_params(t, 0.0), k
    t, s = (float(v[1:]) for v in name.removeprefix("team_").split("_"))
    return (team_params if name.startswith("team_") else chain_params)(t, s)


def arms(kind):
    if kind == "e90":
        return {name: arm_params(name) for name in (E89B, *(f"sw_t{t:g}_k{k:g}" for t, k in E90_GRID))}
    prefix = {"b": "", "c": "team_"}[kind]
    return {name: arm_params(name) for name in (f"{prefix}t{t:g}_s{s:g}" for t, s in GRID)}


def decode(h, ev, params):
    return Decoder(emission=Fixed(ev), params=params).decode(h).codes


def switch_costs(h, hz, stride, k):
    """E90's cost of a change of team into each block from kickoff: K * log((1 - h_b) / h_b), floored at 0, with h_b
    the mean of Sw's hazard HZ over the block's frames."""
    m = h.n - h.id.kickoff
    starts = np.arange(0, m, stride)
    hb = np.add.reduceat(hz[h.id.kickoff:].astype(np.float64), starts) / np.diff(np.append(starts, m))
    hb = np.clip(hb, 1e-6, 1 - 1e-6)
    return np.maximum(k * np.log((1 - hb) / hb), 0.0).tolist()


def decode_costs(h, ev, params, lam):
    """Decoder.decode with every rule off and the penalized path's change costs LAM (one per block) in place of
    switch_penalty."""
    from possession.decoder import _chain, _forward_backward, _penalized_path
    p, k0 = params, h.id.kickoff
    e = ev[k0:].astype(np.float64)
    m = e.shape[0]
    g = _forward_backward(p.temper * np.add.reduceat(e, np.arange(0, m, p.stride), axis=0), _chain(p))
    codes = np.full(h.n, D, dtype=np.int8)
    codes[k0:] = np.repeat(_penalized_path(g, lam), p.stride)[:m]
    return codes


def decode_arm(e, spec):
    """Codes of one arm on one _evidence entry E = (half, labels, log-likelihoods, v20 codes, Sw hazard)."""
    h, _, x, _, hz = e
    if isinstance(spec, tuple):
        return decode_costs(h, x, spec[0], switch_costs(h, hz, spec[0].stride, spec[1]))
    return decode(h, x, spec)


# ---- stages ---------------------------------------------------------------------------------------------------

def _oof_models(m0, m1):
    return {0: Models.load(m0), 1: Models.load(m1)}


def _native_pff():
    """(world, per-game A cases) for native PFF m0 and m2; both share the same halves."""
    worlds = bench.dev_worlds(["pff:m0:native", "pff:m2:native"], (2.6,), seeds=(0,))
    return {w: _game_cases(w, c) for w, c in sorted(worlds.items(), key=lambda kv: "_m2_" in kv[0])}


def stagea(m0, m1):
    worlds = bench.dev_worlds(list(TRAIN_ITEMS), (2.6,), seeds=(0,))
    fold, models, v20 = folds(worlds), _oof_models(m0, m1), _v20()
    del worlds
    native = _native_pff()
    cases = _games(next(iter(native.values())))
    hit = {"E89 argmax": 0, "tier0_v20": 0}
    n = 0
    for c in cases:
        for h, lab in zip(c.halves, c.layout.cut(c.gt)):
            vc = v20.decode(h).codes
            q, pd_ = models[fold[h.id.match]].parts(h, vc)
            post = np.exp(loglik(h, q, pd_, models[fold[h.id.match]].prior).astype(np.float64))
            pred = post.argmax(axis=1)
            g = lab != 3
            g[:h.id.kickoff] = False
            n += g.sum()
            hit["E89 argmax"] += (pred[g] == lab[g]).sum()
            hit["tier0_v20"] += (vc[g] == lab[g]).sum()
        print(c.name, flush=True)
    for k, v in hit.items():
        print(f"{k}: frame accuracy {v / n:.4f} on {n} graded frames of native PFF-A m0")
    print(f"stage A mark (+0.02): {'pass' if (hit['E89 argmax'] - hit['tier0_v20']) / n >= 0.02 else 'fail'}")


def _evidence(cases, models_for, v20, memo=None, sw_for=None):
    """Per half of CASES in order: (half, labels, E89 log-likelihoods, v20 codes, Sw hazard or None). MEMO, keyed by
    (match, half), reuses the model outputs of halves whose inputs are shared, such as native m0 and m2."""
    out, memo = [], {} if memo is None else memo
    for c in cases:
        for h, lab in zip(c.halves, c.layout.cut(c.gt)):
            key = (h.id.match, h.id.half)
            if key not in memo:
                vc = v20.decode(h).codes
                m = models_for(h)
                r, d = features(h, vc)
                q, pd_ = m.split(h, r, d)
                hz = sw_for(h).prob(np.hstack([r, d])) if sw_for else None
                memo[key] = (loglik(h, q, pd_, m.prior), vc, hz)
            out.append((h, lab, *memo[key]))
    return out


def _score_world(world, cases, ev, arms, rows_, per_game):
    """Pooled and per-game spellF1 of v20 and each arm on CASES (a world list with its pooled case); EV follows the
    halves of _games(CASES) in order."""
    pooled = bench.pooled(cases)
    runs = score.valid_runs(pooled.gt)
    by_arm = {"tier0_v20": [e[3] for e in ev]}
    for arm, spec in arms.items():
        by_arm[arm] = [decode_arm(e, spec) for e in ev]
    keys = [(e[0].id.match, e[0].id.half) for e in ev]
    for arm, codes in by_arm.items():
        by_key = dict(zip(keys, codes))
        f1, n_pred = score.spell_f1(pooled.layout, pooled.gt, [by_key[(h.id.match, h.id.half)] for h in pooled.halves],
                                    runs)
        rows_.append({"world": world, "model": arm, "spell_f1": f1, "n_pred": n_pred})
        for c in _games(cases):
            gc = [by_key[(h.id.match, h.id.half)] for h in c.halves]
            per_game.append({"world": world, "game": c.name, "model": arm,
                             "spell_f1": score.spell_f1(c.layout, c.gt, gc, score.valid_runs(c.gt))[0]})


def _sw_models(paths):
    return {f: Trees.load(np.load(path), "sw") for f, path in enumerate(paths)}


def stageb(m0, m1, m_all, out, kind="b", sw=None):
    tw = bench.dev_worlds(list(TRAIN_ITEMS), (2.6,), seeds=(0,))
    fold, oof, v20 = folds(tw), _oof_models(m0, m1), _v20()
    del tw
    grid = arms(kind)
    swm = _sw_models(sw) if sw else None
    sw_for = (lambda h: swm[fold[h.id.match]]) if swm else None
    rows_, per_game = [], []
    memo = {}
    for world, cases in _native_pff().items():
        _score_world(world, cases, _evidence(_games(cases), lambda h: oof[fold[h.id.match]], v20, memo, sw_for), grid,
                     rows_, per_game)
        print(world, flush=True)
    del memo
    for item in SYNTH:
        for world, cases in bench.dev_worlds([item], (1.0, 2.6, 4.0), seeds=(0, 1, 2)).items():
            ev = _evidence(_games(cases), lambda h: oof[fold[h.id.match]], v20, sw_for=sw_for)
            _score_world(world, cases, ev, grid, rows_, per_game)
            print(world, flush=True)
    pd.DataFrame(rows_).to_csv(out, index=False)
    pd.DataFrame(per_game).to_csv(str(out).replace(".csv", "-games.csv"), index=False)
    pick_b(out, E89B if kind == "e90" else "tier0_v20")


def pick_b(out, ref="tier0_v20"):
    t = pd.read_csv(out)
    t["group"] = t.world.map(bench.group)
    native = t[t.world.str.startswith("pff")]
    synth = t[~t.world.str.startswith("pff")]
    base = synth[synth.model == ref].set_index("world").spell_f1
    synth = synth.assign(margin=synth.spell_f1 - synth.world.map(base))
    veto = synth.groupby(["model", "group"]).margin.mean().unstack()
    nat = native.pivot_table(index="model", columns="world", values="spell_f1")
    table = pd.DataFrame({"native_min": nat.min(axis=1), "worst_group_margin": veto.min(axis=1)})
    table["veto"] = table.worst_group_margin >= -0.003
    v = table.loc[ref, "native_min"]
    table["over_ref"] = table.native_min - v
    print(nat.round(4).to_string())
    print(veto.round(4).to_string())
    print(table.sort_values("native_min", ascending=False).round(4).to_string())
    ok = table[~table.index.isin(["tier0_v20", ref]) & table.veto]
    if len(ok) and ok.native_min.max() > v + 0.003:
        print(f"stage B pick: {ok.native_min.idxmax()} ({ok.native_min.max() - v:+.4f} over {ref})")
    else:
        print(f"stage B: no arm passes the veto and clears {ref} by more than 0.003")


INFO_ITEMS = {"transplant": ((*SYNTH, "pff:m0"), (0, 1, 2)), "bridged": (("pff:m0", "pff:m2"), (0,))}


def transplant(m0, m1, out, gaps="transplant"):
    """Every E89b and E89c arm against tier0_v20, OOF, on transplant worlds (a seeded cyclic window of BAR-ATH's real
    ball mask that carries no labelled D edge) for the five synthetic groups and PFF-A m0, seeds 0 to 2, or with
    GAPS "bridged" on native PFF-A m0 and m2 with every gap under BRIDGE_FRAMES counted as seen."""
    items, seeds = INFO_ITEMS[gaps]
    tw = bench.dev_worlds(list(TRAIN_ITEMS), (2.6,), seeds=(0,))
    fold, oof, v20 = folds(tw), _oof_models(m0, m1), _v20()
    del tw
    grid, rows_, per_game = {**arms("b"), **arms("c")}, [], []
    for item in items:
        for world, cases in bench.dev_worlds([item], (2.6,), seeds=seeds, mode=gaps).items():
            cases = _game_cases(world, cases)
            _score_world(world, cases, _evidence(_games(cases), lambda h: oof[fold[h.id.match]], v20), grid, rows_,
                         per_game)
            print(world, flush=True)
    t = pd.DataFrame(rows_)
    t.to_csv(out, index=False)
    pd.DataFrame(per_game).to_csv(str(out).replace(".csv", "-games.csv"), index=False)
    t["group"] = t.world.map(bench.group)
    base = t[t.model == "tier0_v20"].set_index("world").spell_f1
    t["margin"] = t.spell_f1 - t.world.map(base)
    print(t.pivot_table(index="model", columns="group", values="spell_f1").round(4).to_string())
    print(t.pivot_table(index="model", columns="group", values="margin").round(4).to_string())


CODEX_COHORT = ("dev_g3", "dev_J03WOY", "dev_J03WPY", "dev_J03WQQ", "dev_J03WR9")


def cohort(m0, m1, out, arm_names):
    """OOF per-game spellF1 of tier0_v20 and ARM_NAMES on the games Codex holds out of its training (Metrica g3 and
    the last four IDSSE games), at renewal dead_bias 2.6 with seeds 0 and 15 to 24, the worlds of its source gates.
    Each game is decoded by the fold model fitted without it."""
    tw = bench.dev_worlds(list(TRAIN_ITEMS), (2.6,), seeds=(0,))
    fold, oof, v20 = folds(tw), _oof_models(m0, m1), _v20()
    del tw
    grid, rows_ = {a: arm_params(a) for a in arm_names}, []
    for item in SYNTH:
        for world, cases in bench.dev_worlds([item], (2.6,), seeds=(0, *range(15, 25))).items():
            games = [c for c in _games(cases) if c.name in CODEX_COHORT]
            ev = _evidence(games, lambda h: oof[fold[h.id.match]], v20)
            k = 0
            for c in games:
                part = ev[k:k + len(c.halves)]
                k += len(c.halves)
                by_model = {"tier0_v20": [e[3] for e in part],
                            **{a: [decode_arm(e, spec) for e in part] for a, spec in grid.items()}}
                for name, codes in by_model.items():
                    rows_.append({"world": world, "game": c.name, "model": name, "fold": fold[c.halves[0].id.match],
                                  "spell_f1": score.spell_f1(c.layout, c.gt, codes, score.valid_runs(c.gt))[0]})
            print(world, flush=True)
    pd.DataFrame(rows_).to_csv(out, index=False)


def stagec(m_all, arm, sw_all=None, out=None):
    named = {"E89": arm_params(arm)} if not sw_all else {"E89": arm_params(E89B), "E90": arm_params(arm)}
    model, v20 = Models.load(m_all), _v20()
    swm = Trees.load(np.load(sw_all), "sw") if sw_all else None
    worlds = bench.dev_worlds(["pff:m0:native", "pff:m2:native"], (2.6,), seeds=(0,))
    rows_, memo = [], {}
    for world, cases in sorted(worlds.items(), key=lambda kv: "_m2_" in kv[0]):
        games = _games(_game_cases(world, cases, "B"))
        ev = _evidence(games, lambda h: model, v20, memo, (lambda h: swm) if swm else None)
        k = 0
        for c in games:
            part = ev[k:k + len(c.halves)]
            k += len(c.halves)
            by_model = {"tier0_v20": [e[3] for e in part], **{n: [decode_arm(e, spec) for e in part] for n, spec in named.items()}}
            for name, codes in by_model.items():
                pred = score._assemble_checked(c.layout, c.gt, codes)
                f1 = score.spell_f1(c.layout, c.gt, codes, score.valid_runs(c.gt))[0]
                g = c.gt != 3
                acc = float((pred[g] == c.gt[g]).mean())
                rows_.append({"world": world, "game": c.name, "model": name, "spell_f1": f1, "accuracy": acc})
        print(world, flush=True)
    t_ = pd.DataFrame(rows_)
    t_.to_csv(out or f"{Path(m_all).with_suffix('')}-pffb.csv", index=False)
    pairs = [("E89", "tier0_v20")] + ([("E90", "tier0_v20"), ("E90", "E89")] if sw_all else [])
    for world, w in t_.groupby("world"):
        p = w.pivot_table(index="game", columns="model", values="spell_f1")
        acc = w.groupby("model").accuracy.mean()
        print(f"{world}: mean-game spellF1 " + ", ".join(f"{m} {p[m].mean():.6f}" for m in p.columns) + "; accuracy "
              + ", ".join(f"{m} {acc[m]:.4f}" for m in acc.index))
        for a, b in pairs:
            d = p[a] - p[b]
            hw = 1.6955 * d.std(ddof=1) / np.sqrt(len(d))
            print(f"  {a} - {b}: paired {d.mean():+.4f} [{d.mean() - hw:+.4f}, {d.mean() + hw:+.4f}], "
                  f"{(d > 0).sum()}/{len(d)}")


def e90check(m_all):
    """decode_costs with a constant cost list equals Decoder.decode at that switch_penalty, on Metrica and IDSSE m0."""
    model, v20, n = Models.load(m_all), _v20(), 0
    for world, cases in bench.dev_worlds(["m0", "idsse:m0"], (2.6,), seeds=(0,)).items():
        for h, _, x, _, _ in _evidence(_games(cases), lambda h: model, v20):
            for t, sp in ((0.3, 3.0), (0.1, 1.0), (0.03, 0.5)):
                prm = chain_params(t, sp)
                nb = len(range(0, h.n - h.id.kickoff, prm.stride))
                assert np.array_equal(decode_costs(h, x, prm, [sp] * nb), decode(h, x, prm)), (world, h.id, t, sp)
                n += 1
    print(f"e90check: {n} half x arm decodes identical")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=("selftest", "rows", "fit", "fitsw", "e90check", "stagea", "stageb", "stagec",
                                      "pickb", "transplant", "cohort"))
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--fold", default="all")
    ap.add_argument("--arm", action="append", default=[])
    ap.add_argument("--arms", choices=("b", "c", "e90"), default="b")
    ap.add_argument("--sw", nargs="+")
    ap.add_argument("--gaps", choices=("renewal", "transplant", "bridged"), default=None)
    a = ap.parse_args()
    {"selftest": selftest, "rows": lambda: rows(a.out, a.gaps or "renewal"), "fit": lambda: fit(a.paths[0], a.fold, a.out),
     "fitsw": lambda: fit_switch(a.paths[0], a.fold, a.out), "e90check": lambda: e90check(*a.paths),
     "stagea": lambda: stagea(*a.paths), "stageb": lambda: stageb(*a.paths, a.out, a.arms, a.sw),
     "stagec": lambda: stagec(*a.paths, a.sw[0] if a.sw else None, a.out), "pickb": lambda: pick_b(a.paths[0]),
     "transplant": lambda: transplant(*a.paths, a.out, a.gaps or "transplant"),
     "cohort": lambda: cohort(*a.paths, a.out, a.arm)}[a.stage]()
