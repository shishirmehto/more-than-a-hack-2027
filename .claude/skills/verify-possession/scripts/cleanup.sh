#!/usr/bin/env bash
# Usage: cleanup.sh <run-id>
# Removes only what a verification run named <run-id> left outside its evidence folder: the score
# CSVs written as <data dir>/derived/runs/verify-<run-id>*.csv. Keeps the evidence folder and lists it.
set -uo pipefail
[ $# -eq 1 ] || { echo "usage: cleanup.sh <run-id>" >&2; exit 2; }
run_id=$1
root=$(git rev-parse --show-toplevel) || exit 2
data="${MTAH_DATA_DIR:-$root/data}"
removed=0
for f in "$data"/derived/runs/verify-"$run_id"*.csv; do
	[ -e "$f" ] || continue
	rm -- "$f" && removed=$((removed + 1))
done
echo "removed $removed score file(s) under $data/derived/runs"
dir="$data/derived/verify/$run_id"
if [ -d "$dir" ]; then
	echo "evidence kept in $dir:"
	ls -1 "$dir"
else
	echo "no evidence folder at $dir"
fi
