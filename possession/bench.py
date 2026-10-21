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
  * a "world" is a DevSpec: label rule x dead_bias x dropout seed. The first two are UNKNOWN for the
    real match (label convention; real P(missing | dead)), so no single world is ground truth; the
    seed is noise, and a world axis because it moves the ranking more than paired_delta (one draw,
    GT possessions resampled) can see (DESIGN.md, sweeps 4 and 5);
  * a decoder is scored on every world; the winner maximises the MINIMUM pooled spellF1 across worlds,
    ties broken by the mean (max-min). Measured on a synthetic proxy, a decoder that believes
    dead_bias = 3 scores 0.34 / 0.48 / 0.52 across worlds {1, 3, 11} while one that believes 1
    scores 0.44 / 0.44 / 0.44: belief 1 wins max-min and loses mean;
  * per-game rows are reported next to the pooled row so a win that lives in one game is visible;
  * paired_delta before reading any gap: two decoders on one case share their GT spells, so compare
    on those, not on two unpaired intervals.
Measured here: decoding the six dev halves takes 0.09 s at stride 5 ("map" 0.18-0.42 s) and
pm.evaluate on dev_pooled 0.04-0.12 s, so sweep 1 (288 candidates x 4 worlds, params/tier0_v1.json)
ran in 300 s.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from . import challenge, dropout, metrica, score
from .decoder import Decoder, DecoderParams, Tier0Emission
from .half import D, NO_TEAM, X, CleanHalf, Half, Layout, check_codes
from .dropout import DropoutParams
from .metrica import RuleV2

PUBLIC_GT = Path(__file__).resolve().parents[1] / "evaluation" / "gt" / f"{challenge.GAME}_possession_gt_public.csv"

# bench.run refuses a prediction with more switches than this many times the GT's segments.
MAX_SWITCH_RATIO = 10

SELECTION = ("max over candidates of the min pooled-dev spellF1 across worlds, ties by the mean; "
             "NaN (refused as flicker) in any world disqualifies")

Grid = Mapping[str, Sequence[object]]


class Flicker(ValueError):
    """A prediction refused by run's switch guard before pm.spell_overlaps grinds through it."""


@dataclass(frozen=True, slots=True)
class DevSpec:
    """One dev world. Everything that shapes the dev data, nothing else.

    rule:      label rule: a merge_s rule or a controlled-possession rule, never both (RuleV2.key).
    dropout:   generator (dead_bias axis, target rate, ...).
    seed:      dropout seed; labels are seed-free.
    ball_fill: how native Metrica NaN are replaced before dropout ("hold" | "linear").
    """
    rule: RuleV2 = RuleV2()
    dropout: DropoutParams = DropoutParams()
    seed: int = 0
    ball_fill: Literal["hold", "linear"] = "hold"


@dataclass(frozen=True, slots=True)
class Case:
    """name:   "dev_g1" | "dev_g2" | "dev_g3" | "dev_pooled" | "public".
    layout: where each half sits in the scorer array (synthetic for dev, challenge.layout() for public).
    halves: decoder inputs, in layout order.
    gt:     int8 [layout.n_total] in {0..3}. Derived from labels by Layout.assemble, never stored twice.
    The realised dropout of a case is derived from halves + gt when a table needs it (dropout_stats).
    """
    name: str
    layout: Layout
    halves: tuple[Half, ...]
    gt: NDArray[np.int8]

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

    def predict(self, model: Decoder) -> list[NDArray[np.int8]]:
        """One int8 [block.n] per half: `model.decode(h).codes`. make-submission decodes the same
        halves without a Case; selfcheck.public_case_predict_equals_submission pins the two equal."""
        return [model.decode(h).codes for h in self.halves]


def dev_cases(spec: DevSpec) -> list[Case]:
    """metrica.load -> dropout.challengeify -> per-game and pooled Cases. Requires fetched data.

    Returns [dev_g1, dev_g2, dev_g3, dev_pooled]."""
    clean = metrica.load(spec.rule, ball_fill=spec.ball_fill)
    return _dev_cases(clean, dropout.challengeify(clean, spec.dropout, spec.seed))


def _dev_cases(clean: Sequence[CleanHalf], halves: Sequence[Half]) -> list[Case]:
    by_game: dict[str, list[int]] = {}
    for i, c in enumerate(clean):
        by_game.setdefault(c.id.match, []).append(i)
    groups = [("dev_" + match.removeprefix("metrica_"), idx) for match, idx in by_game.items()]
    groups.append(("dev_pooled", list(range(len(clean)))))
    cases = []
    for name, idx in groups:
        layout = Layout.synthetic([clean[i].geometry.n for i in idx])
        labels = [clean[i].labels for i in idx]
        cases.append(Case(name, layout, tuple(halves[i] for i in idx), layout.assemble(labels)))
    return cases


