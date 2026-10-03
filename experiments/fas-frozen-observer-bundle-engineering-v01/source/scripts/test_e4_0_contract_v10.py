from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "finalize_e4_0_contract_v10.py"
SPEC = importlib.util.spec_from_file_location("finalize_e4_0_contract_v10", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import v10 finalizer")
FINALIZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FINALIZER)
MAP_PATH = HERE / "build_e4_0_source_map_v09.py"
MAP_SPEC = importlib.util.spec_from_file_location("build_e4_0_source_map_v09", MAP_PATH)
if MAP_SPEC is None or MAP_SPEC.loader is None:
    raise RuntimeError("cannot import v09 source-map builder")
MAP_BUILDER = importlib.util.module_from_spec(MAP_SPEC)
MAP_SPEC.loader.exec_module(MAP_BUILDER)
SEAL_PATH = HERE / "seal_e4_0_contract_v10.py"
SEAL_SPEC = importlib.util.spec_from_file_location("seal_e4_0_contract_v10", SEAL_PATH)
if SEAL_SPEC is None or SEAL_SPEC.loader is None:
    raise RuntimeError("cannot import v10 sealer")
SEALER = importlib.util.module_from_spec(SEAL_SPEC)
SEAL_SPEC.loader.exec_module(SEALER)


