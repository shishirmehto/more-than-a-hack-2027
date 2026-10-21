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

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

import games  # single source of truth for match constants (CLAUDE.md); never re-typed here
import evaluation.possession_metrics as pm  # noqa: E402  the ONLY import of pm in the package

from .half import A, D, H, X, Layout, check_codes

assert (pm.H, pm.A, pm.D, pm.X) == (H, A, D, X), "label codes drifted from the scorer"


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
        raise NotImplementedError


def evaluate(layout: Layout, gt: NDArray[np.int8], preds: Sequence[NDArray[np.int8]], *,
             bootstrap_n: int = 0) -> Scores:
    """Score per-half predictions against a scorer-length GT array.

    gt:    int8 [layout.n_total] in {0..3}; graded spans are its non-X runs (pm.valid_runs).
    preds: one int8 [block.n] per block, values in {0,1,2}. Abstention (X) inside play is not
           offered: the decoder never emits it; X exists only outside blocks, added here.

    Works for the 17-possession public window (gt has one run inside half 1; predictions outside it
    are ignored by pm) and for pooled Metrica dev layouts (six runs) alike.
    """
    # TODO: pred = layout.assemble(preds)            # also range-checks
    # TODO: check_codes(gt, allow_x=True); assert len(gt) == layout.n_total
    # TODO: r = pm.evaluate(gt, pred, bootstrap_n=bootstrap_n); return Scores(...) from r:
    #       spell_f1 <- r["spell_f1_mean"], f1_* <- r["per_class"][k]["f1"],
    #       trans12/25 <- r["transitions"][12|25]["f1"], spell_ci <- (r["spell_bootstrap_low"], ...)
    raise NotImplementedError


def matched_flags(layout: Layout, gt: NDArray[np.int8], preds: Sequence[NDArray[np.int8]]) -> NDArray[np.bool_]:
    """bool [len(pm.SPELL_IOUS), n_gt_spells]: True where a GT possession is matched at that IoU.

    Same greedy one-to-one matching pm uses (pm.possession_spells -> spell_overlaps -> matched_gt_flags),
    returned per GT spell instead of as counts. The building block for bench.paired_delta, which pm
    does not provide. Predictions are filled (pm.fill_abstentions) first, as pm.evaluate does.
    """
    raise NotImplementedError


def read_codes(path: str | Path, n_expected: int | None = None) -> NDArray[np.int8]:
    """frame,label CSV -> int8 codes, via pm.read_label_csv + pm.validate_submission + pm.label_codes.

    The boundary for every CSV the package reads (public GT, baseline_raw.csv): raises ValueError
    with pm's one-line reason when invalid. Never returns a half-valid array.
    """
    raise NotImplementedError


def write_submission(layout: Layout, preds: Sequence[NDArray[np.int8]], path: str | Path) -> Path:
    """Assemble, validate with pm.validate_submission, then write `frame,label` to `path`.

    Byte-for-byte reproducibility lives here: header `frame,label`, one `{i},{L}` line per row, LF
    newlines written explicitly (no platform newline translation, no pandas to_csv), labels from
    "HADX"[code]. Writes to `path` via a temp file in the same directory and an atomic rename, so a
    crash never leaves a half file that run_evaluation.py would score. Refuses a path whose file
    name matches baseline_*.csv (those are committed) or *_possession_gt*.
    """
    # TODO: codes = layout.assemble(preds); assert layout.n_total == games.source_frames("tactical")
    # TODO: lines = ["frame,label\n"] + [f"{i},{'HADX'[c]}\n" ...] (vectorised join); tmp -> rename
    raise NotImplementedError
