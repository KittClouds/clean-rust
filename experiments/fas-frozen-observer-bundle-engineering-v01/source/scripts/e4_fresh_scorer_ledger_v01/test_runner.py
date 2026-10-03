from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import ledger_adapter as adapter
import run_scoring as runner
from test_adapter import jsonl, make_delivery, make_invocation, synthetic_rows


class CandidateRunnerTests(unittest.TestCase):
    def test_fixed_runtime_handoff_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            attempt = Path(temp).resolve()
            ledger_inputs = attempt / "ledger-inputs"
            ledger_inputs.mkdir()
            invocation_path = ledger_inputs / "scoring-invocation-v01.json"
            delivery_path = ledger_inputs / "panel-delivery-v01.json"
            panel_path = ledger_inputs / "primary-panel-e4-v01.jsonl"
            for path in (invocation_path, delivery_path, panel_path):
                path.write_bytes(b"synthetic")
            invocation = make_invocation(attempt, "synthetic-event")
            resolved = runner.validate_runtime_handoff_paths(
                invocation=invocation,
                invocation_path=invocation_path,
                delivery_path=delivery_path,
                panel_path=panel_path,
            )
            self.assertEqual(resolved, (invocation_path, delivery_path, panel_path))
            with tempfile.NamedTemporaryFile() as external:
                with self.assertRaises(runner.RunnerError):
                    runner.validate_runtime_handoff_paths(
                        invocation=invocation,
                        invocation_path=invocation_path,
                        delivery_path=Path(external.name),
                        panel_path=panel_path,
                    )

    def test_synthetic_stage_writes_and_seals_declared_outputs(self):
        row_label_pairs, predicted = synthetic_rows()
        manifest = [row for row, _ in row_label_pairs]
        labels = [label for _, label in row_label_pairs]
        label_bytes = jsonl(labels)
        manifest_bytes = jsonl(manifest)
        predictions = {
            key: np.asarray(values, dtype=np.int64)
            for key, values in predicted.items()
        }

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            attempt_root = root / "attempt"
            attempt_root.mkdir()
            input_dir = attempt_root / "ledger-inputs"
            input_dir.mkdir()
            manifest_path = root / "synthetic-row-manifest.jsonl"
            manifest_path.write_bytes(manifest_bytes)
            invocation = make_invocation(attempt_root, "synthetic-stage-open-event")
            delivery = make_delivery(
                label_bytes, attempt_root, "synthetic-stage-open-event", len(labels)
            )
            invocation_path = input_dir / "scoring-invocation-v01.json"
            delivery_path = input_dir / "panel-delivery-v01.json"
            invocation_path.write_text(json.dumps(invocation), encoding="utf-8")
            delivery_path.write_text(json.dumps(delivery), encoding="utf-8")
            panel_path = attempt_root / adapter.PANEL_DELIVERY_RELATIVE_PATH
            output_root = root / "fresh-output"

            with (
                mock.patch.object(adapter, "PRIMARY_LABEL_SOURCE_BYTES", len(label_bytes)),
                mock.patch.object(
                    adapter, "PRIMARY_LABEL_SOURCE_SHA256",
                    hashlib.sha256(label_bytes).hexdigest(),
                ),
                mock.patch.object(adapter, "PRIMARY_LABEL_ROWS", len(labels)),
                mock.patch.object(
                    adapter, "POPULATION_ROW_MANIFEST_BYTES", len(manifest_bytes)
                ),
                mock.patch.object(
                    adapter, "POPULATION_ROW_MANIFEST_SHA256",
                    hashlib.sha256(manifest_bytes).hexdigest(),
                ),
                mock.patch.object(adapter, "FEATURE_CACHE_ROWS", len(manifest)),
                mock.patch.object(
                    runner, "preflight_disk",
                    return_value={
                        "volume_total_bytes": 10_000_000_000,
                        "free_before_bytes": 9_000_000_000,
                        "projected_scoring_bytes": 1_877_705_408,
                        "reserve_bytes": 1_000_000_000,
                        "required_free_bytes": 2_877_705_408,
                    },
                ),
                mock.patch.object(
                    runner, "process_peak_memory",
                    return_value={
                        "peak_working_set_bytes": 128 * 1024 * 1024,
                        "peak_pagefile_usage_bytes": 192 * 1024 * 1024,
                        "private_usage_at_receipt_bytes": 96 * 1024 * 1024,
                    },
                ),
                mock.patch.object(
                    adapter, "prepare_primary_predictions",
                    return_value=(manifest, predictions, manifest),
                ) as predict,
            ):
                result = runner.execute_scoring(
                    invocation=invocation,
                    delivery=delivery,
                    feature_cache_path=root / "unused-feature-cache.f32le",
                    row_manifest_path=manifest_path,
                    e3_head_root=root / "unused-e3-heads",
                    staged_panel_file=panel_path,
                    output_root=output_root,
                )

            predict.assert_called_once()
            self.assertEqual(result["status"], "SCORING_EXECUTION_COMPLETE")
            self.assertEqual(
                result["terminal_disposition"],
                "PASS_SIMULTANEOUS_FRESH_BUNDLE_QUALIFICATION",
            )
            self.assertEqual(set(result["outputs"]), set(runner.OUTPUT_NAMES))
            self.assertTrue(all(size >= 0 for size in result["outputs"].values()))
            self.assertFalse((output_root / "score" / "score-stop-v01.json").exists())

            score_dir = output_root / "score"
            metrics = json.loads((score_dir / "metrics-v01.json").read_text(encoding="utf-8"))
            terminal = json.loads(
                (score_dir / "terminal-receipt-v01.json").read_text(encoding="utf-8")
            )
            label_receipt = json.loads(
                (score_dir / "label-open-receipt-v01.json").read_text(encoding="utf-8")
            )
            seal = json.loads((score_dir / "stage-seal-v01.json").read_text(encoding="utf-8"))
            self.assertTrue(metrics["bundle_qualified"])
            self.assertEqual(len(metrics["endpoints"]), 8)
            self.assertTrue(all(item["gate_pass"] for item in metrics["endpoints"].values()))
            self.assertEqual(terminal["primary_rows_scored"], len(labels))
            self.assertFalse(terminal["heldout_template_labels_opened"])
            self.assertFalse(terminal["joint_template_labels_opened"])
            self.assertFalse(terminal["resources"]["cuda_initialized"])
            self.assertEqual(label_receipt["scorer_materialized_file_open_count"], 1)
            self.assertEqual(label_receipt["ledger_open_panel_event_count"], 1)
            self.assertEqual(label_receipt["escrow_label_file_open_count"], 0)
            self.assertEqual(seal["entry_count"], 6)
            self.assertNotIn("score/stage-seal-v01.json", {
                entry["path"] for entry in seal["entries"]
            })


if __name__ == "__main__":
    unittest.main()
