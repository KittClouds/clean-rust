"""Fit and score cached row-level BANK graph readouts; no backbone pass."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SURFACE_EXPERIMENT = HERE.parent / "bank-v1-surface-extremes-20260929"
sys.path.insert(0, str(SURFACE_EXPERIMENT))

from common import sha256, write_json  # noqa: E402
from graph_targets import (ENTITY_TYPES, PATH_CLASSES, RELATION_TYPES,
                           STATE_VALUES, derive_targets, path_class)  # noqa: E402

SURFACES = ("middle_plus_final", "final_plus_mean", "layer_m4_final", "full_mean")
PRIMITIVES_NEEDED = ("final_token", "full_mean", "layer_m4_final", "middle_final")
SPLITS = ("TRAIN", "DEV", "TEST-IID", "TEST-LEXICAL", "TEST-ENTITY",
          "TEST-TEMPLATE", "TEST-COMPOSITION", "TEST-DEPTH", "TEST-ABSTENTION", "TEST-JOINT")
SEED = 20260929
EPOCHS = 8
BATCH_SIZE = 2048
LR = 1e-3
WEIGHT_DECAY = 1e-4
MLP_WIDTH = 256


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            if line.strip():
                yield json.loads(line)


def digest_ids(rows) -> str:
    h = hashlib.sha256()
    for row in rows:
        h.update(row["world_id"].encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def load_world_rows(bank_root: Path, feature_rowmap: list[dict]):
    primary = {str(row["row_id"]): row for row in feature_rowmap if row.get("paired_world") is None}
    if len(primary) != sum(row.get("paired_world") is None for row in feature_rowmap):
        raise RuntimeError("duplicate primary row identities in feature rowmap")
    by_split: dict[str, list[dict]] = {split: [] for split in SPLITS}
    seen = set()
    source_hashes = {}
    for split in SPLITS:
        path = bank_root / "worlds" / f"{split}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(path)
        source_hashes[split] = sha256(path)
        for world in read_jsonl(path):
            world_id = str(world["world_id"])
            if world_id in seen:
                raise RuntimeError(f"duplicate canonical world id: {world_id}")
            seen.add(world_id)
            feature = primary.get(world_id)
            if feature is None:
                raise RuntimeError(f"canonical world missing feature row: {world_id}")
            if feature["split"] != split:
                raise RuntimeError(f"split mismatch for {world_id}: {split} vs {feature['split']}")
            target = derive_targets(world)
            path_idx = path_class(target["goal_path_distance"])
            by_split[split].append({
                "world_id": world_id,
                "idx": int(feature["idx"]),
                "surface_family": str(feature.get("surface_family") or world.get("surface_family") or ""),
                "entity_types": target["entity_types"],
                "relation_types": target["relation_types"],
                "state_values": target["state_values"],
                "goal_path_distance": path_idx,
            })
    if seen != set(primary):
        extra = list(set(primary) - seen)[:5]
        raise RuntimeError(f"primary rowmap/world set mismatch; extra rows: {extra}")
    return by_split, source_hashes


def load_primitives(feature_dir: Path, row_count: int):
    seal = json.loads((feature_dir / "extraction-seal.json").read_text(encoding="utf-8"))
    if seal.get("rows") != row_count or seal.get("truth_joined") is not False:
        raise RuntimeError("upstream feature seal does not match rowmap/truth firewall")
    arrays = {}
    actual_hashes = {}
    for name in PRIMITIVES_NEEDED:
        path = feature_dir / f"{name}.npy"
        spec = seal["primitives"][name]
        if sha256(path) != spec["sha256"]:
            raise RuntimeError(f"cached primitive hash mismatch: {name}")
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        if list(array.shape) != spec["shape"] or array.dtype != np.dtype("<f4"):
            raise RuntimeError(f"bad primitive cache: {name} {array.shape}/{array.dtype}")
        arrays[name] = array
        actual_hashes[name] = spec["sha256"]
    return arrays, seal, actual_hashes


def surface_matrix(primitives: dict[str, np.ndarray], indices: np.ndarray, name: str) -> np.ndarray:
    final = np.asarray(primitives["final_token"][indices], dtype=np.float32)
    if name == "middle_plus_final":
        middle = np.asarray(primitives["middle_final"][indices], dtype=np.float32)
        return np.concatenate((middle, final), axis=1)
    if name == "final_plus_mean":
        mean = np.asarray(primitives["full_mean"][indices], dtype=np.float32)
        return np.concatenate((final, mean), axis=1)
    if name == "layer_m4_final":
        return np.asarray(primitives["layer_m4_final"][indices], dtype=np.float32)
    if name == "full_mean":
        return np.asarray(primitives["full_mean"][indices], dtype=np.float32)
    raise KeyError(name)


def packed_targets(rows: list[dict]):
    n = len(rows)
    entity = np.zeros((n, len(ENTITY_TYPES)), dtype=np.float32)
    relation = np.zeros((n, len(RELATION_TYPES)), dtype=np.float32)
    state = np.zeros((n, len(STATE_VALUES)), dtype=np.float32)
    path = np.full(n, -1, dtype=np.int64)
    family = np.empty(n, dtype=object)
    for i, row in enumerate(rows):
        for label in row["entity_types"]:
            entity[i, ENTITY_TYPES.index(label)] = 1.0
        for label in row["relation_types"]:
            relation[i, RELATION_TYPES.index(label)] = 1.0
        for label in row["state_values"]:
            state[i, STATE_VALUES.index(label)] = 1.0
        if row["goal_path_distance"] is not None:
            path[i] = int(row["goal_path_distance"])
        family[i] = row["surface_family"]
    return {"entity_types": entity, "relation_types": relation,
            "state_values": state, "goal_path_distance": path,
            "surface_family": family}


def train_scaler(x: np.ndarray):
    n, dims = x.shape
    total = np.zeros(dims, dtype=np.float64)
    squares = np.zeros(dims, dtype=np.float64)
    for start in range(0, n, 4096):
        block = np.asarray(x[start:start + 4096], dtype=np.float64)
        total += block.sum(axis=0)
        squares += np.einsum("ij,ij->j", block, block, optimize=True)
    mean = total / n
    variance = np.maximum(squares / n - mean * mean, 0.0)
    scale = np.sqrt(variance)
    scale[scale == 0] = 1.0
    return mean.astype(np.float32), scale.astype(np.float32)


def build_model(torch, dim: int, kind: str):
    import torch.nn as nn

    class GraphReadout(nn.Module):
        def __init__(self):
            super().__init__()
            if kind == "linear":
                self.encoder = nn.Identity()
                out_dim = dim
            elif kind == "tiny_mlp":
                self.encoder = nn.Sequential(nn.Linear(dim, MLP_WIDTH), nn.GELU(),
                                             nn.Dropout(0.1))
                out_dim = MLP_WIDTH
            else:
                raise ValueError(kind)
            self.heads = nn.ModuleDict({
                "entity_types": nn.Linear(out_dim, len(ENTITY_TYPES)),
                "relation_types": nn.Linear(out_dim, len(RELATION_TYPES)),
                "state_values": nn.Linear(out_dim, len(STATE_VALUES)),
                "goal_path_distance": nn.Linear(out_dim, len(PATH_CLASSES)),
            })

        def forward(self, features):
            encoded = self.encoder(features)
            return {name: head(encoded) for name, head in self.heads.items()}

    return GraphReadout().to(device="cuda:0", dtype=torch.float32)


def model_loss(torch, logits: dict, targets: dict):
    import torch.nn.functional as F
    terms = [F.binary_cross_entropy_with_logits(logits[name], targets[name])
             for name in ("entity_types", "relation_types", "state_values")]
    mask = targets["goal_path_distance"] >= 0
    if bool(mask.any()):
        terms.append(F.cross_entropy(logits["goal_path_distance"][mask],
                                     targets["goal_path_distance"][mask]))
    return torch.stack(terms).mean()


def fit_model(torch, x_gpu, target_arrays, kind: str, surface: str, output_dir: Path):
    seed = SEED + SURFACES.index(surface) * 11 + (0 if kind == "linear" else 1)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    model = build_model(torch, x_gpu.shape[1], kind)
    y = {
        "entity_types": torch.as_tensor(target_arrays["entity_types"], device="cuda:0"),
        "relation_types": torch.as_tensor(target_arrays["relation_types"], device="cuda:0"),
        "state_values": torch.as_tensor(target_arrays["state_values"], device="cuda:0"),
        "goal_path_distance": torch.as_tensor(target_arrays["goal_path_distance"],
                                               dtype=torch.long, device="cuda:0"),
    }
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY,
                                  foreach=False)
    epoch_losses = []
    started = time.perf_counter()
    for epoch in range(EPOCHS):
        generator = np.random.default_rng(seed + epoch)
        order = generator.permutation(len(x_gpu))
        weighted_loss = 0.0
        seen = 0
        model.train()
        for start in range(0, len(order), BATCH_SIZE):
            batch_idx = torch.as_tensor(order[start:start + BATCH_SIZE], dtype=torch.long,
                                        device="cuda:0")
            logits = model(x_gpu.index_select(0, batch_idx))
            batch_y = {name: value.index_select(0, batch_idx) for name, value in y.items()}
            loss = model_loss(torch, logits, batch_y)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            count = len(batch_idx)
            weighted_loss += float(loss.detach()) * count
            seen += count
        epoch_loss = weighted_loss / seen
        epoch_losses.append(epoch_loss)
        print(json.dumps({"phase": "fit", "surface": surface, "model": kind,
                          "epoch": epoch + 1, "epochs": EPOCHS, "loss": epoch_loss}),
              flush=True)
    model.eval()
    model_path = output_dir / "models" / f"{surface}-{kind}.pt"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"surface": surface, "kind": kind, "seed": seed,
                "input_dim": int(x_gpu.shape[1]), "width": MLP_WIDTH if kind == "tiny_mlp" else None,
                "state_dict": model.state_dict()}, model_path)
    params = sum(p.numel() for p in model.parameters())
    receipt = {"surface": surface, "model": kind, "seed": seed, "epochs": EPOCHS,
               "batch_size": BATCH_SIZE, "learning_rate": LR, "weight_decay": WEIGHT_DECAY,
               "trainable_parameters": int(params), "epoch_loss": epoch_losses,
               "fit_seconds": time.perf_counter() - started, "model_sha256": sha256(model_path)}
    return model, y, receipt


def predict_split(torch, model, primitives, rows, surface, mean, scale, target_arrays):
    indices = np.asarray([row["idx"] for row in rows], dtype=np.int64)
    x = surface_matrix(primitives, indices, surface)
    device_x = torch.from_numpy(np.array(x, dtype=np.float32, order="C", copy=True)).to("cuda:0")
    device_x.sub_(torch.from_numpy(mean.copy()).to("cuda:0"))
    device_x.div_(torch.from_numpy(scale.copy()).to("cuda:0"))
    del x
    outputs = {name: [] for name in ("entity_types", "relation_types", "state_values", "goal_path_distance")}
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(device_x), 4096):
            logits = model(device_x[start:start + 4096])
            for name, value in logits.items():
                outputs[name].append(value.detach().cpu().numpy())
    predicted = {name: np.concatenate(chunks, axis=0) for name, chunks in outputs.items()}
    del device_x
    return predicted


def multilabel_metrics(logits: np.ndarray, truth: np.ndarray):
    pred = logits >= 0.0
    truth = truth.astype(bool)
    tp = np.logical_and(pred, truth).sum(axis=0)
    fp = np.logical_and(pred, ~truth).sum(axis=0)
    fn = np.logical_and(~pred, truth).sum(axis=0)
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / np.maximum(tp + fn, 1)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    present = (tp + fn) > 0
    micro = 2 * int(tp.sum()) / max(2 * int(tp.sum()) + int(fp.sum()) + int(fn.sum()), 1)
    exact = np.mean(np.all(pred == truth, axis=1))
    return {"rows": int(len(truth)), "micro_f1": float(micro),
            "macro_f1_present_classes": float(np.mean(f1[present])) if present.any() else None,
            "exact_set_match": float(exact), "class_names": list(range(truth.shape[1])),
            "support": (tp + fn).astype(int).tolist(), "tp": tp.astype(int).tolist(),
            "fp": fp.astype(int).tolist(), "fn": fn.astype(int).tolist()}


def categorical_metrics(logits: np.ndarray, truth: np.ndarray):
    mask = truth >= 0
    y = truth[mask]
    scores = logits[mask]
    pred = scores.argmax(axis=1) if len(scores) else np.empty(0, dtype=np.int64)
    classes = np.arange(len(PATH_CLASSES))
    cm = np.zeros((len(classes), len(classes)), dtype=np.int64)
    if len(y):
        np.add.at(cm, (y, pred), 1)
    support = cm.sum(axis=1)
    tp = np.diag(cm)
    precision = tp / np.maximum(cm.sum(axis=0), 1)
    recall = tp / np.maximum(support, 1)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    present = support > 0
    return {"rows": int(len(y)), "accuracy": float(np.mean(y == pred)) if len(y) else None,
            "balanced_accuracy_present_classes": float(np.mean(recall[present])) if present.any() else None,
            "macro_f1_present_classes": float(np.mean(f1[present])) if present.any() else None,
            "class_names": list(PATH_CLASSES), "support": support.tolist(),
            "class_recall": [float(recall[i]) if support[i] else None for i in classes],
            "confusion_matrix_true_rows_pred_cols": cm.tolist()}


def score_rows(predictions: dict, rows: list[dict], targets: dict):
    return {
        "entity_type_presence": multilabel_metrics(predictions["entity_types"], targets["entity_types"]),
        "relation_type_presence": multilabel_metrics(predictions["relation_types"], targets["relation_types"]),
        "state_value_presence": multilabel_metrics(predictions["state_values"], targets["state_values"]),
        "goal_path_distance": categorical_metrics(predictions["goal_path_distance"],
                                                   targets["goal_path_distance"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank-root", type=Path, required=True)
    parser.add_argument("--feature-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    bank_root, feature_dir, output = args.bank_root, args.feature_dir, args.output
    rowmap_path = feature_dir.parent / "rowmap.jsonl"
    rowmap = list(read_jsonl(rowmap_path))
    if [int(r["idx"]) for r in rowmap] != list(range(len(rowmap))):
        raise RuntimeError("rowmap indices are not a contiguous cache-order sequence")
    world_rows, world_hashes = load_world_rows(bank_root, rowmap)
    counts = {split: len(rows) for split, rows in world_rows.items()}
    primitives, extraction_seal, primitive_hashes = load_primitives(feature_dir, len(rowmap))
    packed = {split: packed_targets(rows) for split, rows in world_rows.items()}
    path_support = {split: Counter(PATH_CLASSES[int(x)] for x in packed[split]["goal_path_distance"] if x >= 0)
                    for split in SPLITS}
    print(json.dumps({"phase": "scoring_start", "world_rows": counts,
                      "path_target_support": {k: dict(v) for k, v in path_support.items()}}, sort_keys=True),
          flush=True)

    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this cached-surface scoring run")
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False

    reports = {"surfaces": {}, "training_seconds": 0.0, "scoring_seconds": 0.0}
    target_names = ("entity_types", "relation_types", "state_values", "goal_path_distance")
    for surface in SURFACES:
        surface_started = time.perf_counter()
        train_rows = world_rows["TRAIN"]
        train_idx = np.asarray([r["idx"] for r in train_rows], dtype=np.int64)
        train_x = surface_matrix(primitives, train_idx, surface)
        mean, scale = train_scaler(train_x)
        train_tensor = torch.from_numpy(np.array(train_x, dtype=np.float32, order="C", copy=True)).to("cuda:0")
        del train_x
        train_tensor.sub_(torch.from_numpy(mean.copy()).to("cuda:0"))
        train_tensor.div_(torch.from_numpy(scale.copy()).to("cuda:0"))
        y_train = {name: packed["TRAIN"][name] for name in target_names}
        kind_reports = {}
        scoring_started = time.perf_counter()
        for kind in ("linear", "tiny_mlp"):
            fit_started = time.perf_counter()
            model, _, fit_receipt = fit_model(torch, train_tensor, y_train, kind, surface, output)
            reports["training_seconds"] += fit_receipt["fit_seconds"]
            reports["surfaces"].setdefault(surface, {})[kind] = {"fit": fit_receipt, "metrics": {}}
            for split in SPLITS[1:]:
                split_targets = packed[split]
                pred = predict_split(torch, model, primitives, world_rows[split], surface, mean, scale,
                                     split_targets)
                metrics = score_rows(pred, world_rows[split], split_targets)
                reports["surfaces"][surface][kind]["metrics"][split] = metrics
                if split == "TEST-COMPOSITION":
                    reports["surfaces"][surface][kind]["metrics"]["TEST-COMPOSITION-path-only"] = {
                        "rows": metrics["goal_path_distance"]["rows"],
                        "goal_path_distance": metrics["goal_path_distance"],
                    }
                del pred
            # Renderer-family challenges aggregate primary TEST worlds only.
            test_rows = [r for split in SPLITS if split.startswith("TEST-") for r in world_rows[split]]
            test_target = {
                name: np.concatenate([packed[split][name] for split in SPLITS if split.startswith("TEST-")], axis=0)
                for name in target_names
            }
            family = np.concatenate([packed[split]["surface_family"] for split in SPLITS if split.startswith("TEST-")])
            family_metrics = {}
            for code in ("S7", "S8", "S9"):
                selected = family == code
                if not selected.any():
                    family_metrics[code] = {"rows": 0}
                    continue
                # Scores are recomputed in bounded batches to avoid retaining all test logits.
                selected_rows = [r for r, keep in zip(test_rows, selected) if keep]
                selected_targets = {
                    "entity_types": test_target["entity_types"][selected],
                    "relation_types": test_target["relation_types"][selected],
                    "state_values": test_target["state_values"][selected],
                    "goal_path_distance": test_target["goal_path_distance"][selected],
                }
                pred_family = predict_split(torch, model, primitives, selected_rows, surface, mean, scale,
                                            selected_targets)
                family_metrics[code] = score_rows(pred_family, selected_rows, selected_targets)
                del pred_family
            reports["surfaces"][surface][kind]["heldout_renderer_families"] = family_metrics
            del model
            torch.cuda.empty_cache()
        reports["surfaces"][surface]["input_dim"] = int(train_tensor.shape[1])
        reports["surfaces"][surface]["train_rows"] = int(len(train_tensor))
        reports["surfaces"][surface]["fit_and_score_seconds"] = time.perf_counter() - surface_started
        del train_tensor
        torch.cuda.empty_cache()
        print(json.dumps({"phase": "surface_complete", "surface": surface,
                          "seconds": reports["surfaces"][surface]["fit_and_score_seconds"]}), flush=True)

    report = {
        "schema": "phoenix.bank-v1-graph-capability-appendix/v1",
        "disposition": "ENGINEERING_APPENDIX_COMPLETED",
        "claim": "cached whole-row LFM surfaces support graph-level readouts; no node- or edge-local representation was evaluated",
        "backbone_reextraction": False,
        "fine_tuning": False,
        "retrieval": False,
        "test_truth_status": "BANK-v1 test truth was already opened/scored by the prior surface sweep; this is not fresh qualification",
        "bank_root": str(bank_root.resolve()),
        "bank_release": "BANK-v1",
        "source_world_hashes": world_hashes,
        "source_rowmap_sha256": sha256(rowmap_path),
        "source_rowmap_rows": len(rowmap),
        "primary_world_rows_by_split": counts,
        "feature_extraction_seal_sha256": sha256(feature_dir / "extraction-seal.json"),
        "feature_primitive_hashes_verified": primitive_hashes,
        "input_surfaces": list(SURFACES),
        "surface_input_dimensions": {k: reports["surfaces"][k]["input_dim"] for k in SURFACES},
        "target_definition": {
            "entity_type_presence": "set of entity types present in each canonical world",
            "relation_type_presence": "set of initial_state predicates present in each canonical world",
            "state_value_presence": "set of ACTIVE/INACTIVE values among initial STATE facts",
            "goal_path_distance": {"classes": list(PATH_CLASSES),
                                   "definition": "shortest undirected CONNECTED hop distance from an object's unique initial AT location to an AT goal destination; non-AT, unknown-object, or ambiguous-origin rows are excluded"},
        },
        "target_support_by_split": {split: dict(path_support[split]) for split in SPLITS},
        "model_contract": {"models": ["linear", "tiny_mlp"], "mlp_width": MLP_WIDTH,
                           "epochs": EPOCHS, "batch_size": BATCH_SIZE, "seed": SEED,
                           "optimizer": {"name": "AdamW", "lr": LR, "weight_decay": WEIGHT_DECAY},
                           "scaler": "train-only float64 sum/squared-sum population mean/std"},
        "surfaces": reports["surfaces"],
        "runtime_seconds": {"model_training_total": reports["training_seconds"],
                            "end_to_end": time.perf_counter() - started,
                            "device": torch.cuda.get_device_name(0),
                            "torch": torch.__version__},
    }
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "graph-capability-results.json"
    write_json(report_path, report)
    print(json.dumps({"phase": "complete", "report": str(report_path.resolve()),
                      "sha256": sha256(report_path), "seconds": report["runtime_seconds"]["end_to_end"]}),
          flush=True)


if __name__ == "__main__":
    main()
