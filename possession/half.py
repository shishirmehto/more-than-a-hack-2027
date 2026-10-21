"""Shared vocabulary: label codes, the three array bundles modules trade in, and the scorer layout.

Owns the definition of a *half* (one gap-free 25 fps block from one period of one match) and where
halves sit inside a scorer array. Knows nothing about Metrica, the challenge ATD, HMMs or `pm`.

Three bundles, one per stage of knowledge, not per pipeline step:

    Geometry   what a tracker saw        (Level A: ball + anonymous slots, metres)
    Half       what the decoder is given (Level B: per-frame team evidence, optional features)
    CleanHalf  a dev half before dropout (Geometry with a fully observed ball + event-derived labels)

`Half` deliberately has no geometry field. Geometry is optional-in-practice on a bundle that the
tier-0 challenge path (baseline_raw.csv) can never fill, and "sometimes geometric" types force an
`if half.geometry is None` branch into the decoder. Sources that have geometry reduce it through
`challenge.observe`; sources that do not (baseline_raw) build `Half` directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

FPS = 25

# Scorer contract. score.py asserts these equal pm.H/A/D/X at import, so this is the single copy
# the package owns and pm remains the authority.
H, A, D, X = 0, 1, 2, 3

# Team token space of `Half.nearest_team`. HOME == H and AWAY == A on purpose: a token is "the
# label this frame would have if the nearest player's team had the ball".
HOME, AWAY, NO_TEAM = 0, 1, -1

# pm.valid_runs splits runs at X; match_transitions has no run guard and pairs transitions across
# a short gap (measured: pairs stop at >= 24 X frames at tau = 25). 500 is margin, not a tuned value.
GAP_X = 500


def check_codes(codes: NDArray[np.int8], *, allow_x: bool) -> None:
    """Raise ValueError unless `codes` is int8 with every value in {0,1,2} (or {0,1,2,3}).

    pm.evaluate does no range check: pred=4 silently lands in the next GT row's H column and
    pred=-1 bleeds into the previous row. Every array that reaches the scorer passes through here
    first (Layout.assemble, score.evaluate, score.write_submission).
    """
    # TODO: dtype == int8; codes.min() >= 0; codes.max() <= (X if allow_x else D).
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class HalfId:
    """Identity and the one structural prior every decoder needs.

    match:   "BAR-ATH" | "metrica_g1" | "metrica_g2" | "metrica_g3"
    half:    1 | 2
    kickoff: local index of the kickoff, 0 <= kickoff < n. Frames [0, kickoff) are D by rule.
             Challenge: half 1 -> 0, half 2 -> 2934 (113742 - 110808, published in FAQ.md).
             Metrica: start of the first KICK OFF event of the period minus the block start.
    """
    match: str
    half: int
    kickoff: int


@dataclass(frozen=True, slots=True)
class Geometry:
    """Level A. What a tracker saw in one half. Slots are anonymous: nothing follows a slot in time.

    ball_xy:    float32 [n, 2]    metres, origin top-left; NaN = ball not observed.
    players_xy: float32 [n, S, 2] metres; NaN = slot empty this frame. S = 46 challenge, 22..28 Metrica.
    slot_team:  int8 [S]          0 = home, 1 = away; constant over the half.
    pitch_m:    (length, width)   (105.3, 68.0) challenge (games.py), (105.0, 68.0) Metrica.

    Invariants (checked in __post_init__, arrays frozen read-only): axis-0 lengths agree; slot_team
    values in {0, 1}; pitch positive. Anything computed from a Geometry must be invariant to slot
    order and slot count within a frame (see selfcheck.permutation_invariance).
    """
    ball_xy: NDArray[np.float32]
    players_xy: NDArray[np.float32]
    slot_team: NDArray[np.int8]
    pitch_m: tuple[float, float]

    def __post_init__(self) -> None:
        # TODO: shape/dtype checks above; setflags(write=False) on all three arrays.
        pass

    @property
    def n(self) -> int:
        return int(self.ball_xy.shape[0])


@dataclass(frozen=True, slots=True)
class Features:
    """Per-frame, slot-order-invariant columns beyond the team token. DEFERRED: always None in the
    first implementation.

    names:  fixed order, team-paired (H then A) so a team swap equals a column-pair swap.
            e.g. ("d_nearest_H", "d_nearest_A", "n_within_5m_H", "n_within_5m_A", "ball_speed", ...)
    values: float32 [n, F]; NaN where undefined (ball unobserved). Ball-free columns (team centroid
            offsets, compactness) stay defined during dropout; that is where the ATD era earns its
            keep, because dropout blocks are 10 s of otherwise zero evidence.
    A second source of columns is Smart Tagging set-piece windows (a dead-ball prior); same contract.
    """
    names: tuple[str, ...]
    values: NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class Half:
    """Level B. The decoder's whole input for one half. Source-agnostic.

    id:           HalfId.
    nearest_team: int8 [n] in {-1, 0, 1}. Team of the player nearest the ball (squared metres, first
                  minimum, no threshold: the baseline's convention). -1 means NO EVIDENCE: the ball
                  was not observed (or no slot present). It is a mask, never a dead-ball marker.
    features:     optional richer evidence, see Features.

    n is derived from nearest_team (single source of truth). Invariants: values in {-1,0,1};
    0 <= id.kickoff < n; features is None or features.values.shape[0] == n.
    """
    id: HalfId
    nearest_team: NDArray[np.int8]
    features: Features | None = None

    def __post_init__(self) -> None:
        # TODO: validate invariants above; freeze arrays.
        pass

    @property
    def n(self) -> int:
        return int(self.nearest_team.shape[0])


@dataclass(frozen=True, slots=True)
class CleanHalf:
    """A dev half before challenge-ification: everything Metrica knows, nothing challenge-like yet.

    geometry:   ball_xy has NO NaN (native out-of-play NaN is filled by the source adapter, so the
                only NaN that can ever reach a decoder are the injected dropout ones).
    labels:     int8 [n] in {0,1,2}. No X inside the block; X exists only outside blocks (Layout).
    provenance: JSON-able record of everything that shaped the labels and the fill, e.g.
                {"rule": "v2", "merge_s": 1.0, "pre_kickoff": "D", "ball_fill": "hold",
                 "sample_data_commit": "e706dd5..."}.
    Invariants: labels[:id.kickoff] all D; geometry.n == len(labels).
    """
    id: HalfId
    geometry: Geometry
    labels: NDArray[np.int8]
    provenance: Mapping[str, object]

    def __post_init__(self) -> None:
        # TODO: validate; assert not np.isnan(geometry.ball_xy).any().
        pass


@dataclass(frozen=True, slots=True)
class Block:
    """Where one half sits in the scorer array: rows [origin, origin + n)."""
    origin: int
    n: int


@dataclass(frozen=True, slots=True)
class Layout:
    """Placement of halves inside a scorer array of length n_total. The only owner of origins.

    Invariants: blocks ascending and disjoint; >= GAP_X rows before the first block, between blocks
    and after the last (so pm.valid_runs yields exactly one run per half). The challenge layout
    (challenge.layout) satisfies this trivially; Layout.synthetic builds it for dev.
    """
    n_total: int
    blocks: tuple[Block, ...]

    @staticmethod
    def synthetic(sizes: Sequence[int], gap: int = GAP_X) -> Layout:
        """gap, then each block followed by gap. n_total = gap + sum(size + gap).
        Raises ValueError if gap < GAP_X: a short gap would let pm.match_transitions pair transitions across halves."""
        # TODO: origins by running sum; return Layout.
        raise NotImplementedError

    def assemble(self, parts: Sequence[NDArray[np.int8]]) -> NDArray[np.int8]:
        """int8 [n_total] pre-filled with X, each part copied to its block. parts[i].shape == (blocks[i].n,)."""
        # TODO: out = np.full(n_total, X, np.int8); out[o:o+n] = part; check_codes(out, allow_x=True).
        raise NotImplementedError

    def cut(self, array: NDArray) -> list[NDArray]:
        """Views of a scorer-length array, one per block. Inverse of assemble."""
        raise NotImplementedError
