"""Challenge-ify: turn clean, fully observed Metrica halves into halves that look like the challenge ATD.

Owns the generator of ball dropout, and nothing else. It is a transform on any `CleanHalf` whose
calibration source is the CHALLENGE (baseline_raw.csv run lengths), which is why it is not part of
`metrica/`: swap the source game and this module is unchanged.

What the challenge's own mask looks like (measured on baseline_raw.csv inside the graded halves):
40.7% of frames missing in both halves; 69 / 81 missing runs, median 289 / 245 frames (~10-12 s), p90
1083 / 639, max 3466 / 5537; 99.9% of missing frames sit in runs >= 25 frames. Dropout is BLOCKS, so
independent per-frame dropout would be trivially bridged by any smoother. Metrica's native NaN is the
opposite (an out-of-play marker, 0.7-1.3% alive blips); it is removed upstream (metrica.fill_ball),
so this module is the only source of missingness.

Two constraints, solved per half (what the docstring of `solve_rates` states):
  (1) overall missing rate on the decode window == target_missing_rate      (0.407, measured)
  (2) P(missing | dead) / P(missing | alive) == dead_bias                    (UNKNOWN on the real ATD)
(2) is the generator's world; decoder.Tier0Emission.dead_bias is the decoder's belief about it. The
bench sweeps both and reports the surface; see bench.surface.
"""
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
    """Independent RNG streams. One SeedSequence([seed, game, half, stream]) per (half, purpose), so
    adding a purpose, a half or a game never reshuffles another stream's draws (per
    separate-before-serializing-shared-state: no actor shares a generator)."""
    ALIVE_MASK = 1
    DEAD_MASK = 2
    PREKICK_MASK = 3
    SLOT_FRAGMENTATION = 4  # DEFERRED
    TRANSPLANT_OFFSET = 5


