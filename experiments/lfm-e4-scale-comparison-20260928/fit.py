"""Fit the historical five independent E4 linear observers for either substrate."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from common import OPTIMIZER, REGULARIZATION, TASKS, feature_map, read_jsonl, sha256, task_eligible


def welford(features: np.memmap, indices: np.ndarray, dimension: int) -> tuple[np.ndarray, np.ndarray]:
    count = 0
    mean = np.zeros(dimension, dtype=np.float64)
    m2 = np.zeros(dimension, dtype=np.float64)
    for start in range(0, len(indices), 2048):
        chunk = np.asarray(features[indices[start : start + 2048]], dtype=np.float64)
        chunk_mean = chunk.mean(axis=0, dtype=np.float64)
        centered = chunk - chunk_mean
        chunk_m2 = np.einsum("ij,ij->j", centered, centered, dtype=np.float64, optimize=True)
        if count == 0:
            count = len(chunk)
            mean = chunk_mean
            m2 = chunk_m2
            continue
        combined = count + len(chunk)
        delta = chunk_mean - mean
        mean += delta * (len(chunk) / combined)
        m2 += chunk_m2 + delta * delta * (count * len(chunk) / combined)
        count = combined
    if count != len(indices) or not count:
        raise RuntimeError("invalid scaler row count")
    scale = np.sqrt(np.maximum(m2 / count, 0.0))
    scale[scale == 0.0] = 1.0
    if not np.isfinite(mean).all() or not np.isfinite(scale).all():
        raise RuntimeError("nonfinite scaler")
    return mean.astype("<f4"), scale.astype("<f4")


def fit_head(name: str, features: np.memmap, indices: np.ndarray, labels: np.ndarray,
             dimension: int, output: Path) -> dict:
    import torch
    import torch.nn.functional as F

    classes = TASKS[name][1]
    mean, scale = welford(features, indices, dimension)
    (output / f"{name}.mean.f32le").write_bytes(mean.tobytes())
    (output / f"{name}.scale.f32le").write_bytes(scale.tobytes())
    host = np.array(features[indices], dtype=np.float32, order="C", copy=True)
    x = torch.from_numpy(host).to("cuda:0")
    del host
    y = torch.from_numpy(labels.astype(np.int64, copy=False)).to("cuda:0")
    x.sub_(torch.from_numpy(mean.copy()).to("cuda:0"))
    x.div_(torch.from_numpy(scale.copy()).to("cuda:0"))
    if not bool(torch.isfinite(x).all()):
        raise RuntimeError(f"nonfinite standardized features for {name}")
    linear = torch.nn.Linear(dimension, classes, bias=True, device="cuda:0", dtype=torch.float32)
    with torch.no_grad():
        linear.weight.zero_()
        linear.bias.zero_()
    optimizer = torch.optim.LBFGS(
        linear.parameters(), lr=OPTIMIZER["learning_rate"],
        max_iter=OPTIMIZER["max_iter"], max_eval=OPTIMIZER["max_eval"],
        tolerance_grad=OPTIMIZER["tolerance_grad"],
        tolerance_change=OPTIMIZER["tolerance_change"],
        history_size=OPTIMIZER["history_size"], line_search_fn=OPTIMIZER["line_search"],
    )
    initial = float((F.cross_entropy(linear(x), y)
                     + 0.5 * REGULARIZATION * linear.weight.square().sum()).detach().cpu())

    def closure():
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(linear(x), y)
        loss = loss + 0.5 * REGULARIZATION * linear.weight.square().sum()
        loss.backward()
        return loss

    began = time.perf_counter()
    optimizer.step(closure)
    seconds = time.perf_counter() - began
    with torch.no_grad():
        final = float((F.cross_entropy(linear(x), y)
                       + 0.5 * REGULARIZATION * linear.weight.square().sum()).cpu())
        weight = np.asarray(linear.weight.detach().cpu().numpy(), dtype="<f4", order="C")
        bias = np.asarray(linear.bias.detach().cpu().numpy(), dtype="<f4", order="C")
    if not np.isfinite(final) or not np.isfinite(weight).all() or not np.isfinite(bias).all():
        raise RuntimeError(f"nonfinite {name} fit")
    (output / f"{name}.weight.f32le").write_bytes(weight.tobytes())
    (output / f"{name}.bias.f32le").write_bytes(bias.tobytes())
    state = optimizer.state[linear.weight]
    result = {
        "task": name, "rows": len(indices), "class_counts": np.bincount(labels, minlength=classes).tolist(),
        "classes": classes, "initial_objective": initial, "final_objective": final,
        "fit_seconds": seconds, "optimizer_iterations": int(state.get("n_iter", 0)),
        "optimizer_function_evaluations": int(state.get("func_evals", 0)),
        "trainable_parameters": int(weight.size + bias.size),
    }
    del x, y, linear, optimizer
    torch.cuda.empty_cache()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--row-map", type=Path, required=True)
    parser.add_argument("--index-field", choices=("e1_index", "compact_index"), required=True)
    parser.add_argument("--feature-rows", type=int, required=True)
    parser.add_argument("--dimension", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arm", required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("fit output already exists")
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("historical E3 fitting ABI requires CUDA:0")
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    features = feature_map(args.features, args.feature_rows, args.dimension)
    rows = list(read_jsonl(args.row_map))
    if len(rows) != 85_204 or sum(r["partition"] == "TRAIN" for r in rows) != 76_804:
        raise RuntimeError("shared E1 FIT split does not match its seal")
    tasks: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name, (field, classes) in TASKS.items():
        eligible = [r for r in rows if r["partition"] == "TRAIN" and task_eligible(r, name)]
        indices = np.asarray([r[args.index_field] for r in eligible], dtype=np.int64)
        labels = np.asarray([r[field] for r in eligible], dtype=np.int64)
        if set(labels.tolist()) != set(range(classes)):
            raise RuntimeError(f"{name} lacks a training class")
        tasks[name] = indices, labels
    args.output.mkdir(parents=True)
    began = time.perf_counter()
    heads = {}
    for name, (indices, labels) in tasks.items():
        heads[name] = fit_head(name, features, indices, labels, args.dimension, args.output)
        print(json.dumps({"arm": args.arm, "fit_head": name, **heads[name]}), flush=True)
    files = sorted(args.output.glob("*.f32le"))
    receipt = {
        "schema": "phoenix.e4-scale-five-head-fit/v1",
        "arm": args.arm,
        "dimension": args.dimension,
        "train_only": True,
        "source": "E1 FIT-derived TRAIN, quartet-disjoint from DEV; historical E1 TEST excluded",
        "surface": "V1_FINAL_POSITION",
        "scaler": "train-only float64 chunked Welford population mean/scale; zero scales become 1",
        "optimizer": {"name": "PyTorch LBFGS", **OPTIMIZER},
        "l2_weight_only": REGULARIZATION,
        "heads": heads,
        "total_trainable_parameters": sum(h["trainable_parameters"] for h in heads.values()),
        "total_fit_seconds": time.perf_counter() - began,
        "row_map_sha256": sha256(args.row_map),
        "features_sha256": sha256(args.features),
        "files": {p.name: sha256(p) for p in files},
    }
    (args.output / "fit-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
