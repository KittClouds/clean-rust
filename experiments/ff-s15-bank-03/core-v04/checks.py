"""Independent row checker: recompute semantics/ABI, no build-driver counters."""
from common import *
from generation import public,render_row,attach_abi
import copy

KNOWN_CUES=('you may ask','nobody can tell','reports that','says')

def check(row):
    errors=[]
    if row['PROVENANCE']['provenance_class']!='SYNTHETIC_ONLY' or row['PROVENANCE']['external_root']:
        errors.append('G14-CORE provenance')
    if not row['META']['namespace'].startswith(NAMESPACE):errors.append('G14-CORE namespace')
    if set(row['CAPABILITY_AXES'])!=set(AXES):errors.append('axis completeness')
    errors += ['derivation:'+e for e in targets.verify(row)]
    errors += ['observation:'+e for e in gates.g03(row)]
    errors += ['independent transition:'+e for e in gates.g05(row,gates.Acc())]
    abi=row['SUPERVISION_ABI'];actions=row['ACTION_POLICY']['available_actions']
    ids=[a['id'] for a in actions]
    if ids!=sorted(set(ids)) or ids!=abi['candidate_order']:errors.append('candidate identity/order')
    if abi['core_targets']!=core_labels(row):errors.append('core target replay')
    sm=A.sim_of(row);info=sm.search(cap_depth=row['META']['depth_cap'],max_states=row['META']['state_cap'])
    env=sorted(info['first_actions'])
    if env!=abi['environment_first_actions']:errors.append('shortest-path first set')
    permitted={a['id'] for a in actions if row['ACTION_POLICY']['permissions'].get(a['type'],{'permitted':True})['permitted']}
    eligible=core_labels(row)['disposition']=='EXECUTE'
    expected=sorted(set(env)&permitted) if eligible else []
    if expected!=abi['optimal_action_ids']:errors.append('operational optimal set')
    if bool(expected)!=abi['optimal_set_eligible']:errors.append('empty-set eligibility')
    if eligible:
        ix=abi['selected_action_index']
        if ix is None or ids[ix]!=row['TARGETS']['executed_action']['value'] or ids[ix] not in expected:
            errors.append('selected endpoint identity')
    elif abi['selected_action_index'] is not None or abi['selected_action_id'] is not None:
        errors.append('ineligible endpoint populated')
    for raw,target in zip(actions,abi['candidates']):
        a=sm.by_id[raw['id']];legal=sm.legal(sm.base0,0,a)
        if target['id']!=a.id or target['candidate_legal']!=legal:errors.append('candidate legal truth')
        goal=bool(legal and sm.goal_holds(sm.apply(sm.base0,a),1))
        if goal!=target['candidate_satisfies_goal']:errors.append('candidate goal truth')
    if len(abi['candidates'])!=len(actions):errors.append('candidate count')
    rederived=copy.deepcopy(row);attach_abi(rederived)
    if rederived['SUPERVISION_ABI']!=abi:errors.append('complete ABI replay')
    if rederived['CAPABILITY_AXES']!=row['CAPABILITY_AXES']:errors.append('axis value replay')
    bk=row['BOOKKEEPING']
    if not bk['core_targets_preserved'] or bk['before_core_targets']!=core_labels(row):errors.append('bookkeeping semantics')
    hidden=set(row['OBSERVATION']['hidden_facts']);needed=set()
    for q in row['WORLD_TRUTH']['goal']['required_facts']['query']:
        for alt in q['support_alternatives']:needed.update(alt)
    if set(bk['hidden_irrelevant_facts']) & needed:errors.append('hidden irrelevant overlaps obligations')
    if not set(bk['hidden_irrelevant_facts'])<=hidden:errors.append('bookkeeping identity')
    if bk['hidden_irrelevant_facts']:
        restored=copy.deepcopy(row);chosen=set(bk['hidden_irrelevant_facts'])
        ob=restored['OBSERVATION'];ip=restored['INFORMATION_POLICY']
        ob['visible_facts']=sorted(set(ob['visible_facts'])|chosen)
        ob['supported_facts']=sorted(set(ob['supported_facts'])|chosen)
        ob['hidden_facts']=sorted(set(ob['hidden_facts'])-chosen)
        ip['non_requestable']=sorted(set(ip['non_requestable'])-chosen)
        restored['TARGETS']=targets.compute(restored,A.derive(restored))
        if core_labels(restored)!=core_labels(row):errors.append('bookkeeping reverse replay')
    text=row['OBSERVATION']['rendered_text'].lower()
    if any(p in text for p in KNOWN_CUES):errors.append('old conflict cue survives')
    clone=copy.deepcopy(row);render_row(clone,row['OBSERVATION']['renderer_family_id'],row['META']['renderer_slot'])
    if clone['OBSERVATION']!=row['OBSERVATION']:errors.append('renderer replay')
    p=public(row)
    forbidden={'TARGETS','WORLD_TRUTH','SUPERVISION_ABI','CAPABILITY_AXES','PROVENANCE','BOOKKEEPING','META','hidden_facts','supported_facts'}
    if forbidden & set(p):errors.append('public input firewall')
    if len(p['actions'])!=len(actions):errors.append('public candidate truncation')
    return errors

def mutation_tests(row):
    results={}
    changes={'target':lambda r:r['SUPERVISION_ABI']['core_targets'].update(disposition='FAKE'),
      'provenance':lambda r:r['PROVENANCE'].update(provenance_class='HUMAN'),
      'candidate':lambda r:r['SUPERVISION_ABI']['candidate_order'].reverse(),
      'axis':lambda r:r['CAPABILITY_AXES'].pop('transition_depth'),
      'cue':lambda r:r['OBSERVATION'].update(rendered_text=r['OBSERVATION']['rendered_text']+' reports that'),
      'bookkeeping':lambda r:r['BOOKKEEPING'].update(core_targets_preserved=False)}
    for name,fn in changes.items():
        bad=copy.deepcopy(row);fn(bad);results[name]=bool(check(bad))
    return results
