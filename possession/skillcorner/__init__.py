"""SkillCorner Open Data: twenty A-League 2024/25 matches of broadcast tracking at 10 fps, whose frames
carry SkillCorner's own possession group and whose phases of play mark when the ball is in play. A dev
source with per-frame labels under a third convention we did not write: SkillCorner's algorithmic
output, not DFL's or PFF's. Off-camera players and the off-camera ball are extrapolated, and both carry
an is_detected flag, which native_seen exposes for the ball. github.com/SkillCorner/opendata, MIT;
SkillCorner asks to be credited."""
from __future__ import annotations

import csv
import functools
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

import numpy as np
from numpy.typing import NDArray

import games

from ..half import AWAY, HOME, A, D, H, X, CleanHalf, Geometry, HalfId
from ..metrica import fill_ball
from ..metrica.fetch import copy_hashing
from ..metrica.rule import RuleV2
from ..pff import at_ticks, ticks

__all__ = ["MATCHES", "REVISION", "label_frames", "load", "native_seen", "parse_match", "phase_mask"]

SOURCE = "https://github.com/SkillCorner/opendata"
MANIFEST = Path(__file__).with_name("manifest.json")
_MANIFEST = json.loads(MANIFEST.read_text())
REVISION, PINS = _MANIFEST["revision"], _MANIFEST["files"]
MATCHES = tuple(sorted({name.split("/")[0] for name in PINS}, key=int))
FILES = {"tracking": "tracking_extrapolated.jsonl", "phases": "phases_of_play.csv", "match": "match.json"}
SOURCE_FPS = 10.0
PARSER_VERSION = 1

NO_BALL, DETECTED, EXTRAPOLATED = 0, 1, 2
_GROUP = {"home team": HOME, "away team": AWAY, None: -1}
_FIELDS = ("frame0", "labels", "ball_det", "ball_xy", "players_xy", "players_det", "slot_team")


@dataclass(frozen=True, slots=True)
class Period:
    """One period of the tracking file at 10 fps, one row per frame from frame0 on.

    labels:      int8 [n] H, A, D or X by label_frames.
    ball_det:    int8 [n] NO_BALL (no position), DETECTED or EXTRAPOLATED (ball_data.is_detected false).
    ball_xy:     float32 [n, 2] metres, top-left origin, NaN where the ball has no position.
    players_xy:  float32 [n, S, 2] one slot per roster player present in this period, NaN where absent.
    players_det: bool [n, S] the player's is_detected; False where absent.
    slot_team:   int8 [S] home 0, away 1.
    """
    number: int
    frame0: int
    labels: NDArray[np.int8]
    ball_det: NDArray[np.int8]
    ball_xy: NDArray[np.float32]
    players_xy: NDArray[np.float32]
    players_det: NDArray[np.bool_]
    slot_team: NDArray[np.int8]
    pitch_m: tuple[float, float]


def root(data_dir: str | Path | None = None) -> Path:
    return Path(games.DATA_DIR) / "external" / "skillcorner" if data_dir is None else Path(data_dir)


def label_frames(group: NDArray[np.int8], in_phase: NDArray[np.bool_]) -> NDArray[np.int8]:
    """int8 labels from possession.group (HOME, AWAY or -1 for null) and phase membership: D outside
    every phase of play, since SkillCorner defines phases only while the ball is in play; inside one,
    H or A from the group, and X where the group is null (a loose ball or a gap in SkillCorner's
    possession output: in play, so not D, and no team, so no label)."""
    team = np.where(group == HOME, H, np.where(group == AWAY, A, X))
    return np.where(in_phase, team, D).astype(np.int8)


def phase_mask(n: int, frame0: int, spans: Sequence[tuple[int, int]]) -> NDArray[np.bool_]:
    """bool [n] for frames frame0 .. frame0 + n - 1: inside some [frame_start, frame_end). The span is
    half-open: duration == (frame_end - frame_start) / 10 on every row, and one phase's frame_end is
    the next one's frame_start when they abut."""
    out = np.zeros(n, bool)
    for start, end in spans:
        out[max(start - frame0, 0):max(end - frame0, 0)] = True
    return out


def load(rule: RuleV2 = RuleV2(), *, data_dir: str | Path | None = None) -> Iterator[CleanHalf]:
    """Periods 1 and 2 of every match at 25 Hz, one match at a time (all 40 halves at once are about
    1.5 GB of geometry). A missing file or a rule other than m0 raises here, before the first half.
    Labels are label_frames at 10 fps; kickoff is the first in-phase frame and the block stops after
    the last one. The 10 to 25 fps resample is pff's: tick k at k / 25 s takes labels and the
    detection flag from the nearest source frame (ticks) and positions linearly between the two
    source frames around it, the nearest frame where either is missing (at_ticks); SkillCorner's
    positions change every frame, so pff's undouble does not apply. The ball is ball_data whether
    detected or extrapolated, held through frames without a position. Players are kept whether
    detected or extrapolated. Only m0: the labels hold X inside play, which merge_short's runs do not
    model, and controlled rules need Metrica's PASS and SET PIECE events."""
    if rule.key != "m0":
        raise ValueError(f"SkillCorner supports rule m0 only, got {rule.key}: its labels have X inside play, "
                         "which a merge rule would merge across, and controlled rules need Metrica's events")
    for match in MATCHES:
        paths(match, data_dir)
    return _halves(rule, data_dir)


