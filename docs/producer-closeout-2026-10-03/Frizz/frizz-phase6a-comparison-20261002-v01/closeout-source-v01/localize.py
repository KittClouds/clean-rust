"""Apply prospective operational branch rules without a best-of-panel score."""
import torch
from common import OUT,read,receipt
from panel import target
from ranking import ranking
from response_tools import paired_interval


def value(arm,mode,family):
    return read(OUT/'panel'/arm/'trained'/mode/family/'metrics.json')['metrics']


def good(metric):
    v=metric['selected_ranking']['unrestricted']['all']['selected']
    return (v['eligible_roots']>=200 and v['top1']>=.35 and v['MRR']>=.50 and
            v['top1']-v['uniform_top1_expectation']>=.20)


def main():
    if read(OUT/'probe-replay.json')['status']!='PASS' or read(OUT/'state-replay.json')['status']!='PASS':
        raise ValueError('localization requires cache, pair, control and probe replay')
    diagnostics={(arm,mode,f):value(arm,mode,f) for arm in ('bridge','E')
                 for mode in ('c','cs','e') for f in ('linear','mlp')}
    passed={':'.join(k):good(v) for k,v in diagnostics.items()}
    dv=target('DEV');raw={}
    for family in ('linear','mlp'):
        root=OUT/'panel'/'E'/'trained'/'e'/family
        scores=torch.load(root/'selected.pt',mmap=True,weights_only=False)['logits']
        types=torch.load(root/'type.pt',mmap=True,weights_only=False)['logits'].argmax(1)
        _,r=ranking(scores,dv,types);raw[family]=r['unrestricted']['selected_top1'][dv['selected_eligible']].double().numpy()
    interval=paired_interval(raw['linear'],raw['mlp'])
    cs_loses=any(good(diagnostics['E','cs',f]) and not good(diagnostics['E','e',f]) for f in ('linear','mlp'))
    if good(diagnostics['E','e','linear']):
        branch='SIMPLE_LINEAR_RANKING_SUFFICIENT';earned=False
    elif cs_loses:
        branch='COMPARISON_ACCESS_LOST_OR_DEGRADED_AT_INTEGRATION';earned=False
    elif good(diagnostics['E','e','mlp']) and interval['delta']>=.10 and interval['ci95'][0]>0:
        branch='NONLINEAR_ONLY_COMPARISON_ACCESS_F_EARNED';earned=True
    elif all(not v for v in passed.values()):
        branch='NO_EXPOSED_SURFACE_CLEARS_FIXED_USEFUL_RANKING_THRESHOLD';earned=False
    else:
        branch='PARTIAL_ACCESS_LOCALIZATION_NO_AUTOMATIC_F';earned=False
    receipt(OUT/'LOCALIZATION.json',{'status':branch,'F_earned':earned,
        'well_ranked_by_declared_arm':passed,'E_e_MLP_minus_linear_top1':interval,
        'absence_scope':'failure to recover at this fixed linear/64-MLP dose, not proof of information-theoretic absence',
        'pairwise_scope':'label-constructed contrast accuracy is not full-universe ranking sufficiency',
        'evaluation_opened':False})
    print(branch,flush=True)


if __name__=='__main__':
    main()
