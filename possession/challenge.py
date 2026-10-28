from __future__ import annotations

import functools
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Literal

import numpy as np
from numpy.typing import NDArray

import games

from . import score
from .half import AWAY, D, FPS, HOME, NO_TEAM, BallGeometry, Block, Geometry, Half, HalfId, Layout

GAME = games.GAME

# games.anchor_video_frame is off by one; not used.
KICKOFF_ROW: dict[int, int] = {1: 11185, 2: 113742}

BASELINE_RAW = Path(__file__).resolve().parents[1] / "evaluation" / "results" / "baseline_raw.csv"

SET_PIECES = "set pieces"
GOALS = "goals"
KICKOFF_START = "kick off (start)"
# The restart kinds whose tag marks a stoppage for DecoderParams.stoppage_fill (E81: throw-ins and goal kicks).
STOPPAGE_KINDS = ("throw-in", "goal kick")

_TAG_HALF = {"1st half": 1, "2nd half": 2}

_CHUNK = 20_000
_SPEED_STEP = 2
_PACE_STEP = 12
# Logistic weights of P(home in possession) on _team_shape's columns (adv, line, length, width, spread, push; metres
# and m/s), no intercept so the score is team-symmetric, fitted on IDSSE m0 live frames at 5 Hz by the
# player-position session (in-sample accuracy 0.827). No PFF or BAR-ATH data entered them.
_SHAPE_W = (0.0453, -0.0656, 0.0253, 0.0926, 0.15, 0.2108)
_SHAPE_MIN_PLAYERS, _SHAPE_CAP = 8, 10.0
_PRESS_K, _PRESS_MIN_M = 3, 1.0

_NORM_LIMIT = 2.0
# The broadcast ATD's mapping onto tactical rows (E83): generic geometric tolerances, set once from the exploring
# session's alignment statistics and never tuned on a decode.
_ANCHORS, _ANCHOR_STRIDE, _ANCHOR_PLAYERS, _ANCHOR_CAP_M, _ANCHOR_BEST_M, _ANCHOR_AWAY = 60, 5, 12, 15.0, 1.5, 10 * FPS
_MATCH_PLAYERS, _MATCH_M = 6, 1.5
# A chunk's float sums can depend on its row count, so this size is part of every pinned build that reads the broadcast.
_MATCH_CHUNK = 4096


@dataclass(frozen=True, slots=True)
class Tag:
    """One Smart Tagging instance on submission rows. Automatic: a phase or a restart, not a
    possession, and not ground truth.

    code:        casefolded, e.g. "set pieces", "build up".
    kind:        the casefolded "Type" tag ("throw-in", "corner kick", "kick off (start)", ...); None
                 when the instance has none (only set pieces carry one).
    team:        HOME | AWAY by the ATD metadata's team names (first <Team> is home); NO_TEAM for "N/A".
    half:        1 | 2.
    start, stop: submission rows [start, stop), round(seconds * FPS). 0 <= start < stop.
    """
    code: str
    kind: str | None
    team: int
    half: int
    start: int
    stop: int

    @property
    def restart(self) -> bool:
        """A set piece other than a half's opening kickoff: the stretch before it is dead ball. The
        opening kickoff's dead stretch is the pre-kickoff zone instead."""
        return self.code == SET_PIECES and self.kind != KICKOFF_START

    @property
    def phase(self) -> bool:
        """A team phase: credited to one team, and neither a set piece nor a goal. A goals tag runs on
        through the stoppage to the kick off after the goal."""
        return self.code not in (SET_PIECES, GOALS) and self.team != NO_TEAM


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
    return _nearest(g)[0]


