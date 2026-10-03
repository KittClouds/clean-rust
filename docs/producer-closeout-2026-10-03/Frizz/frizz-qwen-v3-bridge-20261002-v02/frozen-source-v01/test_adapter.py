import copy
import unittest
from adapter import aligned_targets, model_inputs, OBSERVABLE


def fixture():
    p = {'world_id': 'w', 'split': 'TRAIN', 'input_text': 'observable',
         'goal_mentions': [], 'bindings': [], 'requests': [],
         'actions': [{'id': 'a1', 'type': 'MOVE'}], 'WORLD_TRUTH': 'poison'}
    d = {'world_id': 'w', 'split': 'TRAIN', 'CAPABILITY_AXES': {},
         'SUPERVISION_ABI': {'candidate_order': ['a1'],
           'candidates': [{'id': 'a1', 'candidate_legal': True,
                          'candidate_permitted': True, 'candidate_satisfies_goal': True}],
           'selected_action_id': 'a1', 'selected_action_index': 0,
           'selected_action_eligible': True, 'optimal_set_eligible': True,
           'optimal_action_ids': ['a1'], 'global_targets': {},
           'core_targets': {'disposition': 'EXECUTE', 'first_action_type': 'MOVE'}}}
    return p, d


class AdapterTests(unittest.TestCase):
    def test_allowlist(self):
        p, _ = fixture()
        self.assertEqual(set(model_inputs(p)), set(OBSERVABLE))
        self.assertNotIn('WORLD_TRUTH', model_inputs(p))

    def test_id_index_mismatch(self):
        p, d = fixture()
        d['SUPERVISION_ABI']['selected_action_index'] = 1
        with self.assertRaises(ValueError):
            aligned_targets(p, d)

    def test_empty_optimal_not_success(self):
        p, d = fixture()
        d['SUPERVISION_ABI']['optimal_action_ids'] = []
        self.assertFalse(aligned_targets(p, d)['optimal_eligible'])

    def test_no_action_coercion(self):
        p, d = fixture()
        d['SUPERVISION_ABI']['selected_action_eligible'] = False
        d['SUPERVISION_ABI']['selected_action_id'] = 'outside'
        self.assertEqual(aligned_targets(p, d)['action_index'], -1)

    def test_unknown_type_rejected(self):
        p, d = fixture()
        p['actions'][0]['type'] = 'UNKNOWN'
        with self.assertRaises(ValueError):
            aligned_targets(p, d)


if __name__ == '__main__':
    unittest.main()
