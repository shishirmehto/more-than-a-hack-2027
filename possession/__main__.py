"""Thin shell: parse flags, call one function, print. No logic lives here (boundary-discipline).

    fetch-metrica [--write-manifest]      metrica.fetch (add --write-manifest on the very first run)
    fit-dev    --seed S --merge-s M ... --dead-bias R ... --out P [grid flags]
                                          worlds -> bench.fit_dev -> params JSON (+ <stem>_grid.csv beside it)
    sweep      --params P --dead-bias 1 3 11 --belief 1 3 11
                                          bench.surface over worlds, prints the generator x belief table
    score      --params P ... [--dev] [--public] [--merge-s M ...] [--dead-bias R ...] [--mode transplant]
                                          bench.run, prints the table, writes data/derived/runs/<name>.csv
    make-submission --params P --out F    challenge.halves("baseline_raw") -> Decoder.decode -> score.write_submission
                                          reads ONLY committed inputs (baseline_raw.csv + the params JSON):
                                          no RNG, no Metrica on disk, byte-for-byte reproducible
    selfcheck                             selfcheck.run()

bench, metrica and selfcheck are imported inside the commands that use them, so make-submission never
loads the dev harness (selfcheck.public_case_predict_equals_submission checks this).

Dev outputs go under data/derived/runs/ (gitignored). Never under evaluation/results/: run_evaluation.py
scores every CSV there against the public GT, and a file named baseline_*.csv would be committed.
"""
from __future__ import annotations

import argparse
import shlex
import sys
import time
from pathlib import Path
from typing import Sequence

import games

from . import challenge, score
from .decoder import Decoder

RUNS_DIR = Path(games.DATA_DIR) / "derived" / "runs"


def make_submission(params: Path, out: Path) -> Path:
    """The submission path: committed baseline_raw.csv + a params JSON -> a scorer-ready CSV."""
    model = Decoder.load(params)
    preds = [model.decode(h).codes for h in challenge.halves("baseline_raw")]
    return score.write_submission(challenge.layout(), preds, out)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="python -m possession", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    make = sub.add_parser("make-submission", help="decode BAR-ATH and write the submission CSV")
    make.add_argument("--params", type=Path, required=True)
    make.add_argument("--out", type=Path, required=True)

    sub.add_parser("selfcheck", help="run the invariant checks")

    fetch = sub.add_parser("fetch-metrica", help="download and verify the Metrica sample data (~183 MB)")
    fetch.add_argument("--write-manifest", action="store_true")
    fetch.add_argument("--data-dir", type=Path, default=None)

    fit = sub.add_parser("fit-dev", help="fit counts on the reference world, grid-search, write params + grid")
    _world_flags(fit, merge_s=(0.0, 2.0), dead_bias=(1.0, 3.0))
    fit.add_argument("--out", type=Path, required=True)
    fit.add_argument("--temper", type=float, nargs="+", default=[0.02, 0.05, 0.1, 0.2])
    fit.add_argument("--poss-mean-s", type=float, nargs="+", default=[4.0, 6.0, 9.0, 13.0])
    fit.add_argument("--dead-mean-s", type=float, nargs="+", default=[6.0, 10.0, 15.0])
    fit.add_argument("--belief", type=float, nargs="+", default=[1.0, 3.0])
    fit.add_argument("--map-temper", type=float, nargs="*", default=[0.1, 0.2, 0.5, 1.0],
                     help="temper axis of the decode_rule='map' sub-grid; give none to skip it")
    fit.add_argument("--map-min-poss-frames", type=int, nargs="+", default=[1, 50])

    sweep = sub.add_parser("sweep", help="generator dead_bias x decoder belief surface on pooled dev")
    _world_flags(sweep, merge_s=(0.0,), dead_bias=(1.0, 3.0, 11.0))
    sweep.add_argument("--params", type=Path, required=True)
    sweep.add_argument("--belief", type=float, nargs="+", default=[1.0, 3.0, 11.0])

    scores = sub.add_parser("score", help="score decoders on dev worlds and/or the public window")
    _world_flags(scores, merge_s=(0.0,), dead_bias=(1.0,))
    scores.add_argument("--params", type=Path, nargs="+", required=True)
    scores.add_argument("--dev", action="store_true")
    scores.add_argument("--public", action="store_true")
    scores.add_argument("--mode", choices=("renewal", "transplant"), default="renewal")
    scores.add_argument("--bootstrap", type=int, default=0)
    scores.add_argument("--name", default=None, help="run file name (default: the params stems)")

    args = parser.parse_args(argv)
    if args.command == "make-submission":
        print(make_submission(args.params, args.out))
        return 0
    if args.command == "selfcheck":
        from . import selfcheck

        return selfcheck.run()
    if args.command == "fetch-metrica":
        from . import metrica

        print(f"{len(metrica.fetch(args.data_dir, write_manifest=args.write_manifest))} files verified")
        return 0
    if args.command == "fit-dev":
        return _fit_dev(args, argv)
    if args.command == "sweep":
        return _sweep(args)
    if args.command == "score":
        if not (args.dev or args.public):
            parser.error("score needs --dev, --public or both")
        return _score(args)
    raise AssertionError(args.command)


