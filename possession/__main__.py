"""Thin shell: parse flags, call one function, print. No logic lives here (boundary-discipline)."""
from __future__ import annotations

import argparse
import dataclasses
import itertools
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
    """baseline_raw.csv carries the tokens only; an emission that reads ball geometry decodes the halves
    observed from the gated ATD instead (the same tokens, selfcheck atd_reproduces_baseline_raw)."""
    model = Decoder.load(params)
    source = "atd" if model.needs_geometry else "baseline_raw"
    preds = [model.decode(h).codes for h in challenge.halves(source)]
    return score.write_submission(challenge.layout(), preds, out)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="python -m possession",
        description="Label BAR-ATH possession per frame, and select and score decoders on Metrica dev worlds.")
    sub = parser.add_subparsers(dest="command", required=True)

    make = sub.add_parser("make-submission", help="decode BAR-ATH and write the submission CSV")
    make.add_argument("--params", type=Path, required=True)
    make.add_argument("--out", type=Path, required=True)

    sub.add_parser("selfcheck", help="run the invariant checks")

    sub.add_parser("measure", help="print match-wide aggregates of the real BAR-ATH ball mask and Smart Tagging, "
                                   "and decoder constants counted on the Metrica labels; writes nothing")

    fetch = sub.add_parser("fetch-metrica", help="download and verify the Metrica sample data (~183 MB)")
    fetch.add_argument("--write-manifest", action="store_true")
    fetch.add_argument("--data-dir", type=Path, default=None)

    fit = sub.add_parser("fit-dev", help="grid-search decoders on dev worlds, write params + grid")
    _world_flags(fit, rule=("m0", "m2"), dead_bias="the measured bracket, dropout.CALIBRATION.dead_bias_bracket")
    fit.add_argument("--out", type=Path, required=True)
    fit.add_argument("--temper", type=float, nargs="+", default=[0.02, 0.05, 0.1, 0.2])
    fit.add_argument("--poss-mean-s", type=float, nargs="+", default=[4.0, 6.0, 9.0, 13.0])
    fit.add_argument("--dead-mean-s", type=float, nargs="+", default=[6.0, 10.0, 15.0])
    fit.add_argument("--belief", type=float, nargs="+", default=[1.0, 3.0],
                     help="the decoder's dead_bias axis (--dead-bias is the generator's)")
    fit.add_argument("--q", type=float, nargs="+", default=[0.78])
    fit.add_argument("--p-dead-after-poss", type=float, nargs="+", default=[0.25])
    fit.add_argument("--p-flip-after-dead", type=float, nargs="+", default=[0.7])
    fit.add_argument("--map-temper", type=float, nargs="*", default=[0.1, 0.2, 0.5, 1.0],
                     help="temper axis of the decode_rule='map' sub-grid; give none to skip it")
    fit.add_argument("--map-min-poss-frames", type=int, nargs="+", default=[1, 50])
    fit.add_argument("--dead-min-run", type=int, nargs="+", default=[0],
                     help="missing-run dead-ball rule, frames (0 keeps the chain's D); see DecoderParams")
    fit.add_argument("--dead-trim", type=int, nargs="+", default=[0])
    fit.add_argument("--dead-close", type=int, nargs="+", default=[0],
                     help="close stretches of team calls shorter than this between dead runs (0 = off)")
    fit.add_argument("--dead-outside-m", type=float, nargs="+", default=[0.0],
                     help="with --dead-min-run, a ball seen this far outside the pitch counts as missing (0 off)")
    fit.add_argument("--reference-window", type=int, default=None, metavar="WINDOW",
                     help="select by the worst group margin over baseline_smooth<WINDOW> (bench.SELECTION_MARGIN) "
                          "instead of the worst raw world score")

    sweep = sub.add_parser("sweep", help="generator dead_bias x decoder belief surface on pooled dev")
    _world_flags(sweep, rule=("m0",), dead_bias="the bracket and the measured point, dropout.CALIBRATION.surface")
    sweep.add_argument("--params", type=Path, required=True)
    sweep.add_argument("--belief", type=float, nargs="+", default=None,
                       help="decoder dead_bias beliefs (default: the generator worlds)")

    scores = sub.add_parser("score", help="score decoders on dev worlds and/or the public window")
    _world_flags(scores, rule=("m0",), dead_bias="the measured point, dropout.CALIBRATION.dead_bias")
    scores.add_argument("--params", type=Path, nargs="+", required=True)
    scores.add_argument("--baseline", type=int, nargs="+", default=[], metavar="WINDOW",
                        help="also score starter/baseline.py's majority vote at these half-widths in frames, "
                             "named baseline_smooth<WINDOW> (0 is baseline_raw)")
    scores.add_argument("--dev", action="store_true")
    scores.add_argument("--public", action="store_true")
    scores.add_argument("--mode", choices=("renewal", "transplant", "native"), default="renewal",
                        help="how dev balls go missing: renewal dropout at each --dead-bias, a transplant of the "
                             "real BAR-ATH mask (ignores --dead-bias), or native, where the tracker did not see "
                             "the ball (--source pff or skillcorner; ignores --dead-bias and --seed)")
    scores.add_argument("--bootstrap", type=int, default=0)
    scores.add_argument("--objective", type=int, default=None, metavar="WINDOW",
                        help="also print each model's seed-mean dev_pooled margin over baseline_smooth<WINDOW> per "
                             "group (a world without its seed), with the min over groups first")
    scores.add_argument("--paired", action="store_true",
                        help="paired bootstrap spellF1 delta of each later model against the first --params, "
                             "on every dev_pooled and public case")
    scores.add_argument("--name", default=None, help="run file name (default: the params stems)")

    args = parser.parse_args(argv)
    if args.command == "make-submission":
        print(make_submission(args.params, args.out))
        return 0
    if args.command == "selfcheck":
        from . import selfcheck

        return selfcheck.run()
    if args.command == "measure":
        from . import measure

        print(measure.report())
        return 0
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
        if min(args.baseline, default=0) < 0:
            parser.error("--baseline windows must be >= 0")
        if args.mode == "native" and args.source not in ("pff", "skillcorner"):
            parser.error("--mode native needs --source pff or skillcorner, the sources with their own ball-visibility flag")
        from . import bench

        names = [p.stem for p in args.params] + [bench.Smoother(w).name for w in dict.fromkeys(args.baseline)]
        if len(set(names)) < len(names):
            parser.error(f"model names must be unique, got {names}")
        if args.paired and len(names) < 2:
            parser.error("--paired needs two or more models (--params and --baseline together)")
        if args.objective is not None and (args.objective not in args.baseline or not args.dev):
            parser.error("--objective WINDOW needs --dev and the same WINDOW in --baseline")
        return _score(args)
    raise AssertionError(args.command)


