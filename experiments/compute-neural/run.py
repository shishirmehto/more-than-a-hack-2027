"""Matched-update comparison: one network x1800steps versus three networks x600steps."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
os.environ.setdefault('VECLIB_MAXIMUM_THREADS','2')
import dataclasses,hashlib,json,statistics,sys
from pathlib import Path
from datetime import datetime,timezone
import numpy as np

ROOT=Path(__file__).resolve().parents[2];SRC=ROOT/'local/autoresearch-nov17/source'
OUT=ROOT/'local/compute-neural-nov18';OUT.mkdir(exist_ok=True)
os.environ['MTAH_DATA_DIR']=str(ROOT/'data');os.environ['MTAH_TAG_LEAD']='101,178'
sys.path[:0]=[str(SRC),str(ROOT/'experiments/temporal-neural'),str(ROOT/'experiments/quality-neural')]
from possession import bench,metrica,skillcorner,score
from possession.decoder import Decoder
from network import features,mirror,fit,Network
from decoding import predict
from compute import fit_long
import time

FRACTIONS=(.25,.5,.75,1.)
SEEDS=(98117,98118,98119)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name,value):(OUT/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def source(w):return 'skillcorner' if w.startswith('skillcorner') else 'idsse' if w.startswith('idsse') else 'metrica'
plan={'utc_before_results': None, 'question': 'Does three-model averaging beat spending the same total optimizer updates on one network?', 'conditions': ['single600_seed98117', 'single1800_seed98117', 'ensemble_three600_fixedseeds'], 'sensitivity': 'Also run single1800 for seeds98118/98119; report all and mean/range, never pick the best seed.', 'fixed': 'Full eligible external training games, original144000 primary sampled/mirrored rows, same147-64-3 architecture, source/game weighting, batch1024,Adamlr.002,L2.0001,constant LR schedule, decoder transition/quality fallback, tracker-excluded evaluation.', 'intervention': 'Only steps600->1800 for each matched seed. Verify all parameters/scaler match stored600-step model exactly at optimizer step600 before continuing the same Adam states. No early stopping.', 'compute': 'Single1800 and three600 each perform1800 gradient updates x1024 samples. Report measured training time; not an exact FLOP or wall-time match. Ensemble inference remains3x model evaluations.', 'no_PFF': True, 'no_challenge_labels_video': True, 'limitations': 'Previously reused external evaluation, only3training seeds, inherited baseline heads not fully tracker-excluded. This tests fixed optimization duration, not every possible learning-rate schedule. Do not alter frozen PR4 candidate based on these results.'}
plan['utc_before_results']=datetime.now(timezone.utc).isoformat();plan['script_sha256']=sha(__file__);plan['optimizer_sha256']=sha(Path(__file__).with_name('compute.py'))
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
 print('Prepared compute control',world,flush=True)
assert set(transitions)==set(G)
fits=[];rows=[]
for seed in SEEDS:
 for test_source in sorted(set(S)):
  keep=S!=test_source;g,s=G[keep],S[keep];w=np.zeros(keep.sum())
  assert not np.any(S[keep]==test_source)
  for src in sorted(set(s)):
   games=sorted(set(g[s==src]))
   for game in games:
    ix=g==game;w[ix]=1/len(set(s))/len(games)/ix.sum()
  expectedpath=ROOT/f'local/data-size-neural-nov18/seed{seed}-f1-without-{test_source}.npz'
  with np.load(expectedpath) as z:
   expected={k:z[k].copy() for k in ('w1','b1','w2','b2','mean','scale')};transition=z['transition'].copy()
  start=time.perf_counter()
  print('Fit1800',seed,test_source,int(keep.sum()),'rows',flush=True)
  net=fit_long(X[keep],Y[keep],w,expected,seed=seed,steps=1800,log=lambda step,loss:print('Optimization',seed,test_source,step,loss,flush=True))
  seconds=time.perf_counter()-start
  path=OUT/f'seed{seed}-without-{test_source}-1800.npz';np.savez(path,**net.save(),transition=transition)
  fits.append({'seed':seed,'test_source':test_source,'steps':1800,'checkpoint600_exact':True,'training_seconds':seconds,'training_games':sorted(set(g)),'heldout_games':sorted(set(G[S==test_source])),'rows':int(keep.sum()),'weights_sha256':sha(path)})
  save('fits.json',fits)
  for world,cases in worlds.items():
   if source(world)!=test_source:continue
   for case in cases:
    pred=[]
    for h,codes,x in cache[world,case.name]:
     p=.5*(net.prob(x)+net.prob(mirror(x))[:,[1,0,2]])
     pred.append(predict(h,codes,p,transition,'quality_sequence'))
    r=score.evaluate(case.layout,case.gt,pred,bootstrap_n=0)
    rows.append({'seed':seed,'steps':1800,'test_source':test_source,'world':world,'group':bench.group(world),'game':case.name,'spell_f1':r.spell_f1,'macro_f1':r.macro_f1})
  save('rows.json',rows);save('status.json',{'status':'running','fits_complete':len(fits),'fits_planned':9,'no_PFF':True})
prior=json.loads((ROOT/'local/data-size-neural-nov18/rows.json').read_text())
ensemble=json.loads((ROOT/'local/seed-ensemble-nov18/development-rows.json').read_text())
def mean_groups(rs):
 return statistics.mean(statistics.mean(r['spell_f1'] for r in rs if r['group']==g) for g in sorted({r['group'] for r in rs}))
summary=[];paired=[]
for src in sorted(set(S)):
 before=[mean_groups([r for r in prior if r['fraction']==1 and r['seed']==seed and r['test_source']==src]) for seed in SEEDS]
 after=[mean_groups([r for r in rows if r['seed']==seed and r['test_source']==src]) for seed in SEEDS]
 ens=mean_groups([r for r in ensemble if r['model']=='seed_mean' and r['source']==src])
 summary.append({'source':src,'single600_seed98117':before[0],'single1800_seed98117':after[0],'single600_seed_scores':before,'single1800_seed_scores':after,'mean_single600':statistics.mean(before),'mean_single1800':statistics.mean(after),'ensemble_three600':ens,'ensemble_minus_single1800_seed98117':ens-after[0],'ensemble_minus_mean_single1800':ens-statistics.mean(after),'long_minus_short_mean':statistics.mean(after)-statistics.mean(before)})
 games=sorted({r['game'] for r in rows if r['test_source']==src});diff=[]
 for game in games:
  en=statistics.mean(r['spell_f1'] for r in ensemble if r['model']=='seed_mean' and r['source']==src and r['game']==game)
  long=statistics.mean(r['spell_f1'] for r in rows if r['test_source']==src and r['game']==game)
  diff.append(en-long)
 a=np.asarray(diff);rng=np.random.default_rng(77126);boot=rng.choice(a,(50000,len(a)),replace=True).mean(1)
 paired.append({'source':src,'games':len(games),'ensemble_minus_mean_single1800':float(a.mean()),'descriptive_paired_interval':np.quantile(boot,[.025,.975]).tolist(),'limitation':'Game bootstrap conditional on fixed3seeds, reused external data, not fresh-test significance or training-variance proof.'})
save('summary.json',summary);save('paired-comparison.json',paired)
save('status.json',{'status':'complete','fits_complete':len(fits),'rows_scored':len(rows),'checkpoint600_exact_all':all(r['checkpoint600_exact'] for r in fits),'no_PFF':True,'submission_changed':False})
lines=['# Matched-update control:1x1800 versus3x600','', 'Same full data, architecture, optimizer, seed, decoder and evaluation; only training duration changes. Each1800-step run exactly reproduced its frozen600-step checkpoint before continuing Adam. Three seed replications; every result reported, no seed selection.','', '| Held-out tracker | Single600 seed98117 | Single1800 seed98117 | Mean3 singles1800 | Ensemble3x600 |','|---|---:|---:|---:|---:|']
for r in summary:lines.append(f"| {r['source']} | {r['single600_seed98117']:.6f} | {r['single1800_seed98117']:.6f} | {r['mean_single1800']:.6f} | {r['ensemble_three600']:.6f} |")
lines+=['','## Interpretation limits','','This matches total gradient updates, not exact wall time or every possible optimized learning-rate schedule. The ensemble costs about3x model evaluations at inference. Seed means and the predeclared seed98117 contrast are both reported; the best observed seed is not selected. These are reused external tracker results and inherited baseline heads remain fixed. No PFF or challenge-label access, no new submission candidate selected.','', 'Per-game/seed results, training timings and exact checkpoint assertions are in rows.json and fits.json. Descriptive game-paired intervals are in paired-comparison.json.']
(OUT/'REPORT.md').write_text('\n'.join(lines)+'\n');print('COMPUTE_CONTROL_COMPLETE',json.dumps(summary,indent=2),flush=True)
