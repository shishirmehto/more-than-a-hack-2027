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


def matches(trigger: Trigger, events: pd.DataFrame) -> NDArray[np.bool_]:
    """bool [m]: events the trigger selects (kind equality or "*", subtype substring, upper-case)."""
    raise NotImplementedError


def label_period(events: pd.DataFrame, *, frame0: int, n: int, rule: RuleV2) -> PeriodLabels:
    """One period's events -> labels over local frames [0, stop).

    events: rows of one period in raw.EVENT_COLUMNS, `start`/`end` in source Frame numbers.
    frame0: source Frame of local index 0.  n: tracking frames in the period.

    Invariants of the result: values in {0,1,2}; labels[:kickoff] == D; kickoff < stop <= n;
    deterministic (stable sorts only, ties resolved to the later source row).
    """
    # TODO 1. s = start - frame0, e = end - frame0 (int arrays); clip to [0, n-1].
    #
    # TODO 2. dead openers T (D starts at T+1): anchor frame of every event selected by a DEAD_TRIGGERS entry.
    #
    # TODO 3. restart starts R = sorted(s[events not selected by any NOT_RESTART trigger]).
    #     each opener T closes at the first r in R with r > T:  close = r - 1
    #     (np.searchsorted(R, T, side="right")); no such r -> dead to the end of the period.
    #     dead = difference array over (T+1, close+1), cumsum > 0.
    #
    # TODO 4. restart fallback. For every event selected by a FALLBACK_RESTART entry, start r:
    #     if frame r-1 is not dead, L = max(e over earlier events, excluding CARD),
    #     mark dead [L+1, r-1]. (Game 3 alive-and-ball-NaN frames drop 2078 -> 679 with this.)
    #
    # TODO 5. owner timeline. own = events with type in OWNER_KINDS, np.argsort(kind="stable") by s;
    #     idx = np.searchsorted(own_s, arange(n), side="right") - 1   # last owner event with s <= f;
    #     equal starts resolve to the later row because the sort is stable.
    #     owner[idx < 0] = D (before any owner event).
    #
    # TODO 6. kickoff = first SET PIECE with subtype KICK OFF (fallback: first event) start - frame0.
    #     labels = where(dead, D, owner); labels[:kickoff] = D.
    #     stop = clip(max(e) + 1, kickoff + 1, n)   # drops post-final-whistle frames (they are X via Layout)
    #
    # TODO 7. merge (rule.merge_s > 0): run-length encode labels[:stop]; walk possession runs in
    #     order; a run of H/A shorter than merge_s*FPS whose predecessor is an adjacent H/A run takes
    #     the predecessor's label; repeat until stable (cascades resolve left to right, deterministic).
    raise NotImplementedError