@dataclass(frozen=True, slots=True)
class RunPool:
    """Empirical run-length tables of a real ball mask, inside graded halves.

    missing: int32 [R_m] lengths of ball-missing runs (150 runs from baseline_raw).
    present: int32 [R_p] lengths of ball-present runs.
    mask:    bool [N] the real missing mask itself over every half's [kickoff, n), concatenated in half
             order; the source the "transplant" mode windows into.
    Resampled with replacement. A geometric fit would be a second-order worse choice: baseline_raw has
    the real, heavy-tailed block distribution and it costs nothing to use it.
    """
    missing: NDArray[np.int32]
    present: NDArray[np.int32]
    mask: NDArray[np.bool_]

    @staticmethod
    def from_halves(halves: Sequence[Half]) -> RunPool:
        """Run lengths of (nearest_team == NO_TEAM) / its complement over each half's [kickoff, n).

        Runs truncated by a half's edges are kept. On baseline_raw this gives 146 missing and 145
        present runs (150 / 149 only when half 2's pre-kickoff stretch is counted too)."""
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
    """The generator's world.

    target_missing_rate:       overall ball-missing rate over the decode window of each half. 0.407.
    dead_bias:                 rho = P(missing | dead) / P(missing | alive). 1.0 = missingness carries no
                               dead-ball information. Sweep {0.75, 1, 3, 11}: 0.75 ~ public-window
                               P(m|D)=0.34 with a=0.6; 11 ~ P(m|D)=0.9, P(m|alive)=0.08. Above roughly 8
                               the max_rate cap binds on high-alive halves (G3, a=0.68, rho 11 -> 0.98 / 0.14,
                               effective ratio ~7), so the EFFECTIVE ratio saturates; it is recomputed from
                               the data into Case.provenance, never read back from this field.
    prekickoff_missing_rate:   rate on frames [0, kickoff). 0.19, from half 2's 2934 graded
                               pre-kickoff frames (baseline: 564 of 2934 missing). Its own stratum, so
                               it neither inflates "dead" nor is bent by dead_bias.
    max_rate:                  cap on any per-state rate; solve_rates re-solves the other state if hit.
    tolerance, max_attempts:   rejection bound on the realised overall rate (deterministic: the k-th
                               attempt draws from the same SeedSequence child).
    mode:                      "renewal" (default): the alive/dead/pre-kickoff renewal masks above.
                               "transplant": label-blind. The decode window's mask is a seeded cyclic
                               window of the challenge's REAL graded-half mask (both halves of
                               baseline_raw over [kickoff, n), concatenated), so the exact burst structure
                               and its nonstationarity (per-minute rate swinging 0..1) survive; dead_bias
                               and target_missing_rate are ignored and the realised rates are recorded.
                               Pre-kickoff still uses its own stratum.
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
    shared (read-only), only ball_xy is copied, so re-drawing a world for a new dead_bias costs one
    nearest_team pass per half, not a copy of 100 MB.
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
        => p_alive = target / (a + (1 - a) * rho),  p_dead = rho * p_alive.
    If p_dead > cap: p_dead = cap, p_alive = (target - (1 - a) * cap) / a. Raises ValueError if that is
    < 0 or > cap (target unreachable for this half): a loud failure, never a silently wrong world.
    Worked check: a = 0.6, target = 0.407, rho = 11.5 -> p_alive 0.078, p_dead 0.90.
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
    """bool [n], True = ball missing. Alternating renewal process with the challenge's run lengths.

    Missing runs ~ pool.missing (resampled). Present runs ~ pool.present scaled by c so the stationary
    rate is exactly `rate` in expectation:
        c = E[missing] * (1 - rate) / (rate * E[present])      (rounded, each run >= 1)
    A random phase offset into the first cycle removes the start-of-half bias. Measured with this
    construction on synthetic truth: realised overall 0.39-0.43 at target 0.407, realised
    P(missing | dead), P(missing | alive) = 0.83, 0.27 at dead_bias 3.
    """
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
    """Compose the strata into one ball-seen mask for a half. mode "transplant": decode window =
    cyclic window of the real mask at a TRANSPLANT_OFFSET-stream offset; pre-kickoff as below.
    mode "renewal":

        dead  = labels == D on [kickoff, n)      alive = otherwise on [kickoff, n)      prekick = [0, kickoff)
        p_alive, p_dead = solve_rates(alive.mean(), target, dead_bias, max_rate)
        seen[alive] = ~mask_alive[alive];  seen[dead] = ~mask_dead[dead];  seen[:kickoff] = ~mask_prekick
    where each mask is missing_mask over its own span (alive and dead over [kickoff, n), pre-kickoff
    over [0, kickoff)) with its own Stream; with a random phase that equals cutting it out of a
    whole-half draw. Re-draw (attempt k = 0..N) until |realised overall rate - target| <= tolerance
    over the decode window; keep the closest after max_attempts. The realised overall / P(m|dead) /
    P(m|alive) go into the Case provenance.
    """
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
    """SeedSequence([seed, game, half, stream]), child `attempt`. The game key is the crc32 of the
    match name, not its position in the input, so drawing one game alone reproduces its draws."""
    entropy = [seed, zlib.crc32(id.match.encode()), id.half, int(stream)]
    return np.random.default_rng(np.random.SeedSequence(entropy, spawn_key=(attempt,)))


def _run_lengths(mask: NDArray[np.bool_]) -> NDArray[np.int64]:
    edges = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    return edges[1::2] - edges[::2]


def fragment_slots(g: Geometry, rng: np.random.Generator) -> Geometry:
    """DEFERRED. Break identity: 46 anonymous slots, tracklet lifetimes, duplicates (>22 present at times),
    player dropout. Needs the gated ATD to calibrate (slot lifetimes, duplicate rate); until then the
    only anchors are S = 46 and ~20.5 present on average. Not needed for tier-0: nearest_team already
    reduces over slots per frame, so identity-freedom is a tested property of `challenge.nearest_team`
    (selfcheck.permutation_invariance), not something the dev data has to simulate."""
    raise NotImplementedError
