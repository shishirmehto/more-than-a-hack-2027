from __future__ import annotations

import functools
import xml.etree.ElementTree as ET
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

_NORM_LIMIT = 2.0


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
    return Half(id=id, nearest_team=nearest_team(g))


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
    """The tactical ATD as one Geometry per layout() block; block row i is ATD frame_id origin + i + 1.

    Metres use games' pitch (105.3, 68.0), as baseline.py does. The XML FieldSize says 105 x 68.
    Speeds are dropped. Raises IOError when the gated files are not on disk.
    """
    meta, raw = games.require(["atd_meta", "atd_raw"], GAME, data_dir)
    return _load_geometry(str(Path(meta).resolve()), str(Path(raw).resolve()))


@functools.cache
def _load_geometry(meta: str, raw: str) -> tuple[Geometry, Geometry]:
    slot_team = _atd_slot_team(ET.parse(meta).getroot())
    ball, players = _read_atd(Path(raw), len(slot_team))
    pitch = games.GAMES[GAME]["pitch"]
    scale = np.array(pitch, np.float64)
    g1, g2 = (Geometry((ball[b.origin:b.origin + b.n] * scale).astype(np.float32),
                       (players[b.origin:b.origin + b.n] * scale).astype(np.float32),
                       slot_team, pitch)
              for b in layout().blocks)
    return g1, g2


def _atd_slot_team(meta: ET.Element) -> NDArray[np.int8]:
    """Slot s is the s-th <Player>, and the first <Team> is home."""
    team_ids = [team.get("id") for team in meta.iter("Team")]
    players = list(meta.iter("Player"))
    if len(team_ids) != 2 or not players:
        raise ValueError(f"ATD metadata: {len(team_ids)} teams and {len(players)} players")
    channel_player = {c.get("id"): c.get("playerId") for c in meta.iter("PlayerChannel")}
    line_order = list(dict.fromkeys(channel_player[ref.get("playerChannelId")]
                                    for ref in meta.iter("PlayerChannelRef")))
    if line_order != [p.get("id") for p in players]:
        raise ValueError("ATD metadata: the raw-line player order is not the <Player> order")
    return np.array([team_ids.index(p.get("teamId")) for p in players], np.int8)


def _read_atd(raw: Path, n_slots: int) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Normalised ball [n, 2] and players [n, S, 2], NaN where unobserved; row i is frame_id i + 1.

    A line is "frame:x,y,speed;...(S groups):x,y,speed".
    """
    lines = raw.read_text().split()
    width = 1 + 3 * n_slots + 3
    flat = np.fromstring(",".join(lines).translate(str.maketrans(":;", ",,")), sep=",")
    if flat.size != len(lines) * width:
        raise ValueError(f"{raw.name}: {flat.size} values for {len(lines)} lines of {width}")
    rows = flat.reshape(len(lines), width)
    n = games.source_frames("tactical", GAME)
    if not np.array_equal(rows[:, 0], np.arange(1, n + 1)):
        raise ValueError(f"{raw.name}: frame ids are not 1..{n} in order")
    ball, players = rows[:, -3:-1], rows[:, 1:-3].reshape(n, n_slots, 3)[..., :2]
    # The ball reaches y = 1.49 (measured); this only catches a file already in metres.
    if max(np.nanmax(np.abs(ball)), np.nanmax(np.abs(players))) > _NORM_LIMIT:
        raise ValueError(f"{raw.name}: coordinates exceed {_NORM_LIMIT}, expected normalised")
    return ball, players
