"""Independent DA replay, fixed-set optimality, and committed geometry audit."""
import argparse
import json
import math
from pathlib import Path

from oracle import bits, from_bits, readout, sequential, supports, assert_disjoint, metrics

STEPS = (0,-1,1,-2,2,-4,4,-8,8,-16,16)


def close(a,b,absolute=1e-23):
    assert math.isclose(a,b,rel_tol=2e-11,abs_tol=absolute),(a,b)


def norm(v):
    return math.sqrt(sum(x*x for x in v))


def metric_check(actual,target,reported):
    m=metrics(actual,target)
    assert m['mismatches']==reported['mismatch_count']
    close(m['squared_error'],reported['squared_error'])
    close(math.sqrt(m['squared_error']),reported['l2'])
    return m


def audit_event(event):
    if not event['parent_constructor_available']:
        assert not event['sets']
        return {'available':False}
    f=event['fixture'];rows=f['operator']['rows']
    initial=f['initial_weight_bits'];target=f['target_readout_bits']
    baseline=readout(rows,initial)
    assert baseline==f['initial_readout_bits']
    assert readout(rows,f['target_weight_bits'])==target
    incidence=supports(rows,len(initial))
    interior=set(f['interior_indices'])
    eligible={i for i in interior if incidence[i]}
    weights=list(map(from_bits,initial))
    original=metric_check(baseline,target,event['initial'])
    results=[]
    for s in event['sets']:
        order=s['ordered_coordinates']
        assert len(order)==len(eligible) and set(order)==eligible
        selected=[];occupied=set();excluded=[]
        for i in order:
            if incidence[i].isdisjoint(occupied):
                selected.append(i);occupied.update(incidence[i])
            else:
                excluded.append(i)
        assert selected==s['selected_coordinates']
        assert excluded==s['excluded_coordinates']
        assert sorted(occupied)==s['covered_rows']
        assert_disjoint(selected,incidence)
        assert len(s['coordinates'])==len(selected)
        final=initial.copy()
        for i,c in zip(selected,s['coordinates']):
            assert c['coordinate']==i and c['support_rows']==sorted(incidence[i])
            assert c['before_bits']==initial[i]
            support=sorted(incidence[i]);options=[]
            for step in STEPS:
                b=initial[i]+step
                if step and not (b-16>0 and b+16<0x40000000):
                    continue
                old=weights[i];weights[i]=from_bits(b)
                actual=[bits(sequential(rows[r],weights)) for r in support]
                weights[i]=old
                m=metrics(actual,[target[r] for r in support])
                options.append((m['mismatches'],m['squared_error'],step,b,actual))
            best=min(options,key=lambda x:x[:2])
            chosen=next(o for o in options if o[2]==c['selected_step'])
            assert chosen[0]==best[0]
            close(chosen[1],best[1])
            assert c['after_bits']==chosen[3]
            assert c['final_mismatch_count']==chosen[0]
            close(c['final_squared_error'],chosen[1])
            assert [r['after_bits'] for r in c['row_changes']]==chosen[4]
            final[i]=chosen[3]
        actual=readout(rows,final)
        assert actual==s['final_readout_bits']
        current=metric_check(actual,target,s['final_readout'])
        assert current['mismatches']<=original['mismatches']
        for point in s['nested_prefix_curve']:
            n=min(point['requested_coordinates'] or len(selected),len(selected))
            prefix=initial.copy()
            for i in selected[:n]:prefix[i]=final[i]
            metric_check(readout(rows,prefix),target,point)
        base=list(map(from_bits,f['snapshot_base_bits']))
        true=[from_bits(w)-b for w,b in zip(f['target_weight_bits'],base)]
        displacement=[from_bits(w)-b for w,b in zip(final,base)]
        axis=f['acquisition_axis']
        true_axis=sum(x*a for x,a in zip(true,axis))
        final_axis=sum(x*a for x,a in zip(displacement,axis))
        drives_true=[sum(true[i] for i in row) for row in rows]
        drives_final=[sum(displacement[i] for i in row) for row in rows]
        errors={
            'axis_absolute_error':abs(final_axis-true_axis),
            'norm_absolute_error':abs(norm(displacement)-norm(true)),
            'cue_linear_absolute_error':norm([a-b for a,b in zip(drives_final,drives_true)]),
        }
        for key,value in errors.items():close(value,s['legacy_gates'][key],1e-12)
        for i,(w,t) in enumerate(zip(final,f['target_weight_bits'])):
            assert 0<=from_bits(w)<=2
            assert (from_bits(w)==0)==(from_bits(t)==0)
            assert (from_bits(w)==2)==(from_bits(t)==2)
            if w!=initial[i]:
                assert f['permitted'][i] and i in interior and abs(w-initial[i])<=16
        results.append({'set':s['set_index'],'selected':len(selected),
                        'mismatch_before':original['mismatches'],
                        'mismatch_after':current['mismatches'],
                        'l2_ratio':math.sqrt(current['squared_error']/original['squared_error'])
                        if original['squared_error'] else None,
                        'covered_rows':len(occupied),
                        'uncovered_mismatch':sum(baseline[r]!=target[r] for r in range(len(rows)) if r not in occupied)})
    assert len(results)==4
    return {'available':True,'sets':results}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args()
    out={}
    for path in sorted(a.directory.glob('seed*.json')):
        out[path.name]=audit_event(json.loads(path.read_text()))
    assert len(out)==8
    print(json.dumps(out,indent=2))
