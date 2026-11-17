import argparse,hashlib,json,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
here=Path(__file__).resolve().parent;root=here.parents[1]
for name,expected in json.loads((here/'MANIFEST.json').read_text()).items():
 path=root/name
 if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise SystemExit('Hash mismatch: '+name)
subprocess.run([sys.executable,str(root/'experiments/quality-neural/build_candidate.py'),'--repo',str(root),'--data',str(a.data.resolve()),'--weights',str(here/'frozen-model.npz'),'--selection',str(here/'selection.json'),'--out',str(a.out.resolve())],check=True)
expected='a0c7a8d5cf90786e736936ccaac6ebf37e27afae30adea1733123eb62695ca68'
if hashlib.sha256(a.out.read_bytes()).hexdigest()!=expected:raise SystemExit('CSV differs from frozen reference; do not submit automatically')
print('PASS: packaged files verified; CSV matches frozen reference byte for byte')
