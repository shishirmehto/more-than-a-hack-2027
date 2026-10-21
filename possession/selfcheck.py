"""The invariants as runnable checks. The repo has no test suite and numpy/pandas are the only
dependencies, so this is plain asserts behind `python -m possession selfcheck`, seconds to run.

Each check proves one claim against the real artifact (a literal expected value), not a proxy:
a check that would still pass if every imported function returned None is not allowed in here.
Checks marked [needs data] skip with a printed reason when data/metrica_sample/ is absent; the rest
need nothing but the committed repo.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable

import numpy as np

import games

from . import bench, challenge, decoder, dropout, metrica, score
from .decoder import Decoder, DecoderParams, Tier0Emission
from .half import (A, AWAY, D, H, HOME, NO_TEAM, X, Block, CleanHalf, Geometry, Half, HalfId,
                   Layout, check_codes)

REPO = Path(__file__).resolve().parents[1]
PARAMS_V0 = REPO / "params" / "tier0_v0.json"
N_ROWS = 199_319


class Skip(Exception):
    """Raised by a check that cannot run yet; run() reports it without failing."""


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
    """Assemble each half's labels as its own prediction on a dev-like synthetic layout with 6 blocks
    and on the challenge layout with the public GT: spell_f1 == 1.0 and macro_f1 == 1.0, n_pred ==
    n_gt. Proves layout.assemble + score.evaluate wire to pm correctly, incl. one valid run per half.
    score.spell_f1 returns evaluate's (spell_f1, n_pred_spells) exactly, for the oracle and for a
    shifted prediction that matches only some spells.

    Every synthetic block starts and ends in H, so a layout that let pm merge neighbouring halves
    would fuse 5 spells and report 31 instead of 36."""
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
    """pm.valid_runs(Layout.synthetic([100, 100]).assemble([...no X inside...])) == exactly two runs,
    each of the block's size; Layout refuses fewer than GAP_X = 500 X rows before, between or after
    its blocks."""
    layout = Layout.synthetic([100, 100])
    assert layout.n_total == 1700, layout
    runs = score.valid_runs(layout.assemble([np.full(100, H, np.int8)] * 2))
    assert runs == [(500, 600), (1100, 1200)], runs
    assert Layout(1100, (Block(500, 100),)).n_total == 1100
    _raises(ValueError, Layout, 1700, (Block(500, 100), Block(650, 100)))
    _raises(ValueError, Layout, 1100, (Block(499, 100),))
    _raises(ValueError, Layout, 1099, (Block(500, 100),))


def range_guard_fires() -> None:
    """check_codes raises on 4, -1 and a non-int8 array, before pm sees them (pm would corrupt silently)."""
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
    """challenge.nearest_team(g) == nearest_team(g with slots shuffled independently per frame, slot_team
    shuffled with them): identity-freedom is a tested property, not a convention.

    slot_team is per half, so a per-frame shuffle can only move slots within a team; a whole-half
    permutation moves slot_team with the slots, and padding with empty slots tests slot-count
    invariance. Exact distance ties go to the first slot and are the one documented exception."""
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

    rng = np.random.default_rng(0)
    n, s = 3000, 46
    players = (rng.random((n, s, 2)) * (105.3, 68.0)).astype(np.float32)
    players[rng.random((n, s)) < 0.3] = np.nan
    ball = (rng.random((n, 2)) * (105.3, 68.0)).astype(np.float32)
    ball[rng.random(n) < 0.2] = np.nan
    team = (np.arange(s) % 2).astype(np.int8)
    base = challenge.nearest_team(Geometry(ball.copy(), players.copy(), team.copy(), (105.3, 68.0)))
    assert set(np.unique(base).tolist()) == {NO_TEAM, HOME, AWAY}

    perm = rng.permutation(s)
    whole = Geometry(ball.copy(), players[:, perm].copy(), team[perm].copy(), (105.3, 68.0))
    assert np.array_equal(challenge.nearest_team(whole), base)

    within = players.copy()
    for t in (HOME, AWAY):
        slots = np.flatnonzero(team == t)
        order = np.argsort(rng.random((n, len(slots))), axis=1)
        within[:, slots] = players[np.arange(n)[:, None], slots[order]]
    shuffled = Geometry(ball.copy(), within, team.copy(), (105.3, 68.0))
    assert np.array_equal(challenge.nearest_team(shuffled), base)

    padded = np.concatenate([players, np.full((n, 10, 2), np.nan, np.float32)], axis=1)
    pad_team = np.concatenate([team, np.zeros(10, np.int8)])
    assert np.array_equal(challenge.nearest_team(Geometry(ball.copy(), padded, pad_team, (105.3, 68.0))), base)


def baseline_raw_round_trip() -> None:
    """challenge.halves("baseline_raw"): half sizes (79467, 79390), kickoffs (0, 2934), and the NO_TEAM /
    seen counts per half as literals, measured on the committed file: NO_TEAM (32304, 32339), HOME
    (26971, 26176), AWAY (20192, 20875). Whole file via score.read_codes: 85,831 D rows and 113,488
    others (DATA.md). Pins the "D means ball missing" semantics to the committed file."""
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


def public_window_crosstab() -> None:
    """Token vs public GT on rows [11185, 18685): GT D (1469) -> NO_TEAM 494 / HOME 790 / AWAY 185.
    The numbers that proved baseline_raw's D is a mask; a regression here means someone relabelled it.
    The H and A rows are pinned too: GT H (3454) -> 5 / 2750 / 699, GT A (2577) -> 386 / 551 / 1640."""
    gt = score.read_codes(bench.PUBLIC_GT, N_ROWS)[11185:18685]
    first = challenge.layout().blocks[0].origin
    token = challenge.halves("baseline_raw")[0].nearest_team[11185 - first:18685 - first]
    table = [[int(((gt == g) & (token == t)).sum()) for t in (NO_TEAM, HOME, AWAY)] for g in (H, A, D)]
    assert table == [[5, 2750, 699], [386, 551, 1640], [494, 790, 185]], table


def decoder_known_answer() -> None:
    """Synthetic half, kickoff 120 (frames [0,120) D), then tokens HOME 600, missing 300, AWAY 800,
    HOME 500, every visible token correct. The switch inside the all-missing block must land at its
    middle (870) +-stride, the A -> H switch exactly at 1820, and nothing else may switch: at stride 5
    and stride 1, and under "map" with the gap switch anywhere inside the gap. Also: decode twice ->
    identical bytes; H<->A token swap -> H<->A label swap (symmetry); a half with no evidence at all
    decodes to one H run after kickoff (the round-before-argmax tie rule). Parameters are spelled
    out here so a change of defaults cannot move this check."""
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

    # "map" ties every switch position inside a flat block, so only the block itself is pinned there.
    model = Decoder(emission, DecoderParams(stride=1, decode_rule="map", min_poss_frames=25, min_dead_frames=50))
    sw = _switches(model.decode(Half(HalfId("known_answer", 1, 120), tok)).codes)
    assert len(sw) == 3 and sw[0] == (120, D, H) and sw[2] == (1820, A, H), sw
    assert sw[1][1:] == (H, A) and 720 <= sw[1][0] <= 1020, sw

    # No evidence at all: H and A tie exactly in theory, and the rounding rule resolves it to H.
    blind_half = Half(HalfId("blind", 1, 10), np.full(3000, NO_TEAM, np.int8))
    blind = Decoder(emission, DecoderParams(stride=1)).decode(blind_half)
    assert _switches(blind.codes) == [(10, D, H)], _switches(blind.codes)


def marginal_equals_enumeration() -> None:
    """decoder._forward_backward's label posteriors equal brute-force marginals over all 4^7 state
    paths of `_chain`'s HMM to 1e-12, on 20 random evidence sequences of 7 blocks with asymmetric
    switch probabilities; and `_chain` itself matches its docstring on one literal configuration
    (poss 6 s, dead 10 s, stride 5 -> hazards 1/30 and 1/50)."""
    trans = decoder._chain(DecoderParams(poss_mean_s=6.0, dead_mean_s=10.0, p_dead_after_poss=0.25,
                                         p_flip_after_dead=0.7, stride=5)).trans
    hp, hd = 1 / 30, 1 / 50
    expected = [[1 - hp, hp * 0.75, hp * 0.25, 0], [hp * 0.75, 1 - hp, 0, hp * 0.25],
                [hd * 0.3, hd * 0.7, 1 - hd, 0], [hd * 0.7, hd * 0.3, 0, 1 - hd]]
    assert np.allclose(trans, expected, rtol=0, atol=1e-15), trans

    rng = np.random.default_rng(0)
    nb = 7
    paths = np.array(np.meshgrid(*[np.arange(4)] * nb, indexing="ij")).reshape(nb, -1).T   # [4^7, nb]
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
    """Decoder.load round-trips params/tier0_v0.json through save byte for byte, and the defaults
    Decoder(Tier0Emission(), DecoderParams()) are v0 (fit_dev's base). Load refuses a missing field,
    an unknown field, q = 1, stride 0, "marginal" with a minimum duration, and "map" whose mean is not
    above its minimum in blocks; it accepts "map" one block above. The range checks are the
    constructors', so building an out-of-range emission or params raises too."""
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


def _expanded_hmm(p: DecoderParams):
    """The chain-state HMM `_map` claims to solve: state s unrolled into k_s sub-states walked in
    order, a self-loop on the last one, and exits weighted by `_chain`'s switch distribution. The
    first segment starts in its last sub-state (no minimum at the kickoff)."""
    trans = decoder._chain(p).trans
    mean, k = decoder._blocks(p)
    cont = [(m - kc) / (m - kc + 1) for m, kc in zip(mean, k)]
    states = [(s, j) for s in range(4) for j in range(k[s])]
    index = {state: i for i, state in enumerate(states)}
    log_t = np.full((len(states), len(states)), -np.inf)
    for s in range(4):
        for j in range(k[s] - 1):
            log_t[index[s, j], index[s, j + 1]] = 0.0
        last = index[s, k[s] - 1]
        log_t[last, last] = math.log(cont[s])
        for d in range(4):
            if d != s and trans[s, d] > 0:
                log_t[last, index[d, 0]] = math.log(1 - cont[s]) + math.log(trans[s, d] / (1 - trans[s, s]))
    log_pi = np.full(len(states), -np.inf)
    log_pi[[index[0, k[0] - 1], index[1, k[1] - 1]]] = math.log(0.5)
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
    """Score of a label path under the expanded HMM; -inf if the path is not a legal one."""
    k, index, log_t, log_pi, label = _expanded_hmm(p)
    bounds = np.concatenate((np.flatnonzero(np.r_[True, labels[1:] != labels[:-1]]), [len(labels)]))
    states, team = [], None
    for n_seg, (lo, hi) in enumerate(zip(bounds[:-1], bounds[1:])):
        code = int(labels[lo])
        if code == D and team is None:
            return -math.inf
        s = 2 + team if code == D else code             # D_after_H = 2, D_after_A = 3
        team = team if code == D else code
        sub = [k[s] - 1] * (hi - lo) if n_seg == 0 else [min(j, k[s] - 1) for j in range(hi - lo)]
        states += [index[s, j] for j in sub]
    total = log_pi[states[0]] + E[0, label[states[0]]]
    for t in range(1, len(states)):
        total += log_t[states[t - 1], states[t]] + E[t, label[states[t]]]
    return float(total)


def map_equals_expanded_viterbi() -> None:
    """decoder._map's path score equals plain Viterbi on the equivalent expanded chain-state HMM
    (each state s unrolled into k_s sub-states) to 1e-9, on 50 random evidence sequences of length
    200 with min blocks in {1, 3, 7}; and its labels equal the expanded Viterbi's labels (continuous
    random evidence makes the optimum unique). Pins the prefix-sum recursion (bakeoff probe measured
    7e-14). The reference takes its switch distribution from `_chain`, so the two decode rules are
    also pinned to one chain."""
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
    """Dev-like halves with no data on disk: alive and dead strata interleaved in ~100-frame
    segments (alive share ~0.6), a ball on a Lissajous path, one home and one away slot."""
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
    """solve_rates worked example (a=0.6, target=0.407, rho=11.5 -> 0.0783, 0.9001), its cap branch
    (a=0.68, rho=11 -> 0.1374 / 0.98, effective ratio 7.13, the G3 saturation) and its loud failure.
    The committed baseline_raw pool: 146 missing / 145 present runs over [kickoff, n), 155,923 frames,
    64,079 missing. On eight synthetic CleanHalf (2M frames, no data on disk) and rho in {1, 3}, where
    the cap does not bind: every half's realised overall rate within tolerance of 0.407, and pooled
    realised P(missing | dead) / P(missing | alive) within 15% of rho. No observed frame's token
    differs from the clean geometry's (no leak); same seed -> identical tokens, other seed ->
    different. "transplant" ignores dead_bias and its decode window is a cyclic window of the real
    mask."""
    p_alive, p_dead = dropout.solve_rates(0.6, 0.407, 11.5, 0.98)
    assert (round(p_alive, 4), round(p_dead, 4)) == (0.0783, 0.9001), (p_alive, p_dead)
    p_alive, p_dead = dropout.solve_rates(0.68, 0.407, 11.0, 0.98)
    assert (round(p_alive, 4), p_dead, round(p_dead / p_alive, 2)) == (0.1374, 0.98, 7.13), (p_alive, p_dead)
    _raises(ValueError, dropout.solve_rates, 0.5, 0.99, 3.0, 0.98)

    pool = dropout.RunPool.from_halves(challenge.halves("baseline_raw"))
    got = (len(pool.missing), len(pool.present), len(pool.mask), int(pool.mask.sum()), int(pool.missing.sum()))
    assert got == (146, 145, 155_923, 64_079, 64_079), got

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


def _n_spells(labels: np.ndarray) -> int:
    return len(score.possession_spells(labels, [(0, len(labels))]))


def rule_v2_reproduces_measurements() -> None:
    """[needs data] Per game, alive share over TRACKING frames (provenance source_frames, the
    explorers' denominator) 55.1 / 58.4 / 67.9 %; H/A spells 364 / 322 / 387 at merge_s = 0 and
    333 / 297 / 348 at merge_s = 1; pooled spells 1073 / 978 / 825 / 721 at merge_s 0 / 1 / 2 / 3;
    labels[:kickoff] all D; no X anywhere inside a block. Skips when the Metrica files are not under
    games.DATA_DIR (MTAH_DATA_DIR)."""
    try:
        by_merge = {m: metrica.load(metrica.RuleV2(m)) for m in (0.0, 1.0, 2.0, 3.0)}
    except IOError as missing:
        raise Skip(f"no Metrica sample data under {Path(games.DATA_DIR) / 'metrica_sample'} "
                   "(set MTAH_DATA_DIR or run fetch-metrica)") from None

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


def public_case_predict_equals_submission() -> None:
    """bench.public_case().predict(v0) is array-equal, half by half, to the rows __main__.make_submission
    writes for params/tier0_v0.json: the file scored on the public window is the file written. And a
    fresh interpreter that imports the submission path has not imported bench (no Metrica, no RNG)."""
    from . import __main__ as cli

    case = bench.public_case()
    predicted = case.predict(Decoder.load(PARAMS_V0))
    with tempfile.TemporaryDirectory() as tmp:
        written = case.layout.cut(score.read_codes(cli.make_submission(PARAMS_V0, Path(tmp) / "v0.csv"), N_ROWS))
    assert [p.shape for p in predicted] == [(79467,), (79390,)], [p.shape for p in predicted]
    assert all(np.array_equal(p, w) for p, w in zip(predicted, written))
    probe = "import sys, possession.__main__; sys.exit(int('possession.bench' in sys.modules))"
    assert subprocess.run([sys.executable, "-c", probe], cwd=REPO).returncode == 0, "submission path imports bench"


def submission_is_byte_stable() -> None:
    """make-submission twice, in two separate processes, from params/tier0_v0.json -> identical
    sha256; file is 199,320 lines (header + rows), frames 0..199318 in order, every row in HADX, X
    exactly on the 40,462 rows outside games.half_video_blocks, the 2,934 graded pre-kickoff rows of
    half 2 D, and pm.validate_submission passes. public_case_predict_equals_submission pins the
    written rows to the in-memory decode."""
    with tempfile.TemporaryDirectory() as tmp:
        outs = [Path(tmp) / f"run{i}.csv" for i in (1, 2)]
        for out in outs:
            subprocess.run([sys.executable, "-m", "possession", "make-submission",
                            "--params", str(PARAMS_V0), "--out", str(out)],
                           cwd=REPO, check=True, capture_output=True)
        first, second = (out.read_bytes() for out in outs)
        assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
        score.read_codes(outs[0], N_ROWS)  # raises unless pm.validate_submission passes

    lines = first.decode("ascii").split("\n")
    assert lines[0] == "frame,label" and lines[-1] == "" and len(lines) - 1 == 199_320, len(lines)
    frames, labels = zip(*(line.split(",") for line in lines[1:-1]))
    assert frames == tuple(str(i) for i in range(N_ROWS))
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
    public_window_crosstab,
    decoder_known_answer,
    marginal_equals_enumeration,
    params_load_guards,
    map_equals_expanded_viterbi,
    dropout_hits_both_constraints,
    rule_v2_reproduces_measurements,
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
