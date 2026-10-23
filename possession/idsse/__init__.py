"""IDSSE: seven German league matches (two Bundesliga, five 2. Bundesliga) of DFL tracking at 25 Hz whose
ball frames carry the league feed's own BallStatus and BallPossession. The second dev source beside metrica, with per-frame labels under a
convention we did not write. Bassek, Rein, Weber, Memmert (2025), "An integrated dataset of
spatiotemporal and event data in elite soccer", Sci Data 12, 195, doi:10.1038/s41597-025-04505-y,
CC BY 4.0."""
from __future__ import annotations

import functools
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

import games

from ..half import AWAY, FPS, HOME, A, D, H, CleanHalf, Geometry, HalfId
from ..metrica import fill_ball
from ..metrica.fetch import copy_hashing
from ..metrica.rule import RuleV2, merge_short

__all__ = ["MATCHES", "REVISION", "load"]

MATCHES = {"J03WMX": "000001", "J03WN1": "000001", "J03WOH": "000002", "J03WOY": "000002",
           "J03WPY": "000002", "J03WQQ": "000002", "J03WR9": "000002"}
SECTIONS = ("firstHalf", "secondHalf")
SOURCE = "https://huggingface.co/datasets/pysport/idsse-data"
MANIFEST = Path(__file__).with_name("manifest.json")
_MANIFEST = json.loads(MANIFEST.read_text())
REVISION, PINS = _MANIFEST["revision"], _MANIFEST["files"]
PARSER_VERSION = 1


@dataclass(frozen=True, slots=True)
class Section:
    """One GameSection as the positions file has it, indexed by the ball's frame counter N - n0.

    status:     int8 [n] BallStatus, 1 live, 0 dead.
    possession: int8 [n] BallPossession, 1 home, 2 away (never anything else, dead frames included).
    """
    n0: int
    ball_xy: NDArray[np.float32]
    players_xy: NDArray[np.float32]
    slot_team: NDArray[np.int8]
    status: NDArray[np.int8]
    possession: NDArray[np.int8]
    pitch_m: tuple[float, float]


def root(data_dir: str | Path | None = None) -> Path:
    return Path(games.DATA_DIR) / "external" / "idsse" if data_dir is None else Path(data_dir)


def load(rule: RuleV2 = RuleV2(), *, data_dir: str | Path | None = None) -> tuple[CleanHalf, ...]:
    """Every half of every match: D where BallStatus is 0, else H or A from BallPossession. Kickoff is
    the first live frame and the block stops after the last one, so the frames before kickoff and
    after the final whistle are dropped or D. "m0" keeps the feed's labels and a merge rule merges
    them; a controlled rule raises, because it needs Metrica's PASS and SET PIECE events."""
    if rule.controlled:
        raise ValueError(f"IDSSE supports merge rules only, got {rule.key}: controlled rules need PASS and "
                         "SET PIECE events in Metrica's schema")
    halves = []
    for match in MATCHES:
        positions_sha256 = PINS[paths(match, data_dir)["positions"].name]["sha256"]
        for number, section in enumerate(parse_match(match, data_dir), start=1):
            live = np.flatnonzero(section.status == 1)
            kickoff, stop = int(live[0]), int(live[-1]) + 1
            labels = np.where(section.status[:stop] == 1, np.where(section.possession[:stop] == 1, H, A), D)
            labels = labels.astype(np.int8)
            if rule.merge_s:
                labels = merge_short(labels, rule.merge_s * FPS)
            native_nan = int(np.isnan(section.ball_xy[:stop]).any(axis=1).sum())
            geometry = Geometry(fill_ball(section.ball_xy[:stop], "hold"), section.players_xy[:stop],
                                section.slot_team, section.pitch_m)
            provenance = {"source": "idsse", "rule": rule.key, "labels": "D if BallStatus 0, else BallPossession 1 H, 2 A",
                          "revision": REVISION, "positions_sha256": positions_sha256,
                          "source_frame0": section.n0, "block_frames": stop, "ball_fill": "hold",
                          "native_nan_frames": native_nan, "licence": "CC BY 4.0"}
            halves.append(CleanHalf(HalfId(f"idsse_{match}", number, kickoff), geometry, labels, provenance))
    return tuple(halves)


def parse_match(match: str, data_dir: str | Path | None = None) -> tuple[Section, ...]:
    """Both sections of one match, verified against the manifest, parsed once per process and cached as
    .npz under games.DATA_DIR / "derived" / "idsse" (the XML is about 400 MB; the cache loads in about
    a second). The cache is rebuilt, after a fresh sha256 check, when a source file's size or mtime, its
    manifest pin or PARSER_VERSION changes."""
    return _parse_cached(match, str(root(data_dir).resolve()))


def paths(match: str, data_dir: str | Path | None = None) -> dict[str, Path]:
    """The matchinformation and positions files, like games.require: one IOError naming every missing
    file and where to get them."""
    folder, competition = root(data_dir), MATCHES[match]
    found = {role: folder / f"DFL_{prefix}_DFL-COM-{competition}_DFL-MAT-{match}.xml"
             for role, prefix in (("info", "02_01_matchinformation"), ("positions", "04_03_positions_raw_observed"))}
    missing = [str(p) for p in found.values() if not p.is_file()]
    if missing:
        raise IOError("IDSSE data not found:\n  {}\n\nDownload the files named in {} from {} at revision {} "
                      "into {}.".format("\n  ".join(missing), MANIFEST, SOURCE, REVISION, folder))
    return found


