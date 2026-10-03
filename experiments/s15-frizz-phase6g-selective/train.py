"""Single fixed twelve-epoch TRAIN-only selective acquisition."""
from common import *
def normalization(a,t):
    sums=torch.zeros(352,dtype=torch.float64);squares=sums.clone();rows=0
    for first in range(0,len(a['mask']),32):
        ix=torch.arange(first,min(first+32,len(a['mask'])));x=continuous(a,ix).double();mask=t['mask'][ix]
        w=mask.double()/mask.sum(1).clamp_min(1)[:,None]
        sums+=(x*w[:,:,None]).sum((0,1));squares+=(x.square()*w[:,:,None]).sum((0,1));rows+=len(ix)
    mean=sums/rows;std=(squares/rows-mean.square()).clamp_min(1e-10).sqrt()
    y=t['status'];mask=t['mask'];prev=torch.stack([((y==i)&mask).sum(1)/mask.sum(1).clamp_min(1) for i in range(3)]).mean(1)
    if (prev<=0).any():raise ValueError('missing TRAIN status class')
    weights=1/prev;weights/=weights.mean()
    return {'mean':mean.float(),'std':std.float(),'class_weights':weights.float(),'root_balanced_prevalence':prev,'fit_split':'TRAIN'}
def main():
    setup();lock()
    if not (OUT/'binary-baselines.json').exists():raise ValueError('baseline rescore must precede fit')
    a=load(C6/'TRAIN-ABI.pt');t=load(OUT/'TRAIN-targets.pt');norm=normalization(a,t);save(OUT/'normalization.pt',norm)
    torch.manual_seed(0);model=Selective();save(OUT/'initialization.pt',model.state_dict())
    opt=torch.optim.AdamW(model.parameters(),lr=3e-4,weight_decay=.01);start=time.perf_counter();steps=0
    roots=len(a['canonical_ids'])
    receipt(OUT/'TRAIN-contract.json',{'seed':0,'epochs':12,'endpoint':12,'root_count':roots,'paired_rows':2*roots,
        'class_weights':norm['class_weights'].tolist(),'class_prevalence':norm['root_balanced_prevalence'].tolist(),
        'normalization_split':'TRAIN','only_supervision':'strict observable status','canonical_binary_loss':False,
        'selection_loss':False,'consequence_loss':False,'backbone_parameters_trainable':0,'device':'CPU FP32 four threads'})
    for epoch in range(1,13):
        perm=torch.randperm(roots);total=0;nb=0
        for first in range(0,roots,16):
            ix=(perm[first:first+16,None]*2+torch.arange(2)).flatten()
            logits=model(features(a,ix,norm));objective=loss(logits,t['status'][ix],t['mask'][ix],norm['class_weights'])
            if not torch.isfinite(objective):raise ValueError('nonfinite selective loss')
            opt.zero_grad(set_to_none=True);objective.backward();nn.utils.clip_grad_norm_(model.parameters(),1,error_if_nonfinite=True);opt.step()
            total+=float(objective.detach());steps+=1;nb+=1
        save(OUT/f'epoch-{epoch}.pt',{'weights':model.state_dict(),'optimizer':opt.state_dict(),'rng':torch.get_rng_state(),'epoch':epoch})
        receipt(OUT/f'epoch-{epoch}-TRAIN.json',{'epoch':epoch,'loss':total/nb,'steps':steps,'elapsed_seconds':time.perf_counter()-start})
        print('EPOCH',epoch,'TRAIN loss',total/nb,'seconds',time.perf_counter()-start,flush=True)
    receipt(OUT/'training-complete.json',{'status':'PASS','epochs':12,'endpoint':12,'steps':steps,'fit_seconds':time.perf_counter()-start,
        'parameters':sum(p.numel() for p in model.parameters()),'protected_evaluation_opened':False})
if __name__=='__main__':main()
