from __future__ import annotations

import dataclasses
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
         data_dir: str | Path | None = None) -> tuple[CleanHalf, ...]:
    """Parse + label + fill. A game whose files are missing raises one error naming them and the fetch command."""
    halves = []
    for game in GAMES:
        parsed = raw.parse_game(game, data_dir)
        for period in parsed.periods:
            events = parsed.events[parsed.events["period"] == period.period]
            n = len(period.ball_xy)
            labelled = label_period(events, frame0=period.frame0, n=n, rule=rule)
            stop = len(labelled.labels)
            geometry = Geometry(fill_ball(period.ball_xy[:stop], ball_fill),
                                period.players_xy[:stop], period.slot_team, raw.PITCH_M)
            provenance = {"rule": VERSION, **dataclasses.asdict(rule), "pre_kickoff": "D", "ball_fill": ball_fill,
                          "sample_data_commit": COMMIT, "source_frame0": period.frame0,
                          "source_frames": n, "block_frames": stop}
            halves.append(CleanHalf(HalfId(f"metrica_g{game}", period.period, labelled.kickoff),
                                    geometry, labelled.labels, provenance))
    return tuple(halves)


def fill_ball(ball_xy: NDArray[np.float32], how: Literal["hold", "linear"]) -> NDArray[np.float32]:
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
