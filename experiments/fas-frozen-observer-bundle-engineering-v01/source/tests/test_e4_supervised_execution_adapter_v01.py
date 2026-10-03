from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = PROJECT / "source" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from e4_supervised_execution_adapter_v01 import (  # noqa: E402
    ADAPTER_ID,
    BASE_PREDECESSOR_ROOT_KEYS,
    COMMON_ARTIFACTS,
    CONTRACT_ROOT,
    CONTRACT_SHA256,
    HANDOFF_SEAL_ROOT,
    LIBRARY_ACCEPTANCE_ID,
    MODE_ARTIFACTS,
    MODE_OUTPUT_DIR,
    MODE_STAGE,
    OUTPUTS,
    SCHEMA,
    VISIBLE_BRIDGE_ROOT,
    BindingError,
    load_binding,
    validate_binding_document,
)
from e4_runner_artifacts_v05 import artifact_root  # noqa: E402
from e4_runner_common_v05 import E0_ROOT, E1_ROOT, E2_ROOT, E3_BUNDLE_ROOT  # noqa: E402
from e4_runner_modes_v06 import (  # noqa: E402
    verify_seal_members_against_bound_visible_inputs,
    verify_stage_seal_manifest_only,
)


def binding(mode: str) -> dict:
    roots = set(BASE_PREDECESSOR_ROOT_KEYS)
    if mode == "extract-e4":
        roots.add("e4_parity_receipt_root_sha256")
    digest = "a" * 64
    return {
        "schema": SCHEMA,
        "adapter_id": ADAPTER_ID,
        "mode": mode,
        "stage": MODE_STAGE[mode],
        "contract_sha256": CONTRACT_SHA256,
        "contract_seal_manifest_sha256": digest,
        "contract_seal_root_sha256": CONTRACT_ROOT,
        "output_root": str(Path(tempfile.gettempdir()).resolve() / "e4-run-root"),
        "supervised_output_root": str(Path(tempfile.gettempdir()).resolve() / "e4-run-root" / MODE_OUTPUT_DIR[mode]),
        "inherited_stage_root": str(Path(tempfile.gettempdir()).resolve() / "e4-inherited-root"),
        "expected_outputs": list(OUTPUTS[mode]),
        "exact_predecessor_roots": {key: digest for key in roots},
        "artifacts": {
            key: {"path": str(Path(tempfile.gettempdir()).resolve() / f"{key}.json"),
                  "sha256": digest, "bytes": 0}
            for key in (MODE_ARTIFACTS[mode] | COMMON_ARTIFACTS)
        },
        "paths": {
            "model_snapshot": str(Path(tempfile.gettempdir()).resolve() / "model"),
            "tokenizer_snapshot": str(Path(tempfile.gettempdir()).resolve() / "tokenizer"),
            "model_asset_manifest": str(Path(tempfile.gettempdir()).resolve() / "model-manifest.json"),
            "tokenizer_asset_manifest": str(Path(tempfile.gettempdir()).resolve() / "tokenizer-manifest.json"),
        },
        "library_handoff": {
            "library_acceptance_id": LIBRARY_ACCEPTANCE_ID,
            "handoff_seal_root_sha256": HANDOFF_SEAL_ROOT,
            "visible_inheritance_bridge_root_sha256": VISIBLE_BRIDGE_ROOT,
        },
    }


