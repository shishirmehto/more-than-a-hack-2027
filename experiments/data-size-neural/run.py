"""Fixed-compute learning curve: change only the external training-game subset."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
os.environ.setdefault('VECLIB_MAXIMUM_THREADS','2')
import dataclasses,hashlib,json,statistics,sys
from pathlib import Path
from datetime import datetime,timezone
import numpy as np

ROOT=Path(__file__).resolve().parents[2];SRC=ROOT/'local/autoresearch-nov17/source'
OUT=ROOT/'local/data-size-neural-nov18';OUT.mkdir(exist_ok=True)
os.environ['MTAH_DATA_DIR']=str(ROOT/'data');os.environ['MTAH_TAG_LEAD']='101,178'
sys.path[:0]=[str(SRC),str(ROOT/'experiments/temporal-neural'),str(ROOT/'experiments/quality-neural')]
from possession import bench,metrica,skillcorner,score
from possession.decoder import Decoder
from network import features,mirror,fit,Network
from decoding import predict

FRACTIONS=(.25,.5,.75,1.)
SEEDS=(98117,98118,98119)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name,value):(OUT/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def source(w):return 'skillcorner' if w.startswith('skillcorner') else 'idsse' if w.startswith('idsse') else 'metrica'
plan={'utc_before_results':datetime.now(timezone.utc).isoformat(),'script_sha256':sha(__file__),
 'question':'Does scaling the number of independent external training games improve quality_sequence at fixed architecture, optimizer and compute?',
 'fractions':FRACTIONS,'seeds':SEEDS,'heldout_trackers':['metrica','skillcorner','idsse'],
 'fixed':'147 inputs,64 tanh units,3 outputs; same primary-frame samples per game and mirror augmentation; source/game balanced sampling; Adam600 steps,batch1024,lr.002,L2.0001; identical quality fallback and untempered Viterbi algorithm. Same training seed across fractions within a block.',
 'intervention':'Nested deterministic per-source game subsets at ceil(fraction*available games). Fit normalization, neural weights and transition probabilities using only the chosen games. Reset model for every size/seed/tracker. Evaluation games and masks identical for every fit.',
 'outcome':'SpellF1 per held-out game and visibility group; source means average visibility-group means equally. Three seed blocks measure training/subset sensitivity, not three independent test sets.',
 'no_PFF':True,'no_challenge_labels_video':True,'limitations':'Fixed compute, not equal epochs or best achievable score at each size. Unequal source sizes cause rounded realized fractions; held-out training counts differ. Inherited v22 heads remain fixed and saw Metrica/IDSSE; ablation scales new neural/scaler/transition training only. External evaluation was reused. No new model selected or published automatically.'}
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
 print('Prepared learning curve',world,flush=True)
assert set(transitions)==set(G)
fits=[];rows=[]
for seed in SEEDS:
 order={}
 for src in sorted(set(S)):
  rng=np.random.default_rng(seed+int(hashlib.sha256(src.encode()).hexdigest()[:6],16))
  order[src]=rng.permutation(sorted(set(G[S==src]))).tolist()
 previous={src:set() for src in sorted(set(S))}
 for fraction in FRACTIONS:
  chosen={src:games[:max(1,int(np.ceil(len(games)*fraction)))] for src,games in order.items()}
  for src in chosen:
   assert previous[src]<=set(chosen[src]);previous[src]=set(chosen[src])
  for test_source in sorted(set(S)):
   selected=[g for src,games in chosen.items() if src!=test_source for g in games]
   keep=np.isin(G,selected);assert not np.any(S[keep]==test_source)
   g,s=G[keep],S[keep];w=np.zeros(keep.sum())
   for src in sorted(set(s)):
    games=sorted(set(g[s==src]))
    for game in games:
     ix=g==game;w[ix]=1/len(set(s))/len(games)/ix.sum()
   print('Fit curve',seed,fraction,test_source,len(selected),'games',keep.sum(),'rows',flush=True)
   net=fit(X[keep],Y[keep],w,seed=seed,steps=600)
   transition=np.mean([np.mean([transitions[game] for game in chosen[src]],axis=0) for src in sorted(chosen) if src!=test_source],axis=0)
   transition/=transition.sum(1,keepdims=True)
   name=f'seed{seed}-f{fraction:g}-without-{test_source}.npz';np.savez(OUT/name,**net.save(),transition=transition)
   fits.append({'seed':seed,'fraction':fraction,'test_source':test_source,'training_games':sorted(selected),'games_by_source':{src:len(gs) for src,gs in chosen.items() if src!=test_source},'rows':int(keep.sum()),'heldout_games':sorted(set(G[S==test_source])),'weights_sha256':sha(OUT/name)})
   save('fits.json',fits)
   for world,cases in worlds.items():
    if source(world)!=test_source:continue
    for case in cases:
     pred=[]
     for h,codes,x in cache[world,case.name]:
      p=.5*(net.prob(x)+net.prob(mirror(x))[:,[1,0,2]])
      pred.append(predict(h,codes,p,transition,'quality_sequence'))
     r=score.evaluate(case.layout,case.gt,pred,bootstrap_n=0)
     rows.append({'seed':seed,'fraction':fraction,'test_source':test_source,'world':world,'group':bench.group(world),'game':case.name,'training_games':len(selected),'training_rows':int(keep.sum()),'spell_f1':r.spell_f1,'macro_f1':r.macro_f1})
   save('rows.json',rows)
   save('status.json',{'status':'running','fits_complete':len(fits),'fits_planned':len(SEEDS)*len(FRACTIONS)*len(set(S)),'last_fit':name,'no_PFF':True})
summary=[]
for fraction in FRACTIONS:
 for src in sorted(set(S)):
  values=[]
  for seed in SEEDS:
   rs=[r for r in rows if r['fraction']==fraction and r['test_source']==src and r['seed']==seed]
   groups={g:statistics.mean(r['spell_f1'] for r in rs if r['group']==g) for g in sorted({r['group'] for r in rs})}
   values.append(statistics.mean(groups.values()))
  summary.append({'fraction':fraction,'test_source':src,'mean_spell_f1':statistics.mean(values),'seed_scores':values,'seed_min':min(values),'seed_max':max(values)})
save('summary.json',summary);save('status.json',{'status':'complete','fits_complete':len(fits),'rows_scored':len(rows),'no_PFF':True,'submission_changed':False})
lines=['# Data-size ablation','', 'Only the number of training games changes within each seed block. New scaler, network and transition parameters are refitted on that subset. Architecture,600 optimizer steps,decoder algorithm,evaluation games and visibility variants are fixed. Three seeds; no PFF access.','', '| Fraction | Held-out tracker | Mean spellF1 | Seed min | Seed max |','|---|---|---:|---:|---:|']
for r in summary:lines.append(f"| {r['fraction']:.0%} | {r['test_source']} | {r['mean_spell_f1']:.6f} | {r['seed_min']:.6f} | {r['seed_max']:.6f} |")
lines+=['','This is a fixed-compute learning curve, not a guarantee that more data helps. Rounded source counts and actual games/rows are recorded in fits.json. Seed spread measures training sensitivity; it is not a fresh-test confidence interval. Inherited v22 heads are fixed rather than retrained; only new-component training data scales.']
(OUT/'REPORT.md').write_text('\n'.join(lines)+'\n');print(json.dumps(summary,indent=2),flush=True)
