"""Frozen three-seed mean ensemble; no fitting or external labels at inference."""
from pathlib import Path
import dataclasses,hashlib,json,sys
import numpy as np
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'temporal-neural'),str(Path(__file__).resolve().parents[1]/'quality-neural')]
from network import Network,features,mirror
from decoding import predict
from possession.decoder import Decoder,Decoded,_stoppage_fill

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
class Ensemble:
 def __init__(self,base,nets,transition):self.base=base;self.nets=nets;self.transition=transition
 def __getattr__(self,k):return getattr(self.base,k)
 def decode(self,h):
  high=np.isfinite(h.pace_mps)&(h.pace_mps>2.5);persistent=np.zeros(h.n,bool)
  edges=np.flatnonzero(np.diff(np.r_[False,high,False].astype(np.int8)))
  for lo,hi in zip(edges[::2],edges[1::2]):
   if hi-lo>=50:persistent[lo:hi]=True
  pace=h.pace_mps.copy();pace[high&~persistent]=2.5
  codes=self.base.decode(dataclasses.replace(h,pace_mps=pace)).codes;x=features(h,codes)
  probabilities=[.5*(net.prob(x)+net.prob(mirror(x))[:,[1,0,2]]) for net in self.nets]
  p=np.stack(probabilities).mean(0);p/=p.sum(1,keepdims=True)
  out=predict(h,codes,p,self.transition,'quality_sequence')
  if h.restart_rows:out=_stoppage_fill(out,h,h.restart_rows)
  return Decoded(out,None)

def load(source,artifacts):
 folder=Path(artifacts);selection=json.loads((folder/'selection.json').read_text());assert selection['model']=='seed_mean'
 nets=[];transition=None
 for seed in selection['seeds']:
  path=folder/f'seed{seed}.npz';assert sha(path)==selection['weights_sha256'][path.name]
  with np.load(path) as z:
   nets.append(Network(z['mean'],z['scale'],{k:z[k] for k in ('w1','b1','w2','b2')}))
   if transition is None:transition=z['transition'].copy()
   else:assert np.array_equal(transition,z['transition'])
 return Ensemble(Decoder.load(Path(source)/'params/tier0_v22_pfffree.json').replace(dead_pace_live_mps=2.5),nets,transition)
