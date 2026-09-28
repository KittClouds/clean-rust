from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_features_v02.py"
SPEC = importlib.util.spec_from_file_location("extract_features_v02", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
E2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E2)


class FakeCuda:
    def __init__(self, values: dict[str, int]) -> None:
        self.values = values
        self.synchronized = False

    def synchronize(self, _device: object) -> None:
        self.synchronized = True

    def memory_allocated(self, _device: object) -> int:
        return self.values["allocated_current"]

    def memory_reserved(self, _device: object) -> int:
        return self.values["reserved_current"]

    def max_memory_allocated(self, _device: object) -> int:
        return self.values["allocated_peak"]

    def max_memory_reserved(self, _device: object) -> int:
        return self.values["reserved_peak"]


class E2ResourceV02Tests(unittest.TestCase):
    def test_snapshot_uses_process_allocator_counters_and_synchronizes(self) -> None:
        cuda = FakeCuda({
            "allocated_current": 100,
            "reserved_current": 200,
            "allocated_peak": 150,
            "reserved_peak": 250,
        })
        torch = SimpleNamespace(cuda=cuda)

        snapshot = E2.gpu_allocator_snapshot(torch, "cuda:0", "test")

        self.assertTrue(cuda.synchronized)
        self.assertEqual(snapshot["process_id"], __import__("os").getpid())
        self.assertEqual(snapshot["reserved_peak_since_reset_bytes"], 250)
        E2.enforce_gpu_process_limit(snapshot)

    def test_process_gpu_limit_fails_closed_above_10_gib(self) -> None:
        snapshot = {
            "allocated_peak_since_reset_bytes": 10 * 1024**3,
            "reserved_peak_since_reset_bytes": 10 * 1024**3 + 1,
        }
        with self.assertRaisesRegex(RuntimeError, "exceeded"):
            E2.enforce_gpu_process_limit(snapshot)

    def test_allocator_peak_invariant_fails_closed(self) -> None:
        snapshot = {
            "allocated_peak_since_reset_bytes": 201,
            "reserved_peak_since_reset_bytes": 200,
        }
        with self.assertRaisesRegex(RuntimeError, "inconsistent"):
            E2.enforce_gpu_process_limit(snapshot)

    def test_allocator_baselines_must_be_zero_before_and_after_reset(self) -> None:
        clean = {
            "allocated_current_bytes": 0,
            "reserved_current_bytes": 0,
            "allocated_peak_since_reset_bytes": 0,
            "reserved_peak_since_reset_bytes": 0,
        }
        self.assertTrue(E2.allocator_snapshot_is_zero(clean))
        for key in clean:
            dirty = {**clean, key: 1}
            self.assertFalse(E2.allocator_snapshot_is_zero(dirty), key)

    def test_dirty_allocator_receipt_names_narrow_gpu_scope_and_stops_before_contact(self) -> None:
        clean = {
            "phase": "after_cuda_init_before_peak_reset",
            "process_id": 123,
            "allocated_current_bytes": 0,
            "reserved_current_bytes": 4096,
            "allocated_peak_since_reset_bytes": 0,
            "reserved_peak_since_reset_bytes": 4096,
        }
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary)
            E2.write_allocator_preflight_failure(output_root, {}, clean, None, "dirty test baseline")
            receipt = json.loads((output_root / "allocator-preflight-stop-v02.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["scope_claim_exact"], E2.GPU_MEASUREMENT_CLAIM)
        self.assertFalse(receipt["total_gpu_memory_claimed"])
        self.assertFalse(receipt["model_contact_performed"])
        self.assertFalse(receipt["tokenizer_contact_performed"])
        self.assertEqual(receipt["pre_reset_allocator_counters"]["reserved_current_bytes"], 4096)

    def test_cache_equivalence_requires_pinned_reference_and_exact_output_hash(self) -> None:
        reference_hash = E2.EXPECTED_E2_V01_CACHE_SHA256
        reference_bytes = E2.EXPECTED_E2_V01_CACHE_BYTES
        same = E2.exact_cache_equivalence(
            reference_hash,
            reference_bytes,
            reference_hash,
            reference_bytes,
        )
        self.assertTrue(same["passed"])
        self.assertTrue(same["sha256_equal"])
        self.assertTrue(same["byte_length_equal"])

        changed = E2.exact_cache_equivalence(
            reference_hash,
            reference_bytes,
            "0" * 64,
            reference_bytes,
        )
        self.assertFalse(changed["passed"])
        self.assertFalse(changed["sha256_equal"])

        wrong_reference = E2.exact_cache_equivalence(
            "1" * 64,
            reference_bytes,
            "1" * 64,
            reference_bytes,
        )
        self.assertFalse(wrong_reference["reference_matches_pinned_v01_cache"])
        self.assertFalse(wrong_reference["passed"])

        wrong_length = E2.exact_cache_equivalence(
            reference_hash,
            reference_bytes,
            reference_hash,
            reference_bytes - 4,
        )
        self.assertFalse(wrong_length["passed"])
        self.assertFalse(wrong_length["byte_length_equal"])

    def test_e2_draft_status_cannot_pass_the_pre_model_protocol_gate(self) -> None:
        draft = {
            "protocol_id": "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V02",
            "status": "E2_V02_DRAFT_NOT_AUTHORIZED",
        }
        with self.assertRaisesRegex(RuntimeError, "still a draft"):
            E2.verify_frozen_e2_protocol(draft)
        frozen = {
            **draft,
            "status": "E2_V02_FROZEN_NOT_AUTHORIZED",
            "representation_equivalence": {
                "required": True,
                "reference_cache_path": str(E2.EXPECTED_E2_V01_CACHE_PATH),
                "reference_cache_sha256": E2.EXPECTED_E2_V01_CACHE_SHA256,
                "reference_cache_bytes": E2.EXPECTED_E2_V01_CACHE_BYTES,
                "gate": "exact SHA-256 equality and exact byte length equality",
            },
        }
        E2.verify_frozen_e2_protocol(frozen)

    def test_wait_receipt_must_prove_exact_identity_and_stable_absence(self) -> None:
        identity = dict(E2.EXPECTED_S12_PROCESS)
        receipt = {
            "status": "WAIT_COMPLETE_STABLE_ABSENCE",
            "model_contact_performed_by_waiter": False,
            "bound_process": identity,
            "exact_bound_identity_observed_during_wait": identity,
            "matching_script_processes_at_final_sample": [],
            "stable_absent_samples": 2,
            "sample_interval_seconds": 30,
        }
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            path = temporary_root / E2.EXPECTED_WAIT_RECEIPT_RELATIVE_PATH
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(receipt), encoding="utf-8")
            authorization = {
                "repo_root": str(temporary_root),
                "concurrent_run_wait_receipt_path": str(path),
                "concurrent_run_wait_receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            self.assertEqual(E2.verify_wait_receipt(authorization)["status"], "WAIT_COMPLETE_STABLE_ABSENCE")

            receipt["matching_script_processes_at_final_sample"] = [{"pid": 34332}]
            path.write_text(json.dumps(receipt), encoding="utf-8")
            authorization["concurrent_run_wait_receipt_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(RuntimeError, "remained"):
                E2.verify_wait_receipt(authorization)


if __name__ == "__main__":
    unittest.main()
