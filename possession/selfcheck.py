"""The invariants as runnable checks. The repo has no test suite and numpy/pandas are the only
dependencies, so this is plain asserts behind `python -m possession selfcheck`, seconds to run.

Each check proves one claim against the real artifact (a literal expected value), not a proxy:
a check that would still pass if every imported function returned None is not allowed in here.
Checks marked [needs data] skip with a printed reason when data/metrica_sample/ is absent; the rest
need nothing but the committed repo.
"""
from __future__ import annotations

import time
import traceback
from typing import Callable

import numpy as np

from . import challenge, score
from .half import A, AWAY, D, H, HOME, NO_TEAM, X, Block, Geometry, HalfId, Layout, check_codes

PUBLIC_GT = challenge.BASELINE_RAW.parents[1] / "gt" / "BAR-ATH_possession_gt_public.csv"
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
    raise NotImplementedError


def map_equals_expanded_viterbi() -> None:
    raise NotImplementedError


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
    raise NotImplementedError


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
