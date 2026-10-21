from __future__ import annotations

import functools
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from .fetch import paths, root

PITCH_M = (105.0, 68.0)
_EPTS_SLOTS = 22
_EPTS_LINE_VALUES = 1 + 2 * _EPTS_SLOTS + 2

EVENT_COLUMNS: tuple[str, ...] = (
    "team",
    "type",
    "subtypes",
    "period",
    "start",
    "end",
)

# Normalised coordinates may leave [0, 1] (the ball goes over the touchline, players stand behind
# the goal line).
_NORM_WINDOW = (-0.2, 1.2)

_TRACKING_CSV_LEAD = ["Period", "Frame", "Time [s]"]


@dataclass(frozen=True, slots=True)
class RawPeriod:
    """One period of tracking, native (with the out-of-play NaN Metrica uses as its dead-ball marker).

    period:     1 | 2
    frame0:     source Frame of local index 0 (a period's first tracking frame)
    ball_xy:    float32 [n, 2] metres, NaN where untracked
    players_xy: float32 [n, S, 2] metres, NaN for subs not on.
    slot_team:  int8 [S].
    All three arrays are read-only: parse_game is memoised and hands every caller the same objects.
    """
    period: int
    frame0: int
    ball_xy: NDArray[np.float32]
    players_xy: NDArray[np.float32]
    slot_team: NDArray[np.int8]


@dataclass(frozen=True, slots=True)
class RawGame:
    game: int
    periods: tuple[RawPeriod, RawPeriod]
    events: pd.DataFrame


def parse_game(game: int, data_dir: str | Path | None = None) -> RawGame:
    """Parse one game from the local files (never fetches). Memoised on (game, resolved data_dir),
    so `parse_game(1)` and `parse_game(1, None)` share one parse.

    Postconditions checked here: frame ids contiguous within a period; x,y in a sane window
    (-0.2..1.2 before scaling; the ball may be off-pitch); both periods present; every event's start
    frame falls inside its period's frame range.
    """
    return _parse_cached(game, str(root(data_dir).resolve()))


@functools.cache
def _parse_cached(game: int, data_dir: str) -> RawGame:
    files = paths(game, data_dir)
    if game in (1, 2):
        return _parse_csv_game(files["home"], files["away"], files["events"], game)
    if game == 3:
        return _parse_epts_game(files["tracking"], files["meta"], files["events"], game)
    raise ValueError(f"no Metrica sample game {game}; have 1, 2, 3")


def _parse_csv_game(home_csv: Path, away_csv: Path, events_csv: Path, game: int) -> RawGame:
    home, away = _read_team_csv(home_csv), _read_team_csv(away_csv)
    if not np.array_equal(home[:, :2], away[:, :2]):
        raise ValueError(f"game {game}: Home and Away tracking files disagree on Period/Frame")
    if not np.array_equal(home[:, -2:], away[:, -2:], equal_nan=True):
        raise ValueError(f"game {game}: Home and Away tracking files disagree on the ball")
    home_xy, away_xy = (t[:, 3:-2].reshape(len(t), -1, 2) for t in (home, away))
    players = np.concatenate([home_xy, away_xy], axis=1)
    slot_team = np.repeat(np.array([0, 1], np.int8), [home_xy.shape[1], away_xy.shape[1]])
    periods = _split_periods(game, home[:, 0].astype(np.int64), home[:, 1].astype(np.int64),
                             home[:, -2:], players, slot_team)
    return RawGame(game, periods, _check_events(game, _events_from_csv(events_csv), periods))


def _parse_epts_game(tracking_txt: Path, meta_xml: Path, events_json: Path, game: int) -> RawGame:
    meta = ET.parse(meta_xml).getroot()
    team_ids = [team.get("id") for team in meta.find(".//Teams").iter("Team")]
    slot_team = _epts_slot_team(meta, team_ids)

    text = tracking_txt.read_text()
    flat = np.fromstring(",".join(text.split()).translate(str.maketrans(":;", ",,")), sep=",")
    if flat.size % _EPTS_LINE_VALUES:
        raise ValueError(f"{tracking_txt.name}: {flat.size} values is not a whole number of "
                         f"{_EPTS_LINE_VALUES}-value lines")
    lines = flat.reshape(-1, _EPTS_LINE_VALUES)
    frame = lines[:, 0].astype(np.int64)
    players = lines[:, 1:-2].reshape(len(lines), -1, 2)

    bounds = _epts_period_frames(meta)
    period = np.zeros(len(frame), np.int64)
    for p, (start, end) in enumerate(bounds, start=1):
        period[(frame >= start) & (frame <= end)] = p
    if (period == 0).any():
        raise ValueError(f"{tracking_txt.name}: frames outside both periods {bounds}")
    periods = _split_periods(game, period, frame, lines[:, -2:], players, slot_team)
    return RawGame(game, periods, _check_events(game, _events_from_json(events_json, team_ids), periods))


