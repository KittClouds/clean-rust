"""Independent process: hash, identity, normalization, inference and metric replay."""
from p6_contract import *
from fit_panel import features,normalizers,head_model
from ranking import recorder,type_metrics,binary,paired_gain

def main():
    verify();manifest=read(OUT/'MANIFEST.json');checks=0
    for name,digest in manifest['files'].items():
        if sha(OUT/name)!=digest:raise ValueError('Artifact changed '+name)
        checks+=1
    result=read(OUT/'RESULT.json');roots={};inference=0;metric_checks=0;max_delta=0.
    torch.set_num_threads(4)
    for split in ['TRAIN','DEV']:
        arrays,meta,ids=load_split(split);folder=OUT/'cache'/split
        if not np.array_equal(ids,np.load(folder/'ids.npy')):raise ValueError('Population differs')
        roots[split]={meta[i]['root'] for i in ids}
        for key,value in [('mask',arrays['mask'][ids]),('types',arrays['A'][ids,:,0]),('selected',arrays['action'][ids]),('optimal',arrays['optimal'][ids])]:
            if not np.array_equal(value,np.load(folder/(key+'.npy'))):raise ValueError('Canonical label identity differs '+key)
    if roots['TRAIN']&roots['DEV']:raise ValueError('Root leakage')
    for depth in range(5):
        train,tl=features('TRAIN',depth);dev,dl=features('DEV',depth);norms=normalizers(train,tl)
        truth=dl['types'][np.arange(len(dl['selected'])),dl['selected']]-1
        for family in ['linear','tiny_MLP']:
            prefix=f'T{depth}-{family}';row=result['panel'][prefix]
            type_scores=np.load(OUT/'heads'/f'DIAGNOSTIC-T{depth}-type-{family}'/'DEV-scores.npy')
            if type_metrics(truth,type_scores.argmax(1))!=row['first_action_type']:raise ValueError('Type metrics differ')
            for task in ['type','selected','membership']:
                folder=OUT/'heads'/f'DIAGNOSTIC-T{depth}-{task}-{family}'
                artifact=torch.load(folder/'head.pt',map_location='cpu',weights_only=True);key='type' if task=='type' else 'candidate'
                for field in ['mean','std']:
                    if not np.array_equal(artifact['TRAIN_'+field].numpy(),norms[key][field]):raise ValueError('TRAIN normalization differs')
                head=head_model(task,family);head.load_state_dict(artifact['head']);head.eval()
                scores=np.load(folder/'DEV-scores.npy');pieces=[]
                with torch.no_grad():
                    for at in range(0,len(dev[key]),64):
                        x=torch.tensor(np.array(dev[key][at:at+64]));x=(x-artifact['TRAIN_mean'])/artifact['TRAIN_std']
                        v=head(x).numpy();pieces.append(v if task=='type' else v.squeeze(-1))
                replay=np.concatenate(pieces);delta=float(np.abs(replay-scores).max());max_delta=max(max_delta,delta)
                if not np.allclose(replay,scores,rtol=1e-4,atol=1e-4):raise ValueError('CPU head inference differs '+folder.name+f' delta {delta}')
                inference+=1
                if task!='type':
                    metrics,raw=recorder(scores,dl['mask'],dl['selected'],dl['optimal'],dl['types'],type_scores.argmax(1),dl['meta'])
                    if metrics!=row[task]:raise ValueError('Ranking replay differs '+folder.name)
                    metric_checks+=1
                    if task=='membership' and binary(dl['optimal'][dl['mask']],scores[dl['mask']]>=0)!=row['membership_binary']:raise ValueError('Membership binary differs')
            metrics,raw=recorder(cached('DEV',depth)['production'],dl['mask'],dl['selected'],dl['optimal'],dl['types'],type_scores.argmax(1),dl['meta'])
            if metrics!=row['production']:raise ValueError('Production ranking differs')
            metric_checks+=1
            for task in ['selected','membership']:
                ranks=np.load(OUT/'metrics'/(prefix+'-'+task+'-ranks.npz'))['unrestricted-selected_rank']
                if paired_gain(raw['unrestricted']['selected_rank'],ranks)!=row[task+'_production_gap']:raise ValueError('Paired interval differs')
    ordered=[]
    for family in ['linear','tiny_MLP']:
        for depth in range(5):
            gap=result['panel'][f'T{depth}-{family}']['selected_production_gap']
            ordered.append({'depth':depth,'family':family,'gap':gap,'earns_repair':gap['difference']>=.05 and gap['bootstrap95'][0]>0})
    if ordered!=result['repair_gate']:raise ValueError('Repair eligibility order differs')
    chosen=next((x for x in ordered if x['earns_repair']),None)
    if bool(chosen)!=bool(result['followup']):raise ValueError('Repair disposition differs')
    if chosen:
        follow=result['followup']
        if chosen!=follow['chosen_prospectively_ordered_identity']:raise ValueError('Repair choice differs')
        depth=chosen['depth'];family=chosen['family'];_,dl=features('DEV',depth)
        scores=np.load(OUT/'heads'/f'REPAIR-T{depth}-selected-{family}'/'DEV-scores.npy')
        ts=np.load(OUT/'heads'/f'DIAGNOSTIC-T{depth}-type-{family}'/'DEV-scores.npy')
        metrics,raw=recorder(scores,dl['mask'],dl['selected'],dl['optimal'],dl['types'],ts.argmax(1),dl['meta'])
        if metrics!=follow['metrics']:raise ValueError('Repair ranking differs')
        prod=np.load(OUT/'metrics'/f'T{depth}-{family}-production-ranks.npz')['unrestricted-selected_rank']
        if paired_gain(prod,raw['unrestricted']['selected_rank'])!=follow['production_gap']:raise ValueError('Repair gap differs')
        metric_checks+=1
    write(OUT/'REPLAY.json',{'status':'PASS','hash_checks':checks,'head_inference_checks':inference,
        'max_CPU_CUDA_logit_delta':max_delta,'ranking_metric_checks':metric_checks,'TRAIN_normalizers_recomputed':True,
        'canonical_population_replayed':True,'repair_gate_replayed':True,'protected_files_opened':0},replace=True)
    print('REPLAY PASS',checks,inference,metric_checks,flush=True)

if __name__=='__main__':main()