def _nearest(g: Geometry) -> tuple[NDArray[np.int8], BallGeometry]:
    """nearest_team and the BallGeometry built from the same squared distances."""
    out = np.full(g.n, NO_TEAM, dtype=np.int8)
    d_team = np.full((g.n, 2), np.inf)
    nearest_slot = np.zeros(g.n, dtype=np.intp)
    home = g.slot_team == HOME
    for lo in range(0, g.n, _CHUNK):
        ball = g.ball_xy[lo:lo + _CHUNK].astype(np.float64)
        players = g.players_xy[lo:lo + _CHUNK].astype(np.float64)
        d = ((players - ball[:, None, :]) ** 2).sum(-1)
        d = np.where(np.isnan(d), np.inf, d)
        j = d.argmin(1)
        ok = ~np.isnan(ball[:, 0]) & np.isfinite(d[np.arange(len(j)), j])
        out[lo:lo + _CHUNK] = np.where(ok, g.slot_team[j], NO_TEAM)
        nearest_slot[lo:lo + _CHUNK] = j
        d_team[lo:lo + _CHUNK, HOME] = np.where(home, d, np.inf).min(1)
        d_team[lo:lo + _CHUNK, AWAY] = np.where(home, np.inf, d).min(1)
    unseen = out == NO_TEAM
    dist = np.sqrt(d_team)
    with np.errstate(invalid="ignore"):
        margin = np.abs(dist[:, AWAY] - dist[:, HOME])
    margin[np.isinf(dist).any(1)] = np.inf
    length, width = g.pitch_m
    x, y = g.ball_xy[:, 0].astype(np.float64), g.ball_xy[:, 1].astype(np.float64)
    outside = np.hypot(np.maximum.reduce([np.zeros(g.n), -x, x - length]),
                       np.maximum.reduce([np.zeros(g.n), -y, y - width]))
    line = np.minimum.reduce([x, length - x, y, width - y])
    speed = _ball_speed(g.ball_xy.astype(np.float64))
    arrays = [np.where(unseen, np.nan, a).astype(np.float32)
              for a in (margin, dist.min(1), outside, speed, line, _relative_speed(g, nearest_slot, speed))]
    return out, BallGeometry(*arrays)


def _relative_speed(g: Geometry, slot: NDArray[np.intp], speed: NDArray[np.float64]) -> NDArray[np.float64]:
    """|ball velocity - velocity of the frame's nearest slot| from frames t-2 and t+2; speed where either
    the ball or that slot lacks a position at both ends."""
    k, n = _SPEED_STEP, g.n
    t = np.arange(k, n - k)
    ball = g.ball_xy.astype(np.float64)
    who = slot[t]
    vb = (ball[t + k] - ball[t - k]) * FPS / (2 * k)
    vp = (g.players_xy[t + k, who].astype(np.float64) - g.players_xy[t - k, who].astype(np.float64)) * FPS / (2 * k)
    rel = speed.copy()
    both = np.isfinite(vb).all(1) & np.isfinite(vp).all(1)
    rel[t[both]] = np.hypot(*(vb[both] - vp[both]).T)
    return rel


