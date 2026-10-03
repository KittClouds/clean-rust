"""Qualification-only NumPy MLP calibration for F0 through F3b.

The script intentionally does not create a measured identity. F4 is audited by
exact replay; because no learned F4 encoder is frozen in v0.1, the final receipt
is a fail-closed qualification disposition until that encoder is amended.
"""
from __future__ import annotations

import json
import mmap
import struct
from pathlib import Path

import numpy as np


STUDY = Path(__file__).resolve().parents[1]
RUN = STUDY / "runs" / "qualification-v2"
ROW_MODULUS = 256
EPOCHS = 200
CONFIGS = ((0.0003, 2048), (0.0003, 4096), (0.001, 2048), (0.001, 4096))
HIDDEN = (64, 32)
MAGIC = b"FLYREACH3ROWS\0"


def unpack(fmt: str, data: memoryview, pos: int):
    size = struct.calcsize(fmt)
    return struct.unpack_from(fmt, data, pos)[0], pos + size


def skip_vec(data: memoryview, pos: int, size: int) -> tuple[list[float], int]:
    count, pos = unpack("<B", data, pos)
    if size == 4:
        values = list(struct.unpack_from(f"<{count}f", data, pos)) if count else []
    else:
        values = list(struct.unpack_from(f"<{count}b", data, pos)) if count else []
    return values, pos + count * size


def pad(values: list[float], width: int, dtype=np.float32) -> np.ndarray:
    out = np.zeros(width, dtype=dtype)
    out[: min(width, len(values))] = values[:width]
    return out


def read_stream(path: Path) -> dict[str, list]:
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        data = memoryview(mapped)
        pos = 0
        if data[: len(MAGIC)].tobytes() != MAGIC:
            raise RuntimeError(f"bad row magic: {path}")
        pos += len(MAGIC)
        _version, pos = unpack("<I", data, pos)
        substrate_len, pos = unpack("<H", data, pos)
        pos += substrate_len
        side_len, pos = unpack("<H", data, pos)
        pos += side_len
        block, pos = unpack("<Q", data, pos)
        coordinate_count, pos = unpack("<I", data, pos)
        pos += coordinate_count * 4
        f0, f1, f2, f3a, f3b, targets, q = [], [], [], [], [], [], []
        row_index = 0
        while pos < len(data):
            _substrate_index, pos = unpack("<B", data, pos)
            _side_index, pos = unpack("<B", data, pos)
            _block, pos = unpack("<Q", data, pos)
            _trial, pos = unpack("<I", data, pos)
            coordinate, pos = unpack("<I", data, pos)
            probability, pos = unpack("<d", data, pos)
            reference, pos = unpack("<f", data, pos)
            target, pos = unpack("<b", data, pos)
            native, pos = unpack("<f", data, pos)
            support, pos = unpack("<B", data, pos)
            pre, pos = unpack("<I", data, pos)
            post, pos = unpack("<I", data, pos)
            pre_degree, pos = unpack("<I", data, pos)
            post_degree, pos = unpack("<I", data, pos)
            anatomical_sign, pos = unpack("<f", data, pos)
            weight, pos = unpack("<f", data, pos)
            eligibility, pos = unpack("<f", data, pos)
            spikes, pos = unpack("<I", data, pos)
            post_deviation, pos = unpack("<f", data, pos)
            local_signed, pos = unpack("<f", data, pos)
            weight_sign, pos = unpack("<b", data, pos)
            eligibility_history, pos = skip_vec(data, pos, 4)
            weight_history, pos = skip_vec(data, pos, 4)
            local_sign_history, pos = skip_vec(data, pos, 1)
            reward, pos = unpack("<f", data, pos)
            dan_mean, pos = unpack("<f", data, pos)
            feedback_mean, pos = unpack("<f", data, pos)
            gain, pos = unpack("<f", data, pos)
            scale, pos = unpack("<f", data, pos)
            _consumed, pos = unpack("<B", data, pos)
            eligibility_l1, pos = unpack("<f", data, pos)
            active_fraction, pos = unpack("<f", data, pos)
            work, pos = unpack("<Q", data, pos)
            events, pos = unpack("<Q", data, pos)
            _snapshot, pos = unpack("<I", data, pos)
            if target != 0 and support and row_index % ROW_MODULUS == 0:
                f0.append([coordinate, pre, post, pre_degree, post_degree, anatomical_sign])
                f1.append([weight, eligibility, spikes, post_deviation, local_signed, weight_sign])
                f2.append(np.concatenate((pad(eligibility_history, 32), pad(weight_history, 32), pad(local_sign_history, 32))))
                f3a.append([reward, dan_mean, feedback_mean, gain, scale])
                f3b.append([eligibility_l1, active_fraction, work, events])
                targets.append(1 if target > 0 else 0)
                q.append(1.0 / probability)
            row_index += 1
        del data
        return {"block": int(block), "f0": f0, "f1": f1, "f2": f2, "f3a": f3a, "f3b": f3b, "targets": targets, "q": q}


