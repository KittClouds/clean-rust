"""One eight-epoch dense bridge; fixed endpoint, TRAIN pairs, separate DEV recorder."""
import json
import math
import time
import os

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')

import torch

from bridge_model import Bridge
from dataset import load, pack
from evaluate import evaluate
from objective import prevalences, supervised, renderer_consistency, variance_floor
from runtime import OUT, HERE, receipt, verify_handoff
from audit_release import sha


def main():
    torch.set_num_threads(4)
    torch.manual_seed(0)
    torch.use_deterministic_algorithms(True)
    handoff, handoff_sha = verify_handoff()
    if not (OUT/'datasets-complete.json').exists():
        raise ValueError('datasets incomplete')
    folder=OUT/'baseline'
    if folder.exists():
        raise ValueError('bridge identity already started; no implicit rerun')
    tr,dv=load('TRAIN'),load('DEV')
    for d in (tr,dv):
        d['H']['ent']=d['H']['ent'].float().cuda()
    model=Bridge(tr['classes']).cuda()
    pis=prevalences(tr)
    lock={'status':'RUN_STARTED','seed':0,'epochs':8,'root_batch':32,'rendered_batch':64,
          'optimizer':'AdamW','learning_rate':3e-4,'weight_decay':.01,
          'checkpoint_selection':'fixed final epoch eight; DEV reporting only',
          'handoff_v02_sha256':handoff_sha,
          'sources':{p.name:sha(p) for p in HERE.glob('*.py')},
          'spec_sha256':sha(HERE/'BRIDGE.md'),
          'dataset_hashes':{s:sha(OUT/f'{s}-dataset.pt') for s in ('TRAIN','DEV')},
          'train_prevalences':pis,'parameters':sum(p.numel() for p in model.parameters()),
          'frozen_text_parameters':752393024,'evaluation_opened':False,
          'mechanism':'dense baseline only; no E/F/recurrence/LoRA/IHA'}
    receipt(folder/'run-start.json',lock)
    torch.save({n:x.detach().cpu() for n,x in model.state_dict().items()},folder/'initialization.pt')
    before=evaluate(model,dv)
    receipt(folder/'initialization.json',before)
    with torch.no_grad():
        states=[]
        for first in range(0,len(tr['pairs']),32):
            ix=tr['pairs'][first:first+32,0]
            states.append(model(pack(tr,ix))['s'].cpu())
        sigma=torch.cat(states).std(0,unbiased=False)
    torch.save(sigma,folder/'sigma0.pt')
    opt=torch.optim.AdamW(model.parameters(),lr=3e-4,weight_decay=.01)
    batches=math.ceil(len(tr['pairs'])/32)
    schedule=torch.optim.lr_scheduler.CosineAnnealingLR(opt,batches*8)
    started=time.perf_counter();history=[]
    torch.manual_seed(0)
    for epoch in range(1,9):
        model.train();perm=torch.randperm(len(tr['pairs']));totals={}
        for first in range(0,len(perm),32):
            ix=tr['pairs'][perm[first:first+32]].flatten()
            H=pack(tr,ix);out=model(H)
            terms=supervised(out,tr,ix,H['cand_mask'],pis)
            terms['renderer_pair']=.25*renderer_consistency(out,H['cand_mask'],
                                                          (tr['action'][ix]>=0).cuda())
            terms['variance']=.05*variance_floor(out['s'],sigma)
            loss=sum(terms.values())
            if not torch.isfinite(loss):
                raise ValueError('non-finite bridge loss; preserve failed run')
            opt.zero_grad(set_to_none=True);loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1,error_if_nonfinite=True)
            opt.step();schedule.step()
            for n,x in terms.items():
                totals[n]=totals.get(n,0.)+float(x.detach())
        metrics=evaluate(model,dv)
        checkpoint=folder/f'epoch-{epoch}.pt'
        torch.save({n:x.detach().cpu() for n,x in model.state_dict().items()},checkpoint)
        record={'epoch':epoch,'batches':batches,'loss_terms':{n:x/batches for n,x in totals.items()},
                'metrics':metrics,'seconds':time.perf_counter()-started,'checkpoint_sha256':sha(checkpoint)}
        receipt(folder/f'epoch-{epoch}.json',record);history.append(record)
        print(json.dumps({'epoch':epoch,'seconds':record['seconds'],
            'goal':metrics['metrics']['heads']['candidate_satisfies_goal']['balanced_accuracy'],
            'legal':metrics['metrics']['heads']['candidate_legal']['balanced_accuracy'],
            'endpoint':metrics['metrics']['endpoint']}),flush=True)
    final=evaluate(model,dv,ablations=True)
    receipt(folder/'receipt.json',{'status':'BRIDGE_TRAINED_RECORDER_ANALYSIS_PENDING',
             'fixed_epoch':8,'checkpoint_sha256':sha(folder/'epoch-8.pt'),
             'initialization':before,'trained':final,'training_seconds':time.perf_counter()-started,
             'peak_cuda_bytes':torch.cuda.max_memory_allocated(),'evaluation_opened':False})


if __name__=='__main__':
    main()
