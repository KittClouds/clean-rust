"""F4-PRECISION-01 qualification analysis.

Arms A/B/C change precision only. All classifiers are fitted on the four
qualification blocks with the frozen hidden topology and training procedure.
The script also writes arm C as a durable float32-quantize/float64-storage
stream, so the precision intervention has a separately auditable artifact.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

import numpy as np


STUDY = Path(__file__).resolve().parents[1]
RUN = STUDY / "runs/qualification-v2/f4-precision-01-attempt-02"
ANALYSIS_OUT = STUDY / "runs/qualification-v2/f4-precision-01-analysis-v0.1.8"
ARM_A = STUDY / "runs/qualification-v2/f4-features-v1"
ARM_B = RUN / "arm-b-f64"
ARM_C = RUN / "arm-c-f32-features-f64-model"
SPEC_PATH = STUDY / "F4-PRECISION-01-CONTRACT-v0.1.8.json"
MAGIC_A = b"FLYREACH3F4\0"
MAGIC_B = b"FLYREACH3P64\0"
MAGIC_C = b"FLYREACH3C64\0"
WIDTH = 80
ROW_MODULUS = 256
MARGIN_GAMMAS = (1e-12, 1e-11, 1e-10, 1e-9, 1e-8)
EPOCHS = 200
LEARNING_RATE = 0.001
BATCH_SIZE = 2048
BASE_SEED = 304000


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_old_encoder():
    source = STUDY / "scripts/f4_encoder_qualification.py"
    spec = importlib.util.spec_from_file_location("reach03_frozen_f4_encoder", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen F4 encoder")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_header(raw: bytes, magic: bytes):
    if raw[: len(magic)] != magic:
        raise RuntimeError(f"bad feature-stream magic, expected {magic!r}")
    pos = len(magic)
    version, width = struct.unpack_from("<IH", raw, pos)
    pos += 6
    if version != 1 or width != WIDTH:
        raise RuntimeError(f"unsupported feature stream version={version} width={width}")
    size, = struct.unpack_from("<H", raw, pos)
    pos += 2
    substrate = raw[pos : pos + size].decode("utf-8")
    pos += size
    size, = struct.unpack_from("<H", raw, pos)
    pos += 2
    side = raw[pos : pos + size].decode("utf-8")
    pos += size
    block, = struct.unpack_from("<Q", raw, pos)
    pos += 8
    return (substrate, side, int(block)), pos


def read_a(path: Path):
    raw = path.read_bytes()
    cell, pos = read_header(raw, MAGIC_A)
    record = 4 + 4 + 8 + 1 + WIDTH * 4
    if (len(raw) - pos) % record:
        raise RuntimeError(f"truncated arm A stream: {path}")
    n = (len(raw) - pos) // record
    trial = np.empty(n, np.int32)
    coordinate = np.empty(n, np.int32)
    q = np.empty(n, np.float64)
    y = np.empty(n, np.int8)
    x = np.empty((n, WIDTH), np.float32)
    for i in range(n):
        trial[i], coordinate[i] = struct.unpack_from("<II", raw, pos)
        pos += 8
        q[i], = struct.unpack_from("<d", raw, pos)
        pos += 8
        y[i], = struct.unpack_from("<b", raw, pos)
        pos += 1
        x[i] = np.frombuffer(raw, dtype="<f4", count=WIDTH, offset=pos)
        pos += WIDTH * 4
    return {"cell": cell, "trial": trial, "coordinate": coordinate, "q": q, "y": y, "x": x}


def read_b(path: Path, magic: bytes = MAGIC_B):
    raw = path.read_bytes()
    cell, pos = read_header(raw, magic)
    record = 4 + 4 + 8 + 1 + 8 + WIDTH * 8
    if (len(raw) - pos) % record:
        raise RuntimeError(f"truncated arm B/C stream: {path}")
    n = (len(raw) - pos) // record
    trial = np.empty(n, np.int32)
    coordinate = np.empty(n, np.int32)
    q = np.empty(n, np.float64)
    y = np.empty(n, np.int8)
    abs_g = np.empty(n, np.float64)
    x = np.empty((n, WIDTH), np.float64)
    for i in range(n):
        trial[i], coordinate[i] = struct.unpack_from("<II", raw, pos)
        pos += 8
        q[i], = struct.unpack_from("<d", raw, pos)
        pos += 8
        y[i], = struct.unpack_from("<b", raw, pos)
        pos += 1
        abs_g[i], = struct.unpack_from("<d", raw, pos)
        pos += 8
        x[i] = np.frombuffer(raw, dtype="<f8", count=WIDTH, offset=pos)
        pos += WIDTH * 8
    return {"cell": cell, "trial": trial, "coordinate": coordinate, "q": q, "y": y, "abs_g": abs_g, "x": x}


def write_c(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cell = row["cell"]
    with path.open("xb") as stream:
        stream.write(MAGIC_C)
        stream.write(struct.pack("<IH", 1, WIDTH))
        substrate, side, block = cell
        for value in (substrate, side):
            encoded = value.encode("utf-8")
            stream.write(struct.pack("<H", len(encoded)))
            stream.write(encoded)
        stream.write(struct.pack("<Q", block))
        quantized = row["x"].astype(np.float32).astype(np.float64)
        for i in range(len(row["y"])):
            stream.write(struct.pack("<II", int(row["trial"][i]), int(row["coordinate"][i])))
            stream.write(struct.pack("<d", float(row["q"][i])))
            stream.write(struct.pack("<b", int(row["y"][i])))
            stream.write(struct.pack("<d", float(row["abs_g"][i])))
            stream.write(quantized[i].astype("<f8", copy=False).tobytes())


def load_arms(create_c: bool):
    a_files = sorted(ARM_A.glob("*.bin"))
    b_files = sorted(ARM_B.glob("*.bin"))
    if len(a_files) != 72 or len(b_files) != 72:
        raise RuntimeError(f"expected 72 streams per source arm, A={len(a_files)}, B={len(b_files)}")
    a_rows = [read_a(path) for path in a_files]
    b_rows = [read_b(path) for path in b_files]
    a_by_cell = {row["cell"]: row for row in a_rows}
    b_by_cell = {row["cell"]: row for row in b_rows}
    if set(a_by_cell) != set(b_by_cell):
        raise RuntimeError("arm A/B cell panels differ")
    ordered_cells = sorted(a_by_cell)
    parts_a, parts_b, parts_c = [], [], []
    for cell in ordered_cells:
        a, b = a_by_cell[cell], b_by_cell[cell]
        for key in ("trial", "coordinate", "y"):
            if not np.array_equal(a[key], b[key]):
                raise RuntimeError(f"arm A/B row or target mismatch in {cell} field {key}")
        if not np.array_equal(a["q"], b["q"]):
            raise RuntimeError(f"arm A/B inclusion probability mismatch in {cell}")
        if len(a["y"]) != len(b["y"]):
            raise RuntimeError(f"arm A/B row count mismatch in {cell}")
        # abs_g is a scoring-only sidecar absent from Arm A's frozen stream.
        # Pair it by the already-validated row identity; never pass it to a model.
        a["abs_g"] = b["abs_g"].copy()
        parts_a.append(a)
        parts_b.append(b)
        c_path = ARM_C / f"{cell[0]}-{cell[1]}-{cell[2]}.bin"
        if create_c:
            write_c(c_path, b)
        c = read_b(c_path, MAGIC_C)
        for key in ("trial", "coordinate", "y"):
            if not np.array_equal(b[key], c[key]):
                raise RuntimeError(f"arm B/C row or target mismatch in {cell} field {key}")
        if not np.array_equal(b["q"], c["q"]) or not np.array_equal(b["abs_g"], c["abs_g"]):
            raise RuntimeError(f"arm B/C evaluation sidecar mismatch in {cell}")
        parts_c.append(c)
    def merge(parts):
        return {
            "blocks": np.concatenate([np.full(len(row["y"]), row["cell"][2], dtype=np.int64) for row in parts]),
            "panels": np.concatenate([np.full(len(row["y"]), f"{row['cell'][0]}-{row['cell'][1]}", dtype="U64") for row in parts]),
            "trial": np.concatenate([row["trial"] for row in parts]),
            "coordinate": np.concatenate([row["coordinate"] for row in parts]),
            "q": np.concatenate([row["q"] for row in parts]),
            "y": np.concatenate([row["y"] for row in parts]),
            "abs_g": np.concatenate([row["abs_g"] for row in parts]),
            "x": np.concatenate([row["x"] for row in parts], axis=0),
        }
    return merge(parts_a), merge(parts_b), merge(parts_c), b_files


class Encoder64:
    def __init__(self, seed: int):
        rng = np.random.default_rng(seed)
        # Match the frozen float32 initialization exactly, then promote it.
        # This keeps initialization out of the B/C precision contrast.
        self.w1 = (rng.standard_normal((80, 128)) * np.sqrt(2.0 / 80)).astype(np.float32).astype(np.float64)
        self.b1 = np.zeros(128, dtype=np.float64)
        self.w2 = (rng.standard_normal((128, 64)) * np.sqrt(2.0 / 128)).astype(np.float32).astype(np.float64)
        self.b2 = np.zeros(64, dtype=np.float64)
        self.w3 = (rng.standard_normal((64, 1)) * np.sqrt(2.0 / 64)).astype(np.float32).astype(np.float64)
        self.b3 = np.zeros(1, dtype=np.float64)
        self.values = [self.w1, self.b1, self.w2, self.b2, self.w3, self.b3]
        self.m = [np.zeros_like(v) for v in self.values]
        self.v = [np.zeros_like(v) for v in self.values]
        self.step = 0

    @staticmethod
    def gelu(x):
        return 0.5 * x * (1.0 + np.tanh(0.79788456 * (x + 0.044715 * x * x * x)))

    @staticmethod
    def gelu_grad(x):
        t = np.tanh(0.79788456 * (x + 0.044715 * x * x * x))
        return 0.5 * (1.0 + t) + 0.5 * x * (1.0 - t * t) * 0.79788456 * (1.0 + 3.0 * 0.044715 * x * x)

    def forward(self, x):
        z1 = x @ self.w1 + self.b1
        a1 = self.gelu(z1)
        z2 = a1 @ self.w2 + self.b2
        a2 = self.gelu(z2)
        return (a2 @ self.w3 + self.b3)[:, 0], (x, z1, a1, z2, a2)

    def update(self, x, y):
        logits, (x, z1, a1, z2, a2) = self.forward(x)
        p = 1.0 / (1.0 + np.exp(-np.clip(logits, -30.0, 30.0)))
        d3 = ((p - y) / max(1, len(y)))[:, None]
        d2 = (d3 @ self.w3.T) * self.gelu_grad(z2)
        d1 = (d2 @ self.w2.T) * self.gelu_grad(z1)
        grads = [x.T @ d1, d1.sum(axis=0), a1.T @ d2, d2.sum(axis=0), a2.T @ d3, d3.sum(axis=0)]
        self.step += 1
        for i, (value, grad) in enumerate(zip(self.values, grads)):
            self.m[i] = 0.9 * self.m[i] + 0.1 * grad
            self.v[i] = 0.999 * self.v[i] + 0.001 * grad * grad
            mh = self.m[i] / (1.0 - 0.9 ** self.step)
            vh = self.v[i] / (1.0 - 0.999 ** self.step)
            value -= LEARNING_RATE * mh / (np.sqrt(vh) + 1e-8)

    def fit(self, x, y):
        for _ in range(EPOCHS):
            for start in range(0, len(y), BATCH_SIZE):
                self.update(x[start : start + BATCH_SIZE], y[start : start + BATCH_SIZE])


def standardize32(x: np.ndarray, train: np.ndarray):
    mean = x[train].mean(axis=0)
    scale = x[train].std(axis=0)
    scale[scale < 1e-6] = 1.0
    return ((x - mean) / scale).astype(np.float32)


def standardize64(x: np.ndarray, train: np.ndarray):
    mean = x[train].mean(axis=0)
    scale = x[train].std(axis=0)
    scale[scale < 1e-6] = 1.0
    return ((x - mean) / scale).astype(np.float64)


def balanced_metrics(y: np.ndarray, pred: np.ndarray, q: np.ndarray):
    positive = y > 0
    negative = ~positive
    if not len(y):
        return {"rows": 0, "positive": 0, "negative": 0, "two_class_supported": False, "balanced_error": None, "omega_hat_unclipped": None, "omega_hat": None}
    err = pred != positive
    # Match the parent evaluator's frozen denominator floor for a class-absent
    # fold or margin slice. Such fold scores are explicitly marked degenerate.
    plus_error = float(np.sum(q[positive] * err[positive]) / max(1e-12, np.sum(q[positive])))
    minus_error = float(np.sum(q[negative] * err[negative]) / max(1e-12, np.sum(q[negative])))
    balanced = 0.5 * (plus_error + minus_error)
    return {"rows": int(len(y)), "positive": int(positive.sum()), "negative": int(negative.sum()), "two_class_supported": bool(positive.any() and negative.any()), "balanced_error": balanced, "omega_hat_unclipped": 1.0 - 2.0 * balanced, "omega_hat": max(0.0, 1.0 - 2.0 * balanced)}


def train_arm(name: str, data: dict, blocks: np.ndarray):
    x = data["x"]
    y = (data["y"] > 0).astype(np.float64 if name != "A-f32" else np.float32)
    q = data["q"]
    predictions = np.zeros(len(y), dtype=bool)
    logits_all = np.zeros(len(y), dtype=np.float64)
    fold_results = []
    for fold, block in enumerate(sorted(np.unique(blocks).tolist())):
        train = blocks != block
        valid = ~train
        if name == "A-f32":
            encoder_module = load_old_encoder()
            normalized = standardize32(x, train)
            model = encoder_module.Encoder(BASE_SEED + fold)
            model.fit(normalized[train], y[train].astype(np.float32))
            logits = model.forward(normalized[valid])[0].astype(np.float64)
        else:
            normalized = standardize64(x, train)
            model = Encoder64(BASE_SEED + fold)
            model.fit(normalized[train], y[train].astype(np.float64))
            logits = model.forward(normalized[valid])[0]
        pred = logits > 0.0
        predictions[valid] = pred
        logits_all[valid] = logits
        base = balanced_metrics(data["y"][valid], pred, q[valid])
        base.update({"holdout_block": int(block), "train_rows": int(train.sum()), "signed_margin": float(np.sum(q[valid] * data["y"][valid] * logits) / np.sum(q[valid])), "mean_abs_logit": float(np.mean(np.abs(logits)))})
        by_margin = {}
        for gamma in MARGIN_GAMMAS:
            eligible = data["abs_g"][valid] > gamma
            metric = balanced_metrics(data["y"][valid][eligible], pred[eligible], q[valid][eligible])
            by_margin[f"{gamma:.0e}"] = metric
        base["margin_ladder"] = by_margin
        fold_results.append(base)
    pooled = balanced_metrics(data["y"], predictions, q)
    pooled["signed_margin"] = float(np.sum(q * data["y"] * logits_all) / np.sum(q))
    pooled["margin_ladder"] = {}
    for gamma in MARGIN_GAMMAS:
        eligible = data["abs_g"] > gamma
        pooled["margin_ladder"][f"{gamma:.0e}"] = balanced_metrics(data["y"][eligible], predictions[eligible], q[eligible])
    return {"folds": fold_results, "pooled_oof": pooled, "predictions": predictions, "logits": logits_all}


def _distance_quantiles(values: np.ndarray):
    finite = values[np.isfinite(values)]
    if not len(finite):
        return None
    return {str(q): float(np.quantile(finite, q)) for q in (0.0, 0.25, 0.5, 0.75, 0.9, 1.0)}


def _nearest_distances(x: np.ndarray, y: np.ndarray, chunk: int):
    x64 = np.asarray(x, dtype=np.float64)
    mean = x64.mean(axis=0)
    scale = x64.std(axis=0)
    scale[scale < 1e-12] = 1.0
    z = (x64 - mean) / scale
    norm = np.einsum("ij,ij->i", z, z)
    same_min = np.full(len(z), np.nan, dtype=np.float64)
    opposite_min = np.full(len(z), np.nan, dtype=np.float64)
    for start in range(0, len(z), chunk):
        stop = min(start + chunk, len(z))
        d2 = norm[start:stop, None] + norm[None, :] - 2.0 * (z[start:stop] @ z.T)
        np.maximum(d2, 0.0, out=d2)
        row_ids = np.arange(start, stop)
        d2[np.arange(stop - start), row_ids] = np.inf
        same = y[start:stop, None] == y[None, :]
        same_values = np.min(np.where(same, d2, np.inf), axis=1)
        opposite_values = np.min(np.where(~same, d2, np.inf), axis=1)
        same_ok = np.isfinite(same_values)
        opposite_ok = np.isfinite(opposite_values)
        same_min[start:stop][same_ok] = np.sqrt(same_values[same_ok])
        opposite_min[start:stop][opposite_ok] = np.sqrt(opposite_values[opposite_ok])
    return same_min, opposite_min


def _summarize_nearest(same_min: np.ndarray, opposite_min: np.ndarray):
    paired = np.isfinite(same_min) & np.isfinite(opposite_min)
    gap = opposite_min[paired] - same_min[paired]
    return {
        "rows": int(len(same_min)),
        "same_supported_rows": int(np.isfinite(same_min).sum()),
        "opposite_supported_rows": int(np.isfinite(opposite_min).sum()),
        "paired_comparison_rows": int(paired.sum()),
        "same_nearest_distance_quantiles": _distance_quantiles(same_min),
        "opposite_nearest_distance_quantiles": _distance_quantiles(opposite_min),
        "opposite_nearer_or_tied_fraction": float(np.mean(opposite_min[paired] <= same_min[paired])) if paired.any() else None,
        "opposite_minus_same_distance_quantiles": _distance_quantiles(gap),
    }


def nearest_neighbor_summary(x: np.ndarray, y: np.ndarray, panels: np.ndarray, chunk: int = 256):
    same_all, opposite_all, by_panel = [], [], {}
    for panel in sorted(np.unique(panels).tolist()):
        indices = np.flatnonzero(panels == panel)
        same_min, opposite_min = _nearest_distances(x[indices], y[indices], chunk)
        same_all.append(same_min)
        opposite_all.append(opposite_min)
        panel_result = _summarize_nearest(same_min, opposite_min)
        panel_result["positive_rows"] = int((y[indices] > 0).sum())
        panel_result["negative_rows"] = int((y[indices] < 0).sum())
        by_panel[str(panel)] = panel_result
    pooled = _summarize_nearest(np.concatenate(same_all), np.concatenate(opposite_all))
    pooled["panels"] = len(by_panel)
    pooled["panel_support"] = "one-class panels retain same-class distances; opposite-class metrics are null where the panel has no opposite labels"
    pooled["by_panel"] = by_panel
    return pooled


def exact_opposite_collision_summary(x32: np.ndarray, y: np.ndarray, panels: np.ndarray):
    details = {}
    totals = {"unique_f32_vectors": 0, "exact_collision_groups": 0, "opposite_label_collision_groups": 0, "rows_in_opposite_label_collision_groups": 0, "discordant_pairs": 0}
    for panel in sorted(np.unique(panels).tolist()):
        groups: dict[bytes, list[int]] = {}
        indices = np.flatnonzero(panels == panel)
        for row, label in zip(x32[indices], y[indices]):
            key = np.ascontiguousarray(row, dtype=np.float32).tobytes()
            counts = groups.setdefault(key, [0, 0])
            counts[0 if label > 0 else 1] += 1
        mixed = [counts for counts in groups.values() if counts[0] and counts[1]]
        detail = {
            "unique_f32_vectors": len(groups),
            "exact_collision_groups": int(sum(sum(counts) > 1 for counts in groups.values())),
            "opposite_label_collision_groups": len(mixed),
            "rows_in_opposite_label_collision_groups": int(sum(sum(counts) for counts in mixed)),
            "discordant_pairs": int(sum(counts[0] * counts[1] for counts in mixed)),
        }
        details[str(panel)] = detail
        for key, value in detail.items():
            totals[key] += value
    totals["panels"] = len(details)
    totals["by_panel"] = details
    return totals


def precision_diagnostics(b: dict, c: dict, c_predictions: np.ndarray):
    x64 = b["x"]
    xq = c["x"]
    delta = x64 - xq
    scale = x64.std(axis=0)
    scale[scale < 1e-12] = 1.0
    normalized_delta = delta / scale
    relative = np.sqrt(np.mean(normalized_delta * normalized_delta, axis=1))
    quantile_edges = np.quantile(relative, [0.0, 0.25, 0.5, 0.75, 1.0])
    quartiles = []
    error = c_predictions != (c["y"] > 0)
    for index in range(4):
        if index == 3:
            mask = (relative >= quantile_edges[index]) & (relative <= quantile_edges[index + 1])
        else:
            mask = (relative >= quantile_edges[index]) & (relative < quantile_edges[index + 1])
        quartiles.append({
            "quartile": index + 1,
            "rows": int(mask.sum()),
            "relative_delta_z_median": float(np.median(relative[mask])) if mask.any() else None,
            "arm_c_error_rate": float(np.mean(error[mask])) if mask.any() else None,
        })
    return {
        "changed_feature_cells": int(np.count_nonzero(delta)),
        "total_feature_cells": int(delta.size),
        "rows_with_any_quantization_change": int(np.any(delta != 0.0, axis=1).sum()),
        "mean_abs_delta_z": float(np.mean(np.abs(delta))),
        "rmse_delta_z": float(np.sqrt(np.mean(delta * delta))),
        "max_abs_delta_z": float(np.max(np.abs(delta))),
        "relative_delta_z_quantiles": {str(q): float(np.quantile(relative, q)) for q in (0.0, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0)},
        "arm_c_error_by_relative_delta_quartile": quartiles,
    }


def main():
    if not SPEC_PATH.is_file():
        raise SystemExit("F4-PRECISION-01 contract is missing")
    contract = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if contract["status"] != "QUALIFICATION_ONLY_FROZEN":
        raise SystemExit("precision contract is not frozen")
    for entry in contract["frozen_inputs"]:
        path = STUDY / entry["path"]
        if not path.is_file() or sha(path) != entry["sha256"]:
            raise SystemExit(f"frozen input hash mismatch: {entry['path']}")
    if sha(Path(__file__).resolve()) != contract["analysis_script_sha256"]:
        raise SystemExit("analysis script hash differs from frozen contract")
    if ANALYSIS_OUT.exists():
        raise SystemExit("analysis output identity already exists; preserve and stop")
    create_c = not ARM_C.exists()
    if create_c:
        ARM_C.mkdir(parents=True)
    a, b, c, b_files = load_arms(create_c)
    if not np.array_equal(a["blocks"], b["blocks"]) or not np.array_equal(b["blocks"], c["blocks"]):
        raise SystemExit("arm row order mismatch")
    if len(a["y"]) != 13420:
        raise SystemExit(f"unexpected common U* row count: {len(a['y'])}")
    if not np.array_equal(a["y"], b["y"]) or not np.array_equal(b["y"], c["y"]):
        raise SystemExit("arm target mismatch")
    if not np.array_equal(a["q"], b["q"]) or not np.array_equal(b["q"], c["q"]):
        raise SystemExit("arm inclusion probability mismatch")
    if not np.array_equal(a["trial"], b["trial"]) or not np.array_equal(a["coordinate"], b["coordinate"]):
        raise SystemExit("arm coordinate-time identity mismatch")
    blocks = a["blocks"]
    a_result = train_arm("A-f32", a, blocks)
    parent_path = STUDY / "F4-CAPACITY-01-TERMINAL-RECEIPT.json"
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    anchor_rows = parent["findings"]["cross_block_80d"]
    for actual, expected in zip(a_result["folds"], anchor_rows):
        if actual["holdout_block"] != expected["holdout_block"]:
            raise SystemExit("arm A anchor fold order changed")
        if abs(actual["balanced_error"] - expected["balanced_error"]) > 1e-8:
            raise SystemExit("arm A failed to reproduce F4-CAPACITY-01 anchor")

    b_result = train_arm("B-f64", b, blocks)
    c_result = train_arm("C-f32-features-f64-model", c, blocks)

    # The B/C contrast holds estimator arithmetic and initialization fixed.
    result = {
        "schema": "FLY-REACH-03-F4-PRECISION-01-analysis-v1",
        "identity": "F4-PRECISION-01",
        "status": "QUALIFICATION_ANALYSIS_COMPLETE",
        "contract_sha256": sha(SPEC_PATH),
        "rows": int(len(a["y"])),
        "blocks": sorted(np.unique(blocks).tolist()),
        "arms": {
            "A-f32-features-f32-model": {"pooled_oof": a_result["pooled_oof"], "folds": a_result["folds"]},
            "B-f64-features-f64-model": {"pooled_oof": b_result["pooled_oof"], "folds": b_result["folds"]},
            "C-f32-quantized-features-f64-model": {"pooled_oof": c_result["pooled_oof"], "folds": c_result["folds"]},
        },
        "contrasts": {
            "B_minus_C_pooled_omega_hat": b_result["pooled_oof"]["omega_hat"] - c_result["pooled_oof"]["omega_hat"],
            "B_minus_A_pooled_omega_hat": b_result["pooled_oof"]["omega_hat"] - a_result["pooled_oof"]["omega_hat"],
            "C_minus_A_pooled_omega_hat": c_result["pooled_oof"]["omega_hat"] - a_result["pooled_oof"]["omega_hat"],
        },
        "representation_diagnostics": {
            "B_vs_C_quantization": precision_diagnostics(b, c, c_result["predictions"]),
            "A_f32_exact_collision": exact_opposite_collision_summary(a["x"], a["y"], a["panels"]),
            "C_f32_exact_collision": exact_opposite_collision_summary(c["x"].astype(np.float32), c["y"], c["panels"]),
            "nearest_neighbors": {
                "within_substrate_side_panel": True,
                "A_f32": nearest_neighbor_summary(a["x"], a["y"], a["panels"]),
                "B_f64": nearest_neighbor_summary(b["x"], b["y"], b["panels"]),
                "C_quantized": nearest_neighbor_summary(c["x"], c["y"], c["panels"]),
            },
        },
        "margin_ladder": {name: arm["pooled_oof"]["margin_ladder"] for name, arm in {
            "A-f32-features-f32-model": {"pooled_oof": a_result["pooled_oof"]},
            "B-f64-features-f64-model": {"pooled_oof": b_result["pooled_oof"]},
            "C-f32-quantized-features-f64-model": {"pooled_oof": c_result["pooled_oof"]},
        }.items()},
        "parent_failure_anatomy_sha256": sha(parent_path),
        "source_data_attempt": "qualification-v2/f4-precision-01-attempt-02",
        "arm_a_abs_g_sidecar": "paired from Arm B only after exact row identity, target, and inclusion-probability checks; scoring only",
        "measured_namespace_created": False,
        "scientific_interpretation_opened": False,
        "biological_promotion": False,
        "prediction_flip_rescue": False,
        "estimator_capacity_changed": False,
    }
    ANALYSIS_OUT.mkdir(parents=True, exist_ok=False)
    analysis_path = ANALYSIS_OUT / "F4-PRECISION-01-ANALYSIS.json"
    analysis_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = sorted(ARM_C.glob("*.bin"))
    manifest = [{"path": path.name, "bytes": path.stat().st_size, "sha256": sha(path)} for path in files]
    (ANALYSIS_OUT / "C-QUANTIZATION-RECEIPT.json").write_text(json.dumps({"schema": "FLY-REACH-03-F4-PRECISION-01-C-quantization-receipt-v1", "status": "PASS", "source_arm": "B-f64", "transform": "float64 -> float32 -> float64", "streams": len(files), "rows": len(c["y"]), "features_changed": int(np.count_nonzero(b["x"] != c["x"])), "files": manifest, "measured_namespace_created": False}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "arms": {k: v["pooled_oof"]["omega_hat"] for k, v in result["arms"].items()}, "margin_ladder": result["margin_ladder"]}, sort_keys=True))


if __name__ == "__main__":
    main()
