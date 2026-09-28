from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import scorer


def endpoint_fixture(*, failing_endpoint: str | None = None) -> dict[str, scorer.EndpointData]:
    class_counts = (32, 32, 2, 3, 3, 3, 3, 3)
    result: dict[str, scorer.EndpointData] = {}
    for endpoint, class_count in zip(scorer.ENDPOINT_ORDER, class_counts, strict=True):
        labels: list[int] = []
        predictions: list[int] = []
        quartets: list[str] = []
        strata: list[int] = []
        for label in range(class_count):
            for repeat in range(3):
                quartet = f"{endpoint}-c{label}-q{repeat}"
                for _variant in scorer.QUARTET_VARIANTS:
                    labels.append(label)
                    predictions.append(
                        (label + 1) % class_count
                        if endpoint == failing_endpoint
                        else label
                    )
                    quartets.append(quartet)
                    strata.append(label)
        result[endpoint] = scorer.EndpointData(
            labels=np.asarray(labels, dtype=np.int64),
            predictions=np.asarray(predictions, dtype=np.int64),
            quartet_ids=tuple(quartets),
            quartet_strata=tuple(strata),
            class_count=class_count,
        )
    return result


def fast_score(data: dict[str, scorer.EndpointData]) -> dict:
    return scorer._score_endpoint_set(
        data,
        replicates=128,
        seed=scorer.BOOTSTRAP_SEED,
        chunk_replicates=scorer.BOOTSTRAP_CHUNK_REPLICATES,
        alpha=scorer.BOOTSTRAP_ALPHA,
        minimum_rows_per_class=8,
        performance_floor=scorer.PERFORMANCE_FLOOR,
    )


def auth_fixture() -> tuple[dict, scorer.ScoringAuthIdentity]:
    roots = {key: f"root-{index}" for index, key in enumerate(scorer.SCORING_PREDECESSOR_ROOT_KEYS)}
    expected = scorer.ScoringAuthIdentity(
        contract_sha256="contract-hash",
        contract_seal_manifest_sha256="manifest-hash",
        contract_seal_root_sha256="contract-root",
        exact_predecessor_roots=roots,
        output_root=r"C:\\synthetic\\e4-score",
    )
    auth = {
        "schema": scorer.AUTH_SCHEMA,
        "authorization_id": "synthetic-stage-auth",
        "status": "AUTHORIZED",
        "stage": "FRESH_SCORING",
        "contract_sha256": expected.contract_sha256,
        "contract_seal_manifest_sha256": expected.contract_seal_manifest_sha256,
        "contract_seal_root_sha256": expected.contract_seal_root_sha256,
        "exact_predecessor_roots": roots,
        "output_root": expected.output_root,
        "scope": dict(scorer.SCORING_AUTH_SCOPE),
        "authorized_by": "ACTIVE_USER_REQUEST",
        "issued_utc_unix_seconds": 100,
        "valid_from_utc_unix_seconds": 110,
        "valid_until_utc_unix_seconds": 200,
    }
    return auth, expected


