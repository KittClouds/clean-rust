"""Same-type hard legal pairs, count slices and independent scalar comparison."""
import argparse,torch
from common import OUT,P6,read,receipt
from targets import load
from probes import pair_metric
from response_tools import paired_interval


def compute():
    t=load('DEV');pairs=t['pairs'];rows=torch.arange(len(pairs))[:,None]
    legal=t['labels']['legality'][:,:,0]==t['vocab']['legality'][0].index(1)
    both=legal[rows,pairs[:,:,0]]&legal[rows,pairs[:,:,1]]
    counts=torch.load(P6/'DEV-targets.pt',mmap=True,weights_only=False)['mask'].sum(1)
    result={}
    for arm in ('bridge','E'):
        for phenotype in ('init','trained'):
            for mode in ('c','cs','e'):
                for family in ('linear','mlp'):
                    folder=OUT/'panel'/arm/phenotype/mode/family
                    scalar=torch.load(P6/'panel'/arm/phenotype/mode/family/'selected.pt',mmap=True,weights_only=False)['logits']
                    independent=scalar[rows,pairs[:,:,0]]-scalar[rows,pairs[:,:,1]]
                    views={'independent_scalar':pair_metric(independent,t)}
                    for view in ('concat','difference','product'):
                        logits=torch.load(folder/f'pair-{view}.pt',mmap=True,weights_only=False)['logits']
                        metrics={}
                        for name,choose in (('all',t['pair_mask']),('both_legal',t['pair_mask']&both),
                            ('1-28',t['pair_mask']&(counts<=28)[:,None]),
                            ('29-64',t['pair_mask']&((counts>28)&(counts<=64))[:,None]),
                            ('65-128',t['pair_mask']&((counts>64)&(counts<=128))[:,None]),
                            ('129-171',t['pair_mask']&(counts>128)[:,None])):
                            modified={**t,'pair_mask':choose}
                            if not choose.any():metrics[name]={'pairs':0,'roots':0,'balanced_accuracy':None};continue
                            metrics[name]=pair_metric(logits,modified)
                        mask=t['pair_mask'];y=t['pair_labels']>.5
                        a=(((independent>0)==y)&mask).sum(1)/mask.sum(1).clamp_min(1)
                        b=(((logits>0)==y)&mask).sum(1)/mask.sum(1).clamp_min(1)
                        roots=mask.any(1)
                        metrics['root_mean_accuracy_gain']=paired_interval(a[roots].double().numpy(),b[roots].double().numpy())
                        views[view]=metrics
                    result[':'.join((arm,phenotype,mode,family))]=views
    return {'arms':result,'scope':'same-type contrasts; both-legal remains descriptive below200roots',
        'evaluation_opened':False}


def main(replay):
    value=compute();p=OUT/'pair-qualification.json'
    if replay:
        if value!=read(p):raise ValueError('pair derived metric replay mismatch')
        receipt(OUT/'qualification-replay.json',{'status':'PASS','evaluation_opened':False})
    else:receipt(p,value)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true');a=p.parse_args();main(a.replay)
