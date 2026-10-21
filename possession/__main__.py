"""Thin shell: parse flags, call one function, print. No logic lives here (boundary-discipline).

    fetch-metrica                         metrica.fetch (add --write-manifest on the very first run)
    fit-dev    --seed S --merge-s M ...   worlds -> bench.fit_dev -> params JSON (+ grid table beside it)
    sweep      --dead-bias 1 3 11 ...     bench.surface over worlds, prints the generator x belief table
    score      --params P [--dev] [--public]   bench.run, prints the table, writes data/derived/runs/<name>.csv
    make-submission --params P --out F    bench.public_case().predict(model) -> score.write_submission
                                          reads ONLY committed inputs (baseline_raw.csv + the params JSON):
                                          no RNG, no Metrica on disk, byte-for-byte reproducible
    selfcheck                             selfcheck.run()

Dev outputs go under data/derived/runs/ (gitignored). Never under evaluation/results/: run_evaluation.py
scores every CSV there against the public GT, and a file named baseline_*.csv would be committed.
"""
from __future__ import annotations

import argparse
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    # TODO: argparse subcommands above; each calls exactly one possession.* function.
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
