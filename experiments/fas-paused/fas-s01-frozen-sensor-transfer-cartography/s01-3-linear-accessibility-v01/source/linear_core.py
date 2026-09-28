from __future__ import annotations

import os
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import numpy as np
import torch
import torch.nn.functional as functional


def configure_determinism(expected_device: str = "NVIDIA GeForce RTX 3080") -> torch.device:
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("the frozen S01-3 CUDA execution device is unavailable")
    if torch.cuda.get_device_name(0) != expected_device:
        raise RuntimeError("CUDA device identity differs from the frozen S01-3 contract")
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_float32_matmul_precision("highest")
    torch.cuda.manual_seed_all(0)
    return torch.device("cuda:0")


def feature_scaler(matrix: np.ndarray, row_indices: np.ndarray, chunk_rows: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Compute training-only population moments with chunked float64 Welford merges."""
    if len(row_indices) == 0:
        raise RuntimeError("cannot standardize an empty fit set")
    dimension = matrix.shape[1]
    count = 0
    mean = np.zeros(dimension, dtype=np.float64)
    m2 = np.zeros(dimension, dtype=np.float64)
    for start in range(0, len(row_indices), chunk_rows):
        indices = row_indices[start : start + chunk_rows]
        batch = np.asarray(matrix[indices], dtype=np.float64)
        if not np.isfinite(batch).all():
            raise RuntimeError("non-finite feature value in a sealed training row")
        batch_count = len(batch)
        batch_mean = batch.mean(axis=0, dtype=np.float64)
        centered = batch - batch_mean
        batch_m2 = np.einsum("ij,ij->j", centered, centered, optimize=True)
        delta = batch_mean - mean
        combined = count + batch_count
        mean += delta * (batch_count / combined)
        m2 += batch_m2 + delta * delta * (count * batch_count / combined)
        count = combined
    scale = np.sqrt(m2 / count)
    scale[scale == 0.0] = 1.0
    if not np.isfinite(mean).all() or not np.isfinite(scale).all() or np.any(scale <= 0):
        raise RuntimeError("training-only feature scaler contains invalid values")
    return mean, scale


def standardized_tensor(
    matrix: np.ndarray,
    row_indices: np.ndarray,
    mean: np.ndarray,
    scale: np.ndarray,
    device: torch.device,
) -> torch.Tensor:
    raw = np.ascontiguousarray(matrix[row_indices], dtype=np.float32)
    if not np.isfinite(raw).all():
        raise RuntimeError("non-finite feature value in selected sealed rows")
    tensor = torch.from_numpy(raw).to(device=device, dtype=torch.float32)
    del raw
    mean32 = torch.as_tensor(mean, dtype=torch.float32, device=device)
    scale32 = torch.as_tensor(scale, dtype=torch.float32, device=device)
    if bool(torch.any(scale32 == 0).item()):
        raise RuntimeError("a nonzero frozen feature scale underflowed in float32")
    tensor.sub_(mean32).div_(scale32)
    if not bool(torch.isfinite(tensor).all().item()):
        raise RuntimeError("standardization produced non-finite values")
    return tensor


def fit_probe(
    x_train: torch.Tensor,
    y_raw: np.ndarray,
    regularization: float = 1e-4,
    max_iter: int = 300,
    max_eval: int = 375,
    tolerance_grad: float = 1e-7,
    tolerance_change: float = 1e-9,
    history_size: int = 10,
) -> dict[str, object]:
    classes = np.unique(y_raw).astype(np.int64)
    if len(classes) < 2 or len(y_raw) != len(x_train):
        raise RuntimeError("probe fit labels or rows are invalid")
    lookup = {int(value): index for index, value in enumerate(classes)}
    y = torch.as_tensor(np.fromiter((lookup[int(v)] for v in y_raw), dtype=np.int64), device=x_train.device)
    weights = torch.nn.Parameter(torch.zeros((len(classes), x_train.shape[1]), dtype=torch.float32, device=x_train.device))
    bias = torch.nn.Parameter(torch.zeros(len(classes), dtype=torch.float32, device=x_train.device))
    optimizer = torch.optim.LBFGS(
        [weights, bias],
        lr=1.0,
        max_iter=max_iter,
        max_eval=max_eval,
        tolerance_grad=tolerance_grad,
        tolerance_change=tolerance_change,
        history_size=history_size,
        line_search_fn="strong_wolfe",
    )

    def closure() -> torch.Tensor:
        optimizer.zero_grad(set_to_none=True)
        logits = functional.linear(x_train, weights, bias)
        loss = functional.cross_entropy(logits, y)
        loss = loss + (0.5 * regularization) * torch.sum(weights * weights)
        loss.backward()
        return loss

    optimizer.step(closure)
    final_logits = functional.linear(x_train, weights, bias)
    final_loss = functional.cross_entropy(final_logits, y) + (0.5 * regularization) * torch.sum(weights * weights)
    grad_weights, grad_bias = torch.autograd.grad(final_loss, (weights, bias), retain_graph=False)
    grad_norm = torch.sqrt(torch.sum(grad_weights * grad_weights) + torch.sum(grad_bias * grad_bias))
    state = optimizer.state[weights]
    n_iter = int(state.get("n_iter", 0))
    func_evals = int(state.get("func_evals", 0))
    return {
        "classes": classes,
        "weights": weights.detach().cpu().numpy().astype("<f4", copy=True),
        "bias": bias.detach().cpu().numpy().astype("<f4", copy=True),
        "objective": float(final_loss.item()),
        "gradient_norm": float(grad_norm.item()),
        "iterations": n_iter,
        "function_evaluations": func_evals,
        "iteration_limit_reached": n_iter >= max_iter,
    }


def predict_probabilities(x: torch.Tensor, weights: np.ndarray, bias: np.ndarray, batch_rows: int = 16384) -> np.ndarray:
    w = torch.as_tensor(weights, dtype=torch.float32, device=x.device)
    b = torch.as_tensor(bias, dtype=torch.float32, device=x.device)
    pieces: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, len(x), batch_rows):
            logits = functional.linear(x[start : start + batch_rows], w, b)
            probs = torch.softmax(logits, dim=1).cpu().numpy().astype("<f4", copy=True)
            pieces.append(probs)
    if not pieces:
        return np.empty((0, len(bias)), dtype="<f4")
    return np.concatenate(pieces, axis=0)


def classification_metrics(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    classes: np.ndarray,
    probability_floor: float = 1e-7,
) -> dict[str, object]:
    if len(y_true) != len(probabilities) or len(y_true) == 0:
        raise RuntimeError("metric input is empty or has mismatched rows")
    predicted = classes[probabilities.argmax(axis=1)]
    class_to_index = {int(value): i for i, value in enumerate(classes)}
    confusion = np.zeros((len(classes), len(classes)), dtype=np.int64)
    for truth, pred in zip(y_true, predicted, strict=True):
        confusion[class_to_index[int(truth)], class_to_index[int(pred)]] += 1
    supports = confusion.sum(axis=1)
    recalls = np.divide(
        np.diag(confusion), supports, out=np.full(len(classes), np.nan, dtype=np.float64), where=supports > 0
    )
    true_col = np.fromiter((class_to_index[int(v)] for v in y_true), dtype=np.int64, count=len(y_true))
    clipped = np.maximum(probabilities[np.arange(len(y_true)), true_col].astype(np.float64), probability_floor)
    one_hot = np.zeros_like(probabilities, dtype=np.float64)
    one_hot[np.arange(len(y_true)), true_col] = 1.0
    per_row_brier = np.square(probabilities.astype(np.float64) - one_hot).sum(axis=1)
    supported = supports > 0
    return {
        "support": int(len(y_true)),
        "accuracy": float(np.mean(predicted == y_true)),
        "balanced_accuracy": float(np.nanmean(recalls)),
        "multiclass_log_loss": float(-np.log(clipped).mean()),
        "multiclass_brier_score": float(per_row_brier.mean()),
        "class_ids": [int(v) for v in classes],
        "class_support": [int(v) for v in supports],
        "per_class_recall": [None if not np.isfinite(v) else float(v) for v in recalls],
        "confusion_matrix": confusion.tolist(),
        "balanced_accuracy_classes": int(supported.sum()),
    }


def synthetic_self_test() -> dict[str, object]:
    """Exercise the exact probe family on generated vectors only."""
    device = configure_determinism()
    generator = np.random.default_rng(270923)
    dimension = 24
    prototypes = generator.normal(0.0, 2.0, size=(3, dimension)).astype(np.float32)
    labels = np.repeat(np.arange(3, dtype=np.int64), 96)
    features = prototypes[labels] + generator.normal(0.0, 0.25, size=(len(labels), dimension)).astype(np.float32)
    mean = features.mean(axis=0, dtype=np.float64)
    scale = features.std(axis=0, dtype=np.float64)
    scale[scale == 0] = 1
    x = torch.as_tensor(((features - mean.astype(np.float32)) / scale.astype(np.float32)), device=device)
    first = fit_probe(x, labels)
    first_prob = predict_probabilities(x, first["weights"], first["bias"])
    second = fit_probe(x, labels)
    second_prob = predict_probabilities(x, second["weights"], second["bias"])
    accuracy = float(np.mean(first_prob.argmax(axis=1) == labels))
    weight_delta = float(np.max(np.abs(first["weights"] - second["weights"])))
    probability_delta = float(np.max(np.abs(first_prob - second_prob)))
    if accuracy < 0.98 or weight_delta != 0.0 or probability_delta != 0.0:
        raise RuntimeError("synthetic deterministic linear-probe qualification failed")
    return {
        "synthetic_only": True,
        "accuracy": accuracy,
        "repeat_weight_max_abs_delta": weight_delta,
        "repeat_probability_max_abs_delta": probability_delta,
        "optimizer_iterations": first["iterations"],
        "optimizer_limit_reached": first["iteration_limit_reached"],
        "device": torch.cuda.get_device_name(0),
        "torch_version": torch.__version__,
    }