def _world_flags(p: argparse.ArgumentParser, *, rule: Sequence[str], dead_bias: str) -> None:
    p.add_argument("--seed", type=int, nargs="+", default=[0], help="dropout seeds, one world each")
    p.add_argument("--rule", nargs="+", default=list(rule), metavar="[SOURCE:]KEY[:MODE]",
                   help='label rules by RuleV2.key: "m0" raw, "m2" merges spells under 2 s, '
                        '"h3p3" controlled possession (3 s or 3 passes); "idsse:m0" takes that rule from '
                        'another source than --source, and "pff:m0:native" also another ball-gap mode, so '
                        'one run can mix sources and modes')
    p.add_argument("--dead-bias", type=float, nargs="+", default=None,
                   help=f"generator dead_bias worlds (default: {dead_bias})")
    # bench.SOURCES spelled out: importing bench here would put pandas on make-submission's import path.
    p.add_argument("--source", choices=("metrica", "idsse", "pff", "pffsb", "skillcorner"), default="metrica",
                   help="dev games: the three Metrica samples, the seven IDSSE matches with the DFL feed's own "
                        "labels, the 64 PFF FC World Cup 2022 games with labels from PFF's game events, or the same "
                        "games with StatsBomb's possession teams, or the 20 SkillCorner A-League matches with SkillCorner's possession "
                        "group (IDSSE and PFF take merge rules only, SkillCorner m0 only; files under "
                        "<data dir>/external/idsse, /pff, /statsbomb_wc2022 and /skillcorner)")


