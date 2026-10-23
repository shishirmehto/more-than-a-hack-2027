from __future__ import annotations

import dataclasses
import math
import zlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal, NamedTuple, Sequence

import numpy as np
from numpy.typing import NDArray

from . import challenge
from .half import D, NO_TEAM, CleanHalf, Half, HalfId


class Stream(IntEnum):
    ALIVE_MASK = 1
    DEAD_MASK = 2
    PREKICK_MASK = 3
    TRANSPLANT_OFFSET = 5


@dataclass(frozen=True, slots=True)
class RunPool:
    """Empirical run-length tables of a real ball mask, inside graded halves.

    missing: int32 [R_m] lengths of ball-missing runs.
    present: int32 [R_p] lengths of ball-present runs.
    mask:    bool [N] the real missing mask itself over every half's [kickoff, n), concatenated in half
             order.
    """
    missing: NDArray[np.int32]
    present: NDArray[np.int32]
    mask: NDArray[np.bool_]

    @staticmethod
    def from_halves(halves: Sequence[Half]) -> RunPool:
        """Run lengths of (nearest_team == NO_TEAM) / its complement over each half's [kickoff, n).

        Runs truncated by a half's edges are kept."""
        masks = [h.nearest_team[h.id.kickoff:] == NO_TEAM for h in halves]
        missing = np.concatenate([run_lengths(m) for m in masks]).astype(np.int32)
        present = np.concatenate([run_lengths(~m) for m in masks]).astype(np.int32)
        if missing.size == 0 or present.size == 0:
            raise ValueError("a run pool needs at least one missing and one present run")
        mask = np.concatenate(masks)
        for a in (missing, present, mask):
            a.setflags(write=False)
        return RunPool(missing=missing, present=present, mask=mask)


class MissingRates(NamedTuple):
    """Ball-missing counts on dead and alive rows. Rates are derived; NaN where a side has no rows."""
    dead_frames: int
    dead_missing: int
    alive_frames: int
    alive_missing: int

    @property
    def p_dead(self) -> float:
        return self.dead_missing / self.dead_frames if self.dead_frames else math.nan

    @property
    def p_alive(self) -> float:
        return self.alive_missing / self.alive_frames if self.alive_frames else math.nan

    @property
    def ratio(self) -> float:
        """p_dead / p_alive, the quantity DropoutParams.dead_bias sets; NaN unless p_alive > 0."""
        return self.p_dead / self.p_alive if self.p_alive > 0 else math.nan


def missing_rates(missing: NDArray[np.bool_], *, dead: NDArray[np.bool_],
                  alive: NDArray[np.bool_]) -> MissingRates:
    """Counts over the dead and the alive rows. The one formula behind a measured dead_bias
    (measure.estimate) and a realised one (bench.dropout_stats). ValueError when the shapes differ
    or a row is both dead and alive."""
    if not missing.shape == dead.shape == alive.shape:
        raise ValueError(f"shapes differ: missing {missing.shape}, dead {dead.shape}, alive {alive.shape}")
    if (dead & alive).any():
        raise ValueError("a row is both dead and alive")
    return MissingRates(int(dead.sum()), int(missing[dead].sum()), int(alive.sum()), int(missing[alive].sum()))


@dataclass(frozen=True, slots=True)
class Calibration:
    """The generator's constants, measured on the real BAR-ATH observation (tactical ATD and Smart
    Tagging, 2026-10-23). Reproduce: python -m possession measure. selfcheck re-measures the counts from
    the committed baseline_raw without data (dropout_hits_both_constraints) and from the ATD with data
    (measure_pins_calibration).

    window_missing / window_frames:          ball-missing rows over every half's [kickoff, n): the window
                                             the decoder reads and the generator's target covers.
    prekickoff_missing / prekickoff_frames:  over [0, kickoff), which only half 2 has.
    dead_bias:          the reading world: the median of the 16 restart-proxy definitions (measure.SWEEP,
                        1.999 to 3.445, median 2.579), to one decimal.
    dead_bias_bracket:  fit-dev's max-min worlds: from 1, where missingness says nothing (the floor a
                        robust decoder must survive), to the ceiling of the largest of the 16 definitions.
                        measure.calibrated states both rules. The per-restart-kind ratios are reported
                        beside them and need not lie inside: each rests on 4 to 26 restarts, and against
                        the phase complement corners and kick-offs after a goal reach 4.57.
    """
    window_missing: int = 64_079
    window_frames: int = 155_923
    prekickoff_missing: int = 564
    prekickoff_frames: int = 2_934
    dead_bias: float = 2.6
    dead_bias_bracket: tuple[float, float] = (1.0, 4.0)

    @property
    def window_rate(self) -> float:
        return self.window_missing / self.window_frames

    @property
    def prekickoff_rate(self) -> float:
        return self.prekickoff_missing / self.prekickoff_frames

    @property
    def surface(self) -> tuple[float, ...]:
        """sweep's generator worlds and decoder beliefs: the bracket and the point, ascending."""
        return tuple(sorted({*self.dead_bias_bracket, self.dead_bias}))


CALIBRATION = Calibration()


