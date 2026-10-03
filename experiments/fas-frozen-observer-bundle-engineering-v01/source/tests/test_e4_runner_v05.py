"""Synthetic-only E4-0 runner tests; imports do not load tokenizer/model/CUDA."""

from __future__ import annotations

import json
import ast
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import e4_gpu_lease_v04 as gpu
import e4_runner_artifacts_v05 as artifacts
import e4_runner_common_v05 as common
import e4_runner_modes_v05 as modes


class QueryAndSelectorTests(unittest.TestCase):
    def test_query_template_identity_is_recovered_from_label_free_text(self) -> None:
        contexts = frozenset({"context-7"})
        entities = frozenset({"entity-4"})
        for expected, template in enumerate(common.QUERY_TEMPLATES):
            query = template.format(relation="kelmori", entity="entity-4", context="context-7")
            text = f"Observation\n{query}\nOptions: x, y, z"
            self.assertEqual(common.infer_query_template_id(text, contexts, entities), expected)

    def test_query_template_rejects_unknown_term_or_ambiguous_shape(self) -> None:
        with self.assertRaises(common.E4RunnerError):
            common.infer_query_template_id(
                "Observation\nWhat is kelmori for missing in context-7?\nOptions: x",
                frozenset({"context-7"}), frozenset({"entity-4"}),
            )

    def test_parity_selector_is_deterministic_and_balanced(self) -> None:
        quartets = []
        for query in range(8):
            for rank in range(32):
                quartet = f"q{query:02d}-r{rank:02d}"
                rows = [
                    {"variant_id": variant, "cache_row_index": (query * 32 + rank) * 4 + i}
                    for i, variant in enumerate(common.VARIANTS)
                ]
                quartets.append({
                    "quartet_id": quartet,
                    "query_template_id": query,
                    "max_token_count": rank + 1,
                    "rows": rows,
                })
        first = common.select_parity_quartets(quartets)
        second = common.select_parity_quartets(list(reversed(quartets)))
        self.assertEqual([row["quartet_id"] for row in first], [row["quartet_id"] for row in second])
        self.assertEqual(len(first), 256)
        self.assertEqual({(row["query_template_id"], row["quartile_id"]) for row in first}, {
            (query, quartile) for query in range(8) for quartile in range(4)
        })
        self.assertTrue(all(len(row["rows"]) == 4 for row in first))

    def test_e1_fit_quartet_builder_validates_identity_and_keeps_only_fit_rows(self) -> None:
        quartet_id = "fit-quartet"
        rows = []
        manifest = []
        query = common.QUERY_TEMPLATES[0].format(
            relation="kelmori", entity="entity-4", context="context-7",
        )
        for index, variant in enumerate(common.VARIANTS):
            row_id = f"row-{index}"
            rows.append({
                "row_id": row_id, "quartet_id": quartet_id, "variant_id": variant,
                "input_text": f"Observation\n{query}\nOptions: x, y, z",
            })
            manifest.append({
                "row_index": index, "row_id": row_id, "quartet_id": quartet_id,
                "variant_id": variant, "quartet_split": "FIT",
            })
        splits = [{
            "exact_target_stratum": "synthetic", "quartet_id": quartet_id,
            "split": "FIT", "split_assignment": 0,
        }]
        with patch.object(common, "E1_ROWS", 4):
            result = common.build_parity_quartets(
                rows, manifest, splits, frozenset({"context-7"}), frozenset({"entity-4"}),
                lambda _text: [1, 2, 3],
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["query_template_id"], 0)
        self.assertEqual([row["variant_id"] for row in result[0]["rows"]], list(common.VARIANTS))


