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
census PARAMS        why labelled possessions go unmatched under PARAMS (matched, dead, wrong team, fragmented,
                     overlong), by labelled length
hold                 token accuracy on PFF-A: nearest team against the last team within R m, by distance
holdgrid PARAMS --out CSV
                     E20: the held-team token (HoldEmission, q fitted on PFF-A by fit_hold) crossed with lag
deadcues PARAMS      false and missed D frames under PARAMS by dead cue and by distance to a labelled stoppage
versions PARAMS...   margin over smooth50 of each params file on --rule worlds, held-out B games skipped
merge PARAMS --out CSV
                     E22: short possessions joined to their neighbours (spell_merge_frames, spell_merge_tails)
select CSV...        apply the pre-registered final rule (decision log, rule v2) to deadrule tables
barath-push          label-free: the shipped push signal's attack sign, quantiles and home-token share by push bin on
                     BAR-ATH's ATD
pff-push-tokens      barath-push's home-token share by push bin on native PFF A games (m0), for comparison
switchpen PARAMS --out CSV
                     E27: PARAMS's block posterior decoded by a path that charges each change of team, then PARAMS's
                     rules; held-out B games are not decoded
spellmass PARAMS --only V...
                     E27 diagnostic: match rate of PARAMS's short possessions by length and by posterior log-odds
                     tercile on PFF-A m0, and the matched share of the possessions each variant removes
equivpath SHIPPED BASE
                     frames where SHIPPED (BASE + switch_penalty) differs from switchpen's probe path on BASE
mergedose PARAMS --out CSV
                     diagnostic, not a candidate: E22's length merge at 25, 35 and 50 frames on PARAMS, to compare a
                     length cut with E27's penalty at a similar dose
deadruns PARAMS BASE9
                     E28 oracle, label-reading: interior flagged runs vetoed by the PFF-A m0 labels, rescored on
                     PFF-A m0 and m2 under PARAMS and BASE9, with the run table, census transitions and a
                     convention check
flipruns PARAMS      label-reading ceiling of short-possession flips: a greedy oracle gives team runs under 250
                     frames to the other team on PFF-A m0 and m2 (populations seen, unseen, all)
spellflip PARAMS --out PREFIX [--drop F ...] [--split]
                     E29: a ridge logistic on decoder._spell_runs features predicts which short possessions to
                     give to the other team; 2-fold game-OOF on PFF-A; writes PREFIX-pff.csv and PREFIX-weights.json
barath-spell PARAMS  E29's registered stop, label-free: spell-feature medians on BAR-ATH's candidate runs against
                     PFF-A m0's 10th-90th percentiles, and the frames PARAMS's spell flip changes on BAR-ATH
spellseen PARAMS     label-free: spell-feature medians and the fully-seen share of candidate runs on synthetic
                     IDSSE m0 and Metrica m0 (r2.6, seed 0) and on PFF-A m0
deadsplit PARAMS     label-reading: PARAMS's dead-ball headroom on PFF-A split into inserted, long inserted and removed D
deadcensus PARAMS    label-reading: label-free statistics of the long stoppages PARAMS misses on PFF-A, against live play
deadedges PARAMS     label-reading: insert_long split into missed, half and caught stoppages and the caught ones' edges
outrungrid PARAMS --out CSV  E33: PARAMS with each OUTRUN_GRID minimum run for ball-out cue runs
leadgrid PARAMS --out CSV  E32: PARAMS with each LEAD_GRID start-trim cut on the --rule worlds
insertruns PARAMS    label-reading ceiling of making short dead cue runs D, by ball-out evidence
ttitoken             E39 gate: nearest-player token against a time-to-intercept token on PFF-A seen alive frames
restartdet PARAMS    restart detector gate: law-of-the-game triggers and last touch against the first call after D
postfill PARAMS      restart-taker ceiling: wrong first calls after D given the labelled restart team
postd PARAMS         restart-taker gate: first team call after each D stretch against the labelled restart team
islandruns PARAMS    E37 ceiling: label-free island candidates inside team runs, inserted where labels say it helps
spellmodel PARAMS    E36 first gate: OOF spell flip target and capacity arms (weighted, span_share, pairs, dedup)
seedwins CSV A B     per seed world, how often model B beats model A in a score CSV
e41grid PARAMS       E41 arms: base and q_logit refitted with ln(1 + relative ball speed) (full decode per arm)
e60grid PARAMS       E60 arms: base, q_logit refitted with the goalward-ball term, and that refit at lag 10 and 5
e61grid PARAMS       E61 arms: base and E60's frozen goalward-ball emission (E60_REFIT), on another base
e62grid PARAMS       E62 arms: E60's grid refitted on undoubled, interpolated PFF, plus E60_REFIT
e64grid PARAMS SPELL E64 arms: base, spell_logit from the SPELL JSON, and the split and inter goalward forms
e65grid PARAMS       E65 arms: base and the one-sided goalward term with its distance interaction (oneint)
velgrid PARAMS       E66 arms: the push, still-ball and pace constants one step either side, on the fixed loader
velfield PARAMS      velgrid's arms each decoded from scratch (for a base with dead-line fields, which rulegrid rejects)
e67grid PARAMS       E67 arms: temper, switch_penalty and poss_mean_s one step either side
e68grid PARAMS SPELL E68 arms: base, and spell_logit from the SPELL JSON at spell_flip_p 0.8, 0.7 and 0.65
officials            label-free: is an official tracked inside a BAR-ATH team slot (over-11 runs, slot profiles)
linegrid PARAMS      E42 arms: a shorter dead length for missing runs that start near a line
linelead PARAMS      E42b arms: E42 plus a 25-frame lead cut for those runs (full decode per arm)
linefull PARAMS      E42c arms: E42 with the whole 50-frame start trim removed for those runs
endlead PARAMS       E46 arms: a dead run ends where players are fast 2 or 4 s later (full decode per arm)
returngrid PARAMS    E47 arms: a run whose ball reappears far from where it vanished needs a longer dead length
flippairs PARAMS     adjacent co-flips: label-free share of paired flips, and the independent oracle resolved per pair
flipindep PARAMS     spell flip ceiling with the per-run target applied at once (indep) against the greedy oracle (seq)
insertfit PARAMS --out PREFIX
                     E35 first gate: OOF run logistic on PFF-A choosing short cue runs to make D
stepfeas PARAMS      E34 feasibility pass: pace-drop dating of no-out stoppage starts against labels, with the kill gate
contest              label-reading: a contest gate's hit rate near labelled hand-overs against inside possessions
slotcheck            label-free BAR-ATH slot check: keepers' teams, teams over 11 slots, fast nearest-slot jumps
deadends PARAMS      label-reading: stoppage ends by restart kick, and short stoppages by ball-out evidence
deadstarts PARAMS    label-reading: the dead rule's cue runs against labelled stoppage edges, by ball-out evidence
spellveto PARAMS WEIGHTS --out CSV
                     E29 veto rows: PARAMS with the spell flip at each registered arm and spellflip's all-A weights
subs CSV...          label-free: label shares, H, A and D runs and differing frames of our own submission CSVs
confirm CSV          a `score` run table: per-group margins over smooth50 for every model, and paired
                     per-game differences with 90% t intervals on the native PFF games

