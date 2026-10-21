"""The invariants as runnable checks. The repo has no test suite and numpy/pandas are the only
dependencies, so this is plain asserts behind `python -m possession selfcheck`, seconds to run.

Each check proves one claim against the real artifact (a literal expected value), not a proxy:
a check that would still pass if every imported function returned None is not allowed in here.
Checks marked [needs data] skip with a printed reason when data/metrica_sample/ is absent; the rest
need nothing but the committed repo.
"""
from __future__ import annotations


def oracle_scores_one() -> None:
    """Assemble each half's labels as its own prediction on a dev-like synthetic layout with 6 blocks
    and on the challenge layout with the public GT: spell_f1 == 1.0 and macro_f1 == 1.0, n_pred ==
    n_gt. Proves layout.assemble + score.evaluate wire to pm correctly, incl. one valid run per half."""
    raise NotImplementedError


def layout_splits_halves() -> None:
    """pm.valid_runs(Layout.synthetic([100, 100]).assemble([...no X inside...])) == exactly two runs,
    each of the block's size; Layout.synthetic(..., gap=10) raises (GAP_X = 500 is the floor)."""
    raise NotImplementedError


def range_guard_fires() -> None:
    """check_codes raises on 4, -1 and a non-int8 array, before pm sees them (pm would corrupt silently)."""
    raise NotImplementedError


def permutation_invariance() -> None:
    """challenge.nearest_team(g) == nearest_team(g with slots shuffled independently per frame, slot_team
    shuffled with them): identity-freedom is a tested property, not a convention."""
    raise NotImplementedError


def baseline_raw_round_trip() -> None:
    """challenge.halves("baseline_raw"): half sizes (79467, 79390), kickoffs (0, 2934), and the NO_TEAM /
    seen counts per half as literals (the sketch guessed (32304, 32339) / (47163, 47051): measure them on
    the committed file once and pin what it says). Whole file via score.read_codes: 85,831 D rows and
    113,488 others (DATA.md). Pins the "D means ball missing" semantics to the committed file."""
    raise NotImplementedError


def public_window_crosstab() -> None:
    """Token vs public GT on rows [11185, 18685): GT D (1469) -> NO_TEAM 494 / HOME 790 / AWAY 185.
    The numbers that proved baseline_raw's D is a mask; a regression here means someone relabelled it."""
    raise NotImplementedError


def decoder_known_answer() -> None:
    """Synthetic half, 3 spells (H 600 frames, A 800, H 500), tokens 100% correct inside the middle,
    all-missing block of 300 frames between spell 1 and 2 (the switch must land at the block's middle
    +-stride), kickoff 120 (frames [0,120) D). decode().codes equals the literal expected array.
    Also: decode twice -> identical bytes; H<->A token swap -> H<->A label swap (symmetry)."""
    raise NotImplementedError


def map_equals_expanded_viterbi() -> None:
    """decoder._map's path score equals plain Viterbi on the equivalent expanded chain-state HMM
    (each state s unrolled into k_s sub-states) to 1e-9, on 50 random evidence sequences of length
    200 with min blocks in {1, 3, 7}; and its labels equal the expanded Viterbi's labels wherever the
    expanded path is unique. Pins the prefix-sum recursion (bakeoff probe measured 7e-14)."""
    raise NotImplementedError


def dropout_hits_both_constraints() -> None:
    """[needs data] solve_rates worked example (a=0.6, target=0.407, rho=11.5 -> 0.078, 0.90). On each
    CleanHalf and rho in {0.75, 1, 3, 11}: realised overall rate within tolerance of 0.407, and realised
    P(missing | dead) / P(missing | alive) within 15% of the ratio implied by the (p_alive, p_dead) that
    solve_rates RETURNED. That is rho itself unless the 0.98 cap fired (rho 11 on G3, alive share 0.68,
    saturates near 7); cap-hit cells are reported with their effective ratio, never asserted against rho.
    No observed frame differs from the filled ball (no native-NaN leak); same seed -> identical masks,
    other seed -> different."""
    raise NotImplementedError


def rule_v2_reproduces_measurements() -> None:
    """[needs data] alive share 55.1 / 58.4 / 67.9 %, raw spells 364 / 322 / 387 (merge_s = 0), and
    333 / 297 / 348 at merge_s = 1; labels[:kickoff] all D; no X anywhere inside a block."""
    raise NotImplementedError


def submission_is_byte_stable() -> None:
    """make-submission twice -> identical sha256; file is 199,320 lines (header + rows), every row in
    HADX, X exactly outside games.half_video_blocks, pm.validate_submission passes, score on the public
    window equals the number bench.run reports for the same params."""
    raise NotImplementedError


def run() -> int:
    """Run every check, print one line each, return 0 iff all passed."""
    raise NotImplementedError
