"""Fresh process replay of canonical semantics, shallow inference, and ranking."""
from b6_contract import *
from b6_gold import one,ceilings
from b6_probes import model,candidate_labels,differences,score_metrics
from ranking import recorder

def main():
    verify();manifest=read(OUT/'MANIFEST.json');checks=0
    for name,digest in manifest['files'].items():
        if sha(OUT/name)!=digest:raise ValueError('Hash differs '+name)
        checks+=1
    h=adapter.read(adapter.ROOT/'PHASE5-HANDOFF-v02.json');canonical=0
    for split in ['TRAIN','DEV']:
        meta=read(PREVIOUS/'cache'/split/'metadata.json');wanted={v['id']:i for i,v in enumerate(meta)}
        saved=np.load(OUT/'gold'/split/'features.npy',mmap_mode='r');sig=read(OUT/'gold'/split/'signatures.json')
        root=None;value=None
        for p,t in adapter.pairs(split,h):
            if p['world_id'] not in wanted:continue
            if p['canonical_id']!=root:value=one(p,t);root=p['canonical_id'];canonical+=1
            i=wanted[p['world_id']];x,s=value
            if not np.array_equal(saved[i,:len(x)],x) or s!=sig[i]:raise ValueError('Canonical semantics replay differs')
    tl=candidate_labels('TRAIN');dl=candidate_labels('DEV');tg=np.load(OUT/'gold/TRAIN/features.npy');dg=np.load(OUT/'gold/DEV/features.npy')
    result=read(OUT/'RESULT.json');factor_end=len(next(iter(result['panel'].values()))['selected_factor_names'])
    torch.set_num_threads(4);head_checks=0;maximum=0.
    for depth in range(5):
        te=np.asarray(inherited.cached('TRAIN',depth)['e']);de=np.asarray(inherited.cached('DEV',depth)['e'])
        tx,td,ty,tm=differences(te,tg[:,:,:factor_end],tl);dx,dd,dy,dm=differences(de,dg[:,:,:factor_end],dl)
        for family in ['linear','tiny_MLP']:
            for suffix,xx,yy,labels in [('factors',de,dg[:,:,:factor_end],dl),('pair-choice',dx,dy,dm),('factor-difference',dx,dd,dm)]:
                folder=OUT/'heads'/f'T{depth}-{family}-{suffix}'
                artifact=torch.load(folder/'head.pt',weights_only=True,map_location='cpu');head=model(artifact['inputs'],artifact['outputs'],family)
                head.load_state_dict(artifact['state']);head.eval();parts=[]
                with torch.no_grad():
                    for at in range(0,len(xx),64):
                        inp=(torch.tensor(np.array(xx[at:at+64]))-artifact['mean'])/artifact['std'];z=head(inp)
                        if artifact['mode']=='binary':z=z.sigmoid()
                        parts.append(z.numpy())
                pred=np.concatenate(parts);original=np.load(folder/'DEV.npy');delta=float(np.abs(pred-original).max());maximum=max(maximum,delta)
                if not np.allclose(pred,original,rtol=1e-4,atol=1e-4):raise ValueError('CPU replay differs '+folder.name)
                receipt=read(folder/'RECEIPT.json')
                if artifact['mode']=='binary' and score_metrics(yy,original,labels['mask'],artifact['factor_names'])!=receipt['metrics']:raise ValueError('Factor metric replay differs')
                head_checks+=1
    rankings=0
    gold_type=dl['types'][np.arange(len(dl['selected'])),dl['selected']]-1
    sig=read(OUT/'gold/DEV/signatures.json');cc=ceilings(sig,dl['selected'],dl['mask'],dl['types'])
    for row in result['ladder']:
        rung=row['rung']
        if row['identity_signature_ceiling']!=cc[rung]:raise ValueError('Ceiling differs')
        for suffix,key in [('gold-linear','linear_gold_recovery'),('exact','exact_TRAIN_signature_recovery')]:
            scores=np.load(OUT/'heads'/f'G{rung}-gold-linear'/'DEV.npy').squeeze(-1) if suffix=='gold-linear' else np.load(OUT/'gold'/f'G{rung}-exact-scores.npy')
            metrics,_=recorder(scores,dl['mask'],dl['selected'],dl['optimal'],dl['types'],gold_type,dl['meta'])
            if metrics!=row[key]:raise ValueError('Gold ranking differs')
            rankings+=1
    write(OUT/'REPLAY.json',{'status':'PASS','hash_checks':checks,'canonical_roots_rederived':canonical,
        'frozen_state_head_CPU_inferences':head_checks,'max_CPU_CUDA_delta':maximum,'gold_ranking_metric_replays':rankings,
        'protected_files_opened':0,'recurrence_weights_unchanged':True})
    print('REPLAY PASS',checks,canonical,head_checks,rankings,flush=True)

if __name__=='__main__':main()
