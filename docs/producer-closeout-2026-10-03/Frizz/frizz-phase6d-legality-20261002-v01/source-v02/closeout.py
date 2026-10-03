"""Receipt closure; active logs excluded, fresh seal verifier."""
import sys
from common import *

def main(verify=False):
    setup();lock()
    if verify:
        seal=read(OUT/'PHASE6D-SEALED.json')
        for name,digest in seal['artifacts'].items():
            if sha(OUT/name)!=digest:raise ValueError('sealed artifact drift '+name)
        receipt(OUT/'seal-replay.json',{'status':'PASS','artifacts_verified':len(seal['artifacts']),
            'seal_sha256':sha(OUT/'PHASE6D-SEALED.json'),'protected_evaluation_opened':False})
        print('SEALED AND VERIFIED',flush=True);return
    r=read(OUT/'results.json');b=r['results']['trained']['primary'];g=b['full_legal_sets'];s=b['same_type_legal_sets'];fit=read(OUT/'training-complete.json')
    lines=['# Phase 6D — factorized legality acquisition','',r['decision']['disposition'],'',
        'One legality-only gate; Qwen/E/goal heads and Phase6C consequence scores frozen. Protected evaluation unopened.',
        '', '| Endpoint (333 canonical DEV roots) | Initialization | Epoch 8 |','|---|---:|---:|']
    for key in ('BA','precision','recall','F1','full_exact_set_recovery','root_mean_Jaccard','false_positives_per_root','false_negatives_per_root','selected_retention'):
        lines.append(f"| {key} | {r['results']['init']['primary']['full_legal_sets'][key]:.6f} | {g[key]:.6f} |")
    lines += ['',f"Same-type exact sets: {s['full_exact_set_recovery']:.6f}.",
        f"Root FP/FN decomposition: {g['root_decomposition']}.",
        '', '| Path | Full top1 | Full MRR | Same-type top1 | Same-type MRR |','|---|---:|---:|---:|---:|']
    for name,p in b['paths'].items():
        f=p['full']['selected'];t=p['same_type']['selected']
        lines.append(f"| {name} | {f['top1']:.6f} | {f['MRR']:.6f} | {t['top1']:.6f} | {t['MRR']:.6f} |")
    lines += ['', 'Full results.json contains separate selected/optimal denominators, top3/top5, best-optimal ranks, every root FP/FN, both renderings, action-type/candidate-count/renderer slices, support census, and paired bootstrap intervals.',
        '', 'Gate rejection is an error (MRR/top-k zero), not eligibility exclusion. Empty gates abstain. Fixed logit>0 threshold; no threshold or cardinality shopping.',
        '', 'Gold legality is not permission policy. Its 81.98% same-type result does not imply full-set decision sufficiency: gold-gate full-set top1 remains 0.30%. Learned pruning gains on incorrect sets are not evidence of precise legality.',
        '', f"Exactly recovered sets: {b['exact_gate_subset_roots']} roots; learned/gold composition is identical on this subset.",
        '', 'Preservation: frozen E production goal/binding/globalization/renderer panel retained exactly; candidate permutation test passed. Consequence legal ordering and distance MAE unchanged; all frozen DEV consequence outputs independently reproduced exactly.',
        '', f"Parameters: {fit['parameters']}; training {fit['fit_seconds']:.2f}s, {fit['optimizer_steps']} steps, CPU FP32 four threads. Forward timings/bytes: evaluation-cost.json. No new Qwen extraction or GPU use.",
        '', 'Independent fresh-process gate-logit/metric replay and canonical legality derivation pass. Source, specification, checkpoints, upstream identities, and receipts are hash-bound. Active logs excluded from closure.',
        '', f"Next proposed experiment (not run): {r['decision']['next_experiment_proposed_only']}. F/comparator/recurrence/LoRA remain unrun."]
    with (OUT/'REPORT.md').open('x',encoding='utf-8') as f:f.write('\n'.join(lines)+'\n')
    artifacts={str(p.relative_to(OUT)).replace('\\','/'):sha(p) for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in str(p)
        and p.name not in ('run.stdout.log','run.stderr.log')}
    receipt(OUT/'PHASE6D-SEALED.json',{'status':'SEALED','artifacts':artifacts,'disposition':r['decision']['disposition'],
        'consequence_checkpoint_sha256':sha(C6/'epoch-8.pt'),'E_checkpoint_sha256':sha(P5/'E/run/epoch-8.pt'),
        'specification_sha256':sha(OUT/'SPECIFICATION.json'),'protected_evaluation_opened':False})

if __name__=='__main__':main('--verify' in sys.argv)
