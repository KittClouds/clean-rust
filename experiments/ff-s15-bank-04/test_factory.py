"""Adversarial qualification: reject corrupt targets, never rubber-stamp gates."""
import copy
import unittest
from common import LANES
import domains
import engine
import teacher
import audit
import loader


def fixture(lane='planning'):
    w = domains.generate(lane, 'TRAIN', 0)
    f = teacher.family(w, 'TRAIN', 0)
    roots = []
    for s in f['states']:
        for partial in (False, True):
            frame, target = teacher.project(w, f, s, partial)
            target['_construction_state'] = list(s)
            roots.append((frame, target))
    return w, f, roots


class Qualification(unittest.TestCase):
    def test_all_lanes_and_two_lossless_surfaces(self):
        for lane in LANES:
            with self.subTest(lane=lane):
                w, f, roots = fixture(lane)
                audit.audit_family(w, f, roots)
                for frame, _ in roots:
                    for style in (0, 1):
                        self.assertEqual(teacher.parse(teacher.render(frame, style), style), frame)

    def test_mutant_targets_are_rejected(self):
        w, f, roots = fixture()
        mutations = [
            lambda t: t['grounding'][0].update(legality='CORRUPT'),
            lambda t: t['grounding'][0].update(permission='CORRUPT'),
            lambda t: t['decision'].update(mode='CORRUPT'),
            lambda t: t['canonical_consequences'][0].update(distance=999),
            lambda t: t['canonical_consequences'][0].update(actual_effects=[[0, 999]]),
            lambda t: t['canonical_consequences'][0].update(policy_cost_to_goal=999),
            lambda t: t['canonical_consequences'][0].update(next_state=[999]*6),
            lambda t: t.update(canonical_optimal_actions=['CORRUPT']),
            lambda t: t['grounded_observation'][0].update(value=999)]
        for mutate in mutations:
            altered = copy.deepcopy(roots)
            mutate(altered[0][1])
            with self.assertRaises(AssertionError):
                audit.audit_family(w, f, altered)

    def test_mask_mutant_rejected(self):
        w, f, roots = fixture()
        roots[1][1]['supervision_masks']['canonical_consequences'] = True
        with self.assertRaises(AssertionError):
            audit.audit_family(w, f, roots)

    def test_permission_is_not_legality(self):
        w = domains.generate('policy_tools', 'TRAIN', 0)
        a = next(a for a in w['actions'] if a['type'] == 'REFUND')
        s = (1, 1, 0, 0, 0)
        self.assertTrue(engine.legal(w, s, a))
        self.assertFalse(engine.permitted(s, a))

    def test_wait_is_legal_but_not_automatically_optimal(self):
        w = domains.generate('graph', 'TRAIN', 0)
        states, edges = engine.catalogue(w, [w['initial']])
        ds = engine.distances(w, states, edges, 'policy')
        nong = next(s for s in states if not engine.goal(w, s))
        offered = list(range(len(w['actions'])))
        wait = next(a for a in w['actions'] if a['type'] == 'WAIT')
        self.assertIsNotNone(engine.step(w, nong, wait))
        self.assertNotIn(wait['id'], teacher.best(w, nong, offered, ds)[0])

    def test_timed_wait_actual_vs_operator(self):
        w = domains.generate('household', 'TRAIN', 0)
        wait = next(a for a in w['actions'] if a['type'] == 'WAIT')
        state = (0, 1, 0, 0, 0, 1, 1)
        result = engine.step(w, state, wait)
        self.assertEqual(wait['effects'], [])
        self.assertEqual(result[3], 1)
        self.assertEqual(result[5], 2)

    def test_impossible_not_distance_zero(self):
        w = domains.generate('policy_tools', 'TRAIN', 0)
        w['initial'][1] = 0
        states, edges = engine.catalogue(w, [w['initial']])
        ds = engine.distances(w, states, edges, 'steps')
        self.assertNotIn(tuple(w['initial']), ds)

    def test_bad_api_argument_types(self):
        w = domains.generate('api_binding', 'TRAIN', 0)
        bad = [a for a in w['actions'] if a['binding'] is not None and not engine.binding_valid(w, a)]
        self.assertEqual(len(bad), 4)
        self.assertTrue(all(engine.step(w, (1, 0, 1, 0), a) is None for a in bad))

    def test_candidate_order_equivariance(self):
        w, f, roots = fixture()
        state = f['states'][0]
        self.assertEqual(teacher.best(w, state, f['offered'], f['distances']['policy']),
                         teacher.best(w, state, list(reversed(f['offered'])), f['distances']['policy']))

    def test_loader_masks_partial_canonical_truth(self):
        import tempfile
        from pathlib import Path
        from common import encode
        from build import pair_comparisons
        w, f, roots = fixture()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)/'corpus'/'TRAIN'/'planning'
            folder.mkdir(parents=True)
            with (folder/'inputs.jsonl').open('wb') as inf, (folder/'targets.jsonl').open('wb') as tf:
                for j, (frame, target) in enumerate(roots):
                    target.pop('_construction_state')
                    target['root_id'] = str(j)
                    target['pairwise_consequence_coordinates'] = pair_comparisons(target['canonical_consequences'])
                    target['supervision_masks']['pairwise_consequence_coordinates'] = j % 2 == 0
                    tf.write(encode(target)+b'\n')
                    for style in (0, 1):
                        inf.write(encode({'root_id': str(j), 'view': style, 'input_text': teacher.render(frame, style)})+b'\n')
            records = list(loader.load(temp, 'TRAIN', 'planning', 'integrated'))
            for i, (_, labels) in enumerate(records):
                self.assertEqual('canonical_consequences' in labels, i//2 % 2 == 0)
                self.assertEqual('pairwise_consequence_coordinates' in labels, i//2 % 2 == 0)
            self.assertEqual(len(list(loader.load(temp, 'TRAIN', 'planning', 'gold_grounding_to_consequence'))), 4)

    def test_archetype_mutants_rejected(self):
        from archetype_checks import qualify
        w = domains.generate('sokoban', 'TRAIN', 0)
        operation = next(a for a in w['actions'] if a['type'] == 'MOVE')
        operation['effects'][0][1] = operation['preconditions'][0][2]
        with self.assertRaises(AssertionError):
            qualify(w)
        w = domains.generate('sudoku', 'TRAIN', 0)
        operation = next(a for a in w['actions'] if a['type'] == 'FILL')
        operation['preconditions'].pop()
        with self.assertRaises(AssertionError):
            qualify(w)


if __name__ == '__main__':
    unittest.main()
