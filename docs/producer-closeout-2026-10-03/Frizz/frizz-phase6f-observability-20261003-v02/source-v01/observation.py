"""Source-traced semantic transcript and exact interface fingerprints."""
from common import *

def relation_wording(phrase):
    # Canonicalize observable synonym pools, not private relation IDs. Shared
    # phrases join overlapping pools; inverse pools remain distinct unless
    # actual wording overlaps. This conservative lexical equivalence is not
    # used for absolute input ceilings (those retain the full original text).
    words={phrase};pools=[set(pool) for pair in generation.render.REL_PHRASES.values() for pool in pair if pool]
    pools.extend(set(pool) for pool in generation.render.GENERIC_REL if pool)
    while True:
        expanded=words.union(*(pool for pool in pools if words & pool))
        if expanded==words:return sorted(words)
        words=expanded

def replay_public(p,r):
    clone=copy.deepcopy(r);generation.render_row(clone,r['OBSERVATION']['renderer_family_id'],r['META']['renderer_slot'])
    rebuilt=generation.public(clone)
    if rebuilt!=p:raise ValueError('renderer/public replay mismatch')

def semantic(p,r):
    # This inverse is licensed by the replayed generator AST, not arbitrary
    # canonical fields: only values explicitly consumed by rendered sections.
    wt=r['WORLD_TRUTH'];ob=r['OBSERVATION'];fk=A.fact_key_map(r);st=generation.render.R(r,ob['renderer_family_id'],r['META']['renderer_slot'])
    nm=lambda e:st.nm(e)
    def fact(k):
        if k[0]=='REL':
            # Registry IDs are not emitted. Retain the observed predicate phrase,
            # never its private ontology identity; exact-input proofs do not
            # depend on synonym normalization.
            return ['REL',nm(k[1]),relation_wording(st.rel_phrase(k[2])),nm(k[3])]
        return [k[0],*[nm(v) if v in st.ents else v for v in k[1:]]]
    scheduled={s['fact']['id']:s for s in wt['scheduled']}
    direct=[]
    for fid in ob['visible_facts']:
        s=scheduled.get(fid);direct.append({'fact':fact(fk[fid]),'validity':[s['valid_from'],s['valid_to']] if s else None})
    reports=[{'fact':fact(fk[a['fact_id']]),'source':a['channel'],'confidence_pct':a['confidence_pct']} for a in ob['reports']]
    # Queries expose subject/attribute/edge, never the hidden fact value.
    queries=[]
    for kind,key in (('available','requestable'),('unavailable','non_requestable')):
        for fid in r['INFORMATION_POLICY'][key]:
            k=fk[fid]
            if all(st.ents[e]['introduced'] for e in generation.render._entity_args(k)):
                queries.append([kind,generation.render.question_phrase(r,k,st.ents)])
    secs=generation.render.sections(generation.render.R(r,ob['renderer_family_id'],r['META']['renderer_slot']))
    # Goal prose is actually emitted; truth-only goal.entity/required_facts excluded.
    menu=[];bindings={b['id']:b for b in p['bindings']}
    for a in p['actions']:
        menu.append({'type':a['type'],'arguments':[[key,bindings[a['args'][key]]['name'] if a['args'][key] in bindings else 'UNBOUND'] for key in sorted(a['args'])]})
    result={'bindings':p['bindings'],'actor':nm(wt['actor']),
        'direct':sorted(direct,key=canonical),'reports':sorted(reports,key=canonical),
        'gates':sorted([{'edge':[nm(e) for e in g['edge']],'condition':[nm(g['cond'][0]),*g['cond'][1:]]} for g in wt['transition_system']['gates']],key=canonical),
        'action_costs':r['ACTION_POLICY']['action_costs'],
        'denied_permissions':{a:{'authority':v['authority']} for a,v in r['ACTION_POLICY']['permissions'].items() if not v['permitted']},
        'escalation_rules':[{'kind':v['kind'],**{k:v[k] for k in {'MAX_PLAN_DEPTH':['limit'],'COST_LIMIT':['limit'],'ACTION_TYPE_REQUIRES_TIER':['action_type'],'CONFIRM_UNCERTAIN':['min_confidence_pct']}[v['kind']]}} for v in r['ACTION_POLICY']['escalation_rules']],
        'queries':sorted({canonical(q):q for q in queries}.values(),key=canonical),
        'goal_prose':secs['goal'],'goal_mentions':p['goal_mentions'],
        'menu':menu,'requests_text':sorted(a['text'] for a in p['requests'])}
    return result

def exact_interface(p):
    bindings={b['id']:b for b in p['bindings']}
    return {'input_text':p['input_text'],'bindings':p['bindings'],'goal_mentions':p['goal_mentions'],
        'candidate_coordinates':[{'type':a['type'],'arguments':[[k,bindings[a['args'][k]]['name'] if a['args'][k] in bindings else 'UNBOUND'] for k in sorted(a['args'])]} for a in p['actions']]}

def observable_evidence(r):
    ob=r['OBSERVATION'];wt=r['WORLD_TRUTH'];fk=A.fact_key_map(r)
    scheduled={s['fact']['id']:s for s in wt['scheduled']};direct=set();inactive=set()
    for fid in ob['visible_facts']:
        s=scheduled.get(fid)
        if not s or s['valid_from']<=0 and (s['valid_to'] is None or 0<s['valid_to']):direct.add(fk[fid])
        else:inactive.add(fk[fid])
    return direct,inactive

def clauses(r,a,sim=None):
    sim=sim or A.sim_of(r);act=sim.by_id[a['id']]
    return [{'polarity':'positive','fact':list(k),'truth':sim.eff_has(sim.base0,0,k)} for k in act.pre]+[
        {'polarity':'negative','fact':list(k),'truth':not sim.eff_has(sim.base0,0,k)} for k in act.neg]

def primitive(k,direct,inactive,closed_graph=False):
    if k in direct:return True,'direct_active_record'
    if k in inactive:return None,'inactive_schedule_does_not_exclude_unseen_static_fact'
    if k[0] in ('AT','HOLDS','CONTAINS'):
        subject=F.subject_of(k)
        alternatives=[v for v in direct if v[0] in ('AT','HOLDS','CONTAINS') and F.subject_of(v)==subject]
        if alternatives:return False,'licensed_functional_location_slot_other_value'
    if k[0]=='STATE' and any(v[0]=='STATE' and v[1:3]==k[1:3] and v[3]!=k[3] for v in direct):
        return False,'licensed_attribute_other_value'
    if closed_graph and k[0] in ('CONNECTED','BLOCKED'):return False,'recipe_qualified_closed_graph_absence'
    return None,'no_observable_truth_support'

def oracle(r,a,closed_graph=False,prepared=None):
    sim,direct,inactive=prepared or (A.sim_of(r),*observable_evidence(r));out=[]
    for c in clauses(r,a,sim):
        k=tuple(c['fact']);v,why=primitive(k,direct,inactive,closed_graph)
        if v is not None and c['polarity']=='negative':v=not v
        out.append({**c,'observable':v,'reason':why})
    status='CERTAIN_ILLEGAL' if any(c['observable'] is False for c in out) else 'UNRESOLVED' if any(c['observable'] is None for c in out) else 'CERTAIN_LEGAL'
    return status,out