@dataclass(frozen=True, slots=True)
class DropoutParams:
    """
    target_missing_rate:       overall ball-missing rate over the decode window [kickoff, n) of each
                               half; default CALIBRATION.window_rate.
    dead_bias:                 rho = P(missing | dead) / P(missing | alive). 1.0 = missingness carries no
                               dead-ball information.
    prekickoff_missing_rate:   rate on frames [0, kickoff); default CALIBRATION.prekickoff_rate. Its own
                               stratum, so it neither inflates "dead" nor is bent by dead_bias.
    max_rate:                  cap on any per-state rate; solve_rates re-solves the other state if hit.
    tolerance, max_attempts:   rejection bound on the realised overall rate.
    mode:                      "renewal" (default): the alive/dead/pre-kickoff renewal masks.
                               "transplant": label-blind. The decode window's mask is a seeded cyclic
                               window of the challenge's REAL graded-half mask (both halves of
                               baseline_raw over [kickoff, n), concatenated); dead_bias and
                               target_missing_rate are ignored. Pre-kickoff still uses its own stratum.
    """
    mode: Literal["renewal", "transplant"] = "renewal"
    target_missing_rate: float = CALIBRATION.window_rate
    dead_bias: float = 1.0
    prekickoff_missing_rate: float = CALIBRATION.prekickoff_rate
    max_rate: float = 0.98
    tolerance: float = 0.02
    max_attempts: int = 50


def challengeify(clean: Sequence[CleanHalf], params: DropoutParams, seed: int,
                 pool: RunPool | None = None) -> list[Half]:
    """CleanHalf -> Half, one per input, deterministic in (clean, params, seed, pool).

    pool defaults to RunPool.from_halves(challenge.halves("baseline_raw")). The players array is
    shared (read-only), only ball_xy is copied.
    """
    if pool is None:
        pool = RunPool.from_halves(challenge.halves("baseline_raw"))
    out = []
    for c in clean:
        seen = _seen_mask(c, params, seed, pool)
        ball = np.where(seen[:, None], c.geometry.ball_xy, np.float32(np.nan)).astype(np.float32)
        out.append(challenge.observe(dataclasses.replace(c.geometry, ball_xy=ball), c.id))
    return out


def solve_rates(alive_share: float, target: float, dead_bias: float, cap: float) -> tuple[float, float]:
    """(p_alive, p_dead) such that BOTH constraints hold exactly in expectation.

    With a = alive_share of the decode window (from the labels) and rho = dead_bias:
        target = a * p_alive + (1 - a) * p_dead,   p_dead = rho * p_alive
    If p_dead > cap: p_dead = cap, p_alive = (target - (1 - a) * cap) / a. Raises ValueError if that is
    < 0 or > cap (target unreachable for this half).
    """
    a, rho = alive_share, dead_bias
    p_alive = target / (a + (1 - a) * rho)
    p_dead = rho * p_alive
    if p_dead > cap:
        p_dead = cap
        p_alive = (target - (1 - a) * cap) / a if a > 0 else -1.0
    if not (0 <= p_alive <= cap and 0 <= p_dead <= cap):
        raise ValueError(f"target {target} unreachable: alive share {a}, dead_bias {rho}, cap {cap} "
                         f"give p_alive {p_alive:.4f}, p_dead {p_dead:.4f}")
    return p_alive, p_dead


def missing_mask(n: int, rate: float, pool: RunPool, rng: np.random.Generator) -> NDArray[np.bool_]:
    if rate <= 0:
        return np.zeros(n, dtype=bool)
    if rate >= 1:
        return np.ones(n, dtype=bool)
    e_m, e_p = float(pool.missing.mean()), float(pool.present.mean())
    c = e_m * (1 - rate) / (rate * e_p)
    k = int(2.5 * n / (e_m + c * e_p)) + 8
    lens, off = np.empty(0, dtype=np.int64), None
    while off is None or lens.sum() < off + n:
        present = np.maximum(1, np.rint(c * rng.choice(pool.present, k))).astype(np.int64)
        missing = rng.choice(pool.missing, k).astype(np.int64)
        lens = np.concatenate([lens, np.column_stack([present, missing]).ravel()])
        if off is None:
            off = int(rng.integers(0, lens[0] + lens[1]))
    out = np.repeat(np.tile([False, True], len(lens) // 2), lens)
    return out[off:off + n]


def _seen_mask(c: CleanHalf, params: DropoutParams, seed: int, pool: RunPool) -> NDArray[np.bool_]:
    n, k0 = c.geometry.n, c.id.kickoff
    pre = missing_mask(k0, params.prekickoff_missing_rate, pool, _rng(seed, c.id, Stream.PREKICK_MASK))
    if params.mode == "transplant":
        start = int(_rng(seed, c.id, Stream.TRANSPLANT_OFFSET).integers(0, len(pool.mask)))
        window = pool.mask[(start + np.arange(n - k0)) % len(pool.mask)]
        return ~np.concatenate([pre, window])
    if params.mode != "renewal":
        raise ValueError(f"dropout mode must be 'renewal' or 'transplant', got {params.mode!r}")

    dead = c.labels[k0:] == D
    p_alive, p_dead = solve_rates(1.0 - float(dead.mean()), params.target_missing_rate, params.dead_bias,
                                  params.max_rate)
    best, best_err = None, math.inf
    for attempt in range(params.max_attempts):
        alive_mask = missing_mask(n - k0, p_alive, pool, _rng(seed, c.id, Stream.ALIVE_MASK, attempt))
        dead_mask = missing_mask(n - k0, p_dead, pool, _rng(seed, c.id, Stream.DEAD_MASK, attempt))
        missing = np.where(dead, dead_mask, alive_mask)
        err = abs(float(missing.mean()) - params.target_missing_rate)
        if err < best_err:
            best, best_err = missing, err
        if err <= params.tolerance:
            break
    return ~np.concatenate([pre, best])


def _rng(seed: int, id: HalfId, stream: Stream, attempt: int = 0) -> np.random.Generator:
    entropy = [seed, zlib.crc32(id.match.encode()), id.half, int(stream)]
    return np.random.default_rng(np.random.SeedSequence(entropy, spawn_key=(attempt,)))


def run_lengths(mask: NDArray[np.bool_]) -> NDArray[np.int64]:
    """Lengths of the True runs of a 1-D mask, in order."""
    edges = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    return edges[1::2] - edges[::2]