def load() -> dict[str, np.ndarray]:
    pieces = [read_stream(path) for path in sorted((RUN / "rows").glob("*.bin"))]
    keys = ("f0", "f1", "f2", "f3a", "f3b")
    output: dict[str, np.ndarray] = {}
    for key in keys:
        output[key] = np.asarray([row for piece in pieces for row in piece[key]], dtype=np.float32)
    output["targets"] = np.asarray([value for piece in pieces for value in piece["targets"]], dtype=np.float32)
    output["q"] = np.asarray([value for piece in pieces for value in piece["q"]], dtype=np.float64)
    output["blocks"] = np.asarray([piece["block"] for piece in pieces for _ in piece["targets"]], dtype=np.int64)
    return output


def gelu(x: np.ndarray) -> np.ndarray:
    return 0.5 * x * (1.0 + np.tanh(0.79788456 * (x + 0.044715 * x * x * x)))


def gelu_grad(x: np.ndarray) -> np.ndarray:
    t = np.tanh(0.79788456 * (x + 0.044715 * x * x * x))
    return 0.5 * (1.0 + t) + 0.5 * x * (1.0 - t * t) * 0.79788456 * (1.0 + 3.0 * 0.044715 * x * x)


class MLP:
    def __init__(self, width: int, seed: int):
        rng = np.random.default_rng(seed)
        self.w1 = (rng.standard_normal((width, 64)) * np.sqrt(2.0 / width)).astype(np.float32)
        self.b1 = np.zeros(64, dtype=np.float32)
        self.w2 = (rng.standard_normal((64, 32)) * np.sqrt(2.0 / 64)).astype(np.float32)
        self.b2 = np.zeros(32, dtype=np.float32)
        self.w3 = (rng.standard_normal((32, 1)) * np.sqrt(2.0 / 32)).astype(np.float32)
        self.b3 = np.zeros(1, dtype=np.float32)
        self.m = [np.zeros_like(value) for value in (self.w3, self.b3, self.w2, self.b2, self.w1, self.b1)]
        self.v = [np.zeros_like(value) for value in (self.w3, self.b3, self.w2, self.b2, self.w1, self.b1)]
        self.step = 0

    def forward(self, x: np.ndarray):
        z1 = x @ self.w1 + self.b1
        a1 = gelu(z1)
        z2 = a1 @ self.w2 + self.b2
        a2 = gelu(z2)
        logits = a2 @ self.w3 + self.b3
        return logits[:, 0], (x, z1, a1, z2, a2)

    def update(self, x: np.ndarray, y: np.ndarray, lr: float) -> None:
        logits, cache = self.forward(x)
        x, z1, a1, z2, a2 = cache
        p = 1.0 / (1.0 + np.exp(-np.clip(logits, -30.0, 30.0)))
        d3 = ((p - y) / max(1, len(y))).astype(np.float32)[:, None]
        grads = [a2.T @ d3, d3.sum(axis=0), a1.T @ ((d3 @ self.w3.T) * gelu_grad(z2)), ((d3 @ self.w3.T) * gelu_grad(z2)).sum(axis=0), x.T @ (((d3 @ self.w3.T) * gelu_grad(z2)) @ self.w2.T * gelu_grad(z1)), ((((d3 @ self.w3.T) * gelu_grad(z2)) @ self.w2.T) * gelu_grad(z1)).sum(axis=0)]
        values = [self.w3, self.b3, self.w2, self.b2, self.w1, self.b1]
        self.step += 1
        for index, (value, grad) in enumerate(zip(values, grads)):
            self.m[index] = 0.9 * self.m[index] + 0.1 * grad
            self.v[index] = 0.999 * self.v[index] + 0.001 * grad * grad
            m_hat = self.m[index] / (1.0 - 0.9 ** self.step)
            v_hat = self.v[index] / (1.0 - 0.999 ** self.step)
            value -= lr * m_hat / (np.sqrt(v_hat) + 1e-8)

    def fit(self, x: np.ndarray, y: np.ndarray, lr: float, batch: int, epochs: int = EPOCHS) -> None:
        for _ in range(epochs):
            for start in range(0, len(y), batch):
                self.update(x[start : start + batch], y[start : start + batch], lr)

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.forward(x)[0] > 0.0


