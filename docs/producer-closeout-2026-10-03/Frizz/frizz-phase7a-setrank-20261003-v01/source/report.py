"""Post-hoc presentation: CONTEXT.json, DISPOSITION.json, REPORT.md. Written AFTER DEV scoring.

Nothing scored depends on this file: it only reads receipts (and re-derives the within-type chance baseline from the
frozen targets). Its own hash is recorded in ANALYSIS-ADDENDUM.json before it is run.
"""
import torch

from common import OUT, P6A, RELIABLE_ROOTS, read, receipt, sha
import data as dd

FINDING = 'SETRANK_SEED0_BELOW_SURVIVAL_RULE_NO_CONFIRMATION_NO_WIDENING'


def pct(x):
    return f'{100 * x:.1f}'


def f4(x):
    return 'n/a' if x is None else f'{x:.4f}'


def context():
    D = dd.load_split('DEV')
    t = D['targets']
    el = t['selected_eligible']
    sel = t['selected'].clamp_min(0)
    ts = t['types'].gather(1, sel[:, None]).squeeze(1)
    n_same = ((t['types'] == ts[:, None]) & t['mask']).sum(1).float()
    chance = {'within_type_uniform_top1': float((1 / n_same)[el].mean()),
              'within_type_uniform_MRR': float(torch.tensor([sum(1 / k for k in range(1, int(n) + 1)) / n for n in n_same[el]]).mean()),
              'unrestricted_uniform_top1': float((1 / t['mask'].sum(1).float())[el].mean()),
              'trivial_all_illegal_root_fraction': float((~D['legal'].any(1)).float().mean()),
              'mean_same_type_candidates_per_eligible_root': float(n_same[el].mean())}
    refs = {}
    for mode in ('c', 'cs', 'e'):
        for fam in ('linear', 'mlp'):
            m = read(P6A / 'panel' / 'E' / 'trained' / mode / fam / 'metrics.json')['metrics']['selected_ranking']
            u, g = m['unrestricted']['all']['selected'], m['gold_type']['all']['selected']
            refs[f'E:trained:{mode}:{fam}'] = {'top1': u['top1'], 'MRR': u['MRR'], 'gold_type_top1': g['top1'], 'gold_type_MRR': g['MRR']}
    return {'chance': chance, 'sealed_independent_scorer_reference_phase6a': refs,
            'reference_note': 'Phase 6A TinyMLP/linear independent scalar scorers on the same frozen trained-E states, same 333 DEV roots'}


def table(rows, header):
    out = ['| ' + ' | '.join(header) + ' |', '|' + '---|' * len(header)]
    out += ['| ' + ' | '.join(str(c) for c in r) + ' |' for r in rows]
    return '\n'.join(out)