def _attack_signs(g: Geometry, kickoff: int) -> dict[int, float | None]:
    """Per team, +1 when it attacks toward +x, -1 toward 0, None when it has no slot over the first second
    after kickoff. With both teams placed, the team whose slots' mean x is lower attacks +x, so the two always
    attack opposite ways; with one, it attacks +x when its mean x is in the left half."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        x = {team: float(np.nanmean(g.players_xy[kickoff:kickoff + FPS, g.slot_team == team, 0]))
             for team in (HOME, AWAY)}
    if not np.isnan(x[HOME]) and not np.isnan(x[AWAY]):
        home = 1.0 if x[HOME] < x[AWAY] else -1.0
        return {HOME: home, AWAY: -home}
    return {team: None if np.isnan(v) else 1.0 if v < g.pitch_m[0] / 2 else -1.0 for team, v in x.items()}


def _goal_velocity(g: Geometry, kickoff: int, token: NDArray[np.int8]) -> NDArray[np.float32]:
    """BallGeometry.goal_mps: the ball's x velocity from frames t-2 and t+2, else between t and whichever of
    them has a ball, 0 when neither, signed toward the goal the token's team defends (_attack_signs), and 0
    for a team whose direction is unknown."""
    k, x = _SPEED_STEP, g.ball_xy[:, 0].astype(np.float64)
    pad = np.full(k, np.nan)
    back, fwd = np.r_[pad, x[:-k]][:g.n], np.r_[x[k:], pad][-g.n:]
    one = np.where(np.isnan(fwd), x - back, fwd - x) / k
    vx = np.nan_to_num(np.where(np.isnan(fwd - back), one, (fwd - back) / (2 * k)), nan=0.0) * FPS
    out, signs = np.full(g.n, np.nan), _attack_signs(g, kickoff)
    for team in (HOME, AWAY):
        out[token == team] = -(signs[team] or 0.0) * vx[token == team]
    return out.astype(np.float32)


def _player_pace(g: Geometry) -> NDArray[np.float32]:
    k, out = _PACE_STEP, np.full(g.n, np.nan, np.float32)
    for lo in range(k, g.n - k, _CHUNK):
        hi = min(lo + _CHUNK, g.n - k)
        step = g.players_xy[lo + k:hi + k].astype(np.float64) - g.players_xy[lo - k:hi - k].astype(np.float64)
        speed = np.hypot(step[..., 0], step[..., 1]) / (2 * k) * FPS
        some = np.isfinite(speed).any(axis=1)
        out[lo:hi][some] = np.nanmedian(speed[some], axis=1)
    return out


def _team_push(g: Geometry, kickoff: int) -> NDArray[np.float32]:
    k, push, signs = _PACE_STEP, np.full((g.n, 2), np.nan), _attack_signs(g, kickoff)
    for team in (HOME, AWAY):
        x, sign = g.players_xy[:, g.slot_team == team, 0], signs[team]
        if sign is None:
            continue
        for lo in range(k, g.n - k, _CHUNK):
            hi = min(lo + _CHUNK, g.n - k)
            dx = (x[lo + k:hi + k].astype(np.float64) - x[lo - k:hi - k].astype(np.float64)) / (2 * k) * FPS
            some = np.isfinite(dx).any(axis=1)
            push[lo:hi, team][some] = sign * np.nanmedian(dx[some], axis=1)
    return (push[:, HOME] - push[:, AWAY]).astype(np.float32)


def _team_press(g: Geometry) -> NDArray[np.float32]:
    k, press = _PACE_STEP, np.full((g.n, 2), np.nan)
    for lo in range(k, g.n - k, _CHUNK):
        hi = min(lo + _CHUNK, g.n - k)
        v = (g.players_xy[lo + k:hi + k].astype(np.float64) - g.players_xy[lo - k:hi - k].astype(np.float64)) \
            / (2 * k) * FPS
        rel = g.ball_xy[lo:hi, None, :].astype(np.float64) - g.players_xy[lo:hi].astype(np.float64)
        d = np.hypot(rel[..., 0], rel[..., 1])
        with np.errstate(invalid="ignore", divide="ignore"):
            toward = (v * rel).sum(-1) / d
            far = np.where(d >= _PRESS_MIN_M, d, np.inf)
        for team in (HOME, AWAY):
            cols = g.slot_team == team
            order = np.argsort(far[:, cols], axis=1, kind="stable")[:, :_PRESS_K]
            pick = np.where(np.isfinite(np.take_along_axis(far[:, cols], order, 1)),
                            np.take_along_axis(toward[:, cols], order, 1), np.nan)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                press[lo:hi, team] = np.nanmean(pick, axis=1)
    return (press[:, HOME] - press[:, AWAY]).astype(np.float32)


def _team_shape(g: Geometry, kickoff: int) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """(Half.shape_lo, Half.shape_parts): the six columns per team and their weighted home-minus-away score."""
    rows, out, signs = np.arange(g.n), [], _attack_signs(g, kickoff)
    for team in (HOME, AWAY):
        xy = g.players_xy[:, g.slot_team == team].astype(np.float64)
        xp = (signs[team] or -1.0) * (xy[..., 0] - g.pitch_m[0] / 2)
        present = ~np.isnan(xp)
        keeper = np.argmin(np.where(present, xp, np.inf), axis=1)
        ox, oy = xp.copy(), xy[..., 1].copy()
        ox[rows, keeper] = oy[rows, keeper] = np.nan
        k = _PACE_STEP
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            cx, cy = np.nanmean(ox, 1), np.nanmean(oy, 1)
            f = np.stack([cx, np.nanmean(np.sort(ox, 1)[:, :4], 1), np.nanmax(ox, 1) - np.nanmin(ox, 1),
                          np.nanmax(oy, 1) - np.nanmin(oy, 1),
                          np.nanmean(np.hypot(ox - cx[:, None], oy - cy[:, None]), 1), np.full(g.n, np.nan)], 1)
            if g.n > 2 * k:
                f[k:-k, 5] = np.nanmedian((ox[2 * k:] - ox[:-2 * k]) / (2 * k) * FPS, 1)
        f[present.sum(1) < _SHAPE_MIN_PLAYERS] = np.nan
        out.append(f)
    return (np.clip((out[0] - out[1]) @ np.asarray(_SHAPE_W), -_SHAPE_CAP, _SHAPE_CAP).astype(np.float32),
            np.concatenate(out, axis=1).astype(np.float32))


def _gap_return(ball: NDArray[np.float64]) -> NDArray[np.float32]:
    """float32 [n]: on each frame of a ball gap that has a seen ball on both sides, the distance in metres
    between the last seen ball before the gap and the first seen ball after it; NaN elsewhere."""
    out = np.full(len(ball), np.nan, np.float32)
    gap = np.concatenate(([False], np.isnan(ball[:, 0]), [False]))
    edges = np.flatnonzero(np.diff(gap.view(np.int8)))
    for start, stop in zip(edges[::2], edges[1::2]):
        if start > 0 and stop < len(ball):
            out[start:stop] = np.hypot(*(ball[stop] - ball[start - 1]))
    return out


def _ball_speed(ball: NDArray[np.float64]) -> NDArray[np.float64]:
    k = _SPEED_STEP
    pad = np.full((k, 2), np.nan)
    back, fwd = np.vstack([pad, ball[:-k]])[:len(ball)], np.vstack([ball[k:], pad])[-len(ball):]
    both = np.hypot(*(fwd - back).T) / (2 * k)
    one = np.fmax(np.hypot(*(ball - back).T), np.hypot(*(fwd - ball).T)) / k
    return np.nan_to_num(np.where(np.isnan(both), one, both), nan=0.0) * FPS


def _ball_velocity(ball: NDArray[np.float64]) -> NDArray[np.float64]:
    """[n, 2] m/s from _ball_speed's frames: t+2 against t-2, else t against whichever of them has a ball, else 0."""
    k = _SPEED_STEP
    pad = np.full((k, 2), np.nan)
    back, fwd = np.vstack([pad, ball[:-k]])[:len(ball)], np.vstack([ball[k:], pad])[-len(ball):]
    one = np.where(np.isnan(back), fwd - ball, ball - back) / k
    return np.nan_to_num(np.where(np.isnan(fwd - back), one, (fwd - back) / (2 * k)), nan=0.0) * FPS


