"""Post-hoc presentation: CONTEXT.json, DISPOSITION.json, REPORT.md. Written AFTER DEV scoring.

Nothing scored depends on this file: it reads receipts and re-derives the within-type chance baseline from frozen targets.
Its hash is recorded in ANALYSIS-ADDENDUM.json before it runs.
"""
import torch

from common import ALL_ARMS, OUT, P6A, P7A, read, receipt, run_dir, sha
import data as dd
from train import eligible_subset

FINDING = 'PARTITIONED_PL_SEED0_DOES_NOT_SURVIVE_LEARNS_COARSE_LEGALITY_ORDER_LOSES_SELECTED_VS_LEGAL_NO_CONFIRMATION'
NAMES = {'ce': 'A  CE (control)', 'vanilla_pl': 'B  vanilla PL', 'partitioned_pl': 'C  partitioned PL',
         'vanilla_pl_truncated': 'supp. vanilla PL (truncated)'}


def f3(x):
    return 'n/a' if x is None else f'{x:.3f}'


def table(rows, header):
    out = ['| ' + ' | '.join(header) + ' |', '|' + '---|' * len(header)]
    out += ['| ' + ' | '.join(str(c) for c in r) + ' |' for r in rows]
    return '\n'.join(out)


def context():
    D = eligible_subset(dd.load_split('DEV'))
    t = D['targets']
    sel = t['selected'].clamp_min(0)
    ts = t['types'].gather(1, sel[:, None]).squeeze(1)
    n_same = ((t['types'] == ts[:, None]) & t['mask']).sum(1).float()
    ctx = {'chance': {'unrestricted_uniform_top1': float((1 / t['mask'].sum(1).float()).mean()),
                      'within_type_uniform_top1': float((1 / n_same).mean()),
                      'within_type_uniform_MRR': float(torch.tensor([sum(1 / k for k in range(1, int(n) + 1)) / n for n in n_same]).mean()),
                      'mean_same_type_candidates': float(n_same.mean())}}
    ctx['phase7a_context'] = {}
    for a in ('set', 'pointwise'):
        m = read(P7A / 'metrics' / f'{a}-epoch12-DEV.json')['metrics']['ranking']
        ctx['phase7a_context'][a] = {'top1': m['unrestricted']['all']['selected']['top1'], 'MRR': m['unrestricted']['all']['selected']['MRR'],
                                     'gold_type_top1': m['gold_type']['all']['selected']['top1'], 'gold_type_MRR': m['gold_type']['all']['selected']['MRR']}
    m = read(P6A / 'panel' / 'E' / 'trained' / 'e' / 'linear' / 'metrics.json')['metrics']['selected_ranking']
    ctx['phase6a_best_independent_scorer'] = {'top1': m['unrestricted']['all']['selected']['top1'], 'MRR': m['unrestricted']['all']['selected']['MRR'],
                                              'gold_type_top1': m['gold_type']['all']['selected']['top1'], 'gold_type_MRR': m['gold_type']['all']['selected']['MRR']}
    return ctx


