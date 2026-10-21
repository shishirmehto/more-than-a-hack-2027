from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray

import games

from . import score
from .half import D, NO_TEAM, Block, Geometry, Half, HalfId, Layout

GAME = games.GAME

# games.anchor_video_frame is off by one; not used.
KICKOFF_ROW: dict[int, int] = {1: 11185, 2: 113742}

BASELINE_RAW = Path(__file__).resolve().parents[1] / "evaluation" / "results" / "baseline_raw.csv"

_CHUNK = 20_000


def layout() -> Layout:
    """The real scorer layout: n_total = games.source_frames("tactical") (199,319), blocks from
    games.half_video_blocks(GAME)."""
    blocks = tuple(Block(origin=first, n=last - first + 1)
                   for _, first, last in games.half_video_blocks(GAME))
    return Layout(n_total=games.source_frames("tactical"), blocks=blocks)


def _half_ids() -> tuple[HalfId, HalfId]:
    h1, h2 = (HalfId(GAME, half, KICKOFF_ROW[half] - b.origin) for half, b in enumerate(layout().blocks, start=1))
    return h1, h2


def nearest_team(g: Geometry) -> NDArray[np.int8]:
    """int8 [n] in {-1, 0, 1}.

    Per frame with an observed ball: squared distance in metres from the ball to every non-NaN slot,
    take the FIRST minimum (np.argmin), return slot_team of that slot; no distance threshold.
    -1 where the ball is NaN or no slot is present.
    """
    out = np.full(g.n, NO_TEAM, dtype=np.int8)
    for lo in range(0, g.n, _CHUNK):
        ball = g.ball_xy[lo:lo + _CHUNK].astype(np.float64)
        players = g.players_xy[lo:lo + _CHUNK].astype(np.float64)
        d = ((players - ball[:, None, :]) ** 2).sum(-1)
        d = np.where(np.isnan(d), np.inf, d)
        j = d.argmin(1)
        ok = ~np.isnan(ball[:, 0]) & np.isfinite(d[np.arange(len(j)), j])
        out[lo:lo + _CHUNK] = np.where(ok, g.slot_team[j], NO_TEAM)
    return out


def observe(g: Geometry, id: HalfId) -> Half:
    """Geometry -> Half.

    Slot-order and slot-count invariant by construction, up to exact distance ties, which go to the
    first slot.
    """
    return Half(id=id, nearest_team=nearest_team(g), features=None)


def halves(source: Literal["baseline_raw", "atd"] = "baseline_raw",
           data_dir: str | Path | None = None) -> tuple[Half, Half]:
    """The two decoder inputs for BAR-ATH from the chosen source."""
    if source == "baseline_raw":
        return _halves_from_baseline_raw()
    if source == "atd":
        (g1, g2), (id1, id2) = load_geometry(data_dir), _half_ids()
        return observe(g1, id1), observe(g2, id2)
    raise ValueError(f"unknown source {source!r}; have 'baseline_raw', 'atd'")


@functools.cache
def _halves_from_baseline_raw() -> tuple[Half, Half]:
    """baseline_raw.csv -> tier-0 Halves.

    In that file label D means "ball not observed", NOT dead ball.
    """
    full = layout()
    codes = score.read_codes(BASELINE_RAW, n_expected=full.n_total)
    token = np.where(codes == D, NO_TEAM, codes).astype(np.int8)
    h1, h2 = (Half(id, part.copy()) for id, part in zip(_half_ids(), full.cut(token)))
    return h1, h2


def load_geometry(data_dir: str | Path | None = None) -> tuple[Geometry, Geometry]:
    raise NotImplementedError(
        "challenge.load_geometry: the ATD parser is not written yet (the gated data is not on disk). "
        "Use halves('baseline_raw') until it lands; possession/DESIGN.md, 'Where the ATD plugs in', "
        "states what it must return.")
