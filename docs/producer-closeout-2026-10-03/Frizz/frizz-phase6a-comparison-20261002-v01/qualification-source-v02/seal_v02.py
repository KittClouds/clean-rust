"""Additive report/seal qualification; original sealed bytes remain preserved."""
from common import OUT,read,receipt,sha


def main():
    old=OUT/'PHASE6A-SEALED.json';old_verification=read(OUT/'PHASE6A-SEAL-VERIFIED.json')
    if sha(old)!=old_verification['seal_sha256']:
        raise ValueError('original seal drift')
    for name,digest in read(old)['artifact_hashes'].items():
        from pathlib import Path
        if sha(Path(name))!=digest:
            raise ValueError('original sealed bytes drift')
    if read(OUT/'comparison-qualification-replay.json')['status']!='PASS':
        raise ValueError('qualification replay incomplete')
    text=(OUT/'REPORT.md').read_text()
    text+='\n## Versioned qualification v02\n\n'
    text+='This additive qualification preserves the original report, scores, parameters, branch rule and seal. '
    text+='No diagnostic refit or new organ ran.\n\n'
    text+='**Coarse pair comparison is accessible; useful full-set ranking is not established.** '
    text+='Trained E e-linear pair BA is .8453 and TinyMLP pair BA is .8483, while selected top1 is '
    text+='.0901/.0871 and MRR .2407/.2399. These are not a general representation collapse: '
    text+='the sealed goal-relative linear control remains .8134. No hidden nonlinear ranking rescue appeared.\n\n'
    text+='A linear scalar on [candidate;shared context] adds an identical context offset to every candidate; '
    text+='it cancels in ranking and CE. A weak cs-linear result alone cannot establish absent contextual information. '
    text+='The TinyMLP tests interactions. Candidate-local vectors already contain contextual Qwen signal. '
    text+='Bridge/E initialization panels duplicate exact zero-residual lineage, not independent replications.\n\n'
    text+='### Restriction baseline correction\n\n'
    text+='Original metrics.json uniform_top1_expectation values use full N even in restricted views. '
    text+='For conditional-universe chance comparison, use restricted-universe-baselines.json. '
    text+='Ranks, MRR, top-k, exclusions and the unrestricted branch decision are unaffected.\n\n'
    chance=read(OUT/'restricted-universe-baselines.json')['arms']
    text+='| Trained arm | Surface | Readout | Gold-type top1 | Gold-type chance | Predicted-type top1 | Predicted-type chance |\n'
    text+='|---|---|---|---:|---:|---:|---:|\n'
    for arm in ('bridge','E'):
        for mode in ('c','cs','e'):
            for family in ('linear','mlp'):
                key=':'.join((arm,'trained',mode,family));c=chance[key]
                r=read(OUT/'panel'/arm/'trained'/mode/family/'metrics.json')['metrics']['selected_ranking']
                text+=f"| {arm} | {mode} | {family} | {r['gold_type']['all']['selected']['top1']:.4f} | {c['gold_type']['selected_uniform_top1']:.4f} | {r['predicted_type']['all']['selected']['top1']:.4f} | {c['predicted_type']['selected_uniform_top1']:.4f} |\n"
    text+='\nE e-linear gold-type top1 .1532 versus within-type uniform .1140 is still weak. '
    text+='Thus the residual is not explained solely by type identification; within-type comparison remains a problem.\n\n'
    q=read(OUT/'comparison-qualification.json')
    text+='### Pair-type strata (descriptive, not selection criteria)\n\n'
    text+='| Trained arm | Surface | Readout | Same-type pair BA | Pairs / roots | Different-type pair BA | Pairs / roots |\n'
    text+='|---|---|---|---:|---:|---:|---:|\n'
    for key,views in q['pair_type_strata'].items():
        a,b=views['selected_pair']['same_action_type'],views['selected_pair']['different_action_type']
        parts=key.split(':');text+='| '+' | '.join(parts)+' | '
        text+=f"{a['balanced_accuracy']} | {a['pairs']}/{a['roots']} | {b['balanced_accuracy']} | {b['pairs']}/{b['roots']} |\n"
    text+='\nRoot counts below 200 remain descriptive; pair counts are not independent world support. '
    text+='This post-fit decomposition does not alter the prospective F rule.\n\n'
    text+='Endpoint population audit: '+str(q['endpoint_population_audit'])+'. '
    text+='Where logged selection and the optimal singleton coincide, equal endpoint numbers are a bank property, '
    text+='not two independent confirmations. Keep the endpoint contracts separate.\n\n'
    text+='**Final disposition: no automatic F.** Seal weak full-universe accessibility at this fixed dose, '
    text+='while retaining the positive coarse-pair and goal-relative findings. Neither an E-specific information-loss '
    text+='claim nor information-theoretic absence is established. Protected evaluation remains unopened.\n'
    path=OUT/'REPORT-v02.md'
    with path.open('x',encoding='utf-8') as stream:
        stream.write(text)
    files={str(p):sha(p) for p in OUT.rglob('*') if p.is_file() and p.suffix in ('.json','.pt','.py','.md')}
    receipt(OUT/'PHASE6A-SEALED-v02.json',{'status':'PHASE6A_COMPARISON_AUDIT_SEALED',
        'predecessor_seal_sha256':sha(old),'localization':read(OUT/'LOCALIZATION.json'),
        'F':'NOT_EARNED_NOT_RUN','changes':'additive restricted-universe chance correction and descriptive pair/endpoint qualification; no score refit',
        'report_sha256':sha(path),'artifact_hashes':files,'evaluation_opened':False})


if __name__=='__main__':
    main()
