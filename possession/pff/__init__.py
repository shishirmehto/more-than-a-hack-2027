"""PFF FC: the 64 matches of the FIFA World Cup 2022 as broadcast tracking at 29.97 fps, whose game
events give per-frame labels under a convention we did not write. The third dev source, and the only
one with the tracker's own ball-visibility flag, which native_seen exposes. No licence file ships with
the data and its specs call it PFFA Acquisition LLC proprietary information, so treat it as all
rights reserved: never commit a PFF file, an excerpt, or anything frame-level derived from one."""
from __future__ import annotations

import bz2
import hashlib
import itertools
import json
import operator
import os
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np
from numpy.typing import NDArray

import games

from ..half import AWAY, FPS, HOME, A, D, H, CleanHalf, Geometry, HalfId
from ..metrica import fill_ball
from ..metrica.fetch import copy_hashing
from ..metrica.rule import RuleV2, merge_short

__all__ = ["GAMES", "MANIFEST_SHA256", "load", "native_seen", "parse_game"]

MANIFEST = Path(__file__).with_name("manifest.json")
MANIFEST_SHA256 = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
PINS = json.loads(MANIFEST.read_text())["files"]
GAMES = tuple(sorted({name.split("/")[1].split(".")[0] for name in PINS}, key=int))
PARSER_VERSION = 1

NO_BALL, VISIBLE, ESTIMATED = 0, 1, 2
_VISIBILITY = {"VISIBLE": VISIBLE, "ESTIMATED": ESTIMATED}
# kloppy 3.18's PFF reader (infra/serializers/tracking/pff.py); any other game event leaves the state.
_DEAD_EVENTS = frozenset({"OUT", "END"})
_LIVE_EVENTS = frozenset({"FIRSTKICKOFF", "SECONDKICKOFF", "THIRDKICKOFF", "FOURTHKICKOFF", "OTB"})
_PERIODS = (1, 2, 3, 4)
_FIELDS = ("frame0", "labels", "ball_vis", "ball_xy", "players_xy", "slot_team")


@dataclass(frozen=True, slots=True)
class Period:
    """One period of the tracking file at the source rate, one row per frameNum from frame0 on.

    labels:     int8 [n] H, A or D by the game-event rule (load's docstring).
    ball_vis:   int8 [n] NO_BALL, VISIBLE or ESTIMATED, from balls[0].visibility.
    ball_xy:    float32 [n, 2] metres, top-left origin, NaN where balls is empty.
    players_xy: float32 [n, S, 2] one slot per roster player seen in this period, NaN where absent.
    slot_team:  int8 [S] home 0, away 1.
    """
    number: int
    frame0: int
    fps: float
    labels: NDArray[np.int8]
    ball_vis: NDArray[np.int8]
    ball_xy: NDArray[np.float32]
    players_xy: NDArray[np.float32]
    slot_team: NDArray[np.int8]
    pitch_m: tuple[float, float]


def root(data_dir: str | Path | None = None) -> Path:
    return Path(games.DATA_DIR) / "external" / "pff" if data_dir is None else Path(data_dir)


def load(rule: RuleV2 = RuleV2(), *, data_dir: str | Path | None = None) -> Iterator[CleanHalf]:
    """Periods 1 and 2 of every game at 25 Hz, one half at a time: all 128 at once are about 2 GB of
    geometry, so the iterator holds one game's arrays. A missing file or a controlled rule raises here,
    before the first half. The labels are kloppy 3.18's reading of PFF: the state starts dead, an OUT
    or END game event makes it dead, a kickoff or OTB game event makes it live, and a live frame
    belongs to the last game event's home_ball (True is home). They are computed at the source rate
    and resampled with the geometry by ticks. Kickoff is the first live frame (index 0 in every PFF
    period) and the block stops after the last one. The ball is balls[0] whatever its visibility,
    held through frames without one. The smoothed lists are never read: ballsSmoothed sits on the
    labelled carrier. "m0" keeps the labels and a merge rule merges them at 25 Hz; a controlled rule
    raises, because it needs Metrica's PASS and SET PIECE events."""
    if rule.controlled:
        raise ValueError(f"PFF supports merge rules only, got {rule.key}: controlled rules need PASS and "
                         "SET PIECE events in Metrica's schema")
    for game in GAMES:
        paths(game, data_dir)
    return _halves(rule, data_dir)


