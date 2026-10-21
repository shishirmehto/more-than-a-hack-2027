"""Label rule "v2": per-frame H / A / D from Metrica events. Pure function of one period's events.

What it encodes (measured by the explorers on the three games; reproduce these before trusting it:
alive share 55.1 / 58.4 / 67.9 %, raw spells 364 / 322 / 387, nearest-player team == label on
79-82 % of alive ball-visible frames):

    dead  = D opens the frame after a stoppage event and closes the frame before the next restart.
    owner = the team of the latest ball-controlling event.
    label = D if dead else owner;  D before kickoff;  optional controlled-possession filter or
            merge of very short spells.

It is a *convention*, not truth: Metrica logs quick RECOVERY/PASS/BALL LOST alternations, so about 30%
of raw spells are under 2 s while the challenge's public window has median 7.6 s. Two knobs address
that mismatch, both axes of the dev world and never tuned toward the public window (17 possessions
cannot rank anything): `merge_s`, a length threshold, and `hold_s` / `min_passes`, the challenge's own
definition of a change of possession (CHALLENGE.md, "Change of possession").
"""
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
    previous spell's label, shortest spell first (leftmost on ties), until none is left. Measured
    spell counts (3 games pooled): m=0 -> 1073, 1 s -> 978, 2 s -> 825, 3 s -> 721.

    hold_s, min_passes: controlled possession, one left-to-right pass. Inside a stretch of live play,
    a run of the other team only takes possession if that team shows control: the run lasts at least
    hold_s seconds, or it holds at least min_passes of that team's PASS events (Metrica logs only
    completed passes as PASS), or it holds that team's SET PIECE. Otherwise its frames keep the
    previous possessor, so a contested or loose phase stays with the last team. The first run after
    a stoppage or the kickoff always stands (the restart names the possessor), and D frames never
    change. A run is judged on its own, so a rejected run's touches do not count towards the next
    one. 0 turns a proxy off.

    Measured on the three games (426,640 frames): hold_s alone is the merge with a left-to-right scan
    instead of shortest first (0 frames differ at 1, 2, 3 and 5 s; 977 / 818 / 709 spells at
    1 / 2 / 3 s). So the controlled labels differ from merge_s ones by the scan order, plus the pass
    proxy, which binds only from about 4 s (h2p3 = h2 and h3p3 = h3; h5p3 moves 306 frames off h5).
    The SET PIECE clause changed no label. merge_s with a controlled rule raises: at merge_s <=
    hold_s the merge changed nothing or exactly undid the pass proxy (h5p3 + m5 = h5)."""
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
    """Selects events of `kind` ("*" = any kind) whose subtype contains any of `subtype_any`
    (None = any subtype). `anchor` is the frame the rule reads: the event's start or end."""
    kind: str
    subtype_any: tuple[str, ...] | None
    anchor: Literal["start", "end"]


_STOPPING_LOSSES = ("OFFSIDE", "FORCED", "END HALF", "HAND BALL")

# Stoppage openers: D starts at anchor + 1. CARD and ADVANTAGE are never openers.
DEAD_TRIGGERS: tuple[Trigger, ...] = (
    Trigger("BALL OUT", None, "end"),
    Trigger("SHOT", ("OUT", "GOAL"), "end"),
    Trigger("BALL LOST", _STOPPING_LOSSES, "end"),
    Trigger("PASS", _STOPPING_LOSSES, "end"),
    Trigger("FAULT RECEIVED", None, "start"),
    Trigger("CHALLENGE", ("FAULT",), "start"),
)

# Events whose start does NOT close a stoppage; every other event's start is a restart.
NOT_RESTART: tuple[Trigger, ...] = (
    Trigger("CARD", None, "start"),
    Trigger("FAULT RECEIVED", None, "start"),
    Trigger("CHALLENGE", ("FAULT",), "start"),
)

# A restart the openers missed: if the frame before one of these is alive, the stoppage runs from
# the latest earlier end frame (CARD excluded) to the restart.
FALLBACK_RESTART: tuple[Trigger, ...] = (
    Trigger("SET PIECE", None, "start"),
    Trigger("*", ("GOAL KICK",), "start"),
)

# The owner is the team of the latest of these by start frame. CARRY exists only in Game 3.
OWNER_KINDS: frozenset[str] = frozenset({"SET PIECE", "PASS", "SHOT", "RECOVERY", "CARRY"})

# The period's first match is the kickoff; a period with none starts at its first event.
KICKOFF = Trigger("SET PIECE", ("KICK OFF",), "start")


def matches(trigger: Trigger, events: pd.DataFrame) -> NDArray[np.bool_]:
    """bool [m]: events the trigger selects (kind equality or "*", subtype substring, upper-case)."""
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
    last_dead_frame = np.append(restarts - 1, n - 1)  # a stoppage with no later restart runs to the period's end
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
    # Team 0 / 1 are the label codes H / A; slot 0 is "no owner event yet".
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
    """bool [n]: frames inside any inclusive range [first, last]; empty ranges (first > last) cover nothing."""
    keep = first <= last
    steps = np.bincount(first[keep], minlength=n + 1) - np.bincount(last[keep] + 1, minlength=n + 1)
    return np.cumsum(steps[:n]) > 0


def _keep_controlled(labels: NDArray[np.int8], rule: RuleV2, passes: list[NDArray[np.int64]],
                     set_pieces: list[NDArray[np.int64]]) -> NDArray[np.int8]:
    """RuleV2.hold_s / min_passes, left to right over the runs. passes / set_pieces: local start
    frames per team (index = label code), sorted because the events are."""
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
    """Repeatedly take the shortest possession run under min_frames that directly follows another
    possession run (leftmost on ties) and give it that run's label, until none is left. Shortest
    first is what reproduces the measured spell counts; a plain left-to-right pass does not."""
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