Oracle rows read other games' labels and are diagnostics, never candidates. Nothing here reads a BAR-ATH
label or the public window.
"""
import argparse
import dataclasses
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from possession import bench, challenge, idsse, metrica, score
from possession.decoder import SPELL_FEATURES, Decoder, _missing_run_dead
from possession.half import AWAY, FPS, HOME, NO_TEAM, A, BallGeometry, D, H, X

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
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        per = {}
        for half, gt in zip(case.halves, case.layout.cut(case.gt)):
            mine, floor = model.decode(half).codes, s50.decode(half).codes
            team = ffill_team(mine, np.where(floor == D, H, floor))
            seen = half.nearest_team != NO_TEAM
            variants = {"model": mine, "s50": floor,
                        "s50D_modelteam": np.where(floor == D, D, team),
                        "oracleD_modelteam": np.where(gt == D, D, team),
                        "modelD_oracleteam": np.where(mine == D, D, np.where(gt == D, team, gt)),
                        "modelD_oracleteam_seen": np.where(mine == D, D, np.where((gt != D) & seen, gt, team)),
                        "modelD_oracleteam_unseen": np.where(mine == D, D, np.where((gt != D) & ~seen, gt, team))}
            for name, codes in variants.items():
                per.setdefault(name, []).append(codes.astype(np.int8))
        for name, preds in per.items():
            f1, n = score.spell_f1(case.layout, case.gt, preds, runs)
            rows.append({"group": group, "variant": name, "spell_f1": f1, "n_pred": n})
    t = pd.DataFrame(rows)
    print(t.pivot_table(index="variant", columns="group", values="spell_f1").round(4).to_string())


def census(params, rhos=(2.6,), items=SEARCH):
    """Why labelled possessions go unmatched: each one is matched (a same-team spell at IoU >= 0.5), dead or
    wrong_team (under half of it covered by its team), fragmented (two or more same-team spells, none at 0.5) or
    overlong (one spell covers it but runs on into its neighbours); by labelled length. Held-out B games are skipped."""
    model, rows = Decoder.load(params), []
    bins = [0, 2, 5, 10, 20, np.inf]
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        pred = score._assemble_checked(case.layout, case.gt, [model.decode(h).codes for h in case.halves])
        spells = score.possession_spells(pred, runs)
        starts = np.array([a for a, _, _ in spells])
        for a, b, c in score.possession_spells(case.gt, runs):
            seg = pred[a:b]
            same = [(x, y) for x, y, k in spells[max(np.searchsorted(starts, a, "right") - 1, 0):
                                                 np.searchsorted(starts, b)] if k == c and x < b and y > a]
            iou = max(((min(b, y) - max(a, x)) / (max(b, y) - min(a, x)) for x, y in same), default=0.0)
            if iou >= 0.5:
                kind = "matched"
            elif (seg == c).sum() * 2 < b - a:
                kind = "dead" if (seg == D).sum() >= ((seg != c) & (seg != D)).sum() else "wrong_team"
            else:
                kind = "fragmented" if len(same) > 1 else "overlong"
            rows.append({"group": group, "kind": kind,
                         "length": pd.cut([(b - a) / FPS], bins, right=False).astype(str)[0]})
        print(world, "labelled", len(rows), "predicted spells", len(spells), flush=True)
    t = pd.DataFrame(rows)
    print(pd.crosstab([t.group, t.length], t.kind, normalize="index", margins=False).round(3).to_string())
    print(pd.crosstab(t.group, t.kind, normalize="index").round(3).to_string())
    print(t.groupby(["group", "length"]).size().unstack("length").to_string())


def hold():
    """Token accuracy on native PFF A games, live frames after kickoff: the nearest team against the team of the
    last player seen within R m of the ball (held through flights and gaps), by nearest-player distance."""
    from possession import challenge, pff
    radii, games, rows = (1.0, 1.5, 2.0, 3.0), [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        h = challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id)
        tok, d, idx = h.nearest_team, h.geometry.nearest_m, np.arange(h.n)
        live = (c.labels != D) & (idx >= h.id.kickoff)
        row = {"seen": tok != NO_TEAM, "d": np.nan_to_num(d, nan=np.inf), "nearest": tok == c.labels}
        for r in radii:
            ctrl = (tok != NO_TEAM) & (d <= r)
            last = np.maximum.accumulate(np.where(ctrl, idx, -1))
            row[f"hold{r:g}"] = np.where(last >= 0, tok[np.maximum(last, 0)], NO_TEAM) == c.labels
        rows.append(pd.DataFrame({k: v[live] for k, v in row.items()}))
    t = pd.concat(rows, ignore_index=True)
    t["bin"] = np.where(t.seen, pd.cut(t.d, [0, 1, 2, 3, 5, 10, np.inf], right=False).astype(str), "unseen")
    out = t.groupby("bin").mean(numeric_only=True).drop(columns=["seen", "d"])
    out.insert(0, "share", t.groupby("bin").size() / len(t))
    print(out.round(4).to_string())
    print("all seen", t[t.seen].mean(numeric_only=True).round(4).to_dict())


def restart(params, window_s=5.0, exit_s=2.0, edge_m=1.0):
    """After each labelled stoppage on native PFF A games (m0): the decoder's codes over the first window_s of the
    restarted possession, the share of all wrong-team live frames that fall there, and how often the restart
    team differs from the last team before the stoppage, by where the ball was last seen in the exit_s before
    it (beyond or within edge_m of a touchline or a goal line, inside, or unseen)."""
    from possession import challenge, pff
    model, games, rows, wrong = Decoder.load(params), [], [], 0
    w, e = int(window_s * FPS), int(exit_s * FPS)
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        h = challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id)
        codes, gt, idx = model.decode(h).codes, c.labels, np.arange(h.n)
        bad = (gt != D) & (idx >= h.id.kickoff) & (codes != gt) & (codes != D)
        wrong += int(bad.sum())
        length, width = c.geometry.pitch_m
        live_idx = np.flatnonzero(gt != D)
        for s in np.flatnonzero((gt[1:] != D) & (gt[:-1] == D)) + 1:
            before = live_idx[live_idx < s]
            if not len(before) or before[-1] < h.id.kickoff:
                continue
            team, last, out = gt[s], gt[before[-1]], before[-1] + 1
            stop = s + int(np.argmax(np.r_[gt[s:] != team, True]))
            win = slice(s, min(s + w, stop))
            xy = ball[max(out - e, 0):out + 1]
            xy = xy[~np.isnan(xy[:, 0])]
            if not len(xy):
                exit = "unseen"
            else:
                x, y = xy[-1]
                exit = ("touchline" if min(y, width - y) < edge_m else
                        "goal line" if min(x, length - x) < edge_m else "inside")
            rows.append({"exit": exit, "flip": bool(team != last), "frames": win.stop - win.start,
                         "right": int((codes[win] == team).sum()), "dead": int((codes[win] == D).sum()),
                         "wrong": int(bad[win].sum()), "seen": int(seen[win].sum()),
                         "stoppage_s": (s - out) / FPS})
    t = pd.DataFrame(rows)
    print(f"restarts {len(t)}; wrong-team live frames {wrong}, of which in the first {window_s:g} s after a "
          f"restart {t.wrong.sum()} ({t.wrong.sum() / wrong:.1%})")
    g = t.groupby(["exit", "flip"])
    out = g[["frames", "right", "dead", "wrong", "seen"]].sum()
    out = out[["right", "dead", "wrong", "seen"]].div(out.frames, axis=0).round(3).assign(
        restarts=g.size(), frames=g.frames.sum(), median_stoppage_s=g.stoppage_s.median().round(1))
    print(out.to_string())
    flip = t.groupby("exit").flip.agg(["mean", "size"]).round(3)
    print("flip rate by exit\n" + flip.to_string())


def _team_push(g, kickoff, k=12):
    """Home push minus away push in m/s: each team's median per-slot x velocity over 2k frames, positive toward
    the goal it attacks (E16's Half.push_mps, removed in fa14a26)."""
    push = np.full((g.n, 2), np.nan)
    for team in (HOME, 1 - HOME):
        x = g.players_xy[:, g.slot_team == team, 0].astype(np.float64)
        with np.errstate(all="ignore"):
            start = float(np.nanmean(x[kickoff:kickoff + FPS]))
        if np.isnan(start):
            continue
        dx = np.full_like(x, np.nan)
        dx[k:-k] = (x[2 * k:] - x[:-2 * k]) / (2 * k) * FPS
        some = np.isfinite(dx).any(axis=1)
        with np.errstate(all="ignore"):
            push[some, team] = (1.0 if start < g.pitch_m[0] / 2 else -1.0) * np.nanmedian(dx[some], axis=1)
    return push[:, HOME] - push[:, 1 - HOME]


def pushgap(params):
    """On native PFF A games (m0), live frames after kickoff with the ball unseen and an H or A code: the decoder's
    accuracy by the push toward the team it calls (E16's push, signed so positive agrees with the code)."""
    from possession import challenge, pff
    model, games, rows = Decoder.load(params), [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        h = challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id)
        codes, gt, idx = model.decode(h).codes, c.labels, np.arange(h.n)
        push = _team_push(c.geometry, h.id.kickoff)
        keep = (gt != D) & (idx >= h.id.kickoff) & ~seen & (codes != D) & np.isfinite(push)
        toward = np.where(codes == HOME, push, -push)
        rows.append(pd.DataFrame({"toward": toward[keep], "right": (codes == gt)[keep]}))
    t = pd.concat(rows, ignore_index=True)
    t["bin"] = pd.cut(t.toward, [-np.inf, -3, -2, -1, -0.5, 0.5, 1, 2, 3, np.inf]).astype(str)
    out = t.groupby("bin", sort=False).right.agg(["mean", "size"])
    out["share"] = out["size"] / len(t)
    order = sorted(out.index, key=lambda b: float(b.split(",")[0].strip("(")))
    print(out.loc[order].round(3).to_string())
    print("all", round(t.right.mean(), 4), len(t))


def spellpush(params):
    """Per predicted possession on native PFF A games (m0): how often it is mostly wrong (under half its frames
    carry its team's label), by its mean push toward its own team, its length, its unseen share and whether
    both neighbours are possessions of the other team; other_gt_right is the mean share of frames labelled
    with the other team minus the share labelled with its own, so a positive value means flipping helps.
    Tells whether push can judge whole spells."""
    from possession import challenge, pff
    model, games, rows = Decoder.load(params), [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        h = challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id)
        codes, gt, k0 = model.decode(h).codes, c.labels, h.id.kickoff
        push = _team_push(c.geometry, k0)
        edges = np.flatnonzero(np.diff(codes[k0:])) + 1 + k0
        runs = [(int(a), int(b), int(codes[a])) for a, b in zip(np.r_[k0, edges], np.r_[edges, len(codes)])]
        for i, (a, b, team) in enumerate(runs):
            if team == D:
                continue
            toward = push[a:b] if team == HOME else -push[a:b]
            other = 1 - team
            rows.append({"length_s": (b - a) / FPS, "unseen": float((~seen[a:b]).mean()),
                         "push": float(np.nanmean(toward)) if np.isfinite(toward).any() else np.nan,
                         "sandwiched": i > 0 and i + 1 < len(runs) and runs[i - 1][2] == other == runs[i + 1][2],
                         "right": float((gt[a:b] == team).mean()), "other": float((gt[a:b] == other).mean()),
                         "frames": b - a})
    t = pd.DataFrame(rows).dropna()
    t["wrong"] = t.right < 0.5
    t["push_bin"] = pd.cut(t.push, [-np.inf, -2, -1, 0, 1, 2, np.inf]).astype(str)
    t["len_bin"] = pd.cut(t.length_s, [0, 2, 5, 10, np.inf], right=False).astype(str)
    t["mostly_unseen"] = t.unseen >= 0.5
    print(f"{len(t)} predicted possessions, {t.wrong.mean():.3f} mostly wrong")
    for keys in (["push_bin"], ["mostly_unseen", "push_bin"], ["sandwiched", "push_bin"], ["len_bin", "push_bin"]):
        g = t.groupby(keys)
        print(pd.DataFrame({"spells": g.size(), "wrong": g.wrong.mean().round(3),
                            "other_gt_right": (g.other.mean() - g.right.mean()).round(3),
                            "frames": g.frames.sum()}).to_string(), "\n")


def equiv(shipped, base, *changes):
    """Frames where SHIPPED decodes differently from BASE.replace(k=v, ...), the variant a grid selected: one
    world per dev source at dead_bias 2.6, seed 0, A games only for the native sources. 0 means the frozen file
    is the probe's winner."""
    import json
    a = Decoder.load(shipped)
    b = Decoder.load(base).replace(**{k: json.loads(v) for k, v in (c.split("=", 1) for c in changes)})
    n = differ = 0
    for items in (["pff:m0:native"], ["pffsb:m0:native"], ["idsse:m0"], ["m0"]):
        for group, world, case in itertools.islice(scored_cases(bench.dev_worlds(items, [2.6], seeds=[0])), 1):
            for h in case.halves:
                x, y = a.decode(h).codes, b.decode(h).codes
                n, differ = n + x.size, differ + int((x != y).sum())
            print(world, flush=True)
    print(f"{shipped} against {base} with {' '.join(changes)}: {differ} of {n} frames differ")


def equivpath(shipped, base):
    """Frames where SHIPPED, which is BASE plus switch_penalty, decodes differently from switchpen's probe path on
    BASE: one world per dev source at dead_bias 2.6, seed 0, A games only for PFF. 0 means the decoder's
    _penalized_path and its place in decode reproduce the selected arm."""
    a, b = Decoder.load(shipped), Decoder.load(base)
    assert a.replace(switch_penalty=0.0) == b
    n = differ = 0
    for items in (["pff:m0:native"], ["idsse:m0"], ["m0"]):
        for group, world, case in itertools.islice(scored_cases(bench.dev_worlds(items, [2.6], seeds=[0])), 1):
            for h in case.halves:
                g, m = _block_posterior(b, h)
                x = a.decode(h).codes
                y = _path_codes(b, h, g, m, a.params.switch_penalty, np.zeros(len(g), bool))
                n, differ = n + x.size, differ + int((x != y).sum())
            print(world, flush=True)
    print(f"{shipped} against switchpen's path on {base}: {differ} of {n} frames differ")


def _held(half, radius):
    """Team of the last frame whose nearest player was seen within radius m of the ball; NO_TEAM before it."""
    tok, idx = half.nearest_team, np.arange(half.n)
    last = np.maximum.accumulate(np.where((tok != NO_TEAM) & (half.geometry.nearest_m <= radius), idx, -1))
    return np.where(last >= 0, tok[np.maximum(last, 0)], NO_TEAM).astype(np.int8)


def fit_hold(radius):
    """(q_hold, q_gap) on native PFF A games, live frames after kickoff with a held team: how often the held team
    is the labelled one on seen frames farther than radius from the nearest player, and on unseen frames."""
    from possession import challenge, pff
    games, far, gap = [], [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        h = challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id)
        held, tok = _held(h, radius), h.nearest_team
        keep = (c.labels != D) & (np.arange(h.n) >= h.id.kickoff) & (held != NO_TEAM)
        hit = held == c.labels
        far.append(hit[keep & (tok != NO_TEAM) & (h.geometry.nearest_m > radius)])
        gap.append(hit[keep & (tok == NO_TEAM)])
    q_hold, q_gap = float(np.concatenate(far).mean()), float(np.concatenate(gap).mean())
    print(f"hold {radius:g} m: q_hold {q_hold:.4f}, q_gap {q_gap:.4f}", flush=True)
    return q_hold, q_gap


@dataclasses.dataclass(frozen=True)
class HoldEmission:
    """Probe-only: BASE's emission, with the team row of every seen frame farther than radius from the nearest
    player replaced by the held team at q_hold, and (q_gap > 0) unseen frames given the held team at q_gap."""
    base: object
    radius: float
    q_hold: float
    q_gap: float

    @property
    def needs_geometry(self):
        return True

    def loglik(self, half):
        out = self.base.loglik(half).astype(np.float64)
        held, tok = _held(half, self.radius), half.nearest_team
        alive = np.logaddexp(out[:, 0], out[:, 1])
        far = (tok != NO_TEAM) & (half.geometry.nearest_m > self.radius) & (held != NO_TEAM)
        home = held == HOME
        lq, lm = np.log(self.q_hold), np.log1p(-self.q_hold)
        out[far, 0] = np.where(home[far], lq, lm) + alive[far]
        out[far, 1] = np.where(home[far], lm, lq) + alive[far]
        if self.q_gap:
            gap = (tok == NO_TEAM) & (held != NO_TEAM)
            lq, lm = np.log(self.q_gap), np.log1p(-self.q_gap)
            out[gap, 0] += np.where(home[gap], lq, lm)
            out[gap, 1] += np.where(home[gap], lm, lq)
            out[gap, 2] += np.log(0.5)
        return out.astype(np.float32)


def holdgrid(params, out, rhos, items):
    """E20: PARAMS with the held-team token, R x gaps x lag; the dead-run stage as PARAMS has it."""
    from possession.decoder import _lag_handovers
    base, s50, rows = Decoder.load(params), bench.Smoother(50), []
    fits = {r: fit_hold(r) for r in HOLD_RADII}
    zero = dict(dead_min_run=0, dead_trim=0, dead_close=0, dead_outside_m=0.0, dead_still_mps=0.0,
                dead_still_frames=0, dead_pace_still_mps=0.0, dead_pace_live_mps=0.0, handover_lag=0)
    chain_params = dataclasses.replace(base.params, **zero)
    chains = {(r, gaps): Decoder(HoldEmission(base.emission, r, q_hold, q_gap if gaps else 0.0), chain_params)
              for r, (q_hold, q_gap) in fits.items() for gaps in (False, True)}
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        variants = {"base": [base.decode(h).codes for h in case.halves]}
        for (r, gaps), chain in chains.items():
            dead = [_missing_run_dead(chain.decode(h).codes, h, base.params) for h in case.halves]
            for lag in HOLD_LAGS:
                variants[f"hold={r:g} gaps={'on' if gaps else 'off'} lag={lag}"] = [_lag_handovers(c, lag) for c in dead]
        for name, codes in variants.items():
            f1, n = score.spell_f1(case.layout, case.gt, codes, runs)
            rows.append({"group": group, "world": world, "variant": name, "spell_f1": f1,
                         "floor": floor, "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out)


def deadcues(params, rhos=(2.6,), items=SEARCH):
    """Where PARAMS's D goes wrong, by frame: labelled-live frames called D (false D) and labelled-D frames called
    live (missed D), split by which dead cue covers the frame (ball unseen, slow ball run, walking players, ball
    off the pitch, none) and by distance to the nearest labelled stoppage. Held-out B games are skipped."""
    model, rows = Decoder.load(params), []
    p = model.params
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        for half, gt in zip(case.halves, case.layout.cut(case.gt)):
            codes, g, n = model.decode(half).codes, half.geometry, half.n
            idx = np.arange(n)
            slow = np.zeros(n, bool)
            run = np.concatenate(([0], (g.speed_mps < p.dead_still_mps).view(np.int8), [0]))
            edges = np.flatnonzero(np.diff(run))
            for a, b in zip(edges[::2], edges[1::2]):
                slow[a:b] = b - a >= p.dead_still_frames
            cue = np.select([half.nearest_team == NO_TEAM, slow, half.pace_mps < p.dead_pace_still_mps,
                             g.outside_m > p.dead_outside_m], ["unseen", "slow", "walking", "outside"], "none")
            dead_gt = np.flatnonzero(gt == D)
            if len(dead_gt) == 0:
                continue
            pos = np.clip(np.searchsorted(dead_gt, idx), 1, len(dead_gt) - 1)
            gap = np.minimum(np.abs(idx - dead_gt[pos - 1]), np.abs(dead_gt[pos] - idx)) / FPS
            near = np.asarray(pd.cut(gap, [-1, 0, 2, 5, 10, np.inf]).astype(str), dtype=object)
            keep = (idx >= half.id.kickoff) & (gt != X)
            kind = np.where((gt != D) & (codes == D), "false_D", np.where((gt == D) & (codes != D), "missed_D", ""))
            m = keep & (kind != "")
            rows.append(pd.DataFrame({"group": group, "kind": kind[m], "cue": cue[m], "near_s": near[m]}))
            rows.append(pd.DataFrame({"group": group, "kind": np.where(gt[keep] == D, "all_D", "all_live"),
                                      "cue": cue[keep], "near_s": near[keep]}))
        print(world, flush=True)
    t = pd.concat(rows, ignore_index=True)
    print(t.groupby(["group", "kind"]).size().unstack("kind").to_string())
    print(pd.crosstab([t.group, t.kind], t.cue, normalize="index").round(3).to_string())
    print(pd.crosstab([t.group, t.kind], t.near_s, normalize="index").round(3).to_string())


def versions(paths, items):
    """Margin over smooth50 of each params file in PATHS on ITEMS's worlds; held-out B games are skipped."""
    models, s50, rows = {Path(q).stem: Decoder.load(q) for q in paths}, bench.Smoother(50), []
    for group, world, case in scored_cases(bench.dev_worlds(items, (2.6,), seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        for name, model in models.items():
            f1, n = score.spell_f1(case.layout, case.gt, [model.decode(h).codes for h in case.halves], runs)
            rows.append({"group": group, "params": name, "spell_f1": f1, "floor": floor, "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    t = pd.DataFrame(rows)
    print(t.pivot_table(index="params", columns="group", values="margin").round(4).to_string())
    print(t.pivot_table(index="params", columns="group", values="spell_f1").round(4).to_string())
    print(t.groupby("group").floor.first().round(4).to_string())


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


def barath_push():
    """Label-free orientation check of the shipped Half.push_mps on BAR-ATH's ATD: each team's mean x at kick-off
    and the attack sign it implies, push quantiles, and the share of seen frames whose nearest player is home by
    push bin (PFF-A labels give 0.24 at <= -3 and 0.75 at >= +3 for P(home), push_probe)."""
    for g, hid in zip(challenge.load_geometry(), challenge._half_ids()):
        h = challenge.observe(g, hid)
        for team in (HOME, 1 - HOME):
            with np.errstate(all="ignore"):
                start = float(np.nanmean(g.players_xy[hid.kickoff:hid.kickoff + FPS, g.slot_team == team, 0]))
            print(f"half {hid.half} team {team}: mean x at kick-off {start:.1f} of {g.pitch_m[0]}, "
                  f"attack sign {'+' if start < g.pitch_m[0] / 2 else '-'}")
        live = np.arange(h.n) >= hid.kickoff
        print(f"  push NaN share {np.isnan(h.push_mps[live]).mean():.3f}; quantiles 5/25/50/75/95:",
              np.nanpercentile(h.push_mps[live], [5, 25, 50, 75, 95]).round(2).tolist())
        print(_token_by_push([h]).to_string())


def pff_push_tokens():
    """barath-push's home-token share by push bin, on native PFF A games (m0) with the ball PFF's tracker saw:
    the same label-free statistic on the dev source the push stage was selected on."""
    from possession import pff
    games, hs = [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        hs.append(challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id))
    print(f"{len(hs)} halves")
    print(_token_by_push(hs).to_string())


def _token_by_push(hs, bins=(-1e9, -3, -2, -1, 0, 1, 2, 3, 1e9)):
    parts = []
    for h in hs:
        live = np.arange(h.n) >= h.id.kickoff
        tok, push = h.nearest_team[live], h.push_mps[live].astype(np.float64)
        keep = (tok != NO_TEAM) & np.isfinite(push)
        parts.append(pd.DataFrame({"push": push[keep], "home": tok[keep] == HOME}))
    t = pd.concat(parts, ignore_index=True)
    grp = t.groupby(pd.cut(t.push, list(bins)), observed=False)
    return pd.DataFrame({"share": grp.size() / len(t), "p_home_token": grp.home.mean()}).round(3).T


def subs(paths):
    """Label-free counts of our own submission CSVs on the graded frames: label shares, maximal H, A and D runs,
    and frames that differ from the first file."""
    import games
    blocks = [(lo, hi + 1) for _, lo, hi in games.half_video_blocks(challenge.GAME)]
    first = None
    for path in paths:
        lab = pd.read_csv(path).label.to_numpy()
        graded = np.concatenate([lab[lo:hi] for lo, hi in blocks])
        runs = {k: sum(int(((x == k) & ~np.r_[False, x[:-1] == k]).sum()) for x in (lab[lo:hi] for lo, hi in blocks))
                for k in ("H", "A", "D")}
        diff = "" if first is None else f", differs from the first file on {int((graded != first).sum())} frames"
        print(f"{Path(path).name}: shares", pd.Series(graded).value_counts(normalize=True).round(4).to_dict(),
              f"runs {runs}{diff}")
        if first is not None:
            half = np.concatenate([np.full(hi - lo, k + 1) for k, (lo, hi) in enumerate(blocks)])
            moved = graded != first
            print(pd.crosstab([half[moved], first[moved]], graded[moved],
                              rownames=["half", "first file"], colnames=["this file"]).to_string())
        first = graded if first is None else first


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
        if not world.endswith(("_native", "_bridged")):
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


def confirm(path, halves=("all", "A", "B")):
    t = pd.read_csv(path)
    pooled = t[t.case == "dev_pooled"].assign(group=lambda f: f.world.map(bench.group))
    if "B" not in halves and "all" not in halves:
        pooled = pooled[~pooled.world.str.endswith(("_native", "_bridged"))]
    spell = pooled.pivot_table(index=["group", "world"], columns="model", values="spell_f1")
    margin = spell.sub(spell["baseline_smooth50"], axis=0).groupby("group").mean()
    print("seed-mean pooled margin over smooth50 per group")
    print(margin.T.assign(min=margin.T.min(1), mean=margin.T.mean(1)).sort_values("min", ascending=False)
          .round(4).to_string())
    games = t[(t.case != "dev_pooled") & t.world.str.endswith(("_native", "_bridged"))]
    if games.empty:
        return
    wide = games.pivot_table(index=["world", "case"], columns="model", values="spell_f1")
    models = [m for m in wide.columns if m != "baseline_smooth50"]
    print("\nnative PFF, paired per game: mean difference [90% t interval], games won; "
          "A = odd-indexed games (selection), B = even-indexed (held out)")
    for world, w in wide.groupby(level="world"):
        order = list(dict.fromkeys(games[games.world == world].case))
        split = {k: v for k, v in {"all": order, "A": order[0::2], "B": order[1::2]}.items() if k in halves}
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


def jitter(paths, rel=1e-6, seeds=(0, 1, 2), near=1e-5):
    """BAR-ATH frames whose code changes when every float input of the decoder moves by up to rel, relative
    (about eight float32 ulps), and frames whose geometry sits within near of a dead-rule threshold: how
    much another numpy build or CPU could change the submission. Reads only automatic inputs."""
    halves = challenge.halves("atd")
    names = [f.name for f in dataclasses.fields(BallGeometry)]
    for path in paths:
        model = Decoder.load(path)
        p = model.params
        base = [model.decode(h).codes for h in halves]
        cuts = [("outside_m", p.dead_outside_m), ("speed_mps", p.dead_still_mps)]
        close = {n: sum(int((np.abs(getattr(h.geometry, n) - t) < near).sum()) for h in halves)
                 for n, t in cuts if t}
        if p.dead_pace_still_mps:
            close["pace_mps"] = sum(int((np.abs(h.pace_mps - p.dead_pace_still_mps) < near).sum()) for h in halves)
        changed = []
        for seed in seeds:
            rng = np.random.default_rng(seed)

            def shake(a):
                return (a * (1 + rel * rng.uniform(-1, 1, a.shape))).astype(np.float32)
            moved = [dataclasses.replace(h, geometry=BallGeometry(*(shake(getattr(h.geometry, n)) for n in names)),
                                         pace_mps=shake(h.pace_mps), push_mps=shake(h.push_mps)) for h in halves]
            changed.append(sum(int((model.decode(m).codes != b).sum()) for m, b in zip(moved, base)))
        print(f"{path}: frames changed under {rel:g} relative jitter, seeds {list(seeds)}: {changed} of "
              f"{sum(len(b) for b in base)}; frames within {near:g} of a threshold: {close}")


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


def _goal_columns(nearest_m, goal_mps, form):
    """The goalward-ball columns of a GOAL_FORMS form, u = BallGeometry.goal_mps clipped to +-40 and
    s = sign(u) ln(1+|u|): odd s (E60); split ln(1+max(u,0)) and ln(1+max(-u,0)), one weight per direction;
    inter s and s ln(1+d), d the nearest player's distance; oneint ln(1+max(u,0)) and its product with ln(1+d)
    (E65)."""
    u = np.clip(goal_mps.astype(np.float64), -40.0, 40.0)
    odd = np.sign(u) * np.log1p(np.abs(u))
    if form == "odd":
        return odd[:, None]
    if form == "split":
        return np.column_stack([np.log1p(np.maximum(u, 0.0)), np.log1p(np.maximum(-u, 0.0))])
    if form == "inter":
        return np.column_stack([odd, odd * np.log1p(nearest_m.astype(np.float64))])
    if form == "oneint":
        toward = np.log1p(np.maximum(u, 0.0))
        return np.column_stack([toward, toward * np.log1p(nearest_m.astype(np.float64))])
    raise ValueError(form)


GOAL_FORMS = ("odd", "split", "inter", "oneint")


def fit_logit(speed=False, rel=False, goal=False):
    """Logistic fit of P(token == labelled team) on native PFF seen alive frames of the A games (games[0::2]
    in pff.load order, the same split as scored_cases). speed adds ln(1+v) and ln(1+d)ln(1+v), v the decoder's
    BallGeometry.speed_mps capped at 40. rel (E41) adds ln(1+r), r = BallGeometry.rel_mps capped at 40. goal
    (E60) adds sign(u) ln(1+|u|), u = BallGeometry.goal_mps clipped to +-40; a GOAL_FORMS name instead of True
    adds that form's columns (E64)."""
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
        if rel:
            x = np.column_stack([x, np.log1p(np.minimum(h.geometry.rel_mps[keep].astype(np.float64), 40.0))])
        if goal:
            x = np.column_stack([x, _goal_columns(h.geometry.nearest_m[keep], h.geometry.goal_mps[keep],
                                                  "odd" if goal is True else goal)])
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


@dataclasses.dataclass(frozen=True)
class GoalFormEmission:
    """Probe-only: Tier0Emission with q per seen frame from _logit_features plus a GOAL_FORMS form's columns,
    weights W in that order. BASE must have no q_logit term, so its seen rows carry a constant q."""
    base: object
    form: str
    w: tuple
    needs_geometry = True

    def loglik(self, half):
        out = self.base.loglik(half).astype(np.float64)
        g, tok = half.geometry, half.nearest_team
        where = tok != -1
        nearest = g.nearest_m[where].astype(np.float64)
        x = np.column_stack([_logit_features(nearest, g.margin_m[where].astype(np.float64)),
                             _goal_columns(nearest, g.goal_mps[where], self.form)])
        z = x @ np.asarray(self.w)
        q0 = self.base.q
        seen_row = (out[where, 0] + out[where, 1] - np.log(q0) - np.log1p(-q0)) / 2
        hit, miss, home = -np.logaddexp(0.0, -z), -np.logaddexp(0.0, z), tok[where] == 0
        out[where, 0] = np.where(home, hit, miss) + seen_row
        out[where, 1] = np.where(home, miss, hit) + seen_row
        return out.astype(np.float32)


def goal_form_model(model, form, w):
    """MODEL with its emission's q from GoalFormEmission(FORM, W); every q_logit field of the base zeroed."""
    from possession.decoder import _LOGIT_FIELDS, Decoder as Dec
    const = dataclasses.replace(model.emission, **dict.fromkeys(_LOGIT_FIELDS, 0.0))
    return Dec(GoalFormEmission(const, form, tuple(w)), model.params)


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
        if world.endswith("_B"):
            continue
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
HOLD_RADII, HOLD_LAGS = (1.0, 1.5, 2.0), (0, 10, 20)
PUSH_GRID = [{}] + [{"spell_push_mps": t, "spell_push_frames": n} for t, n in ((2.0, 125), (2.0, 250), (1.5, 125),
                                                                          (3.0, 250))] + \
    [{"spell_push_mps": 2.0, "spell_push_frames": n, "spell_push_between": 1} for n in (125, 250)]
PUSH_UNSEEN_GRID = [{}] + [{"spell_push_mps": t, "spell_push_frames": n, "spell_push_unseen": u}
                          for u in (0.5, 0.8) for t, n in ((2.0, 125), (2.0, 250), (3.0, 250))]
# E67: the chain's evidence scale and persistence one step either side, on a base carrying the goalward term.
CHAIN_GOAL_GRID = [{}] + [{"temper": t} for t in (0.07, 0.14)] + [{"switch_penalty": v} for v in (0.5, 1.5)] + \
    [{"poss_mean_s": v} for v in (4.5, 8.0)]
# E66: the velocity-reading constants one step either side of v13's, re-selected on the undoubled PFF loader.
VELOCITY_GRID = [{}] + [{"spell_push_mps": t, "spell_push_frames": n}
                        for t, n in ((1.5, 250), (2.5, 250), (3.0, 250), (2.0, 125), (2.0, 375))] + \
    [{"dead_still_mps": v, "dead_still_frames": f} for v, f in ((0.5, 50), (1.5, 50), (1.0, 25), (1.0, 100))] + \
    [{"dead_pace_still_mps": v} for v in (0.0, 0.75)]
DOSE_GRID = [{}] + [{"spell_merge_frames": n} for n in (25, 35, 50)]
MERGE_GRID = [{}] + [{"spell_merge_frames": n} for n in (25, 50, 75, 100)] + \
    [{"spell_merge_frames": n, "spell_merge_tails": 1} for n in (25, 50)]
COMBO_GRID = [{"handover_lag": lag, "dead_trim": trim, "dead_pace_still_mps": sv, "dead_still_frames": sf}
              for lag in (15, 20) for trim in (50, 37) for sv in (0.5, 0.75) for sf in (50, 25)]
LEAD_GRID = [{}] + [{"dead_out_lead_cut": o} for o in (25, 40, 50)] + \
    [dict(dead_lead_cut=l, **({"dead_out_lead_cut": o} if o else {}))
     for l, outs in ((10, (0, 25, 40)), (20, (0, 25, 30)), (30, (0, 20)), (40, (0, 10)), (50, (0,))) for o in outs]
OUTRUN_GRID = [{}] + [{"dead_out_min_run": r} for r in (113, 101, 88, 76)]
CUT_GRID = [{}] + [{"spell_flip_p": c} for c in (0.75, 0.7, 0.65)]
ADJ_GRID = [{}] + [{"spell_flip_adjacent": True, **({"spell_flip_p": c} if c != 0.8 else {})} for c in (0.8, 0.75, 0.7, 0.65)]
DEAD6_GRID = [{"dead_min_run": r, "dead_trim": t, "dead_close": c}
              for r in (101, 126) for t in (12, 25, 37, 50) for c in (100, 150, 200)]


def rulegrid(params, out, rhos, items, grid):
    """PARAMS's chain decoded once per half, then each grid entry's dead-run and lag fields applied on top;
    held-out B games are not decoded."""
    from possession.decoder import _frame_logodds, _rules
    base, s50, rows = Decoder.load(params), bench.Smoother(50), []
    chain = _rules_off(base)

    def logodds(h):
        if not base.params.spell_flip_p:
            return None
        g, m = _block_posterior(base, h)
        return _frame_logodds(g, h, base.params.stride, m)

    rules = {" ".join(f"{k}={v}" for k, v in g.items()) or "base": dataclasses.replace(base.params, **g) for g in grid}
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        chained = [chain.decode(h).codes for h in case.halves]
        lods = [logodds(h) for h in case.halves]
        for name, p in rules.items():
            codes = [_rules(c, h, p, lo) for c, h, lo in zip(chained, case.halves, lods)]
            if p == base.params:
                assert all(np.array_equal(c, base.decode(h).codes) for c, h in zip(codes[:2], case.halves))
            f1, n = score.spell_f1(case.layout, case.gt, codes, runs)
            rows.append({"group": group, "world": world, "variant": name, "spell_f1": f1,
                         "floor": floor, "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out)


def fieldgrid(params, out, rhos, items, grid):
    """Like rulegrid, but each grid entry is a full Decoder.replace of PARAMS (emission fields included), so every
    arm decodes from scratch; held-out B games are not decoded."""
    base = Decoder.load(params)
    modelgrid({" ".join(f"{k}={v}" for k, v in g.items()) or "base": base.replace(**g) for g in grid}, out, rhos, items)


def modelgrid(models, out, rhos, items):
    """fieldgrid's table for named decoders MODELS."""
    s50, rows = bench.Smoother(50), []
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        for name, model in models.items():
            f1, n = score.spell_f1(case.layout, case.gt, [model.decode(h).codes for h in case.halves], runs)
            rows.append({"group": group, "world": world, "variant": name, "spell_f1": f1,
                         "floor": floor, "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out)


def e41_grid():
    """E41's arms: base, and the q_logit refitted with the relative-speed term (fit_logit rel=True, PFF-A only)."""
    w = fit_logit(rel=True)
    return [{}, {"q_logit_a": round(float(w[0]), 6), "q_logit_dist": round(float(w[1]), 6),
                 "q_logit_margin": round(float(w[2]), 6), "q_logit_rel": round(float(w[3]), 6)}]


def e60_grid():
    """E60's arms: base; the q_logit refitted with the goalward-ball term (fit_logit goal=True, PFF-A only); and
    that refit with handover_lag 10 and 5, since the term itself delays the switch at an interception."""
    w = fit_logit(goal=True)
    refit = {"q_logit_a": round(float(w[0]), 6), "q_logit_dist": round(float(w[1]), 6),
             "q_logit_margin": round(float(w[2]), 6), "q_logit_goal": round(float(w[3]), 6)}
    return [{}, refit, {**refit, "handover_lag": 10}, {**refit, "handover_lag": 5}]



E60_REFIT = {"q_logit_a": 1.794214, "q_logit_dist": -1.27255, "q_logit_margin": 1.088767, "q_logit_goal": -0.352173}
E61_GRID = [{}, E60_REFIT]


def e64_models(params, spell):
    """E64's arms on PARAMS: base; spell_logit SPELL (a JSON file of weights); and the goalward term in the split
    and inter forms (GOAL_FORMS), each refitted on PFF-A with fit_logit."""
    base = Decoder.load(params)
    models = {"base": base, "spell refit": base.replace(spell_logit=json.loads(Path(spell).read_text()))}
    for form in ("split", "inter"):
        models[f"goal {form}"] = goal_form_model(base, form, fit_logit(goal=form))
    return models


def e68_models(params, spell, cuts=(0.8, 0.7, 0.65), name="spell refit"):
    """E68's arms on PARAMS: base, and spell_logit SPELL (a JSON file of weights) at each spell_flip_p in CUTS.
    E70 passes E69's touch weights with cuts 0.8, 0.75, 0.7 and 0.65."""
    base = Decoder.load(params)
    w = json.loads(Path(spell).read_text())
    return {"base": base, **{f"{name} p={p}": base.replace(spell_logit=w, spell_flip_p=p) for p in cuts}}


def e69_models(params, control, touch):
    """E69's arms on PARAMS at its own cut: base, and spell_logit refitted on the fixed loader from CONTROL (E30's
    feature set) and TOUCH (E31's, with touch_own and touch_other), each a JSON file of weights."""
    base = Decoder.load(params)
    load = lambda p: json.loads(Path(p).read_text())
    return {"base": base, "control refit": base.replace(spell_logit=load(control)),
            "touch refit": base.replace(spell_logit=load(touch))}


def e65_models(params):
    """E65's arms on PARAMS: base, and the goalward term in the oneint form (GOAL_FORMS) refitted on PFF-A."""
    base = Decoder.load(params)
    return {"base": base, "goal oneint": goal_form_model(base, "oneint", fit_logit(goal="oneint"))}


def e62_grid():
    """E62's arms: E60's grid refitted on PFF positions undoubled and interpolated to 25 Hz, plus E60's own weights
    (E60_REFIT, fitted on the nearest-frame resampling) for comparison."""
    base, refit, lag10, lag5 = e60_grid()
    return [base, refit, E60_REFIT, lag10, lag5]

LINE_GRID = [{}] + [{"dead_line_m": m, "dead_line_min_run": r} for r in (75, 50, 25) for m in (1.0, 2.0)]
LINE_LEAD_GRID = [{}] + [{"dead_line_m": m, "dead_line_min_run": r, "dead_line_lead_cut": 25}
                         for r in (100, 75) for m in (1.0, 2.0)]
LINE_FULL_GRID = [{}] + [{"dead_line_m": m, "dead_line_min_run": r, "dead_line_lead_cut": 50}
                         for r in (75, 50) for m in (1.0, 2.0)]
END_LEAD_GRID = [{}] + [{"dead_end_lead": f, "dead_end_live_mps": v} for v in (2.5, 2.0, 1.5) for f in (100, 50)]
RETURN_GRID = [{}] + [{"dead_return_m": m, "dead_return_min_run": r} for r in (375, 250) for m in (20.0, 10.0)]

SWITCH_GRID = [{}] + [{"switch_penalty": lam} for lam in (1, 2, 4, 8)] + \
    [{"switch_penalty": 8, "switch_free_at_dead": 1}, {"switch_penalty": 16},
     {"switch_penalty": 16, "switch_free_at_dead": 1}, {"switch_penalty": 32}]


def penalized_path(l, lam, free):
    """E27: the block labels maximising the summed log-posterior l (nb x 3: H, A, D) minus lam per change of team.
    States H, A, D after H, D after A; a team change into a block where free is True costs nothing. Ties keep the
    current state, then the lower index."""
    rows, free, nb = l.tolist(), free.tolist(), len(l)
    h, a, dh, da = rows[0][0], rows[0][1], rows[0][2], rows[0][2]
    back = [bytearray(nb) for _ in range(4)]
    bh, ba, bdh, bda = back
    for t in range(1, nb):
        lh, la, ld = rows[t]
        c = 0.0 if free[t] else lam
        best, arg = h, 0
        if a - c > best:
            best, arg = a - c, 1
        if dh > best:
            best, arg = dh, 2
        if da - c > best:
            best, arg = da - c, 3
        nh, bh[t] = best + lh, arg
        best, arg = a, 1
        if h - c > best:
            best, arg = h - c, 0
        if dh - c > best:
            best, arg = dh - c, 2
        if da > best:
            best, arg = da, 3
        na, ba[t] = best + la, arg
        ndh, bdh[t] = (h + ld, 0) if h > dh else (dh + ld, 2)
        nda, bda[t] = (a + ld, 1) if a > da else (da + ld, 3)
        h, a, dh, da = nh, na, ndh, nda
    final = [h, a, dh, da]
    s, out = final.index(max(final)), bytearray(nb)
    for t in range(nb - 1, 0, -1):
        out[t] = s
        s = back[s][t]
    out[0] = s
    return np.array([H, A, D, D], np.int8)[np.frombuffer(out, np.uint8)]


def _block_posterior(model, h):
    """The chain's block posterior P(H, A, D) over [kickoff, n) and that span's frame count, as decode builds them."""
    from possession.decoder import _chain, _forward_backward
    p, k0 = model.params, h.id.kickoff
    ev = model.emission.loglik(h)[k0:].astype(np.float64)
    m = ev.shape[0]
    return _forward_backward(p.temper * np.add.reduceat(ev, np.arange(0, m, p.stride), axis=0), _chain(p)), m


def _path_codes(model, h, g, m, lam, free):
    """penalized_path over g at lam, repeated by stride after a D head, then MODEL's rules."""
    from possession.decoder import _rules
    p, k0 = model.params, h.id.kickoff
    l = np.round(np.log(np.maximum(np.round(g, 9), 1e-12)), 12)
    path = penalized_path(l, lam, free)
    return _rules(np.concatenate([np.full(k0, D, np.int8), np.repeat(path, p.stride)[:m]]), h, p)


def _removed(base, codes):
    """Base H/A runs that carry another code on more than half their frames."""
    edges = np.flatnonzero(np.diff(base)) + 1
    return sum(1 for a, b in zip(np.r_[0, edges], np.r_[edges, len(base)])
               if base[a] != D and (codes[a:b] != base[a]).mean() > 0.5)


def switchpen(params, out, rhos, items, only=()):
    """E27: PARAMS's block posterior decoded by penalized_path at each SWITCH_GRID entry, then PARAMS's rules;
    ONLY keeps base and the named variants; held-out B games are not decoded."""
    from possession.decoder import _rules
    base, s50, rows = Decoder.load(params), bench.Smoother(50), []
    p = base.params
    grid = {" ".join(f"{k}={v}" for k, v in g.items()) or "base": g for g in SWITCH_GRID}
    grid = {name: g for name, g in grid.items() if name == "base" or not only or name in only}
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        codes, removed = {name: [] for name in grid}, dict.fromkeys(grid, 0)
        for h in case.halves:
            k0 = h.id.kickoff
            g, m = _block_posterior(base, h)
            chained = np.concatenate([np.full(k0, D, np.int8),
                                      np.repeat(np.round(g, 9).argmax(axis=1).astype(np.int8), p.stride)[:m]])
            shipped = _rules(chained, h, p)
            assert np.array_equal(shipped, base.decode(h).codes), h.id
            dead = _missing_run_dead(np.zeros(h.n, np.int8), h, p) == D
            assert np.array_equal(dead, _missing_run_dead(chained, h, p) == D), h.id
            free = np.add.reduceat(dead[k0:].astype(np.int64), np.arange(0, m, p.stride)) > 0
            for name, gi in grid.items():
                if not gi:
                    codes[name].append(shipped)
                    continue
                c = _path_codes(base, h, g, m, float(gi["switch_penalty"]),
                                free if gi.get("switch_free_at_dead") else np.zeros_like(free))
                codes[name].append(c)
                removed[name] += _removed(shipped, c)
        for name in grid:
            f1, n = score.spell_f1(case.layout, case.gt, codes[name], runs)
            rows.append({"group": group, "world": world, "variant": name, "spell_f1": f1,
                         "floor": floor, "margin": f1 - floor, "n_pred": n, "removed": removed[name]})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out)


def _team_runs(codes, k0):
    edges = np.flatnonzero(np.diff(codes[k0:])) + 1 + k0
    return [(int(a), int(b), int(codes[a])) for a, b in zip(np.r_[k0, edges], np.r_[edges, len(codes)])
            if codes[a] != D]


def spellmass(params, variants):
    """E27 diagnostic on PFF-A m0, not a gate: PARAMS's predicted possessions under 125 frames, matched when a
    labelled run of the same team overlaps at IoU >= 0.5, by length band and by tercile within the band of S, the
    summed log-odds of the possession's team over the other in the chain posterior; then, per variant, how many
    PARAMS possessions it removes and what share of those were matched."""
    from possession import pff
    base, games, rows = Decoder.load(params), [], []
    p = base.params
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        h = challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id)
        k0 = h.id.kickoff
        g, m = _block_posterior(base, h)
        post = np.vstack([np.tile([0.0, 0.0, 1.0], (k0, 1)), np.repeat(g, p.stride, axis=0)[:m]])
        logodds = np.log(np.maximum(post[:, 0], 1e-12)) - np.log(np.maximum(post[:, 1], 1e-12))
        shipped = base.decode(h).codes
        dead = _missing_run_dead(np.zeros(h.n, np.int8), h, p) == D
        free = np.add.reduceat(dead[k0:].astype(np.int64), np.arange(0, m, p.stride)) > 0
        arms = {}
        for v in variants:
            kv = dict(x.split("=") for x in v.split())
            arms[v] = _path_codes(base, h, g, m, float(kv["switch_penalty"]),
                                  free if kv.get("switch_free_at_dead") else np.zeros_like(free))
        gt = [(a, b, t) for a, b, t in _team_runs(c.labels, k0)]
        starts = np.array([a for a, _, _ in gt])
        for a, b, team in _team_runs(shipped, k0):
            near = gt[max(np.searchsorted(starts, a, "right") - 1, 0):np.searchsorted(starts, b)]
            iou = max(((min(b, y) - max(a, x)) / (max(b, y) - min(a, x)) for x, y, t in near if t == team and x < b
                       and y > a), default=0.0)
            s = float(logodds[a:b].sum() / p.stride) * (1 if team == HOME else -1)
            rows.append({"frames": b - a, "S": s, "matched": iou >= 0.5,
                         **{v: bool((arms[v][a:b] != team).mean() > 0.5) for v in variants}})
    t = pd.DataFrame(rows)
    short = t[t.frames < 125].copy()
    short["band"] = pd.cut(short.frames, [0, 30, 60, 125], right=False).astype(str)
    short["tercile"] = short.groupby("band").S.transform(lambda s: pd.qcut(s.rank(method="first"), 3,
                                                                              labels=["low", "mid", "high"]))
    print(f"{len(t)} predicted possessions, {t.matched.mean():.3f} matched; {len(short)} under 125 frames")
    print(short.groupby(["band", "tercile"], observed=True).agg(spells=("S", "size"), S_median=("S", "median"),
                                                                matched=("matched", "mean")).round(3).to_string())
    for v in variants:
        gone = t[t[v]]
        print(f"{v}: removes {len(gone)}, of which matched {gone.matched.mean():.3f}; "
              f"median length {gone.frames.median():.0f} frames")


def flag_runs(h, p):
    """_missing_run_dead's flags as it builds them, each bool [n]: (flagged, unseen, slow, walk, outside)."""
    z = np.zeros(h.n, bool)
    unseen, slow = h.nearest_team == NO_TEAM, z.copy()
    if p.dead_still_mps:
        for a, b in zip(*_runs(h.geometry.speed_mps < p.dead_still_mps)):
            if b - a >= p.dead_still_frames:
                slow[a:b] = True
    walk = h.pace_mps < p.dead_pace_still_mps if p.dead_pace_still_mps else z
    outside = h.geometry.outside_m > p.dead_outside_m if p.dead_outside_m else z
    flagged = unseen | slow | walk | outside
    if p.dead_pace_live_mps:
        flagged = flagged & ~(h.pace_mps > p.dead_pace_live_mps)
    return flagged, unseen, slow, walk, outside


def veto_dead(codes, h, p, runs, veto):
    """_missing_run_dead over the flagged RUNS, except that a run whose start is in VETO adds no D: it is skipped
    inside the run loop, before dead_close, so its frames keep the filled team."""
    kickoff, n = h.id.kickoff, h.n
    team = codes.copy()
    called = np.flatnonzero(team != D)
    if len(called):
        last = np.maximum.accumulate(np.where(team != D, np.arange(n), -1))
        team = np.where(last >= 0, team[np.maximum(last, 0)], team[called[0]]).astype(np.int8)
    dead = np.zeros(n + 1, dtype=np.int32)
    for start, stop in runs:
        if start in veto:
            continue
        lo = start + p.dead_trim if start > 0 else -p.dead_min_run
        hi = stop - p.dead_trim if stop < n else n + p.dead_min_run
        if hi - lo >= p.dead_min_run - 2 * p.dead_trim and min(hi, n) > max(lo, 0):
            dead[max(lo, 0)] += 1
            dead[min(hi, n)] -= 1
    out = np.where(np.cumsum(dead[:n]) > 0, D, team).astype(np.int8)
    out[:kickoff] = D
    if p.dead_close:
        for start, stop in zip(*_runs(out != D)):
            if start > kickoff and stop < n and stop - start < p.dead_close:
                out[start:stop] = D
    return out


def census_kinds(gt, pred, runs):
    """census()'s kind for each labelled possession of GT under PRED (both assembled)."""
    spells = score.possession_spells(pred, runs)
    starts = np.array([a for a, _, _ in spells])
    kinds = []
    for a, b, c in score.possession_spells(gt, runs):
        seg = pred[a:b]
        same = [(x, y) for x, y, k in spells[max(np.searchsorted(starts, a, "right") - 1, 0):
                                             np.searchsorted(starts, b)] if k == c and x < b and y > a]
        iou = max(((min(b, y) - max(a, x)) / (max(b, y) - min(a, x)) for x, y in same), default=0.0)
        if iou >= 0.5:
            kinds.append("matched")
        elif (seg == c).sum() * 2 < b - a:
            kinds.append("dead" if (seg == D).sum() >= ((seg != c) & (seg != D)).sum() else "wrong_team")
        else:
            kinds.append("fragmented" if len(same) > 1 else "overlong")
    return kinds


def native_a():
    """(world, PFF-A pooled Case, its halves' labels, its per-game Cases) per native PFF world, m0 first; B games
    are dropped before any decode."""
    worlds = bench.dev_worlds(NATIVE, (2.6,), seeds=(0,))
    for world, cases in sorted(worlds.items(), key=lambda kv: "_m2_" in kv[0]):
        case = bench.pooled(cases)
        games = list(dict.fromkeys(h.id.match for h in case.halves))
        keep = set(games[0::2])
        labels = case.layout.cut(case.gt)
        idx = [i for i, h in enumerate(case.halves) if h.id.match in keep]
        sub = bench._dev_cases([labels[i] for i in idx], [case.halves[i] for i in idx])
        yield world, bench.pooled(sub), [labels[i] for i in idx], [c for c in sub if c.name != "dev_pooled"]


def paired_delta(per_game, variants):
    """Per-game paired spellF1 delta of each variant over base on PFF-A m0: mean [90% t interval], games won."""
    g = pd.DataFrame(per_game).pivot_table(index=["base", "game"], columns="variant", values="spell_f1")
    print("\nper-game paired delta on PFF-A m0, mean [90% t interval], games won")
    for bname, w in g.groupby(level="base"):
        for name in variants:
            d = (w[name] - w["base"]).to_numpy()
            hw = T90 * d.std(ddof=1) / np.sqrt(len(d))
            print(f"  {bname} {name}: {d.mean():+.4f} [{d.mean() - hw:+.4f}, {d.mean() + hw:+.4f}] "
                  f"{(d > 0).sum()}/{len(d)}")


VETO_SETS = {"A": lambda r: r.y < 0.2, "B": lambda r: ~r.has_D,
             "A_g": lambda r: (r.y < 0.2) & r.guarded, "B_g": lambda r: ~r.has_D & r.guarded}


def deadruns(params, base9):
    """E28 oracle, label-reading and never a candidate: on native PFF-A m0 and m2, each interior flagged run of
    126+ frames is vetoed (adds no D) when the m0 labels say so (VETO_SETS: A, labelled-D share of the trimmed span
    under 0.2; B, no labelled-D stretch of 25+ frames there; _g, only runs with no slow or outside frame and finite
    pace on half their frames). One veto set per half serves both worlds and both bases (PARAMS and BASE9)."""
    from possession.decoder import _lag_handovers, _merge_spells, _push_flip
    s50 = bench.Smoother(50)
    bases = {}
    for path in (params, base9):
        m = Decoder.load(path)
        chain = m.replace(dead_min_run=0, dead_trim=0, dead_close=0, dead_outside_m=0.0, dead_still_mps=0.0,
                          dead_still_frames=0, dead_pace_still_mps=0.0, dead_pace_live_mps=0.0, handover_lag=0,
                          spell_merge_frames=0, spell_merge_tails=0, spell_push_mps=0.0, spell_push_frames=0,
                          spell_push_between=0, spell_push_unseen=0.0)
        bases[Path(path).stem] = (m, chain)
    p = next(iter(bases.values()))[0].params
    assert all(getattr(m.params, f) == getattr(p, f) for m, _ in bases.values() for f in
               ("dead_min_run", "dead_trim", "dead_close", "dead_still_mps", "dead_still_frames",
                "dead_pace_still_mps", "dead_pace_live_mps", "dead_outside_m")), "bases must share the dead flags"
    table, vetoes, rows, per_game, census_rows, false_d, edge_runs = [], {}, [], [], {}, [0, 0], 0
    for world, pooled_a, labs, games_a in native_a():
        halves = pooled_a.halves
        m0 = "_m0_" in world
        flags = {}
        for h, lab in zip(halves, labs):
            key = (h.id.match, h.id.half)
            flagged, unseen, slow, walk, outside = flag_runs(h, p)
            runs = list(zip(*_runs(flagged)))
            flags[key] = runs
            if not m0:
                continue
            edge_runs += sum(1 for s, e in runs if (s == 0 or e == h.n) and e - s >= p.dead_min_run - 2 * p.dead_trim)
            t = p.dead_trim
            for s, e in runs:
                if not (s > 0 and e < h.n and e - s >= p.dead_min_run):
                    continue
                span = lab[s + t:e - t] == D
                pace = h.pace_mps[s:e].astype(np.float64)
                fin = pace[np.isfinite(pace)]
                table.append({"key": key, "s": int(s), "e": int(e), "frames": int(e - s), "y": span.mean(),
                              "has_D": any(b - a >= 25 for a, b in zip(*_runs(span))),
                              "guarded": bool(not slow[s:e].any() and not outside[s:e].any()
                                              and np.isfinite(pace).mean() >= 0.5),
                              "pace": float(np.median(fin)) if len(fin) else np.nan,
                              "false_d": int((~span).sum()), "unseen": unseen[s:e].mean(), "walk": walk[s:e].mean(),
                              "slow": slow[s:e].mean(), "outside": outside[s:e].mean()})
        if m0:
            t = pd.DataFrame(table)
            for name, rule in VETO_SETS.items():
                chosen = t[rule(t)]
                vetoes[name] = {k: set(g.s) for k, g in chosen.groupby("key")}
        runs_ = score.valid_runs(pooled_a.gt)
        floor, _ = score.spell_f1(pooled_a.layout, pooled_a.gt, [s50.decode(h).codes for h in halves], runs_)
        for bname, (model, chain) in bases.items():
            bp = model.params
            chained = [chain.decode(h).codes for h in halves]
            variants = {}
            for name in ["base"] + list(VETO_SETS):
                codes = []
                for c, h in zip(chained, halves):
                    key = (h.id.match, h.id.half)
                    x = veto_dead(c, h, bp, flags[key], vetoes.get(name, {}).get(key, set()))
                    x = _lag_handovers(_merge_spells(_push_flip(x, h, bp), bp.spell_merge_frames,
                                                    bp.spell_merge_tails), bp.handover_lag)
                    codes.append(x)
                variants[name] = codes
            assert all(np.array_equal(c, model.decode(h).codes) for c, h in zip(variants["base"], halves)), bname
            gt_cut = labs
            for name, codes in variants.items():
                sc = score.evaluate(pooled_a.layout, pooled_a.gt, codes)
                base_codes = variants["base"]
                relab = sum(int((c != b).sum()) for c, b in zip(codes, base_codes))
                made_live = sum(int(((b == D) & (c != D) & (g == D)).sum()) for c, b, g in zip(codes, base_codes, gt_cut))
                nveto = sum(len(v) for v in vetoes.get(name, {}).values()) if name != "base" else 0
                rows.append({"base": bname, "world": world, "variant": name, "spell_f1": sc.spell_f1,
                             "margin": sc.spell_f1 - floor, "n_pred": sc.n_pred_spells, "macro_f1": sc.macro_f1,
                             "f1_d": sc.f1_d, "vetoed": nveto, "relabelled": relab, "labelled_d_made_live": made_live})
                if m0:
                    by_key = {(h.id.match, h.id.half): c for h, c in zip(halves, codes)}
                    for g in games_a:
                        gc = [by_key[(h.id.match, h.id.half)] for h in g.halves]
                        f1, _ = score.spell_f1(g.layout, g.gt, gc, score.valid_runs(g.gt))
                        per_game.append({"base": bname, "game": g.name, "variant": name, "spell_f1": f1})
            if m0 and bname == Path(params).stem:
                pa = {n: score._assemble_checked(pooled_a.layout, pooled_a.gt, variants[n]) for n in ("base", "B_g")}
                census_rows = {n: census_kinds(pooled_a.gt, v, runs_) for n, v in pa.items()}
                for h, lab, c in zip(halves, labs, variants["base"]):
                    key = (h.id.match, h.id.half)
                    fd = (c == D) & (lab != D)
                    fd[:h.id.kickoff] = False
                    inside = np.zeros(h.n, bool)
                    for s in vetoes["B"].get(key, ()):
                        e = next(e for s2, e in flags[key] if s2 == s)
                        inside[s + p.dead_trim:e - p.dead_trim] = True
                    false_d[0] += int(fd.sum())
                    false_d[1] += int((fd & inside).sum())
        print(world, flush=True)
    t = pd.DataFrame(table)
    t["ybin"] = pd.cut(t.y, [-1, 0, 0.2 - 1e-12, 0.8 - 1e-12, 1.0], labels=["0", "(0,0.2)", "[0.2,0.8)", "[0.8,1]"])
    print(f"\n1. interior qualifying runs on PFF-A m0: {len(t)} (half-edge runs {edge_runs}); "
          f"has_D false {int((~t.has_D).sum())}; guarded {int(t.guarded.sum())}")
    print(t.groupby("ybin", observed=True).agg(runs=("y", "size"), median_frames=("frames", "median"),
                                               false_d=("false_d", "sum"), guarded=("guarded", "mean"),
                                               median_pace=("pace", "median"),
                                               pace_under_1=("pace", lambda s: (s < 1).mean()),
                                               unseen=("unseen", "mean"), walk=("walk", "mean"),
                                               slow=("slow", "mean"), outside=("outside", "mean")).round(3).to_string())
    print(f"share of {Path(params).stem}'s false-D frames (PFF-A m0) inside trimmed spans of has_D-false runs: "
          f"{false_d[1]}/{false_d[0]} = {false_d[1] / max(false_d[0], 1):.3f}")
    r = pd.DataFrame(rows)
    ref = r[r.variant == "base"].set_index(["base", "world"]).spell_f1
    r["delta"] = r.spell_f1.to_numpy() - ref.loc[list(zip(r.base, r.world))].to_numpy()
    print("\n2. oracle table (PFF-A pooled; margin over smooth50)")
    print(r.round(4).to_string(index=False))
    paired_delta(per_game, VETO_SETS)
    k = pd.DataFrame({"base": census_rows["base"], "B_g": census_rows["B_g"]})
    print(f"\n3. census transitions on PFF-A m0, {Path(params).stem} base -> oracle B_g (labelled possessions)")
    print(pd.crosstab(k.base, k.B_g).to_string())
    left = k[(k.base == "dead") & (k.B_g != "dead")]
    print(f"left the dead class: {len(left)}; to matched {int((left.B_g == 'matched').sum())}; "
          f"entered dead: {int(((k.base != 'dead') & (k.B_g == 'dead')).sum())}")
    low = t[t.y < 0.2]
    conv = (low.pace < 1) | (low.slow > 0) | (low.outside > 0)
    print(f"\n4. convention: of {len(low)} runs with y < 0.2, median pace under 1 m/s {(low.pace < 1).mean():.3f}, "
          f"a slow or outside frame {((low.slow > 0) | (low.outside > 0)).mean():.3f}, either {conv.mean():.3f}")


FLIP_POPS = {"seen": lambda share: share >= 0.5, "unseen": lambda share: share < 0.5, "all": lambda share: True}


def flipruns(params, frames=250):
    """Label-reading ceiling of any rule that gives short possessions to the other team, never a candidate: on
    native PFF-A m0 and m2, PARAMS's codes after its push flip and before its lag; left to right, each team run
    under FRAMES of a FLIP_POPS population (share of frames with a token) is flipped when that raises the half's
    mean matched count over SPELL_IOUS minus F/2 per predicted spell (F = the world's base spellF1, so the step
    is the sign of the pooled spellF1 change), each world on its own labels."""
    from possession.decoder import _lag_handovers, _merge_spells, _push_flip
    model, rows, per_game = Decoder.load(params), [], []
    p = model.params
    chain = model.replace(dead_min_run=0, dead_trim=0, dead_close=0, dead_outside_m=0.0, dead_still_mps=0.0,
                          dead_still_frames=0, dead_pace_still_mps=0.0, dead_pace_live_mps=0.0, handover_lag=0,
                          spell_merge_frames=0, spell_merge_tails=0, spell_push_mps=0.0, spell_push_frames=0,
                          spell_push_between=0, spell_push_unseen=0.0)
    lag = lambda x: _lag_handovers(x, p.handover_lag)
    for world, pooled_a, labs, games_a in native_a():
        halves = pooled_a.halves
        pre = [_merge_spells(_push_flip(_missing_run_dead(chain.decode(h).codes, h, p), h, p),
                             p.spell_merge_frames, p.spell_merge_tails) for h in halves]
        assert all(np.array_equal(lag(c), model.decode(h).codes) for c, h in zip(pre, halves))
        f_base, _ = score.spell_f1(pooled_a.layout, pooled_a.gt, [lag(c) for c in pre], score.valid_runs(pooled_a.gt))

        def value(lab, codes):
            s = score.pm.spell_scores(lab, codes, [(0, len(lab))])
            return np.mean([v["n_matched"] for v in s["per_iou"].values()]) - f_base / 2 * s["n_pred"]

        variants, flips = {"base": [lag(c) for c in pre]}, dict.fromkeys(FLIP_POPS, 0)
        for name, keep in FLIP_POPS.items():
            out = []
            for c, h, lab in zip(pre, halves, labs):
                cur, best = c.copy(), value(lab, lag(c))
                for a, b, team in _team_runs(c, h.id.kickoff):
                    if b - a >= frames or not keep((h.nearest_team[a:b] != NO_TEAM).mean()):
                        continue
                    trial = cur.copy()
                    trial[a:b] = 1 - team
                    v = value(lab, lag(trial))
                    if v > best:
                        cur, best = trial, v
                        flips[name] += 1
                out.append(lag(cur))
            variants[name] = out
        runs_ = score.valid_runs(pooled_a.gt)
        for name, codes in variants.items():
            f1, n = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs_)
            rows.append({"world": world, "variant": name, "spell_f1": f1, "delta": f1 - f_base, "n_pred": n,
                         "flipped": flips.get(name, 0)})
            if "_m0_" in world:
                by_key = {(h.id.match, h.id.half): x for h, x in zip(halves, codes)}
                for g in games_a:
                    gc = [by_key[(h.id.match, h.id.half)] for h in g.halves]
                    per_game.append({"base": Path(params).stem, "game": g.name, "variant": name,
                                     "spell_f1": score.spell_f1(g.layout, g.gt, gc, score.valid_runs(g.gt))[0]})
        print(world, flush=True)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    paired_delta(per_game, FLIP_POPS)


def flipindep(params, frames=250):
    """Label-reading, never a candidate: does the spell flip's per-run target hold flipruns' ceiling? On native
    PFF-A m0 and m2 with PARAMS's codes before its spell flip and lag (_pre_lag): flip every FLIP_POPS run under
    FRAMES whose flip alone raises the half's matched-minus-F/2 value on the world's labels, all at once on the
    pre-flip codes (indep, the target spellflip fits and _spell_flip applies), against flipruns' greedy left-to-right
    oracle on the same codes (seq); with no flip and PARAMS's own codes for reference."""
    from possession.decoder import _lag_handovers
    model, rows, per_game = Decoder.load(params), [], []
    p, chain = model.params, _rules_off(model)
    lag = lambda x: _lag_handovers(x, p.handover_lag)
    for world, pooled_a, labs, games_a in native_a():
        halves = pooled_a.halves
        pre = [_pre_lag(model, chain, h)[0] for h in halves]
        runs_ = score.valid_runs(pooled_a.gt)
        f_base, _ = score.spell_f1(pooled_a.layout, pooled_a.gt, [lag(c) for c in pre], runs_)

        def value(lab, codes):
            s = score.pm.spell_scores(lab, codes, [(0, len(lab))])
            return np.mean([v["n_matched"] for v in s["per_iou"].values()]) - f_base / 2 * s["n_pred"]

        variants = {"no flip": [lag(c) for c in pre], Path(params).stem: [model.decode(h).codes for h in halves]}
        counts = {}
        for name, keep in FLIP_POPS.items():
            ind, seq, k_ind, k_seq, both = [], [], 0, 0, 0
            for c, h, lab in zip(pre, halves, labs):
                v0, picked = value(lab, lag(c)), []
                cur, best = c.copy(), v0
                for a, b, team in _team_runs(c, h.id.kickoff):
                    if b - a >= frames or not keep((h.nearest_team[a:b] != NO_TEAM).mean()):
                        continue
                    alone = c.copy()
                    alone[a:b] = 1 - team
                    if value(lab, lag(alone)) > v0:
                        picked.append((a, b, team))
                    trial = cur.copy()
                    trial[a:b] = 1 - team
                    v = value(lab, lag(trial))
                    if v > best:
                        cur, best, k_seq = trial, v, k_seq + 1
                        both += bool(picked and picked[-1][0] == a)
                new = c.copy()
                for a, b, team in picked:
                    new[a:b] = 1 - team
                k_ind += len(picked)
                ind.append(lag(new))
                seq.append(lag(cur))
            variants[f"indep {name}"], variants[f"seq {name}"] = ind, seq
            counts[f"indep {name}"], counts[f"seq {name}"] = k_ind, (k_seq, both)
        for name, codes in variants.items():
            f1, n = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs_)
            k = counts.get(name, 0)
            rows.append({"world": world, "variant": name, "spell_f1": f1, "delta": f1 - f_base, "n_pred": n,
                         "flipped": k[0] if isinstance(k, tuple) else k,
                         "also_indep": k[1] if isinstance(k, tuple) else ""})
            if "_m0_" in world:
                by_key = {(h.id.match, h.id.half): x for h, x in zip(halves, codes)}
                for g in games_a:
                    gc = [by_key[(h.id.match, h.id.half)] for h in g.halves]
                    per_game.append({"base": "no flip", "game": g.name, "variant": name,
                                     "spell_f1": score.spell_f1(g.layout, g.gt, gc, score.valid_runs(g.gt))[0]})
        print(world, flush=True)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    g = pd.DataFrame(per_game).pivot_table(index="game", columns="variant", values="spell_f1")
    print("\nper-game paired delta over no flip on PFF-A m0, mean [90% t interval], games won")
    for name in g.columns.drop("no flip"):
        d = (g[name] - g["no flip"]).to_numpy()
        hw = T90 * d.std(ddof=1) / np.sqrt(len(d))
        print(f"  {name}: {d.mean():+.4f} [{d.mean() - hw:+.4f}, {d.mean() + hw:+.4f}] {(d > 0).sum()}/{len(d)}")


def _resolve_adjacent(runs_gain):
    """From (a, b, team, gain) runs, keep runs in descending gain (ties by start) while neither run sharing a
    boundary with it is kept."""
    kept, starts, stops = [], set(), set()
    for a, b, team, gain in sorted(runs_gain, key=lambda r: (-r[3], r[0])):
        if a in stops or b in starts:
            continue
        kept.append((a, b, team))
        starts.add(a)
        stops.add(b)
    return kept


def flippairs(params, frames=250):
    """Adjacent co-flips, two parts on native PFF-A with PARAMS's pre-flip codes. Label-free: of the runs the
    decoder's own spell logit flips at cut 0.8 and 0.75, the share whose neighbour run is flipped too. Label-reading,
    never a candidate: flipindep's seen population, the independent set (each run whose flip alone helps), the same
    set with adjacent members resolved to the higher single-run gain (_resolve_adjacent), and the greedy oracle."""
    from possession.decoder import _SEEN, _lag_handovers, _spell_runs, _spell_z
    model, rows, per_game = Decoder.load(params), [], []
    p, chain = model.params, _rules_off(model)
    lag = lambda x: _lag_handovers(x, p.handover_lag)
    for world, pooled_a, labs, games_a in native_a():
        halves = pooled_a.halves
        pres = [_pre_lag(model, chain, h) for h in halves]
        if "_m0_" in world:
            for cut in (0.8, 0.75):
                zc, n, paired = round(np.log(cut / (1 - cut)), 6), 0, 0
                for h, (pre, lo) in zip(halves, pres):
                    fl = [(a, b) for a, b, t, x in _spell_runs(pre, h, p.spell_flip_frames, lo)
                          if x[_SEEN] >= p.spell_flip_seen and _spell_z(x, p.spell_logit) >= zc]
                    st, sp = {a for a, _ in fl}, {b for _, b in fl}
                    n += len(fl)
                    paired += sum(a in sp or b in st for a, b in fl)
                print(f"label-free, cut {cut}: the decoder flips {n} runs on PFF-A, {paired} ({paired / max(n, 1):.3f}) "
                      "next to another flipped run")
        pres = [c for c, _ in pres]
        runs_ = score.valid_runs(pooled_a.gt)
        f_base, _ = score.spell_f1(pooled_a.layout, pooled_a.gt, [lag(c) for c in pres], runs_)

        def value(lab, codes):
            s = score.pm.spell_scores(lab, codes, [(0, len(lab))])
            return np.mean([v["n_matched"] for v in s["per_iou"].values()]) - f_base / 2 * s["n_pred"]

        variants = {"no flip": [lag(c) for c in pres]}
        for k in ("indep", "resolved", "seq"):
            variants[k] = []
        n_adj, n_ind, n_res, n_seq = 0, 0, 0, 0
        for c, h, lab in zip(pres, halves, labs):
            v0, helps = value(lab, lag(c)), []
            cur, best = c.copy(), v0
            for a, b, team in _team_runs(c, h.id.kickoff):
                if b - a >= frames or not FLIP_POPS["seen"]((h.nearest_team[a:b] != NO_TEAM).mean()):
                    continue
                alone = c.copy()
                alone[a:b] = 1 - team
                g = value(lab, lag(alone)) - v0
                if g > 0:
                    helps.append((a, b, team, g))
                trial = cur.copy()
                trial[a:b] = 1 - team
                v = value(lab, lag(trial))
                if v > best:
                    cur, best, n_seq = trial, v, n_seq + 1
            st, sp = {r[0] for r in helps}, {r[1] for r in helps}
            n_adj += sum(a in sp or b in st for a, b, _, _ in helps)
            res = _resolve_adjacent(helps)
            for name, chosen in (("indep", [r[:3] for r in helps]), ("resolved", res)):
                new = c.copy()
                for a, b, team in chosen:
                    new[a:b] = 1 - team
                variants[name].append(lag(new))
            n_ind, n_res = n_ind + len(helps), n_res + len(res)
            variants["seq"].append(lag(cur))
        counts = {"indep": n_ind, "resolved": n_res, "seq": n_seq}
        print(f"{world}: {n_ind} runs help alone, {n_adj} of them next to another such run; resolved keeps {n_res}",
              flush=True)
        for name, codes in variants.items():
            f1, n = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs_)
            rows.append({"world": world, "variant": name, "spell_f1": f1, "delta": f1 - f_base, "n_pred": n,
                         "flipped": counts.get(name, 0)})
            if "_m0_" in world:
                by_key = {(h.id.match, h.id.half): x for h, x in zip(halves, codes)}
                for g in games_a:
                    gc = [by_key[(h.id.match, h.id.half)] for h in g.halves]
                    per_game.append({"base": "no flip", "game": g.name, "variant": name,
                                     "spell_f1": score.spell_f1(g.layout, g.gt, gc, score.valid_runs(g.gt))[0]})
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    g = pd.DataFrame(per_game).pivot_table(index="game", columns="variant", values="spell_f1")
    d = (g["resolved"] - g["indep"]).to_numpy()
    hw = T90 * d.std(ddof=1) / np.sqrt(len(d))
    print(f"\nresolved - indep, PFF-A m0 per game: {d.mean():+.4f} [{d.mean() - hw:+.4f}, {d.mean() + hw:+.4f}] "
          f"{(d > 0).sum()}/{len(d)}")


SPELL_CUTS = (0.8, 0.65, 0.5)
SPELL_FRAMES = 250
SPELL_ARMS = [("seen", 0.8), ("all", 0.8), ("seen", 0.65), ("all", 0.65), ("seen", 0.5), ("all", 0.5)]
SPELL_SEEN = {"seen": 0.5, "all": 0.0}


def _rules_off(model):
    return model.replace(dead_min_run=0, dead_trim=0, dead_close=0, dead_outside_m=0.0, dead_still_mps=0.0,
                         dead_still_frames=0, dead_pace_still_mps=0.0, dead_pace_live_mps=0.0, handover_lag=0,
                         spell_merge_frames=0, spell_merge_tails=0, spell_push_mps=0.0, spell_push_frames=0,
                         spell_push_between=0, spell_push_unseen=0.0, spell_flip_p=0.0, spell_flip_frames=0,
                         spell_flip_seen=0.0, spell_logit={}, dead_lead_cut=0, dead_out_lead_cut=0, dead_out_min_run=0,
                         spell_flip_adjacent=False)


def _pre_lag(model, chain, h):
    """MODEL's codes before its spell flip and lag, and the chain's frame log-odds as decode builds them."""
    from possession.decoder import _frame_logodds, _merge_spells, _push_flip
    p = model.params
    pre = _merge_spells(_push_flip(_missing_run_dead(chain.decode(h).codes, h, p), h, p),
                        p.spell_merge_frames, p.spell_merge_tails)
    g, m = _block_posterior(model, h)
    return pre, _frame_logodds(g, h, p.stride, m)


def ridge_newton(x, y, lam=1.0, steps=50, s=None):
    """Logistic weights on raw features X (column 0 the intercept), fitted on standardised columns with a ridge
    LAM on every weight but the intercept, each row weighted by S (default 1); raises unless the step falls under
    1e-8."""
    s = np.ones(len(x)) if s is None else s
    mu, sd = x[:, 1:].mean(axis=0), x[:, 1:].std(axis=0)
    sd[sd == 0] = 1.0
    z = np.column_stack([np.ones(len(x)), (x[:, 1:] - mu) / sd])
    w, ridge = np.zeros(z.shape[1]), lam * np.eye(z.shape[1])
    ridge[0, 0] = 0.0
    for _ in range(steps):
        q = 1 / (1 + np.exp(-z @ w))
        dw = np.linalg.solve(z.T @ (z * (s * q * (1 - q))[:, None]) + ridge, z.T @ (s * (q - y)) + ridge @ w)
        w -= dw
        if np.abs(dw).max() < 1e-8:
            return np.r_[w[0] - (w[1:] / sd * mu).sum(), w[1:] / sd]
    raise RuntimeError("ridge_newton did not converge")


def auc(score_, y):
    r = pd.Series(score_).rank().to_numpy()
    pos = y.astype(bool)
    return (r[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum())


def _spell_weights(x, y, drop=()):
    """ridge_newton on X and Y without the DROP features, rounded to 4 places, as the spell_logit mapping decode
    reads; a dropped feature's weight is 0.0."""
    from possession.decoder import SPELL_FEATURES
    names = ("a",) + SPELL_FEATURES
    keep = [i for i, n in enumerate(names) if n not in drop]
    w = dict.fromkeys(names, 0.0)
    w.update(zip((names[i] for i in keep), (round(float(v), 4) for v in ridge_newton(x[:, keep], y))))
    return w


def _flipped(pre, rows, w, pop, cut):
    """_spell_flip's choice over ROWS with weights W at POP and CUT: the codes and the number of runs flipped."""
    from possession.decoder import _SEEN, _spell_z
    zc, out, n = round(np.log(cut / (1 - cut)), 6), pre.copy(), 0
    for a, b, team, x in rows:
        if x[_SEEN] >= SPELL_SEEN[pop] and _spell_z(x, w) >= zc:
            out[a:b] = 1 - team
            n += 1
    return out, n


SPELL_SPLITS = {"fully seen": lambda r, major: r[3][SPELL_FEATURES.index("seen")] == 1.0, "partly seen": lambda r, major: r[3][SPELL_FEATURES.index("seen")] < 1.0,
                "next to D": lambda r, major: r[3][SPELL_FEATURES.index("next_to_d")] == 1.0, "not next to D": lambda r, major: r[3][SPELL_FEATURES.index("next_to_d")] == 0.0,
                "to majority": lambda r, major: 1 - r[2] == major, "to minority": lambda r, major: 1 - r[2] != major}


def spellflip(params, out, drop=(), split=False):
    """E29 first gate, PFF-A only: a ridge logistic on decoder._spell_runs features (without DROP, E30) predicts
    whether giving a short possession to the other team alone raises the half's matched-minus-F/2 value on the m0
    labels; 2-fold game-OOF weights at SPELL_ARMS flip runs together on m0 and m2, the decoder's own rule; writes
    OUT-pff.csv (OOF margins over smooth50, for pick) and OUT-weights.json (the all-A fit per population)."""
    from possession.decoder import SPELL_FEATURES, _lag_handovers, _spell_runs
    model, s50 = Decoder.load(params), bench.Smoother(50)
    p, chain = model.params, _rules_off(model)
    lag = lambda x: _lag_handovers(x, p.handover_lag)
    by_world, table = {}, []
    for world, pooled_a, labs, games_a in native_a():
        halves, pres, rows_ = pooled_a.halves, [], []
        games = list(dict.fromkeys(h.id.match for h in halves))
        runs = score.valid_runs(pooled_a.gt)
        f_base, _ = score.spell_f1(pooled_a.layout, pooled_a.gt, [model.decode(h).codes for h in halves], runs)
        floor, _ = score.spell_f1(pooled_a.layout, pooled_a.gt, [s50.decode(h).codes for h in halves], runs)
        for h, lab in zip(halves, labs):
            pre, lo = _pre_lag(model, chain, h)
            assert np.array_equal(lag(pre), model.decode(h).codes), h.id
            rows = _spell_runs(pre, h, SPELL_FRAMES, lo)
            pres.append(pre)
            rows_.append(rows)
            if "_m0_" not in world:
                continue

            def value(codes):
                s = score.pm.spell_scores(lab, codes, [(0, len(lab))])
                return np.mean([v["n_matched"] for v in s["per_iou"].values()]) - f_base / 2 * s["n_pred"]

            v0 = value(lag(pre))
            for a, b, t, x in rows:
                trial = pre.copy()
                trial[a:b] = 1 - t
                table.append({"key": (h.id.match, h.id.half), "fold": games.index(h.id.match) % 2, "a": a,
                              "y": float(value(lag(trial)) > v0), **dict(zip(SPELL_FEATURES, x))})
        by_world[world] = (pooled_a, pres, rows_, games_a, floor)
        print(world, flush=True)
    t = pd.DataFrame(table)
    x_all, y_all = np.column_stack([np.ones(len(t)), t[list(SPELL_FEATURES)].to_numpy(np.float64)]), t.y.to_numpy()
    print(f"\n{len(t)} candidate runs on PFF-A m0, flip helps on {t.y.mean():.3f}; seen share >= 0.5 on "
          f"{(t.seen >= 0.5).mean():.3f}")
    print("univariate AUC: " + ", ".join(f"{f} {auc(t[f].to_numpy(), y_all):.3f}" for f in SPELL_FEATURES))
    masks = {pop: (t.seen >= SPELL_SEEN[pop]).to_numpy() for pop in SPELL_SEEN}
    folds = {pop: [_spell_weights(x_all[m & (t.fold != f).to_numpy()], y_all[m & (t.fold != f).to_numpy()], drop)
                   for f in (0, 1)] for pop, m in masks.items()}
    full = {pop: _spell_weights(x_all[m], y_all[m], drop) for pop, m in masks.items()}
    for pop, w in full.items():
        print(f"{pop}: all-A weights " + ", ".join(f"{k} {v:+.4f}" for k, v in w.items()))
    fold_of = {(k, a): f for k, a, f in zip(t.key, t.a, t.fold)}
    rows, per_game = [], []
    for world, (pooled_a, pres, rows_, games_a, floor) in by_world.items():
        runs = score.valid_runs(pooled_a.gt)
        variants, flips = {"base": [lag(c) for c in pres]}, {}
        for pop, cut in SPELL_ARMS:
            name, n, codes = f"{pop}>={cut}", 0, []
            for h, pre, rr in zip(pooled_a.halves, pres, rows_):
                key = (h.id.match, h.id.half)
                c = pre.copy()
                for fold in (0, 1):
                    sub_rows = [r for r in rr if fold_of[(key, r[0])] == fold]
                    flipped, k = _flipped(pre, sub_rows, folds[pop][fold], pop, cut)
                    mask = flipped != pre
                    c[mask] = flipped[mask]
                    n += k
                codes.append(lag(c))
            variants[name], flips[name] = codes, n
        for sub in SPELL_SPLITS if split else ():
            name, n, codes = f"seen>=0.8 {sub}", 0, []
            for h, pre, rr in zip(pooled_a.halves, pres, rows_):
                key, major = (h.id.match, h.id.half), int((h.nearest_team == A).sum() > (h.nearest_team == H).sum())
                c = pre.copy()
                for fold in (0, 1):
                    sub_rows = [r for r in rr if fold_of[(key, r[0])] == fold and SPELL_SPLITS[sub](r, major)]
                    flipped, k = _flipped(pre, sub_rows, folds["seen"][fold], "seen", 0.8)
                    mask = flipped != pre
                    c[mask] = flipped[mask]
                    n += k
                codes.append(lag(c))
            variants[name], flips[name] = codes, n
        f0 = None
        for name, codes in variants.items():
            f1, npred = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs)
            f0 = f1 if name == "base" else f0
            rows.append({"group": world + "_A", "world": world + "_A", "variant": name, "spell_f1": f1,
                         "floor": floor, "margin": f1 - floor, "delta": f1 - f0, "n_pred": npred,
                         "flipped": flips.get(name, 0)})
            if "_m0_" in world:
                by_key = {(h.id.match, h.id.half): x for h, x in zip(pooled_a.halves, codes)}
                for g in games_a:
                    gc = [by_key[(h.id.match, h.id.half)] for h in g.halves]
                    per_game.append({"base": Path(params).stem, "game": g.name, "variant": name,
                                     "spell_f1": score.spell_f1(g.layout, g.gt, gc, score.valid_runs(g.gt))[0]})
    r = pd.DataFrame(rows)
    print("\nOOF flips on PFF-A (oracle ceilings from flipruns: m0 seen +0.0413, all +0.0617)")
    print(r.drop(columns=["group"]).round(4).to_string(index=False))
    paired_delta(per_game, [n for n in r.variant.unique() if n != "base"])
    r.drop(columns=["delta", "flipped"]).to_csv(f"{out}-pff.csv", index=False, float_format="%.6f")
    Path(f"{out}-weights.json").write_text(json.dumps(full, indent=2, sort_keys=True) + "\n")
    print(f"{out}-pff.csv {out}-weights.json")


SPELL_BASE = ("len", "own_tok", "other_tok", "closest_own", "speed_med", "speed_max", "margin_own", "push", "logodds",
              "sandwiched", "prev_len", "next_len", "next_to_d")
SPELL_PAIRS = ("len", "own_tok", "closest_own", "speed_med", "margin_own", "push", "logodds", "sandwiched", "prev_len",
               "next_len")


def _span_share(pre, a, b):
    """ln(L / (L + P + N)) for the run [a, b) of PRE, P and N its team neighbours' lengths (0 for a D neighbour)."""
    edges = np.flatnonzero(np.diff(pre)) + 1
    starts, stops = np.r_[0, edges], np.r_[edges, len(pre)]
    k = int(np.searchsorted(starts, a))
    side = lambda j: stops[j] - starts[j] if 0 <= j < len(starts) and pre[starts[j]] != D else 0
    return float(np.log((b - a) / ((b - a) + side(k - 1) + side(k + 1))))


def spellmodel(params, cut=0.8):
    """E36 first gate, PFF-A only, zero decoder change: on PARAMS's pre-flip codes, the spell flip's runs (its
    frames and seen limits) with their single-run value change on m0 and on m2; 2-fold game-OOF arms R (refit of the
    shipped form: SPELL_BASE, 0/1 m0 target), W0 (R weighted by |d_m0| capped at 1, mean 1 per training fold), S (R
    plus span_share), X (R plus pairwise products of SPELL_PAIRS) and D (R without next_to_d and other_tok); each
    arm's runs flip together on the pre-flip codes, at CUT and at R's flip count, scored by pooled spellF1."""
    from possession.decoder import SPELL_FEATURES, _lag_handovers, _spell_runs
    model = Decoder.load(params)
    p, chain = model.params, _rules_off(model)
    lag = lambda x: _lag_handovers(x, p.handover_lag)
    col = {f: i for i, f in enumerate(SPELL_FEATURES)}
    worlds, recs = {}, {}
    for world, pooled_a, labs, games_a in native_a():
        halves = pooled_a.halves
        games = list(dict.fromkeys(h.id.match for h in halves))
        runs = score.valid_runs(pooled_a.gt)
        f13, _ = score.spell_f1(pooled_a.layout, pooled_a.gt, [model.decode(h).codes for h in halves], runs)
        pres = []
        for h, lab in zip(halves, labs):
            pre, lo = _pre_lag(model, chain, h)
            pres.append(pre)

            def value(codes):
                s = score.pm.spell_scores(lab, codes, [(0, len(lab))])
                return np.mean([v["n_matched"] for v in s["per_iou"].values()]) - f13 / 2 * s["n_pred"]

            v0 = value(lag(pre))
            for a, b, t, x in _spell_runs(pre, h, p.spell_flip_frames, lo):
                if x[col["seen"]] < p.spell_flip_seen:
                    continue
                trial = pre.copy()
                trial[a:b] = 1 - t
                key = (h.id.match, h.id.half, a)
                r = recs.setdefault(key, {"key": key, "b": b, "t": t, "fold": games.index(h.id.match) % 2,
                                          "span_share": _span_share(pre, a, b), **{f: x[col[f]] for f in SPELL_FEATURES}})
                assert r["b"] == b and r["t"] == t, key
                r["d_m2" if "_m2_" in world else "d_m0"] = value(lag(trial)) - v0
        worlds[world] = (pooled_a, pres, games_a, runs, f13)
        print(world, flush=True)
    t = pd.DataFrame(list(recs.values()))
    assert t[["d_m0", "d_m2"]].notna().all().all()
    y = (t.d_m0 > 0).to_numpy(np.float64)
    pairs = np.column_stack([t[f1] * t[f2] for f1, f2 in itertools.combinations(SPELL_PAIRS, 2)])
    base = t[list(SPELL_BASE)].to_numpy(np.float64)
    arms = {"R": base, "W0": base, "S": np.column_stack([base, t.span_share]), "X": np.column_stack([base, pairs]),
            "D": t[[f for f in SPELL_BASE if f not in ("next_to_d", "other_tok")]].to_numpy(np.float64)}
    fold = t.fold.to_numpy()
    print(f"\n{len(t)} judged runs on PFF-A; flip helps on m0 {y.mean():.3f}, on m2 {(t.d_m2 > 0).mean():.3f}; "
          f"univariate AUC span_share {auc(t.span_share.to_numpy(), y):.3f}")
    z = {}
    for name, feats in arms.items():
        x1 = np.column_stack([np.ones(len(t)), feats])
        z[name] = np.zeros(len(t))
        for f in (0, 1):
            tr = fold != f
            s = None
            if name == "W0":
                s = np.minimum(np.abs(t.d_m0.to_numpy()[tr]), 1.0)
                s = s / s.mean()
                print(f"W0 fold {f}: effective sample {s.sum() ** 2 / (s ** 2).sum():.0f} of {tr.sum()}")
            w = ridge_newton(x1[tr], y[tr], s=s)
            z[name][~tr] = x1[~tr] @ w
        print(f"{name}: OOF AUC {auc(z[name], y):.3f}")
    zc = np.log(cut / (1 - cut))
    k_r = int((z["R"] >= zc).sum())
    picks = {"no flip": np.zeros(len(t), bool)}
    top = lambda name, k: np.isin(np.arange(len(t)), np.argsort(-z[name], kind="stable")[:k])
    for name in arms:
        picks[f"{name}@{cut}"] = z[name] >= zc
        picks[f"{name}#{k_r}"] = top(name, k_r)
    for name in arms:
        k = int(picks[f"{name}@{cut}"].sum())
        if k != k_r:
            picks[f"R#{k}"] = top("R", k)
    rows, per_game = [], []
    for world, (pooled_a, pres, games_a, runs, f13) in worlds.items():
        dcol = "d_m2" if "_m2_" in world else "d_m0"
        idx = {(h.id.match, h.id.half): i for i, h in enumerate(pooled_a.halves)}
        variants = {Path(params).stem: [model.decode(h).codes for h in pooled_a.halves]}
        for name, sel in picks.items():
            codes = [c.copy() for c in pres]
            for (m, hh, a), b, team in zip(t.key[sel], t.b[sel], t.t[sel]):
                codes[idx[(m, hh)]][a:b] = 1 - team
            variants[name] = [lag(c) for c in codes]
        for name, codes in variants.items():
            f1, n = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs)
            sel = picks.get(name)
            rows.append({"world": world, "variant": name, "spell_f1": f1, "delta_v13": f1 - f13, "n_pred": n,
                         "flipped": int(sel.sum()) if sel is not None else "",
                         "captured": round(float(t[dcol][sel].sum()), 2) if sel is not None else ""})
            if "_m0_" in world:
                by_key = {(h.id.match, h.id.half): c for h, c in zip(pooled_a.halves, codes)}
                for g in games_a:
                    gc = [by_key[(h.id.match, h.id.half)] for h in g.halves]
                    per_game.append({"base": "R", "game": g.name, "variant": name,
                                     "spell_f1": score.spell_f1(g.layout, g.gt, gc, score.valid_runs(g.gt))[0]})
    r = pd.DataFrame(rows)
    print("\nOOF flips on PFF-A, all arms judged on the same pre-flip codes")
    print(r.round(5).to_string(index=False))
    g = pd.DataFrame(per_game).pivot_table(index="game", columns="variant", values="spell_f1")
    print("\nper-game paired delta against R at the same operating point, PFF-A m0, mean [90% t interval], games won")
    for name in g.columns:
        ref = f"R@{cut}" if "@" in name else f"R#{k_r}" if "#" in name and not name.startswith("R#") else None
        if ref is None or name == ref:
            continue
        if f"R#{int(picks[name].sum())}" in g.columns and "@" in name and name != f"R@{cut}":
            d = (g[name] - g[f"R#{int(picks[name].sum())}"]).to_numpy()
            print(f"  {name} against R at its flip count: {d.mean():+.4f} [{d.mean() - T90 * d.std(ddof=1) / np.sqrt(len(d)):+.4f}, "
                  f"{d.mean() + T90 * d.std(ddof=1) / np.sqrt(len(d)):+.4f}] {(d > 0).sum()}/{len(d)}")
        d = (g[name] - g[ref]).to_numpy()
        hw = T90 * d.std(ddof=1) / np.sqrt(len(d))
        print(f"  {name}: {d.mean():+.4f} [{d.mean() - hw:+.4f}, {d.mean() + hw:+.4f}] {(d > 0).sum()}/{len(d)}")


ISLAND_MAX, ISLAND_BURST, ISLAND_ALT = 250, 10, {"temper": 0.3, "poss_mean_s": 2.0}


def _stretches(flag, lo, hi, min_len):
    """Maximal runs of FLAG inside [lo, hi) that touch neither edge, MIN_LEN to ISLAND_MAX - 1 frames long."""
    return [(lo + a, lo + b) for a, b in zip(*_runs(flag[lo:hi]))
            if a > 0 and lo + b < hi and min_len <= b - a < ISLAND_MAX]


def _bursts(tok, host, lo, hi, min_len):
    """Spans from the first to the last other-team token of each group of ISLAND_BURST+ such tokens with no host
    token between them, inside [lo, hi) without touching its edges, MIN_LEN to ISLAND_MAX - 1 frames long."""
    idx = np.flatnonzero(np.isin(tok[lo:hi], (host, 1 - host))) + lo
    out, k = [], 0
    while k < len(idx):
        if tok[idx[k]] != 1 - host:
            k += 1
            continue
        j = k
        while j + 1 < len(idx) and tok[idx[j + 1]] == 1 - host:
            j += 1
        a, b = int(idx[k]), int(idx[j]) + 1
        if j - k + 1 >= ISLAND_BURST and a > lo and b < hi and min_len <= b - a < ISLAND_MAX:
            out.append((a, b))
        k = j + 1
    return out


def islandruns(params):
    """E37 ceiling, label-reading, never a candidate: on native PFF-A m0 and m2, PARAMS's codes after its spell flip
    and before its lag; label-free island candidates strictly inside one team run, clear of runs the push or spell
    flip relabelled, from three generators (a: frames whose chain log-odds favour the other team; b: other-team
    runs of a second chain at ISLAND_ALT with no rules; c: bursts of ISLAND_BURST+ other-team tokens), at minimum
    lengths 75 and 50; left to right, an island takes the other team when that raises the half's matched-minus-F/2
    value; plus the perfect-island line (labelled possessions of 50 to 249 frames inside a run of the other team,
    at their labelled edges), each world on its own labels."""
    from possession.decoder import _lag_handovers, _spell_flip
    model, rows, per_game = Decoder.load(params), [], []
    p, chain = model.params, _rules_off(model)
    alt = chain.replace(**ISLAND_ALT)
    lag = lambda x: _lag_handovers(x, p.handover_lag)
    for world, pooled_a, labs, games_a in native_a():
        halves = pooled_a.halves
        posts, cands = [], []
        for h, lab in zip(halves, labs):
            pre, lo = _pre_lag(model, chain, h)
            post = _spell_flip(pre, h, p, lo)
            assert np.array_equal(lag(post), model.decode(h).codes), h.id
            relabelled = post != _missing_run_dead(chain.decode(h).codes, h, p)
            a_codes, tok = alt.decode(h).codes, h.nearest_team
            by = {}
            for a0, b0, host in _team_runs(post, h.id.kickoff):
                other = 1 - host
                flags = {"a": (lo * (1.0 if host == H else -1.0)) < 0, "b": a_codes == other}
                for m in (75, 50):
                    for gname in ("a", "b", "c"):
                        found = (_bursts(tok, host, a0, b0, m) if gname == "c"
                                 else _stretches(flags[gname], a0, b0, m))
                        by.setdefault(f"{gname}{m}", []).extend(
                            (a, b, host) for a, b in found if not relabelled[a:b].any())
                lab_runs = [(a0 + a, a0 + b) for a, b in zip(*_runs(lab[a0:b0] == other))]
                by.setdefault("perfect", []).extend(
                    (a, b, host) for a, b in lab_runs if a > a0 and b < b0 and 50 <= b - a < ISLAND_MAX)
            posts.append(post)
            cands.append({k: sorted(v) for k, v in by.items()})
        runs_ = score.valid_runs(pooled_a.gt)
        f13, _ = score.spell_f1(pooled_a.layout, pooled_a.gt, [lag(c) for c in posts], runs_)

        def value(lab, codes):
            s = score.pm.spell_scores(lab, codes, [(0, len(lab))])
            return np.mean([v["n_matched"] for v in s["per_iou"].values()]) - f13 / 2 * s["n_pred"]

        variants, counts = {"base": [lag(c) for c in posts]}, {}
        for name in ("perfect",) + tuple(f"{g}{m}" for m in (75, 50) for g in "abc"):
            out, k, n_c = [], 0, 0
            for c, lab, cd in zip(posts, labs, cands):
                cur, best = c.copy(), value(lab, lag(c))
                for a, b, host in cd.get(name, []):
                    n_c += 1
                    if (cur[a:b] != host).any():
                        continue
                    trial = cur.copy()
                    trial[a:b] = 1 - host
                    v = value(lab, lag(trial))
                    if v > best:
                        cur, best, k = trial, v, k + 1
                out.append(lag(cur))
            variants[name], counts[name] = out, (k, n_c)
        for name, codes in variants.items():
            f1, n = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs_)
            k, n_c = counts.get(name, (0, 0))
            rows.append({"world": world, "variant": name, "spell_f1": f1, "delta": f1 - f13, "n_pred": n,
                         "inserted": k, "candidates": n_c})
            if "_m0_" in world:
                by_key = {(h.id.match, h.id.half): x for h, x in zip(halves, codes)}
                for g in games_a:
                    gc = [by_key[(h.id.match, h.id.half)] for h in g.halves]
                    per_game.append({"base": Path(params).stem, "game": g.name, "variant": name,
                                     "spell_f1": score.spell_f1(g.layout, g.gt, gc, score.valid_runs(g.gt))[0]})
        print(world, flush=True)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    paired_delta(per_game, [n for n in dict.fromkeys(r["variant"] for r in rows) if n != "base"])


TTI_REACT_S, TTI_VMAX, TTI_STEP = 0.7, 5.0, 5
SPEED_BANDS, MARGIN_BANDS = [0, 2, 8, 1e9], [0, 1, 3, 1e9]


def _tti_token(g, seen):
    """Team of the slot with the smallest time to intercept the ball (Spearman 2018 as in Shaw's open
    implementation: reaction TTI_REACT_S along the slot's velocity over +-TTI_STEP frames, then TTI_VMAX m/s
    straight), NO_TEAM where the ball is not SEEN or no slot is present."""
    out = np.full(g.n, NO_TEAM, np.int8)
    xy = g.players_xy.astype(np.float64)
    v = np.zeros_like(xy)
    k = TTI_STEP
    v[k:-k] = (xy[2 * k:] - xy[:-2 * k]) / (2 * k / FPS)
    v = np.nan_to_num(v)
    for lo in range(0, g.n, CHUNK):
        b = g.ball_xy[lo:lo + CHUNK].astype(np.float64)
        p = xy[lo:lo + CHUNK] + TTI_REACT_S * v[lo:lo + CHUNK]
        t = np.hypot(*(p - b[:, None, :]).transpose(2, 0, 1)) / TTI_VMAX
        t = np.where(np.isnan(t), np.inf, t)
        j = t.argmin(1)
        ok = seen[lo:lo + CHUNK] & np.isfinite(t[np.arange(len(j)), j])
        out[lo:lo + CHUNK] = np.where(ok, g.slot_team[j], NO_TEAM)
    return out


def ttitoken():
    """E39 gate, label-reading, no decode: on native PFF-A m0 seen alive frames after kickoff, how often the
    nearest-player token and the time-to-intercept token (_tti_token) name the labelled team, overall, where they
    disagree, and by ball speed and team margin bands."""
    from possession import pff
    games, rows = [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        h = challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id)
        tti = _tti_token(c.geometry, h.nearest_team != NO_TEAM)
        keep = (np.arange(h.n) >= h.id.kickoff) & (h.nearest_team != NO_TEAM) & np.isin(c.labels, (H, A))
        lab = c.labels[keep]
        rows.append(pd.DataFrame({"near": h.nearest_team[keep] == lab, "tti": tti[keep] == lab,
                                  "speed": np.digitize(h.geometry.speed_mps[keep], SPEED_BANDS[1:-1]),
                                  "margin": np.digitize(h.geometry.margin_m[keep], MARGIN_BANDS[1:-1])}))
    t = pd.concat(rows, ignore_index=True)
    dis = t.near != t.tti
    print(f"{len(t)} seen alive frames on {len(games[0::2])} PFF-A games: nearest right {t.near.mean():.4f}, "
          f"tti right {t.tti.mean():.4f}; they disagree on {dis.mean():.4f}, where tti is right on "
          f"{t.tti[dis].mean():.4f}")
    for col, bands in (("speed", SPEED_BANDS), ("margin", MARGIN_BANDS)):
        g = t.assign(dis=dis).groupby(col)
        print(pd.DataFrame({"band": [f"{bands[i]}-{bands[i + 1]}" for i in g.groups], "frames": g.size().values,
                            "nearest_right": g.near.mean().values, "tti_right": g.tti.mean().values,
                            "disagree": g.dis.mean().values,
                            "tti_right_when_disagree": [x.tti[x.dis].mean() for _, x in g]}).round(4).to_string(index=False))


def postd(params):
    """Restart-taker gate, label-reading: on native PFF-A m0 with PARAMS's final codes, each D stretch after kickoff
    that ends before the half does and is followed by a labelled team within 125 frames; how often the first team
    code after it is that labelled team, and how many team runs under 50 frames follow a D stretch and precede a
    run of the other team (post-D stubs)."""
    model, out = Decoder.load(params), []
    for world, pooled_a, labs, games_a in native_a():
        if "_m0_" not in world:
            continue
        stubs = 0
        for h, lab in zip(pooled_a.halves, labs):
            c = model.decode(h).codes
            for a, b in zip(*_runs(c == D)):
                a, b = int(a), int(b)
                if a <= h.id.kickoff or b >= h.n:
                    continue
                live = np.flatnonzero(np.isin(lab[b:b + 125], (H, A)))
                if len(live):
                    out.append({"right": int(c[b]) == int(lab[b + live[0]]), "lag": int(live[0])})
                k = b
                while k < h.n and c[k] == c[b]:
                    k += 1
                stubs += k - b < 50 and k < h.n and c[k] == 1 - c[b]
        t = pd.DataFrame(out)
        print(f"{world}: {len(t)} D stretches with a labelled team within 125 frames after; first team code after "
              f"the stretch is that team on {t.right.mean():.4f}; label goes live a median {t.lag.median():.0f} "
              f"frames after; post-D stubs {stubs}")


POSTFILL_ARMS = {"k50": 50, "k125": 125, "run": None}


def postfill(params):
    """Restart-taker ceiling, label-reading, never a candidate: on native PFF-A m0 and m2 with PARAMS's final codes,
    each D stretch after kickoff whose first team code is not the labelled team of the first live frame within 125
    frames after it; left to right, the first team run after the stretch takes that team over its first 50 or 125
    frames or whole (POSTFILL_ARMS) when that raises the half's matched-minus-F/2 value, each world on its labels."""
    model, rows, per_game = Decoder.load(params), [], []
    for world, pooled_a, labs, games_a in native_a():
        halves = pooled_a.halves
        base = [model.decode(h).codes for h in halves]
        runs_ = score.valid_runs(pooled_a.gt)
        f13, _ = score.spell_f1(pooled_a.layout, pooled_a.gt, base, runs_)

        def value(lab, codes):
            s = score.pm.spell_scores(lab, codes, [(0, len(lab))])
            return np.mean([v["n_matched"] for v in s["per_iou"].values()]) - f13 / 2 * s["n_pred"]

        cands = []
        for h, lab, c in zip(halves, labs, base):
            cc = []
            for a, b in zip(*_runs(c == D)):
                a, b = int(a), int(b)
                if a <= h.id.kickoff or b >= h.n:
                    continue
                live = np.flatnonzero(np.isin(lab[b:b + 125], (H, A)))
                if not len(live) or int(c[b]) == int(lab[b + live[0]]):
                    continue
                k = b + int(np.argmax(c[b:] != c[b])) if (c[b:] != c[b]).any() else h.n
                cc.append((b, k, int(lab[b + live[0]])))
            cands.append(cc)
        variants, counts = {"base": base}, {}
        for name, cap in POSTFILL_ARMS.items():
            out, n = [], 0
            for c, lab, cc in zip(base, labs, cands):
                cur, best = c.copy(), value(lab, c)
                for b, k, team in cc:
                    trial = cur.copy()
                    trial[b:k if cap is None else min(k, b + cap)] = team
                    v = value(lab, trial)
                    if v > best:
                        cur, best, n = trial, v, n + 1
                out.append(cur)
            variants[name], counts[name] = out, n
        for name, codes in variants.items():
            f1, npred = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs_)
            rows.append({"world": world, "variant": name, "spell_f1": f1, "delta": f1 - f13, "n_pred": npred,
                         "filled": counts.get(name, 0), "candidates": sum(map(len, cands))})
            if "_m0_" in world:
                by_key = {(h.id.match, h.id.half): x for h, x in zip(halves, codes)}
                for g in games_a:
                    gc = [by_key[(h.id.match, h.id.half)] for h in g.halves]
                    per_game.append({"base": Path(params).stem, "game": g.name, "variant": name,
                                     "spell_f1": score.spell_f1(g.layout, g.gt, gc, score.valid_runs(g.gt))[0]})
        print(world, flush=True)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    paired_delta(per_game, POSTFILL_ARMS)


RESTART_HOLD, RESTART_AFTER, CORNER_M, KICKOFF_M, CLEAR_M = 25, 50, 1.5, 1.0, 9.0


def _held(flag):
    """FLAG with only its runs of RESTART_HOLD+ frames kept."""
    out = np.zeros_like(flag)
    for a, b in zip(*_runs(flag)):
        if b - a >= RESTART_HOLD:
            out[a:b] = True
    return out


def _restart_triggers(g, lo, hi, throw_m):
    """{kind: (home fired, away fired)} over frames [lo, hi) of Geometry G, each a law-of-the-game configuration
    held RESTART_HOLD frames: throw-in, a team's slot more than THROW_M beyond a touchline; corner, a slot within
    CORNER_M of a corner point with no opponent within CLEAR_M of it; kick-off, a slot within KICKOFF_M of the
    centre mark, no opponent within CLEAR_M of the mark, and each team's slots on one side of halfway (1 m slack)."""
    xy = g.players_xy[lo:hi].astype(np.float64)
    length, width = g.pitch_m
    team = g.slot_team
    x, y = xy[..., 0], xy[..., 1]
    out = {}
    with np.errstate(invalid="ignore"):
        beyond = (y < -throw_m) | (y > width + throw_m)
        corners = np.array([(0, 0), (0, width), (length, 0), (length, width)], np.float64)
        dc = np.hypot(x[..., None] - corners[:, 0], y[..., None] - corners[:, 1])
        dmark = np.hypot(x - length / 2, y - width / 2)
        side = np.sign(x - length / 2)
        fired = {}
        for k in (HOME, AWAY):
            own, opp = team == k, team == 1 - k
            near_corner = (dc[:, own] < CORNER_M).any(1)
            opp_clear = ~(np.nan_to_num(dc[:, opp], nan=1e9).min(1) < CLEAR_M)
            corner = (near_corner & opp_clear).any(1)
            med_own = np.nanmedian(np.where(own, side, np.nan), axis=1)
            med_opp = np.nanmedian(np.where(opp, side, np.nan), axis=1)
            halves_ok = (np.nan_to_num((x[:, own] - length / 2) * med_own[:, None], nan=1.0) > -1).all(1) & \
                        (np.nan_to_num((x[:, opp] - length / 2) * med_opp[:, None], nan=1.0) > -1).all(1)
            kickoff = (np.nan_to_num(dmark[:, own], nan=1e9) < KICKOFF_M).any(1) & \
                      (np.nan_to_num(dmark[:, opp], nan=1e9) >= CLEAR_M).all(1) & halves_ok
            fired[k] = {"throw": _held(beyond[:, own].any(1)).any(), "corner": _held(corner).any(),
                        "kickoff": _held(kickoff).any()}
    return {kind: (fired[HOME][kind], fired[AWAY][kind]) for kind in ("throw", "corner", "kickoff")}


def restartdet(params):
    """Restart detector gate, label-reading for evaluation only: on native PFF-A m0, PARAMS's D stretches after
    kickoff followed by a labelled team within 125 frames (postd's population); per arm, the team a label-free
    trigger names over the stretch and RESTART_AFTER frames after it (no trigger when both teams fire), its fire
    share, its accuracy where it fires, and the decoder's first team code accuracy on the same stretches."""
    from possession import pff
    model, games, rows = Decoder.load(params), [], []
    for c in pff.load(metrica.RuleV2.parse("m0")):
        if c.id.match not in games:
            games.append(c.id.match)
        if games.index(c.id.match) % 2:
            continue
        seen = pff.native_seen(c)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        h = challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id)
        codes, lab, tok = model.decode(h).codes, c.labels, h.nearest_team
        out_ = np.nan_to_num(h.geometry.outside_m, nan=0.0) > 0.5
        for a, b in zip(*_runs(codes == D)):
            a, b = int(a), int(b)
            if a <= h.id.kickoff or b >= h.n:
                continue
            live = np.flatnonzero(np.isin(lab[b:b + 125], (H, A)))
            if not len(live):
                continue
            hi = min(b + RESTART_AFTER, h.n)
            r = {"truth": int(lab[b + live[0]]), "v13": int(codes[b])}
            for throw_m in (0.5, 1.0):
                trig = _restart_triggers(c.geometry, a, hi, throw_m)
                teams = {k for kind, (fh, fa) in trig.items() for k, f in ((H, fh), (A, fa)) if f}
                r[f"geo{throw_m}"] = teams.pop() if len(teams) == 1 else -1
                if throw_m == 1.0:
                    r.update({f"kind_{kind}": int(fh or fa) for kind, (fh, fa) in trig.items()})
            gone = np.flatnonzero(out_[max(a - 50, 0):hi])
            r["lasttouch"] = -1
            if len(gone):
                f0 = max(a - 50, 0) + int(gone[0])
                before = np.flatnonzero(tok[max(f0 - 125, 0):f0] != NO_TEAM)
                if len(before):
                    r["lasttouch"] = 1 - int(tok[max(f0 - 125, 0) + before[-1]])
            r["geo1.0+lasttouch"] = r["geo1.0"] if r["geo1.0"] >= 0 else r["lasttouch"]
            rows.append(r)
        print(c.id.match, c.id.half, flush=True)
    t = pd.DataFrame(rows)
    print(f"\n{len(t)} D stretches; v13 first call right on {(t.v13 == t.truth).mean():.4f}; kinds fired (1 m): "
          + ", ".join(f"{k} {t[f'kind_{k}'].mean():.3f}" for k in ("throw", "corner", "kickoff")))
    for arm in ("geo0.5", "geo1.0", "lasttouch", "geo1.0+lasttouch"):
        f = t[arm] >= 0
        print(f"{arm}: fires on {f.mean():.4f}; right where it fires {(t[arm][f] == t.truth[f]).mean():.4f}; v13 "
              f"right there {(t.v13[f] == t.truth[f]).mean():.4f}; disagrees with v13 on {(t[arm][f] != t.v13[f]).mean():.4f}"
              f" of those, where it is right on {(t[arm][f & (t[arm] != t.v13)] == t.truth[f & (t[arm] != t.v13)]).mean():.4f}")


def seedwins(csv, a, b):
    """Per seed world in a `possession score --dev` CSV (dev_pooled rows): how often model B beats model A on
    spellF1, and the spread of B - A per group."""
    t = pd.read_csv(csv)
    t = t[t.case == "dev_pooled"].pivot_table(index="world", columns="model", values="spell_f1")
    d = t[b] - t[a]
    print(f"seed worlds {len(d)}; {b} above {a} in {(d > 0).sum()}, equal {(d == 0).sum()}, below {(d < 0).sum()}; "
          f"min {d.min():+.4f} at {d.idxmin()}")
    g = d.groupby(d.index.str.replace(r"_s\d+$", "", regex=True))
    print(pd.DataFrame({"min": g.min(), "max": g.max(), "mean": g.mean(), "above": g.apply(lambda x: (x > 0).sum())})
          .round(4).to_string())


def barath_spell(params):
    """E29's registered stop, label-free: the SPELL_FEATURES medians over BAR-ATH's candidate runs (short team runs
    of PARAMS's codes before its spell flip and lag, ATD inputs only) against the 10th-90th percentile range of
    the same features over PFF-A m0's candidate runs; prints STOP for any median outside it (E30: only features
    whose spell_logit weight is not 0), and the frames PARAMS's spell flip changes on BAR-ATH. Never rescales or
    refits."""
    from possession.decoder import SPELL_FEATURES, _spell_flip, _spell_runs
    model = Decoder.load(params)
    p, chain = model.params, _rules_off(model)
    frames = p.spell_flip_frames or 250
    ref = []
    for world, pooled_a, _, _ in native_a():
        if "_m0_" not in world:
            continue
        for h in pooled_a.halves:
            pre, lo = _pre_lag(model, chain, h)
            ref += [x for _, _, _, x in _spell_runs(pre, h, frames, lo)]
    ref = pd.DataFrame(ref, columns=list(SPELL_FEATURES))
    rows, flipped, n_runs = [], 0, 0
    for g, hid in zip(challenge.load_geometry(), challenge._half_ids()):
        h = challenge.observe(g, hid)
        pre, lo = _pre_lag(model, chain, h)
        runs = _spell_runs(pre, h, frames, lo)
        rows += [x for _, _, _, x in runs]
        n_runs += len(runs)
        if p.spell_flip_p:
            flipped += int((_spell_flip(pre, h, p, lo) != pre).sum())
    bar = pd.DataFrame(rows, columns=list(SPELL_FEATURES))
    t = pd.DataFrame({"pff_a_p10": ref.quantile(0.1), "pff_a_p90": ref.quantile(0.9), "barath_median": bar.median()})
    t["stop"] = (t.barath_median < t.pff_a_p10) | (t.barath_median > t.pff_a_p90)
    if p.spell_logit:
        t["weight"] = pd.Series(p.spell_logit).reindex(list(SPELL_FEATURES)).fillna(0.0)
        t["stop"] &= t.weight != 0
    print(f"{len(ref)} PFF-A m0 candidate runs, {n_runs} BAR-ATH candidate runs")
    print(t.round(4).to_string())
    print("STOP" if t.stop.any() else "no feature median outside the PFF-A 10th-90th range")
    if p.spell_flip_p:
        print(f"{Path(params).stem}'s spell flip changes {flipped} BAR-ATH frames")


def spellseen(params):
    """Label-free: SPELL_FEATURES medians and the fully-seen share over the candidate runs of PARAMS's codes before
    its spell flip and lag, on synthetic IDSSE m0 and Metrica m0 (dead_bias 2.6, seed 0) and on PFF-A m0, to say
    which gap regime the veto worlds exercise."""
    from possession.decoder import SPELL_FEATURES, _spell_runs
    model = Decoder.load(params)
    chain, frames, out = _rules_off(model), model.params.spell_flip_frames or 250, {}
    sources = [(w, c.halves) for _, w, c in scored_cases(bench.dev_worlds(["idsse:m0", "m0"], (2.6,), seeds=(0,)))]
    sources += [(w + "_A", c.halves) for w, c, _, _ in native_a() if "_m0_" in w]
    for world, halves in sources:
        rows = []
        for h in halves:
            pre, lo = _pre_lag(model, chain, h)
            rows += [x for _, _, _, x in _spell_runs(pre, h, frames, lo)]
        t = pd.DataFrame(rows, columns=list(SPELL_FEATURES))
        out[world] = {"runs": len(t), "fully_seen": (t.seen == 1).mean(), **t.median().to_dict()}
        print(world, flush=True)
    print(pd.DataFrame(out).round(4).to_string())


def deadsplit(params):
    """Label-reading, never a candidate: where PARAMS's dead-ball headroom sits on native PFF-A m0 and m2. On its
    final codes: insert (labelled D frames become D), insert_long (only labelled D stretches of 50+ frames),
    remove (D frames labelled live take the previous team call, else the next), both (D exactly where labelled)."""
    model, rows, per_game = Decoder.load(params), [], []

    def fill(codes, gap):
        out = np.where(gap, D, codes).astype(np.int8)
        idx = np.where(out != D, np.arange(len(out)), -1)
        last = np.maximum.accumulate(idx)
        nxt = np.minimum.accumulate(np.where(out != D, np.arange(len(out)), len(out))[::-1])[::-1]
        src = np.where(last >= 0, last, np.minimum(nxt, len(out) - 1))
        return np.where(gap & (out[src] != D), out[src], codes).astype(np.int8)

    for world, pooled_a, labs, games_a in native_a():
        halves = pooled_a.halves
        variants = {k: [] for k in ("base", "insert", "insert_long", "remove", "both")}
        for h, lab in zip(halves, labs):
            c = model.decode(h).codes
            dead = lab == D
            long_ = np.zeros(h.n, bool)
            for a, b in zip(*_runs(dead)):
                if b - a >= 50:
                    long_[a:b] = True
            removed = fill(c, (c == D) & ~dead)
            variants["base"].append(c)
            variants["insert"].append(np.where(dead, D, c).astype(np.int8))
            variants["insert_long"].append(np.where(long_, D, c).astype(np.int8))
            variants["remove"].append(removed)
            variants["both"].append(np.where(dead, D, removed).astype(np.int8))
        runs = score.valid_runs(pooled_a.gt)
        f0 = None
        for name, codes in variants.items():
            f1, n = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs)
            f0 = f1 if name == "base" else f0
            rows.append({"world": world, "variant": name, "spell_f1": f1, "delta": f1 - f0, "n_pred": n})
            if "_m0_" in world:
                by_key = {(h.id.match, h.id.half): x for h, x in zip(halves, codes)}
                for g in games_a:
                    gc = [by_key[(h.id.match, h.id.half)] for h in g.halves]
                    per_game.append({"base": Path(params).stem, "game": g.name, "variant": name,
                                     "spell_f1": score.spell_f1(g.layout, g.gt, gc, score.valid_runs(g.gt))[0]})
        print(world, flush=True)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    paired_delta(per_game, ["insert", "insert_long", "remove", "both"])


def deadcensus(params):
    """Label-reading, never a candidate: on PFF-A m0, PARAMS's final codes over each labelled stretch of 50+
    frames, split into labelled D stretches the decoder misses (under 10% D), half-catches and catches (50%+ D),
    and labelled live stretches it calls a team (control); per class the count, frames and medians of label-free
    stretch statistics."""
    model, rows = Decoder.load(params), []
    for world, pooled_a, labs, _ in native_a():
        if "_m0_" not in world:
            continue
        for h, lab in zip(pooled_a.halves, labs):
            c, g, pace = model.decode(h).codes, h.geometry, h.pace_mps
            seen = h.nearest_team != NO_TEAM
            for dead in (True, False):
                flag = (lab == D) if dead else np.isin(lab, (H, A))
                for a, b in zip(*_runs(flag)):
                    if b - a < 50 or a < h.id.kickoff:
                        continue
                    dshare = float((c[a:b] == D).mean())
                    if dead:
                        kind = "D missed" if dshare < 0.1 else "D caught" if dshare >= 0.5 else "D half"
                    elif dshare < 0.1:
                        kind = "live called team"
                    else:
                        continue
                    s, sp = seen[a:b], g.speed_mps[a:b]
                    pc = pace[a:b]
                    pre = slice(max(a - 50, 0), a)
                    rows.append({"kind": kind, "frames": b - a, "len_s": (b - a) / FPS, "seen": s.mean(),
                                 "speed_med": np.nanmedian(np.where(s, sp, np.nan)) if s.any() else np.nan,
                                 "still_share": float(((sp < 1.0) & s).sum() / max(s.sum(), 1)),
                                 "pace_med": np.nanmedian(pc) if np.isfinite(pc).any() else np.nan,
                                 "walk_share": float(np.nan_to_num(pc < 0.5).mean()),
                                 "out_max": np.nanmax(np.where(s, g.outside_m[a:b], np.nan)) if s.any() else np.nan,
                                 "out_share": float(np.nan_to_num(g.outside_m[a:b] > 0.5).mean()),
                                 "near_med": np.nanmedian(g.nearest_m[a:b]) if s.any() else np.nan,
                                 "speed_pre_max": np.nanmax(g.speed_mps[pre]) if np.isfinite(g.speed_mps[pre]).any()
                                 else np.nan})
    t = pd.DataFrame(rows)
    print(t.groupby("kind").agg(n=("frames", "size"), frames=("frames", "sum")).to_string())
    print("\nmedians")
    print(t.groupby("kind").median(numeric_only=True).round(3).T.to_string())
    print("\nmissed D stretches by length (s)")
    m = t[t.kind == "D missed"]
    print(pd.cut(m.len_s, [2, 5, 10, 20, 40, 1e9]).value_counts().sort_index().to_string())
    q = t[t.kind.isin(["D missed", "live called team"])]
    print("\nunivariate AUC, missed D against live called team")
    for f in ("len_s", "seen", "speed_med", "still_share", "pace_med", "walk_share", "out_max", "out_share",
              "near_med", "speed_pre_max"):
        v = q[f].to_numpy(np.float64)
        ok = np.isfinite(v)
        print(f"  {f} {auc(v[ok], (q.kind == 'D missed').to_numpy()[ok].astype(float)):.3f} "
              f"(finite on {ok.mean():.2f})")


def deadedges(params):
    """Label-reading, never a candidate: deadsplit's insert_long split by what PARAMS's final codes do on each
    labelled D stretch of 50+ frames on native PFF-A m0 and m2: missed (under 10% D), half (10-50%), caught
    (50%+) filled whole, and for caught stretches only the start edge (labelled start to the first D frame) or
    only the end edge (last D frame to labelled end); prints the caught stretches' edge gaps in frames."""
    model, rows, per_game, gaps = Decoder.load(params), [], [], []
    for world, pooled_a, labs, games_a in native_a():
        halves = pooled_a.halves
        names = ("base", "missed", "half", "caught", "caught_start", "caught_end")
        variants = {k: [] for k in names}
        for h, lab in zip(halves, labs):
            c = model.decode(h).codes
            out = {k: c.copy() for k in names[1:]}
            for a, b in zip(*_runs(lab == D)):
                if b - a < 50:
                    continue
                d = np.flatnonzero(c[a:b] == D)
                share = len(d) / (b - a)
                if share < 0.1:
                    out["missed"][a:b] = D
                elif share < 0.5:
                    out["half"][a:b] = D
                else:
                    out["caught"][a:b] = D
                    out["caught_start"][a:a + d[0]] = D
                    out["caught_end"][a + d[-1] + 1:b] = D
                    if "_m0_" in world:
                        gaps.append({"start_gap": int(d[0]), "end_gap": int(b - a - d[-1] - 1),
                                     "d_before": int(a > 0 and c[a - 1] == D), "d_after": int(b < h.n and c[b] == D)})
            variants["base"].append(c)
            for k in names[1:]:
                variants[k].append(out[k])
        runs = score.valid_runs(pooled_a.gt)
        f0 = None
        for name, codes in variants.items():
            f1, n = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs)
            f0 = f1 if name == "base" else f0
            rows.append({"world": world, "variant": name, "spell_f1": f1, "delta": f1 - f0, "n_pred": n})
            if "_m0_" in world:
                by_key = {(h.id.match, h.id.half): x for h, x in zip(halves, codes)}
                for g in games_a:
                    gc = [by_key[(h.id.match, h.id.half)] for h in g.halves]
                    per_game.append({"base": Path(params).stem, "game": g.name, "variant": name,
                                     "spell_f1": score.spell_f1(g.layout, g.gt, gc, score.valid_runs(g.gt))[0]})
        print(world, flush=True)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    paired_delta(per_game, list(names[1:]))
    g = pd.DataFrame(gaps)
    print(f"\ncaught stretches on PFF-A m0: {len(g)}; edge gaps in frames (quantiles 0.1, 0.25, 0.5, 0.75, 0.9)")
    print(g[["start_gap", "end_gap"]].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).to_string())
    print(f"decoder D already before the labelled start on {g.d_before.mean():.3f}, after the labelled end on "
          f"{g.d_after.mean():.3f}")


