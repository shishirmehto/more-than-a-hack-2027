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

`python -m possession.metrica` prints the acceptance table for the labels (see __main__.py).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from ..half import CleanHalf, Geometry, HalfId
from . import raw
from .fetch import COMMIT, fetch
from .rule import VERSION, RuleV2, label_period

__all__ = ["COMMIT", "fetch", "load", "RuleV2"]

GAMES = (1, 2, 3)


def load(rule: RuleV2 = RuleV2(), *, ball_fill: Literal["hold", "linear"] = "hold",
         games: tuple[int, ...] = GAMES, data_dir: str | Path | None = None) -> tuple[CleanHalf, ...]:
    """Parse + label + fill. A game whose files are missing raises one error naming them and the fetch command.

    Parsing (raw.parse_game) is memoised per (game, data_dir): sweeps that re-label with other
    `merge_s` or re-draw dropout never re-read 183 MB. Labelling is ~0.1 s per game.
    """
    data_dir = None if data_dir is None else str(data_dir)
    halves = []
    for game in games:
        parsed = raw.parse_game(game, data_dir)
        for period in parsed.periods:
            events = parsed.events[parsed.events["period"] == period.period]
            n = len(period.ball_xy)
            labelled = label_period(events, frame0=period.frame0, n=n, rule=rule)
            geometry = Geometry(fill_ball(period.ball_xy[:labelled.stop], ball_fill),
                                period.players_xy[:labelled.stop], period.slot_team, raw.PITCH_M)
            provenance = {"rule": VERSION, "merge_s": rule.merge_s, "pre_kickoff": "D", "ball_fill": ball_fill,
                          "sample_data_commit": COMMIT, "source_frame0": period.frame0,
                          "source_frames": n, "block_frames": labelled.stop}
            halves.append(CleanHalf(HalfId(f"metrica_g{game}", period.period, labelled.kickoff),
                                    geometry, labelled.labels, provenance))
    return tuple(halves)


def fill_ball(ball_xy: NDArray[np.float32], how: Literal["hold", "linear"]) -> NDArray[np.float32]:
    """Replace every NaN in the native ball track. Postcondition: no NaN. Idempotent.

    "hold" (default): forward-fill the last observed position, back-fill the head. A dead ball then
    sits where it left play, stationary, and jumps at the restart, like a tracker that re-acquires
    the ball. "linear": np.interp over indices; gives the dead ball a constant velocity that a
    ball-speed feature would read as live play (a different leak), so it is the option, not the default.
    """
    n = len(ball_xy)
    observed = ~np.isnan(ball_xy).any(axis=1)
    if not observed.any():
        raise ValueError("ball is never observed in this half")
    if how == "hold":
        first = int(np.argmax(observed))
        last_seen = np.maximum.accumulate(np.where(observed, np.arange(n), first))
        return ball_xy[last_seen]
    if how == "linear":
        seen = np.flatnonzero(observed)
        return np.stack([np.interp(np.arange(n), seen, ball_xy[seen, axis]) for axis in (0, 1)],
                        axis=1).astype(np.float32)
    raise ValueError(f"ball_fill must be 'hold' or 'linear', got {how!r}")
