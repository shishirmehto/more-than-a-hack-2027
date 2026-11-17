"""Small deterministic temporal MLP and sequence decoder, NumPy only."""
import numpy as np
LAGS=(-375,-125,-25,0,25,125,375)
BASE_NAMES=('home_token','away_token','no_token','log_nearest','log_margin','log_ball_speed','outside','pace','push','shape','log_return','previous_team','next_team','log_since_seen','log_until_seen','base_home','base_away','base_dead','missing_pace','missing_shape','missing_ball_geometry')
SWAP=((0,1),(15,16));SIGNED=(8,9,11,12)
def features(h,codes):
 n=h.n;i=np.arange(n);tok=h.nearest_team;seen=tok>=0;prev=np.maximum.accumulate(np.where(seen,i,-1));nxt=np.minimum.accumulate(np.where(seen,i,n)[::-1])[::-1]
 ps=np.where(prev>=0,1-2*tok[np.maximum(prev,0)],0);ns=np.where(nxt<n,1-2*tok[np.minimum(nxt,n-1)],0);g=h.geometry
 def finite(a,lo,hi):return np.nan_to_num(np.clip(a,lo,hi),nan=0.,posinf=hi,neginf=lo)
 b=np.column_stack((tok==0,tok==1,~seen,finite(np.log1p(g.nearest_m),0,6),finite(np.log1p(g.margin_m),0,5),finite(np.log1p(g.speed_mps),0,5),finite(g.outside_m,0,10)/10,finite(h.pace_mps,0,8)/8,finite(h.push_mps,-5,5)/5,finite(h.shape_lo,-10,10)/10,finite(np.log1p(h.return_m),0,6)/6,ps,ns,np.log1p(np.minimum(np.where(prev>=0,i-prev,n),1500)/25)/5,np.log1p(np.minimum(np.where(nxt<n,nxt-i,n),1500)/25)/5,codes==0,codes==1,codes==2,~np.isfinite(h.pace_mps),~np.isfinite(h.shape_lo),~np.isfinite(g.nearest_m))).astype(np.float32)
 assert b.shape[1]==len(BASE_NAMES)
 ix=np.arange(0,n,5)
 return np.concatenate([b[np.clip(ix+lag,0,n-1)] for lag in LAGS],axis=1)
def mirror(x):
 out=x.copy();width=len(BASE_NAMES)
 for lag in range(len(LAGS)):
  offset=lag*width
  for a,b in SWAP:out[:,offset+a]=x[:,offset+b];out[:,offset+b]=x[:,offset+a]
  for j in SIGNED:out[:,offset+j]=-x[:,offset+j]
 return out

def loss_grad(x,y,params,l2=1e-4):
 h=np.tanh(x@params['w1']+params['b1']);z=h@params['w2']+params['b2'];z-=z.max(1,keepdims=True);p=np.exp(z);p/=p.sum(1,keepdims=True)
 loss=-np.log(np.maximum(p[np.arange(len(y)),y],1e-12)).mean()+l2*.5*(np.square(params['w1']).sum()+np.square(params['w2']).sum())
 d=p.copy();d[np.arange(len(y)),y]-=1;d/=len(y);dh=(d@params['w2'].T)*(1-h*h)
 grads={'w2':h.T@d+l2*params['w2'],'b2':d.sum(0),'w1':x.T@dh+l2*params['w1'],'b1':dh.sum(0)}
 return float(loss),grads
class Network:
 def __init__(self,mean,scale,params):self.mean=mean;self.scale=scale;self.params=params
 def prob(self,x):
  out=[]
  for i in range(0,len(x),8192):
   h=np.tanh(((x[i:i+8192]-self.mean)/self.scale)@self.params['w1']+self.params['b1']);z=h@self.params['w2']+self.params['b2'];z-=z.max(1,keepdims=True);p=np.exp(z);p/=p.sum(1,keepdims=True);out.append(p)
  return np.concatenate(out)
 def save(self):return {**self.params,'mean':self.mean,'scale':self.scale}
def fit(x,y,weights,seed=98117,steps=600,log=None):
 x=np.asarray(x,np.float32);y=np.asarray(y,np.int64);w=np.asarray(weights,float);w/=w.sum();rng=np.random.default_rng(seed)
 mean=np.average(x,axis=0,weights=w).astype(np.float32);scale=np.sqrt(np.average((x-mean)**2,axis=0,weights=w)).astype(np.float32);scale=np.maximum(scale,.05);x=(x-mean)/scale
 params={'w1':(rng.normal(size=(x.shape[1],64))*np.sqrt(2/(x.shape[1]+64))).astype(np.float32),'b1':np.zeros(64,np.float32),'w2':(rng.normal(size=(64,3))*np.sqrt(2/67)).astype(np.float32),'b2':np.zeros(3,np.float32)}
 m={k:np.zeros_like(v) for k,v in params.items()};v={k:np.zeros_like(a) for k,a in params.items()}
 for step in range(1,steps+1):
  ids=rng.choice(len(y),size=1024,replace=True,p=w);loss,grads=loss_grad(x[ids],y[ids],params)
  for key in params:
   m[key]=.9*m[key]+.1*grads[key];v[key]=.999*v[key]+.001*grads[key]*grads[key];params[key]-=.002*(m[key]/(1-.9**step))/(np.sqrt(v[key]/(1-.999**step))+1e-8)
  if log and step%200==0:log(step,loss)
 return Network(mean,scale,params)
def decode(prob,transition,n,kickoff,baseline=None):
 p=np.clip(prob.astype(float),1e-8,1)
 if baseline is not None:
  q=np.full_like(p,.05);q[np.arange(len(q)),baseline[::5]]=.9;p=np.sqrt(p*q);p/=p.sum(1,keepdims=True)
 emission=.1*np.log(p);emission[np.arange(len(p))*5<kickoff,:]=-1e9;emission[np.arange(len(p))*5<kickoff,2]=0
 a=np.log(np.maximum(transition,1e-8));value=emission[0]-np.log(3);back=np.zeros((len(p),3),np.int8)
 for t in range(1,len(p)):
  scores=value[:,None]+a;back[t]=scores.argmax(0);value=scores.max(0)+emission[t]
 path=np.empty(len(p),np.int8);path[-1]=value.argmax()
 for t in range(len(p)-1,0,-1):path[t-1]=back[t,path[t]]
 out=np.repeat(path,5)[:n];out[:kickoff]=2;return out
