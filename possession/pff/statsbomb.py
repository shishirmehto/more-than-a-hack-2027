"""StatsBomb's possession convention on PFF's World Cup 2022 tracking: the same 64 games, the same ball and
the same dead frames, with each live frame given to StatsBomb's possession_team instead of PFF's last
home_ball. StatsBomb changes possession only once a team has established control, so its spells are fewer
and longer (a median of 85 per half against PFF's 137). The events are hudl/open-data at COMMIT under
<data dir>/external/statsbomb_wc2022, fetched for local research under the StatsBomb Public Data User
Agreement (STATSBOMB_AGREEMENT_ACCEPTED=1), which asks for StatsBomb credit on any published analysis: never
commit an event file or anything frame-level derived from one."""
from __future__ import annotations

import dataclasses
import difflib
import json
from pathlib import Path
from typing import Iterator

import numpy as np
from numpy.typing import NDArray

import games
from ..half import FPS, A, D, H, CleanHalf
from ..metrica.rule import RuleV2, merge_short
from . import GAMES, root as pff_root
from . import load as load_pff

__all__ = ["COMMIT", "load"]

COMMIT = "4b73468fc5b0f1950f9f66fada70ad3a4f9327cb"
_MIN_NAME_MATCH = 1.2


def root(data_dir: str | Path | None = None) -> Path:
    return Path(games.DATA_DIR) / "external" / "statsbomb_wc2022" if data_dir is None else Path(data_dir)


def load(rule: RuleV2 = RuleV2(), *, data_dir: str | Path | None = None) -> Iterator[CleanHalf]:
    """pff.load's halves relabelled: a frame PFF calls dead stays D, and a live frame takes the
    possession_team of the latest StatsBomb possession that began at or before it, timed from the
    period's kickoff on both sides. Live frames before the first possession keep PFF's team. Games pair
    by date and team names. A merge rule merges the relabelled frames at 25 Hz, as pff.load does."""
    if rule.controlled:
        raise ValueError(f"StatsBomb-on-PFF supports merge rules only, got {rule.key}")
    return _halves(rule, _spans(root(data_dir)))


def _halves(rule: RuleV2, spans: dict[tuple[str, int], tuple[NDArray[np.float64], NDArray[np.int8]]]
            ) -> Iterator[CleanHalf]:
    for half in load_pff(RuleV2.parse("m0")):
        starts, teams = spans[(half.id.match.removeprefix("pff_"), half.id.half)]
        since = (np.arange(len(half.labels)) - half.id.kickoff) / FPS
        k = np.searchsorted(starts, since, side="right") - 1
        team = np.where(k >= 0, teams[np.maximum(k, 0)], half.labels)
        labels = np.where(half.labels == D, D, team).astype(np.int8)
        if rule.merge_s:
            labels = merge_short(labels, rule.merge_s * FPS)
        yield dataclasses.replace(half, labels=labels, provenance={
            **half.provenance, "rule": rule.key, "statsbomb_commit": COMMIT,
            "labels": "PFF's dead frames (kloppy 3.18 rule); live frames take StatsBomb's possession_team, held "
                      "from each possession's first event to the next",
            "licence": "PFF proprietary and the StatsBomb Public Data User Agreement: never commit"})


def _spans(folder: Path) -> dict[tuple[str, int], tuple[NDArray[np.float64], NDArray[np.int8]]]:
    """(PFF game, period) -> (start in seconds since kickoff, H or A) of every StatsBomb possession."""
    by_date: dict[str, list[dict]] = {}
    for match in json.loads((folder / "matches.json").read_text()):
        by_date.setdefault(match["match_date"], []).append(match)
    out = {}
    for game in GAMES:
        meta = json.loads((pff_root() / "metadata" / f"{game}.json").read_text())[0]
        match = _pair(by_date.get(meta["date"][:10], []), meta["homeTeam"]["name"], meta["awayTeam"]["name"], game)
        home = match["home_team"]["home_team_name"]
        first: dict[tuple[int, int], tuple[float, int]] = {}
        for event in json.loads((folder / "events" / f"{match['match_id']}.json").read_text()):
            key = (event["period"], event["possession"])
            if key not in first:
                h, m, s = event["timestamp"].split(":")
                first[key] = (int(h) * 3600 + int(m) * 60 + float(s), H if event["possession_team"]["name"] == home else A)
        for period in (1, 2):
            rows = sorted(v for (p, _), v in first.items() if p == period)
            out[(game, period)] = (np.array([t for t, _ in rows]), np.array([team for _, team in rows], np.int8))
    return out


def _pair(candidates: list[dict], home: str, away: str, game: str) -> dict:
    def score(match: dict) -> float:
        return (difflib.SequenceMatcher(None, home, match["home_team"]["home_team_name"]).ratio()
                + difflib.SequenceMatcher(None, away, match["away_team"]["away_team_name"]).ratio())
    best = max(candidates, key=score, default=None)
    if best is None or score(best) < _MIN_NAME_MATCH:
        raise ValueError(f"PFF game {game} ({home} v {away}) has no StatsBomb match on its date with the same home side")
    return best
