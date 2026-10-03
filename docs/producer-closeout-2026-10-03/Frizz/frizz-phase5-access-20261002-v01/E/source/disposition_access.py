"""Apply prospectively frozen response-vector gates; no best-arm selection."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch

from flight_panel import BRIDGE
from recorder_runner import LANE
from dataset import load
from objective import prevalences
from response_tools import semantic_response,candidate_counts,paired_interval
from audit_release import sha
from runtime import receipt


def read(path):
    return json.loads(path.read_text())


def probe_logits(folder,shape):
    saved=torch.load(folder/'trained'/'candidate_satisfies_goal-e-linear.pt',
                     mmap=True,weights_only=False)
    value=torch.zeros(shape);value[saved['mask']]=saved['logits']
    return value


def main(arm):
    spec=read(LANE/arm/'SPECIFICATION.json');rule=spec['survival_rule']
    folders={a:LANE/a/'recorder-v01' for a in ('bridge',arm)}
    for folder in folders.values():
        if read(folder/'replay.json')['status']!='PASS':
            raise ValueError('response cannot be judged before full recorder replay')
    tr,dv=load('TRAIN'),load('DEV');ix=dv['pairs'][:,0]
    scores={a:torch.load(f/'trained-production.pt',mmap=True,weights_only=False)['primary']
            for a,f in folders.items()}
    runs={a:read((BRIDGE/'baseline' if a=='bridge' else LANE/a/'run')/'receipt.json')
          for a in folders}
    primary=semantic_response(scores['bridge'],scores[arm],dv,
        prevalences(tr)['candidate_satisfies_goal'],spec['hard_definitions'])
    # Fixed declared e-linear arm, never maximum over the panel.
    truth=dv['candidate']['candidate_satisfies_goal'][ix];mask=dv['H']['cand_mask'][ix]
    counts={a:candidate_counts(probe_logits(f,mask.shape),truth,mask) for a,f in folders.items()}
    linear=paired_interval(counts['bridge'],counts[arm],score='ba')
    positive_roots=int((truth.bool()&mask).any(1).sum())
    negative_roots=int((~truth.bool()&mask).any(1).sum())
    linear['positive_roots']=positive_roots;linear['negative_roots']=negative_roots
    linear_ok=(linear['delta']>=rule['linear_gain'] and linear['ci95'][0]>0 and
               min(positive_roots,negative_roots)>=200)
    b,n=runs['bridge']['trained'],runs[arm]['trained'];preservation={}
    def preserve(name,old,new,tolerance,support):
        preservation[name]={'bridge':old,'arm':new,'delta':None if old is None or new is None else new-old,
            'root_support':support,'tolerance':tolerance,
            'pass':True if old is None or new is None or support<200 else new-old>=-tolerance,
            'scope':'undefined/underpowered values descriptive, not a reliability claim'}
    for target in ('candidate_legal','candidate_satisfies_goal','goal_satisfied','solvable'):
        x,y=b['metrics']['heads'][target],n['metrics']['heads'][target]
        support=(len(ix) if target.startswith('candidate_') else x['n'])
        preserve(target,x['balanced_accuracy'],y['balanced_accuracy'],rule['binary_preservation'],support)
    panels={a:read(f/'trained'/'panel-complete.json')['arms'] for a,f in folders.items()}
    for target in ('candidate_legal-e-linear','goal_satisfied-s-linear','solvable-s-linear'):
        x,y=panels['bridge'][target]['metric'],panels[arm][target]['metric']
        preserve('linear_'+target,x['balanced_accuracy'],y['balanced_accuracy'],rule['binary_preservation'],len(ix))
    for target in dv['classes']:
        x,y=b['metrics']['heads'][target],n['metrics']['heads'][target]
        preserve(target,x['accuracy'],y['accuracy'],rule['core_preservation'],x['n'])
    for target,fields in b['restricted_target_strata'].items():
        for field,buckets in fields.items():
            for value,x in buckets.items():
                y=n['restricted_target_strata'][target][field][value]
                preserve(f'restricted:{target}:{field}:{value}',x['metric']['accuracy'],
                         y['metric']['accuracy'],rule['restricted_preservation'],x['root_n'])
    for endpoint,key in (('exact_logged_action','accuracy'),('optimal_set_hit','rate')):
        x,y=b['metrics']['endpoint'][endpoint],n['metrics']['endpoint'][endpoint]
        preserve(endpoint,x[key],y[key],rule['endpoint_preservation'],x['n'])
    for name in ('unsatisfied_goal','legal_MOVE_unsatisfied_goal'):
        x,y=b['hard_slices'][name],n['hard_slices'][name]
        if name=='unsatisfied_goal':
            x,y=x['heads']['candidate_satisfies_goal'],y['heads']['candidate_satisfies_goal']
            support=int((~dv['binary']['goal_satisfied'][ix].bool()).sum())
        else:
            move=torch.tensor([[a['type']=='MOVE' for a in dv['actions'][int(i)]]+
                [False]*(171-len(dv['actions'][int(i)])) for i in ix])
            support=int((move&mask&dv['candidate']['candidate_legal'][ix].bool()&
                (~dv['binary']['goal_satisfied'][ix].bool())[:,None]).any(1).sum())
        preserve(name,x['balanced_accuracy'],y['balanced_accuracy'],rule['slice_preservation'],support)
    robust={a:read(f/'trained-production.json')['renderer_robustness'] for a,f in folders.items()}
    for target in robust['bridge']:
        x,y=robust['bridge'][target],robust[arm][target]
        # Larger disagreement is worse; negate so all preservation comparisons
        # share the same declared direction without combining their scores.
        preserve('renderer_'+target,-x['fraction'],-y['fraction'],rule['renderer_preservation'],x['root_count'])
    improved=sum(v['improved'] for v in primary.values())
    no_hard_loss_regression=all(v['relative_loss_reduction'] is None or
        v['relative_loss_reduction']>=-rule['maximum_hard_loss_regression'] for v in primary.values())
    gates={'primary_cells':improved>=rule['minimum_improved_primary_cells'],
           'no_hard_loss_regression':no_hard_loss_regression,'fixed_linear_access':bool(linear_ok),
           'preservation_vector':all(v['pass'] for v in preservation.values())}
    survives=all(gates.values())
    result={'arm':arm,'survives':survives,'status':'SURVIVES_AS_CONSTRUCTED' if survives else 'RETIRED_AS_CONSTRUCTED',
        'gates':gates,'hard_primary_cells':primary,'fixed_e_linear_goal_access':linear,
        'preservation_vector':preservation,'specification_sha256':sha(LANE/arm/'SPECIFICATION.json'),
        'conflict':'diagnostic only','evaluation_opened':False,
        'interpretation':'bounded single-family result, not a substrate ceiling; no composite score',
        'underpowered_hard_positive_support':'proper-loss slice is reported separately from positive-class recoverability'}
    receipt(LANE/arm/'DISPOSITION.json',result)
    print(json.dumps({'arm':arm,'survives':survives,'gates':gates}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--arm',choices=['E','F'],required=True)
    main(parser.parse_args().arm)
