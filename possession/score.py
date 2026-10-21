"""The only module that imports the organisers' scorer.

Everything the package knows about `evaluation/possession_metrics.py` is here: import style, the
range guard pm does not do, per-half assembly, the flat Scores row, submission I/O. Callers hand in
a `Layout`, a GT array and per-half int8 predictions and get numbers back; they never see pm's dict.

Import style: the package runs from the repo root (`python -m possession ...`), so `games` and the
`evaluation` namespace package both resolve. This is the one place that spells the import.

Determinism: pm.evaluate(bootstrap_n>0) uses BOOTSTRAP_SEED=0 by default, so bootstrap intervals are
already reproducible. For another seed, call pm.bootstrap_spell_f1 with the filled prediction
(pm.fill_abstentions) from here; nothing else in the package needs to know.
"""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from numpy.typing import NDArray

import games  # single source of truth for match constants (CLAUDE.md); never re-typed here
import evaluation.possession_metrics as pm  # noqa: E402  the ONLY import of pm in the package

from .half import A, D, H, X, Layout, check_codes

if (pm.H, pm.A, pm.D, pm.X) != (H, A, D, X):
    raise ImportError("label codes drifted from the scorer")

REFUSED_NAMES = ("baseline_*.csv", "*_possession_gt*")


@dataclass(frozen=True, slots=True)
class Scores:
    """Flat, DataFrame-ready subset of pm.evaluate. spell_f1 is the ranking metric, macro_f1 breaks ties.

    n_pred_spells / n_gt_spells are the jitter detector: a decoder that flickers shows it here long
    before macro_f1 moves. bench.run refuses to score a prediction with more than 10x the GT spells,
    because pm.spell_overlaps is O(G x P) pure Python.
    """
    spell_f1: float
    macro_f1: float
    n_pred_spells: int
    n_gt_spells: int
    mean_spell_s: float
    gt_mean_spell_s: float
    f1_h: float
    f1_a: float
    f1_d: float
    alive_dead_f1: float
    trans12_f1: float
    trans25_f1: float
    n_graded: int
    spell_ci: tuple[float, float] | None = None  # (low, high) when bootstrap_n > 0

    def as_row(self) -> dict[str, float | int | None]:
        """Flat dict; spell_ci split into spell_lo / spell_hi. Column order is stable."""
        lo, hi = self.spell_ci if self.spell_ci is not None else (None, None)
        return {
            "spell_f1": self.spell_f1, "macro_f1": self.macro_f1,
            "n_pred_spells": self.n_pred_spells, "n_gt_spells": self.n_gt_spells,
            "mean_spell_s": self.mean_spell_s, "gt_mean_spell_s": self.gt_mean_spell_s,
            "f1_h": self.f1_h, "f1_a": self.f1_a, "f1_d": self.f1_d,
            "alive_dead_f1": self.alive_dead_f1,
            "trans12_f1": self.trans12_f1, "trans25_f1": self.trans25_f1,
            "n_graded": self.n_graded, "spell_lo": lo, "spell_hi": hi,
        }


def _assemble_checked(layout: Layout, gt: NDArray[np.int8],
                      preds: Sequence[NDArray[np.int8]]) -> NDArray[np.int8]:
    """The range guard: GT in 0..3 and scorer-length, every prediction in 0..2 (no X inside a half)."""
    check_codes(gt, allow_x=True)
    if len(gt) != layout.n_total:
        raise ValueError(f"gt has {len(gt)} rows, layout {layout.n_total}")
    for p in preds:
        check_codes(p, allow_x=False)
    return layout.assemble(preds)


def evaluate(layout: Layout, gt: NDArray[np.int8], preds: Sequence[NDArray[np.int8]], *,
             bootstrap_n: int = 0) -> Scores:
    """Score per-half predictions against a scorer-length GT array.

    gt:    int8 [layout.n_total] in {0..3}; graded spans are its non-X runs (pm.valid_runs).
    preds: one int8 [block.n] per block, values in {0,1,2}. Abstention (X) inside play is not
           offered: the decoder never emits it; X exists only outside blocks, added here.

    Works for the 17-possession public window (gt has one run inside half 1; predictions outside it
    are ignored by pm) and for pooled Metrica dev layouts (six runs) alike.
    """
    pred = _assemble_checked(layout, gt, preds)
    r = pm.evaluate(gt, pred, bootstrap_n=bootstrap_n)
    ci = None
    if r["spell_bootstrap_low"] is not None:
        ci = (r["spell_bootstrap_low"], r["spell_bootstrap_high"])
    return Scores(
        spell_f1=r["spell_f1_mean"],
        macro_f1=r["macro_f1"],
        n_pred_spells=r["n_pred_spells"],
        n_gt_spells=r["n_gt_spells"],
        mean_spell_s=r["mean_spell_duration_s"],
        gt_mean_spell_s=r["gt_mean_spell_duration_s"],
        f1_h=r["per_class"]["H"]["f1"],
        f1_a=r["per_class"]["A"]["f1"],
        f1_d=r["per_class"]["D"]["f1"],
        alive_dead_f1=r["alive_dead_f1"],
        trans12_f1=r["transitions"][12]["f1"],
        trans25_f1=r["transitions"][25]["f1"],
        n_graded=r["n_graded"],
        spell_ci=ci,
    )


