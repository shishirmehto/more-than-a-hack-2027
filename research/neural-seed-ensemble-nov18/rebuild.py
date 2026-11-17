from pathlib import Path
import argparse,hashlib,json,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
folder=Path(__file__).resolve().parent;root=folder.parents[1]
for name,digest in json.loads((folder/'MANIFEST.json').read_text()).items():
 if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:raise SystemExit('Hash mismatch: '+name)
subprocess.run([sys.executable,str(root/'experiments/seed-ensemble/build_candidate.py'),'--repo',str(root),'--data',str(a.data.resolve()),'--artifacts',str(folder),'--out',str(a.out.resolve())],check=True)
if hashlib.sha256(a.out.read_bytes()).hexdigest()!='c21c56cd76c1da343613c2c5367f60ad6a47d671395b6425dcd5117ec83bac03':raise SystemExit('CSV differs from frozen reference; do not submit automatically')
print('PASS: packaged files verified; ensemble CSV matches frozen reference byte for byte')
