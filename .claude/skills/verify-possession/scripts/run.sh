#!/usr/bin/env bash
# Usage: run.sh <run-id> <label> <command> [args...]
# Runs one command from the repo root and keeps its proof in <data dir>/derived/verify/<run-id>/:
# <label>.cmd (the command), <label>.out, <label>.err and <label>.exit, plus meta.txt once per run.
# Exits with the command's own exit code.
set -uo pipefail
[ $# -ge 3 ] || { echo "usage: run.sh <run-id> <label> <command> [args...]" >&2; exit 2; }
run_id=$1 label=$2
shift 2
root=$(git rev-parse --show-toplevel) || exit 2
cd "$root" || exit 2
dir="${MTAH_DATA_DIR:-$root/data}/derived/verify/$run_id"
mkdir -p "$dir"
if [ ! -f "$dir/meta.txt" ]; then
	{
		echo "run_id $run_id"
		echo "started $(date -u +%Y-%m-%dT%H:%M:%SZ)"
		echo "head $(git rev-parse HEAD) $(git branch --show-current)"
		echo "dirty_paths $(git status --porcelain | wc -l | tr -d ' ')"
		echo "python $(.venv/bin/python -V 2>&1)"
		echo "MTAH_DATA_DIR ${MTAH_DATA_DIR:-unset}"
	} >"$dir/meta.txt"
fi
printf '%q ' "$@" >"$dir/$label.cmd"
echo >>"$dir/$label.cmd"
"$@" >"$dir/$label.out" 2>"$dir/$label.err"
code=$?
echo "$code" >"$dir/$label.exit"
echo "$label exit=$code -> $dir/$label.{cmd,out,err,exit}"
exit "$code"
