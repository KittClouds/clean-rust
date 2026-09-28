"""Post hoc geometric implementation audit. No inferential tests or new samples."""
from pathlib import Path
import json
import sys
import numpy as np
from inspect_geometry import distribution

def summarize(folder):
    events=[];runs=[]
    files=sorted(folder.glob('*-events.json'))
    expected={(s,side,t,c) for s in range(6000,6032) for side in ['R','L'] for t in [4,16]
              for c in ['neither','parallel_only','perpendicular_only','both']}
    seen=set()
    for path in files:
        data=json.loads(path.read_text())
        identity=tuple(data[k] for k in ['seed','side','tau','condition'])
        assert identity not in seen
        seen.add(identity)
        assert data['parent_behavior_parity'] and data['capture_weight_parity']
        assert data['hot_allocations']==0
        assert [r['trial'] for r in data['events']]==list(range(1,257))
        metadata={k:data[k] for k in ['seed','side','tau','condition']}
        for row in data['events']:events.append(dict(**metadata,**row))
        rows=data['events']
        runs.append(dict(**metadata,
                         affected_events=sum(r['clamp_coordinates']>0 for r in rows),
                         sum_signed_clamp_coordinate=sum(r['clamp_coordinate_change'] for r in rows),
                         sum_absolute_clamp_coordinate=sum(abs(r['clamp_coordinate_change']) for r in rows),
                         sum_clamp_l1=sum(r['clamp_l1'] for r in rows),
                         sum_clamp_l2=sum(np.sqrt(r['clamp_l2_sq']) for r in rows),
                         sum_special_commit_coordinate=sum(r['commit_minus_clamp_axis_dot']/r['axis_norm_sq'] for r in rows)))
        runs[-1]['sum_common_base_clamp_coordinate']=sum(r['common_base_clamp_axis_dot']/r['axis_norm_sq'] for r in rows)
        runs[-1]['sum_incremental_clamp_coordinate']=sum(r['incremental_clamp_axis_dot']/r['axis_norm_sq'] for r in rows)
    assert seen==expected,(len(seen),len(expected))
    by={}
    for side in ['R','L']:
        by[side]={}
        for condition in ['neither','parallel_only','perpendicular_only','both']:
            selected=[r for r in runs if r['side']==side and r['condition']==condition]
            event_rows=[r for r in events if r['side']==side and r['condition']==condition]
            by[side][condition]={
                'runs':len(selected),'events':len(event_rows),
                'affected_event_fraction':sum(r['clamp_coordinates']>0 for r in event_rows)/len(event_rows),
                'mean_clamped_coordinates_per_event':float(np.mean([r['clamp_coordinates'] for r in event_rows])),
                'sum_signed_clamp_coordinate_per_run':distribution([r['sum_signed_clamp_coordinate'] for r in selected]),
                'sum_absolute_clamp_coordinate_per_run':distribution([r['sum_absolute_clamp_coordinate'] for r in selected]),
                'sum_special_commit_coordinate_per_run':distribution([r['sum_special_commit_coordinate'] for r in selected]),
                'sum_common_base_clamp_coordinate_per_run':distribution([r['sum_common_base_clamp_coordinate'] for r in selected]),
                'sum_incremental_clamp_coordinate_per_run':distribution([r['sum_incremental_clamp_coordinate'] for r in selected]),
                'per_event_clamp_coordinate':distribution([r['clamp_coordinate_change'] for r in event_rows]),
                'windows':{f'{lo}-{hi}':dict(
                    affected_fraction=float(np.mean([r['clamp_coordinates']>0 for r in event_rows if lo<=r['trial']<=hi])),
                    mean_signed_coordinate=float(np.mean([r['clamp_coordinate_change'] for r in event_rows if lo<=r['trial']<=hi])))
                    for lo,hi in [(1,16),(17,32),(33,64),(65,128),(129,256)]},
            }
    return dict(kind='POST_HOC_GEOMETRIC_IMPLEMENTATION_AUDIT',new_samples=0,
                replayed_runs=len(runs),replayed_reversal_events=len(events),
                all_archived_behavior_comparisons_exact=True,all_capture_on_off_final_weights_exact=True,
                interpretation='Clamp sums are local corrections along realized trajectories, not effects of disabling clipping. Both special endpoint arithmetic is separate. No confidence intervals or hypothesis tests.',
                by_side_condition=by,runs=runs)

if __name__=='__main__':
    result=summarize(Path(sys.argv[1]))
    with Path(sys.argv[2]).open('x') as f:json.dump(result,f,indent=2)
    for side,conditions in result['by_side_condition'].items():
        for c,v in conditions.items():
            print(side,c,'affected=',v['affected_event_fraction'],
                  'mean_signed_coordinate=',v['sum_signed_clamp_coordinate_per_run']['mean'],
                  'mean_abs_coordinate=',v['sum_absolute_clamp_coordinate_per_run']['mean'])
