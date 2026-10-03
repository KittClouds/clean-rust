"""Validate every closed-loop qualification event against pre-holdout gates."""
from pathlib import Path
import hashlib
import json
import sys
from inspect_geometry import distribution

folder=Path(sys.argv[1]);gates_path=Path(sys.argv[2]);out=Path(sys.argv[3])
gates=json.loads(gates_path.read_text())['gates']
expected={(seed,side,tau,c) for seed in range(9000,9006) for side in ['R','L'] for tau in [4,16] for c in ['perpendicular_only','both']}
seen=set();events=[];failures=[]
for path in sorted(folder.glob('*-policy.json')):
    data=json.loads(path.read_text());key=tuple(data[k] for k in ['seed','side','tau','condition'])
    assert key not in seen;seen.add(key)
    if data['failed'] or data['hot_allocations']!=0 or len(data['audits'])!=256:
        failures.append(dict(run=key,reason='failed, incomplete, or allocating trajectory'))
    for index,row in enumerate(data['audits'],1):
        assert row['trial']==index
        for name in ['axial_error_over_total_norm','norm_relative_error','residual_norm_relative_error','residual_abs_cosine']:
            value=row[name]
            if value is None or not 0<=value<=gates[name+'_max']:
                failures.append(dict(run=key,event=index,gate=name,value=value))
        for name in ['boundary_symmetric_difference','outside_support_changes','hot_allocations','max_bound_violation']:
            if row[name]!=0:failures.append(dict(run=key,event=index,gate=name,value=row[name]))
        support_difference=abs(row['true_nonzero']-row['null_nonzero'])/max(1,row['true_nonzero'])
        if support_difference>gates['nonzero_support_count_relative_difference_max']:
            failures.append(dict(run=key,event=index,gate='nonzero_support',value=support_difference))
        events.append(dict(seed=data['seed'],**row))
assert seen==expected,(len(seen),len(expected))
summary=dict(status='CLOSED_LOOP_QUALIFICATION_PASSED' if not failures else 'CLOSED_LOOP_QUALIFICATION_FAILED',
             runs=len(seen),events=len(events),development_events=sum(e['seed']<9004 for e in events),
             holdout_events=sum(e['seed']>=9004 for e in events),failures=failures,
             gates_sha256=hashlib.sha256(gates_path.read_bytes()).hexdigest(),
             measured_seeds_used=0,
             distributions={f:distribution([e[f] for e in events if e[f] is not None]) for f in
                            ['residual_abs_cosine','axial_error_over_total_norm','norm_relative_error','residual_norm_relative_error','sweeps','moves','support']})
with out.open('x') as f:json.dump(summary,f,indent=2)
print(json.dumps(summary,indent=2))