def main():
    ctx = context()
    receipt(OUT / 'CONTEXT.json', ctx)
    rd = run_dir(0)
    cmp_ = read(rd / 'COMPARISON.json')
    M = {s: {a: read(rd / 'metrics' / f'{a}-epoch12-{s}.json')['metrics'] for a in ALL_ARMS} for s in ('DEV', 'TRAIN')}
    traj = {a: read(rd / 'arms' / a / 'trajectory.json')['trajectory'] for a in ALL_ARMS}
    cost = {a: read(rd / 'arms' / a / 'cost.json') for a in ALL_ARMS}
    hashes = {a: read(rd / 'arms' / a / 'checkpoint-hashes.json') for a in ALL_ARMS}
    ident = read(OUT / 'INPUT-IDENTITY.json')
    inv = read(rd / 'INVARIANCE-QUALIFICATION.json')
    eng = read(OUT / 'ENGINEERING-RECEIPT.json')
    replay = read(rd / 'REPLAY.json')
    dose = read(OUT / 'DOSE-DIAGNOSTIC.json')
    dose_replay = read(OUT / 'DOSE-DIAGNOSTIC-REPLAY.json')
    ch = ctx['chance']
    pc = cmp_['comparisons']['partitioned_pl__minus__ce']
    boot = pc['bootstrap']
    rule = pc['survival_rule']

    def R(arm, split='DEV', r='unrestricted'):
        return M[split][arm]['ranking'][r]['all']['selected']

    def P(arm, scope, key, split='DEV', field='root_mean'):
        return M[split][arm]['partition_order'][scope][key][field]

    receipt(OUT / 'DISPOSITION.json', {
        'finding': FINDING, 'survival_rule_output': rule['output'], 'rule_detail': rule, 'seed': 0, 'confirmation_seeds_run': 0,
        'one_sentence_answer': 'No: on these frozen states, training on the ordered partition structure produced a strong, generalising legal-vs-illegal '
                               'ordering but destroyed selected-vs-legal-other ordering, leaving gold-type ranking at the CE level and unrestricted top1 far below it.',
        'reason_no_confirmation': 'frozen survival rule not met', 'exploratory_dose_diagnostic': 'TRAIN partition ordering becomes strong (0.954), DEV stays at the floor',
        'evaluation_opened': False})

    L = []
    A = L.append
    A('# Frizz Phase 7B - partitioned Plackett-Luce ranking objective\n')
    A(f'Status: complete, seed 0 (primary) + one exploratory dose diagnostic. **Finding: `{FINDING}`** (frozen rule output: `{rule["output"]}`). '
      f'Fresh-process replay: **{replay["status"]}** (primary), **{dose_replay["status"]}** (dose diagnostic). Protected evaluation unopened.\n')
    A('## Answer\n')
    A('> Does training the scorer on the actual ordered partition structure recover more useful candidate ranking than ordinary selected-candidate CE?\n')
    A('**No.** Under the frozen contract, partitioned PL did not improve gold-type ranking '
      f'(top1 {R("partitioned_pl", r="gold_type")["top1"]:.3f} vs {R("ce", r="gold_type")["top1"]:.3f}, delta {boot["gold_type_top1"]["delta"]:+.3f}, '
      f'95% CI [{boot["gold_type_top1"]["ci95"][0]:+.3f}, {boot["gold_type_top1"]["ci95"][1]:+.3f}]; MRR delta {boot["gold_type_MRR"]["delta"]:+.3f}, '
      f'CI [{boot["gold_type_MRR"]["ci95"][0]:+.3f}, {boot["gold_type_MRR"]["ci95"][1]:+.3f}]) and **materially degraded** unrestricted selected top1 '
      f'({R("partitioned_pl")["top1"]:.3f} vs {R("ce")["top1"]:.3f}, delta {boot["selected_top1"]["delta"]:+.3f}, CI [{boot["selected_top1"]["ci95"][0]:+.3f}, {boot["selected_top1"]["ci95"][1]:+.3f}]). '
      'This is a statement about *this partitioned-PL construction on these frozen states and this scorer*, not about ranking likelihoods in general. '
      'No confirmation seeds were run and nothing was modified afterwards (the rule was not met).\n')
    A('What each objective actually learned (DEV, root-mean pair rates, 333 eligible roots):\n')
    A(table([[NAMES[a], f3(P(a, 'full', 'selected_gt_legal_other')), f3(P(a, 'full', 'selected_gt_illegal')), f3(P(a, 'full', 'legal_other_gt_illegal')),
              f3(P(a, 'full', 'legal_gt_illegal_all_legal_auc'))] for a in ALL_ARMS],
            ['arm', 'selected > legal-other', 'selected > illegal', 'legal-other > illegal', 'all-legal > illegal (AUC)']))
    A('\nPartitioned PL buys a large, **generalising** coarse-legality ordering '
      f'(legal-other > illegal {P("partitioned_pl", "full", "legal_other_gt_illegal"):.3f} vs CE {P("ce", "full", "legal_other_gt_illegal"):.3f}; paired delta '
      f'{boot["full:legal_other_gt_illegal"]["delta"]:+.3f}, CI [{boot["full:legal_other_gt_illegal"]["ci95"][0]:+.3f}, {boot["full:legal_other_gt_illegal"]["ci95"][1]:+.3f}]; TRAIN {P("partitioned_pl", "full", "legal_other_gt_illegal", "TRAIN"):.3f} so no wall here) '
      f'**and pays for it with selected-vs-legal-other**: {P("partitioned_pl", "full", "selected_gt_legal_other"):.3f} vs {P("ce", "full", "selected_gt_legal_other"):.3f} '
      f'(delta {boot["full:selected_gt_legal_other"]["delta"]:+.3f}, CI [{boot["full:selected_gt_legal_other"]["ci95"][0]:+.3f}, {boot["full:selected_gt_legal_other"]["ci95"][1]:+.3f}]). '
      'A rate well **below 0.5** means the scorer ranks other legal candidates above the selected one more often than not: the legality direction it learned is, on DEV, '
      'anti-aligned with the selection preference. Whole-root ordering (all P1 > all P2 > all P3) is essentially never achieved at the frozen dose '
      f'(DEV {P("partitioned_pl", "full", "reduced_full_ordering", "DEV", "rate"):.3f}).\n')

    A('## Frozen identities\n')
    A(f'- BANK-v3-core synthetic-only release `{ident["bank_v3_core"]["release_identity"]}`; corrected handoff `{ident["bank_v3_core"]["corrected_handoff_sha256"]}`.')
    A(f'- Same frozen trained-E inputs as Phase 7A, re-verified for this experiment against the Phase 6B seal closure ({ident["phase6b"]["artifacts_verified"]} artifacts) and the Phase 6A seal-v02:\n')
    A(table([[k, v['sha256'][:16] + '...', ', '.join(v['verified_against'])] for k, v in ident['consumed'].items()], ['file', 'sha256', 'verified against']))
    A('\nCanonical primary rendering only. Protected/EVAL files never opened. The standardiser (TRAIN-only) equals the Phase 7A one (`standardizer.json`).\n')

    A('## Specification (frozen before DEV scoring: `SPECIFICATION.json` / `.md`)\n')
    A('- **Candidate ABI** (365): `[cs 320; e 32; action-type one-hot 9; argument presence 4]`; IDs join-only; no distance/simulator/truth inputs.')
    A(f'- **Scorer** (all arms): `365->128->64->1`, GELU, candidate-independent, {cost["ce"]["parameters"]:,} parameters. **Identical initial weights** for all arms (sha `{cost["ce"]["initial_weights_sha256"][:16]}...` in every cost receipt).')
    A('- **A CE:** selected-candidate softmax CE + 0.5 x same-type CE.')
    A('- **B vanilla PL:** only one total order is identifiable from group labels (selected first) and ListMLE on it equals CE (unit-tested), so B is the conventional stochastic treatment: ListMLE on a fresh uniformly random linear extension of selected > legal-other > illegal at every call. No tied candidate is ever sorted by a fixed rule.')
    A('- **C partitioned PL:** exact grouped Plackett-Luce likelihood of P1 {selected} > P2 {other legal} > P3 {illegal}, internal orders marginalised exactly (log-space subset DP; |P2| <= 8 on this bank), + 0.5 x the same construction inside the selected candidate\'s action type. Selected and optimal coincide here and are one top partition.')
    A('- **Supplementary (outside the survival rule):** vanilla PL truncated after the legal candidates, to separate random order among legal candidates from random order among the illegal tail.')
    A('- **Training:** seed 0, 12 epochs, AdamW 3e-4 / wd 0.01, clip 1.0, cosine, root batch 32, FP32, identical root order and dose, training on the 1,333 endpoint-eligible TRAIN roots (504 steps); epoch 12 scored on CPU/FP32; no checkpoint selection. No legality head or BCE.\n')

    A('## Grouped-loss verification (before any interpretation)\n')
    A(f'{eng["summary"]}. Brute-force enumeration of all orderings (values **and** autograd gradients) for: single candidate, two partitions, three partitions, empty middle partition, all tied, one candidate per partition, group sizes 2/3/1, '
      'batched rows of different partition shapes; candidate-permutation invariance; padding invariance; finite non-zero gradients; float32 at large score range; oversized groups refused rather than approximated; '
      'selected-first ListMLE == CE; vanilla draws are valid total orders that upper-bound the marginal and never reduce to a fixed sort; arm losses vs brute force; shared initial weights; partition metrics on hand-computed cases.\n')
    A('A bug was found and fixed during the pre-freeze rehearsal (the DP was being run on the final 122-member illegal group, which has probability 1 and needs no enumeration); a regression test was added. '
      'A second rehearsal check showed partitioned PL can fit a 67-root set perfectly (top1, legal>illegal and full ordering all 1.0) while CE left legal>illegal at 0.64 - the objective and its orientation are right.\n')
    rows = []
    for key, r in inv['results'].items():
        if key.endswith('float32'):
            rows.append([key, r['roots'], f'{r["candidate_permutation_max_diff"]:.1e}', f'{r["alone_vs_padded_batch_max_diff"]:.1e}', f'{r["padded_slot_garbage_max_diff"]:.1e}', 'PASS' if r['pass'] else 'FAIL'])
    A(f'Real-data scorer invariance (candidate order, padding; FP32 shown, FP64 also passed; overall: {"PASS" if inv["pass"] else "FAIL"}):\n')
    A(table(rows, ['arm:epoch:split:dtype', 'roots', 'candidate-permutation diff', 'alone vs padded batch', 'padded-slot garbage', 'result']))
    A('')

    A('## Denominators\n')
    A(table([['TRAIN roots / endpoint-eligible (training population)', '12,000 / 1,333'], ['DEV roots / endpoint-eligible (evaluation population)', '3,000 / 333'],
             ['same-type selected-vs-alternative pairs DEV', f'{M["DEV"]["ce"]["same_type_pairs"]["pairs"]:,} ({M["DEV"]["ce"]["same_type_pairs"]["roots_with_pairs"]} roots)'],
             ['legal-other group size (mean / max)', '2.5 / 8 (same-type max 3)'], ['roots with no same-type legal alternative (TRAIN)', '777 of 1,333']], ['quantity', 'value']))
    A('\n## Primary ranking comparison (333 eligible DEV roots, epoch 12, CPU/FP32)\n')
    r = []
    for a in ALL_ARMS:
        u, g = R(a), R(a, r='gold_type')
        o = M['DEV'][a]['ranking']['unrestricted']['all']['optimal']
        r.append([NAMES[a], f3(u['top1']), f3(u['top3']), f3(u['top5']), f3(u['MRR']), f'{u["mean_rank"]:.1f}', f3(g['top1']), f3(g['MRR']),
                  f'{o["top1"]:.3f} / {o["MRR"]:.3f}', f3(M['DEV'][a]['same_type_pairs']['pooled_accuracy'])])
    r.append(['uniform chance', f3(ch['unrestricted_uniform_top1']), '', '', '', '', f3(ch['within_type_uniform_top1']), f3(ch['within_type_uniform_MRR']), '', '0.500'])
    ctx7 = ctx['phase7a_context']
    r.append(['context: Phase 7A SetRank / pointwise', f'{ctx7["set"]["top1"]:.3f} / {ctx7["pointwise"]["top1"]:.3f}', '', '', f'{ctx7["set"]["MRR"]:.3f} / {ctx7["pointwise"]["MRR"]:.3f}', '',
              f'{ctx7["set"]["gold_type_top1"]:.3f} / {ctx7["pointwise"]["gold_type_top1"]:.3f}', f'{ctx7["set"]["gold_type_MRR"]:.3f} / {ctx7["pointwise"]["gold_type_MRR"]:.3f}', '', ''])
    ref = ctx['phase6a_best_independent_scorer']
    r.append(['context: Phase 6A best independent scorer', f3(ref['top1']), '', '', f3(ref['MRR']), '', f3(ref['gold_type_top1']), f3(ref['gold_type_MRR']), '', ''])
    A(table(r, ['arm', 'top1', 'top3', 'top5', 'MRR', 'mean rank', 'gold-type top1', 'gold-type MRR', 'optimal top1 / MRR', 'same-type pair acc']))
    A('\nGold-type restriction is diagnostic only. Optimal-set and selected endpoints coincide on this population (one bank property, not two confirmations). Gold-type chance is the restricted-universe value (mean 10.5 same-type candidates).\n')
    A('Paired canonical-root bootstrap (2,000 resamples), 333 roots. Primary row: C minus A.\n')
    rows = []
    for key in ('partitioned_pl__minus__ce', 'partitioned_pl__minus__vanilla_pl', 'vanilla_pl__minus__ce', 'partitioned_pl__minus__vanilla_pl_truncated', 'vanilla_pl_truncated__minus__ce'):
        b = cmp_['comparisons'][key]['bootstrap']
        row = [key.replace('__minus__', ' - ')]
        for m_ in ('selected_top1', 'selected_MRR', 'gold_type_top1', 'gold_type_MRR', 'same_type_pair_accuracy'):
            x = b[m_]
            row.append(f'{x["delta"]:+.3f} [{x["ci95"][0]:+.3f}, {x["ci95"][1]:+.3f}]')
        rows.append(row)
    A(table(rows, ['comparison', 'selected top1', 'selected MRR', 'gold-type top1 (primary)', 'gold-type MRR', 'same-type pair acc']))
    A('')
    rows = []
    for key in ('partitioned_pl__minus__ce', 'partitioned_pl__minus__vanilla_pl', 'vanilla_pl__minus__ce'):
        b = cmp_['comparisons'][key]['bootstrap']
        row = [key.replace('__minus__', ' - ')]
        for m_ in ('full:selected_gt_legal_other', 'full:selected_gt_illegal', 'full:legal_other_gt_illegal', 'same_type:selected_gt_legal_other', 'same_type:legal_other_gt_illegal'):
            x = b[m_]
            row.append(f'{x["delta"]:+.3f} [{x["ci95"][0]:+.3f}, {x["ci95"][1]:+.3f}]')
        rows.append(row)
    A('Partition-order paired deltas (root-mean pair rates):\n')
    A(table(rows, ['comparison', 'selected>legal-other', 'selected>illegal', 'legal-other>illegal', 'same-type sel>legal-other', 'same-type legal-other>illegal']))
    A(f'\nSurvival rule on C - A: gold-type top1 criterion {rule["gold_type_top1_criterion"]}, gold-type MRR criterion {rule["gold_type_MRR_criterion"]}, '
      f'selected top1 not materially degraded (point delta >= -0.02) {rule["selected_top1_not_materially_degraded"]} -> **{rule["output"]}**.\n')

    A('## Partition-order diagnostics (frozen-dose primary run)\n')
    for split in ('DEV', 'TRAIN'):
        rows = []
        for a in ALL_ARMS:
            f, s = M[split][a]['partition_order']['full'], M[split][a]['partition_order']['same_type']
            rows.append([NAMES[a], f3(f['selected_gt_legal_other']['root_mean']), f3(f['selected_gt_illegal']['root_mean']), f3(f['legal_other_gt_illegal']['root_mean']),
                         f3(s['selected_gt_legal_other']['root_mean']), f3(s['selected_gt_illegal']['root_mean']), f3(s['legal_other_gt_illegal']['root_mean']),
                         f3(f['boundary_P1_over_P2']['rate']), f3(f['boundary_P2_over_P3']['rate']), f3(f['reduced_full_ordering']['rate']), f3(f['strict_three_partition_ordering']['rate'])])
        A(f'**{split}** (eligible roots; roots with the relevant partitions: P1>P2 {M[split]["ce"]["partition_order"]["full"]["boundary_P1_over_P2"]["roots"]}, P2>P3 {M[split]["ce"]["partition_order"]["full"]["boundary_P2_over_P3"]["roots"]}):\n')
        A(table(rows, ['arm', 'sel>legal', 'sel>illeg', 'legal>illeg', 'ST sel>legal', 'ST sel>illeg', 'ST legal>illeg', 'P1>P2 boundary', 'P2>P3 boundary', 'reduced full order', 'strict 3-partition']))
        A('')
    A('"All P1 > all P2 > all P3" and the min/max formulation (min(P1) > max(P2) and min(P2) > max(P3)) are the same event for sets, so one number is reported; the reduced version applies only the boundaries that exist for a root (empty partitions removed), the strict version needs all three partitions non-empty.\n')

    A('## Candidate-count bands (descriptive; no band reaches the 200-root floor)\n')
    rows = []
    for b, e in cmp_['candidate_count_bands'].items():
        if e['eligible_roots']:
            rows.append([b, e['eligible_roots']] + [f'{e[a]["selected_top1"]:.3f} / {e[a]["gold_type_top1"]:.3f}' for a in ALL_ARMS])
    A(table(rows, ['candidates', 'eligible roots'] + [f'{NAMES[a]} top1 / gold-type top1' for a in ALL_ARMS]))
    A('\nIn the two bands with real mass (29-64, 65-128) the PL arms lose unrestricted top1 (near 0) and are within noise of CE on gold-type top1 (0.128/0.141 vs 0.144/0.148 for partitioned vs CE). The 1-28 band has 17 roots (gold-type top1 0.118 vs 0.059 is 2 vs 1 root) and the 129-171 band 1 root; neither supports a claim.\n')
    A('Per action type (only MOVE, 249 roots, reaches the 200-root floor): gold-type top1 for CE / vanilla / partitioned on MOVE: '
      + ' / '.join(f'{M["DEV"][a]["per_action_type"]["MOVE"]["gold_type"]["top1"]:.3f}' for a in ('ce', 'vanilla_pl', 'partitioned_pl')) + '. Other types are descriptive only.\n')

    A('## Training dynamics (frozen dose; recorded every epoch, never used for selection)\n')
    rows = []
    for e in (1, 2, 4, 8, 12):
        row = [e]
        for a in ('ce', 'partitioned_pl', 'vanilla_pl'):
            t = traj[a][e]
            row += [f'{t["train_loss"]["total"]:.2f}', f'{t["TRAIN_monitor"]["selected_top1"]:.3f}', f'{t["TRAIN_monitor"]["reduced_full_ordering"]:.3f}', f'{t["DEV_monitor"]["selected_top1"]:.3f}']
        rows.append(row)
    A(table(rows, ['epoch'] + [f'{n} {c}' for n in ('CE', 'partitioned', 'vanilla') for c in ('loss', 'TRAIN top1', 'TRAIN full-order', 'DEV top1')]))
    A('\nAt the frozen dose the PL arms are **under-fitted on TRAIN itself** (partitioned PL loss plateaus near 9; TRAIN full ordering 0.02) because the objective demands all ~60 illegal candidates fall below every legal one, '
      'a coarse legality partition these frozen features express only weakly. CE fits the single selected target quickly (TRAIN top1 0.58).\n')

    A('## Exploratory dose-sensitivity diagnostic (post-hoc; outside the survival rule; plan declared before running)\n')
    A('`DOSE-DIAGNOSTIC-PLAN.json` fixed one dose before running: 10x learning rate (3e-3) and 5x epochs (60), everything else identical, all four arms, no tuning, no DEV-based choice. '
      'It was triggered by the primary run\'s TRAIN under-fit, which left the outcome "TRAIN partition ordering strong, DEV weak" unassessable. It does **not** change the disposition.\n')
    rows = []
    for a in ALL_ARMS:
        d, t = dose['final_epoch_metrics'][f'{a}:DEV']['metrics'], dose['final_epoch_metrics'][f'{a}:TRAIN']['metrics']
        du, dg = d['ranking']['unrestricted']['all']['selected'], d['ranking']['gold_type']['all']['selected']
        tu = t['ranking']['unrestricted']['all']['selected']
        rows.append([NAMES[a], f3(tu['top1']), f3(t['partition_order']['full']['reduced_full_ordering']['rate']), f3(t['partition_order']['full']['legal_other_gt_illegal']['root_mean']),
                     f3(du['top1']), f3(dg['top1']), f3(du['MRR']), f3(d['partition_order']['full']['selected_gt_legal_other']['root_mean']),
                     f3(d['partition_order']['full']['legal_other_gt_illegal']['root_mean']), f3(d['partition_order']['full']['reduced_full_ordering']['rate'])])
    A(table(rows, ['arm (lr 3e-3, 60 ep)', 'TRAIN top1', 'TRAIN full-order', 'TRAIN legal>illeg', 'DEV top1', 'DEV gold-type top1', 'DEV MRR', 'DEV sel>legal', 'DEV legal>illeg', 'DEV full-order']))
    b = dose['paired_bootstrap_DEV']['partitioned_pl__minus__ce']
    A(f'\nWith enough dose, partitioned PL **does** learn the partition structure on TRAIN (top1 0.96, full ordering 0.95, legal>illegal 1.00) - and DEV stays at the floor: '
      f'gold-type top1 {b["gold_type_top1"]["delta"]:+.3f} vs CE (CI [{b["gold_type_top1"]["ci95"][0]:+.3f}, {b["gold_type_top1"]["ci95"][1]:+.3f}]; PL gold-type top1 is below the 0.114 within-type chance), '
      f'selected top1 {b["selected_top1"]["delta"]:+.3f} (CI [{b["selected_top1"]["ci95"][0]:+.3f}, {b["selected_top1"]["ci95"][1]:+.3f}]), DEV full ordering {dose["final_epoch_metrics"]["partitioned_pl:DEV"]["metrics"]["partition_order"]["full"]["reduced_full_ordering"]["rate"]:.3f}. '
      'The selected-vs-legal-other rate stays near 0.30 on DEV even when TRAIN is 0.97, so the anti-alignment is not a dose artefact. CE at this dose also memorises TRAIN (0.99) and DEV does not move. '
      'This is the "TRAIN partition ordering strong, DEV weak - same generalization wall" outcome, here for the ranking head.\n')

    A('## Cost\n')
    A(table([[NAMES[a], f'{cost[a]["parameters"]:,}', f'{cost[a]["pure_training_seconds"]:.0f}', f'{dose["costs"][a]["pure_training_seconds"]:.0f}', f'{cost[a]["peak_cuda_memory_bytes"]/1e6:.0f}', f'{cost[a]["steps"]}']
             for a in ALL_ARMS], ['arm', 'parameters', 'train s (12 ep)', 'train s (dose diag., 60 ep)', 'peak CUDA MB', 'steps']))
    A(f'\nDevice {cost["ce"]["device"]}; FP32. The exact grouped-PL loss costs {cost["partitioned_pl"]["pure_training_seconds"] / cost["ce"]["pure_training_seconds"]:.0f}x the CE arm\'s training time (a Python-level subset DP over <= 256 states), still under two minutes. CPU scoring: sub-second.\n')

    A('## Outcome catalogue\n')
    A(table([
        ['PL improves selected-vs-legal but not legal-vs-illegal', 'no - the opposite'],
        ['PL improves legal-vs-illegal strongly but not selected-vs-legal', f'**yes**, and worse: legal>illegal {P("ce","full","legal_other_gt_illegal"):.2f} -> {P("partitioned_pl","full","legal_other_gt_illegal"):.2f}, selected>legal {P("ce","full","selected_gt_legal_other"):.2f} -> {P("partitioned_pl","full","selected_gt_legal_other"):.2f}'],
        ['partitioned PL > vanilla PL (ties/partial order matter)', f'barely: legal>illegal +{cmp_["comparisons"]["partitioned_pl__minus__vanilla_pl"]["bootstrap"]["full:legal_other_gt_illegal"]["delta"]:.3f}; top1, MRR, gold-type, pair accuracy indistinguishable'],
        ['vanilla PL ~ partitioned PL (tie structure not limiting)', '**mostly yes** (also vs the truncated vanilla: all primary differences <= 0.003)'],
        ['partitioned PL ~ CE (geometry not enough)', 'gold-type metrics yes; unrestricted top1 no (PL much worse)'],
        ['TRAIN partition ordering strong, DEV weak', '**yes** at the exploratory dose (TRAIN 0.95, DEV 0.006); not assessable at the frozen dose (TRAIN 0.02)']],
            ['pre-listed outcome', 'observed']))
    A('\n## What this does and does not conclude\n')
    A('- Concluded: with a small candidate-independent scorer on the frozen trained-E states, an exact grouped-PL objective teaches a generalising legality ordering but not a within-type or selected-vs-legal preference; the hypothesis "ordinary CE gives the wrong ordering geometry for a signal the model already has" is not supported here. Tie handling (exact marginalisation vs random linear extensions) did not matter.')
    A('- Not concluded: that different weights between the partition terms, a larger or interacting scorer, or other ranking likelihoods would fail (the contract fixed the weights and forbids adding auxiliaries); anything about other seeds (none run: the rule was not met); anything about unseen renderings.')
    A('- Caveats: (a) 1,333 training roots and 333 evaluation roots (CI half-width ~ +/-3 pp); (b) the partitions use gold legality at TRAIN time only (as specified); (c) the dose diagnostic is exploratory and single-dose; (d) the cause of the below-chance selected-vs-legal-other rate is described, not diagnosed; (e) the vanilla arm\'s definition is a documented design decision (only the selected-first order is identifiable, and on it vanilla = CE); (f) candidate-count bands and non-MOVE action types are below the 200-root floor.')
    A('- The next architecture is **not** started from this fan-out.\n')

    A('## Artifacts\n')
    A(table([[NAMES[a], 'epoch 0', hashes[a][f'{a}-epoch00.pt'][:20] + '...', 'epoch 12 (scored)', hashes[a][f'{a}-epoch12.pt'][:20] + '...'] for a in ALL_ARMS], ['arm', '', 'sha256', '', 'sha256']))
    A('\n`SPECIFICATION.json` (frozen before DEV scoring) - `INPUT-IDENTITY.json` - `ENGINEERING-RECEIPT.json` - `runs/seed0/` (checkpoints, scores, metrics, `COMPARISON.json`, `INVARIANCE-QUALIFICATION.json`, `REPLAY.json`) - '
      '`DOSE-DIAGNOSTIC-PLAN.json` / `DOSE-DIAGNOSTIC.json` / `DOSE-DIAGNOSTIC-REPLAY.json` / `dose-diagnostic/` - `CONTEXT.json` - `DISPOSITION.json` - `ANALYSIS-ADDENDUM.json` - `PHASE7B-SEALED.json`.')
    (OUT / 'REPORT.md').open('x', encoding='utf-8').write('\n'.join(L) + '\n')
    print('REPORT written;', FINDING)


if __name__ == '__main__':
    main()
