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

import e4_gpu_lease_v01 as gpu
import e4_runner_artifacts_v01 as artifacts
import e4_runner_common_v01 as common
import e4_runner_modes_v01 as modes


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
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            historical = {
                "e0_v10_root_sha256": common.E0_ROOT,
                "e1_v04_root_sha256": common.E1_ROOT,
                "e2_v07_root_sha256": common.E2_ROOT,
                "e3_v02_bundle_root_sha256": common.E3_BUNDLE_ROOT,
                "e4_population_root_sha256": "1" * 64,
                "e4_population_audit_root_sha256": "2" * 64,
            }
            contract_path, seal_path, audit_path = root / "contract.json", root / "seal.json", root / "audit.json"
            contract_path.write_text(json.dumps({
                "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V05",
                "status": "SEALED",
                "predecessors": {key: historical[key] for key in (
                    "e0_v10_root_sha256", "e1_v04_root_sha256", "e2_v07_root_sha256", "e3_v02_bundle_root_sha256",
                )},
            }), encoding="utf-8")
            contract_sha = common.sha256_file(contract_path)[0]
            seal_root = "f" * 64
            seal_path.write_text(json.dumps({"root_sha256": seal_root, "entries": [{"sha256": contract_sha}]}), encoding="utf-8")
            audit_path.write_text(json.dumps({"status": "PASS", "e4_0_contract_root_sha256": seal_root}), encoding="utf-8")
            scopes = {key: False for key in (
                "population_generation", "tokenizer_contact", "model_contact", "feature_extraction",
                "evaluation_label_opening", "scoring", "fitting", "e4_a",
                "heldout_template_label_opening", "joint_template_label_opening",
            )}
            scopes["tokenizer_contact"] = True
            auth = {
                "schema": "FAS_E4_0_STAGE_AUTH_V01",
                "authorization_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_STAGE_AUTHORIZATION_V01",
                "status": "AUTHORIZED",
                "stage": "PARITY_PANEL_MATERIALIZATION",
                "contract_sha256": contract_sha,
                "contract_seal_manifest_sha256": common.sha256_file(seal_path)[0],
                "contract_seal_root_sha256": seal_root,
                "exact_predecessor_roots": historical,
                "output_root": str(root.resolve()),
                "scope": scopes,
                "authorized_by": "ACTIVE_USER_REQUEST",
                "issued_utc_unix_seconds": 1_000,
                "valid_from_utc_unix_seconds": 1_001,
                "valid_until_utc_unix_seconds": 2_000,
                "artifacts": {
                    "e4_contract": {"path": str(contract_path), "sha256": contract_sha, "bytes": contract_path.stat().st_size},
                    "e4_contract_seal_manifest": {"path": str(seal_path), "sha256": common.sha256_file(seal_path)[0], "bytes": seal_path.stat().st_size},
                    "e4_contract_audit": {"path": str(audit_path), "sha256": common.sha256_file(audit_path)[0], "bytes": audit_path.stat().st_size},
                },
            }
            verified = common.validate_stage_authorization(
                auth, "materialize-parity-panel", datetime.fromtimestamp(1_500, tz=timezone.utc),
            )
            self.assertEqual(verified["root_sha256"], seal_root)
            auth["scope"]["model_contact"] = True
            with self.assertRaises(common.E4RunnerError):
                common.validate_stage_authorization(
                    auth, "materialize-parity-panel", datetime.fromtimestamp(1_500, tz=timezone.utc),
                )

    def test_invalid_stage_auth_fails_before_output_creation_or_cuda_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "must-not-exist"
            before = set(sys.modules)
            with self.assertRaises(common.E4RunnerError):
                modes.run_online_mode({"schema": "wrong", "output_root": str(output)}, "parity")
            self.assertFalse(output.exists())
            self.assertFalse(({"torch", "transformers"} & set(sys.modules)) - before)

    def test_feature_extraction_function_has_no_prediction_or_label_join_call(self) -> None:
        source_path = SCRIPTS / "e4_runner_modes_v01.py"
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
    def test_gpu_allocator_and_process_ram_limits_are_separate(self) -> None:
        within = {
            "allocated_peak_since_reset_bytes": common.GPU_RESERVED_LIMIT_BYTES,
            "reserved_peak_since_reset_bytes": common.GPU_RESERVED_LIMIT_BYTES,
        }
        gpu.verify_gpu_limits(within, common.HOST_RAM_LIMIT_BYTES)
        with self.assertRaises(common.E4RunnerError):
            gpu.verify_gpu_limits({**within, "reserved_peak_since_reset_bytes": common.GPU_RESERVED_LIMIT_BYTES + 1}, 0)
        with self.assertRaises(common.E4RunnerError):
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
            with self.assertRaises(common.E4RunnerError):
                lease.acquire()
            self.assertTrue(lock.exists())
            self.assertFalse(lease.acquired)


if __name__ == "__main__":
    unittest.main()