def deadstarts(params):
    """Label-reading, never a candidate: on native PFF-A m0, for each labelled D stretch of 50+ frames, where the
    dead rule's cue run (decoder._dead_cues) starts and ends against the labelled edges (lead = labelled start
    minus cue-run start, lag = cue-run end minus labelled end, in frames), split by whether the ball is seen
    outside the pitch near the edge; and deadedges' start and end fills on caught stretches split the same way."""
    from possession.decoder import _dead_cues
    model, rows = Decoder.load(params), []
    p = model.params
    fills = {k: [] for k in ("base", "start out", "start in", "end out", "end in")}
    for world, pooled_a, labs, games_a in native_a():
        if "_m0_" not in world:
            continue
        for h, lab in zip(pooled_a.halves, labs):
            c, cue = model.decode(h).codes, _dead_cues(h, p)
            out = h.geometry.outside_m > p.dead_outside_m
            starts, stops = _runs(cue)
            f = {k: c.copy() for k in list(fills)[1:]}
            for a, b in zip(*_runs(lab == D)):
                if b - a < 50 or a < h.id.kickoff:
                    continue
                i = np.searchsorted(stops, a, side="right")
                j = np.searchsorted(starts, b, side="left") - 1
                lead = int(a - starts[i]) if i < len(starts) and starts[i] < b else None
                lag = int(stops[j] - b) if j >= 0 and stops[j] > a else None
                out_a = bool(out[max(a - 25, 0):a + 75].any())
                out_b = bool(out[max(b - 75, 0):b + 25].any())
                d = np.flatnonzero(c[a:b] == D)
                share = len(d) / (b - a)
                rows.append({"kind": "missed" if share < 0.1 else "half" if share < 0.5 else "caught", "lead": lead,
                             "lag": lag, "out_start": out_a, "out_end": out_b,
                             "start_gap": int(d[0]) if len(d) else None,
                             "end_gap": int(b - a - d[-1] - 1) if len(d) else None})
                if share >= 0.5:
                    f["start out" if out_a else "start in"][a:a + d[0]] = D
                    f["end out" if out_b else "end in"][a + d[-1] + 1:b] = D
            fills["base"].append(c)
            for k in list(fills)[1:]:
                fills[k].append(f[k])
        runs = score.valid_runs(pooled_a.gt)
        f0 = None
        for name, codes in fills.items():
            f1, n = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs)
            f0 = f1 if name == "base" else f0
            print(f"{name}: spellF1 {f1:.4f} delta {f1 - f0:+.4f} n_pred {n}")
    t = pd.DataFrame(rows)
    q = [0.1, 0.25, 0.5, 0.75, 0.9]
    for col, by in (("lead", "out_start"), ("lag", "out_end"), ("start_gap", "out_start"), ("end_gap", "out_end")):
        print(f"\n{col} by {by}, caught stretches (frames)")
        s = t[t.kind == "caught"].dropna(subset=[col])
        print(s.groupby(by)[col].describe(percentiles=q).round(1).to_string())
    print("\nout_start share by kind")
    print(t.groupby("kind")[["out_start", "out_end"]].mean().round(3).to_string())


