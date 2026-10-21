"""Possession labeller: sequence decoder + Metrica dev set + evaluation harness.

Run from the repo root so `import games` and `import evaluation.possession_metrics` resolve:

    python -m possession fetch-metrica
    python -m possession fit-dev --seed 0 --out params/tier0_v1.json
    python -m possession make-submission --params params/tier0_v1.json --out evaluation/results/possession_v1.csv

Module map (organised by the knowledge each owns, not by pipeline order):

    half.py       codes, Geometry / Half / CleanHalf, Layout          the shared vocabulary
    score.py      the only importer of evaluation.possession_metrics   scorer adapter, submission I/O
    challenge.py  BAR-ATH: baseline_raw -> Half now, ATD -> Geometry later, the tier-0 token convention
    metrica/      sample data: fetch (pinned), raw parse, label rule v2 -> CleanHalf
    dropout.py    CleanHalf -> Half: block dropout calibrated on the challenge's own mask
    decoder.py    Emission + 4-state chain, forward-backward, fit, params JSON
    bench.py      Cases, run, surface, fit_dev, paired_delta
    selfcheck.py  the invariants as runnable checks
"""
