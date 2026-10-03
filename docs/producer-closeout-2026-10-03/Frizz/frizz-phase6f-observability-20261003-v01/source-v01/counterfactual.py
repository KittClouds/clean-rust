"""Hidden-only alternate truths, strict byte-identical permitted input witnesses."""
from common import *
from observation import exact_interface,semantic

def replace_id(obj,old,new):
    if isinstance(obj,dict):return {k:replace_id(v,old,new) for k,v in obj.items()}
    if isinstance(obj,list):return [replace_id(v,old,new) for v in obj]
    return new if obj==old else obj

def replacements(k,r):
    ents=r['WORLD_TRUTH']['entities'];locations=[e['id'] for e in ents if e['type']=='LOCATION']
    if k[0]=='STATE':return [('STATE',k[1],k[2],{'active':'inactive','inactive':'active','open':'closed','closed':'open'}[k[3]])]
    if k[0]=='AT':return [('AT',k[1],v) for v in locations if v!=k[2]]
    if k[0]=='HOLDS':return [('HOLDS',e['id'],k[2]) for e in ents if e['type']=='AGENT' and e['id']!=k[1]]
    if k[0]=='CONTAINS':return [('CONTAINS',e['id'],k[2]) for e in ents if e['type']=='CONTAINER' and e['id']!=k[1]]
    return []

def find(p,r,stats=None):
    fk=A.fact_key_map(r);reported={a['fact_id'] for a in r['OBSERVATION']['reports']}
    scheduled={a['fact']['id'] for a in r['WORLD_TRUTH']['scheduled']}
    original=[c['candidate_legal'] for c in r['SUPERVISION_ABI']['candidates']]
    attempts=0;failures={} if stats is None else stats
    def note(k):failures[k]=failures.get(k,0)+1
    for fid in sorted(set(r['OBSERVATION']['hidden_facts'])-reported-scheduled):
        for newkey in replacements(fk[fid],r):
            attempts+=1;newfact=F.from_key(newkey)
            if newfact['id'] in r['fact_table']:note('replacement_fact_already_present');continue
            clone=replace_id(copy.deepcopy(r),fid,newfact['id'])
            clone['fact_table'].pop(fid,None);clone['fact_table'][newfact['id']]=newfact
            clone['WORLD_TRUTH']['state']=[newfact if f['id']==newfact['id'] else f for f in clone['WORLD_TRUTH']['state']]
            try:
                # This checks observed/support partitions, types and requirement
                # algebra; still no assertion that a new generator seed emits it.
                deriv=A.derive(clone)
                if deriv.disposition!='EXECUTE':note('conditional_EXECUTE_not_preserved');continue
                sim=A.sim_of(clone);new=[sim.legal(sim.base0,0,sim.by_id[a['id']]) for a in r['ACTION_POLICY']['available_actions']]
                if new==original:note('legality_unchanged');continue
                generation.render_row(clone,r['OBSERVATION']['renderer_family_id'],r['META']['renderer_slot'])
                public=generation.public(clone)
                if exact_interface(public)!=exact_interface(p):note('actual_permitted_input_changed');continue
                if semantic(public,clone)!=semantic(p,r):raise AssertionError('byte-identical witness semantic mismatch')
                changed=[i for i,(a,b) in enumerate(zip(original,new)) if a!=b]
                return {'original_fact':list(fk[fid]),'alternate_fact':list(newkey),
                    'original_legal_set':original,'alternate_legal_set':new,'changed_indices':changed,
                    'exact_interface_sha256':digest(exact_interface(p)),
                    'original_record':r,'alternate_record':clone,
                    'original_public':p,'alternate_public':public,
                    'conditional_EXECUTE_preserved':True,'derived_alternate_disposition':deriv.disposition,
                    'not_a_new_sealed_corpus_row':True},attempts
            except (A.Regenerate,ValueError,KeyError) as e:
                note(type(e).__name__+':'+str(e))
    return None,attempts
