"""Phase6E create-only artifacts and immutable inherited inputs."""
import sys,json,hashlib,time
from pathlib import Path
import torch
HERE=Path(__file__).resolve().parent
OUT=Path('C:/phoenix-target-overgraph/frizz-phase6e-raw-legality-20261002-v01')
C6=Path('C:/phoenix-target-overgraph/frizz-phase6c-consequence-20261002-v01')
D6=Path('C:/phoenix-target-overgraph/frizz-phase6d-legality-20261002-v01')
P6=Path('C:/phoenix-target-overgraph/frizz-phase6a-comparison-20261002-v01')
P5=Path('C:/phoenix-target-overgraph/frizz-phase5-access-20261002-v01')
BRIDGE=Path('C:/phoenix-target-overgraph/frizz-qwen-v3-bridge-20261002-v02')
BANK=Path('C:/phoenix-target-overgraph/bank-v3-core-20261002-v04')
MODEL=Path('D:/codex-runs/s15-lepori-qwen-0.8b-base-v01/models/Qwen3.5-0.8B-Base')
sys.path.insert(0,str(P5/'E/source'))
from dataset import load as dataset_load
from adapter import rows
from response_tools import paired_interval
sys.path.insert(0,str(D6/'source-v02'))
from legal_metrics import legality,rank
sys.path.insert(0,'C:/code land/clean-rust/experiments/ff-s15-bank-02/src')
from bank2 import algebra as A

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(4194304),b''):h.update(b)
    return h.hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def receipt(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(v,f,sort_keys=True,indent=2,allow_nan=False)
def save(p,v):
    if p.exists():raise ValueError('preserve '+str(p))
    torch.save(v,p);receipt(p.with_suffix('.json'),{'sha256':sha(p)})
def load(p):
    m=read(p.with_suffix('.json'))
    if sha(p)!=m.get('sha256',m.get('output_sha256')):raise ValueError('hash drift '+str(p))
    return torch.load(p,mmap=True,weights_only=False)
def setup():
    torch.set_num_threads(4);torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
def lock():
    s=read(OUT/'RAW-SPECIFICATION.json')
    for n,h in s['sources'].items():
        if sha(HERE/n)!=h:raise ValueError('source drift '+n)
    for n,h in s['inputs'].items():
        if sha(n)!=h:raise ValueError('input drift '+n)
    return s
def endpoint(abi):
    t=load(P6/'DEV-targets.pt')
    return {k:t[k][abi['root_indices']] for k in ('selected','selected_eligible','optimal','optimal_eligible')}
