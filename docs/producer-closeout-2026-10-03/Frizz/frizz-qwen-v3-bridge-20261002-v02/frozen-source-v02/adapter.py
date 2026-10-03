"""BANK-v3 observable projection and ID-aligned supervision, never latent inputs."""
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

from audit_release import ROOT, sha

VOCAB = ('MOVE', 'TAKE', 'DROP', 'ACTIVATE', 'DEACTIVATE', 'OPEN', 'CLOSE', 'WAIT', 'TRANSFER')
OBSERVABLE = ('input_text', 'goal_mentions', 'bindings', 'actions', 'requests')


def model_inputs(public):
    """Explicit allowlist: join metadata and supervision cannot enter this view."""
    return {key: public[key] for key in OBSERVABLE}


def aligned_targets(public, labelled):
    if public['world_id'] != labelled['world_id'] or public['split'] != labelled['split']:
        raise ValueError('row join mismatch')
    abi = labelled['SUPERVISION_ABI']
    ids = [a['id'] for a in public['actions']]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise ValueError('noncanonical or duplicate candidate ids')
    if any(a['type'] not in VOCAB for a in public['actions']):
        raise ValueError('unknown action type, no fallback permitted')
    if abi['candidate_order'] != ids or [a['id'] for a in abi['candidates']] != ids:
        raise ValueError('candidate supervision order mismatch')
    selected = abi['selected_action_id']
    index = abi['selected_action_index']
    core = abi['core_targets']
    executable = core['disposition'] == 'EXECUTE'
    eligible = executable and abi['selected_action_eligible']
    if eligible:
        if not isinstance(index, int) or not 0 <= index < len(ids) or ids[index] != selected:
            raise ValueError('selected ID/index mismatch')
        if public['actions'][index]['type'] != core['first_action_type']:
            raise ValueError('selected type mismatch')
    opt = set(abi['optimal_action_ids'])
    if not opt.issubset(ids):
        raise ValueError('optimal id absent from candidates')
    permitted = {a['id'] for a in abi['candidates'] if a['candidate_permitted']}
    if not opt.issubset(permitted):
        raise ValueError('optimal action not permitted')
    return {
        'candidate_legal': [a['candidate_legal'] for a in abi['candidates']],
        'candidate_satisfies_goal': [a['candidate_satisfies_goal'] for a in abi['candidates']],
        'core': core, 'global': abi['global_targets'],
        'action_index': index if eligible else -1,
        'action_eligible': eligible,
        'optimal': [i in opt for i in ids],
        'optimal_eligible': executable and abi['optimal_set_eligible'] and bool(opt),
        # Separate diagnostic metadata; never part of model_inputs.
        'axes': labelled['CAPABILITY_AXES'],
    }


def rows(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)


def audit_adapter(binding):
    result = {'status': 'ADAPTER_TRAIN_DEV_AUDIT_PASS',
              'binding_receipt_sha256': sha(binding), 'evaluation_files_opened': 0,
              'model_inputs': list(OBSERVABLE), 'conflict_training_weight': 0, 'splits': {}}
    lock = json.loads(binding.read_text())
    for split in ('TRAIN', 'DEV'):
        counts, per_root, type_support = Counter(), defaultdict(list), Counter()
        public_files = lock['splits'][split]['public']['files']
        data_files = lock['splits'][split]['data']['files']
        for name, expected in public_files.items():
            data_name = name.replace('public/', 'data/', 1)
            if data_name not in data_files:
                raise ValueError('unpaired shard')
            if sha(ROOT / name) != expected or sha(ROOT / data_name) != data_files[data_name]:
                raise ValueError('changed source shard')
            label_iter = iter(rows(ROOT / data_name))
            for public in rows(ROOT / name):
                labelled = next(label_iter)
                inputs = model_inputs(public)
                targets = aligned_targets(public, labelled)
                m = len(inputs['actions'])
                counts['rows'] += 1
                counts['max_candidates'] = max(counts['max_candidates'], m)
                counts['candidate_slots'] += m
                counts['selected_eligible_rows'] += targets['action_eligible']
                counts['optimal_eligible_rows'] += targets['optimal_eligible']
                counts['empty_optimal_rows'] += not any(targets['optimal'])
                per_root[public['canonical_id']].append((public['renderer_id'], targets))
            if next(label_iter, None) is not None:
                raise ValueError('extra labelled rows')
        for rendered in per_root.values():
            if len(rendered) != 2 or rendered[0][0] == rendered[1][0]:
                raise ValueError('renderer pair identity mismatch')
            if rendered[0][1] != rendered[1][1]:
                raise ValueError('paired semantic targets differ')
            target = rendered[0][1]
            if target['action_eligible']:
                type_support[target['core']['first_action_type']] += 1
        result['splits'][split] = {**counts, 'roots': len(per_root),
                                   'eligible_action_type_root_support': dict(type_support)}
    return result


if __name__ == '__main__':
    binding = Path(__file__).with_name('release-binding-v01.json')
    result = audit_adapter(binding)
    with binding.with_name('adapter-audit-v01.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result, indent=2))
