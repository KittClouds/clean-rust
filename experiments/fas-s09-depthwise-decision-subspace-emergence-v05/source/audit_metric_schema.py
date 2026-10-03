from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import numpy as np

from linear_core import classification_metrics, configure_determinism, predict_probabilities, standardized_tensor
from run_analysis import verify_condition_metric_reproduction
from s01_common_reference import fit_masks, load_metadata_npz, test_condition_masks
from s09_common import DIMENSION, EVENTS, FEATURE_ROOT, RUN_ROOT, entry_for, read_json, sha256_file, write_json


def main() -> int:
    if (RUN_ROOT / "metric-schema-audit-v04.json").exists():
        raise RuntimeError("metric schema audit already exists; refusing overwrite")
    prior_probe = RUN_ROOT / "history-v03" / "M-terminal-probe-state-v03.npz"
    with np.load(prior_probe, allow_pickle=False) as data:
        prior_state = {key: data[key].copy() for key in data.files}
    with np.load(RUN_ROOT / "inputs" / "S01-3" / "terminal-reference" / "M-probe-state.npz", allow_pickle=False) as data:
        reference_state = {key: data[key].copy() for key in data.files}
    for key in ("classes", "weights", "bias", "scaler_mean", "scaler_scale"):
        if not np.array_equal(prior_state[key], reference_state[key]):
            raise RuntimeError(f"preserved v03 M terminal state differs from sealed S01: {key}")

    metadata = load_metadata_npz(RUN_ROOT / "inputs" / "S01-3" / "event-metadata-v01.npz")
    _, test_mask = fit_masks(metadata, "EXACT_TARGET")
    test_rows = np.flatnonzero(test_mask).astype(np.int64, copy=False)
    test_meta = {name: values[test_mask] for name, values in metadata.items()}
    conditions = test_condition_masks(test_meta, "EXACT_TARGET")
    labels = np.asarray(metadata["target"][test_rows], dtype=np.int64)
    expected_classes = np.asarray([0, 1, 2], dtype=np.int64)
    test_manifest = [json.loads(line)["event_id"].encode("ascii") for line in (RUN_ROOT / "inputs" / "S01-3" / "test-events-v01.jsonl").read_text(encoding="utf-8").splitlines()]
    if not np.array_equal(metadata["event_id"][test_rows], np.asarray(test_manifest, dtype=metadata["event_id"].dtype)):
        raise RuntimeError("test row event order differs from the sealed S01 manifest")

    matrix = np.memmap(FEATURE_ROOT / "layer-16-M.f32le", dtype="<f4", mode="r", shape=(EVENTS, DIMENSION), order="C")
    device = configure_determinism()
    x_test = standardized_tensor(matrix, test_rows, prior_state["scaler_mean"], prior_state["scaler_scale"], device)
    probabilities = predict_probabilities(x_test, prior_state["weights"], prior_state["bias"], batch_rows=16384)
    expected_probabilities = np.load(RUN_ROOT / "inputs" / "S01-3" / "terminal-reference" / "M-probabilities.npy", allow_pickle=False)
    if not np.array_equal(np.asarray(probabilities, dtype="<f4"), expected_probabilities):
        delta = float(np.max(np.abs(np.asarray(probabilities, dtype=np.float64) - expected_probabilities.astype(np.float64))))
        raise RuntimeError(f"preserved v03 M terminal probabilities fail replay: max_abs={delta}")

    calculated: dict[str, Any] = {"ALL_TEST_ROWS": classification_metrics(labels, probabilities, expected_classes)}
    for name, mask in conditions.items():
        calculated[name] = classification_metrics(labels[mask], probabilities[mask], expected_classes)
    metrics = read_json(RUN_ROOT / "inputs" / "S01-3" / "metrics-v01.json")
    rows = [row for row in metrics["metrics"] if row.get("view") == "V0_MEAN_FULL" and row.get("task") == "EXACT_TARGET"]
    if len(rows) != 1:
        raise RuntimeError("sealed S01 M exact-target metric row is ambiguous")
    verify_condition_metric_reproduction(calculated, rows[0]["conditions"])

    seal = read_json(RUN_ROOT / "recovery-feature-cache-seal-v03.json")
    receipt = {
        "audit_id": "FAS_S09_METRIC_SCHEMA_AUDIT_V04",
        "prior_v03_probe_state_exact_to_S01": True,
        "replayed_M_probabilities_exact_to_S01": True,
        "condition_names_exact": True,
        "condition_count": len(conditions),
        "all_computed_condition_metric_fields_exact": True,
        "computed_aggregate_omitted_from_condition_comparison": "ALL_TEST_ROWS",
        "reference_provenance_field_omitted": "interpretation_scope",
        "all_other_fields_compared_by_exact_equality": True,
        "test_rows": int(len(test_rows)),
        "feature_cache_root_sha256": seal["root_sha256"],
        "v03_probe_state_sha256": sha256_file(prior_probe)[0],
        "S01_reference_probability_sha256": sha256_file(RUN_ROOT / "inputs" / "S01-3" / "terminal-reference" / "M-probabilities.npy")[0],
        "S01_metrics_sha256": sha256_file(RUN_ROOT / "inputs" / "S01-3" / "metrics-v01.json")[0],
        "model_loaded": False,
        "probe_fitted": False,
        "fas00_artifacts_read": False,
    }
    write_json(RUN_ROOT / "metric-schema-audit-v04.json", receipt)
    print(f"metric_schema_audit=PASS conditions={len(conditions)} test_rows={len(test_rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