def observe(g: Geometry, id: HalfId) -> Half:
    """Geometry -> Half, with the BallGeometry.

    Slot-order and slot-count invariant by construction, up to exact distance ties, which go to the
    first slot.
    """
    token, geometry = _nearest(g)
    vel = np.where((token == NO_TEAM)[:, None], np.nan,
                   _ball_velocity(g.ball_xy.astype(np.float64))).astype(np.float32)
    geometry = replace(geometry, goal_mps=_goal_velocity(g, id.kickoff, token),
                       vx_mps=np.ascontiguousarray(vel[:, 0]), vy_mps=np.ascontiguousarray(vel[:, 1]))
    shape_lo, shape_parts = _team_shape(g, id.kickoff)
    return Half(id=id, nearest_team=token, geometry=geometry, pace_mps=_player_pace(g),
                push_mps=_team_push(g, id.kickoff), shape_lo=shape_lo,
                return_m=_gap_return(g.ball_xy.astype(np.float64)), press_mps=_team_press(g), shape_parts=shape_parts)


def halves(source: Literal["baseline_raw", "atd"] = "baseline_raw",
           data_dir: str | Path | None = None, *, restart_tags: bool = False,
           broadcast: bool = False, camera: bool = False) -> tuple[Half, Half]:
    """The two decoder inputs for BAR-ATH from the chosen source. restart_tags also fills Half.restart_rows
    from Smart Tagging (decoders with stoppage_fill read them). broadcast takes the missing tactical ball from the
    broadcast ATD where its frame matches (broadcast_fill; decoders with broadcast_ball want it), and camera fills
    Half.camera from the same mapping (broadcast_camera; decoders with dead_camera_players read it), source 'atd'
    only."""
    if (broadcast or camera) and source != "atd":
        raise ValueError(f"broadcast and camera match the broadcast to the tactical ATD's players, so they need source "
                         f"'atd', got {source!r}")
    if source == "baseline_raw":
        out = _halves_from_baseline_raw()
    elif source == "atd":
        geoms, blocks, cams = load_geometry(data_dir), layout().blocks, None
        if broadcast or camera:
            b = load_broadcast(data_dir)
            offsets = broadcast_offsets(geoms, b)
            if camera:
                cams = tuple(broadcast_camera(g, blk, off, b) for g, blk, off in zip(geoms, blocks, offsets))
            if broadcast:
                geoms = tuple(broadcast_fill(g, blk, off, b) for g, blk, off in zip(geoms, blocks, offsets))
        out = tuple(observe(g, i) for g, i in zip(geoms, _half_ids()))
        if cams is not None:
            out = tuple(replace(h, camera=c) for h, c in zip(out, cams))
    else:
        raise ValueError(f"source {source!r}; have 'baseline_raw' and 'atd'")
    if restart_tags:
        out = tuple(replace(h, restart_rows=rows) for h, rows in zip(out, restart_rows(data_dir)))
    return out


