from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


PROJECT = Path(__file__).resolve().parents[1]
RUN = Path(r"D:\codex-runs\fas-s08-exact-decision-surface-attribution-v02")
S08_V01_RUN = Path(r"D:\codex-runs\fas-s08-exact-decision-surface-attribution-v01")
S08_V01_FAILURE_SEAL = S08_V01_RUN / "failed-attempt-seal-v01.json"
S08_V01_FAILURE_RECEIPT = S08_V01_RUN / "failed-attempt-receipt-v01.json"
S08_V01_FAILURE_ROOT = "db9319719bab147d3f755370455df0c11604fc6f85dfff72c9aa0380cef8c805"
S06_RUN = Path(r"D:\codex-runs\fas-s06-representation-scaler-probe-compatibility-cube-v02")
S06_PROJECT = Path(r"C:\code land\clean-rust\experiments\fas-s06-representation-scaler-probe-compatibility-cube-v01")
S06_BINDING = S06_PROJECT / "corrections" / "input-hash-v02" / "contracts" / "parent-binding-v02.json"
S06_PROTOCOL_SEAL = S06_PROJECT / "corrections" / "input-hash-v02" / "seals" / "protocol-seal-v02.json"
S06_RESULT_SEAL = S06_RUN / "result-tree-seal-v01.json"
S06_LEDGER = S06_RUN / "crossed-cube-ledger-v01.jsonl"
S06_SUMMARY = S06_RUN / "compatibility-summary-v01.json"
S06_RECEIPT = S06_RUN / "execution-receipt-v01.json"
S05_RUN = Path(r"D:\codex-runs\fas-s05-crossed-representation-readout-decomposition-v07")
S05_POPULATIONS = S05_RUN / "event-populations-v01.json"

S01_RUN = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography")
S01_CACHE_RUN = S01_RUN / "s01-2-feature-geometry-v01"
S01_CACHE = S01_CACHE_RUN / "feature-cache-v01"
S01_FEATURE_ROWS = S01_CACHE / "feature-rows-v01.jsonl"
S01_MEAN_FEATURES = S01_CACHE / "V0_MEAN_FULL.f32le"
S01_FINAL_FEATURES = S01_CACHE / "V1_FINAL_POSITION.f32le"
S01_CACHE_SEAL = S01_CACHE_RUN / "seals" / "feature-cache-seal-v01.json"
S01_CACHE_RESULT_SEAL = S01_CACHE_RUN / "seals" / "result-tree-seal-v01.json"
S01_ACCESS_RUN = S01_RUN / "s01-3-linear-accessibility-v01"
S01_META = S01_ACCESS_RUN / "metadata" / "event-metadata-v01.npz"
S01_ACCESS_SEAL = S01_ACCESS_RUN / "seals" / "result-tree-seal-v01.json"
S01_MEAN_PROBE = S01_ACCESS_RUN / "probes" / "V0_MEAN_FULL" / "EXACT_TARGET" / "probe-state-v01.npz"
S01_FINAL_PROBE = S01_ACCESS_RUN / "probes" / "V1_FINAL_POSITION" / "EXACT_TARGET" / "probe-state-v01.npz"

FAS00_RUN = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00")
FAS00_MEAN_FEATURES = FAS00_RUN / "phase2a-v01" / "feature-cache-v01" / "features-v01.f32le"
FAS00_MEAN_PROBE = FAS00_RUN / "phase3-v02" / "results-v01" / "probe-artifacts" / "HELDOUT_TERM_EXACT_TARGET.npz"
S02_RUN = Path(r"D:\codex-runs\fas-s02-original-corpus-readout-surface-attribution-v01")
S02_FINAL_FEATURES = S02_RUN / "s02-1-final-position-v02" / "feature-cache-v01" / "final-position-v01.f32le"
S02_FINAL_PROBE = S02_RUN / "s02-2-readout-attribution-v01" / "correction-v05" / "results-v01" / "final-position-probe-v01.npz"
S07_GATE_ROOT = Path(r"D:\codex-runs\fas-s07-sparse-compatibility-cartography-v01")
S07_GATE_SEAL = S07_GATE_ROOT / "gate-tree-seal-v01.json"

FEATURE_ROWS = 106496
FEATURE_WIDTH = 2048
FAS00_ROWS = 32768
HIDDEN = FEATURE_WIDTH
PAIR_ORDER = ((0, 1), (0, 2), (1, 2))
PAIR_KEYS = tuple(f"class_{a}_minus_class_{b}" for a, b in PAIR_ORDER)
FACTORS = ("R", "C", "D", "W")
SUBSETS = tuple(range(16))
K_SIZES = (8, 16, 32, 64, 128, 256)

EXPECTED_ROOTS = {
    "s06_result": "b21e4cb026d0b3956f9a666c4928a79922e39ee33b9f64653181d6dbc9a0d1b0",
    "s06_protocol": "ab2bbd4fc1918132e6674e97ef05e29e2eee52945a0ac37229e52c6f9e10b4e7",
    "s01_feature_cache": "4964f35fb87a45a9447cd0f5f028668027ca3ad3a8f0d0c3f9eb7b9cbe7ccaaa",
    "s01_accessibility": "2581b50d75382c197793ea46400bf2b8a27508df22b2ff5bdbe82eb20a5238b7",
    "s01_corpus": "51a55212ba89d55bd6df532673ad4546c95def1f5d75622661f7c17b3e4a7ad1",
    "s07_gate": "fe9bd0bd3de6769cf4374fd09b0cd600650560a7dbbd40d53e94ef0452f8c748",
    "s08_v01_failed_attempt": S08_V01_FAILURE_ROOT,
}


