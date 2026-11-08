"""Re-derive the tag-start-to-kick lead behind probes.TAG_LEAD with committed code: for each Smart Tagging restart
tag, the lead is decoder._kick's first ball-speed kick after the tag's start. Prints counts and quartiles only."""
import numpy as np

from possession import challenge
from possession.decoder import _kick

hs = challenge.halves("atd")
leads = {}
for t in challenge.tags():
    if not t.restart:
        continue
    for h, b in zip(hs, challenge.layout().blocks):
        if b.origin <= t.start < b.origin + b.n:
            k = _kick(h, t.start - b.origin)
            leads.setdefault(t.kind, []).append(None if k is None else k - (t.start - b.origin))
groups = {**leads, "throw-in and goal kick": leads.get("throw-in", []) + leads.get("goal kick", []),
          "all restarts": [x for v in leads.values() for x in v]}
for kind, xs in groups.items():
    found = np.array([x for x in xs if x is not None])
    q = [int(v) for v in np.percentile(found, [25, 50, 75]).round()] if len(found) else []
    print(f"{kind}: {len(xs)} tags, {len(found)} with a kick, lead p25/p50/p75 frames {q}")
