from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

import games
import evaluation.possession_metrics as pm

from .half import A, D, H, X, Layout, check_codes

if (pm.H, pm.A, pm.D, pm.X) != (H, A, D, X):
    raise ImportError("label codes drifted from the scorer")

REFUSED_NAMES = ("baseline_*.csv", "*_possession_gt*")


@dataclass(frozen=True, slots=True)
class Scores:
    """Flat, DataFrame-ready subset of pm.evaluate."""
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
    spell_ci: tuple[float, float] | None = None

    def as_row(self) -> dict[str, float | int | None]:
        """Flat dict in field order, with spell_ci split into spell_lo / spell_hi at the end."""
        row = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "spell_ci"}
        row["spell_lo"], row["spell_hi"] = self.spell_ci if self.spell_ci is not None else (None, None)
        return row


def _assemble_checked(layout: Layout, gt: NDArray[np.int8],
                      preds: Sequence[NDArray[np.int8]]) -> NDArray[np.int8]:
    check_codes(gt, allow_x=True)
    if len(gt) != layout.n_total:
        raise ValueError(f"gt has {len(gt)} rows, layout {layout.n_total}")
    return _assemble_preds(layout, preds)


def _assemble_preds(layout: Layout, preds: Sequence[NDArray[np.int8]]) -> NDArray[np.int8]:
    for p in preds:
        check_codes(p, allow_x=False)
    return layout.assemble(preds)


def evaluate(layout: Layout, gt: NDArray[np.int8], preds: Sequence[NDArray[np.int8]], *,
             bootstrap_n: int = 0) -> Scores:
    """Score per-half predictions against a scorer-length GT array.

    gt:    int8 [layout.n_total] in {0..3}; graded spans are its non-X runs (pm.valid_runs).
    preds: one int8 [block.n] per block, values in {0,1,2}.
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


def spell_f1(layout: Layout, gt: NDArray[np.int8], preds: Sequence[NDArray[np.int8]],
             runs: Sequence[tuple[int, int]]) -> tuple[float, int]:
    """(spell_f1, n_pred_spells) exactly as `evaluate` reports them, without the rest of pm.evaluate.
    runs = valid_runs(gt), computed once per gt by the caller."""
    pred = _assemble_checked(layout, gt, preds)
    s = pm.spell_scores(gt, pm.fill_abstentions(pred, runs), runs)
    return s["mean_f1"], s["n_pred"]


def valid_runs(gt: NDArray[np.int8]) -> list[tuple[int, int]]:
    """pm.valid_runs: half-open [start, stop) spans where gt is not X."""
    check_codes(gt, allow_x=True)
    return pm.valid_runs(gt)


def segments(codes: NDArray[np.int8], runs: Sequence[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """pm.segments: (start, stop, code) of each constant-label run, encoded inside each run separately."""
    check_codes(codes, allow_x=True)
    return pm.segments(codes, runs)


def possession_spells(codes: NDArray[np.int8], runs: Sequence[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """pm.possession_spells: the segments whose code is H or A, the possessions the metric counts."""
    check_codes(codes, allow_x=True)
    return pm.possession_spells(codes, runs)


def transitions(codes: NDArray[np.int8], runs: Sequence[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """pm.transitions: (frame, from_code, to_code) of each label change inside a run."""
    check_codes(codes, allow_x=True)
    return pm.transitions(codes, runs)


def matched_flags(layout: Layout, gt: NDArray[np.int8],
                  preds: Sequence[NDArray[np.int8]]) -> tuple[NDArray[np.bool_], int]:
    """(flags, n_pred_spells). flags: bool [len(pm.SPELL_IOUS), n_gt_spells], True where a GT
    possession is matched at that IoU.

    Same greedy one-to-one matching pm uses (pm.possession_spells -> spell_overlaps -> matched_gt_flags),
    returned per GT spell instead of as counts. Predictions are filled (pm.fill_abstentions) first,
    as pm.evaluate does.
    """
    pred = _assemble_checked(layout, gt, preds)
    runs = pm.valid_runs(gt)
    filled = pm.fill_abstentions(pred, runs)
    gt_spells, pred_spells = pm.possession_spells(gt, runs), pm.possession_spells(filled, runs)
    overlaps = pm.spell_overlaps(gt_spells, pred_spells)
    flags = np.vstack([pm.matched_gt_flags(overlaps, len(gt_spells), iou) for iou in pm.SPELL_IOUS])
    return flags, len(pred_spells)


def read_codes(path: str | Path, n_expected: int | None = None) -> NDArray[np.int8]:
    """frame,label CSV -> int8 codes, via pm.read_label_csv + pm.validate_submission + pm.label_codes.

    Raises ValueError with pm's one-line reason when invalid. Never returns a half-valid array.
    n_expected None accepts the file's own row count (frames must still be 0..n-1 in order).
    """
    table = pm.read_label_csv(path)
    reason = pm.validate_submission(table, len(table) if n_expected is None else n_expected)
    if reason:
        raise ValueError(f"{path}: {reason}")
    return pm.label_codes(table)


def write_submission(layout: Layout, preds: Sequence[NDArray[np.int8]], path: str | Path) -> Path:
    """Assemble (range-checked), then write `frame,label` to `path`.

    Writes to `path` via a temp file in the same directory and an atomic rename, so a crash never
    leaves a half file that run_evaluation.py would score. Before the rename the temp file is read
    back through read_codes, which runs pm.validate_submission on the written bytes. Refuses a path
    whose file name matches baseline_*.csv or *_possession_gt*.
    """
    path = Path(path)
    for pattern in REFUSED_NAMES:
        if fnmatch.fnmatch(path.name, pattern):
            raise ValueError(f"refusing to write {path.name}: matches {pattern!r}")
    n = games.source_frames("tactical")
    if layout.n_total != n:
        raise ValueError(f"layout has {layout.n_total} rows, the submission needs {n}")
    codes = _assemble_preds(layout, preds)
    letters = np.array(pm.LABELS)[codes]

    text = "frame,label\n" + "".join(f"{i},{c}\n" for i, c in enumerate(letters.tolist()))
    tmp = path.with_name(f".{path.name}.tmp")  # not *.csv, so run_evaluation.py never globs it
    try:
        with open(tmp, "wb") as f:
            f.write(text.encode("ascii"))
        if not np.array_equal(read_codes(tmp, n), codes):
            raise ValueError(f"{tmp} does not read back as the assembled codes")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    return path
