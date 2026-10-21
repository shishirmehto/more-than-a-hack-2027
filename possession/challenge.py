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

from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray

import games  # repo-root module, stdlib only; frozen

from . import score  # no cycle: score imports half only
from .half import D, NO_TEAM, Geometry, Half, HalfId, Layout

GAME = games.GAME  # "BAR-ATH"

# Kickoff rows (submission rows == tactical video frames), published in FAQ.md and equal to
# starter/load_smart_tagging.KICKOFF_VIDEO_FRAMES. games.anchor_video_frame is off by one; not used.
KICKOFF_ROW: dict[int, int] = {1: 11185, 2: 113742}

BASELINE_RAW = Path(__file__).resolve().parents[1] / "evaluation" / "results" / "baseline_raw.csv"


def layout() -> Layout:
    """The real scorer layout: n_total = games.source_frames("tactical") (199,319), blocks from
    games.half_video_blocks(GAME).

    (half, first, last) -> Block(origin=first, n=last - first + 1) = (11185, 79467), (110808, 79390).
    Kickoff local index = KICKOFF_ROW[half] - first (0 and 2934).
    """
    raise NotImplementedError


def nearest_team(g: Geometry) -> NDArray[np.int8]:
    """THE tier-0 convention. int8 [n] in {-1, 0, 1}.

    Per frame with an observed ball: squared distance in metres from the ball to every non-NaN slot,
    take the FIRST minimum (np.argmin), return slot_team of that slot; no distance threshold.
    -1 where the ball is NaN or no slot is present. Distances in float64 (upcast), chunked over
    frames so peak memory stays ~30 MB at S = 46.
    """
    # TODO: for chunk in frames(20_000):
    #           d = ((players[chunk] - ball[chunk, None, :]) ** 2).sum(-1)      # [c, S], NaN propagates
    #           d = np.where(np.isnan(d), np.inf, d); j = d.argmin(1)
    #           ok = ~np.isnan(ball[chunk, 0]) & np.isfinite(d[np.arange(c), j])
    #           out[chunk] = np.where(ok, slot_team[j], NO_TEAM)
    raise NotImplementedError


def observe(g: Geometry, id: HalfId) -> Half:
    """Geometry -> Half. First implementation: nearest_team only, features=None.

    The single place a Half is derived from geometry, for the challenge and for Metrica dev halves
    alike. Slot-order and slot-count invariant by construction (reduces over slots per frame).
    DEFERRED: compute `Features` here (team-paired, ball-free and ball-based columns).
    """
    # TODO: return Half(id=id, nearest_team=nearest_team(g), features=None)
    raise NotImplementedError


def halves(source: Literal["baseline_raw", "atd"] = "baseline_raw",
           data_dir: str | Path | None = None) -> tuple[Half, Half]:
    """The two decoder inputs for BAR-ATH from the chosen source. THE seam; see module docstring."""
    # TODO: "baseline_raw" -> _halves_from_baseline_raw(BASELINE_RAW)
    # TODO: "atd"          -> [observe(g, HalfId(GAME, h, kickoff_h)) for h, g in enumerate(load_geometry(data_dir), 1)]
    raise NotImplementedError


def _halves_from_baseline_raw(path: Path) -> tuple[Half, Half]:
    """baseline_raw.csv -> tier-0 Halves. READ THIS BEFORE TOUCHING.

    In that file label D means "ball not observed" (85,831 rows == 199,319 - 113,488 ball-present
    frames), NOT dead ball: 66% of public-window GT-D frames have a visible ball and 44% of
    ball-missing frames are inside live possession. So: D -> NO_TEAM (a mask), H -> HOME, A -> AWAY.
    The decoder never sees the word "D" from this source.
    """
    # TODO: codes = score.read_codes(path, n_expected=games.source_frames("tactical"))   # one CSV boundary, in score.py
    # TODO: token = np.where(codes == D, NO_TEAM, codes).astype(int8)  # H=0 -> HOME, A=1 -> AWAY
    # TODO: for (half, first, last) in games.half_video_blocks(GAME):
    #           Half(HalfId(GAME, half, KICKOFF_ROW[half] - first), token[first:last + 1].copy())
    raise NotImplementedError


def load_geometry(data_dir: str | Path | None = None) -> tuple[Geometry, Geometry]:
    """DEFERRED (gated data not on disk). Raw ATD -> one Geometry per half, S = 46 anonymous slots.

    Grammar (starter/baseline.py): line = `frame_id:slot;slot;...(46):ball`, slot = `x,y,speed`,
    a group starting with 'N' is NaN; ball group has >= 3 comma fields (third unknown: z or NaN).
    Use games.require(["atd_meta", "atd_raw"]); numpy parse of the whole file is ~1 s (kloppy takes
    minutes and gigabytes: not used). Row = frame_id - 1; slice halves by games.half_video_blocks.
    Reuse starter.baseline.team_of_each_track for slot_team (reading starter is fine; editing is not).
    """
    raise NotImplementedError
