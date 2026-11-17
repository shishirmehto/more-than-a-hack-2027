"""Frozen quality-routed neural inference. No external labels or training code runs."""
import dataclasses,hashlib,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'temporal-neural'))
from network import Network,features,mirror
from decoding import predict
from possession.decoder import Decoder,Decoded,_stoppage_fill

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
class FrozenModel:
 def __init__(self,base,network,transition,mode):self.base=base;self.network=network;self.transition=transition;self.mode=mode
 def __getattr__(self,key):return getattr(self.base,key)
 def decode(self,h):
  high=np.isfinite(h.pace_mps)&(h.pace_mps>2.5);persistent=np.zeros(h.n,bool);edges=np.flatnonzero(np.diff(np.r_[False,high,False].astype(np.int8)))
  for lo,hi in zip(edges[::2],edges[1::2]):
   if hi-lo>=50:persistent[lo:hi]=True
  pace=h.pace_mps.copy();pace[high&~persistent]=2.5;codes=self.base.decode(dataclasses.replace(h,pace_mps=pace)).codes;x=features(h,codes);p=.5*(self.network.prob(x)+self.network.prob(mirror(x))[:,[1,0,2]]);out=predict(h,codes,p,self.transition,self.mode)
  if h.restart_rows:out=_stoppage_fill(out,h,h.restart_rows)
  return Decoded(out,None)
def load(source,weights,mode,expected_base_sha=None,expected_weights_sha=None):
 path=Path(source)/'params/tier0_v22_pfffree.json'
 if expected_base_sha:assert sha(path)==expected_base_sha
 if expected_weights_sha:assert sha(weights)==expected_weights_sha
 with np.load(weights) as z:net=Network(z['mean'],z['scale'],{k:z[k] for k in ('w1','b1','w2','b2')});transition=z['transition']
 return FrozenModel(Decoder.load(path).replace(dead_pace_live_mps=2.5),net,transition,mode)