def main():
    ctx = context()
    receipt(OUT / 'CONTEXT.json', ctx)
    cmp_ = read(OUT / 'COMPARISON.json')
    boot = cmp_['bootstrap']
    M = {a: read(OUT / 'metrics' / f'{a}-epoch12-DEV.json')['metrics'] for a in ('set', 'pointwise')}
    T = {a: read(OUT / 'metrics' / f'{a}-epoch12-TRAIN.json')['metrics'] for a in ('set', 'pointwise')}
    I = {a: read(OUT / 'metrics' / f'{a}-epoch00-DEV.json')['metrics'] for a in ('set', 'pointwise')}
    traj = {a: read(OUT / 'arms' / a / 'trajectory.json')['trajectory'] for a in ('set', 'pointwise')}
    cost = {a: read(OUT / 'arms' / a / 'cost.json') for a in ('set', 'pointwise')}
    hashes = {a: read(OUT / 'arms' / a / 'checkpoint-hashes.json') for a in ('set', 'pointwise')}
    eq = read(OUT / 'EQUIVARIANCE-QUALIFICATION.json')
    att = read(OUT / 'ATTENTION-DIAGNOSTICS.json')['arms']
    ident = read(OUT / 'INPUT-IDENTITY.json')
    replay = read(OUT / 'REPLAY.json') if (OUT / 'REPLAY.json').exists() else {'status': 'PENDING'}
    rk = lambda a, r='unrestricted': M[a]['ranking'][r]['all']['selected']
    ch = ctx['chance']
    ref_e = ctx['sealed_independent_scorer_reference_phase6a']['E:trained:e:linear']

    disp = cmp_['disposition_rule_output']
    read_out = {
        'finding': FINDING,
        'rule_output': disp,
        'one_sentence_answer': 'On these frozen trained-E candidate states, full candidate self-attention bought at most a small, '
                               'sub-threshold within-type gain over a matched independent scorer (gold-type top1 +3.6 pp, 95% CI [+0.3, +6.9]; '
                               'all other primary metrics inside noise) and did not solve within-type comparison '
                               '(same-type pair accuracy 0.544 vs 0.536) or legality sets (exact-set recovery on roots with a legal candidate: 0).',
        'seed': 0, 'confirmation_seeds_run': 0,
        'reason_no_confirmation': 'frozen survival rule not met (STRONG needs gold-type top1 delta >= +0.05; PRESERVE needs gold-type MRR delta >= +0.03 with lower bound > 0)',
        'evaluation_opened': False}
    receipt(OUT / 'DISPOSITION.json', read_out)

    L = []
    A = L.append
    A('# Frizz Phase 7A - SetRank-style permutation-equivariant candidate ranker\n')
    A(f'Status: complete, seed 0 only. **Finding: `{FINDING}`** (frozen rule output: `{disp}`). Fresh-process replay: **{replay["status"]}**. Protected evaluation unopened.\n')
    A('## Answer\n')
    A('> Does letting candidates explicitly see one another solve more of the ranking problem than a matched independent scorer?\n')
    A('**Only marginally, and not by the frozen standard.** The SetRank arm beats its matched pointwise control by '
      f'**+{pct(boot["gold_type_top1"]["delta"])} pp gold-type top1** (95% root-bootstrap CI [{100 * boot["gold_type_top1"]["ci95"][0]:+.1f}, {100 * boot["gold_type_top1"]["ci95"][1]:+.1f}] pp), '
      f'which is short of the +5 pp threshold; unrestricted top1 (+{pct(boot["selected_top1"]["delta"])} pp), MRR (+{boot["selected_MRR"]["delta"]:.3f}) and gold-type MRR (+{boot["gold_type_MRR"]["delta"]:.3f}) '
      'all have intervals containing 0. Within-type pair accuracy is 0.544 vs 0.536 and the legality sets are unrecovered by both arms. '
      'This is a statement about *this SetRank construction on these frozen states*, not about set attention in general. No confirmation seeds, no widening.\n')
    A('Three framing points the headline number hides:\n')
    A(f'1. **Absolute level is near chance.** Within-type uniform top1 on these 333 roots is {ch["within_type_uniform_top1"]:.3f} (MRR {ch["within_type_uniform_MRR"]:.3f}). '
      f'SetRank gold-type top1 is {rk("set","gold_type")["top1"]:.3f} (MRR {rk("set","gold_type")["MRR"]:.3f}); the pointwise control is {rk("pointwise","gold_type")["top1"]:.3f} (MRR {rk("pointwise","gold_type")["MRR"]:.3f}) - essentially chance.')
    A(f'2. **SetRank only reaches the level of the older sealed independent scorers; it does not exceed them.** The best Phase 6A independent scorer on the same states (E trained e-linear) has gold-type top1 {ref_e["gold_type_top1"]:.4f} / MRR {ref_e["gold_type_MRR"]:.4f} and unrestricted top1 {ref_e["top1"]:.4f} / MRR {ref_e["MRR"]:.4f}; '
      f'SetRank is {rk("set","gold_type")["top1"]:.4f} / {rk("set","gold_type")["MRR"]:.4f} and {rk("set")["top1"]:.4f} / {rk("set")["MRR"]:.4f}. '
      'The matched pointwise MLP control is *below* those simple scorers, so part of the paired gap is the control under-performing, not SetRank over-performing.')
    A(f'3. **Both arms memorise TRAIN and do not transfer.** TRAIN selected top1 {T["set"]["ranking"]["unrestricted"]["all"]["selected"]["top1"]:.3f} (SetRank) / {T["pointwise"]["ranking"]["unrestricted"]["all"]["selected"]["top1"]:.3f} (control) vs DEV {rk("set")["top1"]:.3f} / {rk("pointwise")["top1"]:.3f}; '
      f'TRAIN same-type pair accuracy {T["set"]["same_type_pairs"]["pooled_accuracy"]:.3f} / {T["pointwise"]["same_type_pairs"]["pooled_accuracy"]:.3f} vs DEV {M["set"]["same_type_pairs"]["pooled_accuracy"]:.3f} / {M["pointwise"]["same_type_pairs"]["pooled_accuracy"]:.3f}. '
      'A likely mechanism (not tested here): the upstream E states were themselves trained on TRAIN, so TRAIN states may carry TRAIN-specific selection information that DEV states do not. Whatever the cause, this train/DEV gap comes with the frozen-feature design; this experiment did not change it.\n')

    A('## Frozen identities\n')
    A(f'- BANK-v3-core synthetic-only release `{ident["bank_v3_core"]["release_identity"]}`; corrected handoff `{ident["bank_v3_core"]["corrected_handoff_sha256"]}`; release manifest `{ident["bank_v3_core"]["release_manifest_sha256"]}`.')
    A(f'- Phase 6B seal `{ident["phase6b"]["seal_sha256"]}` (all {ident["phase6b"]["artifacts_verified"]} sealed artifacts re-hashed; disposition `{ident["phase6b"]["disposition"]}`); Phase 6A seal-v02 `84b91d45a4f46da122a5b2dae22384b7d2fb07d0fd39cf3c07fba556172db0a8`.')
    A('- Consumed (each verified against the Phase 6A seal-v02, the Phase 6B specification inputs where listed, and its sidecar receipt):\n')
    A(table([[k, v['sha256'][:16] + '...', f'{v["bytes"]/1e6:.0f} MB', ', '.join(v['verified_against'])] for k, v in ident['consumed'].items()], ['file', 'sha256', 'size', 'verified against']))
    A('\nThe trained-E state caches physically live in the Phase 6A directory (the Phase 6B directory holds gold-relation and probe-panel artifacts, none of which are consumed); '
      'the Phase 6B specification lists the same cache hashes as its own frozen inputs, which is how the binding to that experiment is checked. '
      'Semantic binding: `c` (256) and `s` (64) form the 320-d `cs`; `e` is the 32-d integrated state - exactly the Phase 6A `features(cache, "cs"|"e")` definitions.\n')
    A('Not run: the paired-render nuisance check (no sealed paired-render state caches exist; Qwen is not regenerated). Protected/EVAL files: never opened.\n')

    A('## Specification (frozen before any DEV scoring: `SPECIFICATION.json`/`.md`)\n')
    A('- **Token** (365): `[cs 320; e 32; action-type one-hot 9; argument-slot presence 4]`; presence = `cand_ent >= 0`; entity IDs never features; TRAIN-only standardisation of cs/e.')
    A('- **SetRank:** Linear 365->128, 2 pre-LN blocks (4 heads x 32, dense key-padded self-attention, FFN 256 GELU), final LN, utility head 128->1, legality head 128->1; no positional/index encoding.')
    A('- **Control:** identical, but each attention sub-layer is replaced by a candidate-independent FFN(128->256->128).')
    A(f'- **Parameters:** SetRank {cost["set"]["parameters"]:,}; control {cost["pointwise"]["parameters"]:,} (0.08% apart).')
    A('- **Loss:** 1.0 full-set selected CE + 0.5 same-type selected CE + 0.25 root-normalised balanced legality BCE; gold legality never masks the softmax.')
    A('- **Training:** seed 0, 12 epochs, AdamW 3e-4 / wd 0.01, clip 1.0, cosine per step, root batch 16, FP32, complete candidate sets, within-root permutation augmentation; both arms consume identical root-order and permutation streams; epoch 12 scored on CPU/FP32; no checkpoint selection.\n')

    A('## Permutation-equivariance qualification (passed before interpretation)\n')
    rows = []
    for key, r in eq['results'].items():
        if key.endswith('float32') or key.endswith('float64'):
            rows.append([key, r['roots'], r['checks'], f'{r["max_abs_utility_logit_diff"]:.2e}', f'{r["max_abs_legality_logit_diff"]:.2e}',
                         r['top1_mismatches'], r['top5_order_mismatches'], r['legality_decision_mismatches'],
                         f'{r["padding"]["alone_vs_padded_batch_max_diff"]:.1e}', 'PASS' if r['pass'] else 'FAIL'])
    A(table(rows, ['arm:epoch:split:dtype', 'roots', 'perm checks', 'max |d utility|', 'max |d legality|', 'top1 mism.', 'top5 mism.', 'decision mism.', 'padding diff', 'result']))
    A('\n200 stratified roots per split (100 eligible), 6 random candidate permutations each; FP32 tolerance 1e-4, FP64 1e-9. A positional negative-control model is detected as non-equivariant in the unit tests, so the detector is not vacuous. '
      f'Unit tests: {read(OUT / "ENGINEERING-RECEIPT.json")["summary"]}. The full pipeline was rehearsed twice on TRAIN-only stand-ins with no DEV contact (identical numbers).\n')

    A('## Denominators\n')
    A(table([['TRAIN roots / eligible', '12,000 / 1,333'], ['DEV roots / eligible', '3,000 / 333'],
             ['same-type selected-vs-alternative pairs TRAIN / DEV', f'11,883 / {M["set"]["same_type_pairs"]["pairs"]:,} (332 DEV roots)'],
             ['max candidates', '171'], ['DEV candidates', f'{M["set"]["legality_all_roots"]["candidates"]:,}'],
             ['DEV roots with >=1 gold-legal candidate', M['set']['legality_all_roots']['roots_with_gold_legal']],
             ['trivial all-illegal DEV roots', f'{round(ch["trivial_all_illegal_root_fraction"] * 3000)} ({100 * ch["trivial_all_illegal_root_fraction"]:.2f}%)']], ['quantity', 'value']))
    A('\nAll match the denominators stated in the task and in Phase 6B.\n')

    A('## Primary ranking comparison (333 eligible DEV roots, epoch 12, CPU/FP32)\n')
    r = []
    for label, key in (('selected top1', 'selected_top1'), ('selected MRR', 'selected_MRR'), ('gold-type top1', 'gold_type_top1'),
                       ('gold-type MRR', 'gold_type_MRR'), ('optimal-set top1 (separate contract)', 'optimal_top1'),
                       ('same-type pair accuracy (root mean, 332 roots)', 'same_type_pair_accuracy_root_mean')):
        b = boot[key]
        r.append([label, f4(b['a_mean']), f4(b['b_mean']), f'{b["delta"]:+.4f}', f'[{b["ci95"][0]:+.4f}, {b["ci95"][1]:+.4f}]', f'{b["fraction_resamples_positive"]:.3f}'])
    A(table(r, ['metric', 'SetRank', 'pointwise', 'delta', 'paired 95% CI (2000 root resamples)', 'P(delta>0)']))
    A('\nOptimal-set and selected endpoints coincide on this population (singleton equality, Phase 6A); equal numbers are one bank property, not two confirmations.\n')
    su, pu = M['set']['ranking']['unrestricted']['all']['selected'], M['pointwise']['ranking']['unrestricted']['all']['selected']
    A(f'SetRank does not dominate: its unrestricted top3 ({su["top3"]:.3f} vs {pu["top3"]:.3f}) and mean rank ({su["mean_rank"]:.1f} vs {pu["mean_rank"]:.1f}) are slightly worse than the control\'s, '
      'and gold-type mean rank is a tie (5.35 vs 5.44). The gains are concentrated in top-1 hits, not in the bulk of the ordering.\n')
    r = []
    for name in ('set', 'pointwise'):
        u, g = M[name]['ranking']['unrestricted']['all']['selected'], M[name]['ranking']['gold_type']['all']['selected']
        r.append([name, f4(u['top1']), f4(u['top3']), f4(u['top5']), f4(u['MRR']), f'{u["mean_rank"]:.2f}', f4(g['top1']), f4(g['MRR']), f'{g["mean_rank"]:.2f}'])
    r.append(['init (epoch 0) set / pointwise', f4(I['set']['ranking']['unrestricted']['all']['selected']['top1']) + ' / ' + f4(I['pointwise']['ranking']['unrestricted']['all']['selected']['top1']), '', '', '', '', '', '', ''])
    r.append(['uniform chance', f4(ch['unrestricted_uniform_top1']), '', '', '', '', f4(ch['within_type_uniform_top1']), f4(ch['within_type_uniform_MRR']), ''])
    r.append(['Phase 6A best independent scorer (E e-linear)', f4(ref_e['top1']), '', '', f4(ref_e['MRR']), '', f4(ref_e['gold_type_top1']), f4(ref_e['gold_type_MRR']), ''])
    A(table(r, ['arm', 'top1', 'top3', 'top5', 'MRR', 'mean rank', 'gold-type top1', 'gold-type MRR', 'gold-type mean rank']))
    A('\nGold-type restriction is diagnostic only (never an input). The "uniform" gold-type row is the restricted-universe chance (mean 10.5 same-type candidates), matching the Phase 6A correction.\n')

    A('## Candidate-count bands (descriptive; only the 29-64 and 65-128 bands exceed ~100 roots, none reaches the 200-root floor)\n')
    r = []
    for b, e in cmp_['candidate_count_bands'].items():
        if e['eligible_roots']:
            r.append([b, e['eligible_roots'], f'{e["unrestricted_top1"]["set"]:.3f} / {e["unrestricted_top1"]["pointwise"]:.3f}', f'{e["unrestricted_mrr"]["set"]:.3f} / {e["unrestricted_mrr"]["pointwise"]:.3f}',
                      f'{e["gold_type_top1"]["set"]:.3f} / {e["gold_type_top1"]["pointwise"]:.3f}', f'{e["gold_type_mrr"]["set"]:.3f} / {e["gold_type_mrr"]["pointwise"]:.3f}'])
    A(table(r, ['candidates', 'eligible roots', 'top1 (set / pw)', 'MRR (set / pw)', 'gold-type top1 (set / pw)', 'gold-type MRR (set / pw)']))
    A('\nThe 1-28 band (17 roots) shows the largest apparent gap and the 129-171 band has 1 root; neither supports a claim. In the two bands with real mass the gold-type top1 gap is +0.037 (29-64) and +0.015 (65-128): no sign that set attention helps more as sets grow.\n')

    A('## Per action type (support retained; only MOVE meets the 200-root reliability floor)\n')
    r = []
    for k in M['set']['per_action_type']:
        s, p = M['set']['per_action_type'][k], M['pointwise']['per_action_type'][k]
        if s['eligible_roots']:
            r.append([k, s['eligible_roots'], 'yes' if s.get('root_supported') else 'descriptive only', f'{s["gold_type"]["top1"]:.3f}', f'{p["gold_type"]["top1"]:.3f}', f'{s["unrestricted"]["top1"]:.3f}', f'{p["unrestricted"]["top1"]:.3f}'])
    A(table(r, ['type', 'eligible DEV roots', 'reliable', 'gold-type top1 set', 'gold-type top1 pw', 'top1 set', 'top1 pw']))
    A('\nMOVE (249 roots): gold-type top1 0.137 vs 0.104. Cells with < 200 roots are not capability claims.\n')

    A('## Legality sidecar (independent head; root-normalised balanced BCE)\n')
    r = []
    for pop, label in (('legality_all_roots', 'all 3,000 DEV roots'), ('legality_eligible_roots', '333 eligible roots')):
        for a in ('set', 'pointwise'):
            l = M[a][pop]
            r.append([label, a, f4(l['candidate_BA']), f4(l['precision']), f4(l['recall']), f4(l['F1']), f4(l['exact_legal_set_recovery']),
                      f4(l['exact_among_roots_with_gold_legal']), f4(l['root_mean_jaccard']), f'{l["false_positives_per_root"]:.2f}', f'{l["false_negatives_per_root"]:.2f}'])
    A(table(r, ['population', 'arm', 'cand. BA', 'precision', 'recall', 'F1', 'exact legal-set', 'exact (roots with a legal cand.)', 'mean Jaccard', 'FP/root', 'FN/root']))
    el = {a: M[a]['legality_eligible_roots'] for a in ('set', 'pointwise')}
    A(f'\nSelected-candidate retention (eligible): {el["set"]["selected_candidate_retention"]:.3f} / {el["pointwise"]["selected_candidate_retention"]:.3f}; same-type exact legal-set recovery: {el["set"]["same_type_exact_legal_set_recovery"]:.3f} / {el["pointwise"]["same_type_exact_legal_set_recovery"]:.3f}. '
      f'Candidate BA is ~0.80 for both, but at ~7.8 false positives per root the **root-level sets are useless**: overall exact-set recovery ({M["set"]["legality_all_roots"]["exact_legal_set_recovery"]:.4f} / {M["pointwise"]["legality_all_roots"]["exact_legal_set_recovery"]:.4f}) equals the trivial all-illegal-root fraction ({ch["trivial_all_illegal_root_fraction"]:.4f}), i.e. credit comes only from roots with nothing legal; on roots with a legal candidate it is {M["set"]["legality_all_roots"]["exact_among_roots_with_gold_legal"]:.4f} / {M["pointwise"]["legality_all_roots"]["exact_among_roots_with_gold_legal"]:.4f}. '
      f'Paired difference in exact-set recovery: {boot["legality_exact_set_all_3000_roots"]["delta"]:+.4f} (CI [{boot["legality_exact_set_all_3000_roots"]["ci95"][0]:+.4f}, {boot["legality_exact_set_all_3000_roots"]["ci95"][1]:+.4f}]) - set attention does not help legality grounding.\n')

    A('## Training dynamics (recorded every epoch; never used for selection)\n')
    r = []
    for e in (0, 1, 2, 4, 6, 8, 10, 12):
        row = [e]
        for a in ('set', 'pointwise'):
            tr = traj[a][e]
            row += [f'{tr["TRAIN_monitor"]["selected_top1"]:.3f}', f'{tr["DEV_monitor"]["selected_top1"]:.3f}', f'{tr["DEV_monitor"]["gold_type_top1"]:.3f}']
        r.append(row)
    A(table(r, ['epoch', 'set TRAIN top1', 'set DEV top1', 'set DEV gold-type', 'pw TRAIN top1', 'pw DEV top1', 'pw DEV gold-type']))
    A('\nDEV never improves beyond the first epochs while TRAIN climbs monotonically: the gap is memorisation. (Per-epoch monitoring is GPU; the scored endpoint is the CPU recomputation from the epoch-12 checkpoint.)\n')

    A('## Attention diagnostics (descriptive; not causal explanations)\n')
    a0, a12 = att['set:epoch00'], att['set:epoch12']
    r = []
    for l in range(2):
        for h in range(4):
            r.append([f'L{l}H{h}', f'{a0["entropy_by_layer_head"][l][h]:.3f} -> {a12["entropy_by_layer_head"][l][h]:.3f}',
                      f'{a0["same_type_by_layer_head"][l][h]:.3f} -> {a12["same_type_by_layer_head"][l][h]:.3f}', f'{a12["base_same_type_by_layer_head"][l][h]:.3f}',
                      f'{a0["sel_legal_by_layer_head"][l][h]:.3f} -> {a12["sel_legal_by_layer_head"][l][h]:.3f}', f'{a12["base_legal_by_layer_head"][l][h]:.3f}'])
    A(table(r, ['layer/head', 'normalised entropy (init -> trained)', 'same-type mass (init -> trained)', 'same-type base rate', 'selected->legal mass (init -> trained)', 'legal base rate']))
    A('\n')
    A(f'Representation change after each block, `||h^(L) - h^(0)|| / ||h^(0)||` (cosine to the projected input in brackets): SetRank trained {a12["representation_change_relative_L2_by_layer"][0]:.2f}, {a12["representation_change_relative_L2_by_layer"][1]:.2f} ({a12["representation_cosine_to_input_projection_by_layer"][0]:.2f}, {a12["representation_cosine_to_input_projection_by_layer"][1]:.2f}); '
      f'pointwise trained {att["pointwise:epoch12"]["representation_change_relative_L2_by_layer"][0]:.2f}, {att["pointwise:epoch12"]["representation_change_relative_L2_by_layer"][1]:.2f} ({att["pointwise:epoch12"]["representation_cosine_to_input_projection_by_layer"][0]:.2f}, {att["pointwise:epoch12"]["representation_cosine_to_input_projection_by_layer"][1]:.2f}); '
      f'at initialisation both ~{a0["representation_change_relative_L2_by_layer"][0]:.2f}/{a0["representation_change_relative_L2_by_layer"][1]:.2f}.\n')
    A('Reading (descriptive): at initialisation attention is near uniform (entropy ~0.99) and matches both base rates. After training the heads moved only modestly (entropy 0.79-0.99): '
      'some heads shifted toward same-type keys (L1H1/L1H3 ~0.28-0.29 vs 0.207 base) and others toward different-type keys (L0H1/L0H3 same-type mass 0.135, i.e. type contrast), '
      'and selected-query mass on legal keys moved from the 0.047 base rate to 0.028-0.071 in both directions. So there is a learned type-contrast structure, but little legality- or selection-specific structure, '
      'and the candidate representations changed only a little more than the pointwise control\'s. Consistent with "almost-pointwise solution plus weak type contrast".\n')

    A('## Cost\n')
    A(table([[a, f'{cost[a]["parameters"]:,}', f'{cost[a]["pure_training_seconds"]:.0f}', f'{cost[a]["train_seconds_including_monitoring"]:.0f}', f'{cost[a]["peak_cuda_memory_bytes"]/1e6:.0f}', f'{cost[a]["steps"]:,}'] for a in ('set', 'pointwise')],
             ['arm', 'parameters', 'training s (excl. monitoring)', 'incl. monitoring s', 'peak CUDA MB', 'steps']))
    A(f'\nDevice {cost["set"]["device"]}; FP32; dense N^2 attention at N<=171 is cheap (SetRank training {cost["set"]["pure_training_seconds"] / cost["pointwise"]["pure_training_seconds"]:.2f}x the control). CPU scoring of DEV: seconds.\n')

    A('## Survival rule and the outcome catalogue\n')
    A(f'Frozen rule output: **{disp}**. STRONG needs gold-type top1 delta >= +0.05 with lower bound > 0: observed +{boot["gold_type_top1"]["delta"]:.3f}, lower bound +{boot["gold_type_top1"]["ci95"][0]:.3f} (positive, but the effect is below threshold). '
      f'PRESERVE needs gold-type MRR delta >= +0.03 with lower bound > 0: observed +{boot["gold_type_MRR"]["delta"]:.3f}, lower bound {boot["gold_type_MRR"]["ci95"][0]:+.3f}. Neither holds, so the experiment is sealed without confirmation seeds or widening. '
      'The borderline gold-type-top1 interval is exactly the kind of single-seed signal the rule says not to chase.\n')
    A(table([
        ['ranking jumps, legality unchanged', 'no: ranking moved little, legality unchanged'],
        ['legality exact sets jump, ranking also jumps', 'no: legality sets unrecovered'],
        ['same-type jumps much more than full-set', 'slightly (+3.6 vs +2.1 pp), within noise; not "much more"'],
        ['different-type improves, same-type weak', 'attention learned type contrast but same-type comparison stays near chance (pair accuracy 0.54)'],
        ['attention model ~ pointwise control', '**closest match**: explicit set interaction adds little on this frozen state'],
        ['training ranking improves but permutation test fails', 'no: qualification passed everywhere']], ['catalogue entry', 'observed']))
    A('\n## What this does and does not conclude\n')
    A('- Concluded: the implementation is permutation-equivariant and padding-invariant; with this construction, seed 0, fixed contract and these frozen trained-E states, set attention did not recover the within-type residual or the legality sets.')
    A('- Not concluded: that set attention is useless; that a different set architecture, loss family (Plackett-Luce was deliberately excluded), pooling, or inputs would fail; anything about other seeds (one seed was run by design); anything about unseen renderings (paired-render check not run).')
    A('- Caveats: (a) heavy TRAIN memorisation / train-DEV state shift limits what any head fitted on TRAIN E states can learn; (b) the matched pointwise MLP control under-performs the older simple independent scorers, so the paired gap overstates the advantage over the best independent baseline (SetRank ~ that baseline); '
      '(c) only 333 ranking roots (CI half-width ~ +/-3 pp); (d) bands and action types below 200 roots are descriptive; (e) a lower interval bound of +0.003 on one primary metric is not a robust finding.')
    A('- The next architecture is **not** started from this fan-out.\n')

    A('## Artifacts\n')
    A('Checkpoints (`arms/<arm>/checkpoints/`, sha256 in `arms/<arm>/checkpoint-hashes.json`):\n')
    A(table([[a, 'epoch00', hashes[a][f'{a}-epoch00.pt'][:20] + '...'] for a in ('set', 'pointwise')] + [[a, 'epoch12 (scored)', hashes[a][f'{a}-epoch12.pt'][:20] + '...'] for a in ('set', 'pointwise')], ['arm', 'checkpoint', 'sha256']))
    A('\n`SPECIFICATION.json` (frozen before DEV scoring) · `INPUT-IDENTITY.json` · `ENGINEERING-RECEIPT.json` · `EQUIVARIANCE-QUALIFICATION.json` · `metrics/` · `scores/` · `COMPARISON.json` · `ATTENTION-DIAGNOSTICS.json` · `CONTEXT.json` · `REPLAY.json` · `DISPOSITION.json` · `PHASE7A-SEALED.json`.')
    (OUT / 'REPORT.md').open('x', encoding='utf-8').write('\n'.join(L) + '\n')
    print('REPORT written;', FINDING)


if __name__ == '__main__':
    main()
