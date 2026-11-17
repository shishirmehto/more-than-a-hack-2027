"""Compare frozen export implementation against research computation, no metric calculation."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2');os.environ.setdefault('VECLIB_MAXIMUM_THREADS','2')
import dataclasses,hashlib,json,pickle,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];SRC=ROOT/'local/autoresearch-nov17/source';os.environ['MTAH_DATA_DIR']=str(ROOT/'data');os.environ['MTAH_TAG_LEAD']='101,178';sys.path[:0]=[str(SRC),str(SRC/'experiments/hillclimb-2026-10-24')]
from possession.decoder import Decoder,_stoppage_fill
from inference import load
from network import features,mirror
from decoding import predict
import probes
cache=ROOT/'local/pff-evaluation-cache';pins=json.loads((cache/'pins.json').read_text());assert hashlib.sha256((cache/'cases.pkl').read_bytes()).hexdigest()==pins['sha256']
with (cache/'cases.pkl').open('rb') as f:worlds=pickle.load(f)
half=next(iter(worlds.values()))[0].halves[0];weights=ROOT/'local/quality-neural-nov17/frozen-model.npz';checks=[]
for mode in ('quality_sequence','quality_rule_sequence'):
 exported=load(SRC,weights,mode);h=probes.Tagged(exported).tag(half);pace=h.pace_mps.copy();high=np.isfinite(pace)&(pace>2.5);sustained=np.zeros(h.n,bool);edges=np.flatnonzero(np.diff(np.r_[False,high,False].astype(np.int8)))
 for lo,hi in zip(edges[::2],edges[1::2]):
  if hi-lo>=50:sustained[lo:hi]=True
 pace[high&~sustained]=2.5;base=Decoder.load(SRC/'params/tier0_v22_pfffree.json').replace(dead_pace_live_mps=2.5);codes=base.decode(dataclasses.replace(h,pace_mps=pace)).codes;x=features(h,codes);p=.5*(exported.network.prob(x)+exported.network.prob(mirror(x))[:,[1,0,2]]);expected=predict(h,codes,p,exported.transition,mode)
 if h.restart_rows:expected=_stoppage_fill(expected,h,h.restart_rows)
 actual=exported.decode(h).codes;assert np.array_equal(actual,expected);checks.append({'mode':mode,'half':str(h.id),'frames':h.n,'exact_codes_match':True})
path=ROOT/'local/quality-neural-nov17/inference-parity.json';path.write_text(json.dumps({'checks':checks,'no_metric_calculated':True,'weights_sha256':hashlib.sha256(weights.read_bytes()).hexdigest()},indent=2)+'\n');print('Frozen export exactly matches research inference for both modes')
