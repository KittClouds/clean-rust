"""Frozen-state Phase 6A: no backbone extraction and no protected reader."""
import hashlib,json,os,sys,time
from pathlib import Path
import numpy as np
import torch

HERE=Path(__file__).resolve().parent
P5_SOURCE=HERE.parent/'s15-lexi-phase5-split-forge-v03'
P5=Path('C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v03')
P5_FINAL=P5.parent/'lexi-phase5-split-forge-20261002-v05'
OUT=P5.parent/'lexi-phase6a-candidate-decision-20261002-v01'
sys.path.insert(0,str(P5_SOURCE))
from lexi_contract import new_bridge,configure,RecurrentCausalGraft,verify as verify_parent
VOCAB=('MOVE','TAKE','DROP','ACTIVATE','DEACTIVATE','OPEN','CLOSE','WAIT','TRANSFER')
SEED=20261002

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,value,replace=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w' if replace else 'x',encoding='utf-8') as stream:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')

def freeze():
    path=OUT/'SPEC.json'
    if path.exists():return verify()
    verify_parent()
    parent=read(P5_FINAL/'V05-FINAL-STATUS.json')
    if parent['status']!='SEALED_AND_INDEPENDENTLY_REPLAYED':raise ValueError('Parent not replayed')
    contract={
      'question':'Localize action type / within-type ranking / cross-type comparison / production optimization / recurrence residual',
      'parent_phase5_seal':parent['v05_seal_identity'],'parent_phase5_spec':sha(P5/'PHASE5-SPEC.json'),
      'population':'Full BANK-v3-core TRAIN/DEV identity; supervised diagnostic fitting/scoring only canonical selected/optimal-eligible roots; empty-set support retained',
      'protected_contact':False,'depths':[0,1,2,3,4],'states':'Frozen BRIDGE T0 and A deterministic T1-T4, projected s/e; weights unchanged',
      'cache':'Compact sourceable rows preserving exact canonical ids, every candidate and adjacent renderer pairs; existing T0/T4 cache parity and saved production prediction parity',
      'heads':{'families':['linear','tiny_MLP'],'MLP_hidden':64,
         'first_action_type_input':'[s_t; masked mean of e_j,t] (128D), one nine-class output',
         'selected_candidate_input':'e_j,t (64D), scalar per candidate',
         'optimal_membership_input':'e_j,t (64D), scalar binary logit per candidate'},
      'normalization':'TRAIN valid candidate states for candidate heads, TRAIN eligible rows for type head; per coordinate mean/std; no DEV statistics',
      'optimization':{'epochs':20,'batch_rows':64,'batch_unit':'32 paired roots','optimizer':'AdamW','lr':.001,'weight_decay':.0001,'seed':SEED,'checkpoint':'fixed final epoch20; no DEV selection'},
      'losses':{'type':'TRAIN inverse-frequency class-balanced CE over nine types',
         'selected':'masked listwise selected-candidate CE, one row contribution',
         'membership':'TRAIN-prevalence balanced binary CE over valid candidates on optimum-eligible roots'},
      'ranking':'Canonical candidate ordinal breaks score ties; learned-type exclusion or empty predicted subset gets MRR/hits zero, no oracle fallback',
      'factorizations':['gold type restriction','learned type restriction','unrestricted'],
      'candidate_count_bins':[[1,16],[17,32],[33,64],[65,96],[97,128],[129,171]],
      'followup_rule':'Family linear before tiny_MLP, earliest depth T0..T4: selected diagnostic top1 gain >=.05 vs same-depth production and root-paired bootstrap95 lower>0. If earned, train one independent fresh scorer from seed20261007 for20 epochs with same selected CE/TRAIN normalizer, frozen states; no second attempt.',
      'repair_meaning':'Dedicated head-only listwise optimization over frozen e, not a novel loss: original production already used candidate CE jointly with semantic objectives',
      'support_floor_roots':200,'bootstrap':'2000 paired-root draws, fixed seed; DEV engineering intervals',
      'source_hashes':{p.name:sha(p) for p in HERE.glob('*.py')},
      'checkpoint_hashes':{name:sha(P5/'models'/name/'best.pt') for name in ['BRIDGE','A_DETERMINISTIC']}}
    write(path,contract);return contract

def verify():
    spec=read(OUT/'SPEC.json')
    for name,digest in spec['source_hashes'].items():
        if sha(HERE/name)!=digest:raise ValueError('Frozen Phase6 source changed '+name)
    for name,digest in spec['checkpoint_hashes'].items():
        if sha(P5/'models'/name/'best.pt')!=digest:raise ValueError('Frozen checkpoint changed '+name)
    return spec

def load_split(split):
    if split not in ('TRAIN','DEV'):raise ValueError('Only TRAIN/DEV are allowed')
    folder=P5/'data'/split
    arrays={key:np.load(folder/(key+'.npy'),mmap_mode='r') for key in ['H','A','mask','action','optimal']}
    meta=read(folder/'metadata.json');selected=arrays['action'];ids=np.flatnonzero(selected>=0)
    if len(ids)%2 or any(meta[ids[i]]['root']!=meta[ids[i+1]]['root'] for i in range(0,len(ids),2)):
        raise ValueError('Sourceable rows not paired')
    for row in ids:
        a=int(selected[row]);typ=int(arrays['A'][row,a,0])-1
        if VOCAB[typ]!=meta[row]['action_type'] or not meta[row]['optimal_eligible'] or not arrays['optimal'][row,a]:
            raise ValueError('Selected/type/optimum canonical source mismatch')
    eligible=np.array([m['optimal_eligible'] for m in meta])
    if not np.array_equal(eligible,selected>=0):raise ValueError('Different optimum/selected populations require separate masks')
    return arrays,meta,ids

def cached(split,depth):
    if split not in ('TRAIN','DEV') or depth not in range(5):raise ValueError('Invalid frozen-state address')
    folder=OUT/'cache'/split
    return {key:np.load(folder/(f'T{depth}-{key}.npy'),mmap_mode='r') for key in ['s','e','production']}
