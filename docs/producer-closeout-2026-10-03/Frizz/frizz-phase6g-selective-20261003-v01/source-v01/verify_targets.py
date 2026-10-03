"""Independent target reconstruction from the sealed strict rule implementation."""
from common import *
def main():
    setup();lock();original=sys.modules['common']
    spec=importlib.util.spec_from_file_location('common',F6/'source-v01/common.py');f=importlib.util.module_from_spec(spec)
    try:
        sys.modules['common']=f;spec.loader.exec_module(f)
        o=module('sealed_phase6f_observation',F6/'source-v01/observation.py')
    finally:sys.modules['common']=original
    checked={}
    for split in ('TRAIN','DEV'):
        a=load(C6/f'{split}-ABI.pt');t=load(OUT/f'{split}-targets.pt')
        rows={(cid,a['renderer'][2*i+j]):2*i+j for i,cid in enumerate(a['canonical_ids']) for j in (0,1)}
        n=0;seen=set()
        for p,r in f.population(split):
            o.replay_public(p,r);i=rows[r['META']['canonical_id'],p['renderer_family']];seen.add(i)
            sim=f.A.sim_of(r);prepared=(sim,*o.observable_evidence(r))
            for j,action in enumerate(p['actions']):
                s,_=o.oracle(r,action,prepared=prepared)
                if int(t['status'][i,j])!=LABELS.index(s):raise ValueError('strict target replay mismatch')
                if bool(t['canonical'][i,j])!=sim.legal(sim.base0,0,sim.by_id[action['id']]):raise ValueError('diagnostic truth replay mismatch')
                n+=1
        if len(seen)!=len(a['mask']) or n!=int(t['mask'].sum()):raise ValueError('independent target support mismatch')
        checked[split]={'rendered_rows':len(seen),'candidate_instances':n}
    receipt(OUT/'independent-target-replay.json',{'status':'PASS','supports':checked,'derivation':'sealed strict oracle on actual BANK TRAIN/DEV, not copied labels',
        'model_supervision':'status only','protected_evaluation_opened':False})
    print('INDEPENDENT STRICT TARGET REPLAY PASS',flush=True)
if __name__=='__main__':main()
