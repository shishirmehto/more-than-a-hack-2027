"""Same optimizer as frozen baseline, with an exact600-step checkpoint assertion."""
import numpy as np
from network import Network,loss_grad
def fit_long(x,y,weights,expected600,seed=98117,steps=1800,log=None):
 x=np.asarray(x,np.float32);y=np.asarray(y,np.int64);w=np.asarray(weights,float);w/=w.sum();rng=np.random.default_rng(seed)
 mean=np.average(x,axis=0,weights=w).astype(np.float32);scale=np.sqrt(np.average((x-mean)**2,axis=0,weights=w)).astype(np.float32);scale=np.maximum(scale,.05);x=(x-mean)/scale
 params={'w1':(rng.normal(size=(x.shape[1],64))*np.sqrt(2/(x.shape[1]+64))).astype(np.float32),'b1':np.zeros(64,np.float32),'w2':(rng.normal(size=(64,3))*np.sqrt(2/67)).astype(np.float32),'b2':np.zeros(3,np.float32)}
 m={k:np.zeros_like(v) for k,v in params.items()};v={k:np.zeros_like(a) for k,a in params.items()}
 for step in range(1,steps+1):
  ids=rng.choice(len(y),size=1024,replace=True,p=w);loss,grads=loss_grad(x[ids],y[ids],params)
  for key in params:
   m[key]=.9*m[key]+.1*grads[key];v[key]=.999*v[key]+.001*grads[key]*grads[key];params[key]-=.002*(m[key]/(1-.9**step))/(np.sqrt(v[key]/(1-.999**step))+1e-8)
  if step==600:
   state={**params,'mean':mean,'scale':scale}
   for key,value in state.items():
    assert np.array_equal(value,expected600[key]),('600-step checkpoint mismatch',seed,key)
   if log:log('checkpoint600_exact',True)
  if log and step%200==0:log(step,loss)
 return Network(mean,scale,params)