@functools.cache
def _parse_cached(match: str, data_dir: str) -> tuple[Section, ...]:
    files = paths(match, data_dir)
    stamp = [str(PARSER_VERSION)] + [str(v) for p in files.values()
                                     for v in (p.stat().st_size, p.stat().st_mtime_ns, PINS[p.name]["sha256"])]
    cache = Path(games.DATA_DIR) / "derived" / "idsse" / f"{match}.npz"
    if cache.is_file():
        with np.load(cache) as z:
            if z["stamp"].tolist() == stamp:
                return tuple(_section_from(z, s) for s in SECTIONS)
    _verify(files)
    sections = _parse_positions(files["positions"], *_teams(files["info"]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    arrays = {f"{s}_{field}": getattr(sec, field) for s, sec in zip(SECTIONS, sections)
              for field in ("n0", "ball_xy", "players_xy", "slot_team", "status", "possession", "pitch_m")}
    tmp = cache.with_name(f"{cache.name}.{os.getpid()}.part.npz")
    np.savez(tmp, stamp=np.array(stamp), **arrays)
    tmp.replace(cache)
    return sections


def _section_from(z: np.lib.npyio.NpzFile, s: str) -> Section:
    pitch = z[f"{s}_pitch_m"]
    return Section(int(z[f"{s}_n0"]), z[f"{s}_ball_xy"], z[f"{s}_players_xy"], z[f"{s}_slot_team"],
                   z[f"{s}_status"], z[f"{s}_possession"], (float(pitch[0]), float(pitch[1])))


def _verify(files: dict[str, Path]) -> None:
    for path in files.values():
        with path.open("rb") as f:
            have = copy_hashing(f)[0]
        if have != PINS[path.name]["sha256"]:
            raise ValueError(f"{path} has sha256 {have}, {MANIFEST.name} pins {PINS[path.name]['sha256']}")


def _teams(info: Path) -> tuple[str, str, tuple[float, float]]:
    """(home club id, guest club id, pitch length and width in metres) from matchinformation."""
    tree = ET.parse(info).getroot()
    general, environment = tree.find(".//General"), tree.find(".//Environment")
    if general is None or environment is None:
        raise ValueError(f"{info}: no General or Environment element")
    return (general.attrib["HomeTeamId"], general.attrib["GuestTeamId"],
            (float(environment.attrib["PitchX"]), float(environment.attrib["PitchY"])))


def _parse_positions(path: Path, home: str, guest: str, pitch_m: tuple[float, float]) -> tuple[Section, ...]:
    """Ball and player frames per section. IDSSE puts the origin at the centre spot with y towards the
    top; Geometry wants the top-left corner with y down, so x += length / 2 and y = width / 2 - y.
    Referees are dropped. Slots are home persons, then away, each sorted by PersonId."""
    ball: dict[str, tuple[NDArray[np.int64], NDArray[np.float32], NDArray[np.int8], NDArray[np.int8]]] = {}
    people: dict[str, list[tuple[int, str, NDArray[np.int64], NDArray[np.float32]]]] = {s: [] for s in SECTIONS}
    for _, element in ET.iterparse(path, events=("end",)):
        if element.tag != "FrameSet":
            continue
        a = element.attrib
        section, team = a["GameSection"], a["TeamId"]
        if section not in SECTIONS:
            raise ValueError(f"{path}: unknown GameSection {section!r}")
        frames = list(element)
        n = np.array([f.attrib["N"] for f in frames], np.int64)
        xy = np.array([(f.attrib["X"], f.attrib["Y"]) for f in frames], np.float64)
        xy = np.stack([xy[:, 0] + pitch_m[0] / 2, pitch_m[1] / 2 - xy[:, 1]], axis=1).astype(np.float32)
        if team == "BALL":
            status = np.array([f.attrib["BallStatus"] for f in frames], np.int8)
            possession = np.array([f.attrib["BallPossession"] for f in frames], np.int8)
            ball[section] = (n, xy, status, possession)
        elif team in (home, guest):
            people[section].append((AWAY if team == guest else HOME, a["PersonId"], n, xy))
        elif team != "referee":
            raise ValueError(f"{path}: TeamId {team!r} is neither club, the ball nor the referee")
        element.clear()
    out = []
    for section in SECTIONS:
        n, ball_xy, status, possession = ball[section]
        n0 = int(n[0])
        if not np.array_equal(n, np.arange(n0, n0 + len(n))):
            raise ValueError(f"{path} {section}: ball frame numbers are not contiguous")
        if not (np.isin(status, (0, 1)).all() and np.isin(possession, (1, 2)).all()):
            raise ValueError(f"{path} {section}: BallStatus outside {{0, 1}} or BallPossession outside {{1, 2}}")
        persons = sorted(people[section], key=lambda p: (p[0], p[1]))
        players = np.full((len(n), len(persons), 2), np.nan, np.float32)
        for slot, (_, person, frame, xy) in enumerate(persons):
            index = frame - n0
            if index.min() < 0 or index.max() >= len(n):
                raise ValueError(f"{path} {section}: {person} has frames outside the ball's range")
            players[index, slot] = xy
        slot_team = np.array([side for side, *_ in persons], np.int8)
        out.append(Section(n0, ball_xy, players, slot_team, status, possession, pitch_m))
    return tuple(out)
