"""Read-only canonical semantics and frozen-state audit identities."""
import sys,json,time,hashlib
from pathlib import Path
import numpy as np
import torch
HERE=Path(__file__).resolve().parent
P6=HERE.parent/'s15-lexi-phase6a-candidate-decision-01'
sys.path.insert(0,str(P6))
import p6_contract as inherited
sys.path.insert(0,str(inherited.P5_SOURCE))
import adapter
sys.path.insert(0,str(HERE.parent/'ff-s15-bank-02'/'src'))
from bank2 import algebra,facts
OUT=Path('C:/phoenix-target-overgraph/lexi-phase6b-within-type-20261002-v01')
PREVIOUS=inherited.OUT
SEED=20261002
NAMES=['legal','immediate_goal','actor_binding','goal_argument_binding','destination_goal_binding',
       'precondition_fraction','negative_clear','effect_goal_add','effect_goal_remove',
       'goal_literal_match_gain','obligation_gain','on_shortest_path']
ENDS=[0,1,2,5,9,11,12]

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8') as f:json.dump(v,f,sort_keys=True,indent=2,allow_nan=False,default=lambda x:x.item() if isinstance(x,np.generic) else (_ for _ in ()).throw(TypeError(type(x).__name__)))

def freeze():
    if (OUT/'SPEC.json').exists():return verify()
    inherited.verify()
    if read(PREVIOUS/'FINAL-STATUS.json')['status']!='SEALED_AND_INDEPENDENTLY_REPLAYED':raise ValueError('Unsealed prior')
    OUT.mkdir(exist_ok=True)
    spec={'question':'Which semantic factors distinguish same-type selected candidates and are accessible in frozen LFM states?',
       'population':'BANK-v3-core TRAIN/DEV only; sourceable eligible roots and their paired renderer states; every candidate retained',
       'gold_only':True,'runtime_gold_inputs_authorized':False,'protected_contact':False,
       'rungs':['type','+legality','+immediate goal','+argument identities and contextual role matches',
         '+precondition/effect signature','+goal/obligation change','+environment shortest-first membership'],
       'G6_boundary':'existing shortest-path membership is endpoint-derived oracle diagnostic, not independent supervision or deployable evidence; no candidate-specific reason source invented',
       'ceiling':'root-local selected signature equivalence class: optimistic target-class reciprocal tie recovery. Not proof of predictable selection; raw identities/effects also reported separately.',
       'gold_recovery':'TRAIN-only exact-signature smoothed membership frequency; fixed scalar linear gold ranking 20epochs; no DEV fitting; root-local ceiling separate',
       'factor_selection':'Probe semantic nonidentity channels through first G1..G5 rung with gold-type linear top1 >=.50; if none, all G1..G5 factors as bounded localization; G6 never earns a mechanism.',
       'probes':'linear and Linear64-GELU-Linear, multitarget BCE for [0,1] factors; TRAIN-only normalization and prevalence balancing; 20epochs fixed; each T0..T4 separate',
       'difference':'selected minus each same-type alternative, both orientations; row/world-batched pair learner and factor-difference regression; no candidate pairs cross worlds',
       'candidate_count_slices':[[1,16],[17,32],[33,64],[65,96],[97,128],[129,171]],
       'source_hashes':{p.name:sha(p) for p in HERE.glob('*.py')},
       'semantic_source_hashes':{str(p):sha(p) for p in [HERE.parent/'ff-s15-bank-02/src/bank2/sim.py',HERE.parent/'ff-s15-bank-02/src/bank2/algebra.py',HERE.parent/'ff-s15-bank-03/core-v04/generation.py']},
       'phase6a_manifest_sha256':sha(PREVIOUS/'MANIFEST.json'),'recurrence_changed':False}
    write(OUT/'SPEC.json',spec);return spec

def verify():
    s=read(OUT/'SPEC.json');inherited.verify()
    for name,digest in s['source_hashes'].items():
        if sha(HERE/name)!=digest:raise ValueError('Audit source changed '+name)
    for name,digest in s['semantic_source_hashes'].items():
        if sha(name)!=digest:raise ValueError('Canonical machinery changed')
    if sha(PREVIOUS/'MANIFEST.json')!=s['phase6a_manifest_sha256']:raise ValueError('Prior manifest changed')
    return s
