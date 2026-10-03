import importlib.util
import hashlib
import json
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "extract_e1_neighborhood_denylist_v02.py"
SPEC = importlib.util.spec_from_file_location("denylist_extractor_v02", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONTRACT = Path(__file__).resolve().parents[1] / "e1-identity-denylist-extraction-contract-v03.json"


class IdentityOnlyParserV02Tests(unittest.TestCase):
    def test_extracts_neighborhood_and_skips_target_payload_as_bytes(self):
        raw = (
            b'{"neighborhood_id":"world-17","target_hash":"x",'
            b'"unrelated":{"target":[0.25,0.75],"text":"\\\"neighborhood_id\\\""}}'
        )
        self.assertEqual(MODULE.neighborhood_id_only(raw), "world-17")

    def test_rejects_duplicate_or_missing_identity(self):
        with self.assertRaises(RuntimeError):
            MODULE.neighborhood_id_only(b'{"neighborhood_id":"a","neighborhood_id":"b"}')
        with self.assertRaises(RuntimeError):
            MODULE.neighborhood_id_only(b'{"target_hash":"x"}')

    def test_frozen_v03_contract_matches_extractor_requirements(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["identity"], "v0.8P-v02-e1-identity-denylist-v02")
        self.assertEqual(
            hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
            contract["extractor"]["sha256"],
        )
        required_source = {
            "panel_identity",
            "panel_contract_sha256",
            "panel_manifest_sha256",
            "seal_manifest_sha256",
            "firewall_lock_sha256",
            "seal_status",
            "expected_neighborhood_count",
        }
        self.assertTrue(required_source.issubset(contract["source"]))
        self.assertEqual(contract["source"]["expected_neighborhood_count"], 2000)
        self.assertIn("domain_prefix", contract["identity_hash"])
        self.assertIn("hashes_filename", contract["output"])
        self.assertIn("seal_filename", contract["output"])


if __name__ == "__main__":
    unittest.main()
