"""Rebuild every pinned params file through the CLI and compare each CSV's sha256 with its pin: the pins that
verify-possession's make-submission.md lists, plus tier0_v0's. Each build runs through the skill's run.sh, so its
command, output and exit code land in <data dir>/derived/verify/RUN_ID. Exits 1 when any pin differs.
Usage: python experiments/hillclimb-2026-10-24/pins.py RUN_ID"""
import hashlib
import pathlib
import re
import subprocess
import sys

import games

V0 = ("tier0_v0", "c471a9b4fe3255c6ca61b741de0b9755765f623879325ee0fe972e7274623def")
SKILL = pathlib.Path(".claude/skills/verify-possession")

run_id = sys.argv[1]
doc = (SKILL / "features" / "make-submission.md").read_text()
pins = [V0, *re.findall(r"`params/(tier0_[a-z0-9_]+)\.json`[^`]*`([0-9a-f]{64})`", doc)]
evidence = pathlib.Path(games.DATA_DIR) / "derived" / "verify" / run_id
fail = 0
for name, pin in pins:
    out = evidence / f"{name}.csv"
    subprocess.run([str(SKILL / "scripts" / "run.sh"), run_id, f"make-{name}", sys.executable, "-m", "possession",
                    "make-submission", "--params", f"params/{name}.json", "--out", str(out)], stdout=subprocess.DEVNULL)
    have = hashlib.sha256(out.read_bytes()).hexdigest() if out.exists() else "missing"
    fail |= have != pin
    print(f"PIN {'ok  ' if have == pin else 'FAIL'} {name} {have[:16]}" + ("" if have == pin else f" pin {pin[:16]}"))
print(f"pins checked: {len(pins)}, fail={fail}")
sys.exit(fail)
