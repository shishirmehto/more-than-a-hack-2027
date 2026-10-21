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

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from . import challenge, dropout, metrica, score
from .decoder import Decoder
from .half import D, NO_TEAM, X, Half, Layout, check_codes
from .dropout import DropoutParams
from .metrica import RuleV2

PUBLIC_GT = Path(__file__).resolve().parents[1] / "evaluation" / "gt" / f"{challenge.GAME}_possession_gt_public.csv"

# bench.run refuses a prediction with more switches than this many times the GT's segments.
MAX_SWITCH_RATIO = 10


class Flicker(ValueError):
    """A prediction refused by run's switch guard before pm.spell_overlaps grinds through it."""


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
        check_codes(self.gt, allow_x=True)
        layout = self.layout
        if len(self.gt) != layout.n_total:
            raise ValueError(f"{self.name}: gt has {len(self.gt)} rows, layout {layout.n_total}")
        if len(self.halves) != len(layout.blocks):
            raise ValueError(f"{self.name}: {len(self.halves)} halves for {len(layout.blocks)} blocks")
        inside = np.zeros(layout.n_total, dtype=bool)
        for h, b in zip(self.halves, layout.blocks):
            if h.n != b.n:
                raise ValueError(f"{self.name}: half {h.id} has {h.n} frames, its block {b.n}")
            inside[b.origin:b.origin + b.n] = True
        if (self.gt[~inside] != X).any():
            raise ValueError(f"{self.name}: gt must be X on every row outside the blocks")
        self.gt.setflags(write=False)

    def labels(self) -> list[NDArray[np.int8]]:
        """gt cut per block: int8 [block.n] in {0..3} (X only for the public case's ungraded frames)."""
        return self.layout.cut(self.gt)

    def pairs(self) -> list[tuple[Half, NDArray[np.int8]]]:
        """(half, labels) for decoder.fit."""
        return list(zip(self.halves, self.labels()))

    def predict(self, model: Decoder) -> list[NDArray[np.int8]]:
        """One int8 [block.n] per half: `model.decode(h).codes`. Used for scoring AND for the submission,
        so the file that gets scored on the public window is the file that gets written."""
        return [model.decode(h).codes for h in self.halves]


def dev_cases(spec: DevSpec) -> list[Case]:
    """metrica.load -> dropout.challengeify -> per-game and pooled Cases. Requires fetched data.

    Returns [dev_g1, dev_g2, dev_g3, dev_pooled]; each provenance holds the spec, the sample-data
    commit and the realised dropout stats of that case's halves (see dropout_stats)."""
    clean = metrica.load(spec.rule, ball_fill=spec.ball_fill, data_dir=spec.data_dir)
    halves = dropout.challengeify(clean, spec.dropout, spec.seed)
    by_game: dict[str, list[int]] = {}
    for i, c in enumerate(clean):
        by_game.setdefault(c.id.match, []).append(i)
    groups = [("dev_" + match.removeprefix("metrica_"), idx) for match, idx in by_game.items()]
    groups.append(("dev_pooled", list(range(len(clean)))))
    spec_json = {**asdict(spec), "data_dir": None if spec.data_dir is None else str(spec.data_dir)}
    cases = []
    for name, idx in groups:
        layout = Layout.synthetic([clean[i].geometry.n for i in idx])
        labels = [clean[i].labels for i in idx]
        case_halves = tuple(halves[i] for i in idx)
        provenance = {"spec": spec_json, "sample_data_commit": metrica.COMMIT,
                      "halves": [f"{h.id.match}/{h.id.half}" for h in case_halves],
                      "dropout": dropout_stats(case_halves, labels)}
        cases.append(Case(name, layout, case_halves, layout.assemble(labels), provenance))
    return cases


def public_case(source: Literal["baseline_raw", "atd"] = "baseline_raw") -> Case:
    """BAR-ATH: challenge.halves(source), challenge.layout(), GT = public CSV via score.read_codes
    (evaluation/gt/BAR-ATH_possession_gt_public.csv; real labels only on rows [11185, 18685)).
    Also the submission case: make-submission writes `case.predict(model)` through score.write_submission."""
    layout = challenge.layout()
    gt = score.read_codes(PUBLIC_GT, layout.n_total)
    halves = tuple(challenge.halves(source))
    provenance = {"source": source, "gt": PUBLIC_GT.name, "dropout": dropout_stats(halves, layout.cut(gt))}
    return Case("public", layout, halves, gt, provenance)


def dropout_stats(halves: Sequence[Half], labels: Sequence[NDArray[np.int8]]) -> dict[str, float]:
    """Realised ball dropout on graded decode-window frames ([kickoff, n), label != X), pooled:
    overall missing rate, P(missing | D), P(missing | alive), their ratio (the EFFECTIVE dead_bias),
    and the missing rate on [0, kickoff). Recomputed from the tokens, never read back from a spec.
    NaN where a stratum is empty."""
    def rate(mask: NDArray[np.bool_], where: NDArray[np.bool_]) -> float:
        return float(mask[where].mean()) if where.any() else float("nan")

    window = [(h.nearest_team[h.id.kickoff:] == NO_TEAM, lab[h.id.kickoff:]) for h, lab in zip(halves, labels)]
    missing = np.concatenate([m for m, _ in window])
    lab = np.concatenate([l for _, l in window])
    pre = np.concatenate([h.nearest_team[:h.id.kickoff] == NO_TEAM for h in halves])
    graded = lab != X
    p_dead, p_alive = rate(missing, graded & (lab == D)), rate(missing, graded & (lab != D))
    return {"overall": rate(missing, graded), "p_missing_dead": p_dead, "p_missing_alive": p_alive,
            "ratio": p_dead / p_alive if p_alive > 0 else float("nan"),
            "prekickoff": rate(pre, np.ones(len(pre), dtype=bool))}


def run(models: Mapping[str, Decoder], cases: Sequence[Case], *, bootstrap_n: int = 0) -> pd.DataFrame:
    """One row per (model, case): model, case, then score.Scores.as_row() columns.

    Refuses (raises Flicker, naming the model and case) a prediction whose switch count exceeds 10x
    the GT's segments, instead of grinding through pm.spell_overlaps (O(GT x pred) pure Python) on a
    flicker. Both are counted inside the graded runs only, so the public case's 17-possession window
    is not compared against switches across two whole halves.
    """
    rows = []
    for name, model in models.items():
        for case in cases:
            preds = case.predict(model)
            _refuse_flicker(name, case, preds)
            s = score.evaluate(case.layout, case.gt, preds, bootstrap_n=bootstrap_n)
            rows.append({"model": name, "case": case.name, **s.as_row()})
    return pd.DataFrame(rows)


def _refuse_flicker(name: str, case: Case, preds: Sequence[NDArray[np.int8]]) -> None:
    pred = case.layout.assemble(preds)
    switches = segments = 0
    for start, stop in score.valid_runs(case.gt):
        g, p = case.gt[start:stop], pred[start:stop]
        segments += 1 + int((g[1:] != g[:-1]).sum())
        switches += int((p[1:] != p[:-1]).sum())
    if switches > MAX_SWITCH_RATIO * segments:
        raise Flicker(f"model {name!r} on case {case.name!r}: {switches} switches > "
                      f"{MAX_SWITCH_RATIO} x {segments} GT segments")


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
