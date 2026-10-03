"""Frozen DH02 analysis: a single primary contrast; no selective exclusions."""
import itertools
import json
import pathlib
import sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONDITIONS = ['immediate', 'quiet', 'distractor']


def validate(rows, config):
    keys = [(r['side'], r['tau'], r['seed'], r['arm'], r['condition']) for r in rows]
    expected = set(itertools.product(config['sides'], config['taus'], config['seeds'], config['arms'], CONDITIONS))
    assert len(keys) == len(set(keys)), 'duplicate outcome cell'
    assert set(keys) == expected, 'missing or unexpected outcome cell'
    lookup = dict(zip(keys, rows))
    for side, tau, seed, arm in itertools.product(config['sides'], config['taus'], config['seeds'], config['arms']):
        group = [lookup[side, tau, seed, arm, c] for c in CONDITIONS]
        assert all(r['result']['acquisition_state_sha256'] == group[0]['result']['acquisition_state_sha256'] for r in group), 'acquisition states differ'
        assert all(r['result']['outcome']['probe_acquisition'] == group[0]['result']['outcome']['probe_acquisition'] for r in group)
        if arm == 'Z':
            assert all(r['result']['outcome']['curve'] == group[0]['result']['outcome']['curve'] for r in group), 'no-learning actions differ'
        for row in group:
            o = row['result']['outcome']
            d = row['result']['diagnostics']
            assert 0 <= o['probe_reversal'] <= 1 and 0 <= o['accuracy'] <= 1
            assert o['hot_allocations'] == 0 and o['unique_cue_codes'] == config['cues']
            assert o['max_gain_mass_error'] < 1e-5
            assert arm != 'Z' or o['changed_weights'] == 0
            assert all(p['trials'] == config['trials']//2 for p in d)
            assert d[0]['interval_eligibility_l1_mean'] == 0
            if row['condition'] != 'distractor':
                assert d[1]['interval_eligibility_l1_mean'] == 0
            expected_events = config['trials'] if row['condition'] == 'immediate' else config['trials']//2*(config['delay_steps']+2)
            assert o['stimulus_events'] == expected_events
    return lookup


def contrast(lookup, config, side, first='quiet', second='distractor'):
    differences = np.array([[lookup[side, tau, seed, 'E', first]['result']['outcome'][config['primary_metric']] -
                             lookup[side, tau, seed, 'E', second]['result']['outcome'][config['primary_metric']]
                             for tau in config['taus']] for seed in config['seeds']])
    bundles = differences.mean(axis=1)
    rng = np.random.default_rng(config['bootstrap_seed'])
    samples = bundles[rng.integers(0, len(bundles), size=(config['bootstrap_resamples'], len(bundles)))].mean(axis=1)
    return dict(mean=float(bundles.mean()), ci95=np.quantile(samples, [0.025, 0.975]).tolist(),
                seed_differences=bundles.tolist(), n_seed_bundles=len(bundles),
                tau_means={str(t): float(differences[:, i].mean()) for i, t in enumerate(config['taus'])})


def analyze(run):
    config = json.loads((ROOT / 'config.json').read_text())
    execution = json.loads((run / 'execution.json').read_text())
    assert execution['complete'] and config['primary_metric'] == 'probe_reversal'
    rows = []
    nulls = []
    for side in config['sides']:
        for tau in config['taus']:
            records = [json.loads(line) for line in (run / f'{side}-tau{tau:g}.jsonl').read_text().splitlines()]
            assert [r['seed'] for r in records] == config['seeds']
            for bundle in records:
                null = bundle['null_routing']
                assert null['degree_preserved'] and null['source_strength_preserved'] and null['accepted'] > 0 and null['retained_fraction'] < 0.95
                assert all(r['seed'] == bundle['seed'] and r['side'] == side and r['tau'] == tau for r in bundle['results'])
                nulls.append(null)
                rows.extend(bundle['results'])
    lookup = validate(rows, config)
    assert len(rows) == execution['outcome_rows']
    primary = contrast(lookup, config, 'R')
    if primary['ci95'][0] > 0:
        status = 'SUPPORTED_TOTAL_DISTRACTOR_EXPOSURE_EFFECT_IN_MODEL'
    elif primary['ci95'][1] < 0:
        status = 'OPPOSITE_DIRECTION_TO_DISTRACTOR_IMPAIRMENT_HYPOTHESIS'
    else:
        status = 'NO_CLEAR_QUIET_VS_DISTRACTOR_EFFECT'
    comparisons = {side: {'quiet_minus_distractor': contrast(lookup, config, side),
                          'immediate_minus_quiet': contrast(lookup, config, side, 'immediate', 'quiet'),
                          'immediate_minus_distractor': contrast(lookup, config, side, 'immediate', 'distractor')}
                   for side in config['sides']}
    means = {}
    fields = ['accuracy', 'acquisition', 'reversal', 'late_acquisition', 'late_reversal', 'probe_acquisition', 'probe_reversal', 'seconds', 'state_bytes', 'work']
    for side in config['sides']:
        means[side] = {}
        for arm in config['arms']:
            means[side][arm] = {}
            for condition in CONDITIONS:
                selected = [r['result'] for r in rows if r['side'] == side and r['arm'] == arm and r['condition'] == condition]
                entry = {f: float(np.mean([r['outcome'][f] for r in selected])) for f in fields}
                entry['curve'] = np.mean([r['outcome']['curve'] for r in selected], axis=0).tolist()
                entry['phase_diagnostics'] = [{f: float(np.mean([r['diagnostics'][phase][f] for r in selected])) for f in selected[0]['diagnostics'][phase]} for phase in [0, 1]]
                for f in ['observer_array_bytes', 'final_weight_floor_fraction', 'final_weight_ceiling_fraction']:
                    entry[f] = float(np.mean([r[f] for r in selected]))
                entry['probe_reversal_by_tau'] = {str(tau): float(np.mean([lookup[side,tau,seed,arm,condition]['result']['outcome']['probe_reversal'] for seed in config['seeds']])) for tau in config['taus']}
                means[side][arm][condition] = entry
    result = dict(status=status, primary=primary, comparisons=comparisons, means=means, execution=execution,
                  arms=len(rows), training_trials=len(rows)*config['trials'],
                  unique_acquisition_streams=len(config['sides'])*len(config['taus'])*len(config['seeds'])*len(config['arms']),
                  unique_reversal_streams=len(rows), all_acquisition_states_matched=True,
                  zero_hot_allocations=True, numpy_version=np.__version__,
                  null_retained_range=[min(n['retained_fraction'] for n in nulls), max(n['retained_fraction'] for n in nulls)],
                  total_online_edge_visits=sum(r['result']['outcome']['work'] for r in rows))
    (run / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    report = ['# DH-02 measured results', '', f'**{status}**', '',
              'All reversal conditions began from identical acquired states within each seed, side, tau and learning arm.', '',
              f"Primary: right-slice uniform-learning final reversal probe, quiet minus distractor = **{100*primary['mean']:+.3f} percentage points**, paired 95% bootstrap interval **[{100*primary['ci95'][0]:+.3f}, {100*primary['ci95'][1]:+.3f}]**.", '',
              f"{len(rows)} arm runs; {result['training_trials']:,} computed training trials; {result['unique_acquisition_streams']} distinct acquisition streams reused across three conditions; 24 new computational seed bundles; two taus; one specimen.", '',
              '## Final reversal probe accuracy', '', '| Soma slice | Arm | Immediate | Quiet delay | Distractor delay |', '|---|---|---:|---:|---:|']
    for side in config['sides']:
        for arm in config['arms']:
            report.append(f'| {side} | {arm} | ' + ' | '.join(f"{100*means[side][arm][c]['probe_reversal']:.2f}%" for c in CONDITIONS) + ' |')
    report += ['', 'E learns with uniform modulation; Z has fixed weights. Only the primary contrast is inferential; all other comparisons are descriptive.', '',
               '## Primary sensitivity by eligibility tau', '']
    report += [f'- tau={tau}: quiet minus distractor {100*value:+.3f} percentage points.' for tau, value in primary['tau_means'].items()]
    report += ['', '## Reversal diagnostics: right slice, uniform learning', '',
               '| Condition | Cue L1 | Interval L1 | Cue share of component L1 | Cue output saturation | Proposed clipping | A/B relative routing RMS |',
               '|---|---:|---:|---:|---:|---:|---:|']
    for c in CONDITIONS:
        d = means['R']['E'][c]['phase_diagnostics'][1]
        report.append(f"| {c} | {d['cue_eligibility_l1_mean']:.3f} | {d['interval_eligibility_l1_mean']:.3f} | {100*d['cue_share_of_component_l1_mean']:.2f}% | {100*d['cue_output_saturation_fraction']:.2f}% | {100*d['proposed_clip_fraction_mean']:.2f}% | {100*d['routing_relative_rms_ab_mean']:.3f}% |")
    report += ['', 'These are observer-only summaries. L1 component shares describe pre-clipping eligibility, not fractions of measured learning or proof of erroneous credit. Counterfactual routing uses the same current DAN state and is never delivered to E/Z.', '',
               '## Phase performance: right slice, uniform learning', '', '| Condition | Acquisition probe | Online reversal | Late reversal | Final reversal probe |', '|---|---:|---:|---:|---:|']
    for c in CONDITIONS:
        m = means['R']['E'][c]
        report.append('| ' + c + ' | ' + ' | '.join(f'{100*m[f]:.2f}%' for f in ['probe_acquisition','reversal','late_reversal','probe_reversal']) + ' |')
    report += ['', '## Integrity and resources', '',
               '- Complete expected outcome grid, matching acquired-state hashes, no-learning action parity, zero quiet-interval eligibility, and routing-null invariants passed.',
               f"- Simulator execution including diagnostics and setup: {execution['wall_seconds']:.3f} seconds on {execution['threads']} workers. Downloads/build/analysis excluded.",
               '- No hot-loop allocations. Observer CPU and arrays are additional experimental instrumentation costs.',
               f"- Learner float arrays: {means['R']['E']['immediate']['state_bytes']:,.0f} bytes; observer float arrays: {means['R']['E']['immediate']['observer_array_bytes']:,.0f} bytes per right-slice simulator. Immutable graph/cache, blank pattern and initial-weight audit copy are additional.",
               '', '## Limits', '',
               '- Quiet versus distractor tests total sensory exposure during reversal at matched time steps. It does not separately identify baseline adaptation, eligibility contamination, clipping, or other internal mediators.',
               '- Immediate versus quiet changes both elapsed time and internal-state updates.',
               '- Same fixed local rule, arbitrary synthetic action mapping and model dynamics; no rule search or post-outcome tuning.',
               '- One animal; left/right are related soma slices. No biological functional validation.',
               '- DH-01 remains frozen. The archived DH-01 engine is used only for compatibility tests.', '',
               'Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY. https://male-cns.janelia.org/download/']
    (run / 'REPORT.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    print(json.dumps({'status':status,'primary':primary,'arms':len(rows)}, indent=2))


if __name__ == '__main__':
    analyze(pathlib.Path(sys.argv[1]))
