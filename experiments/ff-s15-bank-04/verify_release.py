"""Fresh-process replay from serialized corpus, not the builder's terminal claims."""
import argparse
import collections
import json
import pathlib
from common import digest, encode, read, write, sha, LANES, BUDGET, NAMESPACE
import engine
import teacher
import audit
from build import pair_comparisons


def lines(path):
    with path.open('rb') as handle:
        for line in handle:
            record = json.loads(line)
            audit.check(encode(record)+b'\n' == line, 'CANONICAL_FILE_RECORD')
            yield record


def verify(root, output):
    root = pathlib.Path(root)
    counts = collections.Counter()
    family_splits = {}
    for split in BUDGET:
        for lane in LANES:
            folder = root/'corpus'/split/lane
            inputs = iter(lines(folder/'inputs.jsonl'))
            targets = iter(lines(folder/'targets.jsonl'))
            metadata = iter(lines(folder/'metadata.jsonl'))
            lane_families = 0
            for construction in lines(folder/'construction.jsonl'):
                family_id = construction['family_id']
                audit.check(family_id == digest([NAMESPACE, split, lane, lane_families]), 'PROSPECTIVE_FAMILY_IDENTITY')
                lane_families += 1
                audit.check(family_id not in family_splits, 'GROUP_ID_DISJOINTNESS')
                family_splits[family_id] = split
                w = construction['world']
                states = construction['sibling_states']
                hidden = construction['hidden_slot']
                starts = engine.completions(w, states[0], hidden)+engine.completions(w, states[1], hidden)
                space, edges = engine.catalogue(w, starts)
                fam = {'states': states, 'hidden': hidden, 'offered': construction['offered_indices'],
                       'edges': edges, 'distances': {mode: engine.distances(w, space, edges, mode)
                                                  for mode in ('steps', 'environment', 'policy')}}
                roots = []
                for j in range(4):
                    target = next(targets)
                    meta = next(metadata)
                    audit.check(target['root_id'] == meta['root_id'], 'META_JOIN')
                    audit.check(target['root_id'] == digest([family_id, j]), 'ROOT_IDENTITY')
                    audit.check(meta['family_id'] == family_id and meta['split'] == split and meta['lane'] == lane, 'PROVENANCE_JOIN')
                    frames = []
                    for style in (0, 1):
                        row = next(inputs)
                        audit.check(row['root_id'] == target['root_id'] and row['view'] == style, 'INPUT_JOIN')
                        frames.append(teacher.parse(row['input_text'], style))
                    audit.check(frames[0] == frames[1], 'SURFACE_INFORMATION_EQUIVALENCE')
                    expected = {k: v for k, v in w.items() if k != 'initial'}
                    expected['observation'] = {str(i): v for i, v in enumerate(states[j//2]) if j % 2 == 0 or i != hidden}
                    expected['complete_slots'] = sorted(expected['observation'], key=int)
                    expected['offered_actions'] = [w['actions'][i]['id'] for i in fam['offered']]
                    audit.check(frames[0] == expected, 'PUBLIC_FRAME_EXACT_PROJECTION')
                    audit.check(target['pairwise_consequence_coordinates'] == pair_comparisons(target['canonical_consequences']), 'PAIRWISE_COORDINATES')
                    audit.check(target['supervision_masks']['pairwise_consequence_coordinates'] == (j % 2 == 0), 'PAIRWISE_MASK')
                    target['_construction_state'] = states[j//2]
                    roots.append((frames[0], target))
                    counts['roots'] += 1
                    counts['renderings'] += 2
                receipt = audit.audit_family(w, fam, roots)
                audit.check(receipt == construction['semantic_receipt'], 'REPLAY_RECEIPT_MATCH')
                counts['families'] += 1
                counts['independent_transitions'] += receipt['transitions']
            audit.check(next(targets, None) is None and next(inputs, None) is None and next(metadata, None) is None, 'NO_EXTRA_ROWS')
            audit.check(lane_families == read(root/'BUILD.json')['requested_families_per_lane'][split], 'CELL_COUNT')
            print('REPLAY', split, lane, flush=True)
    manifest = {str(p.relative_to(root)).replace('\\', '/'): {'sha256': sha(p), 'bytes': p.stat().st_size}
                for p in sorted((root/'corpus').rglob('*.jsonl'))}
    expected_counts = read(root/'BUILD.json')['counts']
    audit.check(all(counts[k] == expected_counts[k] for k in ('families', 'roots', 'renderings')), 'RELEASE_COUNTS')
    write(output, {'status': 'PASS', 'counts': dict(counts), 'corpus_manifest': manifest,
                   'corpus_root': digest(manifest), 'protected_external_truth_opened': False,
                   'own_transfer_truth_access': 'INDEPENDENT_CONSTRUCTION_REPLAY'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    verify(args.root, args.output)
