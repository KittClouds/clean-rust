from pathlib import Path
import datetime
import json
from freeze import digest,ROOT

run=ROOT/'artifacts/20260915T215102Z'
dev=run/'development-independent.json'
gates={
    'axial_error_over_total_norm_max':1e-7,
    'norm_relative_error_max':1e-7,
    'residual_norm_relative_error_max':1e-7,
    'residual_abs_cosine_max':1e-5,
    'boundary_membership_symmetric_difference_max':0,
    'outside_permitted_support_changes_max':0,
    'nonzero_support_count_relative_difference_max':0.01,
    'hot_allocations_max':0,
}
receipt=dict(protocol='Q07-BoundedNull-v1',phase='holdout_qualification',
             created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
             before_holdout_states=True,development_summary_sha256=digest(dev),
             constructor_revision='2-exact-boundary-membership',
             binary_sha256=digest(run/'frozen/q07-bounded-null-v1.exe'),
             constructor_source_sha256=digest(run/'frozen/src/rotation.rs'),
             inspection_script_sha256=digest(ROOT/'scripts/inspect_geometry.py'),
             seeds=[9004,9005],taus=[4,16],sides=['R','L'],parallel_contexts=[0,1],
             slots=[1,16,32,64,128,256,'first_max_boundary','first_min_boundary'],gates=gates,
             rationale='Development maxima: normalized errors <=2.1e-8, cosine <=1.3e-8; thresholds allow numerical headroom. Exact boundary membership added after revision1 saturation mismatch. No behavioral outcome used.',
             limitation='Snapshot qualification only; no null-policy trajectory, global solver optimum, or biological claim.',
             failure_policy='Report any failure without parameter adjustment, replacement seeds, or measured launch.')
with (run/'holdout-gates.json').open('x') as f:json.dump(receipt,f,indent=2)
print(json.dumps(receipt,indent=2))
