"""Qualification-only failure anatomy for the frozen F4 encoder.

This identity does not alter the parent F4 calibration stop and never creates
the measured namespace. It separates memorization, within-block generalization,
and cross-block polarity orientation using the already frozen 80D encoder.
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
FEATURE_ROOT = STUDY / "runs/qualification-v2/f4-features-v1"
CONTRACT = STUDY / "F4-CAPACITY-01-CONTRACT.json"
MAGIC = b"FLYREACH3F4\0"


def load_encoder_module():
    path = STUDY / "scripts/f4_encoder_qualification.py"
    spec = importlib.util.spec_from_file_location("reach03_f4_encoder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen encoder implementation")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_stream(path: Path) -> tuple[int, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = path.read_bytes()
    pos = len(MAGIC)
    version, width = struct.unpack_from("<IH", raw, pos)
    pos += 6
    if raw[: len(MAGIC)] != MAGIC or version != 1 or width != 80:
        raise RuntimeError(f"bad F4 feature stream: {path}")
    substrate_len, = struct.unpack_from("<H", raw, pos)
    pos += 2 + substrate_len
    side_len, = struct.unpack_from("<H", raw, pos)
    pos += 2 + side_len
    block, = struct.unpack_from("<Q", raw, pos)
    pos += 8
    record = 4 + 4 + 8 + 1 + width * 4
    if (len(raw) - pos) % record:
        raise RuntimeError(f"truncated F4 stream: {path}")
    count = (len(raw) - pos) // record
    trials = np.empty(count, dtype=np.int64)
    q = np.empty(count, dtype=np.float64)
    y = np.empty(count, dtype=np.float32)
    features = np.empty((count, width), dtype=np.float32)
    for i in range(count):
        trials[i], _coordinate = struct.unpack_from("<II", raw, pos)
        pos += 8
        q[i], = struct.unpack_from("<d", raw, pos)
        pos += 8
        target, = struct.unpack_from("<b", raw, pos)
        pos += 1
        y[i] = 1.0 if target > 0 else 0.0
        features[i] = np.frombuffer(raw, dtype="<f4", count=width, offset=pos)
        pos += width * 4
    return int(block), trials, q, y, features


def load() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    pieces = [read_stream(path) for path in sorted(FEATURE_ROOT.glob("*.bin"))]
    if len(pieces) != 72:
        raise RuntimeError(f"expected 72 streams, found {len(pieces)}")
    block = np.concatenate([np.full(len(piece[1]), piece[0], dtype=np.int64) for piece in pieces])
    trial = np.concatenate([piece[1] for piece in pieces])
    q = np.concatenate([piece[2] for piece in pieces])
    y = np.concatenate([piece[3] for piece in pieces])
    x = np.concatenate([piece[4] for piece in pieces], axis=0)
    return block, trial, q, y, x


def score_with_margin(model, x, y, q):
    logits = model.forward(x)[0]
    prediction = logits > 0.0
    errors = prediction != (y > 0.5)
    plus = y > 0.5
    minus = ~plus
    plus_error = float(np.sum(q[plus] * errors[plus]) / max(1e-12, np.sum(q[plus])))
    minus_error = float(np.sum(q[minus] * errors[minus]) / max(1e-12, np.sum(q[minus])))
    balanced = 0.5 * (plus_error + minus_error)
    return {
        "rows": int(len(y)),
        "balanced_error": balanced,
        "omega_hat": max(0.0, 1.0 - 2.0 * balanced),
        "positive_prediction_rate": float(np.mean(prediction)),
        "signed_margin": float(np.sum(q * (2.0 * y - 1.0) * logits) / max(1e-12, np.sum(q))),
        "mean_abs_logit": float(np.mean(np.abs(logits))),
    }


def main() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract["status"] != "QUALIFICATION_ONLY_FROZEN":
        raise SystemExit("F4-CAPACITY-01 contract is not frozen")
    encoder = load_encoder_module()
    blocks, trials, q, y, x = load()
    unique = sorted(np.unique(blocks).tolist())
    if unique != [303000, 303001, 303002, 303003]:
        raise SystemExit(f"unexpected blocks {unique}")

    within = []
    cross = []
    for fold_index, block in enumerate(unique):
        within_train = (blocks == block) & (trials < 6144)
        within_valid = (blocks == block) & (trials >= 6144)
        x_norm, _mean, _scale = encoder.standardize(x, within_train)
        model = encoder.Encoder(306000 + fold_index)
        model.fit(x_norm[within_train], y[within_train])
        result = score_with_margin(model, x_norm[within_valid], y[within_valid], q[within_valid])
        result.update({"block": int(block), "train_rows": int(within_train.sum()), "validation_rule": "trial >= 6144"})
        within.append(result)

        train = blocks != block
        valid = ~train
        x_norm, _mean, _scale = encoder.standardize(x, train)
        model = encoder.Encoder(304000 + fold_index)
        model.fit(x_norm[train], y[train])
        result = score_with_margin(model, x_norm[valid], y[valid], q[valid])
        result.update({"holdout_block": int(block), "train_rows": int(train.sum())})
        cross.append(result)

    pos = np.flatnonzero(y > 0.5)[:128]
    neg = np.flatnonzero(y <= 0.5)[:128]
    mem_idx = np.concatenate((pos, neg))
    mem_train = np.zeros(len(y), dtype=bool)
    mem_train[mem_idx] = True
    x_mem, _mean, _scale = encoder.standardize(x[mem_idx], np.ones(len(mem_idx), dtype=bool))
    model = encoder.Encoder(305000)
    for _ in range(1000):
        for start in range(0, len(mem_idx), 64):
            model.update(x_mem[start : start + 64], y[mem_idx][start : start + 64])
    memorization = score_with_margin(model, x_mem, y[mem_idx], q[mem_idx])
    memorization.update({"rows": 256, "positive_rows": 128, "negative_rows": 128, "epochs": 1000, "batch_size": 64})

    receipt = {
        "schema": "FLY-REACH-03-F4-CAPACITY-01-receipt-v1",
        "status": "PROBES_COMPLETE_REPRESENTATION_LADDER_DEFERRED",
        "identity": "F4-CAPACITY-01",
        "contract_sha256": sha(CONTRACT),
        "parent_encoder_spec_sha256": "3325e1b6ce91956162fa3022c9e2c3bdf3396b269e975da9c108f45d9129d43b",
        "feature_stream_identity": "f4-features-v1",
        "feature_streams": 72,
        "feature_rows": int(len(y)),
        "within_block_temporal": within,
        "memorization": memorization,
        "cross_block_signed_margin": cross,
        "representation_ladder": {
            "status": "DEFERRED",
            "reason": "first three probes are required before authoring any representation expansion",
            "measured_namespace_created": False,
        },
        "scientific_interpretation_opened": False,
        "measured_namespace_created": False,
        "biological_promotion": False,
        "no_prediction_flip_rescue": True,
        "no_estimator_tuning": True,
    }
    output = STUDY / "F4-CAPACITY-01-RECEIPT.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "memorization_omega": memorization["omega_hat"], "within": within, "cross": cross}, sort_keys=True))


if __name__ == "__main__":
    main()
