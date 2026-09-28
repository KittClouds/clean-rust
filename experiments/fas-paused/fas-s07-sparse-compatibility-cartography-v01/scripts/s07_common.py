from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np


PROJECT = Path(__file__).resolve().parents[1]
RUN = Path(r"D:\codex-runs\fas-s07-sparse-compatibility-cartography-v01")
CONTRACTS = PROJECT / "contracts"
PARENT_BINDING = CONTRACTS / "parent-binding-v02.json"
SAE_CONTRACT = CONTRACTS / "sae-training-contract-v01.json"
ANALYSIS_CONTRACT = CONTRACTS / "analysis-contract-v01.json"
PROTOCOL_SEAL_V01 = PROJECT / "seals" / "protocol-seal-v01.json"
PROTOCOL_SEAL_V02 = PROJECT / "seals" / "protocol-seal-v02.json"
PROTOCOL_SEAL_V03 = PROJECT / "seals" / "protocol-seal-v03.json"
PROTOCOL_SEAL = PROJECT / "seals" / "protocol-seal-v04.json"

S01_ROOT = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography")
S01_2_ROOT = S01_ROOT / "s01-2-feature-geometry-v01"
S01_3_ROOT = S01_ROOT / "s01-3-linear-accessibility-v01"
S01_CACHE = S01_2_ROOT / "feature-cache-v01"
S01_META = S01_3_ROOT / "metadata" / "event-metadata-v01.npz"
S01_CORPUS = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2-v01-sealed\corpus\counterfactual-quartets-v01.jsonl")
S01_PROBE_M = S01_3_ROOT / "probes" / "V0_MEAN_FULL" / "EXACT_TARGET" / "probe-state-v01.npz"
S01_PROBE_F = S01_3_ROOT / "probes" / "V1_FINAL_POSITION" / "EXACT_TARGET" / "probe-state-v01.npz"

S04_ROOT = Path(r"D:\codex-runs\fas-s04-controlled-factor-to-decision-transfer-geometry-v01")
S05_ROOT = Path(r"D:\codex-runs\fas-s05-crossed-representation-readout-decomposition-v07")
S05_POPULATIONS = S05_ROOT / "event-populations-v01.json"
S06_ROOT = Path(r"D:\codex-runs\fas-s06-representation-scaler-probe-compatibility-cube-v02")
S06_LEDGER = S06_ROOT / "crossed-cube-ledger-v01.jsonl"
S06_SUMMARY = S06_ROOT / "compatibility-summary-v01.json"

FAS00_ROOT = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00")
FAS00_PHASE1_EVENTS = FAS00_ROOT / "phase1-v03" / "corpus" / "qualification-events-v03.jsonl"
FAS00_PHASE2 = FAS00_ROOT / "phase2a-v01"
FAS00_PHASE3 = FAS00_ROOT / "phase3-v02" / "results-v01"
FAS00_FEATURES = FAS00_PHASE2 / "feature-cache-v01" / "features-v01.f32le"
FAS00_MEAN_PROBE = FAS00_PHASE3 / "probe-artifacts" / "HELDOUT_TERM_EXACT_TARGET.npz"

S02_ROOT = Path(r"D:\codex-runs\fas-s02-original-corpus-readout-surface-attribution-v01")
S02_CACHE = S02_ROOT / "s02-1-final-position-v02" / "feature-cache-v01"
S02_RESULT = S02_ROOT / "s02-2-readout-attribution-v01" / "correction-v05"
S02_FEATURES = S02_CACHE / "final-position-v01.f32le"
S02_PROBE = S02_RESULT / "results-v01" / "final-position-probe-v01.npz"

S01_ROWS = 106_496
S01_HIDDEN = 2_048
FAS00_ROWS = 65_536
FAS00_EVENTS = 32_768
FAS00_HIDDEN = 2_048
S02_ROWS = 32_768
S02_HIDDEN = 2_048


