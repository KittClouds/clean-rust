"""Candidate semantics: never reads EVAL and never exports gold as runtime input."""
from b6_contract import *
from collections import Counter,defaultdict

def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':'))

def one(p,t):
    abi=adapter.align(p,t);sm=algebra.sim_of(t);goal=sm.goal_key
    ents={e['id']:e['type'] for e in t['WORLD_TRUTH']['entities']};actor=t['WORLD_TRUTH'].get('actor')
    gargs=t['WORLD_TRUTH']['goal']['args'];req=t['WORLD_TRUTH']['goal']['required_facts']['query']
    def obligations(state,tick):
        return sum(any(all(sm.eff_has(state,tick,facts.key(t['fact_table'][fid])) for fid in alt)
            for alt in q['support_alternatives']) for q in req)
    initial=obligations(sm.base0,0);features=[];signatures=[[] for _ in range(7)]
    for raw,c in zip(p['actions'],abi['candidates']):
        a=sm.by_id[raw['id']];legal=sm.legal(sm.base0,0,a)
        if legal!=c['candidate_legal']:raise ValueError('Legal replay mismatch')
        next_=sm.apply(sm.base0,a) if legal else sm.base0
        immediate=bool(legal and sm.goal_holds(next_,1))
        if immediate!=c['candidate_satisfies_goal']:raise ValueError('Goal replay mismatch')
        values=list(raw['args'].values());actor_match=any(raw['args'].get(k)==actor for k in ['agent','from','to'])
        goal_match=sum(v in gargs for v in values)/max(1,len(values))
        dest=any(raw['args'].get(k) in gargs for k in ['dst','target','at'])
        pre=sum(sm.eff_has(sm.base0,0,k) for k in a.pre)/max(1,len(a.pre)) if a.pre else 1.
        neg=all(not sm.eff_has(sm.base0,0,k) for k in a.neg)
        add=goal in a.add if goal else False;remove=goal in a.rm if goal else False
        def match(state):
            if not goal:return 0.
            keys=[k for k in state if k[0]==goal[0] and len(k)==len(goal)]
            return max([sum(x==y for x,y in zip(k[1:],goal[1:]))/max(1,len(goal)-1) for k in keys] or [0.])
        gain=match(next_)-match(sm.base0) if legal else 0.
        obgain=(obligations(next_,1)-initial)/max(1,len(req)) if legal else 0.
        v=[float(legal),float(immediate),float(actor_match),float(goal_match),float(dest),float(pre),float(neg),float(add),float(remove),
           float((gain+1)/2),float((obgain+1)/2),float(c['on_environment_shortest_path'])]
        features.append(v)
        parts=[raw['type'],bool(legal),immediate,
            {'args':raw['args'],'types':{k:ents.get(value,'UNKNOWN') for k,value in raw['args'].items()},'role':v[2:5]},
            {'pre':a.pre,'neg':a.neg,'add':a.add,'rm':a.rm,'pre_live':v[5:9]},
            {'goal_change':v[9],'obligation_change':v[10]},
            {'shortest_first':bool(c['on_environment_shortest_path'])}]
        for rung in range(7):signatures[rung].append(canon(parts[:rung+1]))
    # Full argument/effect identity signatures can be unique without being decision-relevant.
    return np.asarray(features,np.float32),signatures

def build():
    if (OUT/'GOLD-RECEIPT.json').exists():return read(OUT/'GOLD-RECEIPT.json')
    start=time.perf_counter();h=adapter.read(adapter.ROOT/'PHASE5-HANDOFF-v02.json');receipt={}
    for split in ['TRAIN','DEV']:
        folder=OUT/'gold'/split;folder.mkdir(parents=True,exist_ok=True)
        ids=np.load(PREVIOUS/'cache'/split/'ids.npy');source_meta=read(PREVIOUS/'cache'/split/'metadata.json')
        want={m['id']:i for i,m in enumerate(source_meta)};x=np.zeros((len(ids),171,len(NAMES)),np.float32)
        sig=[None]*len(ids);last_root=None;prior=None;count=0
        for p,t in adapter.pairs(split,h):
            if p['world_id'] not in want:continue
            i=want[p['world_id']];root=p['canonical_id']
            if root!=last_root:prior=one(p,t);last_root=root;count+=1
            values,signature=prior
            if [a['id'] for a in p['actions']]!=source_meta[i]['action_ids']:raise ValueError('Candidate join mismatch')
            x[i,:len(values)]=values;sig[i]=signature
            if count%250==0 and i%2==0:print('GOLD',split,count,flush=True)
        if any(s is None for s in sig):raise ValueError('Missing sourceable gold row')
        np.save(folder/'features.npy',x);write(folder/'signatures.json',sig)
        receipt[split]={'rows':len(ids),'roots':count,'candidates':int(np.load(PREVIOUS/'cache'/split/'mask.npy').sum()),'factor_names':NAMES,
           'same_root_renderer_semantics_reused_after_candidate_id_check':True}
    result={'splits':receipt,'seconds':time.perf_counter()-start,'simulator_label_checks':'all eligible candidates legality and immediate goal exact',
        'G6_source':'SUPERVISION_ABI.candidates.on_environment_shortest_path, endpoint-derived oracle diagnostic only',
        'unavailable':'candidate-specific information/policy reason beyond canonical permitted/shortest fields; no invented reason labels',
        'protected_files_opened':0}
    write(OUT/'GOLD-RECEIPT.json',result);return result

def ceilings(signatures,selected,mask,types):
    result=[]
    for rung in range(7):
        collisions=[];same=[]
        for i,a in enumerate(selected):
            own=signatures[i][rung];s=own[a];ix=[j for j in range(int(mask[i].sum())) if own[j]==s]
            collisions.append(len(ix));same.append(sum(types[i,j]==types[i,a] for j in ix))
        result.append({'rung':rung,'rows':len(selected),'roots':len(selected)//2,
            'full_selected_signature_tie_ceiling':float(np.mean(1/np.array(collisions))),
            'same_type_selected_signature_tie_ceiling':float(np.mean(1/np.array(same))),
            'selected_collision_rows':sum(v>1 for v in collisions),'same_type_collision_rows':sum(v>1 for v in same),
            'collision_histogram':dict(sorted(Counter(map(str,collisions)).items())),
            'identity_warning':rung>=3})
    return result

def exact_scores(train_sig,dev_sig,tl,dl,rung):
    table=defaultdict(lambda:[0,0]);total=0;positive=0
    for i in range(0,len(tl['selected']),2):
        for j in range(int(tl['mask'][i].sum())):
            key=train_sig[i][rung][j];table[key][1]+=1;table[key][0]+=int(j==tl['selected'][i]);total+=1;positive+=int(j==tl['selected'][i])
    prior=positive/total;scores=np.zeros(dl['mask'].shape,np.float32);seen=0
    for i in range(len(dl['selected'])):
        for j,key in enumerate(dev_sig[i][rung]):
            pos,n=table.get(key,(0,0));seen+=n>0;scores[i,j]=(pos+prior)/(n+1)
    return scores,{'TRAIN_signature_count':len(table),'DEV_candidate_seen_fraction':seen/int(dl['mask'].sum()),'smoothing_prior':prior}
