"""Deterministic streaming bank builder. Every family receives independent replay."""
import argparse
import collections
import time
from contextlib import ExitStack
from common import *
import domains
import teacher
import audit


def pair_comparisons(consequences):
    rows = []
    for i, a in enumerate(consequences):
        for b in consequences[i+1:]:
            values = {}
            for field in ('legal', 'permitted', 'goal_delta', 'next_distance', 'policy_cost_to_goal'):
                x, y = a[field], b[field]
                values[field] = 'UNDEFINED' if x is None or y is None else 'EQUAL' if x == y else 'LEFT_GREATER' if x > y else 'RIGHT_GREATER'
            rows.append({'left': a['candidate_id'], 'right': b['candidate_id'], 'coordinates': values})
    return rows


def structural(w, fam):
    # A disclosed narrow signature, not a claim of complete graph-isomorphism detection.
    return digest({'lane': w['lane'], 'domains': w['domains'], 'goal': w['goal'],
                   'actions': sorted(w['actions'], key=lambda a: a['id']),
                   'states': [list(s) for s in fam['states']], 'hidden': fam['hidden'],
                   'offered': sorted(w['actions'][i]['id'] for i in fam['offered'])})


def build(root, budgets):
    root = pathlib.Path(root)
    stats = collections.Counter()
    distributions = collections.Counter()
    signatures = collections.defaultdict(collections.Counter)
    input_hashes = collections.defaultdict(collections.Counter)
    failures = []
    start = time.monotonic()
    for split, count in budgets.items():
        for lane in LANES:
            directory = root/'corpus'/split/lane
            directory.mkdir(parents=True, exist_ok=True)
            with ExitStack() as stack:
                handles = {name: stack.enter_context((directory/(name+'.jsonl')).open('xb'))
                           for name in ('inputs', 'targets', 'metadata', 'construction')}
                def emit(name, obj):
                    handles[name].write(encode(obj)+b'\n')
                for index in range(count):
                    # Failure remains explicit: no automatic replacement or seed search.
                    family_id = digest([NAMESPACE, split, lane, index])
                    try:
                        w = domains.generate(lane, split, index)
                        fam = teacher.family(w, split, index)
                        roots = []
                        for state in fam['states']:
                            for partial in (False, True):
                                frame, target = teacher.project(w, fam, state, partial)
                                target['_construction_state'] = list(state)
                                roots.append((frame, target))
                        receipt = audit.audit_family(w, fam, roots)
                    except (AssertionError, ValueError) as exc:
                        failures.append({'family': family_id, 'split': split, 'lane': lane,
                                         'index': index, 'reason': str(exc)})
                        continue
                    signature = structural(w, fam)
                    signatures[signature][split] += 1
                    emit('construction', {'family_id': family_id, 'world': w,
                                           'sibling_states': [list(s) for s in fam['states']],
                                           'hidden_slot': fam['hidden'], 'offered_indices': fam['offered'],
                                           'semantic_receipt': receipt})
                    for j, (frame, target) in enumerate(roots):
                        root_id = digest([family_id, j])
                        target.pop('_construction_state')
                        target['pairwise_consequence_coordinates'] = pair_comparisons(target['canonical_consequences'])
                        target['supervision_masks']['pairwise_consequence_coordinates'] = j % 2 == 0
                        emit('targets', {'root_id': root_id, **target})
                        for style in (0, 1):
                            text = teacher.render(frame, style)
                            audit.check(teacher.parse(text, style) == frame, 'LOSSLESS_RENDERING')
                            emit('inputs', {'root_id': root_id, 'view': style, 'input_text': text})
                            input_hashes[digest([style, text])][split] += 1
                            stats['renderings'] += 1
                        by_id = {a['id']: a for a in w['actions']}
                        offered_types = [by_id[k]['type'] for k in frame['offered_actions']]
                        same_type = sum(offered_types[i] == offered_types[k]
                                        for i in range(len(offered_types)) for k in range(i))
                        metadata = {'root_id': root_id, 'family_id': family_id, 'lane': lane,
                                    'split': split, 'generator_index': index, 'sibling': j//2,
                                    'observation': 'partial' if j % 2 else 'full',
                                    'producer_order': frame['offered_actions'], 'structural_signature': signature,
                                    'strata': {'slots': len(w['slots']), 'candidate_count': len(fam['offered']),
                                               'same_type_pairs': same_type, 'reachable_states': fam['reachable_count'],
                                               'max_clause_arity': max(map(lambda a: len(a['preconditions']), w['actions'])),
                                               'domain_variant': 'larger_or_stricter' if split == 'TRANSFER' else 'base'},
                                    'provenance': {'source': lane, 'method': 'fresh_deterministic_archetype',
                                                   'seed': digest(['world', lane, split, index]),
                                                   'public_rows_used': 0, 'generator_model': None}}
                        emit('metadata', metadata)
                        distributions[(split, lane, 'mode', target['decision']['mode'])] += 1
                        distributions[(split, lane, 'valid_count', len(target['canonical_optimal_actions']))] += 1
                        distributions[(split, lane, 'same_type_pairs', same_type)] += 1
                        stats['roots'] += 1
                    for key, value in receipt.items():
                        stats['audit_'+key] += value
                    stats['families'] += 1
                print(split, lane, count, 'elapsed', round(time.monotonic()-start, 1), flush=True)
    def overlap(table):
        return {'distinct_signatures': len(table),
                'within_split_repeated_occurrences': sum(max(0, count-1) for row in table.values() for count in row.values()),
                'cross_split_signatures': sum(len(row) > 1 for row in table.values()),
                'cross_split_pairs': dict(collections.Counter(pair for row in table.values()
                    for i, s in enumerate(sorted(row)) for pair in ((s, t) for t in sorted(row)[i+1:])))}
    # JSON object keys must be strings.
    overlaps = {}
    for name, table in [('structural', signatures), ('input', input_hashes)]:
        value = overlap(table)
        value['cross_split_pairs'] = {'|'.join(k): v for k, v in value['cross_split_pairs'].items()}
        overlaps[name] = value
    write(root/'BUILD.json', {'namespace': NAMESPACE, 'requested_families_per_lane': budgets,
                             'counts': dict(stats), 'failures': failures,
                             'distributions': [{'split': k[0], 'lane': k[1], 'coordinate': k[2], 'value': k[3], 'count': v}
                                               for k, v in sorted(distributions.items(), key=lambda item: str(item[0]))],
                             'overlap': overlaps, 'observer_model_contact': False,
                             'transfer_truth_access': 'CONSTRUCTION_AND_FULL_SEMANTIC_AUDIT',
                             'source_identity': digest({p.name: sha(p) for p in SOURCE.glob('*.py')})})
    if failures:
        raise RuntimeError(f'{len(failures)} construction failures; release refused')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(OUT))
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    build(args.out, {s: 2 for s in BUDGET} if args.smoke else BUDGET)
