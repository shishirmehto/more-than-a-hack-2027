"""Compare frozen export with recorded-research inference on both target conventions; no scoring."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
os.environ.setdefault('VECLIB_MAXIMUM_THREADS','2')
import dataclasses,hashlib,json,pickle,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];SRC=ROOT/'local/autoresearch-nov17/source';OUT=ROOT/'local/seed-ensemble-nov18'
os.environ['MTAH_DATA_DIR']=str(ROOT/'data');os.environ['MTAH_TAG_LEAD']='101,178'
sys.path[:0]=[str(SRC),str(SRC/'experiments/hillclimb-2026-10-24')]
from inference import load
from network import features,mirror
from decoding import predict
from possession.decoder import _stoppage_fill
import probes
cache=ROOT/'local/pff-evaluation-cache';pins=json.loads((cache/'pins.json').read_text());assert hashlib.sha256((cache/'cases.pkl').read_bytes()).hexdigest()==pins['sha256']
with (cache/'cases.pkl').open('rb') as f:worlds=pickle.load(f)
model=load(SRC,OUT);checks=[]
for world,cases in worlds.items():
 # One half from each label convention; no metrics or new model selection.
 half=cases[0].halves[0];h=probes.Tagged(model).tag(half)
 high=np.isfinite(h.pace_mps)&(h.pace_mps>2.5);persistent=np.zeros(h.n,bool);edges=np.flatnonzero(np.diff(np.r_[False,high,False].astype(np.int8)))
 for lo,hi in zip(edges[::2],edges[1::2]):
  if hi-lo>=50:persistent[lo:hi]=True
 pace=h.pace_mps.copy();pace[high&~persistent]=2.5
 codes=model.base.decode(dataclasses.replace(h,pace_mps=pace)).codes;x=features(h,codes)
 ps=[.5*(net.prob(x)+net.prob(mirror(x))[:,[1,0,2]]) for net in model.nets]
 p=np.stack(ps).mean(0);p/=p.sum(1,keepdims=True);expected=predict(h,codes,p,model.transition,'quality_sequence')
 if h.restart_rows:expected=_stoppage_fill(expected,h,h.restart_rows)
 actual=model.decode(h).codes;assert np.array_equal(actual,expected)
 checks.append({'world':world,'half':str(h.id),'frames':h.n,'exact_match':True})
(OUT/'inference-parity.json').write_text(json.dumps({'checks':checks,'no_metrics_calculated':True,'scope':'Two convention cases, same underlying physical half; narrow code parity, not additional generalization evidence'},indent=2)+'\n')
print('PASS: ensemble export matches research inference exactly in both convention cases')