class ContractV10Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[4]
        cls.project = root / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
        cls.v06 = json.loads((cls.project / "contracts" / "e4-0-contract-v06-final.json").read_text(encoding="utf-8"))

    def test_v06_baseline_is_sealed_and_exact_hash(self) -> None:
        path = self.project / "contracts" / "e4-0-contract-v06-final.json"
        size, sha = FINALIZER.sha256_file(path)
        self.assertEqual(size, 43208)
        self.assertEqual(sha, FINALIZER.BASELINE_SHA256)
        self.assertEqual(self.v06["contract_id"], "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06")
        self.assertEqual(self.v06["status"], "SEALED")

    def test_v08_is_exact_sealed_immediate_predecessor_and_v06_science_baseline(self) -> None:
        contract = self.project / "contracts" / "e4-0-contract-v08-final.json"
        seal = self.project / "seals" / "e4-0-contract-v08-seal.json"
        audit = self.project / "audits" / "e4-0-track-e" / "track-e-postseal-receipt-v08.json"
        self.assertEqual(FINALIZER.sha256_file(contract), (54286, FINALIZER.V08_CONTRACT_SHA256))
        self.assertEqual(FINALIZER.sha256_file(seal), (68666, FINALIZER.V08_SEAL_SHA256))
        self.assertEqual(FINALIZER.sha256_file(audit), (68220, FINALIZER.V08_AUDIT_SHA256))
        payload = json.loads(contract.read_text(encoding="utf-8"))
        self.assertEqual(payload["contract_id"], "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V08")
        self.assertEqual(payload["engineering_amendment"]["scientific_baseline"]["seal_root_sha256"], FINALIZER.V06_ROOT_SHA256)

    def test_v09_failed_preseal_candidate_is_bound_without_claiming_a_seal(self) -> None:
        map_path = self.project / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v08.md"
        contract_path = self.project / "contracts" / "e4-0-contract-v09-final.json"
        stop_path = self.project / "audits" / "e4-0-track-e" / "track-e-preseal-receipt-v09.json"
        self.assertEqual(FINALIZER.sha256_file(map_path), (FINALIZER.V09_MAP_BYTES, FINALIZER.V09_MAP_SHA256))
        self.assertEqual(FINALIZER.sha256_file(contract_path), (FINALIZER.V09_CONTRACT_BYTES, FINALIZER.V09_CONTRACT_SHA256))
        self.assertEqual(FINALIZER.sha256_file(stop_path), (FINALIZER.V09_PRESEAL_BYTES, FINALIZER.V09_PRESEAL_SHA256))
        receipt = json.loads(stop_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V09")
        self.assertIsNone(receipt["final_seal"])
        self.assertFalse(receipt["pass"])
        self.assertFalse(receipt["population_truth_files_opened"])
        self.assertFalse(receipt["template_or_joint_truth_opened"])
        for key in ("preserved_v07_authorization_stop", "preserved_v08_authorization_stop"):
            self.assertFalse(receipt[key]["model_contact"])
            self.assertFalse(receipt[key]["tokenizer_contact"])

    def test_v08_stop_and_pmon_preflight_are_bound_no_contact_history(self) -> None:
        stop = self.project / "audits" / "e4-0-auth-issuer-v08" / "online-parity-precontact-stop-v01.json"
        bindings = self.project / "audits" / "e4-0-auth-issuer-v08" / "online-parity-bindings-v01.json"
        pmon = self.project / "audits" / "e4-0-execution" / "wddm-gpu-lease-preflight-v02.json"
        self.assertEqual(FINALIZER.sha256_file(stop), (FINALIZER.V08_STOP_BYTES, FINALIZER.V08_STOP_SHA256))
        self.assertEqual(FINALIZER.sha256_file(bindings), (FINALIZER.V08_BINDINGS_BYTES, FINALIZER.V08_BINDINGS_SHA256))
        self.assertEqual(FINALIZER.sha256_file(pmon), (FINALIZER.WDDM_BYTES, FINALIZER.WDDM_SHA256))
        stop_payload = json.loads(stop.read_text(encoding="utf-8"))
        pmon_payload = json.loads(pmon.read_text(encoding="utf-8"))
        self.assertIs(stop_payload["authorization_output_written"], False)
        self.assertIs(stop_payload["model_contact"], False)
        MAP_BUILDER.validate_v08_authorization_stop(stop_payload)
        self.assertEqual(stop_payload["status"], "E4_0_V08_AUTHORIZATION_STOP_POPULATION_AUDIT_SCHEMA_MISMATCH")
        self.assertEqual(stop_payload["stop_class"], "PRECONTACT_AUTHORIZATION_VERIFIER_SCHEMA_MISMATCH")
        wrong_stop_class = copy.deepcopy(stop_payload)
        wrong_stop_class["stop_class"] = "MODEL_RUNTIME_FAILURE"
        with self.assertRaises(RuntimeError):
            MAP_BUILDER.validate_v08_authorization_stop(wrong_stop_class)
        self.assertTrue(pmon_payload["nvidia_smi_pmon_snapshot"].startswith("# gpu"))
        self.assertIs(pmon_payload["gpu_lease_acquired"], False)
        self.assertIs(pmon_payload["total_gpu_memory_claimed"], False)

    def test_v08_preseal_stop_attempts_are_preserved_exactly(self) -> None:
        stop = self.project / "audits" / "e4-0-track-e" / "history" / "track-e-preseal-stop-v08-v01.json"
        self.assertEqual(FINALIZER.sha256_file(stop), (FINALIZER.V08_PRESEAL_STOP_BYTES, FINALIZER.V08_PRESEAL_STOP_SHA256))
        payload = json.loads(stop.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V08")

    def test_source_map_metadata_is_excluded_from_science_projection(self) -> None:
        candidate = copy.deepcopy(self.v06)
        candidate["design_inputs"].pop("implementation_source_map_v05_path", None)
        candidate["design_inputs"]["implementation_source_map_v08_path"] = "different-map.md"
        self.assertEqual(FINALIZER.scientific_projection(candidate), FINALIZER.scientific_projection(self.v06))
        FINALIZER.require_scientific_invariance(candidate, self.v06)

    def test_any_registered_scientific_field_change_fails_closed(self) -> None:
        for field in FINALIZER.IMMUTABLE:
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.v06)
                candidate[field] = {"tampered": True}
                with self.assertRaises(RuntimeError):
                    FINALIZER.require_scientific_invariance(candidate, self.v06)

    def test_design_input_change_other_than_map_metadata_fails_closed(self) -> None:
        candidate = copy.deepcopy(self.v06)
        candidate["design_inputs"]["template_manifest_sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            FINALIZER.require_scientific_invariance(candidate, self.v06)

    def test_predecessor_map_parser_finds_unique_source_receipt_tables(self) -> None:
        predecessor_map = self.project / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v07.md"
        sources = MAP_BUILDER.table(predecessor_map, ["Path", "Bytes", "SHA-256", "Role"])
        receipts = MAP_BUILDER.table(predecessor_map, ["Track", "Path", "Bytes", "SHA-256", "Status"])
        inputs = MAP_BUILDER.table(predecessor_map, ["Input Path", "Bytes", "SHA-256", "Role"])
        self.assertGreater(len(sources), 30)
        self.assertGreater(len(receipts), 8)
        self.assertGreater(len(inputs), 10)

    def test_predecessor_track_names_are_not_double_prefixed(self) -> None:
        self.assertEqual(MAP_BUILDER.predecessor_track("Track A v03"), "Predecessor Track A v03")
        self.assertEqual(MAP_BUILDER.predecessor_track("Predecessor Track A v03"), "Predecessor Track A v03")
        self.assertIn("TRACK_E_SOURCE_TESTS_PASS_V09_PREMAP_SYNTHETIC_AUDITOR", MAP_BUILDER.PASS_STATUSES)

    def test_table_parser_fails_closed_when_requested_table_is_absent(self) -> None:
        with self.assertRaises(RuntimeError):
            MAP_BUILDER.table(Path(__file__), ["Track", "Path", "Bytes", "SHA-256", "Status"])

    def test_finalizer_rejects_bypass_and_track_status_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = root / "receipt.json"
            map_path = root / "map.md"
            for track, status in (("Prior X", "BYPASS_PASS"), ("Authorization issuer v10", "TRACK_E_SOURCE_TESTS_PASS_V10_PREMAP_SYNTHETIC_AUDITOR")):
                receipt.write_text(json.dumps({"status": status}), encoding="utf-8")
                size, sha = FINALIZER.sha256_file(receipt)
                map_path.write_text(
                    "| Track | Path | Bytes | SHA-256 | Status |\n| --- | --- | ---: | --- | --- |\n"
                    f"| {track} | `receipt.json` | {size} | `{sha}` | `{status}` |\n",
                    encoding="utf-8",
                )
                with self.assertRaises(RuntimeError):
                    FINALIZER.receipt_rows(map_path, root)

    def test_finalizer_accepts_preserved_v08_track_e_pre_map_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = root / "receipt.json"
            status = "TRACK_E_SOURCE_TESTS_PASS_V08_PREMAP_SYNTHETIC_AUDITOR"
            receipt.write_text(json.dumps({"status": status}), encoding="utf-8")
            size, sha = FINALIZER.sha256_file(receipt)
            map_path = root / "map.md"
            map_path.write_text(
                "| Track | Path | Bytes | SHA-256 | Status |\n| --- | --- | ---: | --- | --- |\n"
                f"| Predecessor Track E | `receipt.json` | {size} | `{sha}` | `{status}` |\n",
                encoding="utf-8",
            )
            rows = FINALIZER.receipt_rows(map_path, root)
            self.assertEqual(rows[0]["status"], status)

    def test_finalizer_reconstructs_receipt_source_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = "experiments/fas-frozen-observer-bundle-engineering-v01"
            names = {
                "e4_runner_common_v05.py", "e4_runner_artifacts_v05.py", "e4_gpu_lease_v04.py",
                "e4_runner_modes_v05.py", "e4_online_parity_v05.py", "test_e4_runner_v05.py",
            }
            source_rows, bindings = [], []
            for name in sorted(names):
                rel = f"{project}/source/{'tests' if name.startswith('test_') else 'scripts'}/{name}"
                source = root / rel
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(name.encode("utf-8"))
                size, sha = FINALIZER.sha256_file(source)
                source_rows.append({"path": rel, "bytes": size, "sha256": sha})
                bindings.append({"path": rel.removeprefix(project + "/"), "bytes": size, "sha256": sha})
            builder_rows = [(row["path"], root / row["path"], "synthetic") for row in source_rows]
            MAP_BUILDER.verify_receipt_source_bindings("Track B v05", {"bound_sources": bindings}, builder_rows)
            receipt_path = root / "receipt.json"
            receipt_path.write_text(json.dumps({"bound_sources": bindings}), encoding="utf-8")
            receipts = [{"track": "Track B v05", "path": "receipt.json"}]
            FINALIZER.verify_receipt_source_closure(receipts, source_rows, root)
            bindings[-1]["sha256"] = "0" * 64
            with self.assertRaises(RuntimeError):
                MAP_BUILDER.verify_receipt_source_bindings("Track B v05", {"bound_sources": bindings}, builder_rows)
            receipt_path.write_text(json.dumps({"bound_sources": bindings}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                FINALIZER.verify_receipt_source_closure(receipts, source_rows, root)

    def test_sealer_rejects_casefolded_duplicate_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / "MixedCase.bin"
            artifact.write_bytes(b"sealed")
            size, sha = SEALER.digest(artifact)
            by_path, by_identity = {}, set()
            SEALER.add_member(root, by_path, by_identity, "first", "MixedCase.bin", size, sha)
            with self.assertRaises(RuntimeError):
                SEALER.add_member(root, by_path, by_identity, "second", "MIXEDCASE.BIN", size, sha)

    def test_fixed_output_paths_reject_traversal_and_existing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "seals").mkdir()
            self.assertEqual(SEALER.safe_output_path(root, "seals/out.json"), root / "seals" / "out.json")
            with self.assertRaises(RuntimeError):
                SEALER.safe_output_path(root, "../escape.json")
            (root / "seals" / "out.json").write_text("exists", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                SEALER.safe_output_path(root, "seals/out.json")

    def test_builder_and_finalizer_reject_symlinked_output_parents(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            alias = root / "plans"
            alias.mkdir()
            real_is_symlink = Path.is_symlink
            def simulated_symlink(path: Path) -> bool:
                return path.name == "plans" or real_is_symlink(path)
            with patch.object(MAP_BUILDER, "WORKSPACE", root):
                with patch.object(Path, "is_symlink", autospec=True, side_effect=simulated_symlink):
                    with self.assertRaises(RuntimeError):
                        MAP_BUILDER.safe_output_path(alias / "map.md")
                    with self.assertRaises(RuntimeError):
                        FINALIZER.safe_output_path(alias / "contract.json", root)

    def test_builder_accepts_safe_existing_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plans = root / "plans"
            plans.mkdir()
            with patch.object(MAP_BUILDER, "WORKSPACE", root):
                MAP_BUILDER.safe_output_path(plans / "map.md")

    def test_builder_rejects_output_parent_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "inside"
            outside = Path(temp) / "outside"
            root.mkdir()
            outside.mkdir()
            with patch.object(MAP_BUILDER, "WORKSPACE", root):
                with self.assertRaises(RuntimeError):
                    MAP_BUILDER.safe_output_path(outside / "map.md")


if __name__ == "__main__":
    unittest.main(verbosity=2)