def public_case(source: Literal["baseline_raw", "atd"] = "baseline_raw") -> Case:
    """BAR-ATH: challenge.halves(source), challenge.layout(), GT = public CSV via score.read_codes
    (evaluation/gt/BAR-ATH_possession_gt_public.csv; real labels only on rows [11185, 18685)).
    make-submission decodes the same two halves without building this case."""
    layout = challenge.layout()
    return Case("public", layout, tuple(challenge.halves(source)), score.read_codes(PUBLIC_GT, layout.n_total))


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


def pooled(cases: Sequence[Case]) -> Case:
    """The world's "dev_pooled" case: the one selection reads."""
    return next(c for c in cases if c.name == "dev_pooled")


def worlds(rules: Sequence[RuleV2], dead_bias: Sequence[float], *, seeds: Sequence[int] = (0,),
           mode: Literal["renewal", "transplant"] = "renewal") -> dict[str, list[Case]]:
    """dev_cases for every (rule, dead_bias, seed), keyed "{rule.key}_r{dead_bias:g}" ("m2_r1"), plus
    "_s{seed}" for a seed other than 0 ("h3p3_r1_s2"), so a seed-0 key reads as it did before seeds
    were an axis. Rule-major, seed innermost. "transplant" ignores dead_bias, so it builds one world
    per (rule, seed), keyed "{rule.key}_transplant[_s{seed}]". Labels load once per rule; dropout is
    drawn per world, because the renewal draw reads the labels."""
    out = {}
    for rule in rules:
        clean = metrica.load(rule)
        generators = ({"transplant": DropoutParams(mode="transplant")} if mode == "transplant"
                      else {f"r{rho:g}": DropoutParams(dead_bias=rho) for rho in dead_bias})
        for generator, params in generators.items():
            for seed in seeds:
                key = f"{rule.key}_{generator}" + (f"_s{seed}" if seed else "")
                out[key] = _dev_cases(clean, dropout.challengeify(clean, params, seed))
    return out


def run(models: Mapping[str, Decoder], cases: Sequence[Case], *, bootstrap_n: int = 0) -> pd.DataFrame:
    """One row per (model, case): model, case, score.Scores.as_row() columns, then the case's
    dropout_stats, so the effective dead_bias a score was measured under sits in the same row.

    Refuses (raises Flicker, naming the model and case) a prediction whose switch count exceeds 10x
    the GT's segments, instead of grinding through pm.spell_overlaps (O(GT x pred) pure Python) on a
    flicker. Both are counted inside the graded runs only, so the public case's 17-possession window
    is not compared against switches across two whole halves.
    """
    stats = [dropout_stats(case.halves, case.layout.cut(case.gt)) for case in cases]
    rows = []
    for name, model in models.items():
        memo: _Memo = {}
        for case, case_stats in zip(cases, stats):
            s = _evaluate(name, model, case, memo, bootstrap_n=bootstrap_n)
            rows.append({"model": name, "case": case.name, **s.as_row(), **case_stats})
    return pd.DataFrame(rows)


# One model's decodes keyed by a half's content (id and tokens, the decoder's whole input while
# Half.features is None), never by world or case name: two worlds share a decode only when their
# draws are byte-identical, which today's merge rule happens to give, not something it promises.
_Memo = dict[tuple[str, bytes], NDArray[np.int8]]


def _predict(name: str, model: Decoder, case: Case, memo: _Memo) -> list[NDArray[np.int8]]:
    """case.predict(model) through `memo`, then the flicker guard (raises Flicker)."""
    preds = []
    for h in case.halves:
        key = (repr(h.id), h.nearest_team.tobytes())
        if key not in memo:
            memo[key] = model.decode(h).codes
        preds.append(memo[key])
    _refuse_flicker(name, case, preds)
    return preds


