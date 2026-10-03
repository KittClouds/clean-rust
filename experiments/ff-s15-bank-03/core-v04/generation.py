"""New v3 roots from pinned V2 functions; neutral report rendering and typed ABI."""
import copy
from common import *


def bookkeeping(rec,seed):
    """A real irrelevant-hiding intervention; certify all six labels afterward."""
    old=core_labels(rec);ob=rec['OBSERVATION'];ip=rec['INFORMATION_POLICY']
    rf=rec['WORLD_TRUTH']['goal']['required_facts']
    required=set(rec['TARGETS']['evidence']['value'])
    for req in rf['query']:
        for alt in req['support_alternatives']:required.update(alt)
    reported={r['fact_id'] for r in ob['reports']}
    pool=[fid for fid in ob['visible_facts'] if fid not in required|reported
          and R.is_open(F.key(rec['fact_table'][fid]),rec['WORLD_TRUTH']['slot_markers'])]
    rr=rng(NAMESPACE,'irrelevant-hiding',seed)
    chosen=rr.sample(sorted(pool),min(rr.randrange(4),len(pool)))
    saved=copy.deepcopy(rec)
    ob['visible_facts']=sorted(set(ob['visible_facts'])-set(chosen))
    ob['supported_facts']=sorted(set(ob['supported_facts'])-set(chosen))
    ob['hidden_facts']=sorted(set(ob['hidden_facts'])|set(chosen))
    ip['non_requestable']=sorted(set(ip['non_requestable'])|set(chosen))
    try:
        d=A.derive(rec);rec['TARGETS']=targets.compute(rec,d)
        if core_labels(rec)!=old:raise ValueError('intervention changes core labels')
    except (A.Regenerate,ValueError):
        rec.clear();rec.update(saved);chosen=[]
    return {'eligible_facts':len(pool),'hidden_irrelevant_facts':chosen,
            'before_hidden_count':len(saved['OBSERVATION']['hidden_facts']),
            'after_hidden_count':len(rec['OBSERVATION']['hidden_facts']),
            'core_targets_preserved':core_labels(rec)==old,'before_core_targets':old}


def render_row(rec,family,slot):
    st=render.R(rec,family,slot);secs=render.sections(st)
    fk=A.fact_key_map(rec)
    # All evidence uses the same assertion grammar. Source/confidence remain explicit.
    scheduled={s['fact']['id']:s for s in rec['WORLD_TRUTH']['scheduled']}
    facts=[]
    for i in rec['OBSERVATION']['visible_facts']:
        validity=(f"; validity ticks [{scheduled[i]['valid_from']},{scheduled[i]['valid_to']})"
                  if i in scheduled else '')
        facts.append(f"record {st.fact_sentence(fk[i])}; source direct; confidence 100%{validity}")
    facts += [f"record {st.fact_sentence(fk[r['fact_id']])}; source {r['channel']}; confidence {r['confidence_pct']}%"
              for r in rec['OBSERVATION']['reports']]
    st.r.shuffle(facts);secs['facts']=facts;secs['reports']=[]
    secs['policy']=[s.replace('you may ask ','query access available for ')
                   .replace('nobody can tell you ','query access unavailable for ') for s in secs['policy']]
    text,(gs,ge)=render.compose(st,secs)
    spans=[];cursor=gs
    for m in rec['OBSERVATION']['goal_mentions']:
        at=text.find(m['surface'],cursor,ge) if ge>gs else text.find(m['surface'])
        if at>=0:
            spans.append({'surface':m['surface'],'role':m['role'],'span':[at,at+len(m['surface'])]})
            cursor=at+len(m['surface'])
    out={'text':text,'family':family,'rendered_fact_ids':sorted(st.rendered),'mention_spans':spans}
    ob=rec['OBSERVATION'];ob.update(rendered_text=text,renderer_id=f'CORE/{family}/{slot}',
       renderer_family_id=family,rendered_fact_ids=out['rendered_fact_ids'],mention_spans=spans)
    rec['TARGETS']['entity']=render.entity_target(rec,out)
    rec['META']['textual_id']=sha256_hex(text)
    rec['META']['renderer_slot']=slot