def halves_for(model, source: Literal["baseline_raw", "atd"] | None = None,
               data_dir: str | Path | None = None) -> tuple[Half, Half]:
    """The two BAR-ATH halves MODEL decodes, read off its needs_geometry, needs_tags, needs_broadcast and needs_camera
    (decoder.Decoder has all four): from the gated ATD when it reads geometry, the broadcast ball or the camera, or
    SOURCE says so, else from baseline_raw, with every input it reads. make-submission and probes.jitter both build
    their halves here, so a new input cannot reach one and miss the other."""
    atd = model.needs_geometry or model.needs_broadcast or model.needs_camera
    return halves(source or ("atd" if atd else "baseline_raw"), data_dir, restart_tags=model.needs_tags,
                  broadcast=model.needs_broadcast, camera=model.needs_camera)


def restart_rows(data_dir: str | Path | None = None) -> tuple[tuple[int, ...], ...]:
    """Per half, the sorted half rows where a STOPPAGE_KINDS restart tag starts."""
    starts = [t.start for t in tags(data_dir) if t.restart and t.kind in STOPPAGE_KINDS]
    return tuple(tuple(sorted(s - b.origin for s in starts if b.origin <= s < b.origin + b.n)) for b in layout().blocks)


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


def tags(data_dir: str | Path | None = None) -> tuple[Tag, ...]:
    """Smart Tagging in file order. Raises IOError when the gated files are not on disk, and
    ValueError as _parse_tags does."""
    meta, path = games.require(["atd_meta", "smart_tagging"], GAME, data_dir)
    home, away = _team_names(ET.parse(meta).getroot())
    return _parse_tags(ET.parse(path).getroot(), home, away)


def tag_rows(tags: Iterable[Tag], *, n_total: int, lead_s: float = 0.0,
             tail_s: float | None = None) -> NDArray[np.bool_]:
    """bool [n_total], True on rows [start - lead_s, start + tail_s) of every tag, or on
    [start - lead_s, stop) when tail_s is None. Seconds round to rows as tag times do; rows clip to
    [0, n_total)."""
    out = np.zeros(n_total, dtype=bool)
    lead = _row(lead_s)
    for t in tags:
        lo = max(0, t.start - lead)
        hi = t.stop if tail_s is None else t.start + _row(tail_s)
        out[lo:max(lo, hi)] = True
    return out


def _row(seconds: float | str) -> int:
    return int(round(float(seconds) * FPS))


