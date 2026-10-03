"""Full core construction. Failures are recorded; the seal is a separate step."""
import multiprocessing as mp,time
from collections import Counter
from common import *
from generation import build_root,public
from checks import check,mutation_tests

SHARD=250

def worker(job):
    split,start,end=job;shard=start//SHARD
    truthdir='protected/evaluation-truth' if split=='EVAL' else 'data'
    path=OUTPUT/truthdir/split/f'part-{shard:04d}.jsonl.gz'
    inp=OUTPUT/'public'/split/f'part-{shard:04d}.jsonl.gz'
    meta=[];fail=[];t0=time.perf_counter();maxc=0;attempts=0
    with gz_writer(path) as f,gz_writer(inp) as g:
        for index in range(start,end):
            rows,attempt=build_root(split,index);attempts+=attempt
            for row in rows:
                bad=check(row)
                if bad:raise ValueError(f'{split}:{index} gate failures {bad}')
                maxc=max(maxc,len(row['ACTION_POLICY']['available_actions']))
                emit(f,row);emit(g,public(row))
            first=rows[0]
            meta.append({'canonical_id':first['META']['canonical_id'],'structural_id':first['META']['structural_id'],
              'textual_ids':[r['META']['textual_id'] for r in rows],
              'cell':first['META']['curriculum_cell'],'target':first['SUPERVISION_ABI']['core_targets'],
              'axes':first['CAPABILITY_AXES'],'bookkeeping':first['BOOKKEEPING'],
              'candidate_count':len(first['ACTION_POLICY']['available_actions']),
              'action_eligible':first['SUPERVISION_ABI']['selected_action_eligible']})
    receipt={'split':split,'start':start,'end':end,'canonical_roots':len(meta),'rows':2*len(meta),
             'row_checks':2*len(meta),'rejected_generation_attempts':attempts,'max_candidates':maxc,
             'seconds':time.perf_counter()-t0,'files':{str(p.relative_to(OUTPUT)):sha(p) for p in (path,inp)},
             'roots':meta}
    write(OUTPUT/'receipts/shards'/f'{split}-{shard:04d}.json',receipt)
    return {'split':split,'shard':shard,'roots':len(meta),'seconds':receipt['seconds']}

def main():
    if os.environ.get('PYTHONHASHSEED')!='0':raise ValueError('Generation requires PYTHONHASHSEED=0')
    spec=freeze_build();t=time.perf_counter()
    fixture=build_root('SEAL-FIXTURE',0)[0][0]
    mutations=mutation_tests(fixture)
    if not all(mutations.values()):raise ValueError('Gate mutation sensitivity failed')
    write(OUTPUT/'receipts/MUTATION-TESTS.json',mutations)
    jobs=[(s,i,min(i+SHARD,n)) for s,n in BUDGET.items() for i in range(0,n,SHARD)]
    procs=min(8,max(1,(os.cpu_count() or 4)//2))
    with mp.Pool(procs) as pool:
        for k,r in enumerate(pool.imap_unordered(worker,jobs),1):
            if k%4==0 or k==len(jobs):print(json.dumps({'shards_done':k,'of':len(jobs),'last':r}),flush=True)
    canonical={};struct={};text={};cell=Counter();target={s:{} for s in BUDGET};bk=Counter();maxc=0
    axes={s:{a:Counter() for a in AXES} for s in BUDGET};joint={s:Counter() for s in BUDGET}
    for p in sorted((OUTPUT/'receipts/shards').glob('*.json')):
        r=read(p);s=r['split'];maxc=max(maxc,r['max_candidates'])
        for root in r['roots']:
            for key,seen,ids in [('canonical',canonical,[root['canonical_id']]),('structural',struct,[root['structural_id']]),('context',text,root['textual_ids'])]:
                for identity in ids:
                    if identity in seen:raise ValueError(f'{key} duplicate across/root within split: {identity}')
                    seen[identity]=s
            cell[(s,root['cell'])]+=1
            for name,y in root['target'].items():target[s].setdefault(name,Counter())[str(y)]+=1
            for a,v in root['axes'].items():axes[s][a][canonical_json(v)]+=1
            bk['roots']+=1;bk['eligible']+=root['bookkeeping']['eligible_facts']>0
            bk['intervened']+=bool(root['bookkeeping']['hidden_irrelevant_facts'])
            joint[s][canonical_json([root['target']['missing_cardinality'],root['bookkeeping']['after_hidden_count']])]+=1
    if bk['intervened']==0:raise ValueError('No actual bookkeeping interventions')
    for s in BUDGET:
        values={}
        for key in joint[s]:
            missing,hidden=json.loads(key);values.setdefault(missing,set()).add(hidden)
        if any(len(v)<2 for v in values.values()):raise ValueError('Bookkeeping counter not decoupled in '+s)
    def power(c):return {k:{'n':n,'status':'SUPPORTED_COUNT' if n>=200 else 'UNDERPOWERED'} for k,n in c.items()}
    census={'canonical_roots':BUDGET,'rendered_rows':{s:2*n for s,n in BUDGET.items()},'max_candidates':maxc,
       'targets':target,'DEV_support_status':{k:power(v) for k,v in target['DEV'].items()},
       'cell_counts':{'|'.join(k):v for k,v in cell.items()},'capability_axis_census':axes,
       'bookkeeping':bk,'cross_split_or_within_split_root_duplicates':0,'context_duplicates':0,
       'missing_vs_total_hidden_joint_counts':joint,'bookkeeping_decoupling_gate':'PASS: per-class multiple total-hidden counts; reverse intervention replay on all affected rows',
       'source_hashes_verified':verify_spec()['source_hashes'],'construction_seconds':time.perf_counter()-t}
    write(OUTPUT/'CENSUS.json',census)
    print(json.dumps({'status':'CONSTRUCTED_NOT_YET_SEALED','seconds':census['construction_seconds']}),flush=True)

if __name__=='__main__':main()