def valid_runs(gt: NDArray[np.int8]) -> list[tuple[int, int]]:
    """pm.valid_runs: half-open [start, stop) spans where gt is not X."""
    check_codes(gt, allow_x=True)
    return pm.valid_runs(gt)


def matched_flags(layout: Layout, gt: NDArray[np.int8], preds: Sequence[NDArray[np.int8]]) -> NDArray[np.bool_]:
    """bool [len(pm.SPELL_IOUS), n_gt_spells]: True where a GT possession is matched at that IoU.

    Same greedy one-to-one matching pm uses (pm.possession_spells -> spell_overlaps -> matched_gt_flags),
    returned per GT spell instead of as counts. The building block for bench.paired_delta, which pm
    does not provide. Predictions are filled (pm.fill_abstentions) first, as pm.evaluate does.
    """
    pred = _assemble_checked(layout, gt, preds)
    runs = pm.valid_runs(gt)
    filled = pm.fill_abstentions(pred, runs)
    gt_spells = pm.possession_spells(gt, runs)
    overlaps = pm.spell_overlaps(gt_spells, pm.possession_spells(filled, runs))
    return np.vstack([pm.matched_gt_flags(overlaps, len(gt_spells), iou) for iou in pm.SPELL_IOUS])


def read_codes(path: str | Path, n_expected: int | None = None) -> NDArray[np.int8]:
    """frame,label CSV -> int8 codes, via pm.read_label_csv + pm.validate_submission + pm.label_codes.

    The boundary for every CSV the package reads (public GT, baseline_raw.csv): raises ValueError
    with pm's one-line reason when invalid. Never returns a half-valid array. n_expected None
    accepts the file's own row count (frames must still be 0..n-1 in order).
    """
    table = pm.read_label_csv(path)
    reason = pm.validate_submission(table, len(table) if n_expected is None else n_expected)
    if reason:
        raise ValueError(f"{path}: {reason}")
    return pm.label_codes(table)


def write_submission(layout: Layout, preds: Sequence[NDArray[np.int8]], path: str | Path) -> Path:
    """Assemble, validate with pm.validate_submission, then write `frame,label` to `path`.

    Byte-for-byte reproducibility lives here: header `frame,label`, one `{i},{L}` line per row, LF
    newlines written explicitly (no platform newline translation, no pandas to_csv), labels from
    "HADX"[code]. Writes to `path` via a temp file in the same directory and an atomic rename, so a
    crash never leaves a half file that run_evaluation.py would score. The temp file is read back
    through read_codes before the rename. Refuses a path whose file name matches baseline_*.csv
    (those are committed) or *_possession_gt*.
    """
    path = Path(path)
    for pattern in REFUSED_NAMES:
        if fnmatch.fnmatch(path.name, pattern):
            raise ValueError(f"refusing to write {path.name}: matches {pattern!r}")
    n = games.source_frames("tactical")
    if layout.n_total != n:
        raise ValueError(f"layout has {layout.n_total} rows, the submission needs {n}")
    for p in preds:
        check_codes(p, allow_x=False)
    codes = layout.assemble(preds)
    letters = np.array(list("HADX"))[codes]
    reason = pm.validate_submission(pd.DataFrame({"frame": np.arange(n), "label": letters}), n)
    if reason:
        raise ValueError(f"assembled submission is invalid: {reason}")

    text = "frame,label\n" + "".join(f"{i},{c}\n" for i, c in enumerate(letters.tolist()))
    tmp = path.with_name(f".{path.name}.tmp")  # not *.csv, so run_evaluation.py never globs it
    with open(tmp, "wb") as f:
        f.write(text.encode("ascii"))
    if not np.array_equal(read_codes(tmp, n), codes):
        raise ValueError(f"{tmp} does not read back as the assembled codes")
    os.replace(tmp, path)
    return path
