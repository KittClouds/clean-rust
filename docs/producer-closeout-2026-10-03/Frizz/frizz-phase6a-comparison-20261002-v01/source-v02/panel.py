"""Complete frozen readout panel, no target-driven selection or hidden reruns."""
import argparse
import torch
from common import OUT,P5,read,receipt,sha,check_lock,config
from probes import Probe,TASKS,fit,predict
from ranking import ranking,pair_metric
from evaluate import categorical_metric,binary_metric


def cached(arm,phenotype,split):
    p=OUT/f'{arm}-{phenotype}-{split}.pt'
    if sha(p)!=read(p.with_suffix('.json'))['sha256']:
        raise ValueError('cached frozen state drift')
    return torch.load(p,mmap=True,weights_only=False)


def target(split):
    p=OUT/f'{split}-targets.pt'
    if sha(p)!=read(p.with_suffix('.json'))['sha256']:
        raise ValueError('pair/target drift')
    return torch.load(p,mmap=True,weights_only=False)


def controls(tr,dv):
    folder=OUT/'controls';folder.mkdir(exist_ok=False)
    for family in ('linear','mlp'):
        for task in ('selected','selected_pair'):
            probe,cost=fit(None,tr,'e',family,task,True)
            logits,latency=predict(probe,None,dv,'e',task,True)
            if task=='selected':
                scores=logits.masked_fill(~dv['mask'],float('-inf'))
                use=dv['selected_eligible'];metric=float((scores.argmax(1)[use]==dv['selected'][use]).float().mean())
            else:
                metric=pair_metric(logits,dv[task])['accuracy']
            if metric<.99:
                raise ValueError('known-solvable comparison instrument failed')
            path=folder/f'{family}-{task}.pt'
            torch.save({'weights':probe.cpu().state_dict(),'logits':logits},path)
            receipt(path.with_suffix('.json'),{'accuracy':metric,'cost':cost,'seconds':latency,'sha256':sha(path)})
    receipt(folder/'complete.json',{'status':'CONTROLS_PASS','arms':4})


def execute(replay=False):
    config();check_lock();tr,dv=target('TRAIN'),target('DEV')
    if not replay:
        controls(tr,dv)
    for arm in ('bridge','E'):
        for phenotype in ('init','trained'):
            tc=cached(arm,phenotype,'TRAIN') if not replay else None
            dc=cached(arm,phenotype,'DEV')
            for mode in ('c','cs','e'):
                for family in ('linear','mlp'):
                    folder=OUT/'panel'/arm/phenotype/mode/family
                    if not replay:
                        folder.mkdir(parents=True,exist_ok=False)
                    scores={};costs={}
                    for task in TASKS:
                        path=folder/f'{task}.pt'
                        if replay:
                            meta=read(path.with_suffix('.json'))
                            if sha(path)!=meta['sha256']:
                                raise ValueError('saved probe drift')
                            saved=torch.load(path,mmap=True,weights_only=False)
                            dim=dc['e' if mode=='e' else 'c'].shape[-1]+(64 if mode=='cs' else 0)
                            probe=Probe(dim*2 if task.endswith('_pair') else dim,family,task).cuda()
                            probe.load_state_dict(saved['weights'])
                            logits,latency=predict(probe,dc,dv,mode,task)
                            if not torch.equal(logits,saved['logits']):
                                raise ValueError('fresh-process probe logit replay mismatch')
                        else:
                            probe,cost=fit(tc,tr,mode,family,task)
                            logits,latency=predict(probe,dc,dv,mode,task)
                            torch.save({'weights':{n:x.cpu() for n,x in probe.state_dict().items()},'logits':logits},path)
                            cost['DEV_seconds']=latency;cost['peak_cuda_bytes']=torch.cuda.max_memory_allocated()
                            receipt(path.with_suffix('.json'),{'sha256':sha(path),'cost':cost,'task':task,
                                'mode':mode,'family':family,'evaluation_opened':False})
                            costs[task]=cost
                        scores[task]=logits;del probe
                    result=metrics(scores,dv)
                    if replay:
                        if result!=read(folder/'metrics.json')['metrics']:
                            raise ValueError('ranking or pair metric replay mismatch')
                    else:
                        receipt(folder/'metrics.json',{'metrics':result,'costs':costs,
                            'goal_control':{f:read(P5/arm/'recorder-v01'/phenotype/f'candidate_satisfies_goal-{mode}-{f}.json')['metric']
                                            for f in ('linear','mlp')},'evaluation_opened':False})
                    print(f'{"REPLAY" if replay else "FIT"} {arm} {phenotype} {mode} {family}',flush=True)
            del tc,dc
    receipt(OUT/('probe-replay.json' if replay else 'panel-complete.json'),
            {'status':'PASS','probe_count':120,'evaluation_opened':False})


def metrics(scores,dv):
    kind=scores['type'].argmax(-1)
    result={'first_action_type':categorical_metric(kind,dv['first_action_type'],9),
            'selected_pair':pair_metric(scores['selected_pair'],dv['selected_pair']),
            'optimal_pair':pair_metric(scores['optimal_pair'],dv['optimal_pair'])}
    for task in ('selected','optimal'):
        r,_=ranking(scores[task],dv,kind);result[task+'_ranking']=r
    use=dv['mask']&dv['optimal_eligible'][:,None]
    result['optimal_membership']=binary_metric(scores['optimal'][use],dv['optimal'][use].float())
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true');a=p.parse_args();execute(a.replay)
