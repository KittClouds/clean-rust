"""Clause census, equivalence classes, certified oracle and hidden witnesses."""
from collections import Counter,defaultdict
import math
from common import *
from observation import *
from counterfactual import find

class Stream:
    def __init__(self,name,replay):
        self.p=OUT/name;self.replay=replay
        self.f=gzip.open(self.p,'rt' if replay else 'xt',encoding='utf-8');self.count=0;self.h=hashlib.sha256()
    def put(self,x):
        line=canonical(x);self.h.update((line+'\n').encode());self.count+=1
        if self.replay:
            old=self.f.readline()
            if not old or canonical(json.loads(old))!=line:raise ValueError('stream replay '+str(self.p)+' row '+str(self.count))
        else:self.f.write(line+'\n')
    def close(self):
        if self.replay and self.f.readline():raise ValueError('extra stream rows')
        self.f.close();return {'rows':self.count,'semantic_content_sha256':self.h.hexdigest()}

def collision(classes,root_count):
    total=sum(len(v) for v in classes.values());ambiguous=0;roots=set();selected=0;records=[];correct=0
    for key,items in sorted(classes.items()):
        pos=sum(v['legal'] for v in items);neg=len(items)-pos;correct+=max(pos,neg)
        if pos and neg:
            ambiguous+=len(items);roots.update(v['root'] for v in items);selected+=sum(v['selected'] for v in items)
        p=pos/len(items);entropy=0 if p in (0,1) else -p*math.log2(p)-(1-p)*math.log2(1-p)
        records.append({'signature':key,'count':len(items),'legal':pos,'illegal':neg,'entropy_bits':entropy,
            'roots':len({v['root'] for v in items}),'renderers':dict(Counter(v['renderer'] for v in items))})
    return {'instances':total,'classes':len(classes),'ambiguous_candidates':ambiguous,
        'ambiguous_candidate_fraction':ambiguous/max(total,1),'roots_with_ambiguous_candidate':len(roots),
        'root_fraction':len(roots)/root_count,'selected_in_ambiguous_classes':selected,
        'selected_fraction':selected/(2*root_count),'empirical_candidate_scalar_accuracy_ceiling':correct/max(total,1)},records

def root_ceiling(groups):
    n=sum(len(v) for v in groups.values());correct=0;amb=0
    for values in groups.values():
        c=Counter(values);correct+=max(c.values())
        if len(c)>1:amb+=len(values)
    return {'roots':n,'classes':len(groups),'ambiguous_roots':amb,'empirical_exact_set_ceiling':correct/max(n,1)}