def _halves(rule: RuleV2, data_dir: str | Path | None) -> Iterator[CleanHalf]:
    for match in MATCHES:
        tracking_sha256 = PINS[_pin_name(paths(match, data_dir)["tracking"])]["sha256"]
        for period in parse_match(match, data_dir):
            index = ticks(len(period.labels), SOURCE_FPS)
            live = np.flatnonzero(period.labels[index] != D)
            kickoff, stop = int(live[0]), int(live[-1]) + 1
            index = index[:stop]
            labels = period.labels[index]
            geometry = Geometry(fill_ball(at_ticks(period.ball_xy, SOURCE_FPS, stop), "hold"),
                                at_ticks(period.players_xy, SOURCE_FPS, stop), period.slot_team, period.pitch_m)
            present = ~np.isnan(period.players_xy[index, :, 0])
            ball = period.ball_det[index]
            provenance = {"source": "skillcorner", "rule": rule.key,
                          "labels": "D outside every phase of play, else possession.group home H, away A, null X",
                          "revision": REVISION, "tracking_sha256": tracking_sha256,
                          "source_frame0": period.frame0, "source_fps": SOURCE_FPS,
                          "resample": ("positions linear between the two source frames around each 25 Hz tick, the "
                                       "nearest frame where either is missing; labels and flags from the nearest frame"),
                          "block_frames": stop, "ball_fill": "hold",
                          "ball_detected_frames": int((ball == DETECTED).sum()),
                          "ball_extrapolated_frames": int((ball == EXTRAPOLATED).sum()),
                          "ball_no_position_frames": int((ball == NO_BALL).sum()),
                          "player_extrapolated_share": float(1 - period.players_det[index][present].mean()),
                          "x_frames": int((labels == X).sum()), "licence": "MIT, credit SkillCorner"}
            yield CleanHalf(HalfId(f"skillcorner_{match}", period.number, kickoff), geometry, labels, provenance)


def native_seen(half: CleanHalf, data_dir: str | Path | None = None) -> NDArray[np.bool_]:
    """bool [half.geometry.n]: SkillCorner detected the ball (ball_data.is_detected true, not
    extrapolated or absent) at that 25 Hz frame. For a half that `load` returned; ValueError when the
    cached period does not start at the half's provenance source_frame0."""
    match, prefix = half.id.match.removeprefix("skillcorner_"), f"p{half.id.half}_"
    with np.load(_cache(match, data_dir)) as z:
        frame0, detected = int(z[f"{prefix}frame0"]), z[f"{prefix}ball_det"]
    if frame0 != half.provenance["source_frame0"]:
        raise ValueError(f"{half.id}: period starts at frame {frame0}, "
                         f"provenance says {half.provenance['source_frame0']}")
    return detected[ticks(len(detected), SOURCE_FPS)[:half.geometry.n]] == DETECTED


def parse_match(match: str, data_dir: str | Path | None = None) -> tuple[Period, ...]:
    """Periods 1 and 2 of one match, verified against the manifest and cached as .npz under
    games.DATA_DIR / "derived" / "skillcorner". The cache is rebuilt, after a fresh sha256 check, when a
    source file's size or mtime, its manifest pin or PARSER_VERSION changes."""
    with np.load(_cache(match, data_dir)) as z:
        pitch = z["pitch_m"]
        return tuple(Period(number, int(z[f"p{number}_frame0"]), z[f"p{number}_labels"], z[f"p{number}_ball_det"],
                            z[f"p{number}_ball_xy"], z[f"p{number}_players_xy"], z[f"p{number}_players_det"],
                            z[f"p{number}_slot_team"], (float(pitch[0]), float(pitch[1])))
                     for number in z["periods"].tolist())


def paths(match: str, data_dir: str | Path | None = None) -> dict[str, Path]:
    """The tracking, phases and match files, like games.require: one IOError naming every missing file
    and where to get them."""
    folder = root(data_dir) / match
    found = {role: folder / f"{match}_{suffix}" for role, suffix in FILES.items()}
    missing = [str(p) for p in found.values() if not p.is_file()]
    if missing:
        raise IOError("SkillCorner data not found:\n  {}\n\nDownload the files named in {} from {} at commit {} "
                      "into {}/<match>/.".format("\n  ".join(missing), MANIFEST, SOURCE, REVISION, root(data_dir)))
    return found


