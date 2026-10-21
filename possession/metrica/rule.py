from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from .. import score
from ..half import D, FPS

VERSION = "v2"


@dataclass(frozen=True, slots=True)
class RuleV2:
    """How the raw rule-v2 spells become possessions: a merge of short spells (merge_s) or controlled
    possession (hold_s, min_passes), never both. All 0 is the raw rule. `key` names a rule ("m0",
    "m2", "h3p3") and `parse` reads one back.

    merge_s: spells shorter than this, that follow another spell directly (no D between), take the
    previous spell's label, shortest spell first (leftmost on ties), until none is left.

    hold_s, min_passes: controlled possession, one left-to-right pass. Inside a stretch of live play,
    a run of the other team only takes possession if that team shows control: the run lasts at least
    hold_s seconds, or it holds at least min_passes of that team's PASS events, or it holds that
    team's SET PIECE. Otherwise its frames keep the previous possessor. The first run after a
    stoppage or the kickoff always stands, and D frames never change. A run is judged on its own, so
    a rejected run's touches do not count towards the next one. 0 turns a proxy off."""
    merge_s: float = 0.0
    hold_s: float = 0.0
    min_passes: int = 0

    def __post_init__(self) -> None:
        if self.merge_s < 0 or self.hold_s < 0 or self.min_passes < 0:
            raise ValueError(f"rule fields must be >= 0: {self}")
        if self.merge_s and self.controlled:
            raise ValueError(f"merge_s and a controlled rule (hold_s, min_passes) are exclusive: {self}")

    @property
    def controlled(self) -> bool:
        return self.hold_s > 0 or self.min_passes > 0

    @property
    def key(self) -> str:
        """World-key prefix: "m2" for a merge rule ("m0" is the raw rule), "h2p3", "h5" or "p3" for a
        controlled one."""
        if not self.controlled:
            return f"m{self.merge_s:g}"
        return (f"h{self.hold_s:g}" if self.hold_s else "") + (f"p{self.min_passes}" if self.min_passes else "")

    @classmethod
    def parse(cls, key: str) -> RuleV2:
        """The rule whose `key` is `key`; ValueError for anything else."""
        found = re.fullmatch(r"m([\d.]+)|(?:h([\d.]+))?(?:p(\d+))?", key)
        if not found or not any(found.groups()):
            raise ValueError(f"not a rule key: {key!r} (expected e.g. m0, m2, h3p3, h5, p3)")
        merge, hold, passes = found.groups()
        rule = cls(float(merge or 0), float(hold or 0), int(passes or 0))
        if rule.key != key:
            raise ValueError(f"not a rule key: {key!r} (did you mean {rule.key!r}?)")
        return rule


@dataclass(frozen=True, slots=True)
class PeriodLabels:
    """labels: int8 in {0,1,2} over the block, local frames [0, len(labels)). kickoff: local index."""
    labels: NDArray[np.int8]
    kickoff: int


@dataclass(frozen=True, slots=True)
class Trigger:
    kind: str
    subtype_any: tuple[str, ...] | None
    anchor: Literal["start", "end"]


_STOPPING_LOSSES = ("OFFSIDE", "FORCED", "END HALF", "HAND BALL")

DEAD_TRIGGERS: tuple[Trigger, ...] = (
    Trigger("BALL OUT", None, "end"),
    Trigger("SHOT", ("OUT", "GOAL"), "end"),
    Trigger("BALL LOST", _STOPPING_LOSSES, "end"),
    Trigger("PASS", _STOPPING_LOSSES, "end"),
    Trigger("FAULT RECEIVED", None, "start"),
    Trigger("CHALLENGE", ("FAULT",), "start"),
)

NOT_RESTART: tuple[Trigger, ...] = (
    Trigger("CARD", None, "start"),
    Trigger("FAULT RECEIVED", None, "start"),
    Trigger("CHALLENGE", ("FAULT",), "start"),
)

FALLBACK_RESTART: tuple[Trigger, ...] = (
    Trigger("SET PIECE", None, "start"),
    Trigger("*", ("GOAL KICK",), "start"),
)

OWNER_KINDS: frozenset[str] = frozenset({"SET PIECE", "PASS", "SHOT", "RECOVERY", "CARRY"})

KICKOFF = Trigger("SET PIECE", ("KICK OFF",), "start")


def matches(trigger: Trigger, events: pd.DataFrame) -> NDArray[np.bool_]:
    hit = np.ones(len(events), bool) if trigger.kind == "*" else (events["type"] == trigger.kind).to_numpy()
    if trigger.subtype_any is not None:
        has_subtype = (any(w in s for s in subs for w in trigger.subtype_any) for subs in events["subtypes"])
        hit = hit & np.fromiter(has_subtype, bool, count=len(events))
    return hit


