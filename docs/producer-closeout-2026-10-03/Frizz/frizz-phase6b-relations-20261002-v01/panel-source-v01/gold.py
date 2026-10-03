"""Canonical same-type factors, counterfactual planner and descriptor collisions."""
import collections,itertools,time
import torch
from common import OUT,BANK,P6,A,F,rows,sha,read,receipt,lockcheck

FAMILIES=('legality','immediate_goal','argument_goal','preconditions','effects_goal','obligations','transition_distance')


def factors(r):
    sm=A.sim_of(r);wt=r['WORLD_TRUTH'];g=sm.goal_key
    entity_ids={e['id'] for e in wt['entities']};goal_entities=[x for x in wt['goal']['args'] if x in entity_ids]
    actor=wt['actor'];reqs=wt['goal']['required_facts']['query'];facts=r['fact_table']
    result={f:[] for f in FAMILIES};identity=[]
    for raw,c in zip(r['ACTION_POLICY']['available_actions'],r['SUPERVISION_ABI']['candidates'],strict=True):
        a=sm.by_id[raw['id']];legal=sm.legal(sm.base0,0,a)
        if legal!=c['candidate_legal']:raise ValueError('canonical legality mismatch')
        post=sm.apply(sm.base0,a) if legal else sm.base0
        immediate=bool(legal and sm.goal_holds(post,1))
        if immediate!=c['candidate_satisfies_goal']:raise ValueError('canonical immediate-goal mismatch')
        args=[raw['args'][k] for k in sorted(raw['args'])];args+=['NONE']*(4-len(args))
        result['legality'].append([int(legal),int(c['candidate_permitted'])])
        result['immediate_goal'].append([int(immediate)])
        result['argument_goal'].append([int(x==actor) for x in args]+[
            int(j<len(goal_entities) and x==goal_entities[j]) for x in args for j in range(4)])
        pre=[sm.eff_has(sm.base0,0,k) for k in a.pre];neg=[not sm.eff_has(sm.base0,0,k) for k in a.neg]
        if len(pre)>8 or len(neg)>2:raise ValueError('precondition signature width exceeded')
        result['preconditions'].append([int(x) for x in pre]+[-1]*(8-len(pre))+[int(x) for x in neg]+[-1]*(2-len(neg)))
        result['effects_goal'].append([int(g in a.add),int(g in a.rm),
            sum(k[0]==(g[0] if g else None) for k in a.add),
            sum(any(x in goal_entities for x in k[1:]) for k in a.add),
            sum(any(x in goal_entities for x in k[1:]) for k in a.rm)])
        satisfaction=[]
        for q in reqs:
            satisfaction.append(any(all(sm.eff_has(post,1,F.key(facts[f])) for f in alt)
                                    for alt in q['support_alternatives']))
        result['obligations'].append([sum(satisfaction),len(satisfaction)-sum(satisfaction)])
        if legal:
            search=sm.search(cap_depth=8,max_states=40000,facts0=post,t0=1)
            distance=search['depth'] if search['status']=='SOLVED' else 9 if search['status']=='UNSAT_EXHAUSTED' else 10
        else:distance=11
        result['transition_distance'].append([distance])
        identity.append(tuple((k,raw['args'][k]) for k in sorted(raw['args'])))
    return result,identity


def collision_stats(records,subset):
    reciprocal=[];unique=0;collisions=0;pairtotal=0;distinguished=0;sizes=[]
    for r in records:
        selected=r['selected'];same=r['same'];f=r['factors']
        def key(j):return tuple(v for name in subset for v in f[name][j])
        chosen=key(selected);n=sum(key(j)==chosen for j in same)
        reciprocal.append(1/n);unique+=n==1;collisions+=n-1;sizes.append(n)
        for j in same:
            if j!=selected:pairtotal+=1;distinguished+=key(j)!=chosen
    n=len(records)
    return {'roots':n,'oracle_tie_top1':sum(reciprocal)/n,
        'unique_selected_roots':unique,'unique_fraction':unique/n,
        'remaining_collision_candidates':collisions,'same_type_pairs':pairtotal,
        'distinguished_pairs':distinguished,'distinguished_fraction':distinguished/pairtotal,
        'scope':'root-conditional descriptor tie ceiling, NOT a learned accuracy or universal decision determinism ceiling'}