def _evaluate(name: str, model: Decoder, case: Case, memo: _Memo, *, bootstrap_n: int = 0) -> score.Scores:
    return score.evaluate(case.layout, case.gt, _predict(name, model, case, memo), bootstrap_n=bootstrap_n)


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
    for a column is base.replace(dead_bias=belief).
    The last row is the column's minimum over worlds (the max-min score). This is the lever that
    turns the open question "does the real ATD drop the ball more on dead frames?" into a number per
    decoder choice, until the real ATD can be crossed with Smart Tagging set-piece windows.
    """
    cells = {}
    for belief in beliefs:
        model, memo = base.replace(dead_bias=belief), {}
        cells[belief] = {rho: _evaluate(f"belief {belief:g}", model, pooled(cases), memo).spell_f1
                         for rho, cases in worlds.items()}
    table = pd.DataFrame(cells)
    table.loc["min"] = table.min()
    table.index.name, table.columns.name = "generator dead_bias", "belief"
    return table


def fit_dev(worlds: Mapping[str, Sequence[Case]], grids: Sequence[Grid], *,
            base: Decoder = Decoder(Tier0Emission(), DecoderParams()),
            on_row: Callable[[dict[str, object]], None] | None = None) -> tuple[Decoder, pd.DataFrame]:
    """Every candidate of `grids` scored on every world's dev_pooled case; returns (best by max-min,
    the whole grid table). Nothing is counted from the dev labels: in sweeps 2 and 3 the counted
    transition probabilities lost to hand-set ones (counted p_dead_after_poss 0.44 against 0.25 cost
    ~0.025 spellF1 on the binding world).

    grids:  a union of Cartesian products, one Mapping per sub-grid, so the "marginal" and "map"
            decode rules can sweep different axes in one table. Keys are Decoder.fields() names
            (dead_bias is the decoder's belief); an axis a sub-grid omits keeps `base`'s value.
    base:   the decoder every candidate varies. The default equals params/tier0_v0.json
            (selfcheck.params_load_guards).
    on_row: called with each finished row (progress for long sweeps).
    The table has one row per candidate, ranked by SELECTION (rank 1 = returned decoder); a world on
    which run's flicker guard refused the candidate scores NaN, and NaN anywhere disqualifies. It is
    written next to the params JSON so a reader can see how flat the optimum is."""
    cases = {name: pooled(world) for name, world in worlds.items()}
    runs = {name: score.valid_runs(case.gt) for name, case in cases.items()}
    models, rows = [], []
    for model in _candidates(base, grids):
        memo: _Memo = {}
        spell, n_pred = {}, {}
        for name, case in cases.items():
            try:
                preds = _predict("candidate", model, case, memo)
            except Flicker:
                spell[name], n_pred[name] = float("nan"), -1
                continue
            spell[name], n_pred[name] = score.spell_f1(case.layout, case.gt, preds, runs[name])
        values = np.array(list(spell.values()))
        row = {**model.fields(), **{f"spell_{k}": v for k, v in spell.items()},
               "min": float(values.min()), "mean": float(values.mean()),
               **{f"pred_{k}": v for k, v in n_pred.items()}}
        if on_row is not None:
            on_row(row)
        models.append(model)
        rows.append(row)
    table = pd.DataFrame(rows)
    order = table.sort_values(["min", "mean"], ascending=False, kind="stable", na_position="last").index
    table = table.loc[order].reset_index(drop=True)
    table.insert(0, "rank", np.arange(1, len(table) + 1))
    return models[order[0]], table


def _candidates(base: Decoder, grids: Sequence[Grid]) -> list[Decoder]:
    out = []
    for grid in grids:
        keys = list(grid)
        for values in itertools.product(*(grid[k] for k in keys)):
            out.append(base.replace(**dict(zip(keys, values))))
    return out


def paired_delta(a: Decoder, b: Decoder, case: Case, *, n_draws: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """(delta, low, high): the observed spellF1(a) - spellF1(b) (spell_f1_mean, pm's mean over IoUs)
    and the 5th / 95th percentiles of its bootstrap, resampling the GT possessions both share.

    pm offers no paired comparison; its pieces do (score.matched_flags -> per-IoU hit flags per GT
    spell). Resample GT spells once per draw, apply to both, recompute each F1 with pm's own
    arithmetic (bootstrap_spell_f1: 2tp / (2tp + fp + fn), fp clamped at 0, predicted count fixed).
    5th/95th percentiles, like pm. Use before believing any gap < 0.04.
    """
    flags, n_pred = zip(*(score.matched_flags(case.layout, case.gt, case.predict(model)) for model in (a, b)))
    n_gt = flags[0].shape[1]

    def spell_f1(hits: NDArray[np.bool_], picks: NDArray[np.int64], predicted: int) -> NDArray[np.float64]:
        tp = hits[:, picks].sum(axis=-1)                      # [n_ious, n_draws]
        fp, fn = np.maximum(0, predicted - tp), n_gt - tp
        f1 = np.where(tp > 0, 2.0 * tp / np.maximum(2 * tp + fp + fn, 1), 0.0)
        return f1.mean(axis=0)

    every = np.arange(n_gt)[None, :]
    observed = spell_f1(flags[0], every, n_pred[0]) - spell_f1(flags[1], every, n_pred[1])
    picks = np.random.default_rng(seed).integers(0, n_gt, size=(n_draws, n_gt))
    deltas = spell_f1(flags[0], picks, n_pred[0]) - spell_f1(flags[1], picks, n_pred[1])
    low, high = np.percentile(deltas, (5, 95))
    return float(observed[0]), float(low), float(high)
