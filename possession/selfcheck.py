"""The invariants as runnable checks. The repo has no test suite and numpy/pandas are the only
dependencies, so this is plain asserts behind `python -m possession selfcheck`, seconds to run.

Each check proves one claim against the real artifact (a literal expected value), not a proxy:
a check that would still pass if every imported function returned None is not allowed in here.
Checks marked [needs data] skip with a printed reason when data/metrica_sample/ is absent; the rest
need nothing but the committed repo.
"""
from __future__ import annotations

import hashlib
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

from . import challenge, decoder, score
from .decoder import Decoder, DecoderParams, Tier0Emission
from .half import (A, AWAY, D, FPS, H, HOME, NO_TEAM, X, Block, Geometry, Half, HalfId, Layout,
                   check_codes)

REPO = Path(__file__).resolve().parents[1]
PUBLIC_GT = REPO / "evaluation" / "gt" / "BAR-ATH_possession_gt_public.csv"
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
    at = np.flatnonzero(codes[1:] != codes[:-1]) + 1
    return [(int(i), int(codes[i - 1]), int(codes[i])) for i in at]


def oracle_scores_one() -> None:
    """Assemble each half's labels as its own prediction on a dev-like synthetic layout with 6 blocks
    and on the challenge layout with the public GT: spell_f1 == 1.0 and macro_f1 == 1.0, n_pred ==
    n_gt. Proves layout.assemble + score.evaluate wire to pm correctly, incl. one valid run per half.

    Every synthetic block starts and ends in H, so a layout that let pm merge neighbouring halves
    would fuse 5 spells and report 31 instead of 36."""
    block = _segments([(H, 120), (A, 80), (D, 50), (A, 200), (H, 60), (A, 90), (D, 40), (H, 160)])
    layout = Layout.synthetic([len(block)] * 6)
    s = score.evaluate(layout, layout.assemble([block] * 6), [block] * 6)
    assert (s.spell_f1, s.macro_f1, s.n_gt_spells, s.n_pred_spells, s.n_graded) == (1.0, 1.0, 36, 36, 4800), s

    public = challenge.layout()
    gt = score.read_codes(PUBLIC_GT, N_ROWS)
    preds = [np.where(part == X, D, part).astype(np.int8) for part in public.cut(gt)]
    s = score.evaluate(public, gt, preds)
    assert (s.spell_f1, s.macro_f1, s.n_gt_spells, s.n_pred_spells, s.n_graded) == (1.0, 1.0, 17, 17, 7500), s


def layout_splits_halves() -> None:
    """pm.valid_runs(Layout.synthetic([100, 100]).assemble([...no X inside...])) == exactly two runs,
    each of the block's size; Layout.synthetic(..., gap=10) raises (GAP_X = 500 is the floor)."""
    layout = Layout.synthetic([100, 100])
    assert layout.n_total == 1700, layout
    runs = score.valid_runs(layout.assemble([np.full(100, H, np.int8)] * 2))
    assert runs == [(500, 600), (1100, 1200)], runs
    _raises(ValueError, Layout.synthetic, [100, 100], gap=10)
    _raises(ValueError, Layout, 1700, (Block(500, 100), Block(650, 100)))


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
        ball_xy=np.array([[0, 0], [2.1, 0], [nan, nan], [0, 0], [0, 0]], np.float32),
        players_xy=np.array([
            [[1, 0], [2, 0], [3, 0]],
            [[1, 0], [2, 0], [3, 0]],
            [[1, 0], [2, 0], [3, 0]],
            [[nan, nan], [5, 0], [nan, nan]],
            [[nan, nan], [nan, nan], [nan, nan]],
        ], np.float32),
        slot_team=np.array([HOME, AWAY, HOME], np.int8),
        pitch_m=(105.3, 68.0))
    got = challenge.nearest_team(tiny)
    assert got.tolist() == [HOME, AWAY, NO_TEAM, AWAY, NO_TEAM], got

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
    gt = score.read_codes(PUBLIC_GT, N_ROWS)[11185:18685]
    first = challenge.layout().blocks[0].origin
    token = challenge.halves("baseline_raw")[0].nearest_team[11185 - first:18685 - first]
    table = [[int(((gt == g) & (token == t)).sum()) for t in (NO_TEAM, HOME, AWAY)] for g in (H, A, D)]
    assert table == [[5, 2750, 699], [386, 551, 1640], [494, 790, 185]], table