def _parse_tags(root: ET.Element, home: str, away: str) -> tuple[Tag, ...]:
    """The SportsCode document as Tags. home and away are the club names the Team tag uses.

    Raises ValueError on a Team other than "N/A", home or away; a Half other than "1st Half" or
    "2nd Half"; an instance without 0 <= start < stop; or a time base that disagrees, meaning the
    two kick off (start) set pieces, one per half, do not contain KICKOFF_ROW.
    """
    side = {home.casefold(): HOME, away.casefold(): AWAY, "n/a": NO_TEAM}
    out = []
    for instance in root.iter("instance"):
        labels = {(label.findtext("group") or "").strip().casefold(): (label.findtext("text") or "").strip()
                  for label in instance.findall("label")}
        code = (instance.findtext("code") or "").strip().casefold()
        team, half, kind = (labels.get(group, "").casefold() for group in ("team", "half", "type"))
        if team not in side:
            raise ValueError(f"Smart Tagging: Team {team!r} is neither 'n/a' nor an ATD team ({home!r}, {away!r})")
        if half not in _TAG_HALF:
            raise ValueError(f"Smart Tagging: Half {half!r} is not '1st half' or '2nd half'")
        start, stop = (_row(instance.findtext(key)) for key in ("start", "end"))
        if not 0 <= start < stop:
            raise ValueError(f"Smart Tagging: a {code!r} instance ends before it starts or starts before row 0")
        out.append(Tag(code, kind or None, side[team], _TAG_HALF[half], start, stop))
    kickoffs = [t for t in out if t.code == SET_PIECES and t.kind == KICKOFF_START]
    if sorted(t.half for t in kickoffs) != [1, 2] or not all(t.start <= KICKOFF_ROW[t.half] < t.stop
                                                            for t in kickoffs):
        raise ValueError("Smart Tagging time base: the kick off (start) tags, one per half, must contain "
                         f"rows {KICKOFF_ROW[1]} and {KICKOFF_ROW[2]}")
    return tuple(out)


def _team_names(meta: ET.Element) -> tuple[str, str]:
    """(home, away) <Team><Name> in document order, the order _atd_slot_team indexes."""
    names = [(team.findtext("Name") or "").strip() for team in meta.iter("Team")]
    if len(names) != 2 or not all(names):
        raise ValueError(f"ATD metadata: team names {names}, expected two")
    return names[0], names[1]


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


def _read_atd(raw: Path, n_slots: int, source: str = "tactical") -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Normalised ball [n, 2] and players [n, S, 2], NaN where unobserved; row i is frame_id i + 1.

    A line is "frame:x,y,speed;...(S groups):x,y,speed".
    """
    lines = raw.read_text().split()
    n = games.source_frames(source, GAME)
    if len(lines) != n:
        raise ValueError(f"{raw.name}: {len(lines)} lines, expected {n}")
    width = 1 + 3 * n_slots + 3
    try:
        flat = np.fromstring(",".join(lines).translate(str.maketrans(":;", ",,")), sep=",")
    except ValueError as error:
        raise ValueError(f"{raw.name}: {error}") from None
    if flat.size != n * width:
        raise ValueError(f"{raw.name}: {flat.size} values for {n} lines of {width}")
    rows = flat.reshape(n, width)
    if not np.array_equal(rows[:, 0], np.arange(1, n + 1)):
        raise ValueError(f"{raw.name}: frame ids are not 1..{n} in order")
    ball, players = rows[:, -3:-1], rows[:, 1:-3].reshape(n, n_slots, 3)[..., :2]
    # The ball reaches y = 1.49 (measured); this only catches a file already in metres.
    if max(np.nanmax(np.abs(ball)), np.nanmax(np.abs(players))) > _NORM_LIMIT:
        raise ValueError(f"{raw.name}: coordinates exceed {_NORM_LIMIT}, expected normalised")
    return ball, players


@dataclass(frozen=True, slots=True)
class Broadcast:
    """The broadcast ATD on its own timeline, in metres: ball_xy [n, 2] and players_xy [n, S, 2], NaN where unobserved;
    slot_team [S]; valid [n], the broadcast homography's flag. Row b is broadcast frame_id b + 1."""
    ball_xy: NDArray[np.float64]
    players_xy: NDArray[np.float64]
    slot_team: NDArray[np.int8]
    valid: NDArray[np.bool_]


