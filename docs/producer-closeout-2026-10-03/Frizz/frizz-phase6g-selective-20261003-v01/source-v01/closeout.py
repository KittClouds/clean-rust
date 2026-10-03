"""Report the fixed response vector and bind all artifacts after replay."""
from common import *
def main():
    lock();v=read(OUT/'results.json');base=read(OUT/'binary-baselines.json');train=read(OUT/'training-complete.json')
    for name in ('fresh-process-replay','independent-target-replay','tests'):
        if read(OUT/(name+'.json'))['status']!='PASS':raise ValueError('required verification '+name)
    lines=['# Phase 6G — selective legality under observable uncertainty','',v['decision']['disposition'],'',
        'Frozen Qwen/E caches; one 365→128→64→3 classifier, twelve fixed epochs. No new extraction, backbone training, LoRA, bank changes or protected evaluation contact.',
        'Targets are the sealed strict observable statuses, not canonical binary legality. Unknown candidates have no canonical legality loss.', '',
        '| Primary renderer | Macro F1 | BA | False certainty (true U) | Certainty coverage | Exact three-way roots |',
        '|---|---:|---:|---:|---:|---:|']
    for name,d in [('D binary',base['arms']['D_trained']['primary']),('Selective init',v['results']['init']['primary']),('Selective epoch12',v['results']['trained']['primary'])]:
        m=d['selective'];lines.append(f"| {name} | {m['macro_F1']:.4f} | {m['BA']:.4f} | {m['false_certainty']['rate']:.2%} | {m['certainty_coverage']:.2%} | {m['exact_three_way_partition']:.2%} |")
    m=v['results']['trained']['primary']['selective'];lines += ['',
        '## Frozen rule and interpretation','',
        'Survival requires false certainty ≤5%, certainty coverage ≥70%, and ≥5 percentage-point exact observable partition gain over the prospectively fixed D-trained binary baseline. No best raw baseline or threshold was selected. Primary rendering is fixed; paired rendering, init delta and every binary baseline remain reported.',
        json.dumps(v['decision'],indent=2),'',
        'False certainty is conditional on true UNRESOLVED candidates; false abstention is conditional on true CERTAIN candidates. Absolute all-candidate fractions and all supports are also recorded. This task is not canonical exact legal-set recovery.',
        'The strict deterministic oracle is the status reference: its candidate certainty coverage is bounded by unresolved observable evidence. It does not promise the frozen ranker can choose the logged or optimal candidate. Oracle filtering removes only CERTAIN_ILLEGAL and retains all UNRESOLVED candidates.',
        '', '## Class responses','', '| Class | Support | Precision | Recall |','|---|---:|---:|---:|']
    for name,c in m['classes'].items():lines.append(f"| {name} | {c['support']} | {c['precision']} | {c['recall']} |")
    lines += ['',f"False abstention: {m['false_abstention']['rate']:.2%}; exact certain-legal set: {m['exact_sets']['CERTAIN_LEGAL']:.2%}; exact certain-illegal set: {m['exact_sets']['CERTAIN_ILLEGAL']:.2%}.",
        '', '## Selection and procedural authorization','',
        'All ranking uses unchanged Phase6C cost and stable candidate-index ties. UNKNOWN is never pruned. Full-set and gold-type-conditioned exact logged ranking and optimal-set ranking have separate denominators. Uncertainty slices are fixed from the true strict observable partition; predicted slices are separately descriptive.',
        'Authorization uses the model-chosen winner, not the gold logged candidate. It requires predicted CERTAIN_LEGAL and resolved rivals with frozen cost no worse than the winner, including ties. This is procedural authority under the frozen ranking contract, not policy permission, optimality certification or canonical truth assurance.', '']
    for path,d in v['results']['trained']['primary']['selection'].items():
        full=d['full']['selected'];same=d['same_type_gold_conditioned']['selected']
        lines += [f"### {path}",'',f"Full selected top1/MRR: {full['top1']} / {full['MRR']} (n={full['eligible_roots']}); same-type top1/MRR: {same['top1']} / {same['MRR']} (n={same['eligible_roots']})."]
        if 'full_authority' in d:
            au=d['full_authority'];lines += [f"Authorized full-menu roots: {au['authorized_roots']}/{au['roots']}; coverage {au['authorized_coverage']:.2%}; logged accuracy among authorized eligible roots {au['logged_exact_accuracy']}; optimal hit {au['optimal_set_hit']}; oracle-status-consistent fraction {au['true_status_consistency_among_authorized']}."]
        lines += ['']
    lines += ['## Verification and preservation','',
        f"Trainable parameters: {train['parameters']}; fixed training time: {train['fit_seconds']:.2f}s. Detailed forward latency/checkpoint size in evaluation-cost.json. Root-normalized TRAIN CE and TRAIN-only balancing/normalization are pinned in TRAIN-contract.json and normalization.pt.",
        'Unit controls cover perfect three-way recovery, binary false-certainty, root-balanced loss, unresolved retention, tied-unknown authorization veto and exact candidate permutation equivariance. Independent reconstruction checks all strict labels against actual sealed TRAIN/DEV worlds. Fresh-process replay reproduces init/epoch12 logits, every metric, all binary rescoring and disposition exactly.',
        'Qwen, E, goal heads and frozen ranker remain unmodified and their identities are hash-checked. This experiment learns observable statuses only; canonical truth is confined to diagnostic truth correctness. No protected evaluation files opened.',
        'All renderer/candidate-count slices, root arrays, class denominators, selected/optimal endpoints and authority denominators are in the machine-readable package. No composite score, automatic escalation or rescue fit.', '']
    with (OUT/'REPORT.md').open('x',encoding='utf-8') as f:f.write('\n'.join(lines))
    artifacts={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    receipt(OUT/'PHASE6G-SEALED.json',{'status':'SEALED','decision':v['decision'],'artifacts':artifacts,
        'observation_contract_sha256':sha(F6/'OBSERVATION-CONTRACT.json'),'protected_evaluation_opened':False})
    print('PHASE6G SEALED',flush=True)
if __name__=='__main__':main()