class E4PopulationStreamTests(unittest.TestCase):
    @staticmethod
    def make_group() -> list[tuple[dict[str, str], dict[str, object]]]:
        result = []
        for surface, custody in (
            (common.PRIMARY_SURFACE, common.PRIMARY_CUSTODY),
            (common.HELDOUT_SURFACE, common.ESCROW_CUSTODY),
        ):
            for variant in common.VARIANTS:
                row_id = f"quartet:{surface}:{variant}"
                input_row = {
                    "row_id": row_id, "quartet_id": "quartet", "variant_id": variant,
                    "input_text": "synthetic label-free input",
                }
                manifest = {
                    "row_index": len(result), "row_id": row_id, "quartet_id": "quartet",
                    "variant_id": variant, "surface_id": surface, "truth_partition": custody,
                }
                result.append((input_row, manifest))
        return result

    def test_e4_stream_checks_schedule_and_custody_without_materializing_population(self) -> None:
        with patch.object(artifacts, "E4_QUARTETS", 1):
            result = list(artifacts.iter_validated_e4_rows(iter(self.make_group())))
        self.assertEqual(len(result), 8)
        bad = self.make_group()
        bad[4][1]["truth_partition"] = common.PRIMARY_CUSTODY
        with patch.object(artifacts, "E4_QUARTETS", 1), self.assertRaises(common.E4RunnerError):
            list(artifacts.iter_validated_e4_rows(iter(bad)))

    def test_jsonl_stream_rejects_labels_and_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path, row_path = root / "inputs.jsonl", root / "rows.jsonl"
            input_path.write_text(json.dumps({
                "row_id": "r", "quartet_id": "q", "variant_id": "A", "input_text": "x", "label": 1,
            }) + "\n", encoding="utf-8")
            row_path.write_text(json.dumps({
                "row_index": 0, "row_id": "r", "quartet_id": "q", "variant_id": "A",
                "surface_id": common.PRIMARY_SURFACE, "truth_partition": common.PRIMARY_CUSTODY,
            }) + "\n", encoding="utf-8")
            with self.assertRaises(common.E4RunnerError):
                list(artifacts.input_row_stream(input_path, row_path))


