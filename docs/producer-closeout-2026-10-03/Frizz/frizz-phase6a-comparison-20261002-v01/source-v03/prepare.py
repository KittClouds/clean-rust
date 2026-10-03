"""Freeze source, artifact identity and pairs before any DEV diagnostic scoring."""
import shutil
import time
import torch
from common import SOURCE,OUT,P5,BRIDGE,read,sha,receipt,weights,setup,new_model,config
from pairs import targets
import readouts as ro


def freeze():
    OUT.mkdir(exist_ok=False);snapshot=OUT/'source';snapshot.mkdir()
    for p in SOURCE.iterdir():
        if p.is_file() and p.suffix in ('.py','.md'):
            shutil.copy2(p,snapshot/p.name)
    prior=read(P5/'LANE-SEAL-VERIFIED.json')
    if prior['status']!='PASS' or sha(P5/'LANE-SEALED.json')!=prior['seal_sha256']:
        raise ValueError('Phase5 seal mismatch')
    inputs={str(P5/'LANE-SEALED.json'):sha(P5/'LANE-SEALED.json')}
    for arm in ('bridge','E'):
        for phenotype in ('init','trained'):
            p=weights(arm,phenotype);inputs[str(p)]=sha(p)
            for mode in ('c','cs','e'):
                for family in ('linear','mlp'):
                    p=P5/arm/'recorder-v01'/phenotype/f'candidate_satisfies_goal-{mode}-{family}.json'
                    inputs[str(p)]=sha(p)
    for split in ('TRAIN','DEV'):
        p=BRIDGE/f'{split}-dataset.pt';inputs[str(p)]=sha(p)
    receipt(OUT/'SPECIFICATION.json',{'status':'FROZEN_BEFORE_DEV_DIAGNOSTICS',
        'source_hashes':{p.name:sha(p) for p in snapshot.iterdir()},'frozen_inputs':inputs,
        'panel':'2 artifacts x 2 phenotypes x 3 surfaces x 2 families x 5 targets',
        'epochs':4,'seed':0,'batch_roots':64,'lr':.001,'weight_decay':.01,
        'evaluation_opened':False,'F_automatic':False})


def caches():
    config();d=setup();started=time.perf_counter()
    for split,data in d.items():
        t=targets(data);path=OUT/f'{split}-targets.pt';torch.save(t,path)
        receipt(path.with_suffix('.json'),{'sha256':sha(path),'roots':len(t['mask']),
            'pair_construction':'pairs.py frozen before DEV scores','selected_roots':int(t['selected_eligible'].sum()),
            'optimal_roots':int(t['optimal_eligible'].sum()),'evaluation_opened':False})
    for arm in ('bridge','E'):
        for phenotype in ('init','trained'):
            model=new_model(arm,d['TRAIN']['classes'])
            model.load_state_dict(torch.load(weights(arm,phenotype),weights_only=True));model.eval()
            for split,data in d.items():
                value=ro.cache(model,data);path=OUT/f'{arm}-{phenotype}-{split}.pt'
                torch.save(value,path)
                receipt(path.with_suffix('.json'),{'sha256':sha(path),
                    'checkpoint_sha256':sha(weights(arm,phenotype)),
                    'state_widths':{'c':256,'cs':320,'e':32},'evaluation_opened':False})
            del model
    receipt(OUT/'caches-complete.json',{'status':'CACHES_AND_PAIRS_COMPLETE',
        'seconds':time.perf_counter()-started,'evaluation_opened':False})


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');args=p.parse_args()
    if args.freeze:
        freeze()
    else:
        caches()