def deadends(params):
    """Label-reading, never a candidate: on native PFF-A m0, (1) for caught labelled stoppages (50%+ D), the cue
    run's end against the labelled end, split by whether the cue run ends on a still seen ball that then moves (a
    restart kick), with the end fill split the same way; (2) for missed and half-caught stoppages, how many have the
    ball seen outside near their start, with the whole fill split the same way."""
    from possession.decoder import _dead_cues
    model, rows = Decoder.load(params), []
    p = model.params
    names = ("base", "end kick", "end other", "short out", "short other")
    for world, pooled_a, labs, _ in native_a():
        if "_m0_" not in world:
            continue
        fills = {k: [] for k in names}
        for h, lab in zip(pooled_a.halves, labs):
            c, cue, g = model.decode(h).codes, _dead_cues(h, p), h.geometry
            seen = h.nearest_team != NO_TEAM
            still = seen & (g.speed_mps < p.dead_still_mps)
            out = g.outside_m > p.dead_outside_m
            starts, stops = _runs(cue)
            f = {k: c.copy() for k in names[1:]}
            for a, b in zip(*_runs(lab == D)):
                if b - a < 50 or a < h.id.kickoff:
                    continue
                d = np.flatnonzero(c[a:b] == D)
                share = len(d) / (b - a)
                if share >= 0.5:
                    j = np.searchsorted(starts, b, side="left") - 1
                    stop = int(stops[j]) if j >= 0 and stops[j] > a else None
                    kick = stop is not None and stop < h.n and still[stop - 25:stop].sum() >= 13 and seen[stop]
                    rows.append({"part": "end", "kick": kick, "lag": None if stop is None else stop - b,
                                 "end_gap": int(b - a - d[-1] - 1)})
                    f["end kick" if kick else "end other"][a + d[-1] + 1:b] = D
                else:
                    o = bool(out[max(a - 25, 0):a + 75].any())
                    rows.append({"part": "short", "out": o, "frames": b - a, "share": share})
                    f["short out" if o else "short other"][a:b] = D
            fills["base"].append(c)
            for k in names[1:]:
                fills[k].append(f[k])
        runs = score.valid_runs(pooled_a.gt)
        f0 = None
        for name, codes in fills.items():
            f1, n = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs)
            f0 = f1 if name == "base" else f0
            print(f"{name}: spellF1 {f1:.4f} delta {f1 - f0:+.4f} n_pred {n}")
    t = pd.DataFrame(rows)
    q = [0.1, 0.25, 0.5, 0.75, 0.9]
    e = t[t.part == "end"]
    print("\ncue-run end minus labelled end, and D's end gap, caught stoppages (frames), by restart kick")
    print(e.groupby("kick")[["lag", "end_gap"]].describe(percentiles=q).round(1).T.to_string())
    s = t[t.part == "short"]
    print("\nmissed and half-caught stoppages by ball-out evidence near the start")
    print(s.groupby("out").agg(n=("frames", "size"), frames=("frames", "sum"), len_med=("frames", "median"),
                               share_med=("share", "median")).to_string())