class SealAndAuthorizationTests(unittest.TestCase):
    def test_generic_stage_seal_verifies_root_bytes_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = root / "features" / "cache.bin"
            payload.parent.mkdir()
            payload.write_bytes(b"synthetic-cache")
            auth = {
                "output_root": str(root),
                "contract_sha256": "a" * 64,
                "contract_seal_root_sha256": "b" * 64,
                "exact_predecessor_roots": {"e0_v10_root_sha256": "c" * 64},
            }
            seal = artifacts.write_stage_seal(auth, "FRESH_FEATURE_EXTRACTION", payload.parent, {"feature_cache": payload})
            self.assertEqual(seal["path_root_kind"], "E4_RUN_ROOT")
            checked = artifacts.verify_stage_seal(
                payload.parent / "stage-seal-v01.json", seal["root_sha256"], "FRESH_FEATURE_EXTRACTION", auth,
            )
            self.assertEqual(checked["entries"][0]["artifact_id"], "feature_cache")
            payload.write_bytes(b"tampered-cache")
            with self.assertRaises(common.E4RunnerError):
                artifacts.verify_stage_seal(
                    payload.parent / "stage-seal-v01.json", seal["root_sha256"], "FRESH_FEATURE_EXTRACTION", auth,
                )

    def test_stage_authorization_binds_contract_roots_scope_and_time(self) -> None:
        self.assertNotIn("materialize-parity-panel", common.CONTRACT_STAGES)
        with self.assertRaises(common.E4RunnerError):
            common.validate_stage_authorization({}, "materialize-parity-panel")

    def test_contract_binding_requires_exact_v09_seal_and_member_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            relative = Path("experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v09-final.json")
            contract_path = root / relative
            contract_path.parent.mkdir(parents=True)
            contract_path.write_text(json.dumps({
                "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V09", "status": "SEALED",
                "predecessors": {
                    "e0_v10_root_sha256": common.E0_ROOT,
                    "e1_v04_root_sha256": common.E1_ROOT,
                    "e2_v07_root_sha256": common.E2_ROOT,
                    "e3_v02_bundle_root_sha256": common.E3_BUNDLE_ROOT,
                },
            }), encoding="utf-8")
            contract_sha, contract_size = common.sha256_file(contract_path)
            entry = {"artifact_id": "E4_0_CONTRACT_V09_FINAL", "path": relative.as_posix(),
                     "bytes": contract_size, "sha256": contract_sha}
            root_hash = __import__("hashlib").sha256(
                f"{entry['artifact_id']}\t{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n".encode()
            ).hexdigest()
            seal = {
                "schema": "FAS_E4_0_ARTIFACT_SEAL_V01", "status": "SEALED",
                "seal_id": "FAS_E4_0_CONTRACT_V09_SEAL", "stage": "E4_0_CONTRACT",
                "path_root_kind": "WORKSPACE_ROOT", "root_sha256": root_hash,
                "entry_count": 1, "entries": [entry],
                "exact_predecessor_roots": json.loads(contract_path.read_text())["predecessors"],
            }
            seal_path = root / "seal.json"
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            audit_path = root / "audit.json"
            audit_path.write_text(json.dumps({
                "status": "E4_0_TRACK_E_POSTSEAL_PASS_V09_SEAL_ROOT_AND_MEMBERS_RECOMPUTED",
                "pass": True, "final_seal": {"root_sha256": root_hash},
            }), encoding="utf-8")
            authorization = {
                "contract_sha256": contract_sha, "contract_seal_root_sha256": root_hash,
                "contract_seal_manifest_sha256": common.sha256_file(seal_path)[0],
                "artifacts": {
                    "e4_contract": {"path": str(contract_path), "sha256": contract_sha, "bytes": contract_size},
                    "e4_contract_seal_manifest": {"path": str(seal_path), "sha256": common.sha256_file(seal_path)[0], "bytes": seal_path.stat().st_size},
                    "e4_contract_audit": {"path": str(audit_path), "sha256": common.sha256_file(audit_path)[0], "bytes": audit_path.stat().st_size},
                },
            }
            self.assertEqual(common.verify_contract_binding(authorization)["root_sha256"], root_hash)
            seal["seal_id"] = "WRONG_SEAL_ID"
            seal_path.write_text(json.dumps(seal), encoding="utf-8")
            authorization["artifacts"]["e4_contract_seal_manifest"].update(
                sha256=common.sha256_file(seal_path)[0], bytes=seal_path.stat().st_size,
            )
            authorization["contract_seal_manifest_sha256"] = common.sha256_file(seal_path)[0]
            with self.assertRaises(common.E4RunnerError):
                common.verify_contract_binding(authorization)

    def test_inherited_v06_stage_seals_are_accepted_under_v09_auth_only_by_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            roots = {
                "e0_v10_root_sha256": common.E0_ROOT,
                "e1_v04_root_sha256": common.E1_ROOT,
                "e2_v07_root_sha256": common.E2_ROOT,
                "e3_v02_bundle_root_sha256": common.E3_BUNDLE_ROOT,
                "e4_population_root_sha256": "1" * 64,
                "e4_population_audit_root_sha256": "2" * 64,
            }
            for stage, extra in (("POPULATION_GENERATION", {}), ("PARITY_PANEL_MATERIALIZATION", {
                "e4_population_root_sha256": roots["e4_population_root_sha256"],
                "e4_population_audit_root_sha256": roots["e4_population_audit_root_sha256"],
            })):
                payload = root / f"{stage}.bin"
                payload.write_bytes(stage.encode())
                stage_roots = {key: value for key, value in roots.items() if key not in ("e4_population_root_sha256", "e4_population_audit_root_sha256")}
                stage_roots.update(extra)
                entry = {"artifact_id": "payload", "path": payload.name,
                         "bytes": payload.stat().st_size, "sha256": common.sha256_file(payload)[0]}
                stage_root = artifacts.artifact_root([entry])
                seal_path = root / f"{stage}.json"
                seal_path.write_text(json.dumps({
                    "schema": "FAS_E4_0_ARTIFACT_SEAL_V01", "status": "SEALED",
                    "seal_id": f"FAS_FROZEN_CAPABILITY_FABRIC_E4_0_{stage}_SEAL_V01",
                    "stage": stage, "path_root_kind": "E4_RUN_ROOT",
                    "created_utc": "2026-09-26T00:00:00+00:00",
                    "contract_sha256": common.INHERITED_E4_V06_CONTRACT_SHA256,
                    "contract_seal_root_sha256": common.INHERITED_E4_V06_CONTRACT_ROOT,
                    "exact_predecessor_roots": stage_roots, "entries": [entry], "entry_count": 1,
                    "root_sha256": stage_root,
                }), encoding="utf-8")
                seal_data = json.loads(seal_path.read_text(encoding="utf-8"))
                auth = {
                    "output_root": str(root), "contract_sha256": "v09-contract-sha",
                    "contract_seal_root_sha256": "v09-contract-root",
                    "exact_predecessor_roots": roots,
                }
                checked = artifacts.verify_stage_seal(seal_path, stage_root, stage, auth)
                self.assertEqual(checked["contract_sha256"], common.INHERITED_E4_V06_CONTRACT_SHA256)
                seal_data["contract_sha256"] = "different"
                seal_path.write_text(json.dumps(seal_data), encoding="utf-8")
                with self.assertRaises(common.E4RunnerError):
                    artifacts.verify_stage_seal(seal_path, stage_root, stage, auth)

    def test_inherited_parity_panel_cannot_be_rematerialized_under_v09(self) -> None:
        with self.assertRaises(common.E4RunnerError):
            modes.materialize_parity_panel({})


    def test_invalid_stage_auth_fails_before_output_creation_or_cuda_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "must-not-exist"
            before = set(sys.modules)
            with self.assertRaises(common.E4RunnerError):
                modes.run_online_mode({"schema": "wrong", "output_root": str(output)}, "parity")
            self.assertFalse(output.exists())
            self.assertFalse(({"torch", "transformers"} & set(sys.modules)) - before)

    def test_feature_extraction_function_has_no_prediction_or_label_join_call(self) -> None:
        source_path = SCRIPTS / "e4_runner_modes_v05.py"
        module = ast.parse(source_path.read_text(encoding="utf-8"))
        function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "run_e4_feature_payload")
        calls = {
            node.func.id for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("head_predictions", calls)
        self.assertNotIn("load_e3_heads", calls)
        self.assertNotIn("open_terminal_labels", calls)


class GpuLeaseSyntheticTests(unittest.TestCase):
    def test_pmon_type_c_process_is_attributed_and_blocks(self) -> None:
        snapshot = "# gpu pid type sm mem enc dec jpg ofa command\n 0 23632 C 19 1 - - - - python.exe\n"
        with patch.object(gpu, "windows_process_identity", return_value={
            "pid": 23632, "executable": "python.exe", "script": "training.py",
        }):
            rows = gpu.classify_pmon_processes(snapshot)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nvidia_smi_process_type"], "C")
        self.assertTrue(rows[0]["lease_blocking"])
        self.assertEqual(rows[0]["classification"], "VERIFIED_TYPE_C_CUDA_COMPUTE_PROCESS")

    def test_pmon_c_plus_g_is_preserved_but_does_not_block(self) -> None:
        snapshot = "# gpu pid type sm mem enc dec jpg ofa command\n 0 584 C+G 10 0 - 7 - - chrome.exe\n"
        with patch.object(gpu, "windows_process_identity", side_effect=AssertionError("C+G must not require process identity")):
            rows = gpu.classify_pmon_processes(snapshot)
        self.assertEqual(rows[0]["nvidia_smi_process_type"], "C+G")
        self.assertFalse(rows[0]["lease_blocking"])
        self.assertIn("584", rows[0]["nvidia_smi_pmon_raw_line"])

    def test_unidentifiable_type_c_fails_closed(self) -> None:
        snapshot = " 0 42744 C 0 0 - - - - python.exe\n"
        with patch.object(gpu, "windows_process_identity", return_value=None):
            with self.assertRaisesRegex(gpu.E4RunnerError, "Type-C process PID 42744 disappeared"):
                gpu.classify_pmon_processes(snapshot)

    def test_unknown_pmon_type_fails_closed(self) -> None:
        with self.assertRaisesRegex(gpu.E4RunnerError, "unsupported pmon process type"):
            gpu.classify_pmon_processes(" 0 99 X 0 0 - - - - unknown.exe\n")

    def test_make_gpu_lease_uses_validated_stage_output_without_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output_root = root / "e4-output" / "parity"
            authorization = {
                "gpu_lease_required_before_model_contact": True,
                "gpu_lease": {
                    "lock_path": str(root / "cuda0.lock.json"),
                    "expected_reserved_ceiling_bytes": common.GPU_RESERVED_LIMIT_BYTES,
                    "quiet_window_seconds": 30,
                    "poll_interval_seconds": 5,
                },
                "authorization_sha256": "f" * 64,
                "valid_from_utc_unix_seconds": 100,
                "valid_until_utc_unix_seconds": 200,
                "output_root": str(output_root),
            }
            before = set(sys.modules)
            output_root.mkdir(parents=True)
            lease = gpu.make_gpu_lease(authorization, "parity", output_root)
            self.assertEqual(
                lease.receipt_path,
                (output_root / "gpu-lease-release-receipt-v01.json").resolve(),
            )
            self.assertFalse(lease.acquired)
            self.assertFalse((root / "cuda0.lock.json").exists())
            self.assertFalse(lease.receipt_path.exists())
            self.assertFalse(({"torch", "transformers"} & set(sys.modules)) - before)

    def test_make_gpu_lease_rejects_relative_stage_output_without_lock(self) -> None:
        authorization = {
            "gpu_lease_required_before_model_contact": True,
            "gpu_lease": {
                "lock_path": "C:/temporary/cuda0.lock.json",
                "expected_reserved_ceiling_bytes": common.GPU_RESERVED_LIMIT_BYTES,
                "quiet_window_seconds": 30,
                "poll_interval_seconds": 5,
            },
            "authorization_sha256": "f" * 64,
            "valid_from_utc_unix_seconds": 100,
            "valid_until_utc_unix_seconds": 200,
        }
        before = set(sys.modules)
        with patch.object(gpu, "GpuLease") as lease_constructor:
            with self.assertRaises(gpu.E4RunnerError):
                gpu.make_gpu_lease(authorization, "parity", Path("relative/output"))
            lease_constructor.assert_not_called()
        self.assertFalse(({"torch", "transformers"} & set(sys.modules)) - before)

    def test_gpu_allocator_and_process_ram_limits_are_separate(self) -> None:
        within = {
            "allocated_peak_since_reset_bytes": common.GPU_RESERVED_LIMIT_BYTES,
            "reserved_peak_since_reset_bytes": common.GPU_RESERVED_LIMIT_BYTES,
        }
        gpu.verify_gpu_limits(within, common.HOST_RAM_LIMIT_BYTES)
        with self.assertRaises(gpu.E4RunnerError):
            gpu.verify_gpu_limits({**within, "reserved_peak_since_reset_bytes": common.GPU_RESERVED_LIMIT_BYTES + 1}, 0)
        with self.assertRaises(gpu.E4RunnerError):
            gpu.verify_gpu_limits(within, common.HOST_RAM_LIMIT_BYTES + 1)

    def test_lease_waits_for_attributed_process_and_writes_release_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tick = [0.0]
            snapshots = [
                [{"pid": 4242, "executable": "python.exe", "script": "other_run.py"}],
                [], [], [],
            ]
            snapshot_count = [0]

            def processes() -> list[dict[str, object]]:
                index = min(snapshot_count[0], len(snapshots) - 1)
                snapshot_count[0] += 1
                return snapshots[index]

            lease = gpu.GpuLease(
                lock_path=root / "cuda0.lock.json",
                receipt_path=root / "release.json",
                experiment_id="synthetic/e4-0",
                authorization_sha256="d" * 64,
                authorized_interval={"valid_from_utc_unix_seconds": 10, "valid_until_utc_unix_seconds": 20},
                expected_reserved_ceiling_bytes=common.GPU_RESERVED_LIMIT_BYTES,
                quiet_window_seconds=30,
                poll_interval_seconds=5,
                process_snapshot=processes,
                device_snapshot=lambda: {
                    "diagnostic_only": True, "total_gpu_memory_claimed": False,
                },
                process_alive=lambda _pid: True,
                sleep=lambda seconds: tick.__setitem__(0, tick[0] + seconds),
                monotonic=lambda: tick[0],
                utcnow=lambda: datetime(2026, 9, 26, tzinfo=timezone.utc),
            )
            lease.acquire()
            self.assertTrue(lease.acquired)
            self.assertTrue(any(item["reason"] == "cuda0_compute_process_present" for item in lease.wait_observations))
            receipt = lease.release({"process_peak_working_set_bytes": 123}, "SYNTHETIC_PASS")
            self.assertFalse(lease.acquired)
            self.assertEqual(receipt["terminal_status"], "SYNTHETIC_PASS")
            self.assertFalse(receipt["total_gpu_memory_claimed"])
            self.assertTrue((root / "release.json").is_file())

    def test_lease_ignores_c_plus_g_but_rechecks_after_quiet_window_race(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tick = [0.0]
            c_plus_g = [{"pid": 584, "nvidia_smi_process_type": "C+G", "lease_blocking": False}]
            type_c = [{"pid": 4242, "executable": "python.exe", "script": "other_run.py",
                       "nvidia_smi_process_type": "C", "lease_blocking": True}]
            snapshots = [c_plus_g, c_plus_g, type_c, [], [], []]
            index = [0]

            def processes() -> list[dict[str, object]]:
                value = snapshots[min(index[0], len(snapshots) - 1)]
                index[0] += 1
                return value

            lease = gpu.GpuLease(
                lock_path=root / "cuda0.lock.json", receipt_path=root / "release.json",
                experiment_id="synthetic/e4-0", authorization_sha256="a" * 64,
                authorized_interval={"valid_from_utc_unix_seconds": 10, "valid_until_utc_unix_seconds": 20},
                expected_reserved_ceiling_bytes=common.GPU_RESERVED_LIMIT_BYTES,
                quiet_window_seconds=30, poll_interval_seconds=5,
                process_snapshot=processes,
                device_snapshot=lambda: {"diagnostic_only": True, "total_gpu_memory_claimed": False},
                process_identity=lambda _pid: {"executable": "python.exe", "script": "other_run.py"},
                process_alive=lambda _pid: True,
                sleep=lambda seconds: tick.__setitem__(0, tick[0] + seconds),
                monotonic=lambda: tick[0],
                utcnow=lambda: datetime(2026, 9, 26, tzinfo=timezone.utc),
            )
            lease.acquire()
            self.assertTrue(lease.acquired)
            self.assertGreaterEqual(index[0], 6)
            reasons = [row["reason"] for row in lease.wait_observations]
            self.assertIn("first_empty_cuda0_compute_snapshot", reasons)
            self.assertIn("cuda0_process_appeared_during_lease_acquisition", reasons)
            observed = [process for row in lease.wait_observations
                        if row["reason"] == "nvidia_smi_pmon_process_snapshot"
                        for process in row["cuda0_compute_processes"]]
            self.assertTrue(any(process.get("nvidia_smi_process_type") == "C+G" for process in observed))
            lease.release({"synthetic": True}, "SYNTHETIC_PASS")

    def test_active_lock_with_reused_pid_or_wrong_script_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lock = root / "cuda0.lock.json"
            lock.write_text(json.dumps({
                "owner": {"pid": 73, "executable": "python.exe", "script": "owner.py"},
            }), encoding="utf-8")
            now = [0.0]
            lease = gpu.GpuLease(
                lock_path=lock,
                receipt_path=root / "release.json",
                experiment_id="synthetic/e4-0",
                authorization_sha256="e" * 64,
                authorized_interval={"valid_from_utc_unix_seconds": 10, "valid_until_utc_unix_seconds": 20},
                expected_reserved_ceiling_bytes=common.GPU_RESERVED_LIMIT_BYTES,
                quiet_window_seconds=30,
                poll_interval_seconds=1,
                process_snapshot=lambda: [],
                device_snapshot=lambda: {"diagnostic_only": True, "total_gpu_memory_claimed": False},
                process_identity=lambda _pid: {"executable": "python.exe", "script": "different.py"},
                process_alive=lambda _pid: True,
                sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
                monotonic=lambda: now[0],
                utcnow=lambda: datetime(2026, 9, 26, tzinfo=timezone.utc),
            )
            with self.assertRaises(gpu.E4RunnerError):
                lease.acquire()
            self.assertTrue(lock.exists())
            self.assertFalse(lease.acquired)


if __name__ == "__main__":
    unittest.main()