class MetricTests(unittest.TestCase):
    def test_frozen_bootstrap_and_endpoint_constants(self) -> None:
        self.assertEqual(scorer.ENDPOINT_ORDER, (
            "context_identity", "entity_identity", "relation", "observed_state",
            "exact_target_in_domain", "exact_target_context_novel",
            "exact_target_entity_novel", "exact_target_both_novel",
        ))
        self.assertEqual(scorer.BOOTSTRAP_REPLICATES, 10_000)
        self.assertEqual(scorer.BOOTSTRAP_SEED, 2_026_092_604)
        self.assertEqual(scorer.BOOTSTRAP_CHUNK_REPLICATES, 64)
        self.assertEqual(scorer.BOOTSTRAP_ALPHA, 0.00625)

    def test_metric_and_serialization_cores_are_byte_identical_to_v03(self) -> None:
        current = Path(__file__).resolve().parent
        prior = current.parent / "e4_fresh_scorer_v03"
        for name in ("scorer.py", "output_artifacts.py"):
            with self.subTest(source=name):
                self.assertEqual((current / name).read_bytes(), (prior / name).read_bytes())
        self.assertEqual(scorer.MINIMUM_ROWS_PER_CLASS, 200)
        self.assertEqual(scorer.PERFORMANCE_FLOOR, 0.90)

    def test_balanced_accuracy_and_support_match_expected_values(self) -> None:
        summary = scorer.metric_summary(
            np.asarray([0, 0, 1, 1], dtype=np.int64),
            np.asarray([0, 1, 1, 1], dtype=np.int64),
            class_count=2,
        )
        self.assertEqual(summary["class_support"], [2, 2])
        self.assertEqual(summary["confusion_matrix"], [[1, 1], [0, 2]])
        self.assertAlmostEqual(summary["balanced_accuracy"], 0.75)

    def test_bootstrap_is_deterministic_and_uses_linear_tail_quantile(self) -> None:
        truth = np.asarray([0, 0, 1, 1] * 8, dtype=np.int64)
        pred = truth.copy()
        pred[1::4] = 1 - pred[1::4]
        quartets = tuple(f"q{index}" for index in range(8) for _ in range(4))
        strata = tuple(index % 2 for index in range(8) for _ in range(4))
        args = (truth, pred, quartets, strata, 2)
        first = scorer.whole_quartet_bootstrap_lower_bound(
            *args,
            np.random.Generator(np.random.PCG64(scorer.BOOTSTRAP_SEED)),
            replicates=257,
        )
        second = scorer.whole_quartet_bootstrap_lower_bound(
            *args,
            np.random.Generator(np.random.PCG64(scorer.BOOTSTRAP_SEED)),
            replicates=257,
        )
        self.assertEqual(first[0], second[0])
        np.testing.assert_array_equal(first[1], second[1])
        self.assertEqual(first[2], {"0": 4, "1": 4})
        self.assertEqual(len(first[1]), 257)


class BundleGateTests(unittest.TestCase):
    def test_perfect_synthetic_bundle_passes_all_eight_endpoints(self) -> None:
        result = fast_score(endpoint_fixture())
        self.assertEqual(tuple(result["endpoints"]), scorer.ENDPOINT_ORDER)
        self.assertEqual(result["passed_endpoints"], list(scorer.ENDPOINT_ORDER))
        self.assertEqual(result["failed_endpoints"], [])
        self.assertTrue(result["bundle_qualified"])
        self.assertEqual(
            result["terminal_disposition"],
            "PASS_SIMULTANEOUS_FRESH_BUNDLE_QUALIFICATION",
        )
        for endpoint in scorer.ENDPOINT_ORDER:
            summary = result["endpoints"][endpoint]
            self.assertEqual(summary["balanced_accuracy"], 1.0)
            self.assertEqual(summary["bootstrap_lower_bound"], 1.0)
            self.assertEqual(summary["bootstrap_lower_bound_alpha"], 0.00625)

    def test_support_failure_is_recorded_and_fails_bundle(self) -> None:
        data = endpoint_fixture()
        data["context_identity"] = scorer.EndpointData(
            labels=np.asarray([0, 0, 0], dtype=np.int64),
            predictions=np.asarray([0, 0, 0], dtype=np.int64),
            quartet_ids=("short-q",) * 3,
            quartet_strata=(0,) * 3,
            class_count=32,
        )
        result = fast_score(data)
        failed = result["endpoints"]["context_identity"]
        self.assertEqual(failed["status"], "FAIL_SUPPORT")
        self.assertFalse(failed["support_gate_pass"])
        self.assertIsNone(failed["balanced_accuracy"])
        self.assertIsNone(failed["bootstrap_lower_bound"])
        self.assertFalse(result["bundle_qualified"])
        self.assertIn("context_identity", result["failed_endpoints"])

    def test_single_endpoint_failure_cannot_be_hidden_by_bundle_average(self) -> None:
        result = fast_score(endpoint_fixture(failing_endpoint="relation"))
        self.assertEqual(result["passed_endpoints"], [
            endpoint for endpoint in scorer.ENDPOINT_ORDER if endpoint != "relation"
        ])
        self.assertEqual(result["failed_endpoints"], ["relation"])
        self.assertEqual(result["endpoints"]["relation"]["balanced_accuracy"], 0.0)
        self.assertEqual(result["endpoints"]["relation"]["bootstrap_lower_bound"], 0.0)
        self.assertFalse(result["bundle_qualified"])
        self.assertEqual(result["terminal_disposition"], "FAIL_FRESH_QUALIFICATION")