def _halves(rule: RuleV2, data_dir: str | Path | None) -> Iterator[CleanHalf]:
    for game in GAMES:
        tracking_sha256 = PINS[f"tracking/{game}.jsonl.bz2"]["sha256"]
        for period in parse_game(game, data_dir):
            if period.number not in (1, 2):
                continue
            index = ticks(len(period.labels), period.fps)
            live = np.flatnonzero(period.labels[index] != D)
            kickoff, stop = int(live[0]), int(live[-1]) + 1
            index = index[:stop]
            labels = period.labels[index]
            if rule.merge_s:
                labels = merge_short(labels, rule.merge_s * FPS)
            geometry = Geometry(fill_ball(period.ball_xy[index], "hold"), period.players_xy[index],
                                period.slot_team, period.pitch_m)
            provenance = {"source": "pff", "rule": rule.key,
                          "labels": "kloppy 3.18 PFF rule: OUT or END dead, kickoff or OTB live, owner the last home_ball",
                          "manifest_sha256": MANIFEST_SHA256, "tracking_sha256": tracking_sha256,
                          "source_frame0": period.frame0, "source_fps": period.fps,
                          "resample": "source frame nearest each 25 Hz tick", "block_frames": stop,
                          "ball_fill": "hold", "native_no_ball_frames": int((period.ball_vis[index] == NO_BALL).sum()),
                          "licence": "none granted, PFF proprietary: never commit"}
            yield CleanHalf(HalfId(f"pff_{game}", period.number, kickoff), geometry, labels, provenance)


def native_seen(half: CleanHalf, data_dir: str | Path | None = None) -> NDArray[np.bool_]:
    """bool [half.geometry.n]: PFF's tracker saw the ball (balls[0].visibility VISIBLE, not ESTIMATED
    or absent) at that 25 Hz frame. For a half that `load` returned; ValueError when the cached
    period does not start at the half's provenance source_frame0. Reads only the visibility array."""
    game, prefix = half.id.match.removeprefix("pff_"), f"p{half.id.half}_"
    with np.load(_cache(game, data_dir)) as z:
        frame0, fps, visibility = int(z[f"{prefix}frame0"]), float(z["fps"]), z[f"{prefix}ball_vis"]
    if frame0 != half.provenance["source_frame0"]:
        raise ValueError(f"{half.id}: period starts at frame {frame0}, "
                         f"provenance says {half.provenance['source_frame0']}")
    return visibility[ticks(len(visibility), fps)[:half.geometry.n]] == VISIBLE


def ticks(n: int, fps: float) -> NDArray[np.int64]:
    """Source index of every 25 Hz frame of a period of n source frames at fps. Tick k sits at k / 25 s
    and takes the source frame nearest in time, floor(k * fps / 25 + 0.5), since frame i sits at
    i / fps. The last tick is the last one at or before the last source frame."""
    k = np.arange(int(np.floor((n - 1) * FPS / fps)) + 1)
    return np.minimum(np.floor(k * fps / FPS + 0.5).astype(np.int64), n - 1)


def parse_game(game: str, data_dir: str | Path | None = None) -> tuple[Period, ...]:
    """Every period of one game in file order (3 and 4 are extra time), verified against the manifest
    and cached as .npz under games.DATA_DIR / "derived" / "pff". The first parse of a game takes
    about 16 s, 12 of them in bz2; the cache loads in a fraction of a second. Nothing is kept in
    memory between calls, because the 64 caches hold 2.4 GB. The cache is rebuilt, after a fresh
    sha256 check, when a source file's size or mtime, its manifest pin or PARSER_VERSION changes."""
    with np.load(_cache(game, data_dir)) as z:
        fps, pitch = float(z["fps"]), z["pitch_m"]
        return tuple(Period(number, int(z[f"p{number}_frame0"]), fps, z[f"p{number}_labels"], z[f"p{number}_ball_vis"],
                            z[f"p{number}_ball_xy"], z[f"p{number}_players_xy"], z[f"p{number}_slot_team"],
                            (float(pitch[0]), float(pitch[1])))
                     for number in z["periods"].tolist())


