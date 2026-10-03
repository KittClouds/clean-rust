"""Bounded interpretation generated from completed measurements."""
from b6_contract import *

def render():
    r=read(OUT/'RESULT.json');lines=['# Phase 6B — within-type decision semantics','',
       'Frozen LFM T0–T4 states; TRAIN-fitted diagnostic heads only. Protected evaluation unopened.','',
       '| Rung | Signature tie ceiling | Semantic tie ceiling | Gold linear full top1 | Gold linear same-type top1 | Exact-signature same-type top1 |',
       '|---|---:|---:|---:|---:|---:|']
    for row in r['ladder']:
        lines.append(f"| G{row['rung']} | {row['identity_signature_ceiling']['same_type_selected_signature_tie_ceiling']:.3f} | {row['semantic_abstraction_ceiling']['same_type_selected_signature_tie_ceiling']:.3f} | {row['linear_gold_recovery']['unrestricted']['selected']['top1_hit']:.3f} | {row['linear_gold_recovery']['gold_type']['selected']['top1_hit']:.3f} | {row['exact_TRAIN_signature_recovery']['gold_type']['selected']['top1_hit']:.3f} |")
    lines+=['','The signature ceiling is an optimistic reciprocal-tie bound conditional on knowing the selected signature, not a learner score. Raw argument IDs uniquely identifying a candidate do not identify which candidate should be chosen.','',
        'G6 is shortest-first-path membership from the canonical ABI. It is explicitly endpoint-related oracle evidence and cannot be used to claim an independently discovered factor. Obligation query sources may depend on the canonical plan.','',
        f"First G1–G5 rung reaching the fixed 50% gold-type linear recovery reference: {r['first_gold_predictive_rung_at_50pct_same_type']}. Factor probes: {r['factor_selection']}.",'',
        '| Depth | Readout | Legality BA | Immediate goal BA | Actor-binding BA | Destination/goal BA | Pair-choice BA |',
        '|---|---|---:|---:|---:|---:|---:|']
    def fmt(x):return 'NA' if x is None else f'{x:.3f}'
    for key,row in r['panel'].items():
        m=row['factor_receipt']['metrics'];pairs=row['pair_choice_receipt']['metrics']['selected_vs_alternative']
        values=[fmt(m.get(k,{}).get('balanced_accuracy')) for k in ['legal','immediate_goal','actor_binding','destination_goal_binding']]
        lines.append(f"| T{row['probe_depth']} | {row['factor_receipt']['family']} | {' | '.join(values)} | {fmt(pairs['balanced_accuracy'])} |")
    rung=r['first_gold_predictive_rung_at_50pct_same_type']
    useful=[]
    for key,row in r['panel'].items():
        useful.append(row['pair_choice_receipt']['metrics']['selected_vs_alternative']['balanced_accuracy'] or 0.)
    disposition='ENDPOINT_OR_MISSING_CONSEQUENCE_SEMANTICS_REMAIN_UNRESOLVED' if rung is None else 'FACTOR_ACCESS_AUDIT_COMPLETE_COMPARATOR_NOT_AUTOMATICALLY_EARNED'
    interpretation={'disposition':disposition,'first_predictive_gold_rung':rung,'pair_choice_BA_range':[min(useful),max(useful)],
       'next_mechanism':'NO_COMPARATOR_IMPLEMENTED; review gold semantic recovery and corresponding factor/difference metrics before any new organ',
       'meaning':'Individual factor accuracy is insufficient to grant a setwise comparator; required discriminating factors and relative choice must be shown accessible.',
       'no_substrate_impossibility_claim':True}
    write(OUT/'DISPOSITION.json',interpretation)
    lines+=['',f"**Disposition:** {disposition}.",'',interpretation['meaning'],'',
       'All per-factor MAE, binary balanced accuracy, supports, prediction diversity, pair-difference MAE, count slices, renderer slices, composition/transition slices, ranks, MRR and top1/3/5 are in RESULT.json and metrics/.',
       '',f"Gold derivation: {r['gold_receipt']['seconds']:.2f}s. Diagnostic fitting costs, parameter counts, and peak memory are in individual receipts.",'',*r['caveats']]
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

if __name__=='__main__':render()
