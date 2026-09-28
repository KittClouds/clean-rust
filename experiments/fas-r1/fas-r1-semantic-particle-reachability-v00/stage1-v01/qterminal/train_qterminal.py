"""Fit the common Q_terminal selector from a prepared Stage 1 dataset."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from model import QTerminal
from qterminal import (
    ContractError,
    SPLITS,
    load_feature_bundle,
    load_manifest,
    load_sample_arrays,
    family_split,
    sha256_file,
    write_json,
)


def _indices_for_split(samples: dict[str, np.ndarray], split: str) -> np.ndarray:
    return np.flatnonzero(samples["splits"] == split).astype(np.int64, copy=False)


def _validate_splits(
    samples: dict[str, np.ndarray],
    features: dict[str, np.ndarray],
    manifest: dict[str, Any],
) -> None:
    families = {
        split: set(samples["family_ids"][samples["splits"] == split].tolist())
        for split in SPLITS
    }
    for index, left in enumerate(SPLITS):
        for right in SPLITS[index + 1 :]:
            overlap = families[left] & families[right]
            if overlap:
                raise ContractError(
                    f"family leakage across {left}/{right}: {sorted(overlap)[:3]}"
                )
    feature_rows = samples["assignment_feature_index"]
    if np.any(feature_rows >= len(features["feature_ids"])):
        raise ContractError("a sample points past the feature bank")
    for row_index, feature_index in enumerate(feature_rows):
        feature_index = int(feature_index)
        if samples["feature_ids"][row_index] != features["feature_ids"][feature_index]:
            raise ContractError("prepared feature IDs no longer align with the feature bank")
        if samples["family_ids"][row_index] != features["family_ids"][feature_index]:
            raise ContractError("prepared sample family does not match its feature")
        if samples["splits"][row_index] != family_split(
            str(samples["family_ids"][row_index]), manifest
        ):
            raise ContractError("prepared sample split does not match the frozen family hash")
    source = samples["source_kinds"]
    for row in np.flatnonzero(source == "policy_visited"):
        if samples["splits"][row] != "train":
            raise ContractError("policy-visited validator labels must come from training families")
    for split in SPLITS:
        split_sources = set(source[samples["splits"] == split].tolist())
        expected_sources = {"random_complete", "policy_visited"} if split == "train" else {"random_complete"}
        if split_sources != expected_sources:
            raise ContractError(f"{split} source mix does not match the frozen manifest")


def _make_batch(
    feature_arrays: dict[str, np.ndarray],
    samples: dict[str, np.ndarray],
    rows: np.ndarray,
    *,
    device: torch.device,
    max_entities: int,
    max_roles: int,
) -> tuple[dict[str, torch.Tensor], torch.Tensor, torch.Tensor]:
    feature_rows = np.asarray(samples["assignment_feature_index"][rows], dtype=np.int64)
    n_values = np.asarray(feature_arrays["n_by_feature"][feature_rows], dtype=np.int64)
    k_values = np.asarray(feature_arrays["k_by_feature"][feature_rows], dtype=np.int64)
    assignment_values = np.asarray(samples["assignments"][rows], dtype=np.uint8)
    assignments = np.zeros((len(rows), max_entities, max_roles), dtype=np.float32)
    entity_mask = np.arange(max_entities)[None, :] < n_values[:, None]
    role_mask = np.arange(max_roles)[None, :] < k_values[:, None]
    for batch_index, (n_value, k_value) in enumerate(zip(n_values, k_values, strict=True)):
        roles = assignment_values[batch_index, :n_value].astype(np.int64)
        if np.any(roles >= k_value):
            raise ContractError("prepared assignment has a role outside its task shape")
        assignments[batch_index, np.arange(n_value), roles] = 1.0
        if np.any(assignment_values[batch_index, n_value:] != 255):
            raise ContractError("prepared assignment has non-sentinel padding")

    H_np = {
        "constraint_embeddings": np.asarray(feature_arrays["h_constraints"][feature_rows]),
        "constraint_mask": np.asarray(feature_arrays["constraint_mask"][feature_rows]),
        "entity_incidence": np.asarray(feature_arrays["entity_incidence"][feature_rows]),
        "role_incidence": np.asarray(feature_arrays["role_incidence"][feature_rows]),
        "entity_mask": entity_mask,
        "role_mask": role_mask,
    }
    H = {
        name: torch.as_tensor(value, device=device)
        for name, value in H_np.items()
    }
    h_global = torch.as_tensor(
        np.asarray(feature_arrays["h_global"][feature_rows]), device=device
    )
    a = torch.as_tensor(assignments, device=device)
    return H, h_global, a


def _batch_width(max_batch: int, clause_rows: int, hidden_dim: int, element_limit: int) -> int:
    per_row = max(1, clause_rows * hidden_dim)
    return max(1, min(max_batch, element_limit // per_row))


def _iterate_batches(
    indices: np.ndarray,
    batch_width: int,
    rng: np.random.Generator | None,
):
    order = rng.permutation(indices) if rng is not None else indices
    for begin in range(0, len(order), batch_width):
        yield order[begin : begin + batch_width]


def _score_indices(
    model: QTerminal,
    feature_arrays: dict[str, np.ndarray],
    samples: dict[str, np.ndarray],
    indices: np.ndarray,
    *,
    device: torch.device,
    batch_width: int,
    max_entities: int,
    max_roles: int,
) -> np.ndarray:
    logits = np.empty(len(indices), dtype=np.float32)
    model.eval()
    with torch.no_grad():
        cursor = 0
        for rows in _iterate_batches(indices, batch_width, None):
            H, h_global, a = _make_batch(
                feature_arrays,
                samples,
                rows,
                device=device,
                max_entities=max_entities,
                max_roles=max_roles,
            )
            values = model(H, h_global, a).detach().cpu().numpy().astype(np.float32)
            logits[cursor : cursor + len(rows)] = values
            cursor += len(rows)
    return logits


def _binary_metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float | int | None]:
    y = np.asarray(labels, dtype=np.uint8)
    p = np.clip(np.asarray(probabilities, dtype=np.float64), 1e-7, 1.0 - 1e-7)
    if len(y) == 0:
        return {"count": 0, "accuracy_at_0.5": None, "balanced_accuracy": None,
                "brier_score": None, "binary_cross_entropy": None, "roc_auc": None,
                "expected_calibration_error_10_bins": None}
    prediction = p >= 0.5
    positives = y == 1
    negatives = ~positives
    tpr = float(prediction[positives].mean()) if positives.any() else float("nan")
    tnr = float((~prediction[negatives]).mean()) if negatives.any() else float("nan")
    balanced_accuracy = float(np.nanmean([tpr, tnr]))
    auc = _roc_auc(y, p)
    ece = 0.0
    for bin_index in range(10):
        lower = bin_index / 10.0
        upper = (bin_index + 1) / 10.0
        selected = (p >= lower) & ((p < upper) if bin_index < 9 else (p <= upper))
        if selected.any():
            ece += float(selected.mean()) * abs(float(y[selected].mean()) - float(p[selected].mean()))
    return {
        "count": int(len(y)),
        "accuracy_at_0.5": float((prediction == positives).mean()),
        "balanced_accuracy": balanced_accuracy,
        "brier_score": float(np.mean((p - y) ** 2)),
        "binary_cross_entropy": float(np.mean(-(y * np.log(p) + (1 - y) * np.log(1 - p)))),
        "roc_auc": auc,
        "expected_calibration_error_10_bins": ece,
    }


def _roc_auc(labels: np.ndarray, probabilities: np.ndarray) -> float | None:
    positive_count = int(np.sum(labels == 1))
    negative_count = len(labels) - positive_count
    if positive_count == 0 or negative_count == 0:
        return None
    order = np.argsort(probabilities, kind="mergesort")
    sorted_scores = probabilities[order]
    ranks = np.empty(len(labels), dtype=np.float64)
    begin = 0
    while begin < len(order):
        end = begin + 1
        while end < len(order) and sorted_scores[end] == sorted_scores[begin]:
            end += 1
        ranks[order[begin:end]] = (begin + 1 + end) / 2.0
        begin = end
    positive_rank_sum = float(ranks[labels == 1].sum())
    return (positive_rank_sum - positive_count * (positive_count + 1) / 2.0) / (
        positive_count * negative_count
    )


def _temperature_for_validation(logits: np.ndarray, labels: np.ndarray) -> float:
    candidates = np.logspace(math.log10(0.05), math.log10(20.0), 301)
    y = labels.astype(np.float64)
    best_temperature = 1.0
    best_loss = float("inf")
    for temperature in candidates:
        scaled = logits.astype(np.float64) / temperature
        loss = np.mean(np.logaddexp(0.0, scaled) - y * scaled)
        if loss < best_loss:
            best_loss = float(loss)
            best_temperature = float(temperature)
    return best_temperature


def _sigmoid(logits: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(logits, dtype=np.float64), -80.0, 80.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _metrics_by_source(
    labels: np.ndarray,
    probabilities: np.ndarray,
    sources: np.ndarray,
) -> dict[str, Any]:
    result: dict[str, Any] = {"overall": _binary_metrics(labels, probabilities)}
    for source in ("random_complete", "policy_visited"):
        mask = sources == source
        result[source] = _binary_metrics(labels[mask], probabilities[mask])
    return result


def _sensor_diagnostic_context(
    report_path: Path | None,
    feature_source: dict[str, Any],
) -> dict[str, Any] | None:
    """Bind diagnostic context to this exact extraction without gating the fit."""
    if report_path is None:
        return None
    if not report_path.is_file():
        raise ContractError(f"sensor diagnostic report does not exist: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("manifest") != "FAS-R1-SENSOR-PROBE-FIT-v01":
        raise ContractError("sensor diagnostic report uses an unexpected manifest")
    if report.get("status") != "SENSOR_LADDER_COMPLETE":
        raise ContractError("sensor diagnostic report is not complete")
    run_receipt_path = report_path.with_name("run-receipt.json")
    if not run_receipt_path.is_file():
        raise ContractError("sensor diagnostic run receipt is missing")
    run_receipt = json.loads(run_receipt_path.read_text(encoding="utf-8"))
    report_hash = sha256_file(report_path)
    if run_receipt.get("status") != "R1_SENSOR_PROBES_COMPLETE":
        raise ContractError("sensor diagnostic run receipt is incomplete")
    if str(run_receipt.get("report_sha256", "")).lower() != report_hash:
        raise ContractError("sensor diagnostic report hash differs from its run receipt")
    extraction_hash = feature_source["extraction_receipt_sha256"]
    if str(run_receipt.get("extraction_receipt_sha256", "")).lower() != extraction_hash:
        raise ContractError("sensor diagnostic and Q_terminal use different extraction receipts")
    rungs = report["rungs"]
    return {
        "report_path": str(report_path.resolve()),
        "report_sha256": report_hash,
        "run_receipt_path": str(run_receipt_path.resolve()),
        "run_receipt_sha256": sha256_file(run_receipt_path),
        "probe_manifest_sha256": run_receipt["probe_manifest_sha256"],
        "extraction_receipt_sha256": extraction_hash,
        "overall_gate_pass": bool(report["overall_gate_pass"]),
        "interpretation": "diagnostic context only; no fit gate",
        "qualification_metrics": {
            "identity_balanced_accuracy": rungs["identity"]["qualification_balanced_accuracy"],
            "binding_entity_micro_f1": rungs["binding"]["qualification"]["entity_micro_f1"],
            "binding_role_micro_f1": rungs["binding"]["qualification"]["role_micro_f1"],
            "binding_combined_f1": rungs["binding"]["qualification"]["combined_f1"],
            "action_relevance_macro_f1": rungs["action_relevance"]["qualification"]["macro_f1"],
        },
    }


def train(
    dataset_dir: Path,
    feature_dir: Path,
    output_dir: Path,
    manifest_path: Path,
    *,
    epochs: int | None = None,
    batch_size: int | None = None,
    device_name: str = "auto",
    sensor_diagnostic_report: Path | None = None,
) -> dict[str, Any]:
    if output_dir.exists():
        raise ContractError(f"output directory already exists: {output_dir}")
    manifest = load_manifest(manifest_path)
    prepared = json.loads((dataset_dir / "dataset-manifest.json").read_text(encoding="utf-8"))
    if prepared["mixture_manifest_sha256"] != sha256_file(manifest_path):
        raise ContractError("prepared dataset was built under a different mixture manifest")
    for name, expected_hash in prepared["sample_array_sha256"].items():
        if sha256_file(dataset_dir / f"{name}.npy") != expected_hash:
            raise ContractError(f"prepared sample array changed since construction: {name}.npy")
    if sha256_file(dataset_dir / "selected-candidates.jsonl") != prepared["selected_candidates_sha256"]:
        raise ContractError("selected candidate ledger changed since construction")
    features, feature_source = load_feature_bundle(
        feature_dir,
        hidden_dim=int(manifest["feature_input"]["h_global"].split(",")[-1].split("]")[0]),
        max_constraints=int(manifest["feature_input"]["max_constraints"]),
        max_entities=int(manifest["feature_input"]["max_entities"]),
        max_roles=int(manifest["feature_input"]["max_roles"]),
    )
    if feature_source != prepared["feature_source"]:
        raise ContractError("sensor extraction inputs changed since mixture construction")
    sensor_context = _sensor_diagnostic_context(sensor_diagnostic_report, feature_source)
    samples = load_sample_arrays(dataset_dir)
    _validate_splits(samples, features, manifest)
    split_indices = {split: _indices_for_split(samples, split) for split in SPLITS}
    for split, rows in split_indices.items():
        if len(rows) == 0:
            raise ContractError(f"prepared dataset has no {split} rows")
    train_indices = split_indices["train"]
    validation_indices = split_indices["validation"]
    train_labels = np.asarray(samples["labels"][train_indices], dtype=np.float32)
    validation_labels = np.asarray(samples["labels"][validation_indices], dtype=np.uint8)
    if set(np.unique(train_labels).tolist()) != {0.0, 1.0}:
        raise ContractError("training labels must contain both classes")
    train_cells = {
        (source_name, label): int(
            np.sum(
                (samples["source_kinds"][train_indices] == source_name)
                & (samples["labels"][train_indices] == label)
            )
        )
        for source_name in ("random_complete", "policy_visited")
        for label in (0, 1)
    }
    if len(set(train_cells.values())) != 1 or min(train_cells.values()) <= 0:
        raise ContractError(f"training cells are not exactly balanced: {train_cells}")
    if set(np.unique(validation_labels).tolist()) != {0, 1}:
        raise ContractError("validation labels must contain both classes for calibration")

    if device_name == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(device_name)
    seed = int(manifest["training"]["seed"])
    np_rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True

    hidden_dim = int(features["h_global"].shape[1])
    max_roles = int(features["role_incidence"].shape[2])
    model = QTerminal(hidden_dim=hidden_dim, hidden_size=128, max_roles=max_roles).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(manifest["training"]["learning_rate"]),
        weight_decay=float(manifest["training"]["weight_decay"]),
    )
    loss_function = nn.BCEWithLogitsLoss()
    epoch_limit = int(epochs if epochs is not None else manifest["training"]["maximum_epochs"])
    requested_batch = int(batch_size if batch_size is not None else manifest["training"]["batch_size"])
    element_limit = int(manifest["training"]["max_clause_feature_elements_per_batch"])
    m_count = int(features["h_constraints"].shape[1])
    effective_batch = min(
        requested_batch,
        max(1, element_limit // max(1, m_count * hidden_dim)),
    )
    patience = int(manifest["training"]["early_stopping_patience"])
    best_loss = float("inf")
    best_epoch = 0
    best_state: dict[str, torch.Tensor] | None = None
    stale_epochs = 0
    history: list[dict[str, float | int]] = []
    max_entities = int(features["entity_incidence"].shape[2])

    for epoch in range(1, epoch_limit + 1):
        model.train()
        total_loss = 0.0
        seen = 0
        epoch_width = _batch_width(effective_batch, m_count, hidden_dim, element_limit)
        for rows in _iterate_batches(train_indices, epoch_width, np_rng):
            H, h_global, a = _make_batch(
                features,
                samples,
                rows,
                device=device,
                max_entities=max_entities,
                max_roles=max_roles,
            )
            y = torch.as_tensor(samples["labels"][rows].astype(np.float32), device=device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(H, h_global, a)
            loss = loss_function(logits, y)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach()) * len(rows)
            seen += len(rows)

        val_width = _batch_width(effective_batch, m_count, hidden_dim, element_limit)
        validation_logits = _score_indices(
            model,
            features,
            samples,
            validation_indices,
            device=device,
            batch_width=val_width,
            max_entities=max_entities,
            max_roles=max_roles,
        )
        scaled = validation_logits.astype(np.float64)
        val_loss = float(
            np.mean(
                np.logaddexp(0.0, scaled)
                - validation_labels.astype(np.float64) * scaled
            )
        )
        history.append({"epoch": epoch, "train_bce": total_loss / max(seen, 1), "validation_bce": val_loss})
        if val_loss < best_loss:
            best_loss = val_loss
            best_epoch = epoch
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stale_epochs = 0
        else:
            stale_epochs += 1
        if stale_epochs >= patience:
            break

    if best_state is None:
        raise ContractError("training did not produce a validation checkpoint")
    model.load_state_dict(best_state)
    model.to(device)
    model.eval()
    validation_logits = _score_indices(
        model,
        features,
        samples,
        validation_indices,
        device=device,
        batch_width=effective_batch,
        max_entities=max_entities,
        max_roles=max_roles,
    )
    temperature = _temperature_for_validation(validation_logits, validation_labels)
    validation_probability = _sigmoid(validation_logits / temperature)

    # The test labels are first read below, after both checkpoint and
    # calibration temperature have been frozen from the training/validation split.
    test_indices = split_indices["test"]
    test_labels = np.asarray(samples["labels"][test_indices], dtype=np.uint8)
    if set(np.unique(test_labels).tolist()) != {0, 1} or int(np.sum(test_labels == 0)) != int(np.sum(test_labels == 1)):
        raise ContractError("test random-complete labels are not balanced after model freeze")
    test_logits = _score_indices(
        model,
        features,
        samples,
        test_indices,
        device=device,
        batch_width=effective_batch,
        max_entities=max_entities,
        max_roles=max_roles,
    )
    test_probability = _sigmoid(test_logits / temperature)
    val_sources = np.asarray(samples["source_kinds"][validation_indices])
    test_sources = np.asarray(samples["source_kinds"][test_indices])

    output_dir.mkdir(parents=True)
    checkpoint_path = output_dir / "qterminal-v02.pt"
    torch.save(
        {
            "schema": "R1_QTERMINAL_CHECKPOINT_V02",
            "model_config": {"hidden_dim": hidden_dim, "hidden_size": 128, "max_roles": max_roles},
            "state_dict": best_state,
            "temperature": temperature,
            "best_epoch": best_epoch,
            "mixture_manifest_sha256": sha256_file(manifest_path),
        },
        checkpoint_path,
    )
    report = {
        "schema": "R1_QTERMINAL_FIT_RECEIPT_V02",
        "status": "QTERMINAL_FITTED_AND_HELDOUT_METRICS_RECORDED",
        "model_contact_performed": False,
        "qterminal_training_performed": True,
        "frozen_lfm_training_performed": False,
        "family_leakage_check_passed": True,
        "policy_trace_labels_from_training_families_only": True,
        "checkpoint_file_sha256": sha256_file(checkpoint_path),
        "prepared_dataset_sha256": sha256_file(dataset_dir / "dataset-manifest.json"),
        "mixture_manifest_sha256": sha256_file(manifest_path),
        "sensor_diagnostic_context": sensor_context,
        "device": str(device),
        "effective_batch_size": effective_batch,
        "epochs_completed": len(history),
        "best_epoch": best_epoch,
        "best_validation_bce_before_calibration": best_loss,
        "validation_temperature": temperature,
        "validation_metrics_after_calibration": _metrics_by_source(
            validation_labels, validation_probability, val_sources
        ),
        "test_metrics_after_calibration": _metrics_by_source(
            test_labels, test_probability, test_sources
        ),
        "training_history": history,
    }
    write_json(output_dir / "fit-receipt.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="prepared Q_terminal dataset directory")
    parser.add_argument("--features", type=Path, required=True, help="feature array directory used to prepare data")
    parser.add_argument("--output", type=Path, required=True, help="new output directory; existing paths are refused")
    parser.add_argument(
        "--manifest", type=Path, default=Path(__file__).with_name("manifest-v02.json")
    )
    parser.add_argument("--epochs", type=int, default=None, help="development override, capped by manifest maximum")
    parser.add_argument("--batch-size", type=int, default=None, help="development override")
    parser.add_argument("--device", default="auto", help="auto, cpu, or an explicit torch device")
    parser.add_argument(
        "--sensor-diagnostic-report",
        type=Path,
        default=None,
        help="optional completed qualification-report.json; recorded as context, never used as a gate",
    )
    args = parser.parse_args()
    try:
        manifest = load_manifest(args.manifest)
        if args.epochs is not None and not (1 <= args.epochs <= manifest["training"]["maximum_epochs"]):
            parser.error("--epochs must be between 1 and the frozen maximum")
        if args.batch_size is not None and args.batch_size < 1:
            parser.error("--batch-size must be positive")
        receipt = train(
            args.dataset,
            args.features,
            args.output,
            args.manifest,
            epochs=args.epochs,
            batch_size=args.batch_size,
            device_name=args.device,
            sensor_diagnostic_report=args.sensor_diagnostic_report,
        )
    except (ContractError, OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(receipt["status"])
    print(f"best epoch={receipt['best_epoch']} validation temperature={receipt['validation_temperature']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
