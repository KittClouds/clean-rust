"""Frozen DH-01 analysis. No selection of seeds, settings or successful arms."""
import collections
import hashlib
import json
import pathlib
import sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARMS = ['A', 'B', 'C', 'D', 'E', 'Z']


def paired_effect(rows, suite, config):
    lookup = {(r['seed'], r['setting'], r['arm']): r['outcome']['accuracy'] for r in rows if r['suite'] == suite}
    differences = np.array([[lookup[seed, setting['name'], 'A'] - lookup[seed, setting['name'], 'B']
                             for setting in config['settings']] for seed in config['seeds']])
    bundles = differences.mean(axis=1)
    rng = np.random.default_rng(20260911)
    samples = bundles[rng.integers(0, len(bundles), size=(20000, len(bundles)))].mean(axis=1)
    return {'mean': float(bundles.mean()), 'ci95': np.quantile(samples, [0.025, 0.975]).tolist(),
            'setting_means': {s['name']: float(differences[:, i].mean()) for i, s in enumerate(config['settings'])},
            'seed_bundle_differences': bundles.tolist(), 'n_seed_bundles': len(bundles)}


def chart(means, out):
    # Static SVG generated from measurements; no image synthesis or web hosting.
    colors = dict(zip(ARMS, ['#167d9a', '#de6c36', '#7651b3', '#ae6fa5', '#479453', '#777777']))
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="410" viewBox="0 0 1080 410">',
             '<rect width="1080" height="410" fill="white"/>',
             '<text x="25" y="30" font-family="sans-serif" font-size="20">DH-01: measured online accuracy (means; uncertainty in report)</text>']
    for panel, suite in enumerate(['primary', 'left_transfer', 'task_transfer']):
        x0 = 55 + panel * 350
        parts.append(f'<text x="{x0}" y="63" font-family="sans-serif" font-size="15">{suite}</text>')
        for tick in [0.3, 0.5, 0.7, 0.9]:
            y = 330 - (tick - 0.3) * 350
            parts.append(f'<path d="M{x0} {y}h280" stroke="#dddddd"/><text x="{x0-32}" y="{y+4}" font-family="sans-serif" font-size="11">{tick:.1f}</text>')
        parts.append(f'<path d="M{x0+140} 83V330" stroke="#bbbbbb" stroke-dasharray="4 4"/>')
        for arm in ARMS:
            curve = means[suite][arm]['curve']
            points = ' '.join(f'{x0+i*40},{330-(value-0.3)*350}' for i, value in enumerate(curve))
            parts.append(f'<polyline points="{points}" fill="none" stroke="{colors[arm]}" stroke-width="2"/>')
        parts.append(f'<text x="{x0}" y="352" font-family="sans-serif" font-size="12">Acquisition → | reversal → (64-trial blocks)</text>')
    for i, arm in enumerate(ARMS):
        parts.append(f'<text x="{55+i*165}" y="390" fill="{colors[arm]}" font-family="sans-serif" font-size="14">Arm {arm}</text>')
    parts.append('</svg>')
    (out / 'learning-curves.svg').write_text('\n'.join(parts), encoding='utf-8')