def load_records(split):
    h=read(BANK/'PHASE5-HANDOFF-v02.json');records=[]
    t=torch.load(P6/f'{split}-targets.pt',mmap=True,weights_only=False)
    index={cid:i for i,cid in enumerate(t['canonical_ids'])};seen=set()
    for name,digest in h['splits'][split]['supervision_files'].items():
        if sha(BANK/name)!=digest:raise ValueError('canonical shard drift')
        for r in rows(BANK/name):
            cid=r['META']['canonical_id']
            if cid in seen:continue
            seen.add(cid);i=index[cid]
            if not t['selected_eligible'][i]:continue
            selected=int(t['selected'][i]);acts=r['ACTION_POLICY']['available_actions']
            same=[j for j,a in enumerate(acts) if a['type']==acts[selected]['type']]
            f,identity=factors(r)
            records.append({'root_index':i,'canonical_id':cid,'selected':selected,'same':same,
                'factors':f,'identity':identity,'candidate_count':len(acts),'selected_type':acts[selected]['type']})
    return records


def inventory(records):
    frequency={};co=collections.Counter()
    for family in FAMILIES:
        frequency[family]=collision_stats(records,[family])
    for r in records:
        s=r['selected']
        for j in r['same']:
            if j==s:continue
            different=[f for f in FAMILIES if r['factors'][f][s]!=r['factors'][f][j]]
            for a,b in itertools.combinations(different,2):co[a+' & '+b]+=1
    return {'families':frequency,'co_occurrence_pair_counts':dict(co),
        'unavailable':['candidate-specific evidence support/counterevidence labels'],
        'obligation_definition':'canonical initial support_alternatives truth after candidate tick1, not a new normative policy target'}


def main():
    lockcheck();start=time.perf_counter();all_records={}
    for split in ('TRAIN','DEV'):
        records=load_records(split);all_records[split]=records
        p=OUT/f'{split}-gold.pt';torch.save(records,p)
        receipt(p.with_suffix('.json'),{'sha256':sha(p),'eligible_roots':len(records),'evaluation_opened':False})
    ladder={};earned=[];first=None;old=0
    for split,records in all_records.items():
        rungs={'type_only':collision_stats(records,[])}
        for i,name in enumerate(FAMILIES):rungs[name]=collision_stats(records,FAMILIES[:i+1])
        ladder[split]=rungs
    train=ladder['TRAIN'];old=train['type_only']['oracle_tie_top1']
    for family in FAMILIES:
        cur=train[family]['oracle_tie_top1']
        if cur-old>=.05:earned.append(family)
        if first is None and cur>=.95 and train[family]['unique_fraction']>=.90:first=family
        old=cur
    if first and first not in earned:earned.append(first)
    receipt(OUT/'gold-audit.json',{'status':'GOLD_SAME_TYPE_AUDIT_COMPLETE','ladder':ladder,
        'inventory':{s:inventory(r) for s,r in all_records.items()},'earned_families_TRAIN_only':earned,
        'first_sufficient_prefix_family_TRAIN':first,'rung_order':list(FAMILIES),'seconds':time.perf_counter()-start,
        'identity_control':'opaque argument tuples distinguish candidates by construction; excluded from semantic sufficiency claims',
        'critical_caveat':'Unique descriptors are not a choice rule. Counterfactual remaining-distance computation is expensive gold planning, not observable cheap supervision.',
        'evaluation_opened':False})
    print('GOLD_COMPLETE '+str(earned)+' first='+str(first),flush=True)


if __name__=='__main__':main()
