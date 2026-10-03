import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "extract_e1_neighborhood_denylist.py"
SPEC = importlib.util.spec_from_file_location("denylist_extractor", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IdentityOnlyParserTests(unittest.TestCase):
    def test_extracts_only_neighborhood_id_and_skips_nested_payload(self):
        record = (
            b'{"family_id":"ignored","payload":{"target":[0.1,0.9],'
            b'"text":"quoted \\\"neighborhood_id\\\" decoy"},'
            b'"neighborhood_id":"family-a-world-0042","target_hash":"ignored"}'
        )
        self.assertEqual(
            MODULE.extract_neighborhood_id_only(record), "family-a-world-0042"
        )

    def test_rejects_missing_or_duplicate_identity_field(self):
        with self.assertRaises(RuntimeError):
            MODULE.extract_neighborhood_id_only(b'{"target_hash":"x"}')
        with self.assertRaises(RuntimeError):
            MODULE.extract_neighborhood_id_only(
                b'{"neighborhood_id":"a","neighborhood_id":"b"}'
            )

    def test_hash_is_domain_separated(self):
        value = "family-a-world-0042"
        self.assertNotEqual(
            MODULE.canonical_identity_hash(value, b"domain-a\0"),
            MODULE.canonical_identity_hash(value, b"domain-b\0"),
        )


if __name__ == "__main__":
    unittest.main()
