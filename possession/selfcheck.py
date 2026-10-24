from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import tempfile
import time
import traceback
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
                       (geo.outside_m, [0, 0, nan, 0, nan, 0])):
        assert np.allclose(have, want, atol=1e-5, equal_nan=True), have
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
        return [a.tobytes() for a in (h.nearest_team, h.geometry.margin_m, h.geometry.nearest_m, h.geometry.outside_m)]

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
    _raises(ValueError, Half, HalfId("bad", 1, 0), tok, BallGeometry(bad, bad, bad.astype(np.float64)))
    _raises(ValueError, Half, HalfId("bad", 1, 0), np.array([0, NO_TEAM, 1], np.int8), BallGeometry(bad, bad, bad))


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
                       outside_m=np.array([nan, 0, 0, 2, 0.5, 0], np.float32))
    half = Half(HalfId("geo", 1, 0), tok, geo)
    plain = Tier0Emission(q=0.8)
    on = Tier0Emission(q=0.8, margin_scale_m=3.0, q_max=0.95, outside_bonus=2.0, outside_min_m=1.0,
                       far_bonus=1.5, far_min_m=10.0)
    assert not plain.needs_geometry and on.needs_geometry
    _raises(ValueError, on.loglik, Half(HalfId("geo", 1, 0), tok))
    assert np.array_equal(plain.loglik(half), plain.loglik(Half(HalfId("geo", 1, 0), tok)))
    base, got = plain.loglik(half).astype(np.float64), on.loglik(half).astype(np.float64)
    e1 = 0.5 + 0.45 * (1 - math.exp(-1))
    qm = np.array([0.5, e1, 0.95, e1, 0.5 + 0.45 * (1 - math.exp(-1 / 3))])
    home = tok[1:] == HOME
    want = np.log(np.stack([np.where(home, qm, 1 - qm), np.where(home, 1 - qm, qm)], 1)) + math.log(5 / 6)
    assert np.allclose(got[1:, :2], want, atol=1e-6), (got[1:, :2], want)
    assert np.allclose(got[:, 2] - base[:, 2], [0, 0, 1.5, 2.0, 0, 0], atol=1e-6), got[:, 2] - base[:, 2]
    assert np.array_equal(got[0], base[0])
    mirrored = on.loglik(Half(HalfId("geo", 1, 0), np.where(tok == NO_TEAM, NO_TEAM, 1 - tok).astype(np.int8), geo))
    assert np.array_equal(mirrored, on.loglik(half)[:, [1, 0, 2]])

    v0 = Decoder.load(PARAMS_V0)
    model = v0.replace(margin_scale_m=3.0, outside_bonus=2.0)
    assert model.emission.margin_scale_m == 3.0 and model.params == v0.params
    with tempfile.TemporaryDirectory() as tmp:
        path = model.save(Path(tmp) / "geo.json", {})
        emission = json.loads(path.read_text())["emission"]
        assert set(emission) == {"kind", "q", "dead_bias", "alive_share", "margin_scale_m", "outside_bonus"}, emission
        assert Decoder.load(path) == model


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
