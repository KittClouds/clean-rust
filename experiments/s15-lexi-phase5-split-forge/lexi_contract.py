import os,sys
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
from pathlib import Path
from adapter import *
import torch

BASE=Path('C:/code land/clean-rust/experiments/ff-s15-semantic-graft-phase0-02')
RECURRENT=BASE.parent/'ff-s15-semantic-graft-phase4a-causal-01'
PREPARED=Path('C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v01')
MODEL=Path('C:/phoenix-target-overgraph/lexi-h2-rebuild-20260930/inputs/lfm2.5-230m-base-9d2be55')
sys.path.insert(0,str(BASE));sys.path.insert(0,str(RECURRENT));sys.path.insert(0,str(PREPARED/'code'))
from graft.model import SemanticEpistemicGraft
from recurrent import RecurrentCausalGraft
from stochastic_transition import StochasticCausalGraft,match_mean_initialization

def configure():
    torch.set_num_threads(4);torch.manual_seed(20261002)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    torch.backends.cuda.enable_flash_sdp(False);torch.backends.cuda.enable_mem_efficient_sdp(False)

def new_bridge():
    config=read(BASE/'config.json');config['use_entity_local']=False
    model=SemanticEpistemicGraft(config)
    model.action_type=torch.nn.Embedding(len(VOCAB),config['action_embedding_dim'],padding_idx=0)
    return model

def freeze():
    if (OUT/'PHASE5-SPEC.json').exists():raise ValueError('Training contract already frozen')
    adapter=read(OUT/'ADAPTER-RECEIPT.json')
    required={'config.json':'f7d0bcc454b7a30fa471b1e7b9e359e11fb25b56f5b4ffd59bb18248e3c2ea3d',
      'tokenizer.json':'df1d8d5ec5d091b460562ffd545e4a5e91d17d4a0db7ebe733be34ed374377bd',
      'model.safetensors':'e91eb22c0aeae0bcbea8ade56f5cfe3cf91bca0c34e859adacae8f4445416fe6'}
    for n,h in required.items():
        if sha(MODEL/n)!=h:raise ValueError('Substrate identity mismatch '+n)
    spec={'lane':'LEXI_LFM230M','release_identity':adapter['release_identity'],
      'handoff_sha256':adapter['handoff_sha256'],'adapter_sha256':sha(OUT/'ADAPTER-RECEIPT.json'),
      'model_path':str(MODEL),'model_hashes':required,'backbone_frozen':True,
      'surface':'final_plus_mean; final nonpadding token concatenated mask-weighted final-layer mean, including specials',
      'extraction':{'dtype':'FP32','batch_size':4,'truncation':False,'max_length':2048,'padding':'right','special_tokens':True},
      'architecture':'earned Phase0 causal graft family, s/e=64, h=128; ten-entry action embedding (PAD+nine v3 types); four type-specific argument slots',
      'role_schema':adapter['role_schema'],'candidate_cap':171,'candidate_truncation':0,
      'arms':['BRIDGE','A_DETERMINISTIC','B_STOCHASTIC'],'iterations':4,'B_operational_trajectories':1,
      'initialization':'fresh Phase0 family seed20261002 for bridge; A/B mean organ identical initialization; bridge frozen for A/B',
      'objective':'S + E + .5A + .25 prediction-JS pair + .05 variance floor; source groups averaged; M binary/count alias one source; balanced binary weights TRAIN only; CF unavailable',
      'count_contract':'SmoothL1 raw missing cardinality, nearest nonnegative integer runtime; no invented categorical JS for count head; binary missingness participates in pair JS',
      'deep_supervision':'A/B L4+.25*mean(L1,L2,L3)',
      'training':{'epochs_per_arm':20,'batch_rows':64,'batch_unit':'paired canonical roots','optimizer':'AdamW','lr':.001,
        'minimum_lr':.0001,'weight_decay':.0001,'gradient_clip':1.,'selection':'lowest fixed-seed full DEV own objective; earliest tie','seed':20261002},
      'probe_contract':{'families':['linear','Linear64-GELU-Linear'],'epochs':4,'batch_world_rows':64,'loss':'TRAIN-balanced BCE',
        'channels':['goal_satisfied','missing_information_present','candidate_legal','candidate_satisfies_goal'],
        'fits':'initial + trained bridge; original world-level and candidate-state interfaces'},
      'scope':'no new access organ; no EVAL contact; no cross-lane winner; v1 scores historical only',
      'renderer_scope':'V1-V8 shared by TRAIN/DEV; paired prediction stability and per-family scores, no held-renderer claim',
      'primary_axes':['composition_depth','transition_depth'],'candidate_semantics':'preservation coordinates',
      'support_rule':'only MOVE meets 200-root DEV action-type floor; other types support-only',
      'stochastic_diagnostics':'fixed seeds 20261002/3/4, only diagnostic variance, never ensemble/selection',
      'source_hashes':{p.name:sha(p) for p in SOURCE.iterdir() if p.suffix in ['.py','.ps1','.md']},
      'frozen_dependencies':{str(p):sha(p) for p in [BASE/'graft/model.py',BASE/'graft/contracts.py',BASE/'config.json',
        RECURRENT/'recurrent.py',PREPARED/'code/stochastic_transition.py',PREPARED/'PREPARATION-RECEIPT.json']}}
    write(OUT/'PHASE5-SPEC.json',spec)
    return spec

def verify():
    spec=read(OUT/'PHASE5-SPEC.json')
    for n,h in spec['source_hashes'].items():
        if sha(SOURCE/n)!=h:raise ValueError('Frozen source changed '+n)
    for p,h in spec['frozen_dependencies'].items():
        if sha(p)!=h:raise ValueError('Frozen dependency changed '+p)
    for n,h in read(OUT/'ADAPTER-RECEIPT.json')['files'].items():
        if sha(OUT/n)!=h:raise ValueError('Adapter data changed '+n)
    return spec
