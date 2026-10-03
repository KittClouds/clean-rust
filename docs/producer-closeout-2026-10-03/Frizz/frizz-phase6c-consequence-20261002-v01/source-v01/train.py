"""Eight fixed epochs; TRAIN consequence only, paired-root batches; no DEV tuning."""
import time
import torch
from common import *
from prepare import batch
from model import Consequence,losses,state_target


def weighting(target):
    y=target['category'];mask=target['mask'];states=state_target(y.clamp_min(0))
    counts=torch.bincount(states[mask],minlength=4).float()
    w=(counts.sum()/counts.clamp_min(1)).sqrt();w=(w/w.mean()).clamp_max(8)
    solved=mask&(y>=0)&(y<9)
    pi=torch.stack([(y[solved]>k).float().mean() for k in range(8)]).clamp(.02,.98)
    return {'state':w,'ordinal_pi':pi}


def main():
    setup();lock();abi=load(OUT/'TRAIN-ABI.pt');target=load(OUT/'TRAIN-targets.pt');d=datasets('TRAIN')
    torch.manual_seed(0);model=Consequence();weights=weighting(target)
    save(OUT/'initialization.pt',model.state_dict())
    receipt(OUT/'TRAIN-WEIGHTS.json',{k:v.tolist() for k,v in weights.items()})
    opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
    start=time.perf_counter();journal=[];roots=len(abi['root_indices']);steps=0
    for epoch in range(1,9):
        model.train();perm=torch.randperm(roots);totals={}
        for first in range(0,roots,16):
            pair=perm[first:first+16];ix=(pair[:,None]*2+torch.arange(2)).flatten()
            x=batch(abi,d,ix);t={k:v[ix] for k,v in target.items()};o=model(x)
            terms=losses(o,t,weights);loss=sum(terms.values())
            if not torch.isfinite(loss):raise ValueError('nonfinite consequence fit; preserve attempt')
            opt.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1,error_if_nonfinite=True);opt.step();steps+=1
            for k,v in terms.items():totals[k]=totals.get(k,0)+float(v.detach())
        checkpoint=OUT/f'epoch-{epoch}.pt'
        save(checkpoint,{'weights':model.state_dict(),'optimizer':opt.state_dict(),'rng':torch.get_rng_state(),'epoch':epoch})
        record={'epoch':epoch,'steps':steps,'elapsed_seconds':time.perf_counter()-start,
            'TRAIN_loss_terms':{k:v/((roots+15)//16) for k,v in totals.items()},'checkpoint_sha256':sha(checkpoint)}
        receipt(OUT/f'epoch-{epoch}-TRAIN.json',record);journal.append(record);print('EPOCH '+str(epoch)+' '+str(record['elapsed_seconds']),flush=True)
    receipt(OUT/'training-complete.json',{'status':'PASS','fixed_epoch':8,'steps':steps,'epochs':journal,
        'parameters':sum(p.numel() for p in model.parameters()),'training_seconds':time.perf_counter()-start,
        'device':'CPU FP32 four threads','Qwen_or_E_trainable_parameters':0,'selected_ID_supervision':False,'evaluation_opened':False})


if __name__=='__main__':main()
