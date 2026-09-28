from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SCOPE_SPEC = importlib.util.spec_from_file_location(
    "jev_v08i_scope_under_test", HERE / "scope_training_inputs.py"
)
assert SCOPE_SPEC and SCOPE_SPEC.loader
scope = importlib.util.module_from_spec(SCOPE_SPEC)
SCOPE_SPEC.loader.exec_module(scope)

ASSEMBLER_SPEC = importlib.util.spec_from_file_location(
    "jev_v08i_assembler_under_test", HERE / "assemble_phase_a.py"
)
assert ASSEMBLER_SPEC and ASSEMBLER_SPEC.loader
assembler = importlib.util.module_from_spec(ASSEMBLER_SPEC)
ASSEMBLER_SPEC.loader.exec_module(assembler)


class TrainingScopeTests(unittest.TestCase):
    def test_assembler_uses_scoped_receipt_filename(self) -> None:
        source = Path("D:/runs/v02/training-inputs")
        self.assertEqual(
            assembler.training_scope_receipt_path(source),
            source / "scope-receipt.json",
        )

    def test_frozen_contract_dimensions_are_read_from_declared_sections(self) -> None:
        contract_path = HERE / "phase-a-v02-clean-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        scope.validate_phase_a_contract(contract)

        with self.assertRaisesRegex(ValueError, "bank dose/count"):
            changed = json.loads(json.dumps(contract))
            changed["bank_construction"]["selected_anchor_dose"] = 4_999
            scope.validate_phase_a_contract(changed)

    def test_protected_legacy_manifests_allow_repeated_group_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-ids.jsonl"
            row = {"group_id": "legacy-group", "episode_id": "legacy-episode"}
            path.write_text(
                json.dumps(row) + "\n" + json.dumps(row) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                len(scope.manifest_rows(path, require_unique=False)), 2
            )
            with self.assertRaisesRegex(ValueError, "duplicate group IDs"):
                scope.manifest_rows(path)

    def test_frozen_group_helpers_load_without_torch_or_transformers(self) -> None:
        probe = scope.load_probe()
        candidate = {
            "candidate_semantic_id": "payment_duplicate",
            "name": "Duplicate payment",
            "description": "One purchase produced repeated charges.",
            "opaque_id": "Q17",
        }
        self.assertEqual(
            probe.candidate_surface(candidate, 0, "name_definition"),
            "Duplicate payment — One purchase produced repeated charges.",
        )
        self.assertEqual(
            probe.candidate_surface(candidate, 0, "opaque_definition"),
            "Q17 — One purchase produced repeated charges.",
        )

    def test_training_value_digest_matches_canonical_signature_domain(self) -> None:
        value = "line one\nline two"
        expected = scope.hashlib.sha256(
            scope.canonical_json(value).encode("utf-8")
        ).hexdigest()
        self.assertEqual(scope.training_value_digest(value), expected)
        self.assertNotEqual(
            scope.training_value_digest(value),
            scope.hashlib.sha256(value.encode("utf-8")).hexdigest(),
        )

    def test_nonselected_record_body_is_not_json_decoded(self) -> None:
        train = {
            "identity": {"episode_id": "train-episode"},
            "state": {"observable": {"content": "training text"}},
        }
        protected = {
            "identity": {"episode_id": "eval-episode"},
            "state": {"observable": {"content": "protected evaluation text"}},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canonical.jsonl"
            path.write_text(
                json.dumps(train, separators=(",", ":"))
                + "\n"
                + json.dumps(protected, separators=(",", ":"))
                + "\n",
                encoding="utf-8",
            )
            selected, audit = scope.selected_canonical_episodes(
                path, {"train-episode"}, {"eval-episode"}
            )
        self.assertEqual(set(selected), {"train-episode"})
        self.assertEqual(audit["selected_training_episode_bodies_parsed"], 1)
        self.assertEqual(audit["protected_eval_episode_bodies_parsed"], 0)
        self.assertEqual(audit["protected_eval_identity_prefixes_seen"], 1)
        self.assertEqual(audit["nonselected_record_bodies_json_decoded"], 0)

    def test_unscoped_representation_table_is_rejected_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = root / "scope-receipt.json"
            receipt_path.write_text(
                json.dumps(
                    {
                        "status": "TRAINING_ONLY_REPRESENTATION_SCOPE_PASS",
                        "source_scope": "training_only",
                        "source_bank": "R100-star",
                        "source_row_count": 100_000,
                        "source_bank_hash": "bank-hash",
                        "contains_eval_ids": False,
                        "contains_eval_family_ids": False,
                        "contains_eval_text": False,
                        "group_file": {
                            "path": str(root / "groups.jsonl"),
                            "sha256": "unused",
                            "source_scope": "training_only",
                            "source_banks": ["R100-star"],
                            "source_bank_hash": "bank-hash",
                        },
                        "representation_tables": {
                            "state_inputs": {
                                "path": str(root / "must-not-open.jsonl"),
                                "sha256": "unused",
                                "count": 1,
                                "source_scope": "training_only",
                                "source_banks": ["random"],
                                "source_bank_hash": "bank-hash",
                                "source_row_count": 100_000,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "refusing to open unscoped"):
                assembler.source_inputs(receipt_path)


if __name__ == "__main__":
    unittest.main()
