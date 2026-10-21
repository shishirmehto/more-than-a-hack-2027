"""Everything about BAR-ATH and the observation convention the challenge baseline established.

Owns: the half blocks and kickoffs, the tier-0 token (`nearest_team`), baseline_raw.csv -> Half, and
the seam where the gated ATD plugs in. The Metrica dev set reuses `observe` so dev observations are
built by the same function, with the same arithmetic, as the real match's.

THE SEAM. `halves(source)` is the only thing downstream code calls:

    halves("baseline_raw")  today.  Reads evaluation/results/baseline_raw.csv (committed, full match).
    halves("atd")           later.   load_geometry() -> observe() per half. Nothing else changes.

What the ATD loader must produce (per half, rows = ATD frame_id - 1, spans from games.half_video_blocks):
    Geometry(ball_xy float32[n,2], players_xy float32[n,46,2], slot_team int8[46], pitch_m=(105.3, 68.0))
    metres = normalised * pitch (x by 105.3, y by 68.0, as starter/baseline.py), NaN where the ATD
    group starts with 'N'. slot_team from the XML <Player teamId> order, first <Team> = home.
    Regression gate once data lands: observe(geometry).nearest_team must reproduce baseline_raw.csv
    (label != "D" <=> ball seen; token == label elsewhere) on >= 99.99% of frames. Exact equality is
    not promised: float32 storage can flip a near-tie that the baseline's float64 text parse resolves
    the other way.
"""
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
    games.half_video_blocks(GAME).

    (half, first, last) -> Block(origin=first, n=last - first + 1) = (11185, 79467), (110808, 79390).
    """
    blocks = tuple(Block(origin=first, n=last - first + 1)
                   for _, first, last in games.half_video_blocks(GAME))
    return Layout(n_total=games.source_frames("tactical"), blocks=blocks)


def _half_ids() -> tuple[HalfId, HalfId]:
    """One HalfId per block of layout(), in half order. Kickoff local index = KICKOFF_ROW[half] - the
    block's origin (0 and 2934)."""
    h1, h2 = (HalfId(GAME, half, KICKOFF_ROW[half] - b.origin) for half, b in enumerate(layout().blocks, start=1))
    return h1, h2


def nearest_team(g: Geometry) -> NDArray[np.int8]:
    """THE tier-0 convention. int8 [n] in {-1, 0, 1}.

    Per frame with an observed ball: squared distance in metres from the ball to every non-NaN slot,
    take the FIRST minimum (np.argmin), return slot_team of that slot; no distance threshold.
    -1 where the ball is NaN or no slot is present. Distances in float64 (upcast), chunked over
    frames so peak memory stays ~30 MB at S = 46.
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
    """Geometry -> Half. First implementation: nearest_team only, features=None.

    The single place a Half is derived from geometry, for the challenge and for Metrica dev halves
    alike. Slot-order and slot-count invariant by construction (reduces over slots per frame), up to
    exact distance ties, which go to the first slot.
    DEFERRED: compute `Features` here (team-paired, ball-free and ball-based columns).
    """
    return Half(id=id, nearest_team=nearest_team(g), features=None)


def halves(source: Literal["baseline_raw", "atd"] = "baseline_raw",
           data_dir: str | Path | None = None) -> tuple[Half, Half]:
    """The two decoder inputs for BAR-ATH from the chosen source. THE seam; see module docstring."""
    if source == "baseline_raw":
        return _halves_from_baseline_raw()
    if source == "atd":
        (g1, g2), (id1, id2) = load_geometry(data_dir), _half_ids()
        return observe(g1, id1), observe(g2, id2)
    raise ValueError(f"unknown source {source!r}; have 'baseline_raw', 'atd'")


@functools.cache
def _halves_from_baseline_raw() -> tuple[Half, Half]:
    """baseline_raw.csv -> tier-0 Halves. READ THIS BEFORE TOUCHING.

    In that file label D means "ball not observed" (85,831 rows == 199,319 - 113,488 ball-present
    frames), NOT dead ball: 66% of public-window GT-D frames have a visible ball and 44% of
    ball-missing frames are inside live possession. So: D -> NO_TEAM (a mask), H -> HOME, A -> AWAY.
    The decoder never sees the word "D" from this source.

    Cached per process (every dev world's dropout pool reads it); a Half's arrays are read-only.
    """
    full = layout()
    codes = score.read_codes(BASELINE_RAW, n_expected=full.n_total)
    token = np.where(codes == D, NO_TEAM, codes).astype(np.int8)
    h1, h2 = (Half(id, part.copy()) for id, part in zip(_half_ids(), full.cut(token)))
    return h1, h2


def load_geometry(data_dir: str | Path | None = None) -> tuple[Geometry, Geometry]:
    """DEFERRED (gated data not on disk). Raw ATD -> one Geometry per half, S = 46 anonymous slots.

    Grammar (starter/baseline.py): line = `frame_id:slot;slot;...(46):ball`, slot = `x,y,speed`,
    a group starting with 'N' is NaN; ball group has >= 3 comma fields (third unknown: z or NaN).
    Use games.require(["atd_meta", "atd_raw"]); numpy parse of the whole file is ~1 s (kloppy takes
    minutes and gigabytes: not used). Row = frame_id - 1; slice halves by games.half_video_blocks.
    Reuse starter.baseline.team_of_each_track for slot_team (reading starter is fine; editing is not).
    """
    raise NotImplementedError(
        "challenge.load_geometry: the ATD parser is not written yet (the gated data is not on disk). "
        "Use halves('baseline_raw') until it lands; the docstring states what it must return.")
