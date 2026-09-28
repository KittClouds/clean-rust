"""Qualification-only learned F4 ceiling calibration.

The encoder is frozen by F4-ENCODER-SPEC-v1.json. This script never creates a
measured namespace and uses only the four qualification blocks.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import numpy as np


STUDY = Path(__file__).resolve().parents[1]
RUN = STUDY / "runs/qualification-v2/f4-features-v1"
SPEC_PATH = STUDY / "F4-ENCODER-SPEC-v1.json"
MAGIC = b"FLYREACH3F4\0"
WEIGHT_MAGIC = b"FLYREACH3F4W\0"
EPOCHS = 200
LR = 0.001
BATCH = 2048
HIDDEN = (128, 64)
BASE_SEED = 304000


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_file(path: Path) -> tuple[int, int, int, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = path.read_bytes()
    pos = 0
    if raw[: len(MAGIC)] != MAGIC:
        raise RuntimeError(f"bad F4 feature magic: {path}")
    pos += len(MAGIC)
    version, width = struct.unpack_from("<IH", raw, pos)
    pos += 6
    if version != 1 or width != 80:
        raise RuntimeError(f"unsupported F4 feature header: {path}")
    substrate_len, = struct.unpack_from("<H", raw, pos)
    pos += 2 + substrate_len
    side_len, = struct.unpack_from("<H", raw, pos)
    pos += 2 + side_len
    block, = struct.unpack_from("<Q", raw, pos)
    pos += 8
    record = 4 + 4 + 8 + 1 + width * 4
    if (len(raw) - pos) % record:
        raise RuntimeError(f"truncated F4 feature stream: {path}")
    count = (len(raw) - pos) // record
    trial = np.empty(count, dtype=np.int32)
    coordinate = np.empty(count, dtype=np.int32)
    q = np.empty(count, dtype=np.float64)
    target = np.empty(count, dtype=np.float32)
    features = np.empty((count, width), dtype=np.float32)
    for i in range(count):
        trial[i], coordinate[i] = struct.unpack_from("<II", raw, pos)
        pos += 8
        q[i], = struct.unpack_from("<d", raw, pos)
        pos += 8
        y, = struct.unpack_from("<b", raw, pos)
        pos += 1
        target[i] = 1.0 if y > 0 else 0.0
        features[i] = np.frombuffer(raw, dtype="<f4", count=width, offset=pos)
        pos += width * 4
    return int(block), count, width, features, target, q, trial.astype(np.int64) * 0 + coordinate


def load() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    pieces = [read_file(path) for path in sorted(RUN.glob("*.bin"))]
    if len(pieces) != 72:
        raise RuntimeError(f"expected 72 feature streams, found {len(pieces)}")
    x = np.concatenate([piece[3] for piece in pieces], axis=0)
    y = np.concatenate([piece[4] for piece in pieces])
    q = np.concatenate([piece[5] for piece in pieces])
    blocks = np.concatenate([np.full(piece[1], piece[0], dtype=np.int64) for piece in pieces])
    return x, y, q, blocks


def gelu(x: np.ndarray) -> np.ndarray:
    return 0.5 * x * (1.0 + np.tanh(0.79788456 * (x + 0.044715 * x * x * x)))


def gelu_grad(x: np.ndarray) -> np.ndarray:
    t = np.tanh(0.79788456 * (x + 0.044715 * x * x * x))
    return 0.5 * (1.0 + t) + 0.5 * x * (1.0 - t * t) * 0.79788456 * (1.0 + 3.0 * 0.044715 * x * x)


class Encoder:
    def __init__(self, seed: int):
        rng = np.random.default_rng(seed)
        self.w1 = (rng.standard_normal((80, HIDDEN[0])) * np.sqrt(2.0 / 80)).astype(np.float32)
        self.b1 = np.zeros(HIDDEN[0], dtype=np.float32)
        self.w2 = (rng.standard_normal((HIDDEN[0], HIDDEN[1])) * np.sqrt(2.0 / HIDDEN[0])).astype(np.float32)
        self.b2 = np.zeros(HIDDEN[1], dtype=np.float32)
        self.w3 = (rng.standard_normal((HIDDEN[1], 1)) * np.sqrt(2.0 / HIDDEN[1])).astype(np.float32)
        self.b3 = np.zeros(1, dtype=np.float32)
        self.values = [self.w1, self.b1, self.w2, self.b2, self.w3, self.b3]
        self.m = [np.zeros_like(value) for value in self.values]
        self.v = [np.zeros_like(value) for value in self.values]
        self.step = 0

    def forward(self, x: np.ndarray):
        z1 = x @ self.w1 + self.b1
        a1 = gelu(z1)
        z2 = a1 @ self.w2 + self.b2
        a2 = gelu(z2)
        return (a2 @ self.w3 + self.b3)[:, 0], (x, z1, a1, z2, a2)

    def update(self, x: np.ndarray, y: np.ndarray) -> None:
        logits, (x, z1, a1, z2, a2) = self.forward(x)
        p = 1.0 / (1.0 + np.exp(-np.clip(logits, -30.0, 30.0)))
        d3 = ((p - y) / max(1, len(y))).astype(np.float32)[:, None]
        d2 = (d3 @ self.w3.T) * gelu_grad(z2)
        d1 = (d2 @ self.w2.T) * gelu_grad(z1)
        grads = [x.T @ d1, d1.sum(axis=0), a1.T @ d2, d2.sum(axis=0), a2.T @ d3, d3.sum(axis=0)]
        self.step += 1
        for index, (value, grad) in enumerate(zip(self.values, grads)):
            self.m[index] = 0.9 * self.m[index] + 0.1 * grad
            self.v[index] = 0.999 * self.v[index] + 0.001 * grad * grad
            m_hat = self.m[index] / (1.0 - 0.9 ** self.step)
            v_hat = self.v[index] / (1.0 - 0.999 ** self.step)
            value -= LR * m_hat / (np.sqrt(v_hat) + 1e-8)

    def fit(self, x: np.ndarray, y: np.ndarray) -> None:
        for _ in range(EPOCHS):
            for start in range(0, len(y), BATCH):
                self.update(x[start : start + BATCH], y[start : start + BATCH])

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.forward(x)[0] > 0.0


def score(model: Encoder, x: np.ndarray, y: np.ndarray, q: np.ndarray) -> tuple[float, float, float]:
    prediction = model.predict(x)
    errors = prediction != (y > 0.5)
    plus = y > 0.5
    minus = ~plus
    plus_error = float(np.sum(q[plus] * errors[plus]) / max(1e-12, np.sum(q[plus])))
    minus_error = float(np.sum(q[minus] * errors[minus]) / max(1e-12, np.sum(q[minus])))
    balanced = 0.5 * (plus_error + minus_error)
    return balanced, max(0.0, 1.0 - 2.0 * balanced), float(prediction.mean())


def standardize(x: np.ndarray, train: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x[train].mean(axis=0)
    scale = x[train].std(axis=0)
    scale[scale < 1e-6] = 1.0
    return ((x - mean) / scale).astype(np.float32), mean.astype(np.float32), scale.astype(np.float32)


def write_weights(path: Path, model: Encoder, mean: np.ndarray, scale: np.ndarray) -> None:
    with path.open("wb") as handle:
        handle.write(WEIGHT_MAGIC)
        handle.write(struct.pack("<III", 1, 80, 3))
        handle.write(mean.astype("<f4").tobytes())
        handle.write(scale.astype("<f4").tobytes())
        for value in model.values:
            flat = np.asarray(value, dtype="<f4")
            handle.write(struct.pack("<I", flat.size))
            handle.write(flat.tobytes())


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_QUALIFICATION_ONLY":
        raise SystemExit("F4 encoder spec is not frozen")
    if sha(SPEC_PATH) != (STUDY / "F4-ENCODER-SPEC-v1.sha256").read_text(encoding="utf-8").split()[0]:
        raise SystemExit("F4 encoder spec hash mismatch")
    x, y, q, blocks = load()
    unique = sorted(np.unique(blocks).tolist())
    if unique != [303000, 303001, 303002, 303003]:
        raise SystemExit(f"unexpected qualification blocks: {unique}")
    fold_results = []
    heldout_predictions = []
    pooled_y = []
    pooled_q = []
    standardization = []
    for fold_index, block in enumerate(unique):
        train = blocks != block
        valid = ~train
        x_norm, mean, scale = standardize(x, train)
        model = Encoder(BASE_SEED + fold_index)
        model.fit(x_norm[train], y[train])
        balanced, omega, positive_rate = score(model, x_norm[valid], y[valid], q[valid])
        fold_results.append({
            "holdout_block": int(block),
            "rows": int(valid.sum()),
            "balanced_error": balanced,
            "omega_hat": omega,
            "positive_prediction_rate": positive_rate,
        })
        heldout_predictions.append(model.predict(x_norm[valid]))
        pooled_y.append(y[valid])
        pooled_q.append(q[valid])
        standardization.append({"holdout_block": int(block), "mean_sha256": hashlib.sha256(mean.tobytes()).hexdigest(), "scale_sha256": hashlib.sha256(scale.tobytes()).hexdigest()})
    pred = np.concatenate(heldout_predictions)
    yy = np.concatenate(pooled_y)
    qq = np.concatenate(pooled_q)
    error = pred != (yy > 0.5)
    plus = yy > 0.5
    minus = ~plus
    pooled_balanced = 0.5 * (float(np.sum(qq[plus] * error[plus]) / np.sum(qq[plus])) + float(np.sum(qq[minus] * error[minus]) / np.sum(qq[minus])))
    pooled_omega = max(0.0, 1.0 - 2.0 * pooled_balanced)
    pass_gate = pooled_balanced <= 0.10 and pooled_omega >= 0.80 and all(row["omega_hat"] >= 0.70 for row in fold_results)
    receipt: dict[str, object] = {
        "schema": "FLY-REACH-03-F4-encoder-qualification-receipt-v1",
        "status": "PASS" if pass_gate else "ESTIMATOR_CAPACITY_STOP",
        "run_id": "qualification-v2",
        "feature_identity": "f4-features-v1",
        "spec_sha256": sha(SPEC_PATH),
        "script_sha256": sha(Path(__file__)),
        "rows": int(len(y)),
        "positive_rows": int(np.sum(y > 0.5)),
        "negative_rows": int(np.sum(y <= 0.5)),
        "feature_width": int(x.shape[1]),
        "architecture": [80, 128, "GELU", 64, "GELU", 1],
        "qualification_folds": fold_results,
        "pooled_heldout": {"rows": int(len(yy)), "balanced_error": pooled_balanced, "omega_hat": pooled_omega},
        "gate": spec["qualification"]["gate"],
        "standardization": standardization,
        "exact_f4_reconstruction": "PASS; Omega(F4)=1 invariant audited separately",
        "measured_namespace_created": False,
        "measured_seal_created": False,
    }
    out = STUDY / "F4-ENCODER-QUALIFICATION-RECEIPT.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if pass_gate:
        final = Encoder(BASE_SEED + 1000)
        x_norm, mean, scale = standardize(x, np.ones(len(y), dtype=bool))
        final.fit(x_norm, y)
        weight_path = STUDY / "F4-ENCODER-WEIGHTS.bin"
        write_weights(weight_path, final, mean, scale)
        (STUDY / "F4-ENCODER-WEIGHTS.sha256").write_text(sha(weight_path) + "  F4-ENCODER-WEIGHTS.bin\n", encoding="utf-8")
        receipt["final_encoder_weights"] = {"path": weight_path.name, "sha256": sha(weight_path)}
        out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "pooled_omega_hat": pooled_omega, "pooled_balanced_error": pooled_balanced}, sort_keys=True))


if __name__ == "__main__":
    main()
