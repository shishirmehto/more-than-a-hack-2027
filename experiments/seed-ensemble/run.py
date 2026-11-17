"""Reduce optimizer variance by ensembling three independently seeded temporal neural networks."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
os.environ.setdefault('VECLIB_MAXIMUM_THREADS','2')
import dataclasses,hashlib,json,statistics,sys
from pathlib import Path
from datetime import datetime,timezone
import numpy as np

ROOT=Path(__file__).resolve().parents[2];SRC=ROOT/'local/autoresearch-nov17/source'
OUT=ROOT/'local/seed-ensemble-nov18';OUT.mkdir(exist_ok=True)
os.environ['MTAH_DATA_DIR']=str(ROOT/'data');os.environ['MTAH_TAG_LEAD']='101,178'
sys.path[:0]=[str(SRC),str(ROOT/'experiments/temporal-neural'),str(ROOT/'experiments/quality-neural')]
from possession import bench,metrica,skillcorner,score
from possession.decoder import Decoder,_stoppage_fill
from network import features,mirror,fit,Network
from decoding import predict

FRACTIONS=(.25,.5,.75,1.)
SEEDS=(98117,98118,98119)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name,value):(OUT/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def source(w):return 'skillcorner' if w.startswith('skillcorner') else 'idsse' if w.startswith('idsse') else 'metrica'
plan={'utc_before_results': None, 'hypothesis': 'Data-size first-seed learning curve gains from25to75percent then plateaus, and seed sensitivity is visible. Average three full-data neural models to reduce optimizer variance and unstable possession boundaries without adding PFF training.', 'models': ['seed_mean', 'seed_geometric', 'seed_median'], 'seeds': [98117, 98118, 98119], 'training': 'Reuse the three full-fraction tracker-excluded fits from data-size ablation. For target train full30 external games with the same600steps per seed, source/game balance; no PFF fitting. Same147-64-3 architecture and quality decoder.', 'selection': 'Incremental to frozen PR3 quality_sequence: each source mean >=0, SkillCorner>=.001, all groups>=-.005; pick greatest equal-source mean improvement. Freeze one before PFF.', 'limitation': 'Adaptive reused validation, baseline inheritance, synthetic masks, extra compute through ensemble; this is a separate experiment from the fixed-compute data-size ablation. No fresh-test significance claim. ExistingPR unchanged.'}
plan['utc_before_results']=datetime.now(timezone.utc).isoformat();plan['script_sha256']=sha(__file__)
assert not (OUT/'plan.json').exists();save('plan.json',plan)
bench.public_case=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Challenge labels forbidden'))
base=Decoder.load(SRC/'params/tier0_v22_pfffree.json').replace(dead_pace_live_mps=2.5)
def baseline(h):
 pace=h.pace_mps.copy();high=np.isfinite(pace)&(pace>2.5);persistent=np.zeros(h.n,bool)
 edges=np.flatnonzero(np.diff(np.r_[False,high,False].astype(np.int8)))
 for lo,hi in zip(edges[::2],edges[1::2]):
  if hi-lo>=50:persistent[lo:hi]=True
 pace[high&~persistent]=2.5
 return base.decode(dataclasses.replace(h,pace_mps=pace)).codes
with np.load(ROOT/'local/quality-neural-nov17/training.npz') as z:
 X,Y,G,S=z['x'],z['y'],z['game'],z['source']
assert len(set(G))==30 and len(X)==144000
skillcorner.MATCHES=tuple(json.loads((ROOT/'local/autoresearch200-nov17/plan.json').read_text())['matches'])
worlds=bench.worlds([metrica.RuleV2()],[],mode='native',source='skillcorner')
for src in ('metrica','idsse'):
 worlds.update(bench.worlds([metrica.RuleV2.parse(r) for r in ('m0','m2')],[1.,2.6,4.],seeds=(2717,),source=src))
worlds={w:[dataclasses.replace(c,halves=tuple(dataclasses.replace(h,restart_rows=()) for h in c.halves)) for c in cs if c.name!='dev_pooled'] for w,cs in worlds.items()}
cache={};transitions={}
for world,cases in worlds.items():
 for case in cases:
  records=[];counts=np.full((3,3),.5)
  for h,gt in zip(case.halves,case.layout.cut(case.gt)):
   codes=baseline(h);x=features(h,codes);records.append((h,codes,x))
   if world.startswith('skillcorner') or world in ('m0_r2.6_s2717','idsse_m0_r2.6_s2717'):
    labels=gt[::5];valid=(labels<3)&(np.arange(len(labels))*5>=h.id.kickoff);both=valid[:-1]&valid[1:]
    np.add.at(counts,(labels[:-1][both],labels[1:][both]),1)
  cache[world,case.name]=records
  if world.startswith('skillcorner') or world in ('m0_r2.6_s2717','idsse_m0_r2.6_s2717'):
   q=counts/counts.sum(1,keepdims=True);per=np.array([1,0,2]);transitions[records[0][0].id.match]=.5*(q+q[per][:,per])
 print('Prepared seed ensemble',world,flush=True)
assert set(transitions)==set(G)
MODES=('seed_mean','seed_geometric','seed_median')
def load_net(path):
 with np.load(path) as z:return Network(z['mean'],z['scale'],{k:z[k] for k in ('w1','b1','w2','b2')}),z['transition'].copy()
def probability(net,x):return .5*(net.prob(x)+net.prob(mirror(x))[:,[1,0,2]])
def combine(probs,mode):
 p=np.stack(probs)
 if mode=='seed_mean':out=p.mean(0)
 elif mode=='seed_geometric':out=np.exp(np.log(np.maximum(p,1e-8)).mean(0))
 else:out=np.median(p,axis=0)
 return out/out.sum(1,keepdims=True)
models={}
for src in sorted(set(S)):
 nets=[]
 for seed in SEEDS:
  path=ROOT/f'local/data-size-neural-nov18/seed{seed}-f1-without-{src}.npz'
  assert path.exists(),path
  net,transition=load_net(path);nets.append(net)
 models[src]=(nets,transition)
rows=[]
for world,cases in worlds.items():
 nets,transition=models[source(world)]
 old,old_transition=load_net(ROOT/f'local/temporal-neural-nov17/without-{source(world)}.npz')
 for case in cases:
  preds={m:[] for m in MODES};refs=[]
  for h,codes,x in cache[world,case.name]:
   p=[probability(net,x) for net in nets]
   refs.append(predict(h,codes,probability(old,x),old_transition,'quality_sequence'))
   for mode in MODES:preds[mode].append(predict(h,codes,combine(p,mode),transition,'quality_sequence'))
  ref=score.evaluate(case.layout,case.gt,refs,bootstrap_n=0)
  for mode in MODES:
   r=score.evaluate(case.layout,case.gt,preds[mode],bootstrap_n=0)
   rows.append({'model':mode,'world':world,'group':bench.group(world),'source':source(world),'game':case.name,'spell_f1':r.spell_f1,'current_neural_spell_f1':ref.spell_f1,'delta':r.spell_f1-ref.spell_f1})
 print('Evaluated seed ensemble',world,flush=True)
save('development-rows.json',rows);summary=[]
for mode in MODES:
 groups={g:statistics.mean(r['delta'] for r in rows if r['model']==mode and r['group']==g) for g in sorted({r['group'] for r in rows})}
 means={s:statistics.mean(v for g,v in groups.items() if (g.startswith(s) if s!='metrica' else not(g.startswith('skillcorner') or g.startswith('idsse')))) for s in ('metrica','skillcorner','idsse')}
 passed=min(means.values())>=0 and means['skillcorner']>=.001 and min(groups.values())>=-.005
 summary.append({'model':mode,'source_mean_deltas':means,'group_deltas':groups,'passes_development':passed})
save('development-summary.json',summary);print('Seed ensemble development',summary,flush=True)
passing=[r for r in summary if r['passes_development']]
if not passing:
 save('status.json',{'status':'development_failed','PFF_read':False,'submission_changed':False});raise SystemExit(0)
best=max(passing,key=lambda r:statistics.mean(r['source_mean_deltas'].values()))['model']
full=[]
for seed in SEEDS:
 if seed==98117:
  net,transition=load_net(ROOT/'local/quality-neural-nov17/frozen-model.npz')
 else:
  w=np.zeros(len(X))
  for src in sorted(set(S)):
   games=sorted(set(G[S==src]))
   for game in games:
    ix=G==game;w[ix]=1/len(set(S))/len(games)/ix.sum()
  net=fit(X,Y,w,seed=seed,steps=600)
  _,transition=load_net(ROOT/'local/quality-neural-nov17/frozen-model.npz')
 np.savez(OUT/f'seed{seed}.npz',**net.save(),transition=transition);full.append(net)
save('selection.json',{'model':best,'seeds':SEEDS,'utc_before_PFF':datetime.now(timezone.utc).isoformat(),'weights_sha256':{f'seed{s}.npz':sha(OUT/f'seed{s}.npz') for s in SEEDS}})
import pickle
sys.path.insert(0,str(SRC/'experiments/hillclimb-2026-10-24'))
import probes
from inference import load
cachepath=ROOT/'local/pff-evaluation-cache';pins=json.loads((cachepath/'pins.json').read_text());assert sha(cachepath/'cases.pkl')==pins['sha256']
for path,digest in pins['source_pins'].items():assert sha(SRC/path)==digest
with (cachepath/'cases.pkl').open('rb') as f:pffworlds=pickle.load(f)
prior=load(SRC,ROOT/'local/quality-neural-nov17/frozen-model.npz','quality_sequence');adapter=probes.Tagged(prior)
control=probes.Tagged(Decoder.load(SRC/'params/tier0_v20.json'));target=[]
for world,cases in pffworlds.items():
 for case in cases:
  pred=[];refs=[]
  for half in case.halves:
   h=adapter.tag(half);codes=baseline(h);x=features(h,codes);p=[probability(net,x) for net in full]
   out=predict(h,codes,combine(p,best),transition,'quality_sequence');ref=predict(h,codes,p[0],transition,'quality_sequence')
   if h.restart_rows:out=_stoppage_fill(out,h,h.restart_rows);ref=_stoppage_fill(ref,h,h.restart_rows)
   pred.append(out);refs.append(ref)
  r=score.evaluate(case.layout,case.gt,pred,bootstrap_n=0);ref=score.evaluate(case.layout,case.gt,refs,bootstrap_n=0)
  v=score.evaluate(case.layout,case.gt,[control.decode(h).codes for h in case.halves],bootstrap_n=0)
  target.append({'world':world,'game':case.name,'spell_f1':r.spell_f1,'current_neural_spell_f1':ref.spell_f1,'v20_spell_f1':v.spell_f1,'delta':r.spell_f1-ref.spell_f1})
 print('Target evaluated',world,flush=True)
save('pff-rows.json',target);results=[]
for world in sorted({r['world'] for r in target}):
 rs=[r for r in target if r['world']==world];assert len(rs)==32
 ref=statistics.mean(r['current_neural_spell_f1'] for r in rs);expected=.5813680133861626 if '_m2_' in world else .52886406892668;assert abs(ref-expected)<1e-12
 delta=np.array([r['delta'] for r in rs]);rng=np.random.default_rng(77125);boot=np.concatenate([rng.choice(delta,(1000,32),replace=True).mean(1) for _ in range(50)])
 results.append({'world':world,'spell_f1':statistics.mean(r['spell_f1'] for r in rs),'current_neural_spell_f1':ref,'delta':float(delta.mean()),'paired_lower':float(np.quantile(boot,.0125)),'games_won':int((delta>0).sum()),'caveat':'Adaptively reused validation; exploratory only'})
save('pff-summary.json',results);save('status.json',{'status':'target_evaluated','PFF_read':True,'submission_changed':False});print('Seed ensemble target',results,flush=True)
