"""Build a research CSV from frozen PFF-free neural weights, without reading labels/video."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2');os.environ.setdefault('VECLIB_MAXIMUM_THREADS','2')
import argparse,hashlib,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--data',type=Path,required=True);p.add_argument('--weights',type=Path,required=True);p.add_argument('--selection',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args();os.environ['MTAH_DATA_DIR']=str(args.data.resolve());sys.path.insert(0,str(args.repo.resolve()))
from possession import challenge,score
from inference import load
selection=json.loads(args.selection.read_text());plan_path=args.selection.with_name('plan.json');plan=json.loads(plan_path.read_text()) if plan_path.exists() else {};model=load(args.repo,args.weights,selection['model'],expected_base_sha=plan.get('base_sha256'),expected_weights_sha=selection['weights_sha256']);pred=[model.decode(h).codes for h in challenge.halves_for(model)];args.out.parent.mkdir(parents=True,exist_ok=True);score.write_submission(challenge.layout(),pred,args.out)
print(json.dumps({'csv':str(args.out),'sha256':hashlib.sha256(args.out.read_bytes()).hexdigest(),'rows':len(score.read_codes(args.out)),'scope':'Frozen research candidate only; no match labels/video used'}))
