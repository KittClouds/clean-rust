"""Separate-process witness check with direct set algebra, not Sim.legal."""
from collections import Counter,defaultdict
from common import *
from observation import exact_interface,semantic

def legal_set(r):
    wt=r['WORLD_TRUTH'];facts={F.key(f) for f in wt['state']}
    for s in wt['scheduled']:
        if s['valid_from']<=0 and (s['valid_to'] is None or 0<s['valid_to']):facts.add(F.key(s['fact']))
    gates=defaultdict(list)
    for g in wt['transition_system']['gates']:gates[tuple(g['edge'])].append(tuple(g['cond']))
    acts=[S.Act(a,gates) for a in r['ACTION_POLICY']['available_actions']]
    return [set(a.pre).issubset(facts) and set(a.neg).isdisjoint(facts) for a in acts]

lock();counts=Counter();examples=[];start=time.perf_counter()
for w in rows(OUT/'witnesses.jsonl.gz'):
    original=w['original_record'];alt=w['alternate_record']
    a={F.key(f) for f in original['WORLD_TRUTH']['state']};b={F.key(f) for f in alt['WORLD_TRUTH']['state']}
    if a-b!={tuple(w['original_fact'])} or b-a!={tuple(w['alternate_fact'])}:raise ValueError('not one canonical fact replacement')
    fid=F.fid(tuple(w['original_fact']))
    if fid not in original['OBSERVATION']['hidden_facts']:raise ValueError('fact not hidden')
    if fid in {r['fact_id'] for r in original['OBSERVATION']['reports']}:raise ValueError('fact reported')
    if original['OBSERVATION']['visible_facts']!=alt['OBSERVATION']['visible_facts']:raise ValueError('visible facts altered')
    if original['OBSERVATION']['reports']!=alt['OBSERVATION']['reports']:raise ValueError('reports altered')
    if legal_set(original)!=w['original_legal_set'] or legal_set(alt)!=w['alternate_legal_set']:raise ValueError('independent truth-set label check')
    if w['original_legal_set']==w['alternate_legal_set']:raise ValueError('no changed label')
    if A.derive(alt).disposition!='EXECUTE':raise ValueError('eligibility changed')
    for paired in (False,True):
        expected=w['paired_original_public'] if paired else w['original_public']
        expected_alt=w['paired_alternate_public'] if paired else w['alternate_public']
        clone=copy.deepcopy(alt)
        if paired:
            clone['world_id']=expected['world_id'];clone['META']['renderer_slot']=1
            clone['OBSERVATION']['renderer_family_id']=expected['renderer_family']
        generation.render_row(clone,expected['renderer_family'],1 if paired else 0)
        actual=generation.public(clone)
        if actual!=expected_alt:raise ValueError('public reconstruction differs')
        if exact_interface(actual)!=exact_interface(expected):raise ValueError('actual interface changed')
    if semantic(w['original_public'],original)!=semantic(w['alternate_public'],alt):raise ValueError('semantic support changed')
    counts[w['split']]+=1
    if len(examples)<3:examples.append({'root':w['root'],'split':w['split'],'original_fact':w['original_fact'],
        'alternate_fact':w['alternate_fact'],'changed_candidate_indices':w['changed_indices'],'exact_input_sha256':w['exact_interface_sha256']})
expected=read(OUT/'results.json')
for split,n in counts.items():
    if n!=expected['splits'][split]['verified_ambiguous_roots']:raise ValueError('witness support mismatch')
receipt(OUT/'independent-witness-check.json',{'status':'PASS','witnesses':dict(counts),
    'truth_test':'Act primitive clauses checked by independent fact-set subset/disjointness; no Sim.legal',
    'both_renderer_public_reconstruction':'exact','one_hidden_unreported_fact_changed':True,
    'examples':examples,'seconds':time.perf_counter()-start,'verifier_sha256':sha(Path(__file__)),
    'protected_evaluation_opened':False})
print('INDEPENDENT WITNESS CHECK PASS',dict(counts),flush=True)