class SupervisedAdapterBindingTests(unittest.TestCase):
    def test_both_frozen_modes_accept_exact_static_binding(self) -> None:
        for mode in ("parity", "extract-e4"):
            with self.subTest(mode=mode):
                checked = validate_binding_document(binding(mode), mode)
                self.assertEqual(checked["mode"], mode)
                self.assertEqual(checked["expected_outputs"], list(OUTPUTS[mode]))

    def test_mode_stage_contract_and_handoff_mismatches_fail_closed(self) -> None:
        mutations = (
            ("mode", "extract-e4"),
            ("stage", "FRESH_FEATURE_EXTRACTION"),
            ("contract_sha256", "0" * 64),
            ("contract_seal_root_sha256", "0" * 64),
        )
        for field, wrong in mutations:
            value = binding("parity")
            value[field] = wrong
            with self.subTest(field=field), self.assertRaises(BindingError):
                validate_binding_document(value, "parity")
        value = binding("parity")
        value["library_handoff"]["handoff_seal_root_sha256"] = "0" * 64
        with self.assertRaises(BindingError):
            validate_binding_document(value, "parity")

    def test_output_inventory_and_artifact_roles_are_fixed(self) -> None:
        value = binding("parity")
        value["expected_outputs"].append("parity/extra.bin")
        with self.assertRaises(BindingError):
            validate_binding_document(value, "parity")

    def test_ledger_worker_root_must_be_fresh_mode_child(self) -> None:
        value = binding("parity")
        value["supervised_output_root"] = str(Path(value["output_root"]).resolve() / "features")
        with self.assertRaises(BindingError):
            validate_binding_document(value, "parity")
        value = binding("parity")
        value["artifacts"]["terminal_labels"] = {
            "path": str(Path(tempfile.gettempdir()).resolve() / "labels.json"),
            "sha256": "a" * 64, "bytes": 1,
        }
        with self.assertRaises(BindingError):
            validate_binding_document(value, "parity")

    def test_authority_and_lease_fields_are_not_part_of_static_binding(self) -> None:
        for field in ("authorization_id", "scope", "lease_id", "fencing_token", "actor_token"):
            value = binding("parity")
            value[field] = "forbidden"
            with self.subTest(field=field), self.assertRaises(BindingError):
                validate_binding_document(value, "parity")

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "binding.json"
            path.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
            with self.assertRaises(BindingError):
                load_binding(path, "parity")

    def test_inherited_seal_audit_does_not_open_unbound_protected_members(self) -> None:
        roots = {
            "e0_v10_root_sha256": E0_ROOT,
            "e1_v04_root_sha256": E1_ROOT,
            "e2_v07_root_sha256": E2_ROOT,
            "e3_v02_bundle_root_sha256": E3_BUNDLE_ROOT,
        }
        entries = [
            {"artifact_id": "visible-population-inputs", "path": "population/inputs.jsonl",
             "bytes": 5, "sha256": "5" * 64},
            {"artifact_id": "protected-labels", "path": "population/private-labels.jsonl",
             "bytes": 900, "sha256": "6" * 64},
        ]
        seal = {
            "schema": "FAS_E4_0_ARTIFACT_SEAL_V01", "status": "SEALED",
            "seal_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_POPULATION_GENERATION_SEAL_V01",
            "stage": "POPULATION_GENERATION", "path_root_kind": "E4_RUN_ROOT",
            "created_utc": "2026-09-27T00:00:00Z",
            "contract_sha256": "ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958",
            "contract_seal_root_sha256": "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64",
            "exact_predecessor_roots": roots, "entries": entries,
            "entry_count": len(entries), "root_sha256": artifact_root(entries),
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            seal_path = root / "population-seal.json"
            import json
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            verified = verify_stage_seal_manifest_only(
                seal_path, seal["root_sha256"], "POPULATION_GENERATION",
                {"contract_sha256": CONTRACT_SHA256, "contract_seal_root_sha256": CONTRACT_ROOT,
                 "exact_predecessor_roots": roots},
            )
            self.assertEqual(len(verified["entries"]), 2)
            self.assertFalse((root / "population" / "private-labels.jsonl").exists())

    def test_visible_member_check_only_requires_the_selected_visible_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            visible = root / "inputs.jsonl"
            visible.write_bytes(b"rows\n")
            import hashlib
            digest = hashlib.sha256(visible.read_bytes()).hexdigest()
            entries = [
                {"artifact_id": "visible", "path": "inputs.jsonl", "bytes": 5, "sha256": digest},
                {"artifact_id": "private", "path": "labels.jsonl", "bytes": 99, "sha256": "9" * 64},
            ]
            seal = {"entries": entries}
            bound = {"population_inputs": {"path": str(visible), "sha256": digest, "bytes": 5}}
            verify_seal_members_against_bound_visible_inputs(seal, root, bound, ("population_inputs",))
            self.assertFalse((root / "labels.jsonl").exists())

    def test_runner_source_has_no_local_authority_or_lease_call(self) -> None:
        mode_path = SCRIPT_DIR / "e4_runner_modes_v06.py"
        source = mode_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertNotIn("make_gpu_lease", source)
        self.assertNotIn("e4_gpu_lease_v04", source)
        self.assertNotIn("validate_stage_authorization(", source)
        self.assertNotIn("gpu_lease_receipt", source)
        run_online = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                          and node.name == "run_online_mode")
        calls = [node.func.id for node in ast.walk(run_online)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertNotIn("make_gpu_lease", calls)
        self.assertNotIn("validate_stage_authorization", calls)
        self.assertNotIn("issue_e4_stage_authorization", source)

    def test_import_path_keeps_heavy_runtime_lazy(self) -> None:
        code = (
            f"import sys; sys.path.insert(0, {str(SCRIPT_DIR)!r}); "
            "import e4_online_supervised_v01; "
            "assert 'torch' not in sys.modules; assert 'transformers' not in sys.modules"
        )
        subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