def decoder_known_answer() -> None:
    """Synthetic half, kickoff 120 (frames [0,120) D), then tokens HOME 600, missing 300, AWAY 800,
    HOME 500, every visible token correct. The switch inside the all-missing block must land at its
    middle (870) +-stride, the A -> H switch exactly at 1820, and nothing else may switch: at stride 5
    and stride 1, and under "map" with the gap switch anywhere inside the gap. Also: decode twice ->
    identical bytes; H<->A token swap -> H<->A label swap (symmetry). Parameters are spelled out
    here so a change of defaults cannot move this check."""
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


def _expanded_hmm(p: DecoderParams):
    """The chain-state HMM `_map` claims to solve: state s unrolled into k_s sub-states walked in
    order, a self-loop on the last one, and exits weighted by `_chain`'s switch distribution. The
    first segment starts in its last sub-state (no minimum at the kickoff)."""
    trans = decoder._chain(p).trans
    k = [math.ceil(p.min_poss_frames / p.stride)] * 2 + [math.ceil(p.min_dead_frames / p.stride)] * 2
    mean = [p.poss_mean_s * FPS / p.stride] * 2 + [p.dead_mean_s * FPS / p.stride] * 2
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


def dropout_hits_both_constraints() -> None:
    """[needs data] solve_rates worked example (a=0.6, target=0.407, rho=11.5 -> 0.078, 0.90). On each
    CleanHalf and rho in {0.75, 1, 3, 11}: realised overall rate within tolerance of 0.407, and realised
    P(missing | dead) / P(missing | alive) within 15% of the ratio implied by the (p_alive, p_dead) that
    solve_rates RETURNED. That is rho itself unless the 0.98 cap fired (rho 11 on G3, alive share 0.68,
    saturates near 7); cap-hit cells are reported with their effective ratio, never asserted against rho.
    No observed frame differs from the filled ball (no native-NaN leak); same seed -> identical masks,
    other seed -> different."""
    raise Skip("needs workstream B/C")


def rule_v2_reproduces_measurements() -> None:
    """[needs data] alive share 55.1 / 58.4 / 67.9 %, raw spells 364 / 322 / 387 (merge_s = 0), and
    333 / 297 / 348 at merge_s = 1; labels[:kickoff] all D; no X anywhere inside a block."""
    raise Skip("needs workstream B/C")


def submission_is_byte_stable() -> None:
    """make-submission twice, in two separate processes, from params/tier0_v0.json -> identical
    sha256; file is 199,320 lines (header + rows), frames 0..199318 in order, every row in HADX, X
    exactly on the 40,462 rows outside games.half_video_blocks, the 2,934 graded pre-kickoff rows of
    half 2 D, pm.validate_submission passes, and the file's public-window score equals the score of
    the same params decoded in memory (bench.run does not exist yet; this is its path minus the table)."""
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
    labels = np.array(labels)
    graded = np.zeros(N_ROWS, dtype=bool)
    for _, first_row, last_row in games.half_video_blocks(games.GAME):
        graded[first_row:last_row + 1] = True
    assert set(labels[graded].tolist()) == {"H", "A", "D"}
    assert (labels[~graded] == "X").all() and int((~graded).sum()) == 40_462
    assert (labels[110_808:113_742] == "D").all()

    layout = challenge.layout()
    gt = score.read_codes(PUBLIC_GT, N_ROWS)
    from_file = score.evaluate(layout, gt, layout.cut(codes))
    model = Decoder.load(PARAMS_V0)
    in_memory = score.evaluate(layout, gt, [model.decode(h).codes for h in challenge.halves("baseline_raw")])
    assert from_file == in_memory, (from_file, in_memory)


CHECKS: tuple[Callable[[], None], ...] = (
    oracle_scores_one,
    layout_splits_halves,
    range_guard_fires,
    permutation_invariance,
    baseline_raw_round_trip,
    public_window_crosstab,
    decoder_known_answer,
    map_equals_expanded_viterbi,
    dropout_hits_both_constraints,
    rule_v2_reproduces_measurements,
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
            print(f"{check.__name__:<34} skip: {why}")
            continue
        except Exception as error:
            counts["FAIL"] += 1
            where = traceback.extract_tb(error.__traceback__)[-1]
            print(f"{check.__name__:<34} FAIL {type(error).__name__}: {error} "
                  f"({where.filename.rsplit('/', 1)[-1]}:{where.lineno})")
            continue
        counts["ok"] += 1
        print(f"{check.__name__:<34} ok   {time.perf_counter() - t0:.2f} s")
    print(", ".join(f"{v} {k}" for k, v in counts.items()))
    return 1 if counts["FAIL"] else 0