def score(model: MLP, x: np.ndarray, y: np.ndarray, q: np.ndarray) -> tuple[float, float]:
    prediction = model.predict(x)
    errors = prediction != (y > 0.5)
    plus = y > 0.5
    minus = ~plus
    plus_error = float(np.sum(q[plus] * errors[plus]) / max(1e-12, np.sum(q[plus])))
    minus_error = float(np.sum(q[minus] * errors[minus]) / max(1e-12, np.sum(q[minus])))
    balanced = 0.5 * (plus_error + minus_error)
    return balanced, max(0.0, 1.0 - 2.0 * balanced)


def main() -> None:
    summary = json.loads((RUN / "QUALIFICATION-SUMMARY.json").read_text(encoding="utf-8"))
    if summary["status"] != "PASS":
        raise SystemExit("qualification summary is not PASS")
    data = load()
    results: dict[str, object] = {}
    unique_blocks = sorted(np.unique(data["blocks"]).tolist())
    cumulative = {
        "f0": data["f0"],
        "f1": np.concatenate((data["f0"], data["f1"]), axis=1),
        "f2": np.concatenate((data["f0"], data["f1"], data["f2"]), axis=1),
        "f3a": np.concatenate((data["f0"], data["f1"], data["f2"], data["f3a"]), axis=1),
        "f3b": np.concatenate((data["f0"], data["f1"], data["f2"], data["f3a"], data["f3b"]), axis=1),
    }
    for level in ("f0", "f1", "f2", "f3a", "f3b"):
        x = cumulative[level]
        mean = x.mean(axis=0)
        scale = x.std(axis=0)
        scale[scale < 1e-6] = 1.0
        x = ((x - mean) / scale).astype(np.float32)
        validation_block = unique_blocks[-1]
        train_mask = data["blocks"] != validation_block
        valid_mask = ~train_mask
        candidates = []
        for candidate_index, (lr, batch) in enumerate(CONFIGS):
            model = MLP(x.shape[1], 30303 + candidate_index)
            model.fit(x[train_mask], data["targets"][train_mask], lr, batch)
            balanced, omega = score(model, x[valid_mask], data["targets"][valid_mask], data["q"][valid_mask])
            candidates.append({"learning_rate": lr, "batch_size": batch, "balanced_error": balanced, "omega_hat": omega})
        selected = min(candidates, key=lambda row: row["balanced_error"])
        folds = []
        for fold_index, block in enumerate(unique_blocks):
            train = data["blocks"] != block
            valid = ~train
            model = MLP(x.shape[1], 30400 + fold_index)
            model.fit(x[train], data["targets"][train], selected["learning_rate"], selected["batch_size"])
            balanced, omega = score(model, x[valid], data["targets"][valid], data["q"][valid])
            folds.append({"holdout_block": int(block), "balanced_error": balanced, "omega_hat": omega, "rows": int(valid.sum())})
        results[level.upper()] = {"feature_width": int(x.shape[1]), "candidate_grid": candidates, "selected": selected, "leave_block_out": folds}
    receipt = {
        "schema": "FLY-REACH-03-qualification-estimator-receipt-v1",
        "attempt": "cumulative-filtration-v2",
        "status": "STOP_F4_LEARNED_ENCODER_REQUIRED",
        "run_id": "qualification-v2",
        "row_modulus": ROW_MODULUS,
        "rows_used": int(len(data["targets"])),
        "f0_f3b_results": results,
        "constant_baseline": {"balanced_error": 0.5, "omega_hat": 0.0},
        "f4_exact_reconstruction": "PASS; Omega(F4)=1 invariant audited separately",
        "f4_learned_calibration": "NOT_RUN; v0.1 freezes no practical F4 encoder",
        "measured_namespace_created": False,
        "measured_seal_created": False,
        "next_required_amendment": "freeze a deterministic F4 encoder and rerun qualification calibration before measured sealing",
    }
    (RUN / "QUALIFICATION-ESTIMATOR-RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "rows_used": receipt["rows_used"], "levels": list(results)}, sort_keys=True))


if __name__ == "__main__":
    main()
