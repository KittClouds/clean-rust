import unittest

from action_semantic_adapter import satisfied, sign_class


class SatisfactionRules(unittest.TestCase):
    def test_same(self):
        self.assertEqual(satisfied("same", [0, 1], [], [2, 2]), 1.0)
        self.assertEqual(satisfied("same", [0, 1], [], [2, 1]), 0.0)

    def test_different(self):
        self.assertEqual(satisfied("different", [0, 1], [], [2, 1]), 1.0)
        self.assertEqual(satisfied("different", [0, 1], [], [2, 2]), 0.0)

    def test_fixed_and_forbidden_role(self):
        self.assertEqual(satisfied("fixed_role", [0], [1], [1]), 1.0)
        self.assertEqual(satisfied("fixed_role", [0], [1], [0]), 0.0)
        self.assertEqual(satisfied("forbidden_role", [0], [1], [0]), 1.0)
        self.assertEqual(satisfied("forbidden_role", [0], [1], [1]), 0.0)

    def test_exactly_one_role(self):
        self.assertEqual(satisfied("exactly_one_role", [0, 1, 2], [1], [1, 0, 1]), 0.0)
        self.assertEqual(satisfied("exactly_one_role", [0, 1, 2], [1], [1, 0, 0]), 1.0)

    def test_implies_not_role_averages_unknown_pairing(self):
        # One pairing is violated while the other is satisfied.
        self.assertEqual(satisfied("implies_not_role", [0, 1], [0, 1], [0, 1]), 0.5)

    def test_same_entity_distinct_role_implication_is_tautology(self):
        self.assertEqual(satisfied("implies_not_role", [0], [0, 1], [0]), 1.0)
        self.assertEqual(satisfied("implies_not_role", [0], [0, 1], [1]), 1.0)

    def test_malformed_shapes_are_neutral(self):
        self.assertEqual(satisfied("same", [0], [], [1]), 0.0)
        self.assertEqual(satisfied("fixed_role", [0], [], [1]), 0.0)
        self.assertEqual(satisfied("implies_not_role", [0, 1], [0], [0, 0]), 0.0)

    def test_sign(self):
        self.assertEqual(sign_class(-0.4), -1)
        self.assertEqual(sign_class(0.0), 0)
        self.assertEqual(sign_class(0.3), 1)
        self.assertEqual(sign_class(1.0e-10), 0)


if __name__ == "__main__":
    unittest.main()
