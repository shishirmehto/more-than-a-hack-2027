from __future__ import annotations

import dataclasses
import math
import zlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal, Sequence

import numpy as np
from numpy.typing import NDArray

from . import challenge
from .half import D, NO_TEAM, CleanHalf, Geometry, Half, HalfId


class Stream(IntEnum):
    ALIVE_MASK = 1
    DEAD_MASK = 2
    PREKICK_MASK = 3
    SLOT_FRAGMENTATION = 4
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
        missing = np.concatenate([_run_lengths(m) for m in masks]).astype(np.int32)
        present = np.concatenate([_run_lengths(~m) for m in masks]).astype(np.int32)
        if missing.size == 0 or present.size == 0:
            raise ValueError("a run pool needs at least one missing and one present run")
        mask = np.concatenate(masks)
        for a in (missing, present, mask):
            a.setflags(write=False)
        return RunPool(missing=missing, present=present, mask=mask)


@dataclass(frozen=True, slots=True)
class DropoutParams:
    """
    target_missing_rate:       overall ball-missing rate over the decode window of each half.
    dead_bias:                 rho = P(missing | dead) / P(missing | alive). 1.0 = missingness carries no
                               dead-ball information.
    prekickoff_missing_rate:   rate on frames [0, kickoff). Its own stratum, so it neither inflates
                               "dead" nor is bent by dead_bias.
    max_rate:                  cap on any per-state rate; solve_rates re-solves the other state if hit.
    tolerance, max_attempts:   rejection bound on the realised overall rate.
    mode:                      "renewal" (default): the alive/dead/pre-kickoff renewal masks.
                               "transplant": label-blind. The decode window's mask is a seeded cyclic
                               window of the challenge's REAL graded-half mask (both halves of
                               baseline_raw over [kickoff, n), concatenated); dead_bias and
                               target_missing_rate are ignored. Pre-kickoff still uses its own stratum.
    """
    mode: Literal["renewal", "transplant"] = "renewal"
    target_missing_rate: float = 0.407
    dead_bias: float = 1.0
    prekickoff_missing_rate: float = 0.19
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


def _run_lengths(mask: NDArray[np.bool_]) -> NDArray[np.int64]:
    edges = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    return edges[1::2] - edges[::2]


def fragment_slots(g: Geometry, rng: np.random.Generator) -> Geometry:
    raise NotImplementedError