def label_period(events: pd.DataFrame, *, frame0: int, n: int, rule: RuleV2) -> PeriodLabels:
    """One period's events -> labels over local frames [0, stop), stop = the last event end + 1.

    events: rows of one period in raw.EVENT_COLUMNS, `start`/`end` in source Frame numbers.
    frame0: source Frame of local index 0.  n: tracking frames in the period.

    Invariants of the result: values in {0,1,2}; labels[:kickoff] == D; kickoff < len(labels) <= n;
    deterministic (stable sorts only, ties resolved to the later source row).
    """
    events = events.sort_values("start", kind="stable")
    start = np.clip(events["start"].to_numpy(np.int64) - frame0, 0, n - 1)
    end = np.clip(events["end"].to_numpy(np.int64) - frame0, 0, n - 1)
    anchor = {"start": start, "end": end}
    types, teams = events["type"].to_numpy(), events["team"].to_numpy(np.int8)

    openers = np.concatenate([anchor[t.anchor][matches(t, events)] for t in DEAD_TRIGGERS])
    is_restart = ~np.any([matches(t, events) for t in NOT_RESTART], axis=0)
    restarts = start[is_restart]
    last_dead_frame = np.append(restarts - 1, n - 1)
    dead = _covered(n, openers + 1, last_dead_frame[np.searchsorted(restarts, openers, side="right")])

    not_card = types != "CARD"
    fallback = np.unique(np.concatenate([anchor[t.anchor][matches(t, events)] for t in FALLBACK_RESTART]))
    for r in fallback[fallback > 0]:
        if dead[r - 1]:
            continue
        earlier = end[not_card & (start < r)]
        if len(earlier) and earlier.max() < r - 1:
            dead[earlier.max() + 1:r] = True

    owned = np.isin(types, list(OWNER_KINDS))
    owner_start, owner_team = start[owned], teams[owned]
    owner = np.append(D, owner_team).astype(np.int8)[np.searchsorted(owner_start, np.arange(n), side="right")]

    kickoffs = start[matches(KICKOFF, events)]
    kickoff = int(kickoffs[0] if len(kickoffs) else start[0])
    stop = int(np.clip(end.max() + 1, kickoff + 1, n))
    labels = np.where(dead, D, owner).astype(np.int8)
    labels[:kickoff] = D
    labels = labels[:stop]
    if rule.controlled:
        passes = [start[(types == "PASS") & (teams == team)] for team in (0, 1)]
        set_pieces = [start[(types == "SET PIECE") & (teams == team)] for team in (0, 1)]
        labels = _keep_controlled(labels, rule, passes, set_pieces)
    elif rule.merge_s > 0:
        labels = _merge_short(labels, rule.merge_s * FPS)
    return PeriodLabels(labels, kickoff)


def _covered(n: int, first: NDArray[np.int64], last: NDArray[np.int64]) -> NDArray[np.bool_]:
    keep = first <= last
    steps = np.bincount(first[keep], minlength=n + 1) - np.bincount(last[keep] + 1, minlength=n + 1)
    return np.cumsum(steps[:n]) > 0


def _keep_controlled(labels: NDArray[np.int8], rule: RuleV2, passes: list[NDArray[np.int64]],
                     set_pieces: list[NDArray[np.int64]]) -> NDArray[np.int8]:
    def inside(starts: NDArray[np.int64], a: int, b: int) -> int:
        return int(np.searchsorted(starts, b) - np.searchsorted(starts, a))

    out, holder = labels.copy(), D
    for a, b, team in score.segments(labels, [(0, len(labels))]):
        if team != D and holder not in (D, team) and not (
                (rule.hold_s and b - a >= rule.hold_s * FPS)
                or (rule.min_passes and inside(passes[team], a, b) >= rule.min_passes)
                or inside(set_pieces[team], a, b)):
            out[a:b] = holder
        else:
            holder = team
    return out


def _merge_short(labels: NDArray[np.int8], min_frames: float) -> NDArray[np.int8]:
    runs = [list(segment) for segment in score.segments(labels, [(0, len(labels))])]
    while True:
        short = [(b - a, k) for k, (a, b, label) in enumerate(runs)
                 if k > 0 and label != D and runs[k - 1][2] != D and b - a < min_frames]
        if not short:
            return np.repeat(np.array([r[2] for r in runs], np.int8), [b - a for a, b, _ in runs])
        k = min(short)[1]
        runs[k - 1][1] = runs[k][1]
        del runs[k]
        if k < len(runs) and runs[k][2] == runs[k - 1][2]:
            runs[k - 1][1] = runs[k][1]
            del runs[k]