def _fit_dev(args: argparse.Namespace, argv: Sequence[str]) -> int:
    from . import bench, dropout, metrica

    started = time.perf_counter()
    rhos = args.dead_bias or list(dropout.CALIBRATION.dead_bias_bracket)
    worlds = bench.dev_worlds(args.rule, rhos, seeds=args.seed, source=args.source)
    shared = {"poss_mean_s": args.poss_mean_s, "dead_mean_s": args.dead_mean_s, "dead_bias": args.belief,
              "q": args.q, "p_dead_after_poss": args.p_dead_after_poss, "p_flip_after_dead": args.p_flip_after_dead,
              "dead_min_run": args.dead_min_run, "dead_trim": args.dead_trim,
              "dead_close": args.dead_close,
              "dead_outside_m": args.dead_outside_m}
    grids = [{"decode_rule": ["marginal"], "temper": args.temper, **shared}]
    if args.map_temper:
        grids.append({"decode_rule": ["map"], "temper": args.map_temper,
                      "min_poss_frames": args.map_min_poss_frames, **shared})
    reference = None if args.reference_window is None else bench.Smoother(args.reference_window)
    model, table = bench.fit_dev(worlds, grids, on_row=_print_row, reference=reference)
    seconds = time.perf_counter() - started

    grid_path = args.out.with_name(f"{args.out.stem}_grid.csv")
    table.to_csv(grid_path, index=False, float_format="%.6f", lineterminator="\n")
    model.save(args.out, {
        "command": shlex.join(["python", "-m", "possession", *argv]),
        "sweep_worlds": list(worlds),
        "selection": bench.SELECTION if reference is None else f"{bench.SELECTION_MARGIN} ({reference.name})",
        **bench.SOURCES[args.source].pin,
        "dropout_calibration": dataclasses.asdict(dropout.CALIBRATION),
        "grid_table": grid_path.name,
        "grid_candidates": len(table),
        "sweep_seconds": round(seconds),
        "public_window": "Selection does not read it. Several grid defaults started from public-window statistics. "
                         "possession/DESIGN.md, Measurements and constant provenance, lists them.",
    })
    print(table.head(10).to_string(index=False))
    print(f"{args.out}\n{grid_path}\n{len(table)} candidates x {len(worlds)} worlds in {seconds:.0f} s")
    return 0


def _print_row(row: dict[str, object]) -> None:
    print(" ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}" for k, v in row.items()), flush=True)


def _sweep(args: argparse.Namespace) -> int:
    from . import bench, dropout, metrica

    base = Decoder.load(args.params)
    rhos = list(dict.fromkeys(args.dead_bias or dropout.CALIBRATION.surface))
    for rule, seed in itertools.product([metrica.RuleV2.parse(key) for key in args.rule], args.seed):
        by_rho = dict(zip(rhos, bench.worlds([rule], rhos, seeds=[seed], source=args.source).values()))
        print(f"rule {rule.key} seed {seed}")
        print(bench.surface(base, by_rho, args.belief or rhos).round(4).to_string())
    return 0


def _score(args: argparse.Namespace) -> int:
    import pandas as pd

    from . import bench, dropout, metrica

    models: dict[str, bench.Model] = {p.stem: Decoder.load(p) for p in args.params}
    models.update({s.name: s for s in map(bench.Smoother, dict.fromkeys(args.baseline))})
    rhos = args.dead_bias or [dropout.CALIBRATION.dead_bias]
    worlds = bench.dev_worlds(args.rule, rhos, seeds=args.seed, mode=args.mode, source=args.source) if args.dev else {}
    if args.public:
        worlds["public"] = [bench.public_case()]
    table = pd.concat([bench.run(models, cases, bootstrap_n=args.bootstrap).assign(world=world)
                       for world, cases in worlds.items()], ignore_index=True)
    table = table[["world", *[c for c in table.columns if c != "world"]]]
    print(table.round(4).to_string(index=False))
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"{args.name or '+'.join(models)}.csv"
    table.to_csv(out, index=False, lineterminator="\n")
    print(out)
    if args.objective is not None:
        print(f"seed-mean dev_pooled spellF1 margin over {bench.Smoother(args.objective).name} per group")
        print(bench.objective(table, bench.Smoother(args.objective).name).round(4).to_string())
    if args.paired:
        (first, reference), *others = models.items()
        rows = []
        for world, cases in worlds.items():
            for case in (c for c in cases if c.name in ("dev_pooled", "public")):
                for name, model in others:
                    delta, low, high = bench.paired_delta(model, reference, case)
                    rows.append({"world": world, "case": case.name, "model": name, "minus": first,
                                 "delta": delta, "low": low, "high": high})
        print("paired spellF1 delta, 5th / 95th percentile of the bootstrap over shared GT possessions")
        print(pd.DataFrame(rows).round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
