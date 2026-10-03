"""Prospective single-family freeze, only after verified bridge (or E failure)."""
import argparse
import json
import shutil
from pathlib import Path

from flight_panel import BRIDGE
from recorder_runner import LANE
from dataset import load
from response_tools import hard_definitions
from bridge_model import Bridge
from audit_release import sha
from runtime import receipt


def main(arm):
    freeze=LANE/'bridge'/'BRIDGE-FROZEN.json'
    if not freeze.exists():
        raise ValueError('bridge is not frozen')
    if arm=='F' and json.loads((LANE/'E'/'DISPOSITION.json').read_text())['survives']:
        raise ValueError('E survived; do not run F')
    here=Path(__file__).resolve().parent;folder=LANE/arm
    folder.mkdir(exist_ok=False)
    snapshot=folder/'source';snapshot.mkdir()
    # Copy, never rewrite frozen source; all scientific definitions bound before
    # the first arm optimizer step. Same base snapshot remains independently bound.
    for path in here.iterdir():
        if path.is_file() and path.suffix in ('.py','.md','.json'):
            shutil.copy2(path,snapshot/path.name)
    tr=load('TRAIN')
    from access_organs import Structured,Sparse
    model=(Structured(tr['classes']) if arm=='E' else Sparse(tr['classes']))
    base=Bridge(tr['classes'])
    parameters=sum(p.numel() for p in model.parameters())
    rule={'minimum_improved_primary_cells':2,'hard_relative_loss_gain':.05,
        'maximum_hard_loss_regression':.05,'linear_gain':.02,
        'binary_preservation':.02,'core_preservation':.03,'restricted_preservation':.05,
        'endpoint_preservation':.03,'slice_preservation':.03,'renderer_preservation':.02,
        'uncertainty':'2000 paired canonical-root bootstrap samples, seed 20261002; gain CI lower > 0',
        'hard_support':'>=200 roots for proper-loss cell; class supports separately reported',
        'linear_support':'positive and negative canonical roots each >=200',
        'logic':'all gates, not a composite score; no best readout or checkpoint selection'}
    architecture=({'family':'typed gated relational residual','relational_width':64,
        'output_width':32,'q':'inherited action type embedding; named identity preserved by aligned row',
        'r':'observable argument entity projection plus explicit key-role embeddings; four existing positions retained',
        'g':'SUBJECT/TARGET entity-vector pools plus missing/ambiguous match flags',
        'w':'inherited global state 64',
        'interaction':'gated [r*g;r*w], 128->64->32, added to inherited dense candidate-conditioned state',
        'initialization':'zero residual output, exact bridge e at init; shared parameters copied from untrained bridge',
        'unbound_entities':'zero entity vector, retain observable role; never reconstruct from truth',
        'baseline_role_caveat':'baseline already has deterministic positional schema; E makes relations explicitly typed'}
        if arm=='E' else {'family':'sparse nonlinear expansion','width':4096,'active_features':32,
            'random_features':'fixed seed 20261002 projection; ReLU and top-k; trained output only',
            'input':'same c_local, context, public goal/entity-role coordinates; no E organ',
            'initialization':'zero residual output; shared untrained bridge initialization'})
    value={'arm':arm,'status':'PROSPECTIVELY_FROZEN','bridge_freeze_sha256':sha(freeze),
        'architecture':architecture,'parameters':parameters,
        'additional_trainable_parameters':parameters-sum(p.numel() for p in base.parameters()),
        'fixed_buffer_elements':sum(b.numel() for b in model.buffers()),
        'training':'eight epochs, seed0, same TRAIN supervision/normalization/prevalence/losses/AdamW as bridge; fixed epoch8',
        'readouts':'declared linear + 64-hidden-unit MLP panel; four epochs, batch64 roots, seed0, AdamW1e-3',
        'hard_definitions':hard_definitions(tr),'survival_rule':rule,
        'forbidden':['recurrence','stochastic transition','LoRA','IHA','architecture search','E/F combination'],
        'source_hashes':{p.name:sha(p) for p in snapshot.iterdir() if p.is_file()},
        'bank_handoff_sha256':sha(Path('C:/phoenix-target-overgraph/bank-v3-core-20261002-v04/PHASE5-HANDOFF-v02.json')),
        'protected_evaluation_opened':False,'conflict_training_weight':0}
    receipt(folder/'SPECIFICATION.json',value)
    print(json.dumps({'arm':arm,'status':value['status'],'parameters':parameters}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--arm',choices=['E','F'],required=True)
    main(parser.parse_args().arm)
