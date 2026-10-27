from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

FPS = 25

H, A, D, X = 0, 1, 2, 3

HOME, AWAY = H, A
NO_TEAM = -1

# pm.valid_runs splits runs at X; match_transitions has no run guard and pairs transitions across
# a short gap (measured: pairs stop at >= 24 X frames at tau = 25). 500 is margin, not a tuned value.
GAP_X = 500


def check_codes(codes: NDArray[np.int8], *, allow_x: bool) -> None:
    """Raise ValueError unless `codes` is int8 with every value in {0,1,2} (or {0,1,2,3}).

    pm.evaluate does no range check: pred=4 silently lands in the next GT row's H column and
    pred=-1 bleeds into the previous row.
    """
    if not isinstance(codes, np.ndarray) or codes.dtype != np.int8 or codes.ndim != 1:
        raise ValueError(f"codes must be a 1-D int8 array, got {type(codes).__name__} "
                         f"{getattr(codes, 'dtype', None)} ndim {getattr(codes, 'ndim', None)}")
    if codes.size == 0:
        return
    top = X if allow_x else D
    lo, hi = int(codes.min()), int(codes.max())
    if lo < 0 or hi > top:
        raise ValueError(f"codes outside 0..{top}: min {lo}, max {hi}")


def _freeze(*arrays: NDArray) -> None:
    for a in arrays:
        a.setflags(write=False)


@dataclass(frozen=True, slots=True)
class HalfId:
    """kickoff: local index of the kickoff, 0 <= kickoff < n. Frames [0, kickoff) are D by rule."""
    match: str
    half: int
    kickoff: int


@dataclass(frozen=True, slots=True)
class Geometry:
    """What a tracker saw in one half. Slots are anonymous: nothing follows a slot in time.

    ball_xy:    float32 [n, 2]    metres, origin top-left; NaN = ball not observed.
    players_xy: float32 [n, S, 2] metres; NaN = slot empty this frame.
    slot_team:  int8 [S]          0 = home, 1 = away; constant over the half.
    pitch_m:    (length, width)

    Invariants (checked in __post_init__, arrays frozen read-only): axis-0 lengths agree; slot_team
    values in {0, 1}; pitch positive. Anything computed from a Geometry must be invariant to slot
    order and slot count within a frame.
    """
    ball_xy: NDArray[np.float32]
    players_xy: NDArray[np.float32]
    slot_team: NDArray[np.int8]
    pitch_m: tuple[float, float]

    def __post_init__(self) -> None:
        b, p, t = self.ball_xy, self.players_xy, self.slot_team
        if b.dtype != np.float32 or b.ndim != 2 or b.shape[1] != 2:
            raise ValueError(f"ball_xy must be float32 [n, 2], got {b.dtype} {b.shape}")
        if p.dtype != np.float32 or p.ndim != 3 or p.shape[2] != 2 or p.shape[0] != b.shape[0]:
            raise ValueError(f"players_xy must be float32 [{b.shape[0]}, S, 2], got {p.dtype} {p.shape}")
        if t.dtype != np.int8 or t.shape != (p.shape[1],) or t.size == 0:
            raise ValueError(f"slot_team must be int8 [{p.shape[1]}] with S >= 1, got {t.dtype} {t.shape}")
        if not np.isin(t, (HOME, AWAY)).all():
            raise ValueError("slot_team values must be in {0, 1}")
        if len(self.pitch_m) != 2 or min(self.pitch_m) <= 0:
            raise ValueError(f"pitch_m must be two positive lengths, got {self.pitch_m}")
        _freeze(b, p, t)

    @property
    def n(self) -> int:
        return int(self.ball_xy.shape[0])