class AuthorizationAndCustodyTests(unittest.TestCase):
    def test_synthetic_suite_keeps_cuda_uninitialized(self) -> None:
        self.assertFalse(scorer.torch.cuda.is_initialized())

    def test_invalid_auth_fails_before_synthetic_label_file_is_opened(self) -> None:
        auth, expected = auth_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic-labels.jsonl"
            payload = b'{"row_id":"r0"}\n'
            path.write_bytes(payload)
            reader = scorer.OneShotPrimaryLabelReader(
                path,
                expected_sha256=hashlib.sha256(payload).hexdigest(),
                expected_bytes=len(payload),
                expected_rows=1,
            )
            invalid = dict(auth)
            invalid["scope"] = {**auth["scope"], "heldout_template_label_opening": True}
            with self.assertRaisesRegex(RuntimeError, "scope is broader"):
                reader.read_once(invalid, expected, now_unix_seconds=150)
            self.assertFalse(reader.attempted)

    def test_authorized_reader_opens_synthetic_labels_once_and_verifies_identity(self) -> None:
        auth, expected = auth_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic-labels.jsonl"
            payload = b'{"row_id":"r0"}\n{"row_id":"r1"}\n'
            path.write_bytes(payload)
            reader = scorer.OneShotPrimaryLabelReader(
                path,
                expected_sha256=hashlib.sha256(payload).hexdigest(),
                expected_bytes=len(payload),
                expected_rows=2,
            )
            rows, receipt = reader.read_once(auth, expected, now_unix_seconds=150)
            self.assertEqual(rows, [{"row_id": "r0"}, {"row_id": "r1"}])
            self.assertEqual(receipt["label_file_open_count"], 1)
            self.assertEqual(receipt["semantic_label_open_count"], 1)
            self.assertEqual(receipt["label_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertFalse(receipt["heldout_template_labels_opened"])
            with self.assertRaisesRegex(RuntimeError, "second open refused"):
                reader.read_once(auth, expected, now_unix_seconds=150)

    def test_feature_inference_excludes_escrow_rows(self) -> None:
        manifest: list[dict] = []
        for surface, partition, prefix in (
            ("PRIMARY_SEEN", "PRIMARY_TERMINAL", "p"),
            ("HELDOUT_TEMPLATE", "TEMPLATE_ESCROW", "h"),
        ):
            for variant in scorer.QUARTET_VARIANTS:
                index = len(manifest)
                manifest.append({
                    "row_index": index,
                    "row_id": f"{prefix}-{variant}",
                    "quartet_id": prefix,
                    "variant_id": variant,
                    "surface_id": surface,
                    "truth_partition": partition,
                })
        heads = {}
        for task, (_field, classes, _scope) in scorer.TASKS.items():
            heads[task] = scorer.LinearHead(
                task=task,
                class_count=classes,
                mean=np.zeros(scorer.DIMENSION, dtype=np.float32),
                scale=np.ones(scorer.DIMENSION, dtype=np.float32),
                weight=np.zeros((classes, scorer.DIMENSION), dtype=np.float32),
                bias=np.zeros(classes, dtype=np.float32),
            )
        features = np.zeros((len(manifest), scorer.DIMENSION), dtype="<f4")
        primary, predictions = scorer.predict_primary_rows(features, manifest, heads, batch_rows=2)
        self.assertEqual([row["row_id"] for row in primary], ["p-A", "p-C", "p-E", "p-P"])
        self.assertEqual(set(predictions), set(scorer.TASKS))
        self.assertTrue(all(len(values) == 4 for values in predictions.values()))


if __name__ == "__main__":
    unittest.main()