def slotcheck():
    """Label-free correctness check of BAR-ATH's track slots (inputs only, no labels, no decoder output): per half,
    slots in one penalty box on 60%+ of their 2,500+ present frames (keepers) against the team that defends that
    box (the team whose players stand nearer it over the first 10 s after kickoff); frames where a team has more
    than 11 slots present; and the share of frames where the slot nearest the ball moves faster than 15 m/s."""
    rows = []
    for g, hid in zip(challenge.load_geometry(), challenge._half_ids()):
        L, W = g.pitch_m
        p, b, team = g.players_xy, g.ball_xy, g.slot_team
        present = np.isfinite(p[..., 0])
        k0 = hid.kickoff
        early = p[k0:k0 + 250, :, 0]
        home_left = np.nanmean(early[:, team == HOME]) < np.nanmean(early[:, team == AWAY])
        box_y = (W / 2 - 20.16, W / 2 + 20.16)
        in_y = (p[..., 1] > box_y[0]) & (p[..., 1] < box_y[1])
        left, right = in_y & (p[..., 0] < 16.5), in_y & (p[..., 0] > L - 16.5)
        n_present = present.sum(0)
        for s in np.flatnonzero(n_present >= 2500):
            for side, box in (("left", left), ("right", right)):
                share = box[:, s].sum() / n_present[s]
                if share >= 0.6:
                    defender = HOME if (side == "left") == home_left else AWAY
                    rows.append({"half": hid.half, "slot": int(s), "frames": int(n_present[s]), "box": side,
                                 "share": round(float(share), 3), "slot_team": "H" if team[s] == HOME else "A",
                                 "defends": "H" if defender == HOME else "A",
                                 "ok": bool(team[s] == defender)})
        over = {t: int((present[:, team == t].sum(1) > 11).sum()) for t in (HOME, AWAY)}
        d = np.where(present, np.hypot(p[..., 0] - b[:, None, 0], p[..., 1] - b[:, None, 1]), np.inf)
        seen = np.isfinite(b[:, 0]) & present.any(1)
        near = d.argmin(1)
        idx = np.arange(len(near) - 1)
        same = seen[:-1] & seen[1:] & (near[:-1] == near[1:])
        step = np.hypot(*(p[idx + 1, near[:-1]] - p[idx, near[:-1]]).T)
        fast = same & (step * FPS > 15)
        print(f"half {hid.half}: slots {p.shape[1]}, home starts left {home_left}, frames with more than 11 slots "
              f"present: home {over[HOME]}, away {over[AWAY]} of {len(p)}; nearest-slot steps over 15 m/s "
              f"{int(fast.sum())} of {int(same.sum())} ({fast.sum() / max(same.sum(), 1):.4f})")
    print(pd.DataFrame(rows).to_string(index=False) if rows else "no keeper-like slots")