class FailClosed(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=1024 * 1024) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def root_simple(entries: list[dict[str, Any]]) -> str:
    ordered = sorted(entries, key=lambda item: item["path"].casefold())
    payload = "".join(f"{item['path']} {item['sha256']}\n" for item in ordered)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def root_tab_bytes(entries: list[dict[str, Any]]) -> str:
    ordered = sorted(entries, key=lambda item: item["path"])
    payload = "".join(f"{item['path']}\t{item['bytes']}\t{item['sha256']}\n" for item in ordered)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_protocol() -> dict[str, Any]:
    if not PROTOCOL_SEAL_V01.is_file():
        raise FailClosed("Historical S07 protocol v01 seal is missing")
    previous = read_json(PROTOCOL_SEAL_V01)
    if root_simple(previous.get("entries", [])) != previous.get("root_sha256"):
        raise FailClosed("Historical S07 protocol v01 seal inventory is corrupt")
    previous_v2 = read_json(PROTOCOL_SEAL_V02)
    if root_simple(previous_v2.get("entries", [])) != previous_v2.get("root_sha256") or previous_v2.get("supersedes_protocol_root_sha256") != previous.get("root_sha256"):
        raise FailClosed("Historical S07 protocol v02 seal inventory is corrupt")
    previous_v3 = read_json(PROTOCOL_SEAL_V03)
    if root_simple(previous_v3.get("entries", [])) != previous_v3.get("root_sha256") or previous_v3.get("supersedes_protocol_root_sha256") != previous_v2.get("root_sha256"):
        raise FailClosed("Historical S07 protocol v03 seal inventory is corrupt")
    if not PROTOCOL_SEAL.is_file():
        raise FailClosed("Corrected S07 protocol v02 seal is missing")
    seal = read_json(PROTOCOL_SEAL)
    entries = seal.get("entries", [])
    if not entries or root_simple(entries) != seal.get("root_sha256") or seal.get("supersedes_protocol_root_sha256") != previous_v3.get("root_sha256"):
        raise FailClosed("S07 protocol v04 root or supersession binding mismatch")
    for item in entries:
        path = PROJECT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise FailClosed(f"S07 sealed source changed: {item['path']}")
    return seal


def verify_parent_manifest(path: Path, expected_root: str, *, style: str) -> dict[str, Any]:
    if not path.is_file():
        raise FailClosed(f"Missing parent seal: {path}")
    seal = read_json(path)
    entries = seal.get("entries", seal.get("files", []))
    if isinstance(entries, dict):
        entries = [{"path": key, **value} for key, value in entries.items()]
    if not isinstance(entries, list) or not entries:
        raise FailClosed(f"Parent seal has no inventory: {path}")
    root = root_tab_bytes(entries) if style == "tab_bytes" else root_simple(entries)
    if root != expected_root or seal.get("root_sha256") != expected_root:
        raise FailClosed(f"Parent seal root mismatch: {path}")
    return seal