class FailClosed(RuntimeError):
    pass


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=1024 * 1024) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FailClosed(f"Refusing to overwrite S08 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def canonical_root(entries: list[dict[str, Any]], *, with_bytes: bool, casefold: bool) -> str:
    ordered = sorted(entries, key=lambda item: item["path"].casefold() if casefold else item["path"])
    if with_bytes:
        payload = "".join(f"{e['path']}\t{e['bytes']}\t{e['sha256']}\n" for e in ordered)
    else:
        payload = "".join(f"{e['path']} {e['sha256']}\n" for e in ordered)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_entries(root: Path, entries: list[dict[str, Any]], *, with_bytes: bool, casefold: bool) -> None:
    observed: list[dict[str, Any]] = []
    for entry in entries:
        path = root / Path(entry["path"])
        if not path.is_file():
            raise FailClosed(f"Missing sealed file: {path}")
        digest = sha_file(path)
        size = path.stat().st_size
        if digest != entry["sha256"] or (with_bytes and size != int(entry["bytes"])):
            raise FailClosed(f"Sealed file identity mismatch: {path}")
        observed.append({"path": entry["path"], "sha256": digest, "bytes": size})
    if canonical_root(observed, with_bytes=with_bytes, casefold=casefold) != canonical_root(entries, with_bytes=with_bytes, casefold=casefold):
        raise FailClosed("Sealed tree root reconstruction mismatch")


def load_probe(path: Path, dataset: str) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as archive:
        state = {key: np.array(archive[key], copy=True) for key in archive.files}
    if dataset == "FAS00_ORIGINAL":
        expected = {"weights", "bias", "mean", "scale"}
        if set(state) != expected:
            raise FailClosed(f"Unexpected FAS-00 readout fields: {path}")
        for key in expected:
            if state[key].dtype != np.dtype("<f8"):
                raise FailClosed(f"Unexpected FAS-00 readout dtype {key}: {state[key].dtype}")
        mean, scale = state["mean"], state["scale"]
    else:
        expected = {"classes", "weights", "bias", "scaler_mean", "scaler_scale"}
        if set(state) != expected:
            raise FailClosed(f"Unexpected S01 readout fields: {path}")
        if (not np.array_equal(state["classes"], np.array([0, 1, 2])) or
                state["weights"].dtype != np.dtype("<f4") or state["bias"].dtype != np.dtype("<f4") or
                state["scaler_mean"].dtype != np.dtype("<f8") or state["scaler_scale"].dtype != np.dtype("<f8")):
            raise FailClosed(f"S01 readout precision/class order differs: {path}")
        mean = state["scaler_mean"].astype(np.float32)
        scale = state["scaler_scale"].astype(np.float32)
        state["weights"] = state["weights"].astype(np.float32, copy=False)
        state["bias"] = state["bias"].astype(np.float32, copy=False)
    if (state["weights"].shape != (3, HIDDEN) or state["bias"].shape != (3,) or
            mean.shape != (HIDDEN,) or scale.shape != (HIDDEN,) or np.any(scale <= 0)):
        raise FailClosed(f"Readout shape/scale invalid: {path}")
    if not all(np.isfinite(state[k]).all() for k in state if state[k].dtype.kind in "f"):
        raise FailClosed(f"Non-finite readout parameters: {path}")
    state["replay_mean"] = mean
    state["replay_scale"] = scale
    return state


def load_features(path: Path, rows: int) -> np.memmap:
    expected = rows * FEATURE_WIDTH * 4
    if not path.is_file() or path.stat().st_size != expected:
        raise FailClosed(f"Feature cache byte count invalid: {path}")
    return np.memmap(path, dtype="<f4", mode="r", shape=(rows, FEATURE_WIDTH), order="C")


def load_s01_metadata() -> dict[str, np.ndarray]:
    with np.load(S01_META, allow_pickle=False) as archive:
        result = {k: np.array(archive[k], copy=True) for k in archive.files}
    required = {"event_id", "quartet_id", "row_index", "split_bucket", "variant", "context_id",
                "entity_id", "context_split", "entity_split", "observation_template", "query_template",
                "relation", "state", "target", "track", "world_family"}
    if set(result) != required or any(result[k].shape != (FEATURE_ROWS,) for k in required):
        raise FailClosed("S01 metadata inventory or row count differs")
    if not np.array_equal(result["row_index"], np.arange(FEATURE_ROWS, dtype=result["row_index"].dtype)):
        raise FailClosed("S01 metadata row_index is not canonical")
    return result


def memmap_rows(path: Path, rows: int, indexes: np.ndarray) -> np.ndarray:
    mm = load_features(path, rows)
    return np.asarray(mm[indexes], dtype=np.float64)
