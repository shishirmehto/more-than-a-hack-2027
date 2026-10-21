#!/usr/bin/env bash
# Read-only: answers "is this checkout worth driving?" for the possession CLI. Exit 0 = no FAIL.
set -uo pipefail
root=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "FAIL  not inside a git checkout"; exit 1; }
cd "$root" || exit 1
py=.venv/bin/python
fail=0

check() {
	local what=$1; shift
	if "$@" >/dev/null 2>&1; then echo "ok    $what"; else echo "FAIL  $what"; fail=1; fi
}

check "repo root has games.py and possession/" test -f games.py -a -f possession/__main__.py
check ".venv/bin/python is Python 3.11" "$py" -c 'import sys; assert sys.version_info[:2] == (3, 11)'
check "numpy, pandas, scorer and package import" "$py" -c 'import numpy, pandas, possession.score, possession.bench'
for f in evaluation/results/baseline_raw.csv evaluation/gt/BAR-ATH_possession_gt_public.csv \
	params/tier0_v0.json params/tier0_v1.json possession/metrica/manifest.json; do
	check "committed input $f" test -s "$f"
done

echo "info  HEAD $(git rev-parse --short HEAD) on $(git branch --show-current), $(git status --porcelain | wc -l | tr -d ' ') dirty paths"
data_dir=$("$py" -c 'import games; print(games.DATA_DIR)' 2>/dev/null) || data_dir="?"
echo "info  data dir $data_dir (MTAH_DATA_DIR=${MTAH_DATA_DIR:-unset})"
metrica=$("$py" - <<'EOF' 2>/dev/null
import json
import importlib
fetch = importlib.import_module("possession.metrica.fetch")
files = json.load(open("possession/metrica/manifest.json"))["files"]
have = sum((fetch.root() / p.removeprefix("data/")).is_file() for p in files)
print(f"{have}/{len(files)}")
EOF
) || metrica="?"
if [ "$metrica" = "9/9" ]; then
	echo "ok    Metrica sample data $metrica files (dev features available)"
else
	echo "skip  Metrica sample data $metrica files: score --dev, fit-dev, sweep and possession.metrica need fetch-metrica"
fi
exit $fail
