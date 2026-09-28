"""Fit one sequentially gated R1 Stage 1 sensor rung and lock predictions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"

import numpy as np
import torch
from torch import nn

torch.set_num_threads(1)
torch.set_num_interop_threads(1)

from r1_sensor_probe_data_v01 import ACTION_ORDER, KIND_ORDER, Rows, SensorData

SEEDS = (20260926, 20260927, 20260928)
ARMS = ("real", "shuffled", "surface", "template")
CONDITIONS = ("id_seen", "template_ood", "vocabulary_ood", "joint_ood")
BATCH = 256
MAX_EPOCHS = 40
PATIENCE = 6
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
EXECUTION_CONTRACT = {
    "seeds": list(SEEDS), "arms": list(ARMS), "evaluation_conditions": list(CONDITIONS),
    "head": {"hidden": 128, "activation": "GELU", "dropout": 0.1, "layers": 2},
    "optimizer": {"name": "AdamW", "learning_rate": 0.0003, "weight_decay": 0.0001,
                  "batch_size": BATCH, "maximum_epochs": MAX_EPOCHS, "patience": PATIENCE,
                  "gradient_norm_cap": 1.0},
    "normalization": "per-arm, train-only population mean/std; std below 1e-6 set to 1",
    "training_weights": "inverse class frequency on train, then equal total weight per task family",
    "semantic": {"input_dim": 2048, "output_dim": 6, "gate_per_condition_balanced_accuracy": 0.90,
                 "gate_min_margin_over_shuffled": 0.20},
    "binding": {"input_dim": 4102, "output_dim": 1, "thresholds": [round(0.10 + 0.05 * i, 2) for i in range(17)],
                "threshold_objective": "validation micro-F1; ties closest to 0.50 then lower threshold",
                "gate_per_condition_micro_f1": 0.90, "gate_margin_over_shuffled": 0.20,
                "gate_margin_over_surface": 0.05},
    "action": {"input_dim": 4180, "output_dim": 3, "gate_equal_condition_mean_balanced_accuracy": 0.60,
               "gate_each_condition_balanced_accuracy": 0.55, "gate_mean_margin_over_each_control": 0.10,
               "family_cluster_bootstrap_replicates": 2000, "confidence_level": 0.95,
               "bootstrap_seed_domain": "R1-ACTION-FAMILY-BOOTSTRAP-v1"},
    "early_stopping": "highest validation rung metric, earliest epoch wins ties; stop after six non-improving epochs",
    "determinism": {"torch_intraop_threads": 1, "torch_interop_threads": 1, "tf32": False, "deterministic_algorithms": True,
                    "cublas_workspace_config": ":4096:8", "cudnn_benchmark": False},
}


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def write_json_new(path: Path, obj: dict[str, Any]) -> None:
    payload = json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def set_seed(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


class Probe(nn.Module):
    def __init__(self, input_dim: int, output_dim: int):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_dim, 128), nn.GELU(), nn.Dropout(0.10), nn.Linear(128, output_dim)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.layers(x)


def normalizer(rows: Rows, train_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    total = np.zeros(rows.input_dim, dtype=np.float64)
    total_sq = np.zeros(rows.input_dim, dtype=np.float64)
    count = 0
    for start in range(0, len(train_ids), BATCH):
        batch = rows.batch(train_ids[start:start + BATCH]).astype(np.float64)
        total += batch.sum(axis=0)
        total_sq += np.square(batch).sum(axis=0)
        count += batch.shape[0]
    mean = total / max(1, count)
    variance = np.maximum(total_sq / max(1, count) - mean * mean, 0.0)
    std = np.sqrt(variance)
    std[std < 1e-6] = 1.0
    return mean.astype(np.float32), std.astype(np.float32)


def sample_weights(labels: np.ndarray, families: np.ndarray, class_count: int) -> np.ndarray:
    counts = np.bincount(labels, minlength=class_count).astype(np.float64)
    if np.any(counts == 0):
        raise ValueError("degenerate training target support")
    base = 1.0 / counts[labels]
    family_sum: dict[str, float] = {}
    for fam, weight in zip(families.tolist(), base.tolist(), strict=True):
        family_sum[fam] = family_sum.get(fam, 0.0) + weight
    family_count = len(family_sum)
    return np.asarray([w / family_sum[fam] / family_count for fam, w in zip(families.tolist(), base.tolist(), strict=True)], dtype=np.float32)


def balanced_accuracy(y: np.ndarray, pred: np.ndarray, classes: int) -> float:
    recalls = []
    for cls in range(classes):
        mask = y == cls
        if not mask.any():
            raise ValueError(f"balanced accuracy undefined: class {cls} absent")
        recalls.append(float(np.mean(pred[mask] == cls)))
    return float(np.mean(recalls))


def binary_f1(y: np.ndarray, score: np.ndarray, threshold: float) -> float:
    pred = score >= threshold
    tp = int(np.sum(pred & (y == 1)))
    fp = int(np.sum(pred & (y == 0)))
    fn = int(np.sum((~pred) & (y == 1)))
    return 2.0 * tp / max(1, 2 * tp + fp + fn)


def select_threshold(y: np.ndarray, score: np.ndarray) -> tuple[float, float]:
    grid = np.asarray([round(0.10 + 0.05 * i, 2) for i in range(17)], dtype=np.float64)
    scored = [(binary_f1(y, score, float(t)), float(t)) for t in grid]
    best_score = max(item[0] for item in scored)
    best_threshold = min((t for value, t in scored if value == best_score), key=lambda t: (abs(t - 0.5), t))
    return best_threshold, best_score


def predict(model: nn.Module, rows: Rows, mean: np.ndarray, std: np.ndarray, device: torch.device) -> np.ndarray:
    model.eval()
    output: list[np.ndarray] = []
    with torch.inference_mode():
        for start in range(0, len(rows), BATCH):
            idx = np.arange(start, min(start + BATCH, len(rows)), dtype=np.int64)
            x = (rows.batch(idx) - mean) / std
            logits = model(torch.from_numpy(x).to(device)).float().cpu().numpy()
            output.append(logits)
    width = model.layers[-1].out_features
    return np.concatenate(output, axis=0) if output else np.empty((0, width), dtype=np.float32)


def validation_score(rung: str, y: np.ndarray, logits: np.ndarray) -> tuple[float, float | None]:
    if rung == "binding":
        threshold, score = select_threshold(y, logits[:, 0])
        return score, threshold
    classes = 6 if rung == "semantic" else 3
    return balanced_accuracy(y, logits.argmax(axis=1), classes), None


def fit_one(rung: str, arm: str, seed: int, train: Rows, valid: Rows, evaluate: Rows, out: Path) -> dict[str, Any]:
    if len(train) == 0 or set(train.labels.tolist()) != set(range(2 if rung == "binding" else 6 if rung == "semantic" else 3)):
        raise ValueError(f"degenerate {rung} training support for {arm} seed {seed}")
    if len(valid) == 0 or set(valid.labels.tolist()) != set(range(2 if rung == "binding" else 6 if rung == "semantic" else 3)):
        raise ValueError(f"degenerate {rung} validation support for {arm} seed {seed}")
    out.mkdir(parents=True, exist_ok=False)
    set_seed(seed)
    device = torch.device(DEVICE)
    if device.type == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)
    model = Probe(train.input_dim, 1 if rung == "binding" else 6 if rung == "semantic" else 3).to(device)
    mean, std = normalizer(train, np.arange(len(train), dtype=np.int64))
    np.savez(out / "normalizer.npz", mean=mean, std=std)
    weights = sample_weights(train.labels, train.families, model.layers[-1].out_features if rung != "binding" else 2)
    weight_t = torch.from_numpy(weights).to(device)
    y_t = torch.from_numpy(train.labels.astype(np.int64)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    rng = np.random.default_rng(seed)
    best_score = -float("inf")
    best_epoch = 0
    best_threshold: float | None = None
    best_state: dict[str, torch.Tensor] | None = None
    bad_epochs = 0
    history: list[dict[str, float | int]] = []
    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        order = rng.permutation(len(train))
        losses: list[float] = []
        for start in range(0, len(order), BATCH):
            ids = order[start:start + BATCH]
            x_np = (train.batch(ids) - mean) / std
            x_t = torch.from_numpy(x_np).to(device)
            logits = model(x_t)
            if rung == "binding":
                per_row = nn.functional.binary_cross_entropy_with_logits(logits[:, 0], y_t[ids], reduction="none")
            else:
                per_row = nn.functional.cross_entropy(logits, y_t[ids], reduction="none")
            loss = torch.sum(per_row * weight_t[ids]) / max(float(weight_t[ids].sum()), 1e-12)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        val_logits = predict(model, valid, mean, std, device)
        score, threshold = validation_score(rung, valid.labels, val_logits)
        history.append({"epoch": epoch, "train_loss_mean_batch": float(np.mean(losses)), "validation_score": score,
                        "validation_threshold": threshold if threshold is not None else -1.0})
        if score > best_score:
            best_score, best_epoch, best_threshold = score, epoch, threshold
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= PATIENCE:
                break
    if best_state is None:
        raise RuntimeError("no valid checkpoint selected")
    model.load_state_dict(best_state)
    torch.save(best_state, out / "weights.pt")
    logits = predict(model, evaluate, mean, std, device)
    np.savez_compressed(out / "evaluation-predictions.npz", row_keys=evaluate.keys, families=evaluate.families,
                        conditions=evaluate.conditions, logits=logits)
    metrics = {
        "schema": "R1_SENSOR_PROBE_FIT_V01", "rung": rung, "arm": arm, "seed": seed,
        "input_dim": train.input_dim, "output_dim": int(logits.shape[1]), "train_rows": len(train),
        "validation_rows": len(valid), "evaluation_rows": len(evaluate), "best_epoch": best_epoch,
        "best_validation_score": best_score, "validation_threshold": best_threshold,
        "optimizer": "AdamW", "learning_rate": 3e-4, "weight_decay": 1e-4,
        "batch_size": BATCH, "maximum_epochs": MAX_EPOCHS, "early_stop_patience": PATIENCE,
        "grad_norm_cap": 1.0, "seed": seed, "device": str(device),
        "train_family_count": len(set(train.families.tolist())), "validation_history": history,
        "training_truth_splits": ["train", "validation"], "evaluation_labels_opened": False,
        "evaluation_metrics_computed": False,
    }
    write_json_new(out / "fit-receipt.json", metrics)
    return metrics


def make_rows(data: SensorData, rung: str, split: str, arm: str) -> Rows:
    if rung == "semantic":
        return data.semantic_rows(split, arm)
    if rung == "binding":
        return data.binding_rows(split, arm)
    return data.action_rows(split, arm)


def verify_authority(manifest_path: Path, extraction: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sidecar = manifest_path.with_suffix(".sha256").read_text(encoding="ascii").split()[0].lower()
    if sha256_file(manifest_path)[0] != sidecar:
        raise ValueError("qualification manifest SHA-256 sidecar mismatch")
    integrity_path = extraction / "EXTRACTION-INTEGRITY-RECEIPT-v04.json"
    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    if integrity.get("status") != "PASS":
        raise ValueError("extraction integrity gate has not passed")
    expected = manifest["prepared_inputs"]
    if sha256_file(extraction / "receipt.json")[0] != integrity["receipt_sha256"]:
        raise ValueError("extraction receipt drift")
    for file_key in ("public_probe_tasks", "private_probe_targets", "name_queries", "private_action_examples", "family_split"):
        entry = expected[file_key]
        digest, size = sha256_file(Path(expected["root"]) / entry["path"])
        if digest != entry["sha256"] or size != entry["bytes"]:
            raise ValueError(f"qualification input drift: {file_key}")
    return manifest


def run_fit(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve(strict=True)
    extraction = args.extraction.resolve(strict=True)
    manifest = verify_authority(manifest_path, extraction)
    source_lock = json.loads(args.source_lock.read_text(encoding="utf-8"))
    source_sidecar = args.source_lock.with_suffix(".sha256").read_text(encoding="ascii").split()[0].lower()
    if sha256_file(args.source_lock)[0] != source_sidecar:
        raise ValueError("probe execution manifest SHA-256 sidecar mismatch")
    if source_lock.get("execution_contract") != EXECUTION_CONTRACT:
        raise ValueError("source lock execution contract does not match the frozen runner")
    if source_lock.get("qualification_manifest_sha256") != sha256_file(manifest_path)[0]:
        raise ValueError("probe execution manifest is not bound to the qualification manifest")
    if source_lock.get("extraction_integrity_receipt_sha256") != sha256_file(extraction / "EXTRACTION-INTEGRITY-RECEIPT-v04.json")[0]:
        raise ValueError("probe execution manifest extraction receipt binding mismatch")
    row_audit_path = Path(source_lock["row_audit_receipt_path"])
    row_audit = json.loads(row_audit_path.read_text(encoding="utf-8"))
    if row_audit.get("status") != "PASS" or sha256_file(row_audit_path)[0] != source_lock["row_audit_receipt_sha256"]:
        raise ValueError("pre-fit row audit is absent, failed, or changed")
    runtime = {
        "python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__,
        "device": DEVICE, "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        "openblas_threads": os.environ.get("OPENBLAS_NUM_THREADS"), "omp_threads": os.environ.get("OMP_NUM_THREADS"),
        "mkl_threads": os.environ.get("MKL_NUM_THREADS"), "numexpr_threads": os.environ.get("NUMEXPR_NUM_THREADS"),
        "torch_intraop_threads": torch.get_num_threads(), "torch_interop_threads": torch.get_num_interop_threads(),
        "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
    }
    if runtime != source_lock.get("runtime"):
        raise ValueError("probe runtime differs from the frozen execution manifest")
    for rel, expected in source_lock["sources"].items():
        digest, _ = sha256_file(Path(__file__).parent / rel)
        if digest != expected:
            raise ValueError(f"probe execution source drift: {rel}")
    rung = args.rung
    if rung not in ("semantic", "binding", "action"):
        raise ValueError("unknown sensor rung")
    if rung == "binding":
        prior = json.loads((args.output / "semantic" / "RUNG-GATE.json").read_text(encoding="utf-8"))
        if prior.get("status") != "PASS":
            raise ValueError("semantic rung gate did not pass")
    if rung == "action":
        prior = json.loads((args.output / "binding" / "RUNG-GATE.json").read_text(encoding="utf-8"))
        if prior.get("status") != "PASS":
            raise ValueError("binding rung gate did not pass")
    data = SensorData(Path(manifest["prepared_inputs"]["root"]), extraction)
    out_root = args.output / rung
    out_root.mkdir(parents=True, exist_ok=False)
    fit_index = []
    for seed in SEEDS:
        for arm in ARMS:
            train = make_rows(data, rung, "train", arm)
            valid = make_rows(data, rung, "validation", arm)
            evaluate = make_rows(data, rung, "evaluation", arm)
            fit_dir = out_root / f"seed-{seed}" / arm
            fit_dir.parent.mkdir(parents=True, exist_ok=True)
            receipt = fit_one(rung, arm, seed, train, valid, evaluate, fit_dir)
            for filename in ("fit-receipt.json", "weights.pt", "normalizer.npz", "evaluation-predictions.npz"):
                digest, size = sha256_file(fit_dir / filename)
                fit_index.append({"seed": seed, "arm": arm, "file": str((fit_dir / filename).relative_to(args.output)), "bytes": size, "sha256": digest})
            print(f"fit complete rung={rung} seed={seed} arm={arm} epoch={receipt['best_epoch']}", flush=True)
    lock = {
        "schema": "R1_SENSOR_RUNG_PREDICTION_LOCK_V01", "rung": rung,
        "manifest_sha256": sha256_file(manifest_path)[0],
        "source_lock_sha256": sha256_file(args.source_lock)[0],
        "extraction_integrity_receipt_sha256": sha256_file(extraction / "EXTRACTION-INTEGRITY-RECEIPT-v04.json")[0],
        "fit_count": len(SEEDS) * len(ARMS), "seed_count": len(SEEDS), "arms": list(ARMS), "files": fit_index,
        "evaluation_labels_opened": False,
    }
    write_json_new(out_root / "PREDICTION-LOCK.json", lock)
    print(json.dumps({"rung": rung, "fit_count": lock["fit_count"], "prediction_lock_sha256": sha256_file(out_root / "PREDICTION-LOCK.json")[0]}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--extraction", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rung", choices=("semantic", "binding", "action"), required=True)
    args = parser.parse_args()
    try:
        return run_fit(args)
    except Exception as error:
        print(f"R1_SENSOR_PROBE_FIT_STOP: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
