"""Pin the design, materialize strict labels, and rescore binary outputs FIRST."""
import shutil
from common import *
from metrics import assess

def freeze():
    OUT.mkdir(exist_ok=False,parents=True)
    files=[F6/'PHASE6F-SEALED.json',F6/'seal-replay.json',F6/'OBSERVATION-CONTRACT.json',F6/'clauses.jsonl.gz',F6/'results.json',
           D6/'DEV-gate-logits.pt',D6/'DEV-gate-logits.json',C6/'DEV-predictions.pt',C6/'DEV-predictions.json',A6/'DEV-targets.pt',A6/'DEV-targets.json',
           D6/'source-v02/legal_metrics.py',E6/'PHASE6E-SEALED.json',E6/'seal-replay.json']
    for s in ('TRAIN','DEV'):
        for stem in ('ABI','targets'):files.extend([C6/f'{s}-{stem}.pt',C6/f'{s}-{stem}.json'])
    for p in sorted((E6/'panel').glob('*.pt')):files.extend([p,p.with_suffix('.json')])
    files.extend([E6/'pilot/final-predictions.pt',E6/'pilot/final-predictions.json'])
    # Inherit all model and source pins without opening a backbone/checkpoint.
    files.extend(Path(p) for p in read(F6/'SPECIFICATION.json')['inputs'])
    sources={p.name:sha(p) for p in HERE.iterdir() if p.suffix in ('.py','.md')}
    receipt(OUT/'SPECIFICATION.json',{'inputs':{str(p):sha(p) for p in files},'sources':sources,
        'ABI_width':365,'target_labels':LABELS,'epochs':12,'fixed_seed':0,'material_root_exact_delta':.05,
        'comparison_arm':'D_trained','observation_contract_sha256':sha(F6/'OBSERVATION-CONTRACT.json'),
        'protected_evaluation_opened':False})
    folder=OUT/'source-v01';folder.mkdir()
    for n in sources:shutil.copy2(HERE/n,folder/n)

def targets():
    abi={s:load(C6/f'{s}-ABI.pt') for s in ('TRAIN','DEV')}
    maps={};out={}
    for s,a in abi.items():
        maps[s]={(cid,a['renderer'][2*i+j]):2*i+j for i,cid in enumerate(a['canonical_ids']) for j in (0,1)}
        out[s]={'status':torch.full_like(a['types'],-1,dtype=torch.long),'canonical':torch.zeros_like(a['mask']),
                'mask':a['mask'].clone()}
    with gzip.open(F6/'clauses.jsonl.gz','rt',encoding='utf-8') as f:
        for line in f:
            c=json.loads(line);s=c['split'];i=maps[s][c['root'],c['renderer']];j=c['index'];a=abi[s]
            if out[s]['status'][i,j]!=-1:raise ValueError('duplicate clause join')
            if not a['mask'][i,j]:raise ValueError('clause outside exhaustive mask')
            out[s]['status'][i,j]=LABELS.index(c['strict_status']);out[s]['canonical'][i,j]=c['canonical_legal']
    census={}
    for s,t in out.items():
        a=abi[s];expected=1333 if s=='TRAIN' else 333
        if len(a['canonical_ids'])!=expected or ((t['status']>=0)!=t['mask']).any():raise ValueError('target population shape')
        if not torch.equal(t['status'][::2],t['status'][1::2]):raise ValueError('renderer target differences')
        old=load(C6/f'{s}-targets.pt');truth=old['mask']&(old['category']>=0)&(old['category']<11)
        if not torch.equal(truth,t['canonical']):raise ValueError('canonical diagnostic truth drift')
        save(OUT/f'{s}-targets.pt',t)
        census[s]={'roots':expected,'renderings':2*expected,'canonical_candidates':int(t['mask'][::2].sum()),
            'class_counts_primary':dict(zip(LABELS,torch.bincount(t['status'][::2][t['mask'][::2]],minlength=3).tolist())),
            'strict_only':True,'canonical_truth_loss':False}
    receipt(OUT/'target-derivation.json',{'source_sha256':sha(F6/'clauses.jsonl.gz'),'observation_contract_sha256':sha(F6/'OBSERVATION-CONTRACT.json'),
        'census':census,'joins':'canonical root, renderer, candidate index; exhaustive mask and canonical truth checked','paired_statuses_exact':True})
    return abi,out

def main():
    setup();freeze();a,t=targets();old=load(A6/'DEV-targets.pt');end={k:old[k][a['DEV']['root_indices']] for k in ('selected','selected_eligible','optimal','optimal_eligible')}
    cost=load(C6/'DEV-predictions.pt')['trained']['cost'];result={}
    for name,logits in binary_panel().items():
        pred=torch.where(logits>0,0,1);result[name]=assess(pred,t['DEV'],a['DEV'],cost,end)
    receipt(OUT/'binary-baselines.json',{'arms':result,'fit_started':False,'threshold_logit':0,'abstention_supported':False,
        'panel_selection':False,'comparison_arm':'D_trained','protected_evaluation_opened':False})
    print('TARGETS AND BINARY BASELINES COMPLETE, NO FIT YET',flush=True)
if __name__=='__main__':main()
