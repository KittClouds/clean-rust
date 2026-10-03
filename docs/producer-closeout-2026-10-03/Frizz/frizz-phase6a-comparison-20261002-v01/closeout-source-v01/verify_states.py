"""Independent-process cache reconstruction, pair reproduction and control replay."""
import torch
from common import OUT,check_lock,config,setup,new_model,weights,sha,read,receipt
from panel import cached,target
from pairs import targets
from probes import Probe,predict
import readouts as ro


def same(a,b):
    if isinstance(a,torch.Tensor):
        return isinstance(b,torch.Tensor) and torch.equal(a,b)
    if isinstance(a,dict):
        return a.keys()==b.keys() and all(same(v,b[k]) for k,v in a.items())
    return a==b


def main():
    config();check_lock();datasets=setup()
    for split,d in datasets.items():
        if not same(target(split),targets(d)):
            raise ValueError('pair/target construction replay mismatch')
    for arm in ('bridge','E'):
        for phenotype in ('init','trained'):
            model=new_model(arm,datasets['TRAIN']['classes'])
            model.load_state_dict(torch.load(weights(arm,phenotype),weights_only=True));model.eval()
            for split,d in datasets.items():
                reconstructed=ro.cache(model,d)
                if not same(reconstructed,cached(arm,phenotype,split)):
                    raise ValueError('frozen representation cache replay mismatch')
                del reconstructed
            del model
    dv=target('DEV')
    for family in ('linear','mlp'):
        for task in ('selected','selected_pair'):
            p=OUT/'controls'/f'{family}-{task}.pt';record=read(p.with_suffix('.json'))
            if sha(p)!=record['sha256']:
                raise ValueError('control drift')
            saved=torch.load(p,mmap=True,weights_only=False)
            probe=Probe(2 if task.endswith('_pair') else 1,family,task).cuda()
            probe.load_state_dict(saved['weights'])
            logits,_=predict(probe,None,dv,'e',task,True)
            if not torch.equal(logits,saved['logits']):
                raise ValueError('positive control replay mismatch')
    receipt(OUT/'state-replay.json',{'status':'PASS','state_caches':8,'positive_controls':4,
        'pair_and_target_reconstruction':'exact','source_identity':'frozen Phase5 checkpoints and Phase6A source',
        'evaluation_opened':False,'scope':'fresh process using declared authored code; not an independent semantic oracle'})


if __name__=='__main__':
    main()