def load_broadcast(data_dir: str | Path | None = None) -> Broadcast:
    """The broadcast ATD and its homography's valid flag. Raises IOError when the files are not on disk."""
    meta, raw, hom = games.require(["atd_meta", "atd_raw", "homography"], GAME, data_dir, source="broadcast")
    return _load_broadcast(str(Path(meta).resolve()), str(Path(raw).resolve()), str(Path(hom).resolve()))


@functools.cache
def _load_broadcast(meta: str, raw: str, hom: str) -> Broadcast:
    slot_team = _atd_slot_team(ET.parse(meta).getroot())
    ball, players = _read_atd(Path(raw), len(slot_team), "broadcast")
    with open(hom) as f:
        names = f.readline().rstrip().split(",")
    frame, valid = np.loadtxt(hom, delimiter=",", skiprows=1, usecols=(names.index("frame"), names.index("valid")),
                              unpack=True)
    if not np.array_equal(frame, np.arange(len(ball))):
        raise ValueError(f"{Path(hom).name}: frames are not 0..{len(ball) - 1} in order")
    scale = np.array(games.GAMES[GAME]["pitch"], np.float64)
    return Broadcast(ball * scale, players * scale, slot_team, valid == 1)


def broadcast_offsets(geoms: tuple[Geometry, ...], b: Broadcast) -> tuple[int, ...]:
    """Per layout() block, tactical row minus broadcast frame: the median over the confident anchors matched inside
    that block, computed from the data on every call. Anchors are _ANCHORS broadcast frames evenly spaced over those
    with a valid homography and _ANCHOR_PLAYERS or more players. Each goes to the tactical row whose players sit
    nearest it (_anchor_cost) at stride _ANCHOR_STRIDE, then at stride 1 around that row. It is confident when the
    cost is under _ANCHOR_BEST_M and every row more than _ANCHOR_AWAY away costs over twice that."""
    lay = layout()
    players_t = np.full((lay.n_total, len(geoms[0].slot_team), 2), np.nan, np.float32)
    for blk, g in zip(lay.blocks, geoms):
        players_t[blk.origin:blk.origin + blk.n] = g.players_xy
    slot_t = geoms[0].slot_team
    cand = np.flatnonzero(b.valid & (np.isfinite(b.players_xy[..., 0]).sum(1) >= _ANCHOR_PLAYERS))
    strided = np.arange(0, lay.n_total, _ANCHOR_STRIDE)
    pt, fits = players_t[strided], []
    for f in cand[np.linspace(0, len(cand) - 1, _ANCHORS).round().astype(int)]:
        p = b.players_xy[f].astype(np.float32)
        cost = _anchor_cost(p, b.slot_team, pt, slot_t)
        k = int(np.argmin(cost))
        runner = float(cost[np.abs(strided - strided[k]) > _ANCHOR_AWAY].min())
        fine = np.arange(max(strided[k] - _ANCHOR_STRIDE + 1, 0), min(strided[k] + _ANCHOR_STRIDE, lay.n_total))
        fc = _anchor_cost(p, b.slot_team, players_t[fine], slot_t)
        if fc.min() < _ANCHOR_BEST_M and runner > 2 * fc.min():
            fits.append((int(fine[np.argmin(fc)]), int(f)))
    out = []
    for blk in lay.blocks:
        off = [r - f for r, f in fits if blk.origin <= r < blk.origin + blk.n]
        if not off:
            raise ValueError(f"no confident broadcast anchor in tactical rows [{blk.origin}, {blk.origin + blk.n})")
        out.append(int(np.round(np.median(off))))
    return tuple(out)