def analyze(replay=False):
    torch.set_num_threads(4);lock();start=time.perf_counter();streams={n:Stream(n+'.jsonl.gz',replay) for n in ('clauses','witnesses','root-partition','collision-classes')}
    report={};attribution=Counter()
    for split,expected in (('TRAIN',1333),('DEV',333)):
        semantic_classes=defaultdict(list);exact_classes=defaultdict(list);root_groups=defaultdict(list);exact_roots=defaultdict(list)
        same_groups=defaultdict(list);exact_same=defaultdict(list);augmented=defaultdict(list);augmented_same=defaultdict(list)
        counterfactual_rejections={};unbound_arguments=0
        pairs={};support=Counter();oracle_counts={'strict':Counter(),'recipe_closed_graph':Counter()};root_info={};witnesses={};raw_pair_changes=0;sem_pair_changes=0
        renderer_fields=Counter();renderer_non_rel_changes=0
        markers=0;hidden_graph=0
        # Eligibility comes ONLY from the immutable canonical population list.
        for p,r in population(split):
            replay_public(p,r);cid=r['META']['canonical_id'];slot=r['META']['renderer_slot'];sem=semantic(p,r);semhash=digest(sem);exact=digest(exact_interface(p))
            actions=p['actions'];sim=A.sim_of(r);prepared=(sim,*observable_evidence(r));labels=[sim.legal(sim.base0,0,sim.by_id[a['id']]) for a in actions]
            binding_ids={b['id'] for b in p['bindings']}
            unbound_arguments+=sum(v not in binding_ids for a in actions for v in a['args'].values())
            if labels!=[c['candidate_legal'] for c in r['SUPERVISION_ABI']['candidates']]:raise ValueError('canonical legality mismatch')
            selected=r['SUPERVISION_ABI']['selected_action_index'];selected_type=actions[selected]['type'];mask=[a['type']==selected_type for a in actions]
            statuses={'strict':[],'recipe_closed_graph':[]};unresolved=[]
            markers+=bool(r['WORLD_TRUTH']['slot_markers'])
            fk=A.fact_key_map(r);hidden_graph+=any(fk[f][0] in ('CONNECTED','BLOCKED') for f in r['OBSERVATION']['hidden_facts'])
            for i,a in enumerate(actions):
                data=[]
                for mode,closed in (('strict',False),('recipe_closed_graph',True)):
                    status,cs=oracle(r,a,closed,prepared);statuses[mode].append(status);oracle_counts[mode][status]+=1
                    if status=='CERTAIN_LEGAL':oracle_counts[mode]['correct_certain_legal']+=labels[i]
                    if status=='CERTAIN_ILLEGAL':oracle_counts[mode]['correct_certain_illegal']+=not labels[i]
                    if mode=='strict':data=cs
                if statuses['strict'][-1]=='UNRESOLVED':
                    missing=[c for c in data if c['observable'] is None]
                    unresolved.append(i)
                    for c in missing:attribution[split+':'+c['polarity']+':'+c['fact'][0]]+=1
                    if len(missing)>1:attribution[split+':multiple_unknown_clauses']+=1
                coord=sem['menu'][i];info={'root':cid,'renderer':p['renderer_family'],'legal':labels[i],'selected':i==selected}
                semantic_classes[digest([semhash,coord])].append(info);exact_classes[digest([exact,coord])].append(info)
                streams['clauses'].put({'split':split,'root':cid,'renderer':p['renderer_family'],'candidate':a['id'],'index':i,
                    'type':a['type'],'canonical_legal':labels[i],'clauses':data,'strict_status':statuses['strict'][-1],
                    'recipe_status':statuses['recipe_closed_graph'][-1],'permission_is_not_a_legality_clause':True})
            non_rel={k:v for k,v in sem.items() if k not in ('direct','reports')}
            for k in ('direct','reports'):non_rel[k]=[x for x in sem[k] if x['fact'][0]!='REL']
            pairs.setdefault(cid,[]).append({'semantic':semhash,'exact':exact,'statuses':statuses,'family':p['renderer_family'],
                'section_hashes':{k:digest(v) for k,v in sem.items()},'non_REL_observable_semantics':digest(non_rel)})
            support['rendered_rows']+=1;support['rendered_candidates']+=len(actions)
            if slot!=0:continue
            support['canonical_roots']+=1;support['canonical_candidates']+=len(actions);support['legal_candidates']+=sum(labels)
            root_groups[semhash].append(canonical(labels));exact_roots[exact].append(canonical(labels));augmented[exact].append(canonical(labels))
            same=[v for v,m in zip(labels,mask) if m];same_groups[digest([semhash,selected_type])].append(canonical(same));exact_same[digest([exact,selected_type])].append(canonical(same))
            augmented_same[digest([exact,selected_type])].append(canonical(same))
            certified=all(s!='UNRESOLVED' for s in statuses['strict']);recipe=all(s!='UNRESOLVED' for s in statuses['recipe_closed_graph'])
            w,attempts=find(p,r,counterfactual_rejections);support['counterfactual_attempts']+=attempts
            root_info[cid]={'split':split,'root':cid,'strict_certified':certified,'recipe_certified':recipe,
                'selected_type':selected_type,'strict_unresolved_candidates':len(unresolved),'counterfactual_found':bool(w)}
            if w:
                # Re-render the same alternate canonical truth in the paired family;
                # proof is not promoted until both original input channels match.
                witnesses[cid]=w
            if support['canonical_roots']%200==0:print(split+' roots '+str(support['canonical_roots']),flush=True)
        if support['canonical_roots']!=expected or support['rendered_rows']!=2*expected:raise ValueError('population support mismatch')
        witness_predicates=Counter();proven=0;selected_ambiguous=0;paired_witness_fail=0;changed_candidates=0;changed_same_type_roots=0
        # A second streaming pass joins original paired renders; no truth inference
        # is drawn from renderer IDs or generator metadata.
        for p,r in population(split):
            cid=r['META']['canonical_id']
            if r['META']['renderer_slot']!=1 or cid not in witnesses:continue
            w=witnesses[cid];alt=copy.deepcopy(w['alternate_record']);alt['world_id']=r['world_id'];alt['META']=copy.deepcopy(r['META'])
            generation.render_row(alt,r['OBSERVATION']['renderer_family_id'],r['META']['renderer_slot']);pub=generation.public(alt)
            if exact_interface(pub)!=exact_interface(p):paired_witness_fail+=1;continue
            if semantic(pub,alt)!=semantic(p,r):raise ValueError('paired witness semantic mismatch')
            proven+=1;witness_predicates[w['original_fact'][0]]+=1
            selected=r['SUPERVISION_ABI']['selected_action_index'];selected_ambiguous+=selected in w['changed_indices']
            selected_type=p['actions'][selected]['type'];changed_candidates+=len(w['changed_indices'])
            same_alt=[v for v,a in zip(w['alternate_legal_set'],p['actions']) if a['type']==selected_type]
            same_orig=[v for v,a in zip(w['original_legal_set'],p['actions']) if a['type']==selected_type]
            changed_same_type_roots+=same_alt!=same_orig
            augmented_same[digest([w['exact_interface_sha256'],selected_type])].append(canonical(same_alt))
            ri=root_info[cid];ri['verified_ambiguous']=True;ri['causal_hidden_predicate']=w['original_fact'][0]
            if ri['strict_certified']:raise ValueError('strict oracle certainty contradicted by byte-identical witness')
            augmented[w['exact_interface_sha256']].append(canonical(w['alternate_legal_set']))
            streams['witnesses'].put({'split':split,'root':cid,**w,'paired_original_public':p,'paired_alternate_public':pub,
                'paired_exact_interface_sha256':digest(exact_interface(p))})
        for cid,rs in pairs.items():
            if len(rs)!=2:raise ValueError('render pair incomplete')
            raw_pair_changes+=rs[0]['exact']!=rs[1]['exact'];sem_pair_changes+=rs[0]['semantic']!=rs[1]['semantic']
            renderer_fields.update(k for k in rs[0]['section_hashes'] if rs[0]['section_hashes'][k]!=rs[1]['section_hashes'][k])
            renderer_non_rel_changes+=rs[0]['non_REL_observable_semantics']!=rs[1]['non_REL_observable_semantics']
            if rs[0]['statuses']!=rs[1]['statuses']:raise ValueError('renderer changes oracle evidence')
            info=root_info[cid];info.setdefault('verified_ambiguous',False)
            info['partition']='VERIFIED_AMBIGUOUS' if info['verified_ambiguous'] else 'OBSERVABLE_RULE_CERTIFIED' if info['strict_certified'] else 'UNRESOLVED_NOT_CERTIFIED'
            streams['root-partition'].put(info)
        semcollision,classes=collision(semantic_classes,expected);exactcollision,exactrecords=collision(exact_classes,expected)
        for level,records in (('semantic',classes),('exact_interface',exactrecords)):
            for record in records:streams['collision-classes'].put({'split':split,'level':level,**record})
        def or_metrics(c):
            n=sum(c[s] for s in ('CERTAIN_LEGAL','CERTAIN_ILLEGAL','UNRESOLVED'))
            return {**dict(c),'coverage':(c['CERTAIN_LEGAL']+c['CERTAIN_ILLEGAL'])/n,
                'certain_legal_precision':c['correct_certain_legal']/c['CERTAIN_LEGAL'] if c['CERTAIN_LEGAL'] else None,
                'certain_illegal_precision':c['correct_certain_illegal']/c['CERTAIN_ILLEGAL'] if c['CERTAIN_ILLEGAL'] else None}
        for mode,c in oracle_counts.items():
            if c['correct_certain_legal']!=c['CERTAIN_LEGAL'] or c['correct_certain_illegal']!=c['CERTAIN_ILLEGAL']:
                raise ValueError('oracle positive-control precision failure '+split+' '+mode)
        report[split]={'supports':dict(support),'unbound_argument_occurrences':unbound_arguments,
            'counterfactual_rejections':counterfactual_rejections,
            'semantic_candidate_collisions':semcollision,'exact_candidate_coordinate_collisions':exactcollision,
            'semantic_root_ceiling':root_ceiling(root_groups),'exact_input_root_ceiling':root_ceiling(exact_roots),
            'semantic_same_type_ceiling_gold_type_conditioned':root_ceiling(same_groups),'exact_same_type_ceiling_gold_type_conditioned':root_ceiling(exact_same),
            'oracle':{m:or_metrics(c) for m,c in oracle_counts.items()},
            'strict_certified_roots':sum(i['strict_certified'] for i in root_info.values()),
            'recipe_certified_roots':sum(i['recipe_certified'] for i in root_info.values()),
            'recipe_closed_graph_assumption_valid_on_population':not(markers or hidden_graph),'unrendered_slot_marker_rows':markers,'hidden_graph_rows':hidden_graph,
            'verified_ambiguous_roots':proven,'verified_ambiguous_fraction':proven/expected,'selected_candidates_flipped_by_witness':selected_ambiguous,
            'witness_changed_candidates':changed_candidates,'witness_changed_candidate_fraction':changed_candidates/support['canonical_candidates'],
            'witness_changed_same_type_roots':changed_same_type_roots,
            'witness_hidden_predicates':dict(witness_predicates),'paired_witness_failures':paired_witness_fail,
            'augmented_counterfactual_exact_ceiling_NOT_original_bank':root_ceiling(augmented),
            'augmented_counterfactual_same_type_ceiling_NOT_original_bank':root_ceiling(augmented_same),
            'equal_root_balanced_pair_audit_ceiling_NOT_original_bank':1-.5*proven/expected,
            'renderer':{'raw_input_changes':raw_pair_changes,'semantic_class_changes':sem_pair_changes,'oracle_status_changes':0,
                'changed_observable_sections':dict(renderer_fields),'non_REL_semantic_changes':renderer_non_rel_changes,
                'relation_phrase_source_private_id_and_family':True,
                'hidden_fact_policy_ordering_source':'fact-ID sorting; exact witness test rejects any changed text',
                'no_legality_clause_truth_inferred_from_renderer_metadata':True}}
    d=report['DEV'];oracle_ok=all(v in (None,1) for k,v in d['oracle']['strict'].items() if k.endswith('precision'))
    dominant=max(d['witness_hidden_predicates'].values(),default=0)/max(d['verified_ambiguous_roots'],1)
    if d['verified_ambiguous_fraction']>=.10:disposition='OBSERVABILITY_GAP_LOCALIZED' if dominant>=.80 else 'TARGET_PARTIALLY_NONIDENTIFIABLE_UNDER_CURRENT_OBSERVATION_CONTRACT'
    elif d['strict_certified_roots']/333>=.90 and oracle_ok and not d['verified_ambiguous_roots']:disposition='OBSERVABILITY_SUFFICIENT'
    else:disposition='OBSERVABILITY_INCONCLUSIVE_ON_UNCERTIFIED_ROOTS'
    value={'splits':report,'attribution_unknown_clauses':dict(attribution),'decision':{'disposition':disposition,
        'partial_nonidentifiability_proven':bool(d['verified_ambiguous_roots']),'no_collision_does_not_prove_identifiable':True,
        'bank_empirical_and_counterfactual_ceilings_separate':True,'no_model_ceiling_claim':True,'training':False,'protected_evaluation_opened':False},
        'streams':{n:s.close() for n,s in streams.items()}}
    if replay:
        if value!=read(OUT/'results.json'):raise ValueError('semantic audit report replay')
        receipt(OUT/'fresh-process-replay.json',{'status':'PASS','every_clause_signature_oracle_collision_witness':'exact',
            'protected_evaluation_opened':False})
    else:receipt(OUT/'results.json',value);receipt(OUT/'cost.json',{'audit_seconds':time.perf_counter()-start,'model_training':False})

if __name__=='__main__':analyze('--replay' in sys.argv)
