"""Independent committed-state recomputation and descriptive qualification summary."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np

def digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def distribution(values):
    a=np.asarray(values,dtype=float)
    return dict(n=len(a),minimum=float(a.min()),median=float(np.median(a)),
                p95=float(np.quantile(a,.95)),maximum=float(a.max()),mean=float(a.mean()))

def inspect(states,geometry):
    rows=[];seen=set();checks=0
    for path in sorted(geometry.glob('*-geometry.json')):
        data=json.loads(path.read_text())
        stem=path.name.removesuffix('-geometry.json')
        source=states/(stem+'-states.json')
        assert digest(source)==data['states_sha256']
        snapshots=json.loads(source.read_text())['snapshots']
        outputs=json.loads((geometry/(stem+'-committed.json')).read_text())
        for row,s,n in zip(data['rows'],snapshots,outputs,strict=True):
            b=np.asarray(s['base'],dtype=np.float32).astype(np.float64)
            t=np.asarray(s['target'],dtype=np.float32).astype(np.float64)
            n=np.asarray(n,dtype=np.float32).astype(np.float64)
            a=np.asarray(s['axis'],dtype=np.float64)
            allowed=np.asarray(s['permitted'],dtype=bool)
            dt=t-b;dn=n-b
            assert np.isfinite(n).all() and (n>=0).all() and (n<=2).all()
            assert np.array_equal(n[~allowed],b[~allowed])
            an=np.linalg.norm(a)
            pt=float(dt@a/an);pn=float(dn@a/an)
            rt=float(np.linalg.norm(dt));rn=float(np.linalg.norm(dn))
            ut=dt-pt*a/an;un=dn-pn*a/an
            residual=float(abs(ut@un)/(np.linalg.norm(ut)*np.linalg.norm(un)))
            numerical=dict(true_norm=rt,true_axial=pt,null_axial=pn,
                           residual_abs_cosine=residual,
                           axial_error_over_total_norm=abs(pn-pt)/rt,
                           norm_relative_error=abs(rn-rt)/rt,
                           residual_norm_relative_error=abs(np.linalg.norm(un)-np.linalg.norm(ut))/np.linalg.norm(ut))
            for key,value in numerical.items():
                assert abs(value-row['audit'][key])<1e-11,(stem,key,value,row['audit'][key])
            assert row['audit']['hot_allocations']==0
            if row['audit']['boundary_symmetric_difference']==0:
                assert np.array_equal(n==0,t==0) and np.array_equal(n==2,t==2)
            checks+=1
            identity=(data['seed'],data['side'],data['tau'],data['condition'],s['trial'])
            if identity in seen: continue
            seen.add(identity)
            tb=int(np.count_nonzero((t==0)|(t==2)))
            nb=int(np.count_nonzero((n==0)|(n==2)))
            rows.append(dict(seed=data['seed'],side=data['side'],tau=data['tau'],condition=data['condition'],trial=s['trial'],
                             **numerical,support=int(allowed.sum()),
                             boundary_true=tb,boundary_null=nb,boundary_count_change=nb-tb,
                             boundary_change_fraction_of_true=(nb-tb)/max(tb,1),
                             true_nonzero=int(np.count_nonzero(dt)),null_nonzero=int(np.count_nonzero(dn))))
    fields=['residual_abs_cosine','axial_error_over_total_norm','norm_relative_error',
            'residual_norm_relative_error','boundary_count_change','boundary_change_fraction_of_true',
            'boundary_true','boundary_null','support','true_nonzero','null_nonzero']
    summary=dict(independent_checks=checks,unique_states=len(rows),numpy=np.__version__,
                 no_behavioral_hypothesis_test=True,distributions={f:distribution([r[f] for r in rows]) for f in fields},
                 per_condition={c:{f:distribution([r[f] for r in rows if r['condition']==c]) for f in fields}
                                for c in sorted({r['condition'] for r in rows})})
    return summary,rows

if __name__=='__main__':
    states,geometry,out=map(Path,sys.argv[1:4])
    summary,rows=inspect(states,geometry)
    with out.open('x') as f:json.dump(dict(summary=summary,states=rows),f,indent=2)
    print(json.dumps(summary,indent=2))
