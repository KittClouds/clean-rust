"""Separate-process full seed, semantic, transition and public-boundary replay.

This is an independent execution/verifier path, not an independent author or
an unrelated semantic implementation. Simulator/refsim transition parity is
checked separately. No neural weights or historical protected truth are read.
"""
import multiprocessing as mp,time,itertools
from collections import Counter
from common import *
from generation import build_root,public
from checks import check

def replay_shard(job):
    split,truth,visible=job;t=time.perf_counter();roots=[];checks=0
    source=iter_rows(OUTPUT/truth);pub=iter_rows(OUTPUT/visible)
    for pair in itertools.zip_longest(*[source]*2):
        a,b=pair
        if a is None or b is None:raise ValueError('Incomplete renderer family')
        if a['META']['canonical_id']!=b['META']['canonical_id']:raise ValueError('Pair root mismatch')
        expected,_=build_root(split,a['META']['generation_index'])
        for row,want in zip((a,b),expected):
            if canonical_json(row)!=canonical_json(want):raise ValueError('Root seed replay mismatch '+row['world_id'])
            errs=check(row)
            if errs:raise ValueError(errs)
            actual=next(pub,None)
            if actual!=public(row):raise ValueError('Public projection mismatch')
            checks+=1
        if a['SUPERVISION_ABI']!=b['SUPERVISION_ABI']:raise ValueError('Pair supervision differs')
        roots.append({'canonical':a['META']['canonical_id'],'structural':a['META']['structural_id'],
                      'contexts':[a['META']['textual_id'],b['META']['textual_id']]})
    if next(pub,None) is not None:raise ValueError('Extra public row')
    return {'split':split,'rows':checks,'roots':roots,'seconds':time.perf_counter()-t}

def main():
    if os.environ.get('PYTHONHASHSEED')!='0':raise ValueError('Replay requires PYTHONHASHSEED=0')
    t=time.perf_counter();spec=verify_spec();manifest=read(OUTPUT/'RELEASE-MANIFEST.json')
    for name,h in manifest['files'].items():
        if sha(OUTPUT/name)!=h:raise ValueError('Manifest hash mismatch '+name)
    jobs=[]
    for s in BUDGET:
        prefix='protected/evaluation-truth' if s=='EVAL' else 'data'
        for p in sorted((OUTPUT/prefix/s).glob('*.gz')):
            jobs.append((s,str(p.relative_to(OUTPUT)),str((OUTPUT/'public'/s/p.name).relative_to(OUTPUT))))
    counts=Counter();rootcounts=Counter();seen=[set(),set(),set()];done=0
    with mp.Pool(8) as pool:
        for r in pool.imap_unordered(replay_shard,jobs):
            counts[r['split']]+=r['rows'];rootcounts[r['split']]+=len(r['roots'])
            for root in r['roots']:
                for values,registry in zip(([root['canonical']],[root['structural']],root['contexts']),seen):
                    for value in values:
                        if value in registry:raise ValueError('Duplicate root/context in independent replay')
                        registry.add(value)
            done+=1
            if done%8==0 or done==len(jobs):print('independent replay shards',done,'/',len(jobs),flush=True)
    if dict(rootcounts)!=BUDGET or dict(counts)!={s:2*n for s,n in BUDGET.items()}:
        raise ValueError('Release populations mismatch')
    receipt={'status':'PASS','role':'BANK_CONSTRUCTION_SEAL_REPLAY','manifest_sha256':sha(OUTPUT/'RELEASE-MANIFEST.json'),
      'roots':dict(rootcounts),'rows':dict(counts),'seed_replay_coverage':1.,'semantic_gate_coverage':1.,
      'public_projection_coverage':1.,'duplicate_roots_or_contexts':0,'protected_truth_scope':'new core EVAL construction only',
      'old_protected_truth_opened':False,'model_contact':False,'seconds':time.perf_counter()-t,
      'independence':'separate execution and verification path; shared pinned generator, independent refsim action parity',
      'source_identity':spec['source_hashes']}
    write(OUTPUT/'INDEPENDENT-REPLAY.json',receipt)
    print(json.dumps({'status':'INDEPENDENT_REPLAY_PASS','seconds':receipt['seconds']}),flush=True)

if __name__=='__main__':main()
