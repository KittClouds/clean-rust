import hashlib
import unittest

from extract_e1_neighborhood_denylist_v03 import (
    canonical_denylist_bytes,
    expected_open_set_matches,
    extract_top_level_string_field,
    sha256_bytes,
)


class SyntheticOnlyTests(unittest.TestCase):
    def test_field_extractor_skips_non_identity_values(self):
        fixture = b'{"target":{"sensitive":[1,2,{"x":"y,}\\\""}]},"neighborhood_id":"n-1"}'
        self.assertEqual(extract_top_level_string_field(fixture, "neighborhood_id"), "n-1")
        with self.assertRaisesRegex(ValueError, "duplicate top-level"):
            extract_top_level_string_field(
                b'{"neighborhood_id":"n-1","neighborhood_id":"n-2"}',
                "neighborhood_id",
            )
        with self.assertRaisesRegex(ValueError, "lacks top-level"):
            extract_top_level_string_field(b'{"other":"n-1"}', "neighborhood_id")

    def test_open_set_requires_exact_membership_and_count(self):
        expected = {"a", "b", "c"}
        self.assertTrue(expected_open_set_matches(["a", "b", "c"], expected))
        self.assertFalse(expected_open_set_matches(["a", "b", "x"], expected))
        self.assertFalse(expected_open_set_matches(["a", "b", "c", "c"], expected))

    def test_denylist_serialization_is_deterministic_and_hashes_only(self):
        ids = [hashlib.sha256(b"n-2").hexdigest(), hashlib.sha256(b"n-1").hexdigest()]
        sources = [{"observed_sha256": "b"}, {"observed_sha256": "a"}]
        first = canonical_denylist_bytes(ids, sources, "extractor")
        second = canonical_denylist_bytes(list(reversed(ids)), list(reversed(sources)), "extractor")
        self.assertEqual(first, second)
        self.assertNotIn(b"n-1", first)
        self.assertEqual(sha256_bytes(first), hashlib.sha256(first).hexdigest())


if __name__ == "__main__":
    unittest.main()
