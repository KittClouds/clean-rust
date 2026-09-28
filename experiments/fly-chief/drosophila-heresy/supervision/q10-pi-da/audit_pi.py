"""Independent replay of PI fixtures/maps; accepts paths, writes no experiment data."""
import argparse
import json
import math
import struct
from pathlib import Path

from oracle import bits, from_bits, metrics, readout, sequential, supports


def close(a, b):
    assert math.isclose(a, b, rel_tol=2e-12, abs_tol=1e-24), (a, b)


def changed(rows, baseline, actual):
    return {r: v for r, v in zip(rows, actual) if baseline[r] != v}


def decode_changes(records):
    result = {r['row']: r['readout_bits'] for r in records}
    assert len(result) == len(records)
    return result


def audit(fixture, mapping):
    events = {e['event_key']: e for e in fixture['events']}
    assert len(events) == len(fixture['events'])
    count = positive = disjoint = 0
    per_event = []
    for event in mapping['events']:
        f = events[event['event_key']]
        rows = f['row_coordinate_ids']
        initial = f['initial_committed_bits']
        base = readout(rows, initial)
        assert base == f['baseline_readout_bits']
        weights = list(map(from_bits, initial))
        incidence = supports(rows, len(initial))
        norm = math.sqrt(math.fsum(from_bits(b)**2 for b in base))
        close(norm, f['baseline_readout_l2'])
        seen = set()
        event_positive = 0
        for pair in event['pairs']:
            a, b = pair['coordinate_a'], pair['coordinate_b']
            assert a != b and tuple(sorted((a, b))) not in seen
            seen.add(tuple(sorted((a, b))))
            union = sorted(incidence[a] | incidence[b])
            shared = incidence[a] & incidence[b]
            assert len(shared) == pair['shared_row_count']
            assert len(union) == pair['union_row_count']
            assert (pair['category'] == 'shared') == bool(shared)
            assert [r['row'] for r in pair['support']] == union
            for p, r in enumerate(pair['support']):
                assert r['union_position'] == p
                assert r['positions_a'] == [i for i,c in enumerate(rows[r['row']]) if c == a]
                assert r['positions_b'] == [i for i,c in enumerate(rows[r['row']]) if c == b]
            singles = []
            for coord, key in ((a, 'single_a'), (b, 'single_b')):
                bank = {}
                for endpoint in pair[key]:
                    step = endpoint['signed_step']
                    replacement = endpoint['replacement_bits']
                    # Scientific repair coordinates are strictly positive interior weights.
                    assert replacement == initial[coord] + step
                    old = weights[coord]
                    weights[coord] = from_bits(replacement)
                    values = [bits(sequential(rows[r], weights)) for r in union]
                    weights[coord] = old
                    assert changed(union, base, values) == decode_changes(endpoint['changed_readout'])
                    bank[step] = values
                assert set(bank) == {-16,-8,-4,-2,-1,1,2,4,8,16}
                singles.append(bank)
            seen_steps = set()
            pair_positive = False
            for candidate in pair['candidates']:
                sa, sb = candidate['signed_steps']
                assert (sa,sb) not in seen_steps
                seen_steps.add((sa,sb))
                wa, wb = candidate['replacement_bits']
                assert wa == initial[a] + sa and wb == initial[b] + sb
                old_a, old_b = weights[a], weights[b]
                weights[a], weights[b] = from_bits(wa), from_bits(wb)
                joint = [bits(sequential(rows[r], weights)) for r in union]
                weights[a], weights[b] = old_a, old_b
                assert changed(union, base, joint) == decode_changes(candidate['joint_changed_readout'])
                interaction = [from_bits(j)-from_bits(x)-from_bits(y)+from_bits(base[r])
                               for r,j,x,y in zip(union,joint,singles[0][sa],singles[1][sb])]
                reported = {r['row']: struct.unpack('<d',struct.pack('<Q',r['value_bits']))[0]
                            for r in candidate['interaction_sparse']}
                actual = {r:v for r,v in zip(union,interaction) if v != 0}
                assert {r:v for r,v in reported.items() if v != 0} == actual
                assert set(actual) <= shared
                length = math.sqrt(math.fsum(x*x for x in interaction))
                close(length, candidate['interaction_norm'])
                close(length/max(norm,mapping['normalization_floor']),candidate['interaction_norm_normalized'])
                count += 1
                positive += bool(actual)
                pair_positive |= bool(actual)
                if not shared:
                    assert not actual
                    disjoint += 1
            assert len(seen_steps) == 100
            event_positive += pair_positive
        per_event.append({'event':event['event_key'],'pairs':len(seen),'positive_pairs':event_positive})
    return {'replayed_candidates':count,'positive_candidates':positive,
            'exact_disjoint_candidates':disjoint,'events':per_event}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('fixture',type=Path)
    parser.add_argument('mapping',type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(json.loads(args.fixture.read_text()),
                           json.loads(args.mapping.read_text())),indent=2))
