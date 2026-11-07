"""Rerun the freeze.py command recorded in every params file freeze.py wrote, into OUT_DIR, and compare each result
with the committed file, the out path put back. Usage: python experiments/hillclimb-2026-10-24/refreeze.py OUT_DIR"""
import json
import pathlib
import shlex
import subprocess
import sys

out_dir = pathlib.Path(sys.argv[1])
out_dir.mkdir(parents=True, exist_ok=True)
same = 0
for path in sorted(pathlib.Path("params").glob("tier0_v*.json")):
    cmd = json.loads(path.read_text()).get("provenance", {}).get("command", "")
    if "freeze.py" not in cmd:
        continue
    argv = shlex.split(cmd)
    out = out_dir / path.name
    argv[argv.index("--out") + 1] = str(out)
    run = subprocess.run([sys.executable, *argv[1:]], capture_output=True, text=True, env={"PYTHONPATH": "."})
    if run.returncode:
        print(f"ERROR {path.name}: {run.stderr.strip().splitlines()[-1]}")
        continue
    ok = out.read_text().replace(str(out), f"params/{path.name}") == path.read_text()
    same += ok
    print(f"{'same' if ok else 'DIFF'} {path.name}")
print(f"identical {same}")