def analyze(run):
    config = json.loads((ROOT / 'config.json').read_text())
    execution = json.loads((run / 'execution.json').read_text())
    assert execution['complete']
    rows = []
    bundles = []
    for suite in config['suites']:
        for setting in config['settings']:
            path = run / f"{suite['name']}-{setting['name']}.jsonl"
            records = [json.loads(line) for line in path.read_text().splitlines()]
            assert [b['seed'] for b in records] == config['seeds']
            for bundle in records:
                assert [r['arm'] for r in bundle['results']] == ARMS
                assert bundle['null_routing']['degree_preserved'] and bundle['null_routing']['source_strength_preserved']
                assert bundle['null_routing']['accepted'] > 0 and bundle['null_routing']['retained_fraction'] < 0.95
                assert all(n['degree_preserved'] and n['source_strength_preserved'] for n in bundle['null_signal'])
                for row in bundle['results']:
                    assert row['suite'] == suite['name'] and row['setting'] == setting['name']
                    assert row['seed'] == bundle['seed'] and row['side'] == suite['side']
                    o = row['outcome']
                    assert 0 <= o['accuracy'] <= 1 and o['hot_allocations'] == 0
                    assert o['unique_cue_codes'] == suite['cues'], 'encoding collapsed held-out cues'
                    assert row['arm'] != 'Z' or o['changed_weights'] == 0
                    assert o['max_gain_mass_error'] < 1e-5
                rows.extend(bundle['results'])
                bundles.append(bundle)
    assert len(rows) == execution['outcome_rows'] == len(config['suites']) * len(config['settings']) * len(config['seeds']) * 6
    means = {}
    metrics = ['accuracy', 'acquisition', 'reversal', 'late_acquisition', 'late_reversal', 'probe_acquisition', 'probe_reversal', 'seconds', 'work', 'state_bytes']
    for suite in config['suites']:
        name = suite['name']
        means[name] = {}
        for arm in ARMS:
            selected = [r['outcome'] for r in rows if r['suite'] == name and r['arm'] == arm]
            means[name][arm] = {m: float(np.mean([r[m] for r in selected])) for m in metrics}
            means[name][arm]['curve'] = np.mean([r['curve'] for r in selected], axis=0).tolist()
    effects = {s['name']: paired_effect(rows, s['name'], config) for s in config['suites']}
    primary = effects['primary']
    supported = primary['ci95'][0] > 0 and all(v > 0 for v in primary['setting_means'].values()) and effects['left_transfer']['mean'] > 0 and effects['task_transfer']['mean'] > 0
    status = 'SUPPORTED_IN_SPECIFIED_SYNTHETIC_MODEL' if supported else 'NOT_SUPPORTED_BY_PRESPECIFIED_GATE'
    motifs = {}
    for side in ['R', 'L']:
        selected = [b for b in bundles if b['results'][0]['side'] == side and b['results'][0]['setting'] == config['settings'][0]['name'] and b['results'][0]['suite'] != 'task_transfer']
        motifs[side] = {'labels': ['reciprocal MBON-DAN pairs', 'KC-MBON-DAN feedforward triangles'],
                        'anatomical': selected[0]['motifs_anatomical'],
                        'route_null_mean': np.mean([b['motifs_route_null'] for b in selected], axis=0).tolist(),
                        'interpretation': 'Anatomy-only diagnostic against coarse degree nulls; no independent animal replication.'}
    summary = {'status': status, 'effects': effects, 'arm_means': means, 'motifs': motifs,
               'outcomes': len(rows), 'total_trials': len(rows) * config['trials'],
               'execution': execution, 'hot_allocations_total': sum(r['outcome']['hot_allocations'] for r in rows),
               'total_online_edge_visits_including_probes': sum(r['outcome']['work'] for r in rows),
               'sum_arm_seconds': sum(r['outcome']['seconds'] for r in rows),
               'route_retention_range': [min(b['null_routing']['retained_fraction'] for b in bundles), max(b['null_routing']['retained_fraction'] for b in bundles)],
               'limitations': ['one specimen', 'coarse degree nulls do not preserve cell-type-pair structure', 'invented neuron dynamics, action partition, and cell-level broadcast', 'global gain normalization and top-k inhibition are modelling assumptions', 'no biological or architecture-family confirmation', 'persistent-array bytes exclude graph, cue cache, and temporary initial-weight audit copy']}
    (run / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    report = ['# DH-01 measured results', '', f'**{status}**', '',
              f"Primary A−B: **{100*primary['mean']:+.3f} percentage points**, paired seed-bundle bootstrap 95% interval **[{100*primary['ci95'][0]:+.3f}, {100*primary['ci95'][1]:+.3f}]**.", '',
              f"{len(rows):,} arm runs; {len(rows)*config['trials']:,} training trials; 24 computational seed bundles per suite; four frozen dynamics settings. One biological specimen.", '',
              '## Online accuracy', '', '| Suite | A anatomical | B route shuffle | C signal shuffle | D both | E uniform | Z no learning |', '|---|---:|---:|---:|---:|---:|---:|']
    for suite in means:
        report.append('| ' + suite + ' | ' + ' | '.join(f"{100*means[suite][a]['accuracy']:.2f}%" for a in ARMS) + ' |')
    report += ['', '## Prespecified routing comparisons', '', '| Suite | A−B (percentage points) | Descriptive 95% interval |', '|---|---:|---:|']
    for suite, e in effects.items():
        report.append(f"| {suite} | {100*e['mean']:+.3f} | [{100*e['ci95'][0]:+.3f}, {100*e['ci95'][1]:+.3f}] |")
    report += ['', 'Only the right-slice primary comparison is the primary inferential endpoint. Transfer intervals and all other contrasts are descriptive.', '',
               '### Primary sensitivity settings', '']
    report += [f'- {k}: {100*v:+.3f} percentage points.' for k, v in primary['setting_means'].items()]
    report += ['', '## Anatomical diagnostics', '', 'Motif counts were defined before outcome execution; these are not selected discoveries.', '']
    for side, m in motifs.items():
        report.append(f"- {side}: reciprocal pairs {m['anatomical'][0]} versus null mean {m['route_null_mean'][0]:.1f}; feedforward triangles {m['anatomical'][1]:,} versus {m['route_null_mean'][1]:,.1f}.")
    report += ['', '## Engineering measurements', '', f"- Execution wall time including setup and all arms: {execution['wall_seconds']:.3f} seconds; {config['threads']} workers.",
               f"- Sum of individual arm timers (concurrent; not wall time): {summary['sum_arm_seconds']:.3f} seconds.",
               f"- Hot-loop allocations across all scientific arm runs: {summary['hot_allocations_total']}.",
               f"- Online edge visits, including probes: {summary['total_online_edge_visits_including_probes']:,}; fixed feature-cache construction is outside this counter but inside execution wall time.",
               f"- Persistent mutable float-array storage per right-slice simulator: {means['primary']['A']['state_bytes']:,.0f} bytes, excluding immutable graph, cue cache, and the audit copy of initial weights.",
               f"- Shuffled routing retains {100*summary['route_retention_range'][0]:.1f}–{100*summary['route_retention_range'][1]:.1f}% of original pairs. Exact binary degrees and outgoing multiplicity sums passed for every null.",
               '', '## Interpretation limits', '']
    report += ['- ' + s + '.' for s in summary['limitations']]
    report += ['', 'The result concerns this fixed local rule and synthetic delayed-reward task. It neither establishes nor refutes biological dopamine function, general local-learning advantages, or a universal learning law.', '',
               'Source attribution: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY. https://male-cns.janelia.org/download/', '',
               'The source hashes, frozen config, executable hash and raw-output hashes are in the adjacent seal and completion receipts.']
    (run / 'REPORT.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    chart(means, run)
    print(json.dumps({'status': status, 'primary': primary, 'outcomes': len(rows)}, indent=2))


if __name__ == '__main__':
    analyze(pathlib.Path(sys.argv[1]))
