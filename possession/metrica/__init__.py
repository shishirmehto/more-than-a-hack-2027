"""Metrica public sample games as clean, labelled halves. Owns everything about that dataset.

Public surface (three names):

    fetch(data_dir=None)                      one-off, network, idempotent, sha256-checked
    load(rule=RuleV2(), ball_fill="hold")     -> tuple[CleanHalf, ...], six halves, order g1p1 g1p2 g2p1 ...
    RuleV2                                    the label rule's one tunable (merge_s)

What `load` guarantees (the boundary of this subpackage; everything inside is a private detail):
  * labels come from events only (rule v2), never from the ball-NaN pattern;
  * ball_xy has no NaN (native out-of-play NaN is filled), so injected dropout is the only missingness
    a decoder ever sees: the dead-ball signal Metrica leaks through native NaN cannot reach it;
  * every half is a gap-free block [first tracking frame of the period, last event end + 1), labels
    in {H, A, D} with the pre-kickoff stretch as D (mirrors the challenge's graded half-2 stretch);
  * coordinates in metres on a 105 x 68 pitch, origin top-left, as the raw files (kloppy is NOT used:
    its CSV loader flips y and its open-data loader re-downloads through an fsspec cache).

Three internal modules, split by the knowledge each owns, not by pipeline order:
    fetch.py  where the files are and that they are the right bytes
    raw.py    the two file formats (CSV pair + CSV events, EPTS txt + xml + JSON events)
    rule.py   what football events mean for who has the ball
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from ..half import CleanHalf, Geometry, HalfId
from . import raw
from .fetch import COMMIT, fetch
from .rule import RuleV2, label_period

__all__ = ["COMMIT", "fetch", "load", "RuleV2"]

GAMES = (1, 2, 3)


def load(rule: RuleV2 = RuleV2(), *, ball_fill: Literal["hold", "linear"] = "hold",
         games: tuple[int, ...] = GAMES, data_dir: str | Path | None = None) -> tuple[CleanHalf, ...]:
    """Parse + label + fill. Raises one readable error naming every missing file and the fetch command.

    Parsing (raw.parse_game) is memoised per (game, data_dir): sweeps that re-label with other
    `merge_s` or re-draw dropout never re-read 183 MB. Labelling is ~0.1 s per game.
    """
    # TODO: halves = []
    #       for g in games:
    #           raw_game = raw.parse_game(g, str(data_dir))                 # cached
    #           for period in raw_game.periods:
    #               ev = raw_game.events[raw_game.events.period == period.period]
    #               pl = label_period(ev, frame0=period.frame0, n=len(period.ball_xy), rule=rule)
    #               geom = Geometry(fill_ball(period.ball_xy[:pl.stop], ball_fill),
    #                               period.players_xy[:pl.stop], period.slot_team, raw.PITCH_M)
    #               halves.append(CleanHalf(HalfId(f"metrica_g{g}", period.period, pl.kickoff),
    #                                       geom, pl.labels, provenance))
    #       return tuple(halves)
    raise NotImplementedError


def fill_ball(ball_xy: NDArray[np.float32], how: Literal["hold", "linear"]) -> NDArray[np.float32]:
    """Replace every NaN in the native ball track. Postcondition: no NaN. Idempotent.

    "hold" (default): forward-fill the last observed position, back-fill the head. A dead ball then
    sits where it left play, stationary, and jumps at the restart, like a tracker that re-acquires
    the ball. "linear": np.interp over indices; gives the dead ball a constant velocity that a
    ball-speed feature would read as live play (a different leak), so it is the option, not the default.
    """
    # TODO: idx = np.flatnonzero(~np.isnan(ball_xy[:, 0])); hold -> idx of last observed via
    #       np.maximum.accumulate(where(observed, arange, 0)), head -> first observed; linear -> np.interp per axis.
    raise NotImplementedError
