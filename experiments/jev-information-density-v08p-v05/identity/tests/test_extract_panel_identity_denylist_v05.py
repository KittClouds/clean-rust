import hashlib
import json
import unittest

from extract_panel_identity_denylist_v05 import (
    canonical_identity,
    extract_identity_hashes,
    extract_top_level_string,
)


class SyntheticOnlyTests(unittest.TestCase):
    def test_top_level_field_only_and_nested_payload_is_opaque(self):
        row = b'{"target":{"nested":[1,{"text":"comma, brace } and quote \\\""}]},"neighborhood_id":"n-1"}'
        self.assertEqual(extract_top_level_string(row, "neighborhood_id"), "n-1")

    def test_duplicate_or_missing_identity_field_fails(self):
        with self.assertRaisesRegex(ValueError, "duplicate neighborhood_id"):
            extract_top_level_string(b'{"neighborhood_id":"a","neighborhood_id":"b"}', "neighborhood_id")
        with self.assertRaisesRegex(ValueError, "missing top-level"):
            extract_top_level_string(b'{"other":"a"}', "neighborhood_id")

    def test_canonical_identity_rejects_untrimmed_and_non_nfc(self):
        self.assertEqual(canonical_identity("n-1"), "n-1")
        with self.assertRaisesRegex(ValueError, "whitespace"):
            canonical_identity(" n-1")
        with self.assertRaisesRegex(ValueError, "NFC"):
            canonical_identity("e\u0301")

    def test_exact_count_and_sorted_hashes(self):
        rows = b"".join(
            (json.dumps({"unread_target": {"index": i}, "neighborhood_id": f"n-{i}"}, separators=(",", ":")) + "\n").encode()
            for i in range(2000)
        )
        hashes = extract_identity_hashes(rows)
        expected = sorted(hashlib.sha256(f"n-{i}".encode()).hexdigest() for i in range(2000))
        self.assertEqual(hashes, expected)
        with self.assertRaisesRegex(ValueError, "exactly 2000"):
            extract_identity_hashes(b'{"neighborhood_id":"only-one"}\n')


if __name__ == "__main__":
    unittest.main()
