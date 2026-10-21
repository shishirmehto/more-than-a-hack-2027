"""Thin shell: parse flags, call one function, print. No logic lives here (boundary-discipline).

    fetch-metrica                         metrica.fetch (add --write-manifest on the very first run)
    fit-dev    --seed S --merge-s M ...   worlds -> bench.fit_dev -> params JSON (+ grid table beside it)
    sweep      --dead-bias 1 3 11 ...     bench.surface over worlds, prints the generator x belief table
    score      --params P [--dev] [--public]   bench.run, prints the table, writes data/derived/runs/<name>.csv
    make-submission --params P --out F    challenge.halves("baseline_raw") -> Decoder.decode -> score.write_submission
                                          reads ONLY committed inputs (baseline_raw.csv + the params JSON):
                                          no RNG, no Metrica on disk, byte-for-byte reproducible
    selfcheck                             selfcheck.run()

fetch-metrica, fit-dev, sweep and score are not wired yet; they print so and exit 2.

Dev outputs go under data/derived/runs/ (gitignored). Never under evaluation/results/: run_evaluation.py
scores every CSV there against the public GT, and a file named baseline_*.csv would be committed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import challenge, score, selfcheck
from .decoder import Decoder

NOT_WIRED = ("fetch-metrica", "fit-dev", "sweep", "score")


def make_submission(params: Path, out: Path) -> Path:
    """The submission path: committed baseline_raw.csv + a params JSON -> a scorer-ready CSV."""
    model = Decoder.load(params)
    preds = [model.decode(h).codes for h in challenge.halves("baseline_raw")]
    return score.write_submission(challenge.layout(), preds, out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m possession", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("make-submission", help="decode BAR-ATH and write the submission CSV")
    make.add_argument("--params", type=Path, required=True)
    make.add_argument("--out", type=Path, required=True)
    sub.add_parser("selfcheck", help="run the invariant checks")
    for name in NOT_WIRED:
        sub.add_parser(name, add_help=False)
    args, extra = parser.parse_known_args(argv)
    if args.command in NOT_WIRED:
        print(f"{args.command}: not implemented yet", file=sys.stderr)
        return 2
    if extra:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")

    if args.command == "make-submission":
        print(make_submission(args.params, args.out))
        return 0
    return selfcheck.run()


if __name__ == "__main__":
    raise SystemExit(main())
