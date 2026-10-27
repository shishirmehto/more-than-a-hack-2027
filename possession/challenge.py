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


def _team_shape(g: Geometry, kickoff: int) -> NDArray[np.float32]:
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
    return np.clip((out[0] - out[1]) @ np.asarray(_SHAPE_W), -_SHAPE_CAP, _SHAPE_CAP).astype(np.float32)


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
    return Half(id=id, nearest_team=token, geometry=geometry, pace_mps=_player_pace(g),
                push_mps=_team_push(g, id.kickoff), shape_lo=_team_shape(g, id.kickoff),
                return_m=_gap_return(g.ball_xy.astype(np.float64)), press_mps=_team_press(g))


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


def _read_atd(raw: Path, n_slots: int) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Normalised ball [n, 2] and players [n, S, 2], NaN where unobserved; row i is frame_id i + 1.

    A line is "frame:x,y,speed;...(S groups):x,y,speed".
    """
    lines = raw.read_text().split()
    n = games.source_frames("tactical", GAME)
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