def _epts_slot_team(meta: ET.Element, team_ids: list[str]) -> NDArray[np.int8]:
    player_team = {p.get("id"): team_ids.index(p.get("teamId")) for p in meta.iter("Player")}
    channel_player = {c.get("id"): c.get("playerId") for c in meta.iter("PlayerChannel")}
    windows = []
    for spec in meta.iter("DataFormatSpecification"):
        slots = next(r for r in spec.findall("SplitRegister") if r.get("separator") == ";")
        teams = []
        for slot in slots.findall("SplitRegister"):
            owners = {channel_player[ref.get("playerChannelId")] for ref in slot.iter("PlayerChannelRef")}
            if len(owners) != 1:
                raise ValueError(f"a slot of {spec.attrib} mixes players {owners}")
            teams.append(player_team[owners.pop()])
        windows.append(teams)
    if not windows or any(w != windows[0] for w in windows) or len(windows[0]) != _EPTS_SLOTS:
        raise ValueError("slot to team mapping is not one constant 22-slot list across the windows")
    return np.array(windows[0], np.int8)


def _epts_period_frames(meta: ET.Element) -> tuple[tuple[int, int], tuple[int, int]]:
    params = {p.findtext("Name"): p.findtext("Value") for p in meta.iter("ProviderParameter")}
    first = int(params["first_half_start"]), int(params["first_half_end"])
    second = int(params["second_half_start"]), int(params["second_half_end"])
    return first, second


def _read_team_csv(path: Path) -> NDArray[np.float32]:
    names = pd.read_csv(path, header=None, skiprows=2, nrows=1, dtype=str).iloc[0].tolist()
    if names[:3] != _TRACKING_CSV_LEAD or names[-2] != "Ball":
        raise ValueError(f"{path.name}: unexpected header row {names[:4]} ... {names[-3:]}")
    return pd.read_csv(path, header=None, skiprows=3, dtype=np.float32).to_numpy()


def _split_periods(game: int, period: NDArray[np.int64], frame: NDArray[np.int64],
                   ball: NDArray[np.floating], players: NDArray[np.floating],
                   slot_team: NDArray[np.int8]) -> tuple[RawPeriod, RawPeriod]:
    for name, values in (("ball", ball), ("players", players)):
        low, high = np.nanmin(values), np.nanmax(values)
        if low < _NORM_WINDOW[0] or high > _NORM_WINDOW[1]:
            raise ValueError(f"game {game}: {name} coordinates span {low}..{high}, expected {_NORM_WINDOW}")
    scale = np.array(PITCH_M, np.float32)
    out = []
    for p in (1, 2):
        rows = np.flatnonzero(period == p)
        if rows.size == 0 or rows[-1] - rows[0] + 1 != rows.size:
            raise ValueError(f"game {game}: period {p} is absent or not one contiguous block of rows")
        block = slice(rows[0], rows[-1] + 1)
        if not (np.diff(frame[block]) == 1).all():
            raise ValueError(f"game {game}: frame ids of period {p} are not consecutive")
        out.append(RawPeriod(p, int(frame[block][0]), _frozen(ball[block] * scale),
                             _frozen(players[block] * scale), _frozen(slot_team.copy())))
    return out[0], out[1]


def _frozen(array: NDArray) -> NDArray:
    array = np.ascontiguousarray(array, dtype=np.float32 if array.dtype.kind == "f" else array.dtype)
    array.setflags(write=False)
    return array


def _check_events(game: int, events: pd.DataFrame, periods: tuple[RawPeriod, RawPeriod]) -> pd.DataFrame:
    for period in periods:
        starts = events.loc[events["period"] == period.period, "start"]
        last = period.frame0 + len(period.ball_xy) - 1
        if starts.empty or starts.min() < period.frame0 or starts.max() > last:
            raise ValueError(f"game {game}: period {period.period} has no events or events starting "
                             f"outside frames {period.frame0}..{last}")
    return events


def _event_table(team: Iterable[int], kind: Iterable[str], subtypes: Iterable[Iterable[str]],
                 period: Iterable[int], start: Iterable[int], end: Iterable[int]) -> pd.DataFrame:
    table = pd.DataFrame({
        "team": np.fromiter(team, np.int8),
        "type": [str(k).strip().upper() for k in kind],
        "subtypes": pd.Series([frozenset(str(s).strip().upper() for s in subs) for subs in subtypes], dtype=object),
        "period": np.fromiter(period, np.int8),
        "start": np.fromiter(start, np.int32),
        "end": np.fromiter(end, np.int32),
    }, columns=list(EVENT_COLUMNS))
    return table.sort_values(["period", "start"], kind="stable").reset_index(drop=True)


def _events_from_csv(path: Path) -> pd.DataFrame:
    rows = pd.read_csv(path)
    team = rows["Team"].map({"Home": 0, "Away": 1})
    if team.isna().any():
        raise ValueError(f"{path.name}: Team values other than Home/Away: {sorted(rows['Team'].unique())}")
    subtypes = [() if pd.isna(s) else (s,) for s in rows["Subtype"]]
    return _event_table(team, rows["Type"], subtypes, rows["Period"], rows["Start Frame"], rows["End Frame"])


def _events_from_json(path: Path, team_ids: list[str]) -> pd.DataFrame:
    rows = json.loads(path.read_text())["data"]
    return _event_table(
        (team_ids.index(r["team"]["id"]) for r in rows),
        (r["type"]["name"] for r in rows),
        (_json_subtypes(r["subtypes"]) for r in rows),
        (r["period"] for r in rows),
        (r["start"]["frame"] for r in rows),
        (r["end"]["frame"] for r in rows),
    )


def _json_subtypes(value: None | dict | list) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value["name"]]
    return [s["name"] for s in value]