def officials():
    """Label-free (inputs only, no labels, no decoder output): is an official tracked inside a team slot? Per live
    half (from kickoff), every run where a team has more than 11 slots present is classed by its extra slot, the
    present slot least present in the 2,000 frames either side: duplicate (some same-team pair within 2 m, median
    over the run), off the field or on the touchline (extra's median distance to the nearest touchline under 2 m),
    or in play. For each extra: median distance to its nearest teammate and nearest opponent, the ball-seen run
    frames on which it is the slot nearest the ball, and those on which dropping it hands the nearest-team token to
    the other team (flip_frames, the most an official in that slot could cost). Then every slot present on 20,000+ live frames: an official
    follows play but keeps off the ball, an assistant runs one touchline."""
    runs, slots_ = [], []
    for g, hid in zip(challenge.load_geometry(), challenge._half_ids()):
        L, W = g.pitch_m
        k0 = hid.kickoff
        p, b, team = g.players_xy[k0:].astype(np.float64), g.ball_xy[k0:].astype(np.float64), g.slot_team
        n = len(p)
        present, seen = np.isfinite(p[..., 0]), np.isfinite(b[:, 0])
        d_ball = np.where(present, np.hypot(p[..., 0] - b[:, None, 0], p[..., 1] - b[:, None, 1]), np.inf)
        nearest = np.where(seen & present.any(1), d_ball.argmin(1), -1)
        touch = np.minimum(p[..., 1], W - p[..., 1])
        for t in (HOME, AWAY):
            own = np.flatnonzero(team == t)
            over = present[:, own].sum(1) > 11
            edges = np.flatnonzero(np.diff(np.r_[0, over.astype(int), 0]))
            for a, z in zip(edges[::2], edges[1::2]):
                sub, pres = p[a:z][:, own], present[a:z][:, own]
                pair = np.hypot(sub[:, :, None, 0] - sub[:, None, :, 0], sub[:, :, None, 1] - sub[:, None, :, 1])
                pair[~(pres[:, :, None] & pres[:, None, :])] = np.inf
                pair[:, np.arange(len(own)), np.arange(len(own))] = np.inf
                outside = np.r_[np.arange(max(0, a - 2000), a), np.arange(z, min(n, z + 2000))]
                share = present[outside][:, own].mean(0) if len(outside) else np.zeros(len(own))
                e = own[min((i for i in range(len(own)) if pres[:, i].mean() > 0.5), key=lambda i: share[i])]
                fr = np.arange(a, z)[present[a:z, e]]
                sf = fr[seen[fr]]
                gap = lambda mask: np.median(np.where(present[fr][:, mask], np.hypot(
                    p[fr][:, mask, 0] - p[fr, e, None, 0], p[fr][:, mask, 1] - p[fr, e, None, 1]), np.inf).min(1))
                kind = ("duplicate" if np.median(pair.min((1, 2))) < 2.0 else
                        "off or touchline" if np.median(touch[fr, e]) < 2.0 else "in play")
                hit = sf[nearest[sf] == e]
                rest = d_ball[hit].copy()
                rest[:, e] = np.inf
                runner_up = rest.argmin(1)
                flips = int((np.isfinite(rest[np.arange(len(hit)), runner_up]) & (team[runner_up] != t)).sum())
                runs.append(dict(half=hid.half, team="H" if t == HOME else "A", kind=kind, frames=int(z - a),
                                 mate_m=gap((team == t) & (np.arange(len(team)) != e)), opp_m=gap(team != t),
                                 ball_m=np.median(d_ball[sf, e]) if len(sf) else np.nan,
                                 nearest_frames=len(hit), flip_frames=flips, seen_frames=len(sf)))
        for s_ in range(p.shape[1]):
            fr = np.flatnonzero(present[:, s_])
            if len(fr) < 20000:
                continue
            sf = fr[seen[fr]]
            slots_.append(dict(half=hid.half, slot=s_, within2m=float((d_ball[sf, s_] < 2).mean()),
                               nearest=float((nearest[sf] == s_).mean()), touchline=float(np.median(touch[fr, s_]))))
    r = pd.DataFrame(runs)
    print(r.groupby("kind").agg(runs=("frames", "size"), frames=("frames", "sum"), mate_m=("mate_m", "median"),
                                opp_m=("opp_m", "median"), ball_m=("ball_m", "median"),
                                nearest_frames=("nearest_frames", "sum"), flip_frames=("flip_frames", "sum"),
                                seen_frames=("seen_frames", "sum")).round(1).to_string())
    near = r[r.nearest_frames > 0]
    print(f"\nruns whose extra is ever nearest the ball: {len(near)}, {int(near.nearest_frames.sum())} frames; "
          f"of those runs, extra closer to a teammate than to an opponent in {int((near.mate_m < near.opp_m).sum())}")
    print(near.round(1).to_string(index=False))
    t = pd.DataFrame(slots_)
    print(f"\n{len(t)} slot-halves present on 20,000+ live frames: within 2 m of the ball on "
          f"{t.within2m.min():.3f} to {t.within2m.max():.3f} of seen frames, nearest on {t.nearest.min():.3f} to "
          f"{t.nearest.max():.3f}; median touchline distance {t.touchline.min():.1f} to {t.touchline.max():.1f} m")