@dataclass(frozen=True, slots=True)
class BallGeometry:
    """Per-frame distances, in metres, from the same ball-to-slot distances as Half.nearest_team. All
    float32 [n], NaN exactly where nearest_team is NO_TEAM, team-symmetric and slot-order invariant.

    margin_m:  |nearest away distance - nearest home distance|; inf when one team has no slot present.
    nearest_m: distance to the nearest player of either team.
    outside_m: distance from the ball to the pitch rectangle, 0 on or inside the lines.
    speed_mps: ball speed in m/s from its displacement between frames t-2 and t+2, else between t and
               whichever of them has a ball; 0 when neither does.
    line_m:    distance from the ball to the nearest touchline or goal line, positive inside the pitch and
               negative outside. None when the source did not compute it.
    rel_mps:   speed in m/s of the ball relative to the nearest player, both velocities from frames t-2 and
               t+2; speed_mps where either lacks a position at both ends. None when not computed.
    goal_mps:  ball x velocity in m/s toward the goal the nearest player's team defends, from the same frames
               as speed_mps; 0 where that team's attack direction is unknown. None when not computed.
    vx_mps, vy_mps: the ball's velocity in m/s along the pitch's x and y axes, from the same frames as
               speed_mps; 0 where speed_mps is 0 because neither neighbour has a ball. None when not computed.
    """
    margin_m: NDArray[np.float32]
    nearest_m: NDArray[np.float32]
    outside_m: NDArray[np.float32]
    speed_mps: NDArray[np.float32]
    line_m: NDArray[np.float32] | None = None
    rel_mps: NDArray[np.float32] | None = None
    goal_mps: NDArray[np.float32] | None = None
    vx_mps: NDArray[np.float32] | None = None
    vy_mps: NDArray[np.float32] | None = None


@dataclass(frozen=True, slots=True)
class Half:
    """The decoder's whole input for one half.

    nearest_team: int8 [n] in {-1, 0, 1}. Team of the player nearest the ball (squared metres, first
                  minimum, no threshold). -1 means NO EVIDENCE: the ball was not observed (or no
                  slot present). It is a mask, never a dead-ball marker.
    geometry:     BallGeometry when the Half was observed from a Geometry (challenge.observe); None
                  for a token-only source (baseline_raw.csv).
    pace_mps:     float32 [n] next to geometry: the median over player slots present at frames t-12 and t+12
                  of their speed in m/s, NaN where no slot is and within 12 frames of either end. It reads a
                  slot across 24 frames, so it assumes the slot follows one tracked object over that span,
                  which holds for the ATD's track slots and the dev sources' player slots; a reused slot is
                  one outlier the median absorbs.
    push_mps:     float32 [n] next to pace_mps: home push minus away push, where a team's push is the median
                  over its slots present at t-12 and t+12 of the x velocity in m/s, positive toward the goal
                  the team attacks (it starts the half in the other half). NaN where either team has no such
                  slot.
    shape_lo:     float32 [n] next to push_mps: ln P(H) - ln P(A) from team shape alone (challenge._team_shape),
                  each team's outfield centroid, back line, length, width, spread and push in its own attacking
                  direction, home minus away, through fixed logistic weights; clipped to +-10, NaN where either team
                  has fewer than 8 players present.
    return_m:     float32 [n] next to shape_lo: on each frame of a ball gap with a seen ball on both sides, the
                  distance in metres from the last seen ball before the gap to the first after it; NaN elsewhere.

    Invariants: values in {-1,0,1}; 0 <= id.kickoff < n; geometry arrays float32 [n], NaN exactly on
    NO_TEAM frames.
    """
    id: HalfId
    nearest_team: NDArray[np.int8]
    geometry: BallGeometry | None = None
    pace_mps: NDArray[np.float32] | None = None
    push_mps: NDArray[np.float32] | None = None
    shape_lo: NDArray[np.float32] | None = None
    return_m: NDArray[np.float32] | None = None

    def __post_init__(self) -> None:
        tok = self.nearest_team
        if tok.dtype != np.int8 or tok.ndim != 1:
            raise ValueError(f"nearest_team must be 1-D int8, got {tok.dtype} ndim {tok.ndim}")
        if not np.isin(tok, (NO_TEAM, HOME, AWAY)).all():
            raise ValueError("nearest_team values must be in {-1, 0, 1}")
        if not 0 <= self.id.kickoff < self.n:
            raise ValueError(f"kickoff {self.id.kickoff} outside [0, {self.n})")
        _freeze(tok)
        if self.geometry is not None:
            unseen = tok == NO_TEAM
            for name in ("margin_m", "nearest_m", "outside_m", "speed_mps", "line_m", "rel_mps", "goal_mps",
                         "vx_mps", "vy_mps"):
                a = getattr(self.geometry, name)
                if a is None and name in ("line_m", "rel_mps", "goal_mps", "vx_mps", "vy_mps"):
                    continue
                if not isinstance(a, np.ndarray) or a.dtype != np.float32 or a.shape != tok.shape:
                    raise ValueError(f"geometry.{name} must be float32 [{self.n}], got "
                                     f"{getattr(a, 'dtype', None)} {getattr(a, 'shape', None)}")
                if not np.array_equal(np.isnan(a), unseen):
                    raise ValueError(f"geometry.{name} must be NaN exactly where nearest_team is NO_TEAM")
                _freeze(a)
        for name in ("pace_mps", "push_mps", "shape_lo", "return_m"):
            a = getattr(self, name)
            if a is None:
                continue
            if not isinstance(a, np.ndarray) or a.dtype != np.float32 or a.shape != tok.shape:
                raise ValueError(f"{name} must be float32 [{self.n}], got {getattr(a, 'dtype', None)} "
                                 f"{getattr(a, 'shape', None)}")
            _freeze(a)

    @property
    def n(self) -> int:
        return int(self.nearest_team.shape[0])