def attach_abi(rec):
    sm=A.sim_of(rec);info=sm.search(cap_depth=rec['META']['depth_cap'],max_states=rec['META']['state_cap'])
    actions=sorted(rec['ACTION_POLICY']['available_actions'],key=lambda a:a['id'])
    rec['ACTION_POLICY']['available_actions']=actions
    perms=rec['ACTION_POLICY']['permissions'];env_first=sorted(info['first_actions'])
    permitted={a['id'] for a in actions if perms.get(a['type'],{'permitted':True})['permitted']}
    eligible=rec['TARGETS']['disposition']['value']=='EXECUTE'
    operational=sorted(set(env_first)&permitted) if eligible else []
    selected=rec['TARGETS']['executed_action']['value'] if eligible else None
    ids=[a['id'] for a in actions]
    if eligible and (selected not in ids or selected not in operational):
        raise ValueError('Selected action not an operational optimum')
    candidate=[]
    for raw in actions:
        a=sm.by_id[raw['id']];legal=sm.legal(sm.base0,0,a)
        candidate.append({'id':a.id,'candidate_legal':legal,
           'candidate_permitted':legal and a.id in permitted,
           'candidate_satisfies_goal':bool(legal and sm.goal_holds(sm.apply(sm.base0,a),1)),
           'on_environment_shortest_path':a.id in env_first})
    rec['SUPERVISION_ABI']={'core_targets':core_labels(rec),'candidates':candidate,
       'candidate_order':ids,'selected_action_id':selected,
       'selected_action_index':ids.index(selected) if eligible else None,
       'selected_action_eligible':eligible,'optimal_action_ids':operational,
       'optimal_set_eligible':eligible and bool(operational),'environment_first_actions':env_first,
       'search_status':info['status'],'unavailable_candidate_targets':[
           'candidate_supported','candidate_has_counterevidence','candidate_requires_missing_information'],
       'global_targets':{'solvable':info['status']=='SOLVED','solvable_available':info['status'] in ('SOLVED','UNSAT_EXHAUSTED'),
           'goal_satisfied':sm.goal_holds(sm.base0,0),'missing_information_present':int((rec['TARGETS']['missing_information'].get('witness') or {}).get('M_size',0))>0}}
    plan=info['canonical_plan'];w=rec['TARGETS']['missing_information'].get('witness') or {}
    runs=sum(i==0 or plan[i-1].type!=a.type for i,a in enumerate(plan))
    rec['CAPABILITY_AXES']={'binding':{'introduced_entities':sum(e['introduced'] for e in rec['WORLD_TRUTH']['entities']),
      'goal_binding_issue':A.referential(rec)[0] is not None},
      'evidence_support':len(rec['TARGETS']['evidence']['value']),
      'counterevidence':int(rec['TARGETS']['contradiction']['value']),
      'missing_requirements':int(w.get('M_size',0)),'conflict':bool(rec['TARGETS']['contradiction']['value']),
      'composition_depth':runs if info['status']=='SOLVED' else None,
      'transition_depth':info['depth'] if info['status']=='SOLVED' else None,
      'candidate_comparison':sum(c['candidate_legal'] for c in candidate),
      'globalization':len(rec['WORLD_TRUTH']['goal']['required_facts']['query']),
      'nuisance_invariance':2}


def build_root(split,index):
    intent=INTENTS[index%len(INTENTS)];deep=(index//len(INTENTS))%2
    cfg=worldgen.Cfg(split=split,intents=(intent,),depth_range=(2,4) if deep and intent not in worldgen.PLAN_FREE_INTENTS else (1,2),
                     state_cap=40000,depth_cap=8)
    last=None
    for attempt in range(320):
        try:
            rec=intents.generate_attempt(f'{NAMESPACE}/{split}',index,attempt,cfg)
            d=rec.pop('_d')
            rec['world_id']='V3:'+sha256_hex([NAMESPACE,split,index,attempt])[:32]
            rec['TARGETS']=targets.compute(rec,d)
            rec['bank']='BANK-v3-core';rec['version']='0.4';rec['split']=split
            rec['META'].update(canonical_id=rec['world_id'],generation_index=index,generation_attempt=attempt,
                   namespace=NAMESPACE,curriculum_cell=f'{intent}/{"deep" if deep else "shallow"}')
            rec['PROVENANCE']={'provenance_class':'SYNTHETIC_ONLY','external_root':False,
               'ancestor':'BANK-v2 compatible pinned machinery','namespace':NAMESPACE,'split':split,'index':index,'attempt':attempt}
            rec['BOOKKEEPING']=bookkeeping(rec,[split,index])
            # Targets recomputed by bookkeeping after structural intervention.
            attach_abi(rec)
            ob={k:v for k,v in rec['OBSERVATION'].items() if k not in ('rendered_text','renderer_id','renderer_family_id','rendered_fact_ids','mention_spans')}
            rec['META']['structural_id']=sha256_hex({'truth':rec['WORLD_TRUTH'],'obs':ob,
                     'ip':rec['INFORMATION_POLICY'],'ap':rec['ACTION_POLICY']})
            families=list(freeze.HELD_FAMILIES if split=='EVAL' else freeze.SEEN_FAMILIES)
            rows=[]
            for slot in range(2):
                row=copy.deepcopy(rec);family=families[(index+slot)%len(families)]
                row['world_id']=rec['world_id']+f'@{family}'
                render_row(row,family,slot);rows.append(row)
            return rows,attempt
        except (worldgen.Reject,A.Regenerate,ValueError) as e:last=str(e)
    raise RuntimeError(f'{split}:{index} exhausted: {last}')


def public(row):
    ob=row['OBSERVATION'];ents=row['WORLD_TRUTH']['entities']
    # No missing/hidden/support counters, labels, witnesses, axes, generator cells.
    return {'world_id':row['world_id'],'canonical_id':row['META']['canonical_id'],
      'split':row['split'],'renderer_id':ob['renderer_id'],'renderer_family':ob['renderer_family_id'],
      'input_text':ob['rendered_text'],'goal_mentions':[{k:v for k,v in m.items() if k!='entity'} for m in ob['goal_mentions']],
      'bindings':[{'id':e['id'],'name':e['name'],'type':e['type'],'aliases':e['aliases']} for e in ents if e['introduced']],
      'actions':[{**a,'text':render.action_text(row,a)} for a in row['ACTION_POLICY']['available_actions']],
      'requests':[{'request_id':r['request_id'],'text':render.request_text(row,r)} for r in row['INFORMATION_POLICY']['request_objects']]}
