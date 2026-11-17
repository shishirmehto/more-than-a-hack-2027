"""Use neural evidence only with available movement/shape; preserve exact fallback."""
import numpy as np

def sequence(prob,transition,n,kickoff,baseline,quality,mix=False,baseline_only=False):
 p=np.clip(prob.astype(float),1e-8,1);q=np.full_like(p,.05);q[np.arange(len(q)),baseline[::5]]=.9
 if baseline_only:p=q
 elif mix:p=np.sqrt(p*q);p/=p.sum(1,keepdims=True)
 emission=np.log(p);bad=~quality[::5];emission[bad]=-1e9;emission[np.flatnonzero(bad),baseline[::5][bad]]=0
 before=np.arange(len(p))*5<kickoff;emission[before]=-1e9;emission[before,2]=0
 a=np.log(np.maximum(transition,1e-8));value=emission[0]-np.log(3);back=np.zeros((len(p),3),np.int8)
 for t in range(1,len(p)):
  scores=value[:,None]+a;back[t]=scores.argmax(0);value=scores.max(0)+emission[t]
 path=np.empty(len(p),np.int8);path[-1]=value.argmax()
 for t in range(len(p)-1,0,-1):path[t-1]=back[t,path[t]]
 out=np.repeat(path,5)[:n];out[~quality]=baseline[~quality];out[:kickoff]=2;return out

def predict(h,codes,p,transition,mode):
 quality=np.isfinite(h.pace_mps)&np.isfinite(h.shape_lo)
 if mode=='quality_argmax':out=np.repeat(p.argmax(1).astype(np.int8),5)[:h.n]
 elif mode=='quality_confident':
  out=codes.copy();pick=np.repeat(p.max(1)>=.8,5)[:h.n]&quality;candidate=np.repeat(p.argmax(1).astype(np.int8),5)[:h.n];out[pick]=candidate[pick]
 else:out=sequence(p,transition,h.n,h.id.kickoff,codes,quality,mix=mode=='quality_rule_sequence',baseline_only=mode=='baseline_sequence_control')
 out[~quality]=codes[~quality];out[:h.id.kickoff]=2;return out
