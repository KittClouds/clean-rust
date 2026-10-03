"""Matched-dose access-arm runner; requires a verified bridge and frozen arm."""
import argparse
import json
import math
import time
from pathlib import Path

from recorder_runner import LANE,BRIDGE,setup,context_pack,new_model
import torch
import evaluate as ev
from objective import prevalences,supervised,renderer_consistency,variance_floor
from runtime import receipt
from audit_release import sha


def main(arm):
    freeze=LANE/'bridge'/'BRIDGE-FROZEN.json'
    if not freeze.exists() or json.loads(freeze.read_text())['status']!='BRIDGE_FROZEN':
        raise ValueError('access arm must follow verified bridge freeze')
    spec=LANE/arm/'SPECIFICATION.json'
    contract=json.loads(spec.read_text())
    if contract['arm']!=arm or contract['bridge_freeze_sha256']!=sha(freeze):
        raise ValueError('prospective architecture contract not bound to bridge')
    for name,digest in contract['source_hashes'].items():
        if sha(Path(__file__).parent/name)!=digest:
            raise ValueError('prospective access source drift')
    if arm=='F':
        disposition=json.loads((LANE/'E'/'DISPOSITION.json').read_text())
        if disposition['survives']:
            raise ValueError('F cannot run after E survival')
    folder=LANE/arm/'run'
    if folder.exists():
        raise ValueError('preserve existing access-arm training identity')
    datasets=setup();tr,dv=datasets['TRAIN'],datasets['DEV']
    torch.manual_seed(0);model=new_model(arm,tr['classes'])
    # Reuse baseline initialization, not the trained bridge. Each family answers
    # an acquisition question at the same supervision/optimizer dose.
    initial=torch.load(BRIDGE/'baseline'/'initialization.pt',weights_only=True)
    missing,unexpected=model.load_state_dict(initial,strict=False)
    if unexpected or any(not n.startswith('organ.') for n in missing):
        raise ValueError('shared bridge initialization mismatch')
    baseline=new_model('bridge',tr['classes']);baseline.load_state_dict(initial)
    test=context_pack(dv,dv['pairs'][:8,0])
    with torch.no_grad():
        base,current=baseline(test),model(test)
        if not torch.equal(base['e'],current['e']):
            raise ValueError('zero residual must preserve initialized bridge e exactly')
    del baseline
    pis=prevalences(tr)
    receipt(folder/'run-start.json',{'arm':arm,'specification_sha256':sha(spec),
        'bridge_freeze_sha256':sha(freeze),'parameters':sum(p.numel() for p in model.parameters()),
        'fixed_buffer_elements':sum(p.numel() for p in model.buffers()),
        'epochs':8,'seed':0,'root_batch':32,'train_prevalences':pis,
        'shared_initialization':'bridge initialization, never trained bridge',
        'initial_residual_equivalence':'exact e equality on eight DEV roots',
        'evaluation_opened':False})
    torch.save({n:x.detach().cpu() for n,x in model.state_dict().items()},folder/'initialization.pt')
    before=ev.evaluate(model,dv);receipt(folder/'initialization.json',before)
    sigma=torch.load(BRIDGE/'baseline'/'sigma0.pt',weights_only=True)
    opt=torch.optim.AdamW(model.parameters(),lr=3e-4,weight_decay=.01)
    batches=math.ceil(len(tr['pairs'])/32)
    schedule=torch.optim.lr_scheduler.CosineAnnealingLR(opt,batches*8)
    started=time.perf_counter();torch.cuda.reset_peak_memory_stats();torch.manual_seed(0)
    for epoch in range(1,9):
        model.train();perm=torch.randperm(len(tr['pairs']));totals={}
        for first in range(0,len(perm),32):
            ix=tr['pairs'][perm[first:first+32]].flatten();H=context_pack(tr,ix)
            out=model(H);terms=supervised(out,tr,ix,H['cand_mask'],pis)
            terms['renderer_pair']=.25*renderer_consistency(out,H['cand_mask'],
                                                           (tr['action'][ix]>=0).cuda())
            terms['variance']=.05*variance_floor(out['s'],sigma)
            loss=sum(terms.values())
            if not torch.isfinite(loss):
                raise ValueError('nonfinite loss: preserve failed access run')
            opt.zero_grad(set_to_none=True);loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1,error_if_nonfinite=True)
            opt.step();schedule.step()
            for n,x in terms.items():
                totals[n]=totals.get(n,0.)+float(x.detach())
        metrics=ev.evaluate(model,dv);path=folder/f'epoch-{epoch}.pt'
        torch.save({n:x.detach().cpu() for n,x in model.state_dict().items()},path)
        receipt(folder/f'epoch-{epoch}.json',{'epoch':epoch,'metrics':metrics,
            'batches':batches,'seconds':time.perf_counter()-started,
            'loss_terms':{n:x/batches for n,x in totals.items()},'checkpoint_sha256':sha(path)})
        print(json.dumps({'arm':arm,'epoch':epoch,'seconds':time.perf_counter()-started}),flush=True)
    final=ev.evaluate(model,dv,ablations=True)
    receipt(folder/'receipt.json',{'status':'ACCESS_TRAINED_RECORDER_PENDING',
        'arm':arm,'fixed_epoch':8,'initialization':before,'trained':final,
        'checkpoint_sha256':sha(folder/'epoch-8.pt'),
        'training_seconds':time.perf_counter()-started,
        'peak_cuda_bytes':torch.cuda.max_memory_allocated(),'evaluation_opened':False})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--arm',choices=['E','F'],required=True)
    main(parser.parse_args().arm)
