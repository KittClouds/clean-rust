from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT = REPO_ROOT / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
SCRIPT_DIR = PROJECT / "source" / "scripts"
SPEC = importlib.util.spec_from_file_location(
    "e2_execution_identity_v06",
    SCRIPT_DIR / "e2_execution_identity_v06.py",
)
assert SPEC is not None and SPEC.loader is not None
IDENTITY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = IDENTITY
SPEC.loader.exec_module(IDENTITY)


class ExecutionIdentityTests(unittest.TestCase):
    def test_historical_e0_v06_manifest_normalizes_without_metadata_alias(self) -> None:
        seal_path = PROJECT / "seals" / "e0-seal-v06.json"
        seal, freeze, identity, metadata = IDENTITY.normalize_e0_manifest(
            REPO_ROOT,
            seal_path,
            "968e7da8d44e36e31de81e87bdf140e7d766100891cecb7bbf9b4be80e99b3ea",
        )
        self.assertNotIn("freeze_id", seal)
        self.assertEqual(seal["seal_id"], "FAS_FROZEN_OBSERVER_BUNDLE_E0_SEAL_V06")
        self.assertEqual(freeze["freeze_id"], "FAS_FROZEN_OBSERVER_BUNDLE_E0_FREEZE_V06")
        self.assertEqual(identity.seal_root_sha256, seal["root_sha256"])
        self.assertEqual(identity.e1_root_sha256, "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03")
        self.assertEqual(identity.extractor_sha256, freeze["extractor_source_sha256"])
        self.assertEqual(identity.representation_abi_sha256, freeze["representation_abi_sha256"])
        self.assertEqual(identity.comparator_sha256, freeze["representation_equivalence_gate"]["reference_cache_sha256"])
        self.assertEqual(metadata["manifest_seal_id"], seal["seal_id"])
        self.assertEqual(metadata["manifest_status"], seal["status"])
        self.assertIsNone(metadata["manifest_freeze_id"])
        self.assertEqual(metadata["contract_freeze_id"], freeze["freeze_id"])

    def test_e0_root_mismatch_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "bound predecessor"):
            IDENTITY.normalize_e0_manifest(
                REPO_ROOT,
                PROJECT / "seals" / "e0-seal-v06.json",
                "0" * 64,
            )

    def test_current_e0_v09_manifest_normalizes_from_sealed_membership(self) -> None:
        seal_path = PROJECT / "seals" / "e0-seal-v09.json"
        seal, freeze, identity, metadata = IDENTITY.normalize_e0_manifest(
            REPO_ROOT,
            seal_path,
        )
        self.assertNotIn("freeze_id", seal)
        self.assertEqual(identity.seal_root_sha256, seal["root_sha256"])
        self.assertEqual(identity.freeze_contract_sha256, IDENTITY.sha256_file(
            REPO_ROOT / seal["freeze_contract_path"]
        )[0])
        self.assertEqual(identity.e1_root_sha256, IDENTITY.EXPECTED_E1_V04_ROOT)
        self.assertEqual(identity.extractor_sha256, freeze["extractor_source_sha256"])
        self.assertEqual(identity.verifier_sha256, freeze["execution_identity_verifier_sha256"])
        self.assertEqual(identity.representation_abi_sha256, freeze["representation_abi_sha256"])
        self.assertEqual(identity.comparator_sha256, freeze["representation_equivalence_gate"]["reference_cache_sha256"])
        self.assertIsNone(metadata["manifest_freeze_id"])
        self.assertEqual(metadata["contract_freeze_id"], freeze["freeze_id"])

    def test_full_v06_pre_model_path_passes_without_model_runtime_imports(self) -> None:
        before = set(sys.modules)
        result = IDENTITY.verify_pre_model_bindings(SCRIPT_DIR / "extract_features_v06.py")
        imported_roots = {name.split(".", 1)[0] for name in set(sys.modules) - before}
        self.assertFalse(imported_roots & {"torch", "transformers", "tokenizers"})
        self.assertTrue(all(result.checks.values()))
        self.assertFalse(result.observations["model_contact_authorized"])
        self.assertFalse(result.observations["tokenizer_contact_authorized"])
        self.assertFalse(result.observations["cuda_allocator_initialized"])
        sealed_root = IDENTITY.read_json(PROJECT / "seals" / "e0-seal-v09.json")["root_sha256"]
        self.assertEqual(result.identity.seal_root_sha256, sealed_root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
