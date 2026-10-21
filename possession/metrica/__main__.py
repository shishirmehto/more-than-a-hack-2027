"""Acceptance table for the Metrica labels: `python -m possession.metrica [--data-dir DIR]`.

One row per game plus a pooled row. Frames are per period (P1/P2; the pooled row sums them):
`tracking` is every frame the tracking file has, `block` is what `load` keeps (kickoff stretch as D,
post-final-whistle dropped). `alive` is the share of non-D frames, over the block and over the
tracking frames. `spells` are maximal H or A runs; `m0` is the raw rule and `m1`..`m3` are
RuleV2(merge_s=1, 2, 3). `ball NaN` is whether any ball_xy still has a NaN after `load`; it must be "no".
"""
from __future__ import annotations

import argparse
import time
from typing import Sequence

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from ..half import D, FPS, CleanHalf
from . import GAMES, RuleV2, load, raw

MERGES = (0.0, 1.0, 2.0, 3.0)


def spell_seconds(labels: NDArray[np.int8]) -> NDArray[np.float64]:
    """Durations in seconds of the maximal H or A runs of one half."""
    edges = np.concatenate([[0], np.flatnonzero(labels[1:] != labels[:-1]) + 1, [len(labels)]])
    return np.diff(edges)[labels[edges[:-1]] != D] / FPS


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m possession.metrica", description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default=None, help="folder from `fetch` (default: games.DATA_DIR/metrica_sample)")
    data_dir = parser.parse_args(argv).data_dir

    parse_s = {}
    for game in GAMES:
        started = time.perf_counter()
        raw.parse_game(game, data_dir)
        parse_s[game] = time.perf_counter() - started
    by_merge = {m: load(RuleV2(m), data_dir=data_dir) for m in MERGES}

    rows = []
    for game in GAMES:
        match = f"metrica_g{game}"
        rows.append(_row(f"G{game}", {m: [h for h in by_merge[m] if h.id.match == match] for m in MERGES},
                         parse_s[game]))
    rows.append(_row("pooled", by_merge, sum(parse_s.values())))
    print(pd.DataFrame(rows).to_string(index=False))
    return 0


def _row(name: str, halves: dict[float, Sequence[CleanHalf]], parse_seconds: float) -> dict[str, object]:
    raw_halves = halves[0.0]
    block = [len(h.labels) for h in raw_halves]
    tracking = [int(h.provenance["source_frames"]) for h in raw_halves]
    alive = sum(int((h.labels != D).sum()) for h in raw_halves)
    seconds = np.concatenate([spell_seconds(h.labels) for h in raw_halves])
    row: dict[str, object] = {
        "game": name,
        "tracking P1/P2": _per_period(tracking),
        "block P1/P2": _per_period(block),
        "alive % block": round(100 * alive / sum(block), 1),
        "alive % tracking": round(100 * alive / sum(tracking), 1),
        "spells m0": len(seconds),
        "median s": round(float(np.median(seconds)), 2),
    }
    for m in MERGES[1:]:
        row[f"spells m{m:g}"] = sum(len(spell_seconds(h.labels)) for h in halves[m])
    row["ball NaN"] = "yes" if any(np.isnan(h.geometry.ball_xy).any() for h in raw_halves) else "no"
    row["parse s"] = round(parse_seconds, 2)
    return row


def _per_period(frames: list[int]) -> str:
    return "/".join(map(str, frames)) if len(frames) == 2 else str(sum(frames))


if __name__ == "__main__":
    raise SystemExit(main())
