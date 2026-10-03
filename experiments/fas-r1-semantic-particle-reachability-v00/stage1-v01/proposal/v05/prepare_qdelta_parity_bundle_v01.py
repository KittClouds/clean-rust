#!/usr/bin/env python3
"""Create a train/validation-only input bundle for Rust Q-delta parity."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


PINS = {
    "public_tasks": "bcc15f28b923a0eb0097abddfd6f99c5fcca6e68681354380fd80da07f238c68",
    "support_manifest": "d51c38a233f67e8c9b17a96be52666369d8676a7831567715f07ffcb2204342d",
    "constraint_h": "c9b68b087b2862b037044196be56712da4a678b2e3aa69e7e3081651c9eba2d5",
    "global_h": "0fddb1a8a928dc7a890e3a29603b0618ebf3c674ff85fa34bbbb25e69567283c",
    "feature_rows": "6248dbb9301fe4607189318a1e37378a9598149c083cc7c48b30bd80e2a2dee1",
    "action_labels": "148122457b9f66fc0164b174d4ce6c59377fce8fbb8e758f5cf5e6843ca7c921",
    "python_predictions": "034d162d1a129cbb3dac4c898d54cd37f646128d930b32d04780da2ad421277a",
    "qterminal_checkpoint": "00e1654dbd335b9bd7622b8bb65b983a20335f81f226904cc2c808f934d4838c",
}


def file_record(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(), "bytes": size}


def require_pin(path: Path, name: str) -> dict[str, Any]:
    record = file_record(path)
    if record["sha256"] != PINS[name]:
        raise ValueError(f"{name} SHA-256 differs from the pinned train/validation bytes")
    return record


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error


def prepare(view: Path, features: Path, action_labels: Path, python_predictions: Path,
            qterminal_checkpoint: Path, output: Path) -> dict[str, Any]:
    view = view.resolve(strict=True)
    features = features.resolve(strict=True)
    action_labels = action_labels.resolve(strict=True)
    python_predictions = python_predictions.resolve(strict=True)
    qterminal_checkpoint = qterminal_checkpoint.resolve(strict=True)
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite parity bundle {output}")

    public_tasks = view / "public-tasks-trainval-v05.jsonl"
    support = view / "stress-support-trainval-v05.json"
    view_receipt = view / "trainval-view-receipt-v05-v01.json"
    feature_receipt = features / "frozen-features-trainval-receipt-v05-v01.json"
    feature_files = {
        "constraint_h": features / "constraint_H_trainval.float32.npy",
        "global_h": features / "global_h_trainval.float32.npy",
        "feature_rows": features / "rows_trainval.jsonl",
    }
    action_receipt_path = action_labels.parent / "action-label-receipt-v05-v01.json"
    prediction_receipt_path = python_predictions.parent / "action-delta-diagnostic-receipt-v01.json"
    checkpoint_receipt_path = qterminal_checkpoint.parent / "fit-receipt-v05-v02.json"

    for name, path in [("public_tasks", public_tasks), ("support_manifest", support),
                       *feature_files.items(), ("action_labels", action_labels),
                       ("python_predictions", python_predictions),
                       ("qterminal_checkpoint", qterminal_checkpoint)]:
        require_pin(path, name)

    trainval_receipt = json.loads(view_receipt.read_text(encoding="utf-8"))
    feature_manifest = json.loads(feature_receipt.read_text(encoding="utf-8"))
    action_receipt = json.loads(action_receipt_path.read_text(encoding="utf-8"))
    prediction_receipt = json.loads(prediction_receipt_path.read_text(encoding="utf-8"))
    checkpoint_receipt = json.loads(checkpoint_receipt_path.read_text(encoding="utf-8"))
    if trainval_receipt.get("schema") != "R1_STAGE1_TRAIN_VALIDATION_VIEW_RECEIPT_V05_V01":
        raise ValueError("unexpected V241 train/validation receipt")
    if trainval_receipt.get("qualification_rows_emitted") != 0 or trainval_receipt.get("qualification_targets_generated"):
        raise ValueError("V241 view contains or generated qualification targets")
    if feature_manifest.get("schema") != "R1_STAGE1_FROZEN_FEATURES_TRAINVAL_V05_V01":
        raise ValueError("unexpected V246 feature receipt")
    if feature_manifest.get("qualification_rows_emitted") != 0 or feature_manifest.get("qualification_targets_generated"):
        raise ValueError("V246 features contain or generated qualification targets")
    if action_receipt.get("qualification_rows") != 0 or action_receipt.get("qualification_targets_generated"):
        raise ValueError("V244 action-label receipt includes qualification targets")
    if prediction_receipt.get("qualification_labels_read"):
        raise ValueError("V266 diagnostic read qualification labels")
    if checkpoint_receipt.get("scope", {}).get("qualification_targets_generated"):
        raise ValueError("V258 Q-terminal fit generated qualification targets")
    if checkpoint_receipt.get("scope", {}).get("test_labels_read"):
        raise ValueError("V258 Q-terminal fit read test labels")

    output.mkdir(parents=True)
    bundled_public = output / "public-tasks-trainval.jsonl"
    bundled_support = output / "support-trainval.json"
    bundled_predictions = output / "python-predictions-trainval.jsonl"
    shutil.copyfile(public_tasks, bundled_public)
    shutil.copyfile(support, bundled_support)
    shutil.copyfile(python_predictions, bundled_predictions)
    feature_view = output / "features"
    feature_view.mkdir()
    copied = {}
    for source_key, destination_name in [
        ("constraint_h", "constraint_H.float32.npy"),
        ("global_h", "global_h.float32.npy"),
    ]:
        destination = feature_view / destination_name
        shutil.copyfile(feature_files[source_key], destination)
        copied[destination_name] = file_record(destination)

    row_output = feature_view / "rows.jsonl"
    row_count = 0
    with feature_files["feature_rows"].open("r", encoding="utf-8") as source, row_output.open("x", encoding="utf-8", newline="\n") as target:
        for line_number, line in enumerate(source, 1):
            row = json.loads(line)
            normalized = {key: row[key] for key in ("task_id", "family_id", "task_index", "kind", "row")}
            if row["kind"] == "constraint":
                normalized["clause_index"] = row["clause_index"]
            target.write(json.dumps(normalized, sort_keys=True, separators=(",", ":")) + "\n")
            row_count += 1
    copied["rows.jsonl"] = file_record(row_output)

    extraction_receipt = {
        "schema": "R1_STAGE1_SENSOR_EXTRACTION_V01",
        "status": "R1_SENSOR_EXTRACTION_COMPLETE",
        "input": {
            "sha256": PINS["public_tasks"],
            "support_manifest": {"sha256": PINS["support_manifest"]},
        },
        "output_files": [
            {"path": name, "sha256": item["sha256"], "bytes": item["bytes"]}
            for name, item in sorted(copied.items())
        ],
    }
    (feature_view / "receipt.json").write_text(
        json.dumps(extraction_receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    states_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for row in read_jsonl(action_labels):
        split = row.get("family_split")
        if split not in ("train", "validation"):
            raise ValueError("action state has an out-of-scope split")
        key = (row["task_id"], int(row["state_index"]))
        state = {"task_id": key[0], "state_index": key[1], "split": split,
                 "assignment": row["assignment"]}
        previous = states_by_key.setdefault(key, state)
        if previous != state:
            raise ValueError(f"inconsistent assignments across action rows for {key}")
    prediction_keys = set()
    for row in read_jsonl(python_predictions):
        if row.get("family_split") not in ("train", "validation"):
            raise ValueError("Python prediction has an out-of-scope split")
        key = (row["task_id"], int(row["state_index"]))
        if key in prediction_keys or len(row.get("predicted_delta_satisfied", [])) != 40:
            raise ValueError(f"duplicate or malformed Python prediction row {key}")
        prediction_keys.add(key)
    if prediction_keys != set(states_by_key):
        raise ValueError("sanitized states and Python predictions do not have identical keys")
    if len(states_by_key) != 2560:
        raise ValueError(f"expected 2560 train/validation states, got {len(states_by_key)}")

    states_path = output / "states-trainval.jsonl"
    with states_path.open("x", encoding="utf-8", newline="\n") as stream:
        for _, state in sorted(states_by_key.items()):
            stream.write(json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n")

    manifest = {
        "schema": "R1_V05_QDELTA_RUST_PARITY_BUNDLE_V01",
        "status": "TRAIN_VALIDATION_PARITY_BUNDLE_READY",
        "source_receipts": {
            "trainval_view": file_record(view_receipt),
            "frozen_features": file_record(feature_receipt),
            "action_labels": file_record(action_receipt_path),
            "qdelta_diagnostic": file_record(prediction_receipt_path),
            "qterminal_fit": file_record(checkpoint_receipt_path),
        },
        "pinned_inputs": {name: PINS[name] for name in PINS},
        "qdelta_beta": float(prediction_receipt["proposal_temperature_inverse_beta"]),
        "outputs": {
            "public_tasks": file_record(bundled_public),
            "support_manifest": file_record(bundled_support),
            "python_predictions": file_record(bundled_predictions),
            "feature_arrays_and_row_map": copied,
            "feature_extraction_receipt": file_record(feature_view / "receipt.json"),
            "sanitized_states": file_record(states_path),
        },
        "state_source_fields_used": ["task_id", "state_index", "family_split", "assignment"],
        "action_truth_teacher_and_solution_fields_used": False,
        "python_prediction_rows": len(prediction_keys),
        "feature_row_records": row_count,
        "train_validation_only": True,
        "qualification_labels_read": False,
    }
    manifest_path = output / "bundle-manifest-v01.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--action-labels", type=Path, required=True)
    parser.add_argument("--python-predictions", type=Path, required=True)
    parser.add_argument("--qterminal-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = prepare(args.view, args.features, args.action_labels, args.python_predictions,
                       args.qterminal_checkpoint, args.output)
    print(f"TRAIN_VALIDATION_PARITY_BUNDLE_READY states={manifest['python_prediction_rows']} output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
