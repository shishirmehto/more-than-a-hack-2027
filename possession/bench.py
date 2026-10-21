"""The evaluation harness: build Cases, score any decoder on them, sweep worlds. The only module that
joins everything, and the only one that knows the selection protocol.

A `Case` is one scoring problem: halves to decode, where they sit (Layout), and the GT array. Three
kinds, one type, so every decoder runs through the same two calls:

    dev_g1 / dev_g2 / dev_g3   one Metrica game: 2 halves, synthetic layout, event-derived labels
    dev_pooled                 all six halves in one layout: one spellF1 over ~721-1073 spells
    public                     BAR-ATH from baseline_raw.csv, public GT: 17 possessions, a CORRECTNESS
                               check (alignment, file format, label meaning), never a selection signal
                               (spellF1 noise ~ +/-0.04)

Determinism: no randomness outside dropout.challengeify (seeded, per-stream); decode is pure; pm is
deterministic. Same inputs, same table, bit for bit.

Selection protocol (the part a person would otherwise improvise):
  * a "world" is a DevSpec: merge_s x dead_bias (x seed). Both axes are UNKNOWN for the real match
    (label convention; real P(missing | dead)), so no single world is ground truth;
  * a decoder is scored on every world; the winner maximises the MINIMUM pooled spellF1 across worlds,
    ties broken by the mean (max-min). Measured on a synthetic proxy, a decoder that believes
    dead_bias = 3 scores 0.34 / 0.48 / 0.52 across worlds {1, 3, 11} while one that believes 1
    scores 0.44 / 0.44 / 0.44: belief 1 wins max-min and loses mean;
  * per-game rows are reported next to the pooled row so a win that lives in one game is visible;
  * paired_delta before reading any gap: two decoders on one case share their GT spells, so compare
    on those, not on two unpaired intervals.
Decode costs ~0.06 s per half at stride 5 (measured); pm.evaluate ~0.3 s on the pooled dev layout,
3 ms on the public window. A 135-config x 3-world grid is a few minutes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from . import challenge, dropout, metrica, score
from .decoder import Decoder
from .half import Half, Layout
from .dropout import DropoutParams
from .metrica import RuleV2


@dataclass(frozen=True, slots=True)
class DevSpec:
    """One dev world. Everything that shapes the dev data, nothing else.

    rule:      label rule (merge_s axis).
    dropout:   generator (dead_bias axis, target rate, ...).
    seed:      dropout seed; labels are seed-free.
    ball_fill: how native Metrica NaN are replaced before dropout ("hold" | "linear").
    """
    rule: RuleV2 = RuleV2()
    dropout: DropoutParams = DropoutParams()
    seed: int = 0
    ball_fill: Literal["hold", "linear"] = "hold"
    data_dir: str | Path | None = None


@dataclass(frozen=True, slots=True)
class Case:
    """name:       "dev_g1" | "dev_g2" | "dev_g3" | "dev_pooled" | "public".
    layout:     where each half sits in the scorer array (synthetic for dev, challenge.layout() for public).
    halves:     decoder inputs, in layout order.
    gt:         int8 [layout.n_total] in {0..3}. Derived from labels by Layout.assemble, never stored twice.
    provenance: JSON-able: DevSpec, sample-data commit, realised dropout stats (overall rate,
                P(missing | dead), P(missing | alive)) recomputed from halves + gt, not synced.
    """
    name: str
    layout: Layout
    halves: tuple[Half, ...]
    gt: NDArray[np.int8]
    provenance: Mapping[str, object]

    def __post_init__(self) -> None:
        """len(gt) == layout.n_total; codes in range (half.check_codes); gt is X on every row outside
        the layout's blocks; one half per block with half.n == block.n. A Case that violates these
        would be scored silently wrong by pm, so it cannot be constructed."""
        raise NotImplementedError

    def labels(self) -> list[NDArray[np.int8]]:
        """gt cut per block: int8 [block.n] in {0..3} (X only for the public case's ungraded frames)."""
        raise NotImplementedError

    def pairs(self) -> list[tuple[Half, NDArray[np.int8]]]:
        """(half, labels) for decoder.fit."""
        raise NotImplementedError

    def predict(self, model: Decoder) -> list[NDArray[np.int8]]:
        """One int8 [block.n] per half: `model.decode(h).codes`. Used for scoring AND for the submission,
        so the file that gets scored on the public window is the file that gets written."""
        raise NotImplementedError


def dev_cases(spec: DevSpec) -> list[Case]:
    """metrica.load -> dropout.challengeify -> per-game and pooled Cases. Requires fetched data."""
    # TODO: clean = metrica.load(spec.rule, ball_fill=spec.ball_fill, data_dir=spec.data_dir)   # 6 CleanHalf
    # TODO: halves = dropout.challengeify(clean, spec.dropout, spec.seed)
    # TODO: per game g: layout = Layout.synthetic([n, n]); gt = layout.assemble([c.labels for c in game_clean])
    # TODO: pooled: Layout.synthetic(all six sizes); provenance gets realised dropout stats per case.
    raise NotImplementedError


def public_case(source: Literal["baseline_raw", "atd"] = "baseline_raw") -> Case:
    """BAR-ATH: challenge.halves(source), challenge.layout(), GT = public CSV via score.read_codes
    (evaluation/gt/BAR-ATH_possession_gt_public.csv; real labels only on rows [11185, 18685)).
    Also the submission case: make-submission writes `case.predict(model)` through score.write_submission."""
    raise NotImplementedError


def run(models: Mapping[str, Decoder], cases: Sequence[Case], *, bootstrap_n: int = 0) -> pd.DataFrame:
    """One row per (model, case): model, case, then score.Scores.as_row() columns.

    Refuses (raises, naming the model and case) a prediction whose switch count exceeds 10x the GT's
    segments, instead of grinding through pm.spell_overlaps (O(GT x pred) pure Python) on a flicker.
    """
    # TODO: for name, m in models.items(): for c in cases:
    #           preds = c.predict(m); guard; s = score.evaluate(c.layout, c.gt, preds, bootstrap_n=bootstrap_n)
    raise NotImplementedError


def surface(base: Decoder, worlds: Mapping[float, Sequence[Case]], beliefs: Sequence[float]) -> pd.DataFrame:
    """Generator dead_bias (rows) x decoder dead_bias belief (columns) -> pooled-dev spellF1.

    worlds: {dead_bias: dev_cases(DevSpec(dropout=DropoutParams(dead_bias=...)))}. The decoder variant
    for a column is dataclasses.replace(base, emission=replace(base.emission, dead_bias=belief)).
    The last row is the column's minimum over worlds (the max-min score). This is the lever that
    turns the open question "does the real ATD drop the ball more on dead frames?" into a number per
    decoder choice, until the real ATD can be crossed with Smart Tagging set-piece windows.
    """
    raise NotImplementedError


def fit_dev(worlds: Mapping[str, Sequence[Case]], grid: Mapping[str, Sequence[float]]) -> tuple[Decoder, pd.DataFrame]:
    """decoder.fit on the pooled labels (counts), then grid over (temper, poss_mean_s, dead_mean_s,
    belief) scored on every world's dev_pooled case; returns (best by max-min, the whole grid table).
    The table is written next to the params JSON so a reader can see how flat the optimum is."""
    raise NotImplementedError


def paired_delta(a: Decoder, b: Decoder, case: Case, *, n_draws: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """(mean delta, low, high) of spellF1(a) - spellF1(b), bootstrapping the GT possessions both share.

    pm offers no paired comparison; its pieces do (score.matched_flags -> per-IoU hit flags per GT
    spell). Resample GT spells once per draw, apply to both, recompute each F1 with pm's own
    precision/recall arithmetic. 5th/95th percentiles, like pm. Use before believing any gap < 0.04.
    """
    raise NotImplementedError
