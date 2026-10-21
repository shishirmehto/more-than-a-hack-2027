"""The two Metrica file formats, parsed into one in-memory shape. No labels, no dropout, no policy.

Games 1 and 2: a Home and an Away tracking CSV (3 header rows; columns Period, Frame, Time [s], then
x,y per player slot, subs NaN until they are on, last two columns the ball) plus an events CSV.
Game 3: EPTS tracking `frame:x,y;...(22 groups);:bx,by` with `NaN,NaN` for missing, a metadata.xml
whose 11 DataFormatSpecification windows rebind the 22 slots at substitutions, and an events JSON.

Both formats are normalised at this boundary (per boundary-discipline) so nothing downstream ever
branches on game number:
    coordinates  -> metres, x * 105, y * 68, origin top-left, NO y flip (events match raw tracking)
    team         -> 0 home / 1 away (Game 3: Team A = home)
    events       -> the EVENT_COLUMNS table below
    periods      -> split on the Period column, never on a frame gap (frame ids are 1-based and run
                    contiguously across periods; there is no halftime gap in the ids)
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.typing import NDArray

PITCH_M = (105.0, 68.0)

# One row per event. `type` and `subtypes` are upper-cased and stripped at parse time so the rule
# module matches strings without case logic. Game 3 JSON subtypes (null | dict | list) all become a
# frozenset; its CARRY events are kept (the rule module decides whether they own the ball).
EVENT_COLUMNS: tuple[str, ...] = (
    "team",      # int8   0 home / 1 away
    "type",      # str    "PASS", "SET PIECE", "BALL OUT", ...
    "subtypes",  # frozenset[str]
    "period",    # int8   1 | 2
    "start",     # int32  source Frame number
    "end",       # int32  source Frame number
)


@dataclass(frozen=True, slots=True)
class RawPeriod:
    """One period of tracking, native (with the out-of-play NaN Metrica uses as its dead-ball marker).

    period:     1 | 2
    frame0:     source Frame of local index 0 (a period's first tracking frame)
    ball_xy:    float32 [n, 2] metres, NaN where untracked (this IS the dead-ball leak; never used as a cue)
    players_xy: float32 [n, S, 2] metres, NaN for subs not on. S = 22..28.
    slot_team:  int8 [S]. Game 3: asserted constant across the 11 substitution windows.
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
    events: pd.DataFrame  # EVENT_COLUMNS, sorted by (period, start), stable on source row order


@functools.cache
def parse_game(game: int, data_dir: str | None = None) -> RawGame:
    """Parse one game from the local files (never fetches). Memoised on (game, data_dir): ~1 s a game.

    Postconditions checked here and nowhere downstream: frame ids contiguous within a period; x,y in
    a sane window (-0.2..1.2 before scaling; the ball may be off-pitch); both periods present; every
    event's start/end falls inside its period's frame range (clip + count, report in provenance).
    """
    # TODO: game in (1, 2) -> _parse_csv_game ; game == 3 -> _parse_epts_game
    raise NotImplementedError


def _parse_csv_game(home_csv: Path, away_csv: Path, events_csv: Path, game: int) -> RawGame:
    # TODO: pd.read_csv(header=None, skiprows=3) on both team files; assert Period/Frame columns agree;
    #       players = [home x,y pairs..., away x,y pairs...]; ball = Home file's last two columns;
    #       split per period; events via _events_from_csv (columns Team, Type, Subtype, Period,
    #       Start Frame, End Frame; Team "Home"/"Away").
    raise NotImplementedError


def _parse_epts_game(tracking_txt: Path, meta_xml: Path, events_json: Path) -> RawGame:
    # TODO: one pass over lines: frame, groups, ball = line.split(":");
    #       np.fromstring(groups.replace(";", ","), sep=",") with "NaN" tokens -> float; 22 x 2 + ball.
    #       Period boundaries from metadata.xml <Period> start/end frames. slot_team from the first
    #       DataFormatSpecification window's player -> teamId; assert every later window agrees.
    raise NotImplementedError


def _events_from_csv(path: Path) -> pd.DataFrame:
    raise NotImplementedError


def _events_from_json(path: Path) -> pd.DataFrame:
    # TODO: {data: [...]}; team.id/name -> 0/1 (Team A = home); type.name; subtypes null|dict|list -> frozenset;
    #       start.frame / end.frame; period. Verify the key names against the real file at first run.
    raise NotImplementedError
