"""Matched root-level depth differences. Seeds are never merged into an endpoint."""
from report import *

def load(identity,seed,depth):
    return np.load(OUT/'predictions'/identity/(str(seed)+'-T'+str(depth)+'.npz'))

def interval(values):
    values=np.asarray(values,dtype=np.float64)
    if not len(values):return {'roots':0,'difference':None,'bootstrap95':None}
    rng=np.random.default_rng(20261002);boot=np.empty(1000)
    for i in range(1000):boot[i]=values[rng.integers(len(values),size=len(values))].mean()
    return {'roots':len(values),'difference':float(values.mean()),'bootstrap95':np.quantile(boot,[.025,.975]).tolist()}

def source_interval(dev,ap,bp,family,k):
    y=dev.arrays['cy' if family=='candidate' else 'gy'][...,k].astype(bool)
    valid=dev.arrays['ca' if family=='candidate' else 'ga'][...,k]
    if family=='candidate':valid=valid&dev.arrays['mask']
    def counts(pred):
        # TP,FN,TN,FP per canonical root, retaining both renderer descendants.
        bits=[y&pred,y&~pred,~y&~pred,~y&pred]
        return np.stack([((v&valid).reshape(dev.n,-1).sum(1)).reshape(-1,2).sum(1) for v in bits],1)
    ac=counts(ap);bc=counts(bp)
    def ba(c):return .5*(c[0]/max(1,c[0]+c[1])+c[2]/max(1,c[2]+c[3]))
    rng=np.random.default_rng(20261002);boot=[]
    for i in range(1000):
        ids=rng.integers(len(ac),size=len(ac));boot.append(ba(bc[ids].sum(0))-ba(ac[ids].sum(0)))
    return {'difference':float(ba(bc.sum(0))-ba(ac.sum(0))),'bootstrap95':np.quantile(boot,[.025,.975]).tolist(),'roots':len(ac)}

def compare(dev,a,b,base):
    y=dev.arrays['action'];eligible=y>=0;root_eligible=eligible[0::2]
    curves=[];seeds=[20261002,20261003,20261004];terminal=[];depth_support=[]
    for seed in seeds:
        own=[]
        for depth in range(5):
            ap=load('A_DETERMINISTIC',20261002,depth)['action'];bp=load('B_STOCHASTIC',seed,depth)['action']
            diff=((bp==y).astype(float)-(ap==y).astype(float)).reshape(-1,2).mean(1)
            row={'seed':seed,'depth':depth,'exact_action_B_minus_A':interval(diff[root_eligible]),'hard_slices':{}}
            for axis in ['composition_depth','transition_depth']:
                for v in sorted({m['axes'][axis] for m in dev.meta}):
                    take=root_eligible&np.array([m['axes'][axis]==v for m in dev.meta[0::2]])
                    row['hard_slices'][axis+'='+str(v)]=interval(diff[take])
            own.append(row);curves.append(row)
        terminal.append(own[4]['exact_action_B_minus_A']['difference'])
        depth_support.append(any(r['difference'] is not None and r['difference']>0 for k,r in own[4]['hard_slices'].items() if int(k.split('=')[1])>=2))
    # Descriptive semantic preservation, no pooled response score.
    semantic={};all_preserved=True
    for family,targets in [('candidate',['candidate_legal','candidate_satisfies_goal']),('global',['solvable','goal_satisfied','missing_information_present'])]:
        for target in targets:
            av=a['depths']['4'][family][target]['balanced_accuracy']
            vals=[]
            for br in [b['operational']]+b['diagnostic_seeds']:
                bv=br['depths']['4'][family][target]['balanced_accuracy'];vals.append(None if av is None or bv is None else bv-av)
            k=targets.index(target);key='c' if family=='candidate' else 'g'
            intervals=[]
            for seed in seeds:
                ac=load('A_DETERMINISTIC',20261002,4)[key][...,k]>=0;bc=load('B_STOCHASTIC',seed,4)[key][...,k]>=0
                intervals.append(source_interval(dev,ac,bc,family,k))
            semantic[target]={'A_balanced_accuracy':av,'B_minus_A_by_seed':vals,'paired_root_intervals':intervals}
            all_preserved&=all(v['bootstrap95'][1]>=0 for v in intervals)
    ycount=dev.arrays['gy'][:,5];apcount=load('A_DETERMINISTIC',20261002,4)['g'][:,5]
    count_intervals=[]
    for seed in seeds:
        bpcount=load('B_STOCHASTIC',seed,4)['g'][:,5]
        improvements=(np.abs(apcount-ycount)-np.abs(bpcount-ycount)).reshape(-1,2).mean(1)
        count_intervals.append(interval(improvements))
    semantic['missing_cardinality']={'A_minus_B_MAE_by_seed':count_intervals,'positive_means_B_improves':True}
    all_preserved&=all(v['bootstrap95'][1]>=0 for v in count_intervals)
    if all(v is not None and v<=0 for v in terminal):disposition='B_RETIRE_NO_USEFUL_COMPUTATION_GAIN'
    elif not all(v is not None and v>0 for v in terminal):disposition='B_RETIRE_NONREPEATABLE_TERMINAL_GAIN'
    elif not all(depth_support):disposition='B_RETIRE_NO_REPEATABLE_DEPTH_CONDITIONED_GAIN'
    elif not all_preserved:disposition='B_RETIRE_SEMANTIC_PRESERVATION_NOT_ESTABLISHED'
    else:disposition='B_SURVIVES_REPEATABLE_DEPTH_GAIN_NO_DETECTED_STATE_LOSS'
    result={'depth_differences':curves,'semantic_preservation':semantic,'disposition':disposition,
      'selection':'A/B fixed epoch20; no sampled-DEV checkpoint or seed choice',
      'resampling':'1000 paired canonical-root draws, fixed seed; separate intervals per trajectory; no ensemble',
      'interpretation':'Descriptive DEV engineering disposition, not external generalization or mechanistic claim',
      'B_terminal_action_differences_by_seed':terminal,'B_hard_depth_gain_by_seed':depth_support,
      'A_minus_bridge_action':a['depths']['4']['action']['exact_logged_accuracy']-base['depths']['0']['action']['exact_logged_accuracy'],
      'new_access_organ':False,'EVAL_files_opened':0,'completed_arms':['BRIDGE','A_DETERMINISTIC','B_STOCHASTIC'],
      'support_rule':'Only MOVE clears DEV 200-root type floor; other types support-only',
      'no_rescue':True}
    write(OUT/'COMPARISON.json',result);return result