@dataclass(frozen=True, slots=True)
class CleanHalf:
    """geometry:   ball_xy has NO NaN.
    labels:     int8 [n] in {0,1,2}.
    provenance: JSON-able record of everything that shaped the labels and the fill.
    Invariants: labels[:id.kickoff] all D; geometry.n == len(labels).
    """
    id: HalfId
    geometry: Geometry
    labels: NDArray[np.int8]
    provenance: Mapping[str, object]

    def __post_init__(self) -> None:
        check_codes(self.labels, allow_x=False)
        n = len(self.labels)
        if self.geometry.n != n:
            raise ValueError(f"geometry has {self.geometry.n} frames, labels {n}")
        if not 0 <= self.id.kickoff < n:
            raise ValueError(f"kickoff {self.id.kickoff} outside [0, {n})")
        if (self.labels[:self.id.kickoff] != D).any():
            raise ValueError("labels before kickoff must all be D")
        if np.isnan(self.geometry.ball_xy).any():
            raise ValueError("CleanHalf ball has NaN: native NaN must be filled before dropout")
        _freeze(self.labels)


@dataclass(frozen=True, slots=True)
class Block:
    """Where one half sits in the scorer array: rows [origin, origin + n)."""
    origin: int
    n: int


@dataclass(frozen=True, slots=True)
class Layout:
    """Placement of halves inside a scorer array of length n_total.

    Invariants: blocks ascending and disjoint; >= GAP_X rows before the first block, between blocks
    and after the last.
    """
    n_total: int
    blocks: tuple[Block, ...]

    def __post_init__(self) -> None:
        edge = 0
        for b in self.blocks:
            if b.n < 1 or b.origin - edge < GAP_X:
                raise ValueError(f"block {b} needs n >= 1 and >= {GAP_X} X rows before it "
                                 f"(previous edge {edge})")
            edge = b.origin + b.n
        if self.n_total - edge < GAP_X:
            raise ValueError(f"n_total {self.n_total} leaves fewer than {GAP_X} X rows after the last block")

    @staticmethod
    def synthetic(sizes: Sequence[int]) -> Layout:
        """GAP_X X rows, then each block followed by GAP_X X rows. n_total = GAP_X + sum(size + GAP_X)."""
        blocks, origin = [], GAP_X
        for size in sizes:
            blocks.append(Block(origin=origin, n=int(size)))
            origin += int(size) + GAP_X
        return Layout(n_total=origin, blocks=tuple(blocks))

    def assemble(self, parts: Sequence[NDArray[np.int8]]) -> NDArray[np.int8]:
        """int8 [n_total] pre-filled with X, each part copied to its block. parts[i].shape == (blocks[i].n,).
        Every part is range-checked before the copy."""
        if len(parts) != len(self.blocks):
            raise ValueError(f"{len(parts)} parts for {len(self.blocks)} blocks")
        out = np.full(self.n_total, X, dtype=np.int8)
        for b, part in zip(self.blocks, parts):
            check_codes(part, allow_x=True)
            if part.shape != (b.n,):
                raise ValueError(f"part of shape {part.shape} for a block of {b.n} rows")
            out[b.origin:b.origin + b.n] = part
        return out

    def cut(self, array: NDArray) -> list[NDArray]:
        """Views of a scorer-length array, one per block. Inverse of assemble."""
        if array.shape[0] != self.n_total:
            raise ValueError(f"array has {array.shape[0]} rows, layout {self.n_total}")
        return [array[b.origin:b.origin + b.n] for b in self.blocks]
