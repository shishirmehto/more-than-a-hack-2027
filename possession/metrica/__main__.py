from __future__ import annotations

import argparse
import time
from typing import Sequence

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from .. import score
from ..half import D, FPS, CleanHalf
from . import GAMES, RuleV2, load, raw

MERGES = (0.0, 1.0, 2.0, 3.0)

SPELL_RULES = (RuleV2(), RuleV2(2.0), RuleV2(3.0), RuleV2(5.0),
               RuleV2(hold_s=2.0, min_passes=3), RuleV2(hold_s=3.0, min_passes=3), RuleV2(hold_s=5.0, min_passes=3),
               RuleV2(hold_s=5.0), RuleV2(min_passes=3))


def spell_seconds(labels: NDArray[np.int8]) -> NDArray[np.float64]:
    return np.array([b - a for a, b, _ in score.possession_spells(labels, [(0, len(labels))])], np.float64) / FPS


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m possession.metrica",
        description="Print the acceptance tables for the Metrica labels: per-game shares and spell counts, "
                    "then pooled spell lengths per label rule.")
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
    print()
    loaded = {RuleV2(m): halves for m, halves in by_merge.items()}
    spells = [_spell_row(rule, loaded.get(rule) or load(rule, data_dir=data_dir)) for rule in SPELL_RULES]
    print(pd.DataFrame(spells).to_string(index=False))
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


def _spell_row(rule: RuleV2, halves: Sequence[CleanHalf]) -> dict[str, object]:
    seconds = np.concatenate([spell_seconds(h.labels) for h in halves])
    return {"rule": rule.key, "spells": len(seconds), "mean s": round(float(seconds.mean()), 1),
            "median s": round(float(np.median(seconds)), 1), "% under 3 s": round(100 * float((seconds < 3).mean()), 1)}


def _per_period(frames: list[int]) -> str:
    return "/".join(map(str, frames)) if len(frames) == 2 else str(sum(frames))


if __name__ == "__main__":
    raise SystemExit(main())