def broadcast_fill(g: Geometry, block: Block, offset: int, b: Broadcast) -> Geometry:
    """G with its missing ball taken from the broadcast at frame block.origin + i - OFFSET wherever that frame has a
    valid homography, a seen ball and _MATCH_PLAYERS or more players whose mean distance to the nearest same-team
    tactical player of row i is under _MATCH_M (_match_cost). Players are left as they are."""
    f = block.origin + np.arange(g.n) - offset
    fc = np.clip(f, 0, len(b.valid) - 1)
    cand = np.flatnonzero((f == fc) & np.isnan(g.ball_xy[:, 0]) & b.valid[fc] & np.isfinite(b.ball_xy[fc, 0])
                          & (np.isfinite(b.players_xy[fc, :, 0]).sum(1) >= _MATCH_PLAYERS))
    ok = np.zeros(len(cand), bool)
    for lo in range(0, len(cand), _MATCH_CHUNK):
        r = cand[lo:lo + _MATCH_CHUNK]
        cost, count = _match_cost(b.players_xy[fc[r]].astype(np.float32), b.slot_team, g.players_xy[r], g.slot_team)
        ok[lo:lo + _MATCH_CHUNK] = (count >= _MATCH_PLAYERS) & (cost < _MATCH_M)
    fill = cand[ok]
    ball = g.ball_xy.copy()
    ball[fill] = b.ball_xy[fc[fill]].astype(np.float32)
    return replace(g, ball_xy=ball)


def broadcast_camera(g: Geometry, block: Block, offset: int, b: Broadcast) -> NDArray[np.int8]:
    """Per row i of G, how many broadcast players at frame block.origin + i - OFFSET have a same-team tactical player
    of row i (_match_cost's count) when that frame has a valid homography and their mean distance is under _MATCH_M,
    so it shows the play at its live positions; 0 when it shows something else, -1 where no broadcast frame maps."""
    f = block.origin + np.arange(g.n) - offset
    fc = np.clip(f, 0, len(b.valid) - 1)
    out = np.where(f == fc, 0, -1).astype(np.int8)
    rows = np.flatnonzero((f == fc) & b.valid[fc] & np.isfinite(b.players_xy[fc, :, 0]).any(1))
    for lo in range(0, len(rows), _MATCH_CHUNK):
        r = rows[lo:lo + _MATCH_CHUNK]
        cost, count = _match_cost(b.players_xy[fc[r]].astype(np.float32), b.slot_team, g.players_xy[r], g.slot_team)
        out[r] = np.where(cost < _MATCH_M, count, 0)
    return out


def _anchor_cost(p: NDArray[np.float32], sb: NDArray[np.int8], pt: NDArray[np.float32],
                 st: NDArray[np.int8]) -> NDArray[np.float64]:
    """Per tactical row of PT [R, St, 2] (teams ST), the mean over the broadcast players P [Sb, 2] (teams SB, NaN
    skipped) of the distance to the nearest same-team tactical player, capped at _ANCHOR_CAP_M."""
    total, count = np.zeros(len(pt)), 0
    for team in (HOME, AWAY):
        q = p[(sb == team) & np.isfinite(p[:, 0])]
        if len(q):
            t = pt[:, st == team]
            d = np.sqrt((t[:, None, :, 0] - q[None, :, None, 0]) ** 2 + (t[:, None, :, 1] - q[None, :, None, 1]) ** 2)
            total += np.minimum(np.where(np.isnan(d), np.inf, d).min(2), _ANCHOR_CAP_M).sum(1)
            count += len(q)
    return total / max(count, 1)


def _match_cost(pb: NDArray[np.float32], sb: NDArray[np.int8], pt: NDArray[np.float32],
                st: NDArray[np.int8]) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """Per row, the mean over broadcast players PB [c, Sb, 2] (teams SB) of the distance to the nearest same-team
    tactical player of PT [c, St, 2] (teams ST), and how many broadcast players had one."""
    total, count = np.zeros(len(pb)), np.zeros(len(pb), int)
    for team in (HOME, AWAY):
        d = np.sqrt(((pb[:, sb == team, None, :] - pt[:, None, st == team, :]) ** 2).sum(-1))
        d = np.where(np.isnan(d), np.inf, d).min(2)
        ok = np.isfinite(d)
        total += np.where(ok, d, 0.0).sum(1)
        count += ok.sum(1)
    return np.where(count > 0, total / np.maximum(count, 1), np.nan), count