def paths(game: str, data_dir: str | Path | None = None) -> dict[str, Path]:
    """The tracking, metadata and roster files, like games.require: one IOError naming every missing
    file and where they go."""
    folder = root(data_dir)
    found = {"tracking": folder / "tracking" / f"{game}.jsonl.bz2", "metadata": folder / "metadata" / f"{game}.json",
             "rosters": folder / "rosters" / f"{game}.json"}
    missing = [str(p) for p in found.values() if not p.is_file()]
    if missing:
        raise IOError("PFF data not found:\n  {}\n\nPut the PFF FC World Cup 2022 files named in {} under {} "
                      "(tracking/, metadata/ and rosters/).".format("\n  ".join(missing), MANIFEST, folder))
    return found


def _cache(game: str, data_dir: str | Path | None) -> Path:
    """The game's .npz, rebuilt first when its stamp is stale."""
    files = paths(game, data_dir)
    stamp = [str(PARSER_VERSION)] + [str(v) for p in files.values() for v in
                                     (p.stat().st_size, p.stat().st_mtime_ns, PINS[_pin_name(p)]["sha256"])]
    cache = Path(games.DATA_DIR) / "derived" / "pff" / f"{game}.npz"
    if cache.is_file():
        with np.load(cache) as z:
            if z["stamp"].tolist() == stamp:
                return cache
    _verify(files)
    periods = _parse(files)
    cache.parent.mkdir(parents=True, exist_ok=True)
    arrays = {f"p{p.number}_{name}": getattr(p, name) for p in periods for name in _FIELDS}
    tmp = cache.with_name(f"{cache.name}.{os.getpid()}.part.npz")
    np.savez(tmp, stamp=np.array(stamp), periods=np.array([p.number for p in periods]), fps=periods[0].fps,
             pitch_m=np.array(periods[0].pitch_m), **arrays)
    tmp.replace(cache)
    return cache


