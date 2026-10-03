"""Fixed eight-epoch single-task legality acquisition, no DEV scoring."""
import time
from common import *
from gate import LegalGate,loss


def main():
    setup();lock();abi=load(C6/'TRAIN-ABI.pt');old=load(C6/'TRAIN-targets.pt');mask=old['mask']
    legal=mask&(old['category']>=0)&(old['category']<11);d=dataset_load('TRAIN')
    torch.manual_seed(0);model=LegalGate();save(OUT/'initialization.pt',model.state_dict())
    receipt(OUT/'TRAIN-contract-receipt.json',{'canonical_roots':len(abi['root_indices']),'paired_rows':len(mask),
        'legal_candidates_canonical':int(legal[::2].sum()),'illegal_candidates_canonical':int((mask[::2]&~legal[::2]).sum()),
        'weighting':'each root class-normalized legal/illegal BCE, equal class weights where both exist; TRAIN only',
        'threshold_logit':0,'epochs':8,'selected_ID_supervision':False,'consequence_parameters_trainable':0})
    opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01);roots=len(abi['root_indices']);start=time.perf_counter();steps=0
    for epoch in range(1,9):
        permutation=torch.randperm(roots);totals={}
        for first in range(0,roots,16):
            selected_roots=permutation[first:first+16];ix=(selected_roots[:,None]*2+torch.arange(2)).flatten()
            terms=loss(model(batch(abi,d,ix)),legal[ix],mask[ix]);objective=sum(terms.values())
            if not torch.isfinite(objective):raise ValueError('nonfinite gate fit; preserve failure')
            opt.zero_grad(set_to_none=True);objective.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1,error_if_nonfinite=True);opt.step();steps+=1
            for k,v in terms.items():totals[k]=totals.get(k,0)+float(v.detach())
        p=OUT/f'epoch-{epoch}.pt';save(p,{'weights':model.state_dict(),'optimizer':opt.state_dict(),'rng':torch.get_rng_state(),'epoch':epoch})
        receipt(OUT/f'epoch-{epoch}-TRAIN.json',{'epoch':epoch,'steps':steps,'elapsed_seconds':time.perf_counter()-start,
            'losses':{k:v/((roots+15)//16) for k,v in totals.items()},'checkpoint_sha256':sha(p)})
        print('EPOCH '+str(epoch)+' '+str(time.perf_counter()-start),flush=True)
    receipt(OUT/'training-complete.json',{'status':'PASS','fixed_epoch':8,'optimizer_steps':steps,'fit_seconds':time.perf_counter()-start,
        'parameters':sum(p.numel() for p in model.parameters()),'device':'CPU FP32 four threads','evaluation_opened':False,
        'only_trainable_scientific_target':'candidate_legal','frozen_consequence_sha256':sha(C6/'epoch-8.pt')})


if __name__=='__main__':main()
