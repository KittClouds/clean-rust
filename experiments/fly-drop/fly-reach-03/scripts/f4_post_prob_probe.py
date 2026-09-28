"""Qualification-only cue-post-probability representation probe."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import numpy as np


STUDY = Path(__file__).resolve().parents[1]
ROOT = STUDY / "runs/qualification-v2/f4-features-v3-post-probability"
CONTRACT = STUDY / "F4-CAPACITY-01-POST-PROB-CONTRACT.json"
MAGIC = b"FLYREACH3V3\0"
WIDTH = 85
EPOCHS = 200
LR = 0.001
BATCH = 2048


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load():
    pieces = []
    for path in sorted(ROOT.glob("*.bin")):
        raw = path.read_bytes(); pos = len(MAGIC)
        if raw[:len(MAGIC)] != MAGIC: raise RuntimeError(f"bad v3 stream {path}")
        version, width = struct.unpack_from("<IH", raw, pos); pos += 6
        if version != 1 or width != WIDTH: raise RuntimeError(f"bad v3 header {path}")
        sl, = struct.unpack_from("<H", raw, pos); pos += 2 + sl
        sl, = struct.unpack_from("<H", raw, pos); pos += 2 + sl
        block, = struct.unpack_from("<Q", raw, pos); pos += 8
        record = 4 + 4 + 8 + 1 + WIDTH * 4
        if (len(raw) - pos) % record: raise RuntimeError(f"truncated v3 stream {path}")
        n = (len(raw) - pos) // record
        q = np.empty(n, dtype=np.float64); y = np.empty(n, dtype=np.float32); x = np.empty((n, WIDTH), dtype=np.float32)
        for i in range(n):
            pos += 8; q[i], = struct.unpack_from("<d", raw, pos); pos += 8
            target, = struct.unpack_from("<b", raw, pos); pos += 1
            y[i] = 1.0 if target > 0 else 0.0
            x[i] = np.frombuffer(raw, dtype="<f4", count=WIDTH, offset=pos); pos += WIDTH * 4
        pieces.append((int(block), q, y, x))
    if len(pieces) != 72: raise RuntimeError(f"expected 72 v3 streams, found {len(pieces)}")
    return (np.concatenate([np.full(len(p[1]), p[0], dtype=np.int64) for p in pieces]),
            np.concatenate([p[1] for p in pieces]), np.concatenate([p[2] for p in pieces]), np.concatenate([p[3] for p in pieces]))


def gelu(x): return 0.5 * x * (1.0 + np.tanh(0.79788456 * (x + 0.044715 * x * x * x)))


def gelu_grad(x):
    t = np.tanh(0.79788456 * (x + 0.044715 * x * x * x))
    return 0.5 * (1.0 + t) + 0.5 * x * (1.0 - t * t) * 0.79788456 * (1.0 + 3.0 * 0.044715 * x * x)


class Encoder:
    def __init__(self, seed):
        rng = np.random.default_rng(seed)
        self.w1 = (rng.standard_normal((WIDTH, 128)) * np.sqrt(2.0 / WIDTH)).astype(np.float32); self.b1 = np.zeros(128, np.float32)
        self.w2 = (rng.standard_normal((128, 64)) * np.sqrt(2.0 / 128)).astype(np.float32); self.b2 = np.zeros(64, np.float32)
        self.w3 = (rng.standard_normal((64, 1)) * np.sqrt(2.0 / 64)).astype(np.float32); self.b3 = np.zeros(1, np.float32)
        self.values = [self.w1, self.b1, self.w2, self.b2, self.w3, self.b3]; self.m = [np.zeros_like(v) for v in self.values]; self.v = [np.zeros_like(v) for v in self.values]; self.step = 0

    def forward(self, x):
        z1 = x @ self.w1 + self.b1; a1 = gelu(z1); z2 = a1 @ self.w2 + self.b2; a2 = gelu(z2)
        return (a2 @ self.w3 + self.b3)[:, 0], (x, z1, a1, z2, a2)

    def update(self, x, y):
        logits, (x, z1, a1, z2, a2) = self.forward(x); p = 1.0 / (1.0 + np.exp(-np.clip(logits, -30.0, 30.0)))
        d3 = ((p - y) / max(1, len(y))).astype(np.float32)[:, None]; d2 = (d3 @ self.w3.T) * gelu_grad(z2); d1 = (d2 @ self.w2.T) * gelu_grad(z1)
        grads = [x.T @ d1, d1.sum(axis=0), a1.T @ d2, d2.sum(axis=0), a2.T @ d3, d3.sum(axis=0)]; self.step += 1
        for i, (value, grad) in enumerate(zip(self.values, grads)):
            self.m[i] = 0.9 * self.m[i] + 0.1 * grad; self.v[i] = 0.999 * self.v[i] + 0.001 * grad * grad
            value -= LR * (self.m[i] / (1.0 - 0.9 ** self.step)) / (np.sqrt(self.v[i] / (1.0 - 0.999 ** self.step)) + 1e-8)

    def fit(self, x, y):
        for _ in range(EPOCHS):
            for start in range(0, len(y), BATCH): self.update(x[start:start+BATCH], y[start:start+BATCH])


def standardize(x, train):
    mean = x[train].mean(axis=0); scale = x[train].std(axis=0); scale[scale < 1e-6] = 1.0
    return ((x - mean) / scale).astype(np.float32)


def score(model, x, y, q):
    logits = model.forward(x)[0]; pred = logits > 0; err = pred != (y > 0.5); plus = y > 0.5; minus = ~plus
    ep = float(np.sum(q[plus] * err[plus]) / max(1e-12, np.sum(q[plus]))); em = float(np.sum(q[minus] * err[minus]) / max(1e-12, np.sum(q[minus]))); e = 0.5 * (ep + em)
    return {"rows": int(len(y)), "balanced_error": e, "omega_hat": max(0.0, 1.0 - 2.0 * e), "signed_margin": float(np.sum(q * (2*y - 1) * logits) / np.sum(q)), "mean_abs_logit": float(np.mean(np.abs(logits)))}


def main():
    blocks, q, y, x = load(); results = []
    for fold, block in enumerate(sorted(np.unique(blocks).tolist())):
        train = blocks != block; valid = ~train; xn = standardize(x, train); model = Encoder(308000 + fold); model.fit(xn[train], y[train]); row = score(model, xn[valid], y[valid], q[valid]); row.update({"holdout_block": int(block), "train_rows": int(train.sum())}); results.append(row)
    weighted = float(np.average([r["balanced_error"] for r in results], weights=[r["rows"] for r in results])); omega = max(0.0, 1.0 - 2.0 * weighted)
    receipt = {"schema": "FLY-REACH-03-F4-CAPACITY-01-post-prob-receipt-v1", "identity": "F4-CAPACITY-01-POST-PROBABILITY", "status": "PASS_POST_PROBABILITY_CHANNEL_RESTORES_CROSS_BLOCK_EXTRACTION" if all(r["omega_hat"] >= 0.70 for r in results) else "POST_PROBABILITY_CHANNEL_INSUFFICIENT", "contract_sha256": sha(CONTRACT), "feature_identity": "f4-features-v3-post-probability", "feature_width": WIDTH, "rows": int(len(y)), "folds": results, "row_weighted_balanced_error": weighted, "row_weighted_omega_hat": omega, "same_hidden_estimator": True, "hyperparameter_search": False, "prediction_flip_rescue": False, "measured_namespace_created": False, "scientific_interpretation_opened": False, "biological_promotion": False}
    path = STUDY / "F4-CAPACITY-01-POST-PROB-RECEIPT.json"; path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "row_weighted_omega_hat": omega, "folds": results}, sort_keys=True))


if __name__ == "__main__": main()
