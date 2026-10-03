"""Known-solvable controls; never candidate model inputs or capability claims."""
import argparse,time
import torch
from common import OUT,config,receipt,read,sha
from targets import load
from probes import Pair,factor_metric,offsets


def run(replay=False):
    config();start=time.perf_counter();dv=load('DEV');checks={}
    for factor,vocab in dv['vocab'].items():
        ranges,n=offsets(vocab);y=dv['labels'][factor]
        logits=torch.full((*y.shape[:2],n),-20.)
        for k,(a,b) in enumerate(ranges):
            logits[:,:,a:b].scatter_(-1,y[:,:,k].clamp_min(0).unsqueeze(-1),20.)
        known=dv['same_mask']&(y>=0).all(-1)
        metric=factor_metric(logits,{**dv,'same_mask':known},factor)
        metric['unknown_candidates_excluded_from_control_only']=int((dv['same_mask']&~known).sum())
        if metric['mean_component_accuracy']!=1.:raise ValueError('known-label gold decoder control failure')
        checks['oracle-'+factor]=metric
    for family in ('linear','mlp'):
        torch.manual_seed(0);model=Pair(1,family,'difference')
        path=OUT/f'control-{family}.pt'
        if replay:
            if sha(path)!=read(path.with_suffix('.json'))['sha256']:raise ValueError('control drift')
            model.load_state_dict(torch.load(path,weights_only=True))
        else:
            opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
            x=torch.tensor([-1.,1.]).repeat(32).reshape(64,1);y=(x[:,0]>0).float()
            for _ in range(752):
                loss=torch.nn.functional.binary_cross_entropy_with_logits(model(x),y)
                opt.zero_grad(set_to_none=True);loss.backward();opt.step()
            torch.save(model.state_dict(),path)
            receipt(path.with_suffix('.json'),{'sha256':sha(path),'purpose':'synthetic known-solvable sign relation',
                'steps':752,'parameters':sum(p.numel() for p in model.parameters()),'device':'CPU'})
        x=torch.tensor([-2.,-.5,.5,2.]).reshape(4,1)
        result=model(x).detach();accuracy=float(((result>0)==(x[:,0]>0)).float().mean())
        if accuracy!=1.:raise ValueError('known-solvable TRAIN control failed')
        checks[family]={'accuracy':accuracy,'logits':result.tolist()}
        product=Pair(1,family,'product')
        if not torch.equal(product(x),torch.zeros(4)):raise ValueError('symmetric product guard failed')
    payload={'status':'PASS','checks':checks,'evaluation_opened':False}
    if replay:
        if payload!=read(OUT/'controls.json'):raise ValueError('control replay mismatch')
        receipt(OUT/'controls-replay.json',{'status':'PASS'})
    else:
        receipt(OUT/'controls.json',payload)
        receipt(OUT/'controls-cost.json',{'seconds':time.perf_counter()-start})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true');a=p.parse_args();run(a.replay)