@functools.cache
def _cache_path(match: str, data_dir: str) -> Path:
    files = paths(match, data_dir)
    stamp = [str(PARSER_VERSION)] + [str(v) for p in files.values() for v in
                                     (p.stat().st_size, p.stat().st_mtime_ns, PINS[_pin_name(p)]["sha256"])]
    cache = Path(games.DATA_DIR) / "derived" / "skillcorner" / f"{match}.npz"
    if cache.is_file():
        with np.load(cache) as z:
            if z["stamp"].tolist() == stamp:
                return cache
    _verify(files)
    periods = _parse(files)
    cache.parent.mkdir(parents=True, exist_ok=True)
    arrays = {f"p{p.number}_{name}": getattr(p, name) for p in periods for name in _FIELDS}
    tmp = cache.with_name(f"{cache.name}.{os.getpid()}.part.npz")
    np.savez(tmp, stamp=np.array(stamp), periods=np.array([p.number for p in periods]),
             pitch_m=np.array(periods[0].pitch_m), **arrays)
    tmp.replace(cache)
    return cache


def _cache(match: str, data_dir: str | Path | None) -> Path:
    """The match's .npz, rebuilt first when its stamp is stale (checked once per process)."""
    return _cache_path(match, str(root(data_dir).resolve()))


def _pin_name(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _verify(files: dict[str, Path]) -> None:
    for path in files.values():
        with path.open("rb") as f:
            have = copy_hashing(f)[0]
        if have != PINS[_pin_name(path)]["sha256"]:
            raise ValueError(f"{path} has sha256 {have}, {MANIFEST.name} pins {PINS[_pin_name(path)]['sha256']}")


def _parse(files: dict[str, Path]) -> tuple[Period, ...]:
    """Periods 1 and 2 from the tracking lines whose period field says so. SkillCorner puts the origin
    at the centre spot with y towards the top; Geometry wants the top-left corner with y down, so
    x += length / 2 and y = width / 2 - y. Slots are home players, then away, each sorted by player
    id, keeping those present in the period. Raises on a gap in the frame numbers, a player id the
    match file does not list, or a null player is_detected."""
    info = json.loads(files["match"].read_text())
    pitch_m = (float(info["pitch_length"]), float(info["pitch_width"]))
    home, away = info["home_team"]["id"], info["away_team"]["id"]
    side = {}
    for player in info["players"]:
        if player["team_id"] not in (home, away):
            raise ValueError(f"{files['match']}: player {player['id']} has team {player['team_id']}, neither club")
        side[player["id"]] = HOME if player["team_id"] == home else AWAY
    slot_of = {pid: k for k, pid in enumerate(sorted(side, key=lambda p: (side[p], p)))}
    with files["phases"].open(newline="") as f:
        spans = {}
        for row in csv.DictReader(f):
            spans.setdefault(int(row["period"]), []).append((int(row["frame_start"]), int(row["frame_end"])))

    rows: dict[int, dict[str, list]] = {}
    expect = 0
    with files["tracking"].open() as f:
        for line in f:
            r = json.loads(line)
            if r["frame"] != expect:
                raise ValueError(f"{files['tracking']}: frame {r['frame']} where {expect} was due")
            expect += 1
            if r["period"] not in (1, 2):
                continue
            p = rows.setdefault(r["period"], {"frame0": [r["frame"]], "group": [], "ball": [], "det": [], "players": []})
            if p["frame0"][0] + len(p["group"]) != r["frame"]:
                raise ValueError(f"{files['tracking']}: period {r['period']} is not contiguous at frame {r['frame']}")
            b = r["ball_data"]
            p["group"].append(_GROUP[r["possession"]["group"]])
            p["ball"].append((np.nan, np.nan) if b["x"] is None else (b["x"], b["y"]))
            p["det"].append(NO_BALL if b["x"] is None else DETECTED if b["is_detected"] else EXTRAPOLATED)
            for pl in r["player_data"]:
                if pl["player_id"] not in slot_of or pl["is_detected"] is None:
                    raise ValueError(f"{files['tracking']} frame {r['frame']}: player {pl['player_id']} is not in "
                                     f"the match file or has a null is_detected")
            p["players"].append([(slot_of[pl["player_id"]], pl["x"], pl["y"], pl["is_detected"]) for pl in r["player_data"]])
    out = []
    for number in (1, 2):
        p = rows[number]
        n, frame0 = len(p["group"]), p["frame0"][0]
        players = np.full((n, len(slot_of), 2), np.nan, np.float64)
        detected = np.zeros((n, len(slot_of)), bool)
        for i, entries in enumerate(p["players"]):
            for slot, x, y, det in entries:
                players[i, slot] = (x, y)
                detected[i, slot] = det
        keep = ~np.isnan(players[..., 0]).all(axis=0)
        labels = label_frames(np.array(p["group"], np.int8), phase_mask(n, frame0, spans.get(number, ())))
        out.append(Period(number, frame0, labels, np.array(p["det"], np.int8),
                          _flip(np.array(p["ball"], np.float64), pitch_m), _flip(players[:, keep], pitch_m),
                          detected[:, keep], np.array([side[pid] for pid in slot_of], np.int8)[keep], pitch_m))
    return tuple(out)


def _flip(xy: NDArray[np.float64], pitch_m: tuple[float, float]) -> NDArray[np.float32]:
    return np.stack([xy[..., 0] + pitch_m[0] / 2, pitch_m[1] / 2 - xy[..., 1]], axis=-1).astype(np.float32)
