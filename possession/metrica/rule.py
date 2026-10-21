"""Label rule "v2": per-frame H / A / D from Metrica events. Pure function of one period's events.

What it encodes (measured by the explorers on the three games; reproduce these before trusting it:
alive share 55.1 / 58.4 / 67.9 %, raw spells 364 / 322 / 387, nearest-player team == label on
79-82 % of alive ball-visible frames):

    dead  = D opens the frame after a stoppage event and closes the frame before the next restart.
    owner = the team of the latest ball-controlling event.
    label = D if dead else owner;  D before kickoff;  optional merge of very short spells.

It is a *convention*, not truth: Metrica logs quick RECOVERY/PASS/BALL LOST alternations, so about 30%
of raw spells are under 2 s while the challenge's public window has median 7.6 s. `merge_s` is the
one knob for that mismatch, and the harness runs it as an axis of the dev world (0, 1, 2, 3), never
tuned toward the public window (17 possessions cannot rank anything).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from ..half import D, FPS

VERSION = "v2"


@dataclass(frozen=True, slots=True)
class RuleV2:
    """merge_s: spells shorter than this, that follow another spell directly (no D between), take the
    previous spell's label. 0.0 = raw rule. Measured spell counts (3 games pooled): m=0 -> 1073,
    1 s -> 978, 2 s -> 825, 3 s -> 721."""
    merge_s: float = 0.0


@dataclass(frozen=True, slots=True)
class PeriodLabels:
    """labels: int8 [stop] in {0,1,2}. kickoff: local index. stop: exclusive end of the block."""
    labels: NDArray[np.int8]
    kickoff: int
    stop: int


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
    """One period's events -> labels over local frames [0, stop).

    events: rows of one period in raw.EVENT_COLUMNS, `start`/`end` in source Frame numbers.
    frame0: source Frame of local index 0.  n: tracking frames in the period.

    Invariants of the result: values in {0,1,2}; labels[:kickoff] == D; kickoff < stop <= n;
    deterministic (stable sorts only, ties resolved to the later source row).
    """
    events = events.sort_values("start", kind="stable")
    start = np.clip(events["start"].to_numpy(np.int64) - frame0, 0, n - 1)
    end = np.clip(events["end"].to_numpy(np.int64) - frame0, 0, n - 1)
    anchor = {"start": start, "end": end}

    openers = np.concatenate([anchor[t.anchor][matches(t, events)] for t in DEAD_TRIGGERS])
    is_restart = ~np.any([matches(t, events) for t in NOT_RESTART], axis=0)
    restarts = start[is_restart]
    next_restart = np.searchsorted(restarts, openers, side="right")
    closes = np.where(next_restart < len(restarts),
                      restarts[np.minimum(next_restart, len(restarts) - 1)] - 1, n - 1)
    dead = _covered(n, openers + 1, closes)

    not_card = (events["type"] != "CARD").to_numpy()
    fallback = np.unique(np.concatenate([anchor[t.anchor][matches(t, events)] for t in FALLBACK_RESTART]))
    for r in fallback[fallback > 0]:
        if dead[r - 1]:
            continue
        earlier = end[not_card & (start < r)]
        if len(earlier) and earlier.max() < r - 1:
            dead[earlier.max() + 1:r] = True

    owned = np.isin(events["type"].to_numpy(), list(OWNER_KINDS))
    owner_start, owner_team = start[owned], events["team"].to_numpy(np.int8)[owned]
    last_owner = np.searchsorted(owner_start, np.arange(n), side="right") - 1
    # Team 0 / 1 are the label codes H / A.
    owner = np.where(last_owner < 0, D, owner_team[np.maximum(last_owner, 0)]).astype(np.int8)

    kickoffs = start[matches(KICKOFF, events)]
    kickoff = int(kickoffs[0] if len(kickoffs) else start[0])
    stop = int(np.clip(end.max() + 1, kickoff + 1, n))
    labels = np.where(dead, D, owner).astype(np.int8)
    labels[:kickoff] = D
    labels = labels[:stop]
    if rule.merge_s > 0:
        labels = _merge_short(labels, rule.merge_s * FPS)
    return PeriodLabels(labels, kickoff, stop)


def _covered(n: int, first: NDArray[np.int64], last: NDArray[np.int64]) -> NDArray[np.bool_]:
    """bool [n]: frames inside any inclusive range [first, last]; empty ranges (first > last) cover nothing."""
    keep = first <= last
    steps = np.bincount(first[keep], minlength=n + 1) - np.bincount(last[keep] + 1, minlength=n + 1)
    return np.cumsum(steps[:n]) > 0


def _merge_short(labels: NDArray[np.int8], min_frames: float) -> NDArray[np.int8]:
    """Repeatedly take the shortest possession run under min_frames that directly follows another
    possession run (leftmost on ties) and give it that run's label, until none is left. Shortest
    first is what reproduces the measured spell counts; a plain left-to-right pass does not."""
    edges = np.concatenate([[0], np.flatnonzero(labels[1:] != labels[:-1]) + 1, [len(labels)]])
    runs = [[int(a), int(b), int(labels[a])] for a, b in zip(edges[:-1], edges[1:])]
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
