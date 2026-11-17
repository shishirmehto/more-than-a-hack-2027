"""Validate frozen ensemble artifacts and rebuild challenge predictions without labels/video."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
os.environ.setdefault('VECLIB_MAXIMUM_THREADS','2')
import argparse,hashlib,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--data',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
os.environ['MTAH_DATA_DIR']=str(a.data.resolve());sys.path.insert(0,str(a.repo.resolve()))
from possession import challenge,score
from inference import load
model=load(a.repo,a.artifacts);pred=[model.decode(h).codes for h in challenge.halves_for(model)]
a.out.parent.mkdir(parents=True,exist_ok=True);score.write_submission(challenge.layout(),pred,a.out)
print(json.dumps({'csv':str(a.out),'sha256':hashlib.sha256(a.out.read_bytes()).hexdigest(),'rows':len(score.read_codes(a.out)),'no_labels_or_video':True}))