def _world_flags(p: argparse.ArgumentParser, *, merge_s: Sequence[float], dead_bias: Sequence[float]) -> None:
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--merge-s", type=float, nargs="+", default=list(merge_s))
    p.add_argument("--dead-bias", type=float, nargs="+", default=list(dead_bias))


def _fit_dev(args: argparse.Namespace, argv: Sequence[str]) -> int:
    from . import bench, metrica

    started = time.perf_counter()
    worlds = bench.worlds(args.merge_s, args.dead_bias, seed=args.seed)
    reference = bench.pooled(bench.dev_cases(bench.DevSpec(seed=args.seed)))
    shared = {"poss_mean_s": args.poss_mean_s, "dead_mean_s": args.dead_mean_s, "belief": args.belief}
    grids = [{"decode_rule": ["marginal"], "temper": args.temper, **shared}]
    if args.map_temper:
        grids.append({"decode_rule": ["map"], "temper": args.map_temper,
                      "min_poss_frames": args.map_min_poss_frames, **shared})
    model, table = bench.fit_dev(worlds, grids, reference=reference, on_row=_print_row)
    seconds = time.perf_counter() - started

    grid_path = args.out.with_name(f"{args.out.stem}_grid.csv")
    table.to_csv(grid_path, index=False, float_format="%.6f", lineterminator="\n")
    model.save(args.out, {
        "command": shlex.join(["python", "-m", "possession", *argv]),
        "fit_reference_world": f"merge_s 0, dead_bias 1, renewal dropout, seed {args.seed}: decoder.fit "
                               "counts on dev_pooled (six Metrica halves)",
        "sweep_worlds": list(worlds),
        "selection": bench.SELECTION,
        "sample_data_commit": metrica.COMMIT,
        "grid_table": grid_path.name,
        "grid_candidates": len(table),
        "sweep_seconds": round(seconds),
        "not_tuned_on": "the public window",
    })
    if Decoder.load(args.out) != model:
        raise AssertionError(f"{args.out} does not load back as the selected decoder")
    print(table.head(10).to_string(index=False))
    print(f"{args.out}\n{grid_path}\n{len(table)} candidates x {len(worlds)} worlds in {seconds:.0f} s")
    return 0


def _print_row(row: dict[str, object]) -> None:
    print(" ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}" for k, v in row.items()), flush=True)


def _sweep(args: argparse.Namespace) -> int:
    from . import bench

    base = Decoder.load(args.params)
    for m in args.merge_s:
        by_rho = {rho: bench.dev_cases(bench.DevSpec(bench.RuleV2(m), bench.DropoutParams(dead_bias=rho), args.seed))
                  for rho in args.dead_bias}
        print(f"merge_s {m:g}")
        print(bench.surface(base, by_rho, args.belief).round(4).to_string())
    return 0


def _score(args: argparse.Namespace) -> int:
    import pandas as pd

    from . import bench

    models = {p.stem: Decoder.load(p) for p in args.params}
    tables = []
    if args.dev:
        for world, cases in bench.worlds(args.merge_s, args.dead_bias, seed=args.seed, mode=args.mode).items():
            tables.append(bench.run(models, cases, bootstrap_n=args.bootstrap).assign(world=world))
    if args.public:
        tables.append(bench.run(models, [bench.public_case()], bootstrap_n=args.bootstrap).assign(world="public"))
    table = pd.concat(tables, ignore_index=True)
    table = table[["world", *[c for c in table.columns if c != "world"]]]
    print(table.round(4).to_string(index=False))
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"{args.name or '+'.join(models)}.csv"
    table.to_csv(out, index=False, lineterminator="\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