def contest():
    """Label-reading, never a candidate: on native PFF-A m0 and m2, the share of frames that a contest gate marks,
    within 10 frames of a labelled change of team (H to A or A to H with no D between) against frames inside
    labelled possessions at least 50 frames from any change; the gate is the other team's nearest player within R
    metres of the ball (BallGeometry nearest_m + margin_m), optionally or the ball faster than 3 m/s."""
    rows = []
    for world, pooled_a, labs, _ in native_a():
        near_change, inside = [], []
        for h, lab in zip(pooled_a.halves, labs):
            g = h.geometry
            other = (g.nearest_m + g.margin_m).astype(np.float64)
            speed = g.speed_mps.astype(np.float64)
            team = np.isin(lab, (H, A))
            idx = np.flatnonzero(team[:-1] & team[1:] & (lab[:-1] != lab[1:])) + 1
            mark = np.zeros(h.n, bool)
            far = np.ones(h.n, bool)
            for i in idx:
                mark[max(i - 10, 0):i + 10] = True
                far[max(i - 50, 0):i + 50] = False
            seen = h.nearest_team != NO_TEAM
            near_change.append(np.column_stack([other[mark & seen], speed[mark & seen]]))
            inside.append(np.column_stack([other[team & far & seen], speed[team & far & seen]]))
        a, b = np.concatenate(near_change), np.concatenate(inside)
        for r in (1.2, 1.6, 2.0, 2.5, 3.0):
            for fast in (False, True):
                ga = (a[:, 0] <= r) | (fast & (a[:, 1] > 3))
                gb = (b[:, 0] <= r) | (fast & (b[:, 1] > 3))
                rows.append({"world": world, "r_m": r, "or_fast": fast, "near_change": ga.mean(), "inside": gb.mean(),
                             "ratio": ga.mean() / max(gb.mean(), 1e-9)})
        print(world, len(a), len(b), flush=True)
    print(pd.DataFrame(rows).round(3).to_string(index=False))


INSERT_POPS = {"no-out 50+": lambda n, hit: n >= 50 and not hit, "out 50+": lambda n, hit: n >= 50 and hit,
               "all 25+": lambda n, hit: n >= 25}


def insertruns(params):
    """Label-reading ceiling of any rule that makes short dead cue runs D, never a candidate: on native PFF-A m0
    and m2, PARAMS's final codes; left to right, each cue run (decoder._dead_cues) shorter than dead_min_run,
    after kickoff and holding no D, of an INSERT_POPS population (length, ball-out evidence near its start) is made
    D over its whole span when that raises the half's mean matched count minus F/2 per predicted spell."""
    from possession.decoder import _OUT_AFTER, _OUT_BEFORE, _dead_cues
    model, rows, per_game = Decoder.load(params), [], []
    p = model.params
    for world, pooled_a, labs, games_a in native_a():
        halves = pooled_a.halves
        base = [model.decode(h).codes for h in halves]
        f_base, _ = score.spell_f1(pooled_a.layout, pooled_a.gt, base, score.valid_runs(pooled_a.gt))

        def value(lab, codes):
            s = score.pm.spell_scores(lab, codes, [(0, len(lab))])
            return np.mean([v["n_matched"] for v in s["per_iou"].values()]) - f_base / 2 * s["n_pred"]

        variants, counts = {"base": base}, {}
        cands = []
        for h, c in zip(halves, base):
            out = h.geometry.outside_m > p.dead_outside_m
            cands.append([(a, b, bool(out[max(a - _OUT_BEFORE, 0):a + _OUT_AFTER].any()))
                          for a, b in zip(*_runs(_dead_cues(h, p)))
                          if a > h.id.kickoff and b - a < p.dead_min_run and not (c[a:b] == D).any()])
        for name, keep in INSERT_POPS.items():
            got, k = [], 0
            for c, lab, cs in zip(base, labs, cands):
                cur, best = c.copy(), value(lab, c)
                for a, b, hit in cs:
                    if not keep(b - a, hit):
                        continue
                    trial = cur.copy()
                    trial[a:b] = D
                    v = value(lab, trial)
                    if v > best:
                        cur, best, k = trial, v, k + 1
                got.append(cur)
            variants[name], counts[name] = got, k
        n_c = {name: sum(keep(b - a, hit) for cs in cands for a, b, hit in cs) for name, keep in INSERT_POPS.items()}
        runs_ = score.valid_runs(pooled_a.gt)
        for name, codes in variants.items():
            f1, n = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs_)
            rows.append({"world": world, "variant": name, "spell_f1": f1, "delta": f1 - f_base, "n_pred": n,
                         "inserted": counts.get(name, 0), "candidates": n_c.get(name, 0)})
            if "_m0_" in world:
                by_key = {(h.id.match, h.id.half): x for h, x in zip(halves, codes)}
                for g in games_a:
                    gc = [by_key[(h.id.match, h.id.half)] for h in g.halves]
                    per_game.append({"base": Path(params).stem, "game": g.name, "variant": name,
                                     "spell_f1": score.spell_f1(g.layout, g.gt, gc, score.valid_runs(g.gt))[0]})
        print(world, flush=True)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    paired_delta(per_game, INSERT_POPS)


INSERT_FEATURES = ("len", "unseen", "still", "pace", "pace_pre", "pace_post", "dead_post", "turn", "switches",
                   "speed_in", "outside", "gap_d")
INSERT_FIT_POPS = {"no-out 50+": lambda n, hit: n >= 50 and not hit, "50+": lambda n, hit: n >= 50,
                   "25+": lambda n, hit: n >= 25}
INSERT_ARMS = [(pop, cut) for pop in INSERT_FIT_POPS for cut in (0.8, 0.65, 0.5)]
INSERT_PRE, INSERT_STILL_MPS = 50, 1.0


def _med(x):
    x = x[np.isfinite(x)]
    return float(np.median(x)) if len(x) else 0.0


def _insert_rows(codes, h, p, pdead):
    """(start, stop, n, out hit, INSERT_FEATURES) for each decoder._dead_cues run of 25 to dead_min_run - 1 frames
    after kickoff holding no D in CODES. len ln(frames / FPS); unseen, still: share of ball-unseen frames, of seen
    frames under 1 m/s; pace, pace_pre, pace_post: ln(1 + median player pace) inside, over the 50 frames before,
    the 50 after; dead_post: mean chain P(D); turn: 1 when the last team code before differs from the first after;
    switches: ln(1 + team changes inside); speed_in: ln(1 + max ball speed over the 25 frames before, capped at
    40 m/s); outside: max outside_m over [start - 25, start + 75), capped at 5 m; gap_d: ln(1 + frames to the
    nearest D)."""
    from possession.decoder import _OUT_AFTER, _OUT_BEFORE, _dead_cues
    g, n_ = h.geometry, h.n
    dpos = np.flatnonzero(codes == D)
    rows = []
    for a, b in zip(*_runs(_dead_cues(h, p))):
        a, b, n = int(a), int(b), int(b - a)
        if a <= h.id.kickoff or n < 25 or n >= p.dead_min_run or (codes[a:b] == D).any():
            continue
        out = g.outside_m[max(a - _OUT_BEFORE, 0):a + _OUT_AFTER]
        out = out[np.isfinite(out)]
        hit = bool((out > p.dead_outside_m).any())
        seen = h.nearest_team[a:b] != NO_TEAM
        sp = g.speed_mps[a:b][seen]
        pre = g.speed_mps[max(a - 25, 0):a][h.nearest_team[max(a - 25, 0):a] != NO_TEAM]
        pre = pre[np.isfinite(pre)]
        left, right = codes[:a][codes[:a] != D], codes[b:][codes[b:] != D]
        k = np.searchsorted(dpos, a)
        gap = min(a - dpos[k - 1] if k else n_, dpos[k] - b if k < len(dpos) else n_ - b)
        x = (np.log(n / FPS), 1 - seen.mean(), float((sp < INSERT_STILL_MPS).mean()) if len(sp) else 0.0,
             np.log1p(_med(h.pace_mps[a:b])), np.log1p(_med(h.pace_mps[max(a - INSERT_PRE, 0):a])),
             np.log1p(_med(h.pace_mps[b:b + INSERT_PRE])), float(pdead[a:b].mean()),
             float(len(left) and len(right) and left[-1] != right[0]),
             np.log1p(int((np.diff(codes[a:b]) != 0).sum())),
             np.log1p(min(float(pre.max()), 40.0)) if len(pre) else 0.0,
             min(float(out.max()), 5.0) if len(out) else 0.0, np.log1p(gap))
        rows.append((a, b, n, hit, tuple(round(float(v), 9) for v in x)))
    return rows


def insertfit(params, out):
    """E35 first gate, PFF-A only: a ridge logistic on _insert_rows features predicts whether making one short cue
    run D alone raises the half's matched-minus-F/2 value on the m0 labels; 2-fold game-OOF weights at INSERT_ARMS
    make runs D together on the final codes, on m0 and m2; writes OUT-pff.csv (OOF margins over smooth50) and
    OUT-weights.json (the all-A fit per population)."""
    model, s50 = Decoder.load(params), bench.Smoother(50)
    p = model.params
    by_world, table = {}, []
    for world, pooled_a, labs, games_a in native_a():
        halves, bases, rows_ = pooled_a.halves, [], []
        games = list(dict.fromkeys(h.id.match for h in halves))
        runs = score.valid_runs(pooled_a.gt)
        for h in halves:
            bases.append(model.decode(h).codes)
        f_base, _ = score.spell_f1(pooled_a.layout, pooled_a.gt, bases, runs)
        floor, _ = score.spell_f1(pooled_a.layout, pooled_a.gt, [s50.decode(h).codes for h in halves], runs)
        for h, lab, c in zip(halves, labs, bases):
            gpost, m = _block_posterior(model, h)
            pdead = np.ones(h.n)
            pdead[h.id.kickoff:] = np.repeat(gpost[:, 2], p.stride)[:m]
            rows = _insert_rows(c, h, p, pdead)
            rows_.append(rows)
            if "_m0_" not in world:
                continue

            def value(codes):
                s = score.pm.spell_scores(lab, codes, [(0, len(lab))])
                return np.mean([v["n_matched"] for v in s["per_iou"].values()]) - f_base / 2 * s["n_pred"]

            v0 = value(c)
            for a, b, n, hit, x in rows:
                trial = c.copy()
                trial[a:b] = D
                table.append({"key": (h.id.match, h.id.half), "fold": games.index(h.id.match) % 2, "a": a, "n": n,
                              "hit": hit, "y": float(value(trial) > v0), **dict(zip(INSERT_FEATURES, x))})
        by_world[world] = (pooled_a, bases, rows_, games_a, floor)
        print(world, flush=True)
    t = pd.DataFrame(table)
    x_all = np.column_stack([np.ones(len(t)), t[list(INSERT_FEATURES)].to_numpy(np.float64)])
    y_all = t.y.to_numpy()
    print(f"\n{len(t)} candidate runs on PFF-A m0, D helps on {t.y.mean():.3f}")
    print("univariate AUC: " + ", ".join(f"{f} {auc(t[f].to_numpy(), y_all):.3f}" for f in INSERT_FEATURES))
    masks = {pop: np.array([keep(n, hit) for n, hit in zip(t.n, t.hit)]) for pop, keep in INSERT_FIT_POPS.items()}
    names = ("a",) + INSERT_FEATURES
    fit = lambda m: dict(zip(names, (round(float(v), 4) for v in ridge_newton(x_all[m], y_all[m]))))
    folds = {pop: [fit(m & (t.fold != f).to_numpy()) for f in (0, 1)] for pop, m in masks.items()}
    full = {pop: fit(m) for pop, m in masks.items()}
    for pop, m in masks.items():
        z = np.zeros(len(t))
        for f in (0, 1):
            w, sel = folds[pop][f], (t.fold == f).to_numpy()
            z[sel] = x_all[sel] @ np.array([w[k] for k in names])
        print(f"{pop}: {m.sum()} runs, D helps on {y_all[m].mean():.3f}, OOF AUC {auc(z[m], y_all[m]):.3f}; all-A "
              "weights " + ", ".join(f"{k} {v:+.4f}" for k, v in full[pop].items()))
    fold_of = {(k, a): f for k, a, f in zip(t.key, t.a, t.fold)}
    rows, per_game = [], []
    for world, (pooled_a, bases, rows_, games_a, floor) in by_world.items():
        runs = score.valid_runs(pooled_a.gt)
        variants, made = {"base": bases}, {}
        for pop, cut in INSERT_ARMS:
            name, k, codes, zc = f"{pop}>={cut}", 0, [], np.log(cut / (1 - cut))
            for h, c, rr in zip(pooled_a.halves, bases, rows_):
                key, new = (h.id.match, h.id.half), c.copy()
                for a, b, n, hit, x in rr:
                    w = folds[pop][fold_of[(key, a)]]
                    if INSERT_FIT_POPS[pop](n, hit) and w["a"] + sum(w[f] * v for f, v in zip(INSERT_FEATURES, x)) >= zc:
                        new[a:b] = D
                        k += 1
                codes.append(new)
            variants[name], made[name] = codes, k
        f0 = None
        for name, codes in variants.items():
            f1, npred = score.spell_f1(pooled_a.layout, pooled_a.gt, codes, runs)
            f0 = f1 if name == "base" else f0
            rows.append({"group": world + "_A", "world": world + "_A", "variant": name, "spell_f1": f1,
                         "floor": floor, "margin": f1 - floor, "delta": f1 - f0, "n_pred": npred,
                         "inserted": made.get(name, 0)})
            if "_m0_" in world:
                by_key = {(h.id.match, h.id.half): x for h, x in zip(pooled_a.halves, codes)}
                for g in games_a:
                    gc = [by_key[(h.id.match, h.id.half)] for h in g.halves]
                    per_game.append({"base": Path(params).stem, "game": g.name, "variant": name,
                                     "spell_f1": score.spell_f1(g.layout, g.gt, gc, score.valid_runs(g.gt))[0]})
    r = pd.DataFrame(rows)
    print("\nOOF insertions on PFF-A (oracle ceilings from insertruns: m0 no-out 50+ +0.0282, all 25+ +0.0395)")
    print(r.drop(columns=["group"]).round(4).to_string(index=False))
    paired_delta(per_game, [n for n in r.variant.unique() if n != "base"])
    r.drop(columns=["delta", "inserted"]).to_csv(f"{out}-pff.csv", index=False, float_format="%.6f")
    Path(f"{out}-weights.json").write_text(json.dumps(full, indent=2, sort_keys=True) + "\n")
    print(f"{out}-pff.csv {out}-weights.json")


STEP_BOX, STEP_MIN_FINITE, STEP_BACK, STEP_FWD, STEP_KEEP = 25, 13, 50, 200, 25
STEP_MID, STEP_SAFE = (0.4, 30, 50), (0.7, 15, 0)