def _pin_name(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _verify(files: dict[str, Path]) -> None:
    for path in files.values():
        with path.open("rb") as f:
            have = copy_hashing(f)[0]
        if have != PINS[_pin_name(path)]["sha256"]:
            raise ValueError(f"{path} has sha256 {have}, {MANIFEST.name} pins {PINS[_pin_name(path)]['sha256']}")


@dataclass(slots=True)
class _Rows:
    """One period's columns while the file streams. Player entries are flat (roster index, x, y) with a
    count per frame, so the per-player work stays in C (a Python loop over them doubles the parse)."""
    frame0: int
    labels: array = field(default_factory=lambda: array("b"))
    ball_vis: array = field(default_factory=lambda: array("b"))
    ball_xy: array = field(default_factory=lambda: array("d"))
    index: array = field(default_factory=lambda: array("i"))
    xy: array = field(default_factory=lambda: array("d"))
    counts: array = field(default_factory=lambda: array("i"))


_JERSEY = operator.itemgetter("jerseyNum")
_XY = operator.itemgetter("x", "y")
_BALL = operator.itemgetter("visibility", "x", "y")


def _parse(files: dict[str, Path]) -> tuple[Period, ...]:
    """A frameNum repeats once per possession event; its copies collapse to one frame whose label is
    the state after all of them and whose positions are the first copy carrying a game_event. Slots
    are home roster players, then away, each by player id, keeping those seen in the period; a
    tracked jerseyNum joins the roster's shirtNumber within its team."""
    meta = json.loads(files["metadata"].read_text())[0]
    pitch = meta["stadium"]["pitches"][0]
    pitch_m, fps = (float(pitch["length"]), float(pitch["width"])), float(meta["fps"])
    sides = {meta["homeTeam"]["id"]: HOME, meta["awayTeam"]["id"]: AWAY}
    roster = sorted((sides[e["team"]["id"]], int(e["player"]["id"]), e["shirtNumber"])
                    for e in json.loads(files["rosters"].read_text()))
    # The spec types jerseyNum as int; the files carry the roster's string, so both spellings join.
    lookup: tuple[dict[str | int, int], dict[str | int, int]] = ({}, {})
    for i, (side, _, shirt) in enumerate(roster):
        if shirt in lookup[side]:
            raise ValueError(f"{files['rosters']}: shirt {shirt} repeats within a team")
        lookup[side].update({shirt: i, int(shirt): i})
    roster_side = np.array([side for side, *_ in roster], np.int8)

    periods: dict[int, _Rows] = {}
    live, owner = False, D
    with bz2.open(files["tracking"], "rt", encoding="utf-8") as f:
        for frame_num, group in itertools.groupby(map(json.loads, f), key=lambda frame: frame["frameNum"]):
            copies = list(group)
            for frame in copies:
                event = frame["game_event"]
                if event:
                    if event["game_event_type"] in _DEAD_EVENTS:
                        live = False
                    elif event["game_event_type"] in _LIVE_EVENTS:
                        live = True
                    if event["home_ball"] is not None:
                        owner = H if event["home_ball"] else A
            kept = next((frame for frame in copies if frame["game_event"]), copies[0])
            number = kept["period"]
            if number not in _PERIODS or (periods and number < max(periods)):
                raise ValueError(f"{files['tracking']}: period {number!r} at frame {frame_num} is out of order")
            rows = periods.setdefault(number, _Rows(frame_num))
            if frame_num != rows.frame0 + len(rows.labels):
                raise ValueError(f"{files['tracking']} period {number}: frame {frame_num} breaks the frameNum run")
            rows.labels.append(owner if live else D)
            balls = kept["balls"]
            if balls:
                visibility, x, y = _BALL(balls[0])
                rows.ball_vis.append(_VISIBILITY[visibility])
                rows.ball_xy.extend((x, y))
            else:
                rows.ball_vis.append(NO_BALL)
                rows.ball_xy.extend((np.nan, np.nan))
            for side, key in ((HOME, "homePlayers"), (AWAY, "awayPlayers")):
                try:
                    rows.index.extend(map(lookup[side].__getitem__, map(_JERSEY, kept[key])))
                except KeyError as jersey:
                    raise ValueError(f"{files['tracking']}: {key} jersey {jersey} at frame {frame_num} "
                                     "is not on the roster") from None
                rows.xy.extend(itertools.chain.from_iterable(map(_XY, kept[key])))
            rows.counts.append(len(kept["homePlayers"]) + len(kept["awayPlayers"]))

    out = []
    for number, rows in periods.items():
        n, index = len(rows.labels), np.frombuffer(rows.index, np.int32)
        seen = np.unique(index)
        players = np.full((n, len(seen), 2), np.nan, np.float32)
        players[np.repeat(np.arange(n), np.frombuffer(rows.counts, np.int32)), np.searchsorted(seen, index)] = \
            _flip(np.frombuffer(rows.xy, np.float64).reshape(-1, 2), pitch_m)
        ball_xy = _flip(np.frombuffer(rows.ball_xy, np.float64).reshape(n, 2), pitch_m)
        out.append(Period(number, rows.frame0, fps, np.frombuffer(rows.labels, np.int8).copy(),
                          np.frombuffer(rows.ball_vis, np.int8).copy(), ball_xy, players, roster_side[seen], pitch_m))
    return tuple(out)


def _flip(xy: NDArray[np.float64], pitch_m: tuple[float, float]) -> NDArray[np.float32]:
    """PFF puts the origin at the centre spot with y towards the top; Geometry wants the top-left corner
    with y down, so x += length / 2 and y = width / 2 - y."""
    return np.stack([xy[:, 0] + pitch_m[0] / 2, pitch_m[1] / 2 - xy[:, 1]], axis=1).astype(np.float32)
