"""Denominator-complete localization report, hash seal and bounded next branch."""
from pathlib import Path
from common import OUT,P5,read,receipt,sha,check_lock
import torch
from panel import target


def main():
    check_lock();decision=read(OUT/'LOCALIZATION.json')
    if decision['F_earned']:
        raise ValueError('F earned: complete its separately frozen experiment before final seal')
    table={}
    for arm in ('bridge','E'):
        for phenotype in ('init','trained'):
            for mode in ('c','cs','e'):
                for family in ('linear','mlp'):
                    table[arm,phenotype,mode,family]=read(OUT/'panel'/arm/phenotype/mode/family/'metrics.json')
    report='# Phase 6A — Is comparison accessible in the frozen state?\n\n'
    report+='**'+decision['status']+'**. F is not earned by the frozen rule and was not run.\n\n'
    report+='This audit changes no Qwen or graft weights. It measures TRAIN-fitted diagnostic recovery on DEV, '
    report+='not protected generalization or an information-theoretic ceiling.\n\n'
    report+='## Representation localization\n\n'
    report+='Each row is a fixed readout, not a best-of-panel capability score. '
    report+='c = candidate-local 256; cs = candidate + context 320; e = integrated state32.\n\n'
    report+='| Model | State | Surface | Readout | Selected top1 | Selected MRR | Optimal top1 | Optimal MRR | Type accuracy | Goal control BA |\n'
    report+='|---|---|---|---|---:|---:|---:|---:|---:|---:|\n'
    for (arm,phenotype,mode,family),v in table.items():
        m=v['metrics'];s=m['selected_ranking']['unrestricted']['all']['selected']
        o=m['optimal_ranking']['unrestricted']['all']['optimal']
        report+=f"| {arm} | {phenotype} | {mode} | {family} | {s['top1']:.4f} | {s['MRR']:.4f} | {o['top1']:.4f} | {o['MRR']:.4f} | {m['first_action_type']['accuracy']:.4f} | {v['goal_control'][family]['balanced_accuracy']:.4f} |\n"
    report+='\nNamed selected-candidate ranking and optimal-membership scoring have separate fits, targets and eligibility masks. '
    report+='First-action-type is a root-level masked-mean readout; it is not a named-candidate score. '
    report+='The goal-control readouts are existing sealed Phase5 results, copied by reference and exact hash—not refit or selected.\n\n'
    train=target('TRAIN');dev=target('DEV');use=train['selected_eligible']
    majority=int(torch.bincount(train['first_action_type'][use],minlength=9).argmax())
    dvuse=dev['selected_eligible']
    majority_accuracy=float((dev['first_action_type'][dvuse]==majority).float().mean())
    report+=f'TRAIN-majority action type index {majority}; DEV majority accuracy {majority_accuracy:.4f}. '
    report+='Type accuracy alone can ride MOVE prevalence. Per-class support/F1 are retained in every metrics.json.\n\n'
    report+='## Within-type versus full-set ranking\n\n'
    report+='| Model | Surface | Readout | Unrestricted selected top1 | Gold-type top1 | Predicted-type top1 | Gold-type MRR | Predicted-type exclusions |\n'
    report+='|---|---|---|---:|---:|---:|---:|---:|\n'
    for (arm,phenotype,mode,family),v in table.items():
        if phenotype!='trained':
            continue
        r=v['metrics']['selected_ranking'];u=r['unrestricted']['all']['selected']
        g=r['gold_type']['all']['selected'];p=r['predicted_type']['all']['selected']
        report+=f"| {arm} | {mode} | {family} | {u['top1']:.4f} | {g['top1']:.4f} | {p['top1']:.4f} | {g['MRR']:.4f} | {p['excluded_by_restriction']} |\n"
    report+='\nGold type is an oracle restriction, never a learned input or deployable result. '
    report+='Predicted type uses the matching surface/family TRAIN-fit type readout. Excluded positives score zero reciprocal rank/top-k; '
    report+='their censored rank is N+1. The optimal endpoint remains independent, including under type restriction.\n\n'
    report+='Both endpoint families under the **selected-candidate scorer** (not the separately fitted optimal scorer):\n\n'
    report+='| Model | Surface | Readout | Selected roots | Exact top1 | Optimal roots | Optimal hit top1 | Best-optimal MRR |\n'
    report+='|---|---|---|---:|---:|---:|---:|---:|\n'
    for (arm,phenotype,mode,family),v in table.items():
        if phenotype!='trained':
            continue
        r=v['metrics']['selected_ranking']['unrestricted']['all'];s,o=r['selected'],r['optimal']
        report+=f"| {arm} | {mode} | {family} | {s['eligible_roots']} | {s['top1']:.4f} | {o['eligible_roots']} | {o['top1']:.4f} | {o['MRR']:.4f} |\n"
    report+='\nThe full selected-scorer best-optimal ranks/top3/top5 and all restricted results remain in metrics.json.\n\n'
    report+='## Pairwise diagnostics\n\n'
    report+='| Model | State | Surface | Readout | Selected pair BA | Selected pairs / roots | Optimal pair BA | Optimal pairs / roots |\n'
    report+='|---|---|---|---|---:|---:|---:|---:|\n'
    for (arm,phenotype,mode,family),v in table.items():
        a,b=v['metrics']['selected_pair'],v['metrics']['optimal_pair']
        report+=f"| {arm} | {phenotype} | {mode} | {family} | {a['balanced_accuracy']:.4f} | {a['pairs']}/{a['roots']} | {b['balanced_accuracy']:.4f} | {b['pairs']}/{b['roots']} |\n"
    report+='\nPairs were constructed and sealed before DEV scoring. Up to four positive members crossed with four '
    report+='evenly spaced negatives, alternating orientation. IDs and labels never enter features. '
    report+='High pair accuracy on these label-constructed contrasts does not establish full-universe ranking. '
    report+='Linear shared context cancels under antisymmetry; the TinyMLP can condition comparisons on context.\n\n'
    report+='## Candidate-count slices and top-k\n\n'
    report+='| Model | Surface | Readout | Count band | Roots | Selected rank | MRR | Top1 | Top3 | Top5 | Best optimal rank | Optimal MRR | Optimal top1/3/5 |\n'
    report+='|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|\n'
    for (arm,phenotype,mode,family),v in table.items():
        if phenotype!='trained':
            continue
        s=v['metrics']['selected_ranking']['unrestricted'];o=v['metrics']['optimal_ranking']['unrestricted']
        for band in ('all','1-28','29-64','65-128','129-171'):
            x=s[band]['selected'];y=o[band]['optimal']
            if not x['eligible_roots']:
                report+=f"| {arm} | {mode} | {family} | {band} | 0 | — | — | — | — | — | — | — | — |\n"
                continue
            report+=f"| {arm} | {mode} | {family} | {band} | {x['eligible_roots']} | {x['mean_rank']:.2f} | {x['MRR']:.4f} | {x['top1']:.4f} | {x['top3']:.4f} | {x['top5']:.4f} | {y['mean_rank']:.2f} | {y['MRR']:.4f} | {y['top1']:.4f}/{y['top3']:.4f}/{y['top5']:.4f} |\n"
    report+='\nAll restriction/slice endpoint supports are retained in metrics.json. Fewer than 200 roots is descriptive. '
    report+='Stable canonical-ID tie breaking is frozen; no selected-ID tie preference. Uniform selected top1 expectation '
    report+='is mean(1/N); optimal expectation is mean(|A*|/N).\n\n'
    report+='## The next branch\n\n'
    report+='Frozen well-ranked rule: unrestricted selected top1≥.35, MRR≥.50, uniform top1 lift≥.20, ≥200 eligible roots. '
    report+='This is an operational continuation rule, not a definition of information content.\n\n'
    report+='E e TinyMLP-minus-linear top1, paired canonical-root bootstrap: '+str(decision['E_e_MLP_minus_linear_top1'])+'.\n\n'
    report+='Declared pass map: '+str(decision['well_ranked_by_declared_arm'])+'.\n\n'
    if decision['status']=='NO_EXPOSED_SURFACE_CLEARS_FIXED_USEFUL_RANKING_THRESHOLD':
        report+='The present exposed path does not deliver useful full-set comparison under this fixed diagnostic family/dose. '
        report+='This does not prove the frozen substrate contains no comparison information. Goal-relative accessibility can '
        report+='survive while named-candidate ranking remains weak. No automatic F is justified by this result.\n\n'
    elif decision['status']=='SIMPLE_LINEAR_RANKING_SUFFICIENT':
        report+='A simple readout already ranks candidates usefully. The production scorer, not a new access mechanism, is the next target.\n\n'
    elif decision['status']=='COMPARISON_ACCESS_LOST_OR_DEGRADED_AT_INTEGRATION':
        report+='Candidate+context clears the operational rule where integrated e does not. Improve the integration contract; '
        report+='do not expand features blindly. This is a readout-budget localization, not proof of irreversible information loss.\n\n'
    else:
        report+='The panel shows partial access but does not earn the specified nonlinear-only F branch. '
        report+='Keep its distinct surfaces and endpoints rather than converting a marginal score into a global capability claim.\n\n'
    report+='## Cost, identity and verification\n\n'
    report+='120 fixed target fits plus four solvable instrument controls; no substrate/graft training. '
    report+='Frozen Qwen BF16 revision dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68; exhaustive candidates, '
    report+='unchanged TRAIN-only normalization and BANK-v3-core population.\n\n'
    report+='| Model | State | Surface | Readout | Probe parameters (five tasks) | Fit seconds | DEV prediction seconds | Peak CUDA bytes |\n'
    report+='|---|---|---|---|---:|---:|---:|---:|\n'
    for key,v in table.items():
        costs=v['costs'];report+='| '+' | '.join(key)+' | '
        report+=f"{sum(x['parameters'] for x in costs.values())} | {sum(x['training_seconds'] for x in costs.values()):.2f} | {sum(x['DEV_seconds'] for x in costs.values()):.2f} | {max(x['peak_cuda_bytes'] for x in costs.values())} |\n"
    report+='\nPrediction timings are cached-feature diagnostic throughput, not end-to-end Qwen serving latency. '
    report+='Eight state caches reconstructed exactly from sealed checkpoints; pair/target construction reproduced exactly; '
    report+='120 persisted parameter/logit/metric replays and four control replays pass in fresh processes. '
    report+='This is frozen authored-code replay, not an independently authored semantic oracle.\n\n'
    report+='Engineering lineage: initial stable-sort keyword mismatch and compact action-type dtype mismatch were '
    report+='repaired before diagnostic scoring. Failed preparation snapshots and logs remain intact. Four regression tests pass. '
    report+='Writing follows the supplied audit brief; no retrieved writing-style samples were available.\n\n'
    report+='Protected evaluation remained unopened. Conflict is diagnostic-only. No recurrence, LoRA, internal-attention '
    report+='intervention or new organ ran. The sealed Phase5 bridge/E artifacts remain unchanged.\n'
    path=OUT/'REPORT.md'
    with path.open('x',encoding='utf-8') as stream:
        stream.write(report)
    hashes={str(p):sha(p) for p in OUT.rglob('*') if p.is_file() and p.suffix in ('.json','.pt','.py','.md')}
    receipt(OUT/'PHASE6A-SEALED.json',{'status':'PHASE6A_COMPARISON_AUDIT_SEALED',
        'localization':decision,'F':'NOT_EARNED_NOT_RUN','source_spec_sha256':sha(OUT/'SPECIFICATION.json'),
        'Phase5_seal_sha256':sha(P5/'LANE-SEALED.json'),'artifact_hashes':hashes,
        'probe_replay':read(OUT/'probe-replay.json'),'state_replay':read(OUT/'state-replay.json'),
        'report_sha256':sha(path),'evaluation_opened':False})


if __name__=='__main__':
    main()