def verify_direct_inputs(binding: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, item in binding["direct_inputs"].items():
        path = Path(item["path"])
        if not path.is_file():
            raise FailClosed(f"Missing bound input {name}: {path}")
        size = path.stat().st_size
        digest = sha256_file(path)
        if size != item["bytes"] or digest != item["sha256"]:
            raise FailClosed(f"Bound input identity mismatch: {name}")
        result[name] = {"path": item["path"], "bytes": size, "sha256": digest}
    return result


def load_probe(path: Path, *, precision: str) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as archive:
        if "weights" not in archive or "bias" not in archive:
            raise FailClosed(f"Malformed fixed probe: {path}")
        if "scaler_mean" in archive:
            mean, scale = archive["scaler_mean"], archive["scaler_scale"]
        else:
            mean, scale = archive["mean"], archive["scale"]
        dtype = np.float32 if precision == "float32" else np.float64
        return {
            "weights": np.asarray(archive["weights"], dtype=dtype),
            "bias": np.asarray(archive["bias"], dtype=dtype),
            "mean": np.asarray(mean, dtype=dtype),
            "scale": np.asarray(scale, dtype=dtype),
        }


def standardize(raw: np.ndarray, probe: dict[str, np.ndarray], *, precision: str) -> np.ndarray:
    if precision == "float32":
        values = np.asarray(raw, dtype=np.float32)
        mean = np.asarray(probe["mean"], dtype=np.float32)
        scale = np.asarray(probe["scale"], dtype=np.float32)
        return (values - mean) / scale
    values = np.asarray(raw, dtype=np.float64)
    return (values - probe["mean"]) / probe["scale"]


def apply_probe(x: np.ndarray, probe: dict[str, np.ndarray]) -> np.ndarray:
    return np.asarray(x @ probe["weights"].T + probe["bias"], dtype=probe["weights"].dtype)


def semantic_logits(slot_logits: np.ndarray, row: dict[str, Any]) -> np.ndarray:
    order = [int(value) for value in row["candidate_identity_order"]]
    state_by_id = {int(key): int(value) for key, value in row["state_by_candidate_identity"].items()}
    if len(order) != 3 or set(order) != {0, 1, 2} or set(state_by_id) != {0, 1, 2} or set(state_by_id.values()) != {0, 1, 2}:
        raise FailClosed("S01 candidate-position to semantic-state mapping is not a permutation")
    semantic = np.empty(3, dtype=np.float64)
    for position, identity in enumerate(order):
        semantic[state_by_id[identity]] = float(slot_logits[position])
    return semantic


def metrics(logits: np.ndarray, targets: np.ndarray) -> dict[str, Any]:
    values = np.asarray(logits, dtype=np.float64)
    labels = np.asarray(targets, dtype=np.int64)
    if values.ndim != 2 or values.shape != (len(labels), 3) or len(labels) == 0:
        raise FailClosed("Metric input shape/support invalid")
    if not np.isfinite(values).all() or np.any((labels < 0) | (labels > 2)):
        raise FailClosed("Metric input contains nonfinite values or invalid labels")
    predictions = np.argmax(values, axis=1)
    confusion = np.zeros((3, 3), dtype=np.int64)
    np.add.at(confusion, (labels, predictions), 1)
    support = confusion.sum(axis=1)
    if np.any(support == 0):
        raise FailClosed("Metric slice has an empty class")
    recall = np.diag(confusion) / support
    pair = {
        "class_0_minus_class_1": values[:, 0] - values[:, 1],
        "class_0_minus_class_2": values[:, 0] - values[:, 2],
        "class_1_minus_class_2": values[:, 1] - values[:, 2],
    }
    rivals = values.copy()
    rivals[np.arange(len(labels)), labels] = -np.inf
    target_margin = values[np.arange(len(labels)), labels] - np.max(rivals, axis=1)
    def summary(array: np.ndarray) -> dict[str, float]:
        ordered = np.sort(np.asarray(array, dtype=np.float64))
        def nr(q: float) -> float:
            return float(ordered[max(0, math.ceil(q * len(ordered)) - 1)])
        return {"mean": float(np.mean(ordered)), "median": nr(0.5), "p10": nr(0.1), "p90": nr(0.9), "min": float(ordered[0]), "max": float(ordered[-1])}
    return {
        "n": int(len(labels)),
        "accuracy": float(np.trace(confusion) / len(labels)),
        "balanced_accuracy": float(np.mean(recall)),
        "support_by_class": support.tolist(),
        "recall_by_class": recall.tolist(),
        "confusion_matrix_true_rows_predicted_columns": confusion.tolist(),
        "pairwise_margin_summary": {key: summary(value) for key, value in pair.items()},
        "target_margin_summary": summary(target_margin),
        "predictions": predictions,
        "target_margins": target_margin,
    }


def root_of_files(paths: list[Path], relative_to: Path) -> list[dict[str, Any]]:
    entries = []
    for path in paths:
        entries.append({"path": path.relative_to(relative_to).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return sorted(entries, key=lambda item: item["path"].casefold())
