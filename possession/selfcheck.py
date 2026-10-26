from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import tempfile
import time
import traceback
import warnings
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

import games

from . import bench, challenge, decoder, dropout, idsse, measure, metrica, pff, score
from .decoder import Decoder, DecoderParams, State, Tier0Emission
from .half import (A, AWAY, D, H, HOME, NO_TEAM, X, BallGeometry, Block, CleanHalf, Geometry, Half, HalfId,
                   Layout, check_codes)

REPO = Path(__file__).resolve().parents[1]
PARAMS_V0 = REPO / "params" / "tier0_v0.json"
N_ROWS = 199_319


class Skip(Exception):
    pass


def _raises(exc: type[BaseException], fn: Callable, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except exc:
        return
    raise AssertionError(f"{getattr(fn, '__name__', fn)} did not raise {exc.__name__}")


def _segments(spec: list[tuple[int, int]]) -> np.ndarray:
    return np.concatenate([np.full(n, code, np.int8) for code, n in spec])


def _switches(codes: np.ndarray) -> list[tuple[int, int, int]]:
    return score.transitions(codes, [(0, len(codes))])


def _spell_f1_is_evaluate(layout: Layout, gt: np.ndarray, preds: list[np.ndarray]) -> float:
    s = score.evaluate(layout, gt, preds)
    cheap = score.spell_f1(layout, gt, preds, score.valid_runs(gt))
    assert cheap == (s.spell_f1, s.n_pred_spells), (cheap, s)
    return s.spell_f1


def oracle_scores_one() -> None:
    block = _segments([(H, 120), (A, 80), (D, 50), (A, 200), (H, 60), (A, 90), (D, 40), (H, 160)])
    layout = Layout.synthetic([len(block)] * 6)
    synthetic_gt = layout.assemble([block] * 6)
    s = score.evaluate(layout, synthetic_gt, [block] * 6)
    assert (s.spell_f1, s.macro_f1, s.n_gt_spells, s.n_pred_spells, s.n_graded) == (1.0, 1.0, 36, 36, 4800), s
    assert _spell_f1_is_evaluate(layout, synthetic_gt, [block] * 6) == 1.0
    assert 0 < _spell_f1_is_evaluate(layout, synthetic_gt, [np.roll(block, 70)] * 6) < 1

    public = challenge.layout()
    gt = score.read_codes(bench.PUBLIC_GT, N_ROWS)
    preds = [np.where(part == X, D, part).astype(np.int8) for part in public.cut(gt)]
    s = score.evaluate(public, gt, preds)
    assert (s.spell_f1, s.macro_f1, s.n_gt_spells, s.n_pred_spells, s.n_graded) == (1.0, 1.0, 17, 17, 7500), s
    assert 0 < _spell_f1_is_evaluate(public, gt, [np.roll(p, 200) for p in preds]) < 1

    hits, n_pred = score.matched_flags(public, gt, preds)
    assert hits.shape == (5, 17) and hits.all() and n_pred == 17, (hits, n_pred)
    misses, n_pred = score.matched_flags(public, gt, [np.full(b.n, D, np.int8) for b in public.blocks])
    assert misses.shape == (5, 17) and not misses.any() and n_pred == 0, (misses, n_pred)


def layout_splits_halves() -> None:
    layout = Layout.synthetic([100, 100])
    assert layout.n_total == 1700, layout
    runs = score.valid_runs(layout.assemble([np.full(100, H, np.int8)] * 2))
    assert runs == [(500, 600), (1100, 1200)], runs
    assert Layout(1100, (Block(500, 100),)).n_total == 1100
    _raises(ValueError, Layout, 1700, (Block(500, 100), Block(650, 100)))
    _raises(ValueError, Layout, 1100, (Block(499, 100),))
    _raises(ValueError, Layout, 1099, (Block(500, 100),))


def range_guard_fires() -> None:
    check_codes(np.array([H, A, D, X], np.int8), allow_x=True)
    check_codes(np.array([H, A, D], np.int8), allow_x=False)
    _raises(ValueError, check_codes, np.array([0, 4], np.int8), allow_x=True)
    _raises(ValueError, check_codes, np.array([-1, 0], np.int8), allow_x=True)
    _raises(ValueError, check_codes, np.array([0, 1], np.int64), allow_x=True)
    _raises(ValueError, check_codes, np.array([0, X], np.int8), allow_x=False)

    layout = Layout.synthetic([3])
    gt = layout.assemble([np.array([H, H, A], np.int8)])
    assert score.evaluate(layout, gt, [np.array([H, H, A], np.int8)]).spell_f1 == 1.0
    _raises(ValueError, layout.assemble, [np.array([H, 4, A], np.int8)])
    _raises(ValueError, layout.assemble, [np.array([H, 260, A], np.int64)])
    _raises(ValueError, score.evaluate, layout, gt, [np.array([H, X, A], np.int8)])


def permutation_invariance() -> None:
    nan = np.nan
    tiny = Geometry(
        ball_xy=np.array([[0, 0], [2.1, 0], [nan, nan], [0, 0], [0, 0], [0, 0]], np.float32),
        players_xy=np.array([
            [[1, 0], [2, 0], [3, 0]],
            [[1, 0], [2, 0], [3, 0]],
            [[1, 0], [2, 0], [3, 0]],
            [[nan, nan], [5, 0], [nan, nan]],
            [[nan, nan], [nan, nan], [nan, nan]],
            [[1, 0], [0, 1], [5, 5]],
        ], np.float32),
        slot_team=np.array([HOME, AWAY, HOME], np.int8),
        pitch_m=(105.3, 68.0))
    got = challenge.nearest_team(tiny)
    assert got.tolist() == [HOME, AWAY, NO_TEAM, AWAY, NO_TEAM, HOME], got
    geo = challenge.observe(tiny, HalfId("tiny", 1, 0)).geometry
    inf = np.inf
    for have, want in ((geo.margin_m, [1, 0.8, nan, inf, nan, 0]), (geo.nearest_m, [1, 0.1, nan, 5, nan, 1]),
                       (geo.outside_m, [0, 0, nan, 0, nan, 0]), (geo.speed_mps, [0, 26.25, nan, 13.125, nan, 0])):
        assert np.allclose(have, want, atol=1e-5, equal_nan=True), have
    t = np.arange(40, dtype=np.float32)
    walkers = np.zeros((40, 3, 2), np.float32)
    walkers[:, 0, 0], walkers[:, 2, 0] = 0.1 * t, 0.04 * t
    walkers[30, 2] = np.nan
    paced = Geometry(np.zeros((40, 2), np.float32), walkers, np.array([HOME, AWAY, HOME], np.int8), (105.3, 68.0))
    want = [nan] * 12 + [1.0] * 6 + [1.25] + [1.0] * 9 + [nan] * 12
    assert np.allclose(challenge.observe(paced, HalfId("pace", 1, 0)).pace_mps, want, atol=1e-5, equal_nan=True)
    off = Geometry(np.array([[-3, -4], [106.3, 34], [50, 70]], np.float32), np.zeros((3, 2, 2), np.float32),
                   np.array([HOME, AWAY], np.int8), (105.3, 68.0))
    assert np.allclose(challenge.observe(off, HalfId("off", 1, 0)).geometry.outside_m, [5, 1, 2], atol=1e-5)

    rng = np.random.default_rng(0)
    n, s = 3000, 46
    players = (rng.random((n, s, 2)) * (105.3, 68.0)).astype(np.float32)
    players[rng.random((n, s)) < 0.3] = np.nan
    ball = (rng.random((n, 2)) * (105.3, 68.0)).astype(np.float32)
    ball[rng.random(n) < 0.2] = np.nan
    team = (np.arange(s) % 2).astype(np.int8)
    def observed(g: Geometry) -> list[bytes]:
        h = challenge.observe(g, HalfId("perm", 1, 0))
        assert np.array_equal(h.nearest_team, challenge.nearest_team(g))
        g = h.geometry
        return [a.tobytes() for a in (h.nearest_team, g.margin_m, g.nearest_m, g.outside_m, g.speed_mps)]

    base_geometry = Geometry(ball.copy(), players.copy(), team.copy(), (105.3, 68.0))
    base, base_all = challenge.nearest_team(base_geometry), observed(base_geometry)
    assert set(np.unique(base).tolist()) == {NO_TEAM, HOME, AWAY}

    perm = rng.permutation(s)
    whole = Geometry(ball.copy(), players[:, perm].copy(), team[perm].copy(), (105.3, 68.0))
    assert np.array_equal(challenge.nearest_team(whole), base)
    assert observed(whole) == base_all

    within = players.copy()
    for t in (HOME, AWAY):
        slots = np.flatnonzero(team == t)
        order = np.argsort(rng.random((n, len(slots))), axis=1)
        within[:, slots] = players[np.arange(n)[:, None], slots[order]]
    shuffled = Geometry(ball.copy(), within, team.copy(), (105.3, 68.0))
    assert np.array_equal(challenge.nearest_team(shuffled), base)
    assert observed(shuffled) == base_all

    padded = np.concatenate([players, np.full((n, 10, 2), np.nan, np.float32)], axis=1)
    pad_team = np.concatenate([team, np.zeros(10, np.int8)])
    assert np.array_equal(challenge.nearest_team(Geometry(ball.copy(), padded, pad_team, (105.3, 68.0))), base)
    assert observed(Geometry(ball.copy(), padded, pad_team, (105.3, 68.0))) == base_all

    swapped = observed(Geometry(ball.copy(), players.copy(), (1 - team).astype(np.int8), (105.3, 68.0)))
    assert swapped[1:] == base_all[1:], "BallGeometry must not change when the teams swap"
    tok = np.zeros(3, np.int8)
    bad = np.zeros(3, np.float32)
    _raises(ValueError, Half, HalfId("bad", 1, 0), tok, BallGeometry(bad, bad, bad, bad.astype(np.float64)))
    _raises(ValueError, Half, HalfId("bad", 1, 0), np.array([0, NO_TEAM, 1], np.int8), BallGeometry(bad, bad, bad, bad))


def baseline_raw_round_trip() -> None:
    halves = challenge.halves("baseline_raw")
    got = [(h.id.half, h.n, h.id.kickoff,
            int((h.nearest_team == NO_TEAM).sum()), int((h.nearest_team == HOME).sum()),
            int((h.nearest_team == AWAY).sum())) for h in halves]
    assert got == [(1, 79467, 0, 32304, 26971, 20192), (2, 79390, 2934, 32339, 26176, 20875)], got

    codes = score.read_codes(challenge.BASELINE_RAW, N_ROWS)
    assert (int((codes == D).sum()), int((codes != D).sum())) == (85831, 113488)
    whole = challenge.layout().assemble([np.where(h.nearest_team == NO_TEAM, D, h.nearest_team).astype(np.int8)
                                         for h in halves])
    inside = whole != X
    assert np.array_equal(whole[inside], codes[inside]), "halves do not map back onto baseline_raw rows"


def smoother_matches_published_baselines() -> None:
    toy = bench.smooth(np.array([NO_TEAM, HOME, AWAY, AWAY, NO_TEAM, NO_TEAM, NO_TEAM, HOME], dtype=np.int8), 1)
    assert toy.tolist() == [H, H, A, A, A, D, H, H], toy
    _raises(ValueError, bench.Smoother, -1)

    raw = score.read_codes(challenge.BASELINE_RAW, N_ROWS)
    tokens = np.where(raw == D, NO_TEAM, raw).astype(np.int8)
    layout, halves = challenge.layout(), challenge.halves("baseline_raw")
    for window in (0, 25, 50, 125):
        smoother = bench.Smoother(window)
        published = score.read_codes(challenge.BASELINE_RAW.with_name(f"{smoother.name}.csv"), N_ROWS)
        assert np.array_equal(bench.smooth(tokens, window), published), f"{smoother.name}: whole video"
        per_half = layout.assemble([smoother.decode(h).codes for h in halves])
        inside = per_half != X
        assert np.array_equal(per_half[inside], published[inside]), f"{smoother.name}: graded frames"


def atd_reproduces_baseline_raw() -> None:
    try:
        games.require(["atd_meta", "atd_raw"], challenge.GAME)
    except IOError:
        raise Skip(f"no ATD under {Path(games.DATA_DIR) / 'tactical'} (set MTAH_DATA_DIR)") from None
    for got, want in zip(challenge.halves("atd"), challenge.halves("baseline_raw")):
        assert got.id == want.id and got.n == want.n, (got.id, got.n, want.id, want.n)
        differ = int((got.nearest_team != want.nearest_team).sum())
        assert differ == 0, f"half {got.id.half}: {differ} of {got.n} tokens differ from baseline_raw"

    # nearest_team is blind to flips, origin shifts and uniform scale; these per-half means are not.
    means = [(51.04, 36.46, 55.24, 36.62), (51.28, 38.03, 49.72, 35.44)]
    for g, want in zip(challenge.load_geometry(), means):
        assert g.pitch_m == games.GAMES[challenge.GAME]["pitch"], g.pitch_m
        got = np.concatenate([np.nanmean(g.ball_xy, 0, dtype=np.float64),
                              np.nanmean(g.players_xy, (0, 1), dtype=np.float64)])
        assert np.allclose(got, want, atol=0.05), np.round(got, 2)


def measure_pins_calibration() -> None:
    try:
        games.require(["atd_meta", "atd_raw", "smart_tagging"], challenge.GAME)
    except IOError:
        raise Skip(f"no ATD or Smart Tagging under {Path(games.DATA_DIR) / 'tactical'} (set MTAH_DATA_DIR)") from None
    t = measure.timeline()
    # Measured 2026-10-23 by an independent probe: baseline_raw D rows (equal to the ATD mask) crossed
    # with starter.load_smart_tagging, without possession.measure or challenge.tags.
    cal = dropout.CALIBRATION
    window, pre = t.zone == measure.Zone.WINDOW, t.zone == measure.Zone.PRE_KICKOFF
    got = [(int(t.missing[window & (t.half == h)].sum()), int((window & (t.half == h)).sum())) for h in (1, 2)]
    assert got == [(32304, 79467), (31775, 76456)], got
    assert (int(t.missing[window].sum()), int(window.sum())) == (cal.window_missing, cal.window_frames)
    assert (int(t.missing[pre].sum()), int(pre.sum())) == (cal.prekickoff_missing, cal.prekickoff_frames)

    assert len(t.tags) == 638, len(t.tags)
    assert Counter(g.code for g in t.tags) == {
        "players in the box": 97, "ball in final third": 93, "ball in the box": 72, "progression": 66,
        "defending in middle third": 66, "set pieces": 59, "creating chances": 30, "defending in defensive third": 30,
        "long ball": 29, "attacking transition": 24, "defensive transition": 24, "build up": 22,
        "defending in attacking third": 22, "goals": 4}, Counter(g.code for g in t.tags)
    assert Counter(g.team for g in t.tags) == {HOME: 314, AWAY: 288, NO_TEAM: 36}
    kinds = Counter(g.kind for g in t.tags if g.code == challenge.SET_PIECES)
    assert kinds == {"throw-in": 26, "corner kick": 12, "goal kick": 10, "free kick": 5, "kick off (after goal)": 4,
                     "kick off (start)": 2}, kinds

    assert tuple(measure.estimate(t, measure.HEADLINE)) == (7125, 5214, 133098, 45069)
    phase = measure.estimate(t, measure.Proxy(5.0, complement="phase"))
    assert (phase.alive_frames, phase.alive_missing) == (50813, 11113), phase
    by_proxy = measure.estimates(t)
    sweep = [by_proxy[p].ratio for p in measure.SWEEP]
    kind = [by_proxy[p].ratio for p in measure.KIND_PROXIES]
    side = [round(float(np.median([by_proxy[p].ratio for p in measure.SWEEP if p.complement == c])), 4)
            for c in ("rest", "phase")]
    spread = (round(min(sweep), 4), round(float(np.median(sweep)), 4), round(max(sweep), 4))
    assert spread == (1.9986, 2.579, 3.4451) and side == [2.1215, 3.0481], (spread, side)
    assert (round(min(kind), 4), round(max(kind), 4)) == (1.4105, 2.9532), kind
    assert (cal.dead_bias, cal.dead_bias_bracket) == measure.calibrated(sweep) == (2.6, (1.0, 4.0)), spread
    last = tuple(measure._offset_section(t).table.set_index("offset_s").loc["[-5,0)", ["frames", "missing"]])
    assert last == (7125, 5214), last
    _aggregates_only(measure.tactical_sections(t))


def _aggregates_only(sections: list[measure.Section]) -> None:
    for s in sections:
        assert len(s.table) <= 80, f"{s.title!r} has {len(s.table)} rows; measure prints aggregates, not frame rows"
        s.render()


def public_window_crosstab() -> None:
    gt = score.read_codes(bench.PUBLIC_GT, N_ROWS)[11185:18685]
    first = challenge.layout().blocks[0].origin
    token = challenge.halves("baseline_raw")[0].nearest_team[11185 - first:18685 - first]
    table = [[int(((gt == g) & (token == t)).sum()) for t in (NO_TEAM, HOME, AWAY)] for g in (H, A, D)]
    assert table == [[5, 2750, 699], [386, 551, 1640], [494, 790, 185]], table


def decoder_known_answer() -> None:
    tok = _segments([(NO_TEAM, 120), (HOME, 600), (NO_TEAM, 300), (AWAY, 800), (HOME, 500)])
    swapped = np.where(tok == NO_TEAM, NO_TEAM, 1 - tok).astype(np.int8)
    emission = Tier0Emission(q=0.78, dead_bias=1.0, alive_share=0.6)
    for stride in (5, 1):
        model = Decoder(emission, DecoderParams(temper=0.05, poss_mean_s=6.0, dead_mean_s=10.0,
                                                p_dead_after_poss=0.25, p_flip_after_dead=0.7, stride=stride))
        out = model.decode(Half(HalfId("known_answer", 1, 120), tok))
        assert out.codes.dtype == np.int8 and out.codes.shape == (2320,), (out.codes.dtype, out.codes.shape)
        sw = _switches(out.codes)
        assert out.codes[0] == D and len(sw) == 3, (stride, sw)
        assert sw[0] == (120, D, H) and sw[2] == (1820, A, H), (stride, sw)
        assert sw[1][1:] == (H, A) and abs(sw[1][0] - 870) <= stride, (stride, sw)
        assert np.array_equal(out.posterior[:120], np.tile(np.float32([0, 0, 1]), (120, 1)))

        again = model.decode(Half(HalfId("known_answer", 1, 120), tok.copy()))
        assert again.codes.tobytes() == out.codes.tobytes()
        assert again.posterior.tobytes() == out.posterior.tobytes()

        mirrored = model.decode(Half(HalfId("known_answer", 1, 120), swapped)).codes
        assert np.array_equal(mirrored, np.where(out.codes == D, D, 1 - out.codes)), stride

    model = Decoder(emission, DecoderParams(stride=1, decode_rule="map", min_poss_frames=25, min_dead_frames=50))
    decoded = model.decode(Half(HalfId("known_answer", 1, 120), tok))
    assert decoded.posterior is None
    sw = _switches(decoded.codes)
    assert len(sw) == 3 and sw[0] == (120, D, H) and sw[2] == (1820, A, H), sw
    assert sw[1][1:] == (H, A) and 720 <= sw[1][0] <= 1020, sw

    blind_half = Half(HalfId("blind", 1, 10), np.full(3000, NO_TEAM, np.int8))
    blind = Decoder(emission, DecoderParams(stride=1)).decode(blind_half)
    assert _switches(blind.codes) == [(10, D, H)], _switches(blind.codes)


def marginal_equals_enumeration() -> None:
    trans = decoder._chain(DecoderParams(poss_mean_s=6.0, dead_mean_s=10.0, p_dead_after_poss=0.25,
                                         p_flip_after_dead=0.7, stride=5)).trans
    hp, hd = 1 / 30, 1 / 50
    expected = [[1 - hp, hp * 0.75, hp * 0.25, 0], [hp * 0.75, 1 - hp, 0, hp * 0.25],
                [hd * 0.3, hd * 0.7, 1 - hd, 0], [hd * 0.7, hd * 0.3, 0, 1 - hd]]
    assert np.allclose(trans, expected, rtol=0, atol=1e-15), trans

    rng = np.random.default_rng(0)
    nb = 7
    paths = np.array(np.meshgrid(*[np.arange(decoder.N_STATES)] * nb, indexing="ij")).reshape(nb, -1).T
    for trial in range(20):
        p = DecoderParams(poss_mean_s=0.2 + trial * 0.05, dead_mean_s=0.15 + trial * 0.03,
                          p_dead_after_poss=0.1 + trial * 0.04, p_flip_after_dead=0.85 - trial * 0.03, stride=1)
        chain = decoder._chain(p)
        E = rng.normal(0.0, 1.0, size=(nb, 3))
        weight = chain.init[paths[:, 0]] * np.exp(E[0, decoder.STATE_LABEL[paths[:, 0]]])
        for t in range(1, nb):
            step = chain.trans[paths[:, t - 1], paths[:, t]]
            weight = weight * step * np.exp(E[t, decoder.STATE_LABEL[paths[:, t]]])
        labels = decoder.STATE_LABEL[paths]
        brute = np.stack([[weight[labels[:, t] == k].sum() for k in (H, A, D)] for t in range(nb)])
        brute /= brute.sum(axis=1, keepdims=True)
        got = decoder._forward_backward(E, chain)
        assert np.abs(got - brute).max() < 1e-12, (trial, np.abs(got - brute).max())


def params_load_guards() -> None:
    v0 = Decoder.load(PARAMS_V0)
    assert v0 == Decoder(Tier0Emission(), DecoderParams()), v0
    assert v0.replace(dead_bias=3.0, temper=0.1).fields() == {**v0.fields(), "dead_bias": 3.0, "temper": 0.1}
    _raises(ValueError, Tier0Emission, q=1.0)
    _raises(ValueError, DecoderParams, stride=0)
    _raises(ValueError, v0.replace, decode_rule="map", poss_mean_s=1.0, min_poss_frames=25)
    text = PARAMS_V0.read_text()
    doc = json.loads(text)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "p.json"
        v0.save(path, doc["provenance"])
        assert path.read_text() == text

        def load_with(section: str, **change) -> Decoder:
            edited = json.loads(text)
            for key, value in change.items():
                if value is None:
                    del edited[section][key]
                else:
                    edited[section][key] = value
            path.write_text(json.dumps(edited))
            return Decoder.load(path)

        _raises(ValueError, load_with, "params", temper=None)
        _raises(ValueError, load_with, "params", smoothing=3)
        _raises(ValueError, load_with, "emission", q=1.0)
        _raises(ValueError, load_with, "params", stride=0)
        _raises(ValueError, load_with, "params", min_poss_frames=25)
        _raises(ValueError, load_with, "params", decode_rule="map", stride=5, poss_mean_s=1.0, min_poss_frames=25)
        ok = load_with("params", decode_rule="map", stride=5, poss_mean_s=1.2, min_poss_frames=25)
        assert (ok.params.decode_rule, ok.params.min_poss_frames) == ("map", 25), ok.params


def geometry_emission_known_answer() -> None:
    nan, inf = np.nan, np.inf
    tok = np.array([NO_TEAM, HOME, AWAY, HOME, AWAY, HOME], np.int8)
    geo = BallGeometry(margin_m=np.array([nan, 0, 3, inf, 3, 1], np.float32),
                       nearest_m=np.array([nan, 1, 12, 2, 2, 2], np.float32),
                       outside_m=np.array([nan, 0, 0, 2, 0.5, 0], np.float32),
                       speed_mps=np.array([nan, 0, 10, 50, 3, 1], np.float32))
    half = Half(HalfId("geo", 1, 0), tok, geo)
    plain = Tier0Emission(q=0.8)
    on = Tier0Emission(q=0.8, q_logit_a=1.0, q_logit_dist=-1.0, q_logit_margin=0.5)
    assert not plain.needs_geometry and on.needs_geometry
    _raises(ValueError, on.loglik, Half(HalfId("geo", 1, 0), tok))
    assert np.array_equal(plain.loglik(half), plain.loglik(Half(HalfId("geo", 1, 0), tok)))
    base, got = plain.loglik(half).astype(np.float64), on.loglik(half).astype(np.float64)
    qm = np.array([0.576116885, 0.294879445, 0.834571772, 0.644404983, 0.561674644])
    home = tok[1:] == HOME
    want = np.log(np.stack([np.where(home, qm, 1 - qm), np.where(home, 1 - qm, qm)], 1)) + math.log(5 / 6)
    assert np.allclose(got[1:, :2], want, atol=1e-6), (got[1:, :2], want)
    assert np.array_equal(got[:, 2], base[:, 2]) and np.array_equal(got[0], base[0])
    mirrored = on.loglik(Half(HalfId("geo", 1, 0), np.where(tok == NO_TEAM, NO_TEAM, 1 - tok).astype(np.int8), geo))
    assert np.array_equal(mirrored, on.loglik(half)[:, [1, 0, 2]])
    fast = Tier0Emission(q=0.8, q_logit_a=1.0, q_logit_dist=-1.0, q_logit_margin=0.5, q_logit_speed=-0.5,
                         q_logit_dist_speed=0.25)
    qs = np.array([0.576116885, 0.369787202, 0.686011764, 0.570070236, 0.522924595])
    want = np.log(np.stack([np.where(home, qs, 1 - qs), np.where(home, 1 - qs, qs)], 1)) + math.log(5 / 6)
    assert np.allclose(fast.loglik(half).astype(np.float64)[1:, :2], want, atol=1e-6)

    tok = np.array([HOME] * 4 + [AWAY] * 6 + [HOME] * 4, np.int8)
    out = np.zeros(14, np.float32)
    out[5:8] = (2.0, 0.5, 3.0)
    geo = BallGeometry(np.ones(14, np.float32), np.ones(14, np.float32), out, np.ones(14, np.float32))
    rule = Decoder(Tier0Emission(), DecoderParams(dead_min_run=3, dead_trim=0, dead_outside_m=1.0))
    assert rule.needs_geometry and not rule.replace(dead_min_run=0, dead_outside_m=0.0).needs_geometry
    _raises(ValueError, rule.replace, dead_min_run=0)
    _raises(ValueError, rule.decode, Half(HalfId("dead", 1, 0), tok))
    codes = rule.decode(Half(HalfId("dead", 1, 0), tok, geo)).codes
    assert (codes[5:8] != D).all(), codes
    codes = rule.replace(dead_outside_m=0.4).decode(Half(HalfId("dead", 1, 0), tok, geo)).codes
    assert (codes[5:8] == D).all() and (codes[:5] != D).all() and (codes[8:] != D).all(), codes

    v0 = Decoder.load(PARAMS_V0)
    model = v0.replace(q_logit_a=1.0, q_logit_dist=-1.0, q_logit_margin=0.5)
    assert model.emission.q_logit_dist == -1.0 and model.params == v0.params
    with tempfile.TemporaryDirectory() as tmp:
        path = model.save(Path(tmp) / "geo.json", {})
        emission = json.loads(path.read_text())["emission"]
        assert set(emission) == {"kind", "q", "dead_bias", "alive_share", "q_logit_a", "q_logit_dist",
                                 "q_logit_margin"}, emission
        assert Decoder.load(path) == model


def dead_run_rule_known_answer() -> None:
    """decoder._missing_run_dead on hand-built halves: run length, trim, half edges, dead_close, kickoff,
    the team fill, H/A mirroring and the lead cuts, each against a literal answer."""
    code = {"H": H, "A": A, "D": D}
    letter = {v: k for k, v in code.items()}

    def rule(codes: str, missing: list[range], kickoff: int = 0, **params: int) -> str:
        tok = np.full(len(codes), HOME, np.int8)
        for r in missing:
            tok[r.start:r.stop] = NO_TEAM
        out = decoder._missing_run_dead(np.array([code[c] for c in codes], np.int8),
                                        Half(HalfId("rule", 1, kickoff), tok), DecoderParams(**params))
        return "".join(letter[int(c)] for c in out)

    h20, a20 = "H" * 20, "A" * 20
    two_runs = [range(5, 10), range(13, 17)]
    assert rule(h20, two_runs, dead_min_run=5) == "HHHHHDDDDDHHHHHHHHHH"
    assert rule(h20, two_runs, dead_min_run=5, dead_trim=1) == "HHHHHHDDDHHHHHHHHHHH"
    assert rule(h20, [range(0, 1), range(19, 20)], dead_min_run=5) == "DHHHHHHHHHHHHHHHHHHD"
    gap = [range(2, 8), range(10, 16)]
    assert rule(a20, gap, dead_min_run=5, dead_close=3) == "AADDDDDDDDDDDDDDAAAA"
    assert rule(a20, gap, dead_min_run=5, dead_close=2) == "AADDDDDDAADDDDDDAAAA"
    assert rule("DDD" + "H" * 17, [range(5, 10)], kickoff=3, dead_min_run=5, dead_close=10) == "DDDHHDDDDDHHHHHHHHHH"
    assert rule("HHDDDAAAAA", [], dead_min_run=5) == "HHHHHAAAAA"
    mixed = "HHDDHHAADDAAHHAADDAA"
    swap = str.maketrans("HA", "AH")
    assert (rule(mixed.translate(swap), gap, dead_min_run=5, dead_close=3)
            == rule(mixed, gap, dead_min_run=5, dead_close=3).translate(swap))
    assert rule(h20, two_runs, dead_min_run=5, dead_trim=1, dead_lead_cut=1) == "HHHHHDDDDHHHHHHHHHHH"
    assert rule(h20, [range(0, 7)], dead_min_run=5, dead_trim=2, dead_lead_cut=2) == "DDDDDHHHHHHHHHHHHHHH"
    assert rule(h20, [range(5, 9)], dead_min_run=5, dead_trim=2, dead_lead_cut=2) == h20
    _raises(ValueError, DecoderParams, dead_min_run=5, dead_trim=2, dead_lead_cut=3)
    _raises(ValueError, DecoderParams, dead_min_run=5, dead_trim=2, dead_out_lead_cut=1)

    tok = np.full(20, HOME, np.int8)
    tok[6:14] = NO_TEAM
    seen = np.where(tok == NO_TEAM, np.nan, 1.0).astype(np.float32)
    inside = np.where(tok == NO_TEAM, np.nan, 0.0).astype(np.float32)
    left = inside.copy()
    left[5] = 3.0

    def lead(outside: np.ndarray, **params: int) -> str:
        half = Half(HalfId("lead", 1, 0), tok, BallGeometry(seen, seen, outside, seen))
        p = DecoderParams(dead_min_run=5, dead_trim=2, dead_outside_m=1.0, **params)
        return "".join(letter[int(c)] for c in decoder._missing_run_dead(np.full(20, H, np.int8), half, p))

    assert lead(left) == "HHHHHHHDDDDDHHHHHHHH"
    assert lead(left, dead_out_lead_cut=2) == "HHHHHDDDDDDDHHHHHHHH"
    assert lead(left, dead_out_lead_cut=1) == "HHHHHHDDDDDDHHHHHHHH"
    assert lead(inside, dead_out_lead_cut=2) == "HHHHHHHHDDDDHHHHHHHH"
    assert lead(inside, dead_lead_cut=2) == "HHHHHHDDDDDDHHHHHHHH"

    def short(outside: np.ndarray, **params: int) -> str:
        half = Half(HalfId("short", 1, 0), tok, BallGeometry(seen, seen, outside, seen))
        p = DecoderParams(dead_min_run=12, dead_trim=2, dead_outside_m=1.0, **params)
        return "".join(letter[int(c)] for c in decoder._missing_run_dead(np.full(20, H, np.int8), half, p))

    assert short(left) == h20 and short(inside, dead_out_min_run=8) == h20
    assert short(left, dead_out_min_run=8) == "HHHHHHHDDDDDHHHHHHHH"
    assert short(left, dead_out_min_run=8, dead_out_lead_cut=2) == "HHHHHDDDDDDDHHHHHHHH"
    _raises(ValueError, DecoderParams, dead_min_run=12, dead_trim=2, dead_out_min_run=8)
    _raises(ValueError, DecoderParams, dead_min_run=12, dead_trim=2, dead_outside_m=1.0, dead_out_min_run=13)

    lines = np.where(tok == NO_TEAM, np.nan, 20.0).astype(np.float32)

    def line(at5: float = 1.5, **params: float) -> str:
        geo = lines.copy()
        geo[5] = at5
        half = Half(HalfId("line", 1, 0), tok, BallGeometry(seen, seen, inside, seen, geo))
        p = DecoderParams(dead_min_run=12, dead_trim=2, **params)
        return "".join(letter[int(c)] for c in decoder._missing_run_dead(np.full(20, H, np.int8), half, p))

    assert line() == h20 and line(dead_line_m=1.0, dead_line_min_run=8) == h20
    assert line(dead_line_m=2.0, dead_line_min_run=8) == "HHHHHHHHDDDDHHHHHHHH"
    assert line(dead_line_m=2.0, dead_line_min_run=8, dead_line_lead_cut=2) == "HHHHHHDDDDDDHHHHHHHH"
    assert line(-0.5, dead_line_m=1.0, dead_line_min_run=8) == "HHHHHHHHDDDDHHHHHHHH"
    _raises(ValueError, DecoderParams, dead_min_run=12, dead_trim=2, dead_line_lead_cut=2)
    _raises(ValueError, DecoderParams, dead_min_run=12, dead_trim=2, dead_line_m=2.0)
    _raises(ValueError, DecoderParams, dead_min_run=12, dead_trim=2, dead_line_m=2.0, dead_line_min_run=13)
    no_line = Half(HalfId("line", 1, 0), tok, BallGeometry(seen, seen, inside, seen))
    _raises(ValueError, decoder._missing_run_dead, np.full(20, H, np.int8), no_line,
            DecoderParams(dead_min_run=12, dead_trim=2, dead_line_m=2.0, dead_line_min_run=8))

    zero = np.zeros(2, np.float32)
    rel = np.array([0.0, math.e - 1], np.float32)
    two = Half(HalfId("rel", 1, 0), np.array([HOME, HOME], np.int8), BallGeometry(zero, zero, zero, zero, zero, rel))
    ll = Tier0Emission(q_logit_a=1.0, q_logit_rel=-1.0).loglik(two).astype(np.float64)
    assert abs((ll[0, 0] - ll[1, 0]) - (-math.log1p(math.exp(-1.0)) - math.log(0.5))) < 1e-5
    _raises(ValueError, Tier0Emission(q_logit_a=1.0, q_logit_rel=-1.0).loglik,
            Half(HalfId("rel", 1, 0), np.array([HOME, HOME], np.int8), BallGeometry(zero, zero, zero, zero)))

    tok = np.full(20, HOME, np.int8)
    tok[13:17] = NO_TEAM
    speed = np.full(20, 5.0, np.float32)
    speed[5:13] = 0.2
    one = np.ones(20, np.float32)
    geo = BallGeometry(*(np.where(tok == NO_TEAM, np.nan, a).astype(np.float32) for a in (one, one, 0 * one, speed)))
    still = Half(HalfId("still", 1, 0), tok, geo)

    def still_rule(frames: int) -> str:
        p = DecoderParams(dead_min_run=10, dead_still_mps=1.0, dead_still_frames=frames)
        return "".join(letter[int(c)] for c in decoder._missing_run_dead(np.full(20, H, np.int8), still, p))

    assert still_rule(6) == "HHHHH" + "D" * 12 + "HHH"
    assert still_rule(9) == "H" * 20
    _raises(ValueError, DecoderParams, dead_min_run=10, dead_still_mps=1.0)
    _raises(ValueError, DecoderParams, dead_still_mps=1.0, dead_still_frames=6)
    _raises(ValueError, decoder._missing_run_dead, np.full(20, H, np.int8), Half(still.id, tok),
            DecoderParams(dead_min_run=10, dead_still_mps=1.0, dead_still_frames=6))
    assert Decoder(Tier0Emission(), DecoderParams(dead_min_run=10, dead_still_mps=1.0, dead_still_frames=6)).needs_geometry

    tok = np.full(20, HOME, np.int8)
    tok[3:18] = NO_TEAM
    pace = np.full(20, 0.5, np.float32)
    pace[8:12] = 2.8
    paced = Half(HalfId("pace", 1, 0), tok, pace_mps=pace)

    def pace_rule(**params: float) -> str:
        p = DecoderParams(dead_min_run=10, **params)
        return "".join(letter[int(c)] for c in decoder._missing_run_dead(np.full(20, H, np.int8), paced, p))

    assert pace_rule() == "HHH" + "D" * 15 + "HH"
    assert pace_rule(dead_pace_live_mps=2.0) == "H" * 20
    assert pace_rule(dead_pace_still_mps=0.75) == "D" * 20
    assert pace_rule(dead_pace_live_mps=2.0, dead_pace_still_mps=0.75) == "D" * 8 + "HHHH" + "D" * 8
    _raises(ValueError, decoder._missing_run_dead, np.full(20, H, np.int8), Half(paced.id, tok),
            DecoderParams(dead_min_run=10, dead_pace_still_mps=0.75))
    _raises(ValueError, DecoderParams, dead_pace_live_mps=2.0)

    model = Decoder(Tier0Emission(), DecoderParams(dead_min_run=126, dead_trim=25, dead_close=200, dead_outside_m=0.5))
    with tempfile.TemporaryDirectory() as tmp:
        path = model.save(Path(tmp) / "rule.json", {})
        params = json.loads(path.read_text())["params"]
        assert {k: params[k] for k in ("dead_min_run", "dead_trim", "dead_close", "dead_outside_m")} == \
            {"dead_min_run": 126, "dead_trim": 25, "dead_close": 200, "dead_outside_m": 0.5}, params
        assert Decoder.load(path) == model


def handover_lag_known_answer() -> None:
    """decoder._lag_handovers inside runs of team calls, H/A mirroring, the decode path and the save."""
    code = {"H": H, "A": A, "D": D}
    letter = {v: k for k, v in code.items()}

    def lag(codes: str, n: int) -> str:
        return "".join(letter[int(c)] for c in decoder._lag_handovers(np.array([code[c] for c in codes], np.int8), n))

    assert lag("DHHHAAAAAHHH", 2) == "DHHHHHAAAAAH"
    assert lag("HHAADAAHHDHA", 3) == "HHHHDAAAADHH"
    assert lag("HHAADAAHHDHA", 0) == "HHAADAAHHDHA"
    swap = str.maketrans("HA", "AH")
    assert lag("HAHHAAADHAAH".translate(swap), 2) == lag("HAHHAAADHAAH", 2).translate(swap)
    tok = np.array([HOME] * 5 + [AWAY] * 15, np.int8)
    half = Half(HalfId("lag", 1, 0), tok)
    base = Decoder(Tier0Emission(), DecoderParams(temper=1.0))
    plain = base.decode(half)
    lagged = base.replace(handover_lag=4).decode(half)
    assert lagged.posterior is None and plain.posterior is not None
    assert plain.codes.tolist() == [H] * 5 + [A] * 15 and lagged.codes.tolist() == [H] * 9 + [A] * 11
    model = base.replace(handover_lag=15)
    with tempfile.TemporaryDirectory() as tmp:
        assert json.loads(model.save(Path(tmp) / "lag.json", {}).read_text())["params"]["handover_lag"] == 15
        assert "handover_lag" not in json.loads(base.save(Path(tmp) / "off.json", {}).read_text())["params"]
        assert Decoder.load(Path(tmp) / "lag.json") == model


def spell_merge_known_answer() -> None:
    """decoder._merge_spells: interior and tail merges, shortest first, D boundaries, mirroring, decode and save."""
    code = {"H": H, "A": A, "D": D}
    letter = {v: k for k, v in code.items()}

    def merge(codes: str, frames: int, tails: int = 0) -> str:
        out = decoder._merge_spells(np.array([code[c] for c in codes], np.int8), frames, tails)
        return "".join(letter[int(c)] for c in out)

    assert merge("HHHHAAHHHH", 3) == "HHHHHHHHHH"
    assert merge("DAAHHHH", 3) == "DAAHHHH"
    assert merge("HHHHAADD", 3) == "HHHHAADD"
    assert merge("HHHHAADD", 3, 1) == "HHHHHHDD"
    assert merge("HHHHHAHHAHHHHH", 3) == "H" * 14
    assert merge("HHHHHAAHHHAAAAA", 4) == "H" * 10 + "A" * 5
    assert merge("HHHHAAHHHH", 0) == "HHHHAAHHHH"
    swap = str.maketrans("HA", "AH")
    assert merge("HHAHHDAHAAAH".translate(swap), 2, 1) == merge("HHAHHDAHAAAH", 2, 1).translate(swap)
    tok = np.array([HOME] * 10 + [AWAY] * 2 + [HOME] * 10, np.int8)
    base = Decoder(Tier0Emission(q=0.99), DecoderParams(temper=1.0, poss_mean_s=0.2, stride=1))
    assert base.decode(Half(HalfId("merge", 1, 0), tok)).codes.tolist() == [H] * 10 + [A] * 2 + [H] * 10
    merged = base.replace(spell_merge_frames=3).decode(Half(HalfId("merge", 1, 0), tok))
    assert merged.posterior is None and merged.codes.tolist() == [H] * 22
    for bad in ({"spell_merge_tails": 1}, {"spell_merge_frames": 3, "spell_merge_tails": 2}):
        try:
            DecoderParams(**bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} was accepted")
    model = base.replace(spell_merge_frames=50, spell_merge_tails=1)
    with tempfile.TemporaryDirectory() as tmp:
        saved = json.loads(model.save(Path(tmp) / "merge.json", {}).read_text())["params"]
        assert (saved["spell_merge_frames"], saved["spell_merge_tails"]) == (50, 1)
        assert "spell_merge_frames" not in json.loads(base.save(Path(tmp) / "off.json", {}).read_text())["params"]
        assert Decoder.load(Path(tmp) / "merge.json") == model


def spell_push_known_answer() -> None:
    """decoder._push_flip: short runs push contradicts change team, judged on the input runs; length limit,
    threshold, the between-only switch, D runs and NaN push left alone; mirroring, decode and save."""
    code = {"H": H, "A": A, "D": D}
    letter = {v: k for k, v in code.items()}

    def flip(codes: str, push: list, mps: float, frames: int, between: int = 0, unseen: float = 0.0,
             tok: list | None = None) -> str:
        tok = np.full(len(codes), NO_TEAM, np.int8) if tok is None else np.array(tok, np.int8)
        half = Half(HalfId("push", 1, 0), tok, push_mps=np.array(push, np.float32))
        p = DecoderParams(spell_push_mps=mps, spell_push_frames=frames, spell_push_between=between,
                          spell_push_unseen=unseen)
        out = decoder._push_flip(np.array([code[c] for c in codes], np.int8), half, p)
        return "".join(letter[int(c)] for c in out)

    assert flip("HHHAAHHH", [0, 0, 0, 3, 3, 0, 0, 0], 2.0, 3) == "HHHHHHHH"
    assert flip("HHHAAHHH", [0, 0, 0, 1, 1, 0, 0, 0], 2.0, 3) == "HHHAAHHH"
    assert flip("HHHAAHHH", [0, 0, 0, 3, 3, 0, 0, 0], 2.0, 2) == "HHHAAHHH"
    assert flip("AAAHHAAA", [0, 0, 0, -3, -3, 0, 0, 0], 2.0, 3) == "AAAAAAAA"
    assert flip("DDDAAHHH", [0, 0, 0, 3, 3, 0, 0, 0], 2.0, 3) == "DDDHHHHH"
    assert flip("DDDAAHHH", [0, 0, 0, 3, 3, 0, 0, 0], 2.0, 3, 1) == "DDDAAHHH"
    assert flip("HHHDDHHH", [0, 0, 0, -9, -9, 0, 0, 0], 2.0, 3) == "HHHDDHHH"
    assert flip("HHHAAHHH", [0, 0, 0, np.nan, np.nan, 0, 0, 0], 2.0, 3) == "HHHAAHHH"
    assert flip("HAHAH", [-3, 3, -3, 3, -3], 2.0, 2) == "AHAHA"
    seen_a = [NO_TEAM] * 3 + [AWAY, AWAY] + [NO_TEAM] * 3
    half_a = [NO_TEAM] * 3 + [AWAY, NO_TEAM] + [NO_TEAM] * 3
    assert flip("HHHAAHHH", [0, 0, 0, 3, 3, 0, 0, 0], 2.0, 3, unseen=0.5, tok=seen_a) == "HHHAAHHH"
    assert flip("HHHAAHHH", [0, 0, 0, 3, 3, 0, 0, 0], 2.0, 3, unseen=0.5, tok=half_a) == "HHHHHHHH"
    assert flip("HHHAAHHH", [0, 0, 0, 3, 3, 0, 0, 0], 2.0, 3, unseen=0.8, tok=half_a) == "HHHAAHHH"
    swap = str.maketrans("HA", "AH")
    pushes = [0, 0, 0, 3, 3, 0, 2.5, 0, 0]
    assert flip("HHHAAHAHH".translate(swap), [-x for x in pushes], 2.0, 3) == flip("HHHAAHAHH", pushes, 2.0, 3).translate(swap)
    tok = np.array([HOME] * 10 + [AWAY] * 2 + [HOME] * 10, np.int8)
    push = np.array([0] * 10 + [4, 4] + [0] * 10, np.float32)
    base = Decoder(Tier0Emission(q=0.99), DecoderParams(temper=1.0, poss_mean_s=0.2, stride=1))
    flipped = base.replace(spell_push_mps=2.0, spell_push_frames=3).decode(Half(HalfId("push", 1, 0), tok, push_mps=push))
    assert flipped.posterior is None and flipped.codes.tolist() == [H] * 22
    assert base.replace(spell_push_mps=2.0, spell_push_frames=3).needs_geometry and not base.needs_geometry
    for bad in ({"spell_push_mps": 2.0}, {"spell_push_frames": 3}, {"spell_push_between": 1},
                {"spell_push_mps": 2.0, "spell_push_frames": 3, "spell_push_between": 2}, {"spell_push_unseen": 0.5},
                {"spell_push_mps": 2.0, "spell_push_frames": 3, "spell_push_unseen": 1.5}):
        try:
            DecoderParams(**bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} was accepted")
    model = base.replace(spell_push_mps=2.0, spell_push_frames=125, spell_push_between=1)
    with tempfile.TemporaryDirectory() as tmp:
        saved = json.loads(model.save(Path(tmp) / "push.json", {}).read_text())["params"]
        assert (saved["spell_push_mps"], saved["spell_push_frames"], saved["spell_push_between"]) == (2.0, 125, 1)
        assert "spell_push_mps" not in json.loads(base.save(Path(tmp) / "off.json", {}).read_text())["params"]
        assert Decoder.load(Path(tmp) / "push.json") == model


def switch_penalty_known_answer() -> None:
    """decoder._penalized_path: a team run survives only when its summed log-odds reach 2 * lam, a hand-over
    through D is charged once, a D blip inside a team run is free, H/A mirror; decode, guards and save."""
    def path(g: list, lam: float) -> list:
        return decoder._penalized_path(np.array(g, np.float64), lam).tolist()

    h, a = [0.9, 0.05, 0.05], [0.05, 0.9, 0.05]
    island = [h] * 4 + [[0.4, 0.6, 0.0]] * 3 + [h] * 4
    assert path(island, 1.0) == [H] * 11
    assert path(island, 0.5) == [H] * 4 + [A] * 3 + [H] * 4
    assert path([[r[1], r[0], r[2]] for r in island], 1.0) == [A] * 11
    assert path([h] * 3 + [[0.3, 0.3, 0.4]] * 2 + [a] * 3, 5.0) == [H] * 3 + [D] * 2 + [A] * 3
    assert path([h] * 3 + [[0.2, 0.2, 0.6]] * 2 + [h] * 3, 5.0) == [H] * 3 + [D] * 2 + [H] * 3
    tok = np.array([HOME] * 10 + [AWAY] * 2 + [HOME] * 10, np.int8)
    half = Half(HalfId("switch", 1, 0), tok)
    base = Decoder(Tier0Emission(q=0.99), DecoderParams(temper=1.0, poss_mean_s=0.2, stride=1))
    assert base.decode(half).codes.tolist() == [H] * 10 + [A] * 2 + [H] * 10
    kept, gone = base.replace(switch_penalty=3.0).decode(half), base.replace(switch_penalty=4.0).decode(half)
    assert kept.posterior is None and kept.codes.tolist() == [H] * 10 + [A] * 2 + [H] * 10
    assert gone.codes.tolist() == [H] * 10 + [D] * 2 + [H] * 10
    for bad in ({"switch_penalty": -1.0}, {"switch_penalty": 1.0, "decode_rule": "map"}):
        try:
            DecoderParams(**bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} was accepted")
    model = base.replace(switch_penalty=1.0)
    with tempfile.TemporaryDirectory() as tmp:
        assert json.loads(model.save(Path(tmp) / "sw.json", {}).read_text())["params"]["switch_penalty"] == 1.0
        assert "switch_penalty" not in json.loads(base.save(Path(tmp) / "off.json", {}).read_text())["params"]
        assert Decoder.load(Path(tmp) / "sw.json") == model


def spell_flip_known_answer() -> None:
    """decoder._spell_flip: a short run takes the other team when the spell logit over its features reaches
    logit(spell_flip_p); feature values, the length limit, the token-share gate, D runs, mirroring, the
    exactly rounded logit, decode, guards and save."""
    code = {"H": H, "A": A, "D": D}
    letter = {v: k for k, v in code.items()}
    zero = dict.fromkeys(("a",) + decoder.SPELL_FEATURES, 0.0)

    def half(codes: str, near: float = 3.0, swap: bool = False) -> Half:
        tok = np.array([{"H": HOME, "A": AWAY, "D": NO_TEAM}[c] for c in codes], np.int8)
        tok = np.where(tok == NO_TEAM, NO_TEAM, 1 - tok).astype(np.int8) if swap else tok
        n, gap = len(codes), tok == NO_TEAM
        geo = BallGeometry(*(np.where(gap, np.nan, v).astype(np.float32) for v in (2.0, near, 0.0, 5.0)))
        return Half(HalfId("flip", 1, 0), tok, geo, pace_mps=np.ones(n, np.float32),
                    push_mps=np.zeros(n, np.float32))

    def flip(codes: str, cut: float, frames: int = 4, seen: float = 0.0, near: float = 3.0, swap: bool = False,
             tok_codes: str | None = None, adjacent: bool = False, len_w: float = 0.0) -> str:
        p = DecoderParams(spell_flip_p=cut, spell_flip_frames=frames, spell_flip_seen=seen,
                          spell_logit={**zero, "a": -1.0, "closest_own": 1.0, "len": len_w},
                          spell_flip_adjacent=adjacent)
        h = half(tok_codes or codes, near, swap)
        out = decoder._spell_flip(np.array([code[c] for c in codes], np.int8), h, p, np.zeros(len(codes)))
        return "".join(letter[int(c)] for c in out)

    (a, b, team, x), = [r for r in decoder._spell_runs(np.array([code[c] for c in "HHHHHAAAHHHHH"], np.int8),
                                                        half("HHHHHAAAHHHHH"), 4, np.zeros(13))]
    assert (a, b, team) == (5, 8, A)
    assert x == tuple(round(v, 9) for v in (math.log(3 / 25), 1.0, 1.0, 0.0, math.log1p(3.0), math.log1p(5.0),
                                            math.log1p(5.0), math.log1p(2.0), 0.0, 0.0, 1.0, math.log1p(5),
                                            math.log1p(5), 0.0, 0.0, 0.0, 0.0, 0.0)), x
    assert flip("HHHHHAAAHHHHH", 0.5) == "HHHHHHHHHHHHH"
    assert flip("HHHHHAAAHHHHH", 0.65) == "HHHHHAAAHHHHH"
    assert flip("HHHHHAAAHHHHH", 0.5, frames=3) == "HHHHHAAAHHHHH"
    assert flip("HHHHHAAAHHHHH", 0.5, near=1.0) == "HHHHHAAAHHHHH"
    assert flip("HHHHHAAAHHHHH", 0.5, seen=0.5, tok_codes="HHHHHADDHHHHH") == "HHHHHAAAHHHHH"
    assert flip("HHHHHAAAHHHHH", 0.5, seen=0.3, tok_codes="HHHHHADDHHHHH") == "HHHHHHHHHHHHH"
    assert flip("HHHHHDDDHHHHH", 0.5) == "HHHHHDDDHHHHH"
    assert flip("AAAAAHHHAAAAA", 0.5, swap=True) == "AAAAAAAAAAAAA"
    assert flip("HHHHHAAAHHHAAAAA", 0.5) == "HHHHHHHHAAAAAAAA"
    assert flip("HHHHHAAAHHHAAAAA", 0.5, adjacent=True) == "HHHHHHHHHHHAAAAA"
    assert flip("HHHHHAAAHHAAAAA", 0.5, len_w=-1.0) == "HHHHHHHHAAAAAAA"
    assert flip("HHHHHAAAHHAAAAA", 0.5, len_w=-1.0, adjacent=True) == "HHHHHAAAAAAAAAA"
    assert flip("HHHHHAAAHHHHH", 0.5, adjacent=True) == "HHHHHHHHHHHHH"
    assert flip("HHHHHAAAHHHAAAHHHHH", 0.5) == "HHHHHHHHAAAHHHHHHHH"
    assert flip("HHHHHAAAHHHAAAHHHHH", 0.5, adjacent=True) == "HHHHHHHHHHHHHHHHHHH"
    assert decoder._spell_z((1.0,) * len(decoder.SPELL_FEATURES), dict.fromkeys(zero, 0.1)) == 1.9
    assert decoder._spell_z((1.0,) * len(decoder.SPELL_FEATURES), {"a": 0.5, "len": 1.0}) == 1.5
    kick = half("HHHHHAAAHHHHH", near=1.0)
    speed = np.full(13, 5.0, np.float32)
    speed[11] = 15.0
    kick = Half(kick.id, kick.nearest_team, BallGeometry(kick.geometry.margin_m, kick.geometry.nearest_m,
                kick.geometry.outside_m, speed), pace_mps=kick.pace_mps, push_mps=kick.push_mps)
    (*_, xk), = decoder._spell_runs(np.array([code[c] for c in "HHHHHAAAHHHHH"], np.int8), kick, 4, np.zeros(13))
    assert xk[-4:] == (round(math.log1p(10.0), 9), 0.0, 0.0, 0.0), xk
    g = kick.geometry
    rel = Half(kick.id, kick.nearest_team, BallGeometry(g.margin_m, g.nearest_m, g.outside_m, g.speed_mps, None,
               np.full(13, math.e - 1, np.float32)), pace_mps=kick.pace_mps, push_mps=kick.push_mps)
    (*_, xr), = decoder._spell_runs(np.array([code[c] for c in "HHHHHAAAHHHHH"], np.int8), rel, 4, np.zeros(13))
    assert xr[-2] == round(math.log1p(float(np.float32(math.e - 1))), 9), xr
    lo = np.zeros(80, np.float32)
    lo[55:58] = -2.0
    lo[58:70] = np.nan
    sh = Half(HalfId("shape", 1, 0), np.zeros(80, np.int8), BallGeometry(*(np.ones(80, np.float32),) * 4),
              pace_mps=np.ones(80, np.float32), push_mps=np.zeros(80, np.float32), shape_lo=lo)
    codes = np.zeros(80, np.int8)
    codes[5:8] = A
    (*_, xs), = decoder._spell_runs(codes, sh, 4, np.zeros(80))
    assert xs[-1] == 2.0, xs
    tok = np.array([HOME] * 10 + [AWAY] * 2 + [HOME] * 10, np.int8)
    n = len(tok)
    live = Half(HalfId("flip", 1, 0), tok, BallGeometry(*(np.full(n, v, np.float32) for v in (2.0, 3.0, 0.0, 5.0))),
                pace_mps=np.ones(n, np.float32), push_mps=np.zeros(n, np.float32))
    base = Decoder(Tier0Emission(q=0.99), DecoderParams(temper=1.0, poss_mean_s=0.2, stride=1))
    assert base.decode(live).codes.tolist() == [H] * 10 + [A] * 2 + [H] * 10
    on = base.replace(spell_flip_p=0.5, spell_flip_frames=4, spell_logit={**zero, "a": -1.0, "closest_own": 1.0})
    flipped = on.decode(live)
    assert flipped.posterior is None and flipped.codes.tolist() == [H] * n
    assert on.needs_geometry and not base.needs_geometry
    _raises(ValueError, decoder._spell_flip, np.zeros(n, np.int8), live, on.params, None)
    for bad in ({"spell_flip_p": 0.5}, {"spell_flip_p": 0.5, "spell_flip_frames": 4},
                {"spell_flip_p": 0.5, "spell_flip_frames": 4, "spell_logit": {"len": 1.0}},
                {"spell_flip_p": 0.5, "spell_flip_frames": 4, "spell_logit": {"a": 1.0, "nope": 1.0}},
                {"spell_flip_p": 1.5, "spell_flip_frames": 4, "spell_logit": zero}, {"spell_flip_seen": 0.5},
                {"spell_flip_p": 0.5, "spell_flip_frames": 4, "spell_logit": {**zero, "a": math.inf}},
                {"spell_flip_p": 0.5, "spell_flip_frames": 4, "spell_logit": zero, "decode_rule": "map"},
                {"spell_flip_adjacent": True},
                {"spell_flip_p": 0.5, "spell_flip_frames": 4, "spell_logit": zero, "spell_flip_adjacent": 1}):
        try:
            DecoderParams(**bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} was accepted")
    with tempfile.TemporaryDirectory() as tmp:
        saved = json.loads(on.save(Path(tmp) / "flip.json", {}).read_text())["params"]
        assert (saved["spell_flip_p"], saved["spell_flip_frames"], saved["spell_logit"]["closest_own"]) == (0.5, 4, 1.0)
        assert "spell_logit" not in json.loads(base.save(Path(tmp) / "off.json", {}).read_text())["params"]
        assert Decoder.load(Path(tmp) / "flip.json") == on
        assert "spell_flip_adjacent" not in saved
        adj = on.replace(spell_flip_adjacent=True)
        assert json.loads(adj.save(Path(tmp) / "adj.json", {}).read_text())["params"]["spell_flip_adjacent"] is True
        assert Decoder.load(Path(tmp) / "adj.json") == adj


def team_push_known_answer() -> None:
    """challenge._team_push: each team's median slot x velocity, signed toward the goal its kick-off side faces,
    home minus away; NaN at the half's ends and when a team has no slot at kick-off; slot order does not matter."""
    n, t = 60, np.arange(60, dtype=np.float64)[:, None]

    def geometry(home_x0: float, away_x0: float, home_v: list, away_v: list, order: slice = slice(None)) -> Geometry:
        x = np.hstack([home_x0 + t * v for v in home_v] + [away_x0 + t * v for v in away_v])[:, order]
        team = np.array([HOME] * len(home_v) + [AWAY] * len(away_v), np.int8)[order]
        xy = np.stack([x, np.full_like(x, 30.0)], axis=2).astype(np.float32)
        return Geometry(np.full((n, 2), np.nan, np.float32), xy, team, (100.0, 60.0))

    left = challenge._team_push(geometry(30.0, 70.0, [0.1, 0.1, -0.3], [0.1, 0.1]), 0)
    assert np.isnan(left[:12]).all() and np.isnan(left[48:]).all()
    assert np.allclose(left[12:48], 5.0, atol=1e-4), left[12:48]
    right = challenge._team_push(geometry(70.0, 30.0, [0.1, 0.1, -0.3], [0.1, 0.1]), 0)
    assert np.allclose(right[12:48], -5.0, atol=1e-4), right[12:48]
    shuffled = challenge._team_push(geometry(30.0, 70.0, [0.1, 0.1, -0.3], [0.1, 0.1], slice(None, None, -1)), 0)
    assert np.array_equal(shuffled, left, equal_nan=True)
    late = geometry(30.0, 70.0, [0.1, 0.1, -0.3], [0.1, 0.1])
    xy = late.players_xy.copy()
    xy[:25, 3:] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        assert np.isnan(challenge._team_push(Geometry(late.ball_xy, xy, late.slot_team, late.pitch_m), 0)).all()


def _expanded_hmm(p: DecoderParams):
    trans = decoder._chain(p).trans
    mean, k = decoder._blocks(p)
    cont = [(m - kc) / (m - kc + 1) for m, kc in zip(mean, k)]
    states = [(s, j) for s in State for j in range(k[s])]
    index = {state: i for i, state in enumerate(states)}
    log_t = np.full((len(states), len(states)), -np.inf)
    for s in State:
        for j in range(k[s] - 1):
            log_t[index[s, j], index[s, j + 1]] = 0.0
        last = index[s, k[s] - 1]
        log_t[last, last] = math.log(cont[s])
        for d in State:
            if d != s and trans[s, d] > 0:
                log_t[last, index[d, 0]] = math.log(1 - cont[s]) + math.log(trans[s, d] / (1 - trans[s, s]))
    log_pi = np.full(len(states), -np.inf)
    log_pi[[index[State.H, k[State.H] - 1], index[State.A, k[State.A] - 1]]] = math.log(0.5)
    label = decoder.STATE_LABEL[[s for s, _ in states]]
    return k, index, log_t, log_pi, label


def _expanded_viterbi(E: np.ndarray, p: DecoderParams) -> tuple[float, np.ndarray]:
    _, _, log_t, log_pi, label = _expanded_hmm(p)
    emit = E[:, label]
    v, back = log_pi + emit[0], []
    for t in range(1, len(E)):
        cand = v[:, None] + log_t
        arg = cand.argmax(axis=0)
        v = cand[arg, np.arange(len(v))] + emit[t]
        back.append(arg)
    path = [int(v.argmax())]
    for arg in reversed(back):
        path.append(int(arg[path[-1]]))
    return float(v.max()), label[path[::-1]]


def _expanded_score(labels: np.ndarray, E: np.ndarray, p: DecoderParams) -> float:
    k, index, log_t, log_pi, label = _expanded_hmm(p)
    bounds = np.concatenate((np.flatnonzero(np.r_[True, labels[1:] != labels[:-1]]), [len(labels)]))
    poss_state = {H: State.H, A: State.A}
    dead_state_after = {H: State.D_AFTER_H, A: State.D_AFTER_A}
    states, team = [], None
    for n_seg, (lo, hi) in enumerate(zip(bounds[:-1], bounds[1:])):
        code = int(labels[lo])
        if code == D and team is None:
            return -math.inf
        s = dead_state_after[team] if code == D else poss_state[code]
        team = team if code == D else code
        sub = [k[s] - 1] * (hi - lo) if n_seg == 0 else [min(j, k[s] - 1) for j in range(hi - lo)]
        states += [index[s, j] for j in sub]
    total = log_pi[states[0]] + E[0, label[states[0]]]
    for t in range(1, len(states)):
        total += log_t[states[t - 1], states[t]] + E[t, label[states[t]]]
    return float(total)


def map_equals_expanded_viterbi() -> None:
    rng = np.random.default_rng(0)
    combos = [(a, b) for a in (1, 3, 7) for b in (1, 3, 7)]
    for trial in range(50):
        min_poss, min_dead = combos[trial % len(combos)]
        p = DecoderParams(poss_mean_s=0.6, dead_mean_s=0.8, p_dead_after_poss=0.3, p_flip_after_dead=0.6,
                          stride=1, decode_rule="map", min_poss_frames=min_poss, min_dead_frames=min_dead)
        E = rng.normal(0.0, 1.5, size=(200, 3))
        got = decoder._map(E, p)
        best, expected = _expanded_viterbi(E, p)
        gap = abs(_expanded_score(got, E, p) - best)
        assert gap < 1e-9, (trial, min_poss, min_dead, gap)
        assert np.array_equal(got, expected), (trial, min_poss, min_dead)


def _synthetic_clean(n_halves: int = 8, n: int = 250_000, kickoff: int = 500) -> list[CleanHalf]:
    out = []
    t = np.arange(n, dtype=np.float32)
    ball = np.stack([50 + 40 * np.sin(t / 37), 34 + 20 * np.cos(t / 53)], axis=1).astype(np.float32)
    players = np.broadcast_to(np.array([[30, 34], [70, 34]], np.float32), (n, 2, 2))
    for half in range(1, n_halves + 1):
        rng = np.random.default_rng(half)
        labels = np.full(n, D, np.int8)
        i, team = kickoff, H
        while i < n:
            length = int(rng.geometric(1 / 100))
            if rng.random() < 0.6:
                labels[i:i + length] = team
                team = A if team == H else H
            i += length
        geometry = Geometry(ball.copy(), players.copy(), np.array([HOME, AWAY], np.int8), (105.0, 68.0))
        out.append(CleanHalf(HalfId("synthetic", half, kickoff), geometry, labels, {}))
    return out


def dropout_hits_both_constraints() -> None:
    p_alive, p_dead = dropout.solve_rates(0.6, 0.407, 11.5, 0.98)
    assert (round(p_alive, 4), round(p_dead, 4)) == (0.0783, 0.9001), (p_alive, p_dead)
    p_alive, p_dead = dropout.solve_rates(0.68, 0.407, 11.0, 0.98)
    assert (round(p_alive, 4), p_dead, round(p_dead / p_alive, 2)) == (0.1374, 0.98, 7.13), (p_alive, p_dead)
    _raises(ValueError, dropout.solve_rates, 0.5, 0.99, 3.0, 0.98)

    cal = dropout.CALIBRATION
    raw = challenge.halves("baseline_raw")
    pool = dropout.RunPool.from_halves(raw)
    got = (len(pool.missing), len(pool.present), len(pool.mask), int(pool.mask.sum()), int(pool.missing.sum()))
    assert got == (146, 145, cal.window_frames, cal.window_missing, cal.window_missing), got
    pre = np.concatenate([h.nearest_team[:h.id.kickoff] == NO_TEAM for h in raw])
    assert (int(pre.sum()), len(pre)) == (cal.prekickoff_missing, cal.prekickoff_frames)
    defaults = dropout.DropoutParams()
    assert (defaults.target_missing_rate, defaults.prekickoff_missing_rate) == (cal.window_rate, cal.prekickoff_rate)
    assert cal.surface == (1.0, 2.6, 4.0), cal.surface

    clean = _synthetic_clean()
    clean_tokens = [challenge.nearest_team(c.geometry) for c in clean]
    dead = np.concatenate([c.labels[c.id.kickoff:] for c in clean]) == D
    drawn = {}
    for rho in (1.0, 3.0):
        params = dropout.DropoutParams(dead_bias=rho)
        halves = dropout.challengeify(clean, params, 0, pool)
        drawn[rho] = halves
        for h, tokens in zip(halves, clean_tokens):
            seen = h.nearest_team != NO_TEAM
            assert np.array_equal(h.nearest_team[seen], tokens[seen]), (rho, h.id)
            rate = float((~seen[h.id.kickoff:]).mean())
            assert abs(rate - params.target_missing_rate) <= params.tolerance, (rho, h.id, rate)
        missing = np.concatenate([h.nearest_team[h.id.kickoff:] == NO_TEAM for h in halves])
        ratio = float(missing[dead].mean() / missing[~dead].mean())
        assert abs(ratio / rho - 1) <= 0.15, (rho, ratio)

    again = dropout.challengeify(clean, dropout.DropoutParams(dead_bias=3.0), 0, pool)
    assert all(np.array_equal(x.nearest_team, y.nearest_team) for x, y in zip(again, drawn[3.0]))
    other = dropout.challengeify(clean, dropout.DropoutParams(dead_bias=3.0), 1, pool)
    assert not any(np.array_equal(x.nearest_team, y.nearest_team) for x, y in zip(other, drawn[3.0]))

    flat, biased = (dropout.challengeify(clean[:2], dropout.DropoutParams(mode="transplant", dead_bias=rho), 0, pool)
                    for rho in (1.0, 11.0))
    hay = np.tile(pool.mask, 3).tobytes()
    for x, y in zip(flat, biased):
        assert np.array_equal(x.nearest_team, y.nearest_team), x.id
        window = (x.nearest_team[x.id.kickoff:] == NO_TEAM).tobytes()
        assert hay.find(window) >= 0, x.id


_TAGS_XML = """<file><ALL_INSTANCES>
<instance><ID>1</ID><start>447.0</start><end>452.0</end><code>SET PIECES</code>
  <label><group>Team</group><text>N/A</text></label><label><group>Half</group><text>1st Half</text></label>
  <label><group>Type</group><text>Kick Off (Start)</text></label></instance>
<instance><ID>2</ID><start>4549.0</start><end>4554.0</end><code>SET PIECES</code>
  <label><group>Team</group><text>N/A</text></label><label><group>Half</group><text>2nd Half</text></label>
  <label><group>Type</group><text>Kick Off (Start)</text></label></instance>
<instance><ID>3</ID><start>4600.03</start><end>4635.03</end><code>SET PIECES</code>
  <label><group>Team</group><text>Barcelona</text></label><label><group>Half</group><text>2nd Half</text></label>
  <label><group>Type</group><text>Corner Kick</text></label></instance>
<instance><ID>4</ID><start>500.5</start><end>520.0</end><code>BUILD UP</code>
  <label><group>Team</group><text>Atletic Club</text></label><label><group>Half</group><text>1st Half</text></label></instance>
<instance><ID>5</ID><start>600.0</start><end>635.0</end><code>SET PIECES</code>
  <label><group>Team</group><text>N/A</text></label><label><group>Half</group><text>1st Half</text></label>
  <label><group>Type</group><text>Throw-in</text></label></instance>
<instance><ID>6</ID><start>700.0</start><end>720.0</end><code>GOALS</code>
  <label><group>Team</group><text>Barcelona</text></label><label><group>Half</group><text>1st Half</text></label></instance>
<instance><ID>7</ID><start>800.0</start><end>810.0</end><code>CREATING CHANCES</code>
  <label><group>Team</group><text>N/A</text></label><label><group>Half</group><text>1st Half</text></label></instance>
</ALL_INSTANCES></file>"""


def tags_and_rates_known_answer() -> None:
    def parse(xml: str) -> tuple[challenge.Tag, ...]:
        return challenge._parse_tags(ET.fromstring(xml), "Barcelona", "Atletic Club")

    got = parse(_TAGS_XML)
    assert [(t.code, t.kind, t.team, t.half, t.start, t.stop) for t in got] == [
        ("set pieces", "kick off (start)", NO_TEAM, 1, 11175, 11300),
        ("set pieces", "kick off (start)", NO_TEAM, 2, 113725, 113850),
        ("set pieces", "corner kick", HOME, 2, 115001, 115876),
        ("build up", None, AWAY, 1, 12512, 13000),
        ("set pieces", "throw-in", NO_TEAM, 1, 15000, 15875),
        ("goals", None, HOME, 1, 17500, 18000),
        ("creating chances", None, NO_TEAM, 1, 20000, 20250)], got
    assert [t.restart for t in got] == [False, False, True, False, True, False, False]
    assert [t.phase for t in got] == [False, False, False, True, False, False, False]
    _raises(ValueError, parse, _TAGS_XML.replace("Atletic Club", "Athletic Club"))
    _raises(ValueError, parse, _TAGS_XML.replace("<start>447.0</start>", "<start>448.0</start>"))
    _raises(ValueError, parse, _TAGS_XML.replace("2nd Half", "Extra Time"))
    _raises(ValueError, parse, _TAGS_XML.replace("4554.0</end><code>SET PIECES", "4554.0</end><code>BUILD UP"))
    _raises(ValueError, parse, _TAGS_XML.replace("<end>520.0</end>", "<end>500.0</end>"))

    corner = got[2]
    lead = challenge.tag_rows([corner], n_total=N_ROWS, lead_s=2.0, tail_s=0.0)
    assert np.array_equal(np.flatnonzero(lead), np.arange(114951, 115001))
    whole = challenge.tag_rows([corner, got[4]], n_total=N_ROWS)
    assert np.array_equal(np.flatnonzero(whole), np.r_[15000:15875, 115001:115876])
    edges = [challenge.Tag("set pieces", "goal kick", HOME, 1, 10, 30), challenge.Tag("goals", None, AWAY, 1, 95, 120)]
    assert np.array_equal(np.flatnonzero(challenge.tag_rows(edges, n_total=100, lead_s=1.0)), np.r_[0:30, 70:100])

    missing = np.array([1, 1, 1, 0, 1, 0, 0, 0], bool)
    dead = np.array([1, 1, 1, 1, 0, 0, 0, 0], bool)
    r = dropout.missing_rates(missing, dead=dead, alive=~dead)
    assert (tuple(r), r.p_dead, r.p_alive, r.ratio) == ((4, 3, 4, 1), 0.75, 0.25, 3.0), r
    empty = dropout.missing_rates(missing, dead=np.zeros(8, bool), alive=np.ones(8, bool))
    assert math.isnan(empty.p_dead) and math.isnan(empty.ratio) and empty.p_alive == 0.5, empty
    _raises(ValueError, dropout.missing_rates, missing, dead=dead, alive=np.ones(8, bool))
    _raises(ValueError, dropout.missing_rates, missing, dead=dead[:4], alive=~dead[:4])

    assert measure.implied_purity(2.0, 3.0) == 0.5
    assert measure.calibrated([1.04, 3.2, 2.36, 1.5]) == (1.9, (1.0, 4.0))


def _no_metrica() -> Skip:
    return Skip(f"no Metrica sample data under {Path(games.DATA_DIR) / 'metrica_sample'} "
                "(set MTAH_DATA_DIR or run fetch-metrica)")


def _n_spells(labels: np.ndarray) -> int:
    return len(score.possession_spells(labels, [(0, len(labels))]))


def rule_v2_reproduces_measurements() -> None:
    try:
        by_merge = {m: metrica.load(metrica.RuleV2(m)) for m in (0.0, 1.0, 2.0, 3.0)}
    except IOError:
        raise _no_metrica() from None

    pooled = tuple(sum(_n_spells(h.labels) for h in halves) for halves in by_merge.values())
    assert pooled == (1073, 978, 825, 721), pooled
    per_game = []
    for game in metrica.GAMES:
        raw, merged = ([h for h in by_merge[m] if h.id.match == f"metrica_g{game}"] for m in (0.0, 1.0))
        alive = sum(int((h.labels != D).sum()) for h in raw)
        tracking = sum(int(h.provenance["source_frames"]) for h in raw)
        per_game.append((round(100 * alive / tracking, 1), sum(_n_spells(h.labels) for h in raw),
                         sum(_n_spells(h.labels) for h in merged)))
    assert per_game == [(55.1, 364, 333), (58.4, 322, 297), (67.9, 387, 348)], per_game
    for halves in by_merge.values():
        for h in halves:
            assert (h.labels[:h.id.kickoff] == D).all() and int(h.labels.max()) <= D, h.id


def controlled_rule_known_answer() -> None:
    rows = [(H, "SET PIECE", {"KICK OFF"}, 10, 10), (H, "PASS", set(), 20, 30), (A, "RECOVERY", set(), 100, 100),
            (H, "RECOVERY", set(), 130, 130), (A, "RECOVERY", set(), 200, 200),
            *[(A, "PASS", set(), f, f + 5) for f in (205, 215, 225)], (H, "RECOVERY", set(), 240, 240),
            (H, "BALL OUT", set(), 400, 400), (A, "SET PIECE", {"THROW IN"}, 450, 450),
            (H, "RECOVERY", set(), 470, 470), (A, "RECOVERY", set(), 480, 480), (A, "PASS", set(), 590, 599),
            (H, "SET PIECE", {"FREE KICK"}, 600, 600), (A, "RECOVERY", set(), 610, 700)]
    events = pd.DataFrame([{"team": team, "type": kind, "subtypes": frozenset(subtypes), "period": 1,
                            "start": start, "end": end} for team, kind, subtypes, start, end in rows])

    def runs(rule: metrica.RuleV2) -> list[tuple[int, int, int]]:
        out = metrica.rule.label_period(events, frame0=0, n=1000, rule=rule)
        assert out.kickoff == 10, out.kickoff
        return [(a, b, int(code)) for a, b, code in score.segments(out.labels, [(0, len(out.labels))])]

    tail = [(401, 450, D), (450, 600, A), (600, 610, H)]
    expected = {
        metrica.RuleV2(): [(0, 10, D), (10, 100, H), (100, 130, A), (130, 200, H), (200, 240, A), (240, 401, H),
                           (401, 450, D), (450, 470, A), (470, 480, H), (480, 600, A), (600, 610, H), (610, 701, A)],
        metrica.RuleV2(hold_s=2.0): [(0, 10, D), (10, 401, H), *tail, (610, 701, A)],
        metrica.RuleV2(min_passes=3): [(0, 10, D), (10, 200, H), (200, 401, A), (401, 450, D), (450, 600, A),
                                       (600, 701, H)],
        metrica.RuleV2(hold_s=2.0, min_passes=3): [(0, 10, D), (10, 200, H), (200, 240, A), (240, 401, H), *tail,
                                                   (610, 701, A)],
    }
    for rule, want in expected.items():
        got = runs(rule)
        assert got == want, (rule, got)
    _raises(ValueError, metrica.RuleV2, hold_s=-1.0)
    _raises(ValueError, metrica.RuleV2, min_passes=-1)
    _raises(ValueError, metrica.RuleV2, 1.0, 2.0)
    keys = [metrica.RuleV2(*fields).key for fields in ((0.0, 0.0, 0), (2.0, 0.0, 0), (0.0, 3.0, 3))]
    assert keys == ["m0", "m2", "h3p3"], keys
    from .metrica.__main__ import SPELL_RULES

    assert [metrica.RuleV2.parse(rule.key) for rule in SPELL_RULES] == list(SPELL_RULES)
    assert metrica.RuleV2.parse("h3p3") == metrica.RuleV2(hold_s=3.0, min_passes=3)
    for bad in ("", "h2m1", "m2.0", "h0", "x3"):
        _raises(ValueError, metrica.RuleV2.parse, bad)


def controlled_rule_measurements() -> None:
    try:
        raw = metrica.load(metrica.RuleV2())
    except IOError:
        raise _no_metrica() from None

    rules = [metrica.RuleV2(hold_s=h, min_passes=p) for h, p in ((2.0, 3), (3.0, 3), (5.0, 3), (5.0, 0), (0.0, 3))]
    by_rule = {rule.key: metrica.load(rule) for rule in rules}
    pooled = {key: sum(_n_spells(h.labels) for h in halves) for key, halves in by_rule.items()}
    assert pooled == {"h2p3": 818, "h3p3": 709, "h5p3": 582, "h5": 578, "p3": 454}, pooled
    for halves in by_rule.values():
        for h, v2 in zip(halves, raw):
            assert h.id == v2.id and np.array_equal(h.labels == D, v2.labels == D), h.id

    # Measured 2026-10-23 by an independent probe (its own segment walk over metrica.load, native ball
    # from metrica.raw): (q frames, q hits, possessions, possessions before D, possession frames,
    # D stretches, flips, D frames), interior segments of [kickoff, n).
    counted = measure.counted_constants()
    got = {c.rule: (sum(f for _, f in c.q_halves), sum(k for k, _ in c.q_halves), c.poss_segments, c.poss_before_dead,
                    c.poss_frames, c.dead_segments, c.dead_flips, c.dead_frames) for c in counted}
    assert got == {"m0": (258085, 207209, 1061, 313, 256115, 315, 231, 164973),
                   "h2p3": (258085, 205865, 806, 311, 255352, 315, 185, 164973),
                   "h3p3": (258085, 204596, 697, 311, 255352, 315, 180, 164973),
                   "h5p3": (258085, 201676, 570, 311, 253626, 315, 176, 164973)}, got
    assert {(c.window_frames, c.alive_frames) for c in counted} == {(424886, 259913)}
    _aggregates_only(measure.constant_sections(counted, Decoder.load(PARAMS_V0)))


def idsse_reproduces_feed_counts() -> None:
    try:
        halves = idsse.load()
    except IOError:
        raise Skip(f"no IDSSE data under {idsse.root()} (files in possession/idsse/manifest.json)") from None

    # Counted 2026-10-24 by an independent probe straight from the positions XML (its own parse and
    # segment walk): possessions are maximal H or A runs, D ends one; live frames have BallStatus 1.
    assert [(h.id.match, h.id.half) for h in halves] == [(f"idsse_{m}", k) for m in idsse.MATCHES for k in (1, 2)]
    assert sum(_n_spells(h.labels) for h in halves) == 3061
    assert sum(int((h.labels != D).sum()) for h in halves) == 553_105
    assert [_n_spells(h.labels) for h in halves[:2]] == [250, 261]
    for h in halves:
        g = h.geometry
        on_pitch = [(~np.isnan(g.players_xy[:, g.slot_team == team, 0])).sum(axis=1) for team in (HOME, AWAY)]
        assert all(1 <= count.max() <= 11 for count in on_pitch), h.id
        assert -5 < g.ball_xy.min() and g.ball_xy[:, 0].max() < 110 and g.ball_xy[:, 1].max() < 73, h.id
        # Spell counts survive an H/A swap; the nearest player's team does not (0.71 to 0.82 here, about
        # 0.25 swapped).
        tokens, live = challenge.observe(g, h.id).nearest_team, h.labels != D
        assert (tokens[live] == h.labels[live]).mean() > 0.6, h.id
    assert sum(_n_spells(h.labels) for h in idsse.load(metrica.RuleV2(2.0))) == 2042
    _raises(ValueError, idsse.load, metrica.RuleV2(hold_s=3.0, min_passes=3))


def pff_reproduces_feed_counts() -> None:
    try:
        for game in pff.GAMES:
            pff.paths(game)
    except IOError:
        raise Skip(f"no PFF data under {pff.root()} (files in possession/pff/manifest.json)") from None

    # Counted 2026-10-24 by two independent probes straight from the JSONL (their own parse, duplicate
    # collapse and state machine): possessions are maximal H or A runs at the source rate, D ends one.
    # The ball shares are none, VISIBLE and ESTIMATED over the live frames of periods 1 and 2.
    halves = spells = frames = dead = 0
    shown = np.zeros(3, np.int64)
    for game in pff.GAMES:
        for period in pff.parse_game(game):
            frames, dead = frames + len(period.labels), dead + int((period.labels == D).sum())
            if period.number in (1, 2):
                halves, spells = halves + 1, spells + _n_spells(period.labels)
                shown += np.bincount(period.ball_vis[period.labels != D], minlength=3)
    assert (halves, spells) == (128, 17_797), (halves, spells)
    assert (frames, round(dead / frames, 4)) == (11_849_815, 0.4122), (frames, dead)
    assert np.round(shown / shown.sum(), 3).tolist() == [0.061, 0.647, 0.292], shown

    # Regression pins at 25 Hz, measured 2026-10-24 by this code (not an independent probe): the
    # half order, (possessions, live frames, frames, native no-ball frames), VISIBLE frames, and at
    # most 15 players of one team tracked in one frame.
    ids, totals, seen_frames, agree, swapped, hits = [], np.zeros(4, np.int64), 0, [], [], np.zeros(2, np.int64)
    for h in pff.load():
        g, seen = h.geometry, pff.native_seen(h)
        ids.append((h.id.match, h.id.half))
        totals += (_n_spells(h.labels), int((h.labels != D).sum()), g.n, int(h.provenance["native_no_ball_frames"]))
        seen_frames += int(seen.sum())
        on_pitch = [(~np.isnan(g.players_xy[:, g.slot_team == team, 0])).sum(axis=1) for team in (HOME, AWAY)]
        assert h.id.kickoff == 0 and all(1 <= count.max() <= 15 for count in on_pitch), h.id
        # Forgetting the centre-origin shift would leave about half the seen balls off the pitch.
        ball = g.ball_xy[seen]
        inside = (ball >= 0).all(axis=1) & (ball[:, 0] <= g.pitch_m[0]) & (ball[:, 1] <= g.pitch_m[1])
        assert inside.mean() > 0.9, (h.id, inside.mean())
        # Spell counts survive an H/A swap; the nearest player's team does not. Per half it agrees with
        # the labels on 0.554 to 0.893 of live VISIBLE frames, and on 0.107 to 0.446 swapped. The low half
        # is 10512's second, where the away side owns 82% of those frames and the nearest player is
        # often a defender, so the 0.6 bar applies to the pooled share.
        tokens, where = challenge.observe(g, h.id).nearest_team, (h.labels != D) & seen
        agree.append(float((tokens[where] == h.labels[where]).mean()))
        swapped.append(float((tokens[where] == 1 - h.labels[where]).mean()))
        hits += (int((tokens[where] == h.labels[where]).sum()), int(where.sum()))
    assert ids == [(f"pff_{game}", k) for game in pff.GAMES for k in (1, 2)]
    assert totals.tolist() == [17_782, 5_725_878, 9_717_959, 3_153_737] and seen_frames == 4_058_270, (totals, seen_frames)
    assert hits[0] / hits[1] > 0.6 and min(agree) > 0.5 > max(swapped), (hits, min(agree), max(swapped))
    _raises(ValueError, pff.load, metrica.RuleV2(hold_s=3.0, min_passes=3))


def worlds_seed_axis() -> None:
    rule = metrica.RuleV2(2.0)
    try:
        got = bench.worlds([rule], [1.0, 3.0], seeds=[0, 2])
    except IOError:
        raise _no_metrica() from None

    assert list(got) == ["m2_r1", "m2_r1_s2", "m2_r3", "m2_r3_s2"], list(got)
    seed0, seed2 = bench.pooled(got["m2_r3"]), bench.pooled(got["m2_r3_s2"])
    direct = bench.pooled(bench.dev_cases(bench.DevSpec(rule, dropout.DropoutParams(dead_bias=3.0), seed=0)))
    assert all(np.array_equal(a.nearest_team, b.nearest_team) for a, b in zip(seed0.halves, direct.halves))
    assert not any(np.array_equal(a.nearest_team, b.nearest_team) for a, b in zip(seed0.halves, seed2.halves))
    assert np.array_equal(seed0.gt, seed2.gt)
    assert [bench.group(w) for w in ("m2_r1", "m2_r1_s2", "idsse_m0_r2.6_s13")] == ["m2_r1", "m2_r1", "idsse_m0_r2.6"]
    margins = bench.group_margins({"m2_r1": 0.3, "m2_r1_s2": 0.5, "h3p3_r1": 0.2}, {"m2_r1": 0.2, "m2_r1_s2": 0.2, "h3p3_r1": 0.3})
    assert list(margins) == ["m2_r1", "h3p3_r1"] and np.allclose(list(margins.values()), [0.2, -0.1]), margins


def public_case_predict_equals_submission() -> None:
    from . import __main__ as cli

    case = bench.public_case()
    predicted = case.predict(Decoder.load(PARAMS_V0))
    allowed = {"possession", "possession.__main__", "possession.challenge", "possession.decoder", "possession.half",
               "possession.score"}
    probe = ("import pathlib, sys, possession.__main__ as cli; cli.make_submission(*map(pathlib.Path, sys.argv[1:])); "
             "sys.exit(int(any(m.split('.')[0] == 'starter' or "
             f"(m.split('.')[0] == 'possession' and m not in {sorted(allowed)!r}) for m in sys.modules)))")
    with tempfile.TemporaryDirectory() as tmp:
        written = case.layout.cut(score.read_codes(cli.make_submission(PARAMS_V0, Path(tmp) / "v0.csv"), N_ROWS))
        returncode = subprocess.run([sys.executable, "-c", probe, str(PARAMS_V0), str(Path(tmp) / "probe.csv")],
                                    cwd=REPO).returncode
    assert [p.shape for p in predicted] == [(79467,), (79390,)], [p.shape for p in predicted]
    assert all(np.array_equal(p, w) for p, w in zip(predicted, written))
    assert returncode == 0, "make_submission failed or imports a module outside challenge, decoder, half and score"


def submission_is_byte_stable() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        outs = [Path(tmp) / f"run{i}.csv" for i in (1, 2)]
        for out in outs:
            subprocess.run([sys.executable, "-m", "possession", "make-submission",
                            "--params", str(PARAMS_V0), "--out", str(out)],
                           cwd=REPO, check=True, capture_output=True)
        first, second = (out.read_bytes() for out in outs)
        assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
        codes = score.read_codes(outs[0], N_ROWS)

    lines = first.decode("ascii").split("\n")
    assert lines[0] == "frame,label" and lines[-1] == "" and len(lines) - 1 == 199_320, len(lines)
    frames, labels = zip(*(line.split(",") for line in lines[1:-1]))
    assert frames == tuple(str(i) for i in range(N_ROWS))
    code_of = {"H": H, "A": A, "D": D, "X": X}
    assert np.array_equal(codes, [code_of[label] for label in labels]), "read_codes disagrees with the written text"
    labels = np.array(labels)
    graded = np.zeros(N_ROWS, dtype=bool)
    for _, first_row, last_row in games.half_video_blocks(games.GAME):
        graded[first_row:last_row + 1] = True
    assert set(labels[graded].tolist()) == {"H", "A", "D"}
    assert (labels[~graded] == "X").all() and int((~graded).sum()) == 40_462
    assert (labels[110_808:113_742] == "D").all()


CHECKS: tuple[Callable[[], None], ...] = (
    oracle_scores_one,
    layout_splits_halves,
    range_guard_fires,
    permutation_invariance,
    baseline_raw_round_trip,
    smoother_matches_published_baselines,
    atd_reproduces_baseline_raw,
    measure_pins_calibration,
    public_window_crosstab,
    decoder_known_answer,
    marginal_equals_enumeration,
    params_load_guards,
    geometry_emission_known_answer,
    dead_run_rule_known_answer,
    handover_lag_known_answer,
    spell_merge_known_answer,
    spell_push_known_answer,
    team_push_known_answer,
    switch_penalty_known_answer,
    spell_flip_known_answer,
    map_equals_expanded_viterbi,
    dropout_hits_both_constraints,
    tags_and_rates_known_answer,
    rule_v2_reproduces_measurements,
    controlled_rule_known_answer,
    controlled_rule_measurements,
    idsse_reproduces_feed_counts,
    pff_reproduces_feed_counts,
    worlds_seed_axis,
    public_case_predict_equals_submission,
    submission_is_byte_stable,
)


def run() -> int:
    """Run every check, print one line each, return 0 iff none failed (skips do not fail)."""
    counts = {"ok": 0, "skip": 0, "FAIL": 0}
    for check in CHECKS:
        t0 = time.perf_counter()
        try:
            check()
        except Skip as why:
            counts["skip"] += 1
            print(f"{check.__name__:<38} skip: {why}")
            continue
        except Exception as error:
            counts["FAIL"] += 1
            where = traceback.extract_tb(error.__traceback__)[-1]
            print(f"{check.__name__:<38} FAIL {type(error).__name__}: {error} "
                  f"({where.filename.rsplit('/', 1)[-1]}:{where.lineno})")
            continue
        counts["ok"] += 1
        print(f"{check.__name__:<38} ok   {time.perf_counter() - t0:.2f} s")
    print(", ".join(f"{v} {k}" for k, v in counts.items()))
    return 1 if counts["FAIL"] else 0
