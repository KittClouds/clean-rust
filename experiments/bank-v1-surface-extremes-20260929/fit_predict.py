"""Train the shared typed linear readout on each frozen 230M surface."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np

from common import (ALL_HEADS, CATEGORICAL_HEADS, MULTILABEL_HEADS, SEED,
                    SURFACE_ORDER, encode_targets, input_paths, read_jsonl,
                    sha256, surface_batch, surface_dim, targets_from_rows,
                    write_json)
from extract import configure_torch

EPOCHS = 8
BATCH_SIZE = 2048
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
PREDICT_BATCH_SIZE = 2048
TRAIN_SPLIT = "TRAIN"
DEV_SPLIT = "DEV"

def load_targets(path: Path, expected: int):
    values = {}
    masks = {}
    for name, classes in CATEGORICAL_HEADS.items():
        values[name] = np.full(expected, -1, dtype=np.int16)
        masks[name] = np.zeros(expected, dtype=np.bool_)
    for name, classes in MULTILABEL_HEADS.items():
        values[name] = np.zeros((expected, len(classes)), dtype=np.float32)
        masks[name] = np.zeros(expected, dtype=np.bool_)
    seen = 0
    for i, row in enumerate(read_jsonl(path)):
        if i >= expected:
            raise RuntimeError(f"too many supervised rows in {path}")
        for name, target in encode_targets(row).items():
            if name in CATEGORICAL_HEADS:
                values[name][i] = int(target)
                masks[name][i] = True
            elif name in MULTILABEL_HEADS:
                values[name][i, np.asarray(target, dtype=np.int64)] = 1.0
                masks[name][i] = True
        seen += 1
    if seen != expected:
        raise RuntimeError(f"supervised rows {seen} != expected {expected}: {path}")
    return values, masks

def load_primitives(feature_dir: Path, rows: int, hidden: int):
    names = ("final_token", "full_mean", "first_token", "layer_m4_final",
             "layer_m3_final", "layer_m2_final", "middle_final")
    arrays = {}
    for name in names:
        path = feature_dir / f"{name}.npy"
        arr = np.load(path, mmap_mode="r", allow_pickle=False)
        if arr.shape != (rows, hidden) or arr.dtype != np.dtype("<f4"):
            raise RuntimeError(f"bad primitive {name}: {arr.shape}, {arr.dtype}")
        arrays[name] = arr
    projection = np.load(feature_dir / "random-projection-1024x256.npy", mmap_mode="r",
                         allow_pickle=False)
    if projection.shape != (hidden, 256):
        raise RuntimeError("random projection shape mismatch")
    return arrays, projection

def train_scaler(primitives, projection, surface: str, rows: int, hidden: int):
    count = 0
    mean = np.zeros(surface_dim(surface, hidden), dtype=np.float64)
    m2 = np.zeros_like(mean)
    for start in range(0, rows, 1024):
        stop = min(start + 1024, rows)
        x = surface_batch(primitives, start, stop, surface, projection).astype(np.float64)
        cm = x.mean(axis=0, dtype=np.float64)
        centered = x - cm
        cm2 = np.einsum("ij,ij->j", centered, centered, dtype=np.float64, optimize=True)
        if count == 0:
            count, mean, m2 = len(x), cm, cm2
        else:
            n = len(x)
            total = count + n
            delta = cm - mean
            mean += delta * (n / total)
            m2 += cm2 + delta * delta * (count * n / total)
            count = total
    if count != rows or count == 0:
        raise RuntimeError("train-only scaler row count mismatch")
    scale = np.sqrt(np.maximum(m2 / count, 0.0))
    scale[scale == 0] = 1.0
    if not np.isfinite(mean).all() or not np.isfinite(scale).all():
        raise RuntimeError(f"nonfinite scaler for {surface}")
    return mean.astype("<f4"), scale.astype("<f4")

def make_model(torch, dimension: int):
    import torch.nn as nn
    class TypedLinearReadout(nn.Module):
        def __init__(self):
            super().__init__()
            self.heads = nn.ModuleDict({
                name: nn.Linear(dimension, len(classes))
                for name, classes in {**CATEGORICAL_HEADS, **MULTILABEL_HEADS}.items()
            })
        def forward(self, x):
            return {name: layer(x) for name, layer in self.heads.items()}
    return TypedLinearReadout().to(device="cuda:0", dtype=torch.float32)

def torch_targets(torch, values, masks, device):
    y = {}
    mask_t = {}
    for name in ALL_HEADS:
        dtype = torch.long if name in CATEGORICAL_HEADS else torch.float32
        y[name] = torch.as_tensor(values[name], dtype=dtype, device=device)
        mask_t[name] = torch.as_tensor(masks[name], dtype=torch.bool, device=device)
    return y, mask_t

def fit_surface(torch, surface, primitives, projection, hidden, train_rows,
                train_values, train_masks, output_dir):
    import torch.nn.functional as F
    dim = surface_dim(surface, hidden)
    mean, scale = train_scaler(primitives, projection, surface, train_rows, hidden)
    host_x = surface_batch(primitives, 0, train_rows, surface, projection)
    x = torch.from_numpy(np.array(host_x, dtype=np.float32, order="C", copy=True)).to("cuda:0")
    x.sub_(torch.from_numpy(mean.copy()).to("cuda:0"))
    x.div_(torch.from_numpy(scale.copy()).to("cuda:0"))
    if not bool(torch.isfinite(x).all()):
        raise RuntimeError(f"nonfinite standardized train features: {surface}")
    y, masks = torch_targets(torch, train_values, train_masks, "cuda:0")
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    model = make_model(torch, dim)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE,
                                  weight_decay=WEIGHT_DECAY, foreach=False)
    n = train_rows
    epoch_losses = []
    started = time.perf_counter()
    for epoch in range(EPOCHS):
        generator = np.random.default_rng(SEED + epoch)
        order = generator.permutation(n)
        total_loss = 0.0
        steps = 0
        model.train()
        for begin in range(0, n, BATCH_SIZE):
            ids_np = order[begin:begin + BATCH_SIZE]
            ids = torch.as_tensor(ids_np, dtype=torch.long, device="cuda:0")
            logits = model(x.index_select(0, ids))
            terms = []
            for name in ALL_HEADS:
                active = masks[name].index_select(0, ids)
                if not bool(active.any()):
                    continue
                if name in CATEGORICAL_HEADS:
                    yy = y[name].index_select(0, ids)
                    terms.append(F.cross_entropy(logits[name][active], yy[active]))
                else:
                    yy = y[name].index_select(0, ids)
                    terms.append(F.binary_cross_entropy_with_logits(
                        logits[name][active], yy[active], reduction="mean"))
            if not terms:
                raise RuntimeError("batch has no supervised head")
            loss = torch.stack(terms).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach().cpu())
            steps += 1
        epoch_loss = total_loss / max(steps, 1)
        epoch_losses.append(epoch_loss)
        print(json.dumps({"phase": "fit", "surface": surface, "epoch": epoch + 1,
                          "epochs": EPOCHS, "mean_loss": epoch_loss}), flush=True)

    surface_dir = output_dir / "models"
    surface_dir.mkdir(parents=True, exist_ok=True)
    model_path = surface_dir / f"{surface}.npz"
    if model_path.exists():
        raise RuntimeError(f"model checkpoint already exists: {model_path}")
    payload = {"mean": mean, "scale": scale}
    head_sizes = {}
    for name, layer in model.heads.items():
        payload[f"{name}.weight"] = np.asarray(layer.weight.detach().cpu().numpy(), dtype="<f4")
        payload[f"{name}.bias"] = np.asarray(layer.bias.detach().cpu().numpy(), dtype="<f4")
        head_sizes[name] = int(payload[f"{name}.weight"].size + payload[f"{name}.bias"].size)
    np.savez_compressed(model_path, **payload)
    fit_receipt = {
        "surface": surface, "input_dimension": dim, "train_rows": train_rows,
        "heads": head_sizes, "trainable_parameters": sum(head_sizes.values()),
        "normalization": "float64 chunked Welford population mean/std from TRAIN only; zero std -> 1",
        "optimizer": {"name": "AdamW", "epochs": EPOCHS, "batch_size": BATCH_SIZE,
                      "learning_rate": LEARNING_RATE, "weight_decay": WEIGHT_DECAY,
                      "head_loss": "equal mean of active task losses per batch"},
        "seed": SEED, "epoch_losses": epoch_losses,
        "fit_seconds": time.perf_counter() - started,
        "model_path": str(model_path.resolve()), "model_sha256": sha256(model_path),
    }
    write_json(surface_dir / f"{surface}-fit.json", fit_receipt)
    del x, y, masks, model, optimizer
    torch.cuda.empty_cache()
    return model_path, fit_receipt

def load_model_from_npz(torch, path: Path, dimension: int):
    model = make_model(torch, dimension)
    archive = np.load(path, allow_pickle=False)
    state = {}
    for name, layer in model.heads.items():
        state["heads." + name + ".weight"] = torch.from_numpy(
            archive[name + ".weight"].copy()).to("cuda:0")
        state["heads." + name + ".bias"] = torch.from_numpy(
            archive[name + ".bias"].copy()).to("cuda:0")
    model.load_state_dict(state, strict=True)
    model.eval()
    mean = archive["mean"].copy()
    scale = archive["scale"].copy()
    return model, mean, scale

def predict_surface(torch, surface, model_path, primitives, projection, hidden,
                    rowmap, train_rows, dev_rows, output_dir):
    dim = surface_dim(surface, hidden)
    model, mean, scale = load_model_from_npz(torch, model_path, dim)
    start = train_rows
    stop = len(rowmap)
    pred_dir = output_dir / "predictions"
    pred_dir.mkdir(exist_ok=True)
    path = pred_dir / f"{surface}.jsonl"
    if path.exists():
        raise RuntimeError(f"prediction file already exists: {path}")
    with path.open("w", encoding="utf-8", newline="\n") as dst, torch.inference_mode():
        for begin in range(start, stop, PREDICT_BATCH_SIZE):
            end = min(begin + PREDICT_BATCH_SIZE, stop)
            host_x = surface_batch(primitives, begin, end, surface, projection)
            host_x -= mean
            host_x /= scale
            xb = torch.from_numpy(np.asarray(host_x, dtype=np.float32, order="C")).to("cuda:0")
            logits = model(xb)
            cpu_logits = {name: value.detach().cpu().numpy() for name, value in logits.items()}
            rows = []
            for offset, meta in enumerate(rowmap[begin:end]):
                record = {"idx": meta["idx"], "row_id": meta["row_id"],
                          "split": meta["split"], "surface_family": meta["surface_family"],
                          "paired_world": meta.get("paired_world")}
                for name, classes in CATEGORICAL_HEADS.items():
                    score = cpu_logits[name][offset]
                    idx = int(np.argmax(score))
                    record[name] = classes[idx]
                    record[name + "_confidence"] = float(
                        np.exp(score[idx] - np.max(score)) / np.exp(score - np.max(score)).sum()
                    )
                for name, classes in MULTILABEL_HEADS.items():
                    score = cpu_logits[name][offset]
                    probs = 1.0 / (1.0 + np.exp(-np.clip(score, -40, 40)))
                    record[name] = [classes[i] for i, value in enumerate(probs) if value >= 0.5]
                dst.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            if end % (PREDICT_BATCH_SIZE * 4) < PREDICT_BATCH_SIZE:
                print(json.dumps({"phase": "predict", "surface": surface, "rows": end - start,
                                  "total": stop - start}), flush=True)
    pred_rows = stop - start
    prediction_receipt = {
        "surface": surface, "path": str(path.resolve()), "sha256": sha256(path),
        "rows": pred_rows, "first_idx": start, "last_idx_exclusive": stop,
        "partitions": {"DEV": dev_rows, "TEST": pred_rows - dev_rows},
        "truth_join_performed": False,
    }
    write_json(pred_dir / f"{surface}-seal.json", prediction_receipt)
    del model
    torch.cuda.empty_cache()
    return prediction_receipt

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch = configure_torch()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA:0 required for head fitting")
    output_dir = args.output
    feature_dir = output_dir / "features"
    extraction_path = feature_dir / "extraction-seal.json"
    if not extraction_path.is_file():
        raise FileNotFoundError("feature extraction must finish and seal before fitting")
    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    if extraction.get("truth_joined") is not False:
        raise RuntimeError("unexpected truth join in extraction receipt")
    rows = int(extraction["rows"])
    hidden = int(extraction["hidden_size"])
    if extraction["model"]["weights_sha256"] != sha256(args.model / "model.safetensors"):
        raise RuntimeError("model weights do not match extraction")
    source_lock = json.loads((output_dir / "source-lock.json").read_text(encoding="utf-8"))
    if source_lock["release"] != "BANK-v1":
        raise RuntimeError("wrong BANK release")
    paths = dict(input_paths(args.bank_root))
    train_rows = int(next(x["rows_expected"] for x in source_lock["files"] if x["split"] == "TRAIN"))
    dev_rows = int(next(x["rows_expected"] for x in source_lock["files"] if x["split"] == "DEV"))
    rowmap = list(read_jsonl(output_dir / "rowmap.jsonl"))
    if len(rowmap) != rows or any(r["idx"] != i for i, r in enumerate(rowmap)):
        raise RuntimeError("rowmap count/order mismatch")
    if any(r["split"] != "TRAIN" for r in rowmap[:train_rows]):
        raise RuntimeError("TRAIN rows are not a contiguous prefix")
    if any(r["split"] != "DEV" for r in rowmap[train_rows:train_rows + dev_rows]):
        raise RuntimeError("DEV rows are not contiguous after TRAIN")
    if rows != len(rowmap):
        raise RuntimeError("row count mismatch")
    train_values, train_masks = load_targets(paths["TRAIN"], train_rows)
    primitives, projection = load_primitives(feature_dir, rows, hidden)
    result_receipts = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for surface in SURFACE_ORDER:
        model_path = output_dir / "models" / f"{surface}.npz"
        fit_receipt_path = output_dir / "models" / f"{surface}-fit.json"
        if model_path.exists() or fit_receipt_path.exists():
            if not model_path.is_file() or not fit_receipt_path.is_file():
                raise RuntimeError(f"incomplete existing fit artifacts for {surface}")
            fit_receipt = json.loads(fit_receipt_path.read_text(encoding="utf-8"))
            if (fit_receipt.get("surface") != surface
                    or fit_receipt.get("train_rows") != train_rows
                    or fit_receipt.get("seed") != SEED
                    or fit_receipt.get("model_sha256") != sha256(model_path)):
                raise RuntimeError(f"existing fit receipt mismatch for {surface}")
        else:
            model_path, fit_receipt = fit_surface(torch, surface, primitives, projection,
                                                  hidden, train_rows, train_values,
                                                  train_masks, output_dir)
        pred_receipt = predict_surface(torch, surface, model_path, primitives, projection,
                                       hidden, rowmap, train_rows, dev_rows, output_dir)
        result_receipts.append({"fit": fit_receipt, "predictions": pred_receipt})
        print(json.dumps({"phase": "surface_complete", "surface": surface,
                          "prediction_sha256": pred_receipt["sha256"]}), flush=True)
    if {x["fit"]["surface"] for x in result_receipts} != set(SURFACE_ORDER):
        raise RuntimeError("surface roster incomplete")
    receipt = {
        "schema": "phoenix.bank-v1-230m-surface-sweep-predictions/v1",
        "surface_sweep": "BANK-v1-230M-SURFACE-EXTREMES-2026-09-29",
        "surface_order": SURFACE_ORDER, "bank_release": "BANK-v1",
        "train_rows": train_rows, "dev_rows": dev_rows,
        "prediction_rows_per_surface": len(rowmap) - train_rows,
        "hidden_size": hidden, "source_lock_sha256": source_lock["source_lock_sha256"],
        "extraction_seal_sha256": sha256(extraction_path),
        "truth_join_performed": False,
        "arms": [{"surface": x["fit"]["surface"],
                  "fit_receipt_sha256": sha256(output_dir / "models" / f'{x["fit"]["surface"]}-fit.json'),
                  "model_sha256": x["fit"]["model_sha256"],
                  "prediction_seal_sha256": sha256(output_dir / "predictions" / f'{x["fit"]["surface"]}-seal.json'),
                  "prediction_sha256": x["predictions"]["sha256"]}
                 for x in result_receipts],
        "training_contract": {"epochs": EPOCHS, "batch_size": BATCH_SIZE,
                              "learning_rate": LEARNING_RATE, "weight_decay": WEIGHT_DECAY,
                              "seed": SEED, "test_labels_used": False},
    }
    write_json(output_dir / "all-surfaces-prediction-seal.json", receipt)
    print(json.dumps({"phase": "prediction_seal_complete", "surfaces": len(result_receipts),
                      "seal_sha256": sha256(output_dir / "all-surfaces-prediction-seal.json"),
                      "truth_join_performed": False}), flush=True)

if __name__ == "__main__":
    main()