def pace_drop(pace):
    """E34's box drop: mean finite pace over the 25 frames before f minus over the 25 from f, from exact int64
    sums of round(pace * 1e6), NaN unless both boxes hold 13+ finite values, rounded to 9 places."""
    ok = np.isfinite(pace)
    v = np.where(ok, np.round(np.where(ok, pace, 0.0).astype(np.float64) * 1e6), 0).astype(np.int64)
    cs, cn = np.r_[0, np.cumsum(v)], np.r_[0, np.cumsum(ok.astype(np.int64))]
    n, k = len(pace), STEP_BOX
    out = np.full(n, np.nan)
    f = np.arange(k, n - k + 1)
    nb, na = cn[f] - cn[f - k], cn[f + k] - cn[f]
    good = (nb >= STEP_MIN_FINITE) & (na >= STEP_MIN_FINITE)
    with np.errstate(invalid="ignore", divide="ignore"):
        d = (cs[f] - cs[f - k]) / nb / 1e6 - (cs[f + k] - cs[f]) / na / 1e6
    out[f[good]] = d[good]
    return np.round(out, 9)


def _step_runs(h, p):
    """Per qualifying dead cue run of PARAMS on half H, as _missing_run_dead places it: start, stop, ball-out hit,
    v13's lo and hi, whether v13 closed the live gap before it, prev_hi, t* and drop[t*] (t* None when the
    window is empty or all NaN)."""
    from possession.decoder import _OUT_AFTER, _OUT_BEFORE, _dead_cues
    n, k0 = h.n, h.id.kickoff
    cue = _dead_cues(h, p)
    out = h.geometry.outside_m > p.dead_outside_m
    drop = pace_drop(h.pace_mps)
    runs, prev_hi = [], None
    for start, stop in zip(*_runs(cue)):
        hit = bool(out[max(start - _OUT_BEFORE, 0):start + _OUT_AFTER].any())
        lead, need = p.dead_trim - p.dead_lead_cut, p.dead_min_run
        if hit:
            lead, need = max(lead - p.dead_out_lead_cut, 0), p.dead_out_min_run or need
        lo = start + lead if start > 0 else -p.dead_min_run
        hi = stop - p.dead_trim if stop < n else n + p.dead_min_run
        if not (hi - lo >= need - lead - p.dead_trim and min(hi, n) > max(lo, 0)):
            continue
        closable = prev_hi is not None and prev_hi > k0 and p.dead_close > 0
        closed = closable and lo - prev_hi < p.dead_close
        w0, w1 = max(start - STEP_BACK, k0 + STEP_BOX), min(start + STEP_FWD, stop, n - STEP_BOX)
        t, dt = None, None
        if w1 >= w0:
            w = drop[w0:w1 + 1]
            if np.isfinite(w).any():
                t = w0 + int(np.argmax(np.where(np.isfinite(w), w, -np.inf)))
                dt = float(drop[t])
        runs.append({"start": int(start), "stop": int(stop), "hit": hit, "lo": int(lo), "hi": int(min(hi, n)),
                     "closable": closable, "closed": closed, "prev_hi": prev_hi, "t": t, "drop": dt})
        prev_hi = int(min(hi, n))
    return runs


def _step_start(r, arm, p, k0):
    """The dated start of run R under ARM (mps, shift, back), or None when the rule does not fire."""
    mps, shift, back = arm
    if r["hit"] or r["start"] <= k0 or r["closed"] or r["t"] is None or r["drop"] < mps:
        return None
    floor = r["start"] - back
    if r["closable"]:
        floor = max(floor, r["prev_hi"] + p.dead_close)
    s = max(r["t"] - shift, floor, k0)
    return s if s <= r["hi"] - STEP_KEEP else None


def stepfeas(params):
    """E34 feasibility pass, label-reading, never a candidate: on native PFF-A m0, each caught (50%+ D) labelled
    stoppage of 50+ frames after kickoff whose qualifying cue run has no ball-out evidence and an open preceding
    gap; trigger class, signed lead, t* - a, drop[t*], e0 = v13 lo - a; the live null of max box drops; the
    early-unfill oracle; and the registered kill-gate checks for the mid and conservative arms. Then the same
    e0 / e1 table on IDSSE m0 synthetic worlds (dead_bias 2.6, seeds 0-4)."""
    model = Decoder.load(params)
    p = model.params
    rows, null, unfill, closed_n = [], [], {}, [0, 0]
    for world, pooled_a, labs, games_a in native_a():
        variants = {"base": [], "unfill": []}
        for h, lab in zip(pooled_a.halves, labs):
            c, k0 = model.decode(h).codes, h.id.kickoff
            runs = _step_runs(h, p)
            starts = np.array([r["start"] for r in runs])
            stops = np.array([r["stop"] for r in runs])
            u = c.copy()
            seen = h.nearest_team != NO_TEAM
            slow = seen & (h.geometry.speed_mps < p.dead_still_mps)
            still = np.zeros(h.n, bool)
            for a0, b0 in zip(*_runs(slow)):
                if b0 - a0 >= p.dead_still_frames:
                    still[a0:b0] = True
            for a, b in zip(*_runs(lab == D)):
                if b - a < 50 or a <= k0 or (c[a:b] == D).mean() < 0.5:
                    continue
                i = np.searchsorted(stops, a, side="right")
                if i >= len(runs) or starts[i] >= b:
                    continue
                r = runs[i]
                if r["hit"] or r["start"] <= k0:
                    continue
                if "_m0_" in world:
                    closed_n[0] += 1
                    closed_n[1] += int(r["closed"])
                if r["closed"]:
                    continue
                if r["lo"] < a:
                    u[r["lo"]:a] = u[r["lo"] - 1] if r["lo"] > 0 else u[a]
                if "_m0_" not in world:
                    continue
                st = r["start"]
                cls = "U" if not seen[st] else "S" if still[st] else "P" if h.pace_mps[st] < p.dead_pace_still_mps else "?"
                e1 = {}
                for name, arm in (("mid", STEP_MID), ("safe", STEP_SAFE)):
                    s = _step_start(r, arm, p, k0)
                    e1[name] = (s - a) if s is not None else (r["lo"] - a)
                rows.append({"cls": cls, "lead": a - st, "t_minus_a": None if r["t"] is None else r["t"] - a,
                             "dmax": r["drop"], "e0": r["lo"] - a, "e1_mid": e1["mid"], "e1_safe": e1["safe"]})
            if "_m0_" in world:
                live = lab != D
                drop = pace_drop(h.pace_mps)
                for a, b in zip(*_runs(live)):
                    a = max(a, k0)
                    for w in range(a, b - 250 + 1, 250) if b - a >= 500 else ():
                        seg = drop[w:w + 250]
                        if np.isfinite(seg).any():
                            null.append(float(np.nanmax(seg)))
            variants["base"].append(c)
            variants["unfill"].append(u)
        runs_ = score.valid_runs(pooled_a.gt)
        f0 = score.spell_f1(pooled_a.layout, pooled_a.gt, variants["base"], runs_)[0]
        f1 = score.spell_f1(pooled_a.layout, pooled_a.gt, variants["unfill"], runs_)[0]
        unfill[world] = f1 - f0
        print(world, flush=True)
    t = pd.DataFrame(rows)
    nq = np.quantile(null, [0.5, 0.75, 0.9])
    print(f"\npopulation (PFF-A m0): {len(t)} caught no-out stoppages; v13 closed the gap before {closed_n[1]} of "
          f"{closed_n[0]} ({closed_n[1] / max(closed_n[0], 1):.3f}), skipped")
    print("trigger class shares:", t.cls.value_counts(normalize=True).round(3).to_dict())
    print(f"live null max box drop over {len(null)} windows: p50 {nq[0]:.3f}, p75 {nq[1]:.3f}, p90 {nq[2]:.3f}")
    print("early-unfill oracle (v13 D before the labelled start set back to the preceding code):",
          {k: round(v, 4) for k, v in unfill.items()})
    t["tercile"] = pd.cut(t.lead, [-1e9, -0.5, 75, 1e9], labels=["lead<0", "0-75", ">75"])
    q = [0.1, 0.25, 0.5, 0.75, 0.9]
    print("\nquantiles by lead tercile (frames; drop in m/s)")
    print(t.groupby("tercile", observed=True)[["t_minus_a", "dmax", "e0", "e1_mid", "e1_safe"]]
          .quantile(q).round(2).unstack().T.to_string())
    above = t[t.dmax > nq[1]]
    m = float(above.t_minus_a.median())
    shifts = [15, 30, 45]
    if not 15 <= m <= 45:
        shifts = [int(min(max(5 * round(x / 5), 0), 100)) for x in (m - 15, m, m + 15)]
    mps = [0.7, 0.4]
    if abs(nq[1] - 0.4) > 0.15 or abs(nq[2] - 0.7) > 0.15:
        mps = [round(0.05 * round(nq[2] / 0.05), 2), round(0.05 * round(nq[1] / 0.05), 2)]
    ps = float(t.cls.isin(["P", "S"]).mean())
    backs = [0, 50] if ps >= 0.1 else [0]
    print(f"\nrecentring: median t*-a over runs above the null p75 = {m:.1f} -> shifts {shifts}; thresholds {mps}; "
          f"P+S share {ps:.3f} -> backs {backs}")
    e0, e1 = t.e0.abs().median(), t.e1_mid.abs().median()
    long_ = t[t.lead > 75]
    checks = {
        "a mid median|e1| <= 0.8 median|e0|": (e1, 0.8 * e0, e1 <= 0.8 * e0),
        "b drop above null p75 on 60%+": (float((t.dmax > nq[1]).mean()), 0.6, float((t.dmax > nq[1]).mean()) >= 0.6),
        "c long-lead median e1 25+ frames nearer 0": (abs(long_.e1_mid.median()), abs(long_.e0.median()) - 25,
                                                      abs(long_.e1_mid.median()) <= abs(long_.e0.median()) - 25),
        "d p90(e1) <= p90(e0) + 25": (t.e1_mid.quantile(0.9), t.e0.quantile(0.9) + 25,
                                      t.e1_mid.quantile(0.9) <= t.e0.quantile(0.9) + 25),
        "a safe median|e1| <= 0.8 median|e0|": (t.e1_safe.abs().median(), 0.8 * e0, t.e1_safe.abs().median() <= 0.8 * e0),
    }
    print("\nkill gate (the registered arms, before recentring)")
    for name, (got, bar, ok) in checks.items():
        print(f"  {'pass' if ok else 'FAIL'}  {name}: {got:.2f} against {bar:.2f}")
    syn = []
    for world, cases in bench.dev_worlds(["idsse:m0"], (2.6,), seeds=SEEDS).items():
        case = bench.pooled(cases)
        for h, lab in zip(case.halves, case.layout.cut(case.gt)):
            c, k0 = model.decode(h).codes, h.id.kickoff
            runs = _step_runs(h, p)
            starts = np.array([r["start"] for r in runs])
            stops = np.array([r["stop"] for r in runs])
            for a, b in zip(*_runs(lab == D)):
                if b - a < 50 or a <= k0 or (c[a:b] == D).mean() < 0.5:
                    continue
                i = np.searchsorted(stops, a, side="right")
                if i >= len(runs) or starts[i] >= b:
                    continue
                r = runs[i]
                s = _step_start(r, STEP_MID, p, k0)
                if s is not None:
                    syn.append({"e0": abs(r["lo"] - a), "e1": abs(s - a)})
    s = pd.DataFrame(syn)
    if len(s):
        print(f"\nIDSSE m0 r2.6 seeds 0-4: the mid arm fires on {len(s)} caught stoppages; median|e0| "
              f"{s.e0.median():.1f}, median|e1| {s.e1.median():.1f} -> "
              f"{'FAIL' if s.e1.median() > s.e0.median() + 12 else 'pass'}"
              f"{'; under 50 fire, so the veto cannot judge this rule' if len(s) < 50 else ''}")
    else:
        print("\nIDSSE m0 r2.6 seeds 0-4: the mid arm never fires; the veto cannot judge this rule")


def spellveto(params, weights, out, rhos, items):
    """E29 veto rows: PARAMS with spell_flip at each SPELL_ARMS entry and the all-A WEIGHTS (spellflip's JSON),
    applied by decoder._spell_flip on top of PARAMS's codes before its lag; the first two halves of each world are
    also decoded end to end and must match."""
    from possession.decoder import _lag_handovers, _spell_flip
    base, s50, rows = Decoder.load(params), bench.Smoother(50), []
    w = json.loads(Path(weights).read_text())
    chain = _rules_off(base)
    arms = {f"{pop}>={cut}": base.replace(spell_flip_p=cut, spell_flip_frames=250, spell_flip_seen=SPELL_SEEN[pop],
                                          spell_logit=w[pop]) for pop, cut in SPELL_ARMS}
    for group, world, case in scored_cases(bench.dev_worlds(items, rhos, seeds=SEEDS)):
        if world.endswith("_B"):
            continue
        runs = score.valid_runs(case.gt)
        floor, _ = score.spell_f1(case.layout, case.gt, [s50.decode(h).codes for h in case.halves], runs)
        pre = [_pre_lag(base, chain, h) for h in case.halves]
        lag = lambda x: _lag_handovers(x, base.params.handover_lag)
        variants = {"base": [lag(c) for c, _ in pre]}
        for name, m in arms.items():
            variants[name] = [lag(_spell_flip(c, h, m.params, lo)) for (c, lo), h in zip(pre, case.halves)]
            assert all(np.array_equal(x, m.decode(h).codes) for x, h in zip(variants[name][:2], case.halves)), name
        assert all(np.array_equal(x, base.decode(h).codes) for x, h in zip(variants["base"][:2], case.halves))
        for name, codes in variants.items():
            f1, n = score.spell_f1(case.layout, case.gt, codes, runs)
            rows.append({"group": group, "world": world, "variant": name, "spell_f1": f1, "floor": floor,
                         "margin": f1 - floor, "n_pred": n})
        print(world, flush=True)
    pd.DataFrame(rows).to_csv(out, index=False, float_format="%.6f")
    print(out)


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
WIDE_SLACK = 0.010


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


def pick(synth_csv, pff_csv, base, prefer, wide=()):
    """The registered selection: the synthetic veto, then the PFF-A minimum, ties within VETO_SLACK to BASE, then
    PREFER's order, then the fewest k=v fields changed from BASE, then the higher PFF-A minimum; a chosen arm that
    does not clear BASE's PFF-A minimum by more than VETO_SLACK is no change (written into code after E40). Groups whose name
    starts with a WIDE prefix veto at WIDE_SLACK instead (rule v4: idsse_m0)."""
    sm = pd.read_csv(synth_csv).groupby(["group", "variant"]).margin.mean().unstack("group")
    pm = pd.read_csv(pff_csv).groupby(["group", "variant"]).margin.mean().unstack("group")
    allowed = pd.Series([WIDE_SLACK if g.startswith(tuple(wide)) else VETO_SLACK for g in sm.columns], sm.columns)
    slack = sm.sub(sm.loc[base] - allowed, axis=1)
    t = pd.DataFrame({"synth_min": sm.min(axis=1), "pff_a_min": pm.min(axis=1),
                      **{g.replace("pff_", "").replace("_A", ""): pm[g] for g in pm.columns}, "worst_group": slack.idxmin(axis=1), "veto_slack": slack.min(axis=1)})
    t["passes"] = t.veto_slack >= 0
    print(t.sort_values("pff_a_min", ascending=False).round(4).to_string())
    ok = t[t.passes]
    tied = ok[ok.pff_a_min >= ok.pff_a_min.max() - VETO_SLACK]
    order = [base] + [v for v in prefer if v != base]
    rank = {v: i for i, v in enumerate(order)}
    changed = lambda v: len(set(v.split()) - set(base.split()))
    chosen = sorted(tied.index, key=lambda v: (rank.get(v, len(order)), changed(v), -tied.pff_a_min[v]))[0]
    print(f"\n{int(t.passes.sum())} of {len(t)} pass the veto; tied within {VETO_SLACK}: {sorted(tied.index)}")
    if chosen != base and t.pff_a_min[chosen] <= t.pff_a_min[base] + VETO_SLACK:
        print(f"{chosen} is within {VETO_SLACK} of {base} on the PFF-A minimum, so no change (E32's registered clause)")
        chosen = base
    print("SELECTED", chosen)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("probe", choices=("oracle", "geometry", "pff-geometry", "barath-geometry", "close", "deadrule", "chain", "confirm", "select", "edges", "logit", "speed", "spells", "lag", "snap", "chain5", "speedlogit", "masked", "still", "stillgrid", "dead6", "motion", "pacegrid", "push", "lag7", "deadlogit", "pick", "combo", "census", "hold", "holdgrid", "deadcues", "versions", "merge", "jitter", "restart", "pushgap", "equiv", "spellpush", "pushflip", "pushunseen", "barath-push", "pff-push-tokens", "subs", "switchpen", "spellmass", "equivpath", "mergedose", "deadruns", "flipruns", "spellflip", "spellveto", "barath-spell", "spellseen", "deadsplit", "deadcensus", "deadedges", "deadstarts", "leadgrid", "deadends", "slotcheck", "outrungrid", "contest", "stepfeas", "insertruns", "insertfit", "flipindep", "spellmodel", "islandruns", "cutgrid", "ttitoken", "postd", "postfill", "restartdet", "flippairs", "adjgrid", "seedwins", "e41grid", "e60grid", "e61grid", "e62grid", "e64grid", "e65grid", "velgrid", "velfield", "e67grid", "e68grid", "e69grid", "e70grid", "officials", "linegrid", "linelead", "linefull", "endlead", "returngrid"))
    ap.add_argument("params", nargs="*")
    ap.add_argument("--prefer", nargs="+", default=[], help="pick: the registered tie order after the base")
    ap.add_argument("--only", nargs="+", default=[], help="switchpen: decode base and these variants only")
    ap.add_argument("--drop", nargs="+", default=[], help="spellflip: SPELL_FEATURES left out of the fit (E30: seen)")
    ap.add_argument("--split", action="store_true", help="spellflip: also the seen>=0.8 arm restricted to each SPELL_SPLITS subset")
    ap.add_argument("--wide", nargs="+", default=[], help="pick: group prefixes that veto at WIDE_SLACK (rule v4: idsse_m0)")
    ap.add_argument("--out", help="deadrule: where to write the full grid table (CSV)")
    ap.add_argument("--halves", nargs="+", default=["all", "A", "B"], choices=("all", "A", "B"),
                    help="confirm: which native game halves to print (A only keeps held-out rows unread)")
    ap.add_argument("--dead-bias", type=float, nargs="+", default=[2.6], help="deadrule: generator dead_bias worlds")
    ap.add_argument("--rule", nargs="+", default=SEARCH + NATIVE, help="deadrule: [source:]rule[:mode] items")
    a = ap.parse_args()
    one = a.params[0] if a.params else None
    {"oracle": lambda: oracle(one, a.dead_bias, a.rule), "geometry": geometry, "pff-geometry": pff_geometry, "barath-geometry": barath_geometry,
     "close": lambda: close(one), "deadrule": lambda: deadrule(one, a.out, a.dead_bias, a.rule),
     "chain": lambda: chain_grid(one), "confirm": lambda: confirm(one, a.halves), "jitter": lambda: jitter(a.params), "restart": lambda: restart(one), "pushgap": lambda: pushgap(one), "equiv": lambda: equiv(*a.params), "spellpush": lambda: spellpush(one), "barath-push": barath_push, "pff-push-tokens": pff_push_tokens, "subs": lambda: subs(a.params), "switchpen": lambda: switchpen(one, a.out, a.dead_bias, a.rule, a.only), "spellmass": lambda: spellmass(one, a.only), "equivpath": lambda: equivpath(*a.params), "pushflip": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, PUSH_GRID), "pushunseen": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, PUSH_UNSEEN_GRID), "mergedose": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, DOSE_GRID), "leadgrid": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, LEAD_GRID), "outrungrid": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, OUTRUN_GRID), "cutgrid": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, CUT_GRID), "adjgrid": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, ADJ_GRID), "e41grid": lambda: fieldgrid(one, a.out, a.dead_bias, a.rule, e41_grid()), "e60grid": lambda: fieldgrid(one, a.out, a.dead_bias, a.rule, e60_grid()), "e61grid": lambda: fieldgrid(one, a.out, a.dead_bias, a.rule, E61_GRID), "e62grid": lambda: fieldgrid(one, a.out, a.dead_bias, a.rule, e62_grid()), "e64grid": lambda: modelgrid(e64_models(one, a.params[1]), a.out, a.dead_bias, a.rule), "e65grid": lambda: modelgrid(e65_models(one), a.out, a.dead_bias, a.rule), "velgrid": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, VELOCITY_GRID), "velfield": lambda: fieldgrid(one, a.out, a.dead_bias, a.rule, VELOCITY_GRID), "e67grid": lambda: fieldgrid(one, a.out, a.dead_bias, a.rule, CHAIN_GOAL_GRID), "e68grid": lambda: modelgrid(e68_models(one, a.params[1]), a.out, a.dead_bias, a.rule), "e69grid": lambda: modelgrid(e69_models(one, *a.params[1:3]), a.out, a.dead_bias, a.rule), "e70grid": lambda: modelgrid(e68_models(one, a.params[1], (0.8, 0.75, 0.7, 0.65), "touch refit"), a.out, a.dead_bias, a.rule), "linegrid": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, LINE_GRID), "linelead": lambda: fieldgrid(one, a.out, a.dead_bias, a.rule, LINE_LEAD_GRID), "linefull": lambda: fieldgrid(one, a.out, a.dead_bias, a.rule, LINE_FULL_GRID), "endlead": lambda: fieldgrid(one, a.out, a.dead_bias, a.rule, END_LEAD_GRID), "returngrid": lambda: fieldgrid(one, a.out, a.dead_bias, a.rule, RETURN_GRID), "deadruns": lambda: deadruns(*a.params), "flipruns": lambda: flipruns(one), "spellflip": lambda: spellflip(one, a.out, a.drop, a.split), "barath-spell": lambda: barath_spell(one), "spellseen": lambda: spellseen(one), "deadsplit": lambda: deadsplit(one), "deadcensus": lambda: deadcensus(one), "deadedges": lambda: deadedges(one), "deadstarts": lambda: deadstarts(one), "deadends": lambda: deadends(one), "slotcheck": slotcheck, "officials": officials, "contest": contest, "stepfeas": lambda: stepfeas(one), "insertruns": lambda: insertruns(one), "insertfit": lambda: insertfit(one, a.out), "flipindep": lambda: flipindep(one), "spellmodel": lambda: spellmodel(one), "islandruns": lambda: islandruns(one), "ttitoken": ttitoken, "postd": lambda: postd(one), "postfill": lambda: postfill(one), "restartdet": lambda: restartdet(one), "flippairs": lambda: flippairs(one), "seedwins": lambda: seedwins(*a.params), "spellveto": lambda: spellveto(a.params[0], a.params[1], a.out, a.dead_bias, a.rule), "select": lambda: select(a.params),
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
     "pick": lambda: pick(*a.params, a.prefer, a.wide),
     "combo": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, COMBO_GRID),
     "census": lambda: census(one, a.dead_bias, a.rule), "hold": hold,
     "holdgrid": lambda: holdgrid(one, a.out, a.dead_bias, a.rule),
     "deadcues": lambda: deadcues(one, a.dead_bias, a.rule),
     "versions": lambda: versions(a.params, a.rule),
     "merge": lambda: rulegrid(one, a.out, a.dead_bias, a.rule, MERGE_GRID)}[a.probe]()
