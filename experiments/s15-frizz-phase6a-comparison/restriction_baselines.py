"""Supplement restricted-universe chance baselines without refitting or selecting."""
import torch
from common import OUT,read,receipt
from panel import target


def main():
    d=target('DEV');result={}
    for arm in ('bridge','E'):
        for phenotype in ('init','trained'):
            for mode in ('c','cs','e'):
                for family in ('linear','mlp'):
                    folder=OUT/'panel'/arm/phenotype/mode/family
                    kind=torch.load(folder/'type.pt',mmap=True,weights_only=False)['logits'].argmax(1)
                    views={}
                    for restriction,types in (('gold_type',d['first_action_type']),('predicted_type',kind)):
                        allowed=d['mask']&(d['types']==types[:,None]);count=allowed.sum(1)
                        selected=d['selected'].clamp_min(0);inside=allowed.gather(1,selected[:,None]).squeeze(1)
                        opt=(d['optimal']&allowed).sum(1)
                        choose=d['selected_eligible'];use=d['optimal_eligible']
                        expectation=inside.float()/count.clamp_min(1)
                        optimal=opt.float()/count.clamp_min(1)
                        views[restriction]={'selected_roots':int(choose.sum()),
                            'selected_uniform_top1':float(expectation[choose].mean()),
                            'optimal_roots':int(use.sum()),'optimal_uniform_top1':float(optimal[use].mean()),
                            'mean_allowed_candidates':float(count[choose].float().mean()),
                            'empty_allowed_eligible_roots':int(((count==0)&choose).sum())}
                    result[':'.join((arm,phenotype,mode,family))]=views
    receipt(OUT/'restricted-universe-baselines.json',{'status':'DESCRIPTIVE_SUPPLEMENT',
        'arms':result,'evaluation_opened':False,'readout_refits':0,
        'note':'metrics.json uniform_top1_expectation uses full N, including restricted views. Use this supplement for conditional-universe chance baselines. Actual ranks/MRR/top-k/exclusions are unaffected.',
        'branch_rule':'unchanged; uses unrestricted full-universe selected ranking only'})


if __name__=='__main__':
    main()
