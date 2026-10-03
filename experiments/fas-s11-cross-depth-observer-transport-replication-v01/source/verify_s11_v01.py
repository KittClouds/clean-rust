from __future__ import annotations

import hashlib
import os
import struct
import time

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np

from s11_exec_common_v01 import EVENTS, FEATURES, MANIFEST, OBSERVERS, QUARTETS, RESULTS, RUN, canonical_json, entry, jsonl_rows, read_json, sha256_file, tree_root, verify_ancestry, verify_code_binding, write_json
from linear_core import classification_metrics, configure_determinism, predict_probabilities, standardized_raw_tensor


ANALYSIS = RUN / "analysis-v01"
LAYERS = tuple(range(1, 17))
SURFACES = ("M", "F")
CLASSES = (0, 1, 2)
QUOTAS = {0: 1733, 1: 1815, 2: 1770}
REPLICATES = 10_000
SEED = 18_020_131_653_510_978_038
ROWS = 21_272
DIM = 2_048
EXPECTED_ANALYSIS_SEAL = "44518d3901bf578a417d8897dda3485e9741262e80a676857d48297736cdcefc"


def verify_component(base, name: str) -> tuple[dict, list[dict]]:
    seal = read_json(base / name)
    actual = [entry(base.joinpath(*item["path"].split("/")), base) for item in seal["entries"]]
    actual.sort(key=lambda row: row["path"])
    expected = sorted(seal["entries"], key=lambda row: row["path"])
    root = tree_root(actual)
    if actual != expected or root != seal["root_sha256"]:
        raise RuntimeError(f"component tree mismatch: {base}/{name}; got {root}")
    return seal, actual


def load_frozen_observers() -> dict[tuple[int, str], dict[str, np.ndarray]]:
    analysis_seal_path = OBSERVERS / "analysis-seal-v09.json"
    if sha256_file(analysis_seal_path)[0] != EXPECTED_ANALYSIS_SEAL:
        raise RuntimeError("S09 observer seal file identity mismatch")
    seal = read_json(analysis_seal_path)
    entries = {item["path"]: item for item in seal["entries"]}
    out = {}
    for layer in LAYERS:
        for surface in SURFACES:
            relative = f"probes/layer-{layer:02d}/{surface}/probe-state-v09.npz"
            path = OBSERVERS / relative.replace("/", os.sep)
            expected = entries.get(relative)
            digest, size = sha256_file(path)
            if expected is None or (digest, size) != (expected["sha256"], expected["bytes"]):
                raise RuntimeError(f"S09 observer mismatch: {relative}")
            with np.load(path, allow_pickle=False) as data:
                state = {key: data[key].copy() for key in data.files}
            if not np.array_equal(state["classes"], np.asarray(CLASSES)):
                raise RuntimeError(f"observer class order mismatch: {relative}")
            out[(layer, surface)] = state
    return out


def rebuild_prediction_files(observers: dict[tuple[int, str], dict[str, np.ndarray]], labels: np.ndarray, device) -> dict[str, dict]:
    replay = {}
    for surface in SURFACES:
        for target_layer in LAYERS:
            path = FEATURES / "matrices" / f"layer-{target_layer:02d}-{surface}.f32le"
            matrix = np.memmap(path, dtype="<f4", mode="r", shape=(ROWS, DIM), order="C")
            raw = np.asarray(matrix)
            for source_layer in LAYERS:
                state = observers[(source_layer, surface)]
                x = standardized_raw_tensor(raw, state["scaler_mean"], state["scaler_scale"], device)
                probabilities = predict_probabilities(x, state["weights"], state["bias"], batch_rows=16_384)
                metrics = classification_metrics(labels, probabilities, state["classes"])
                predictions = np.asarray(state["classes"][probabilities.argmax(axis=1)], dtype="<i8")
                cell_id = f"{surface}-src-{source_layer:02d}-tgt-{target_layer:02d}"
                stored_path = RESULTS / "predictions" / f"{cell_id}.npy"
                stored = np.load(stored_path, allow_pickle=False)
                if not np.array_equal(predictions, stored):
                    raise RuntimeError(f"independent prediction replay differs: {cell_id}")
                digest = hashlib.sha256(predictions.tobytes(order="C")).hexdigest()
                replay[cell_id] = {"predictions": predictions, "metrics": metrics, "prediction_ids_sha256": digest}
                del x, probabilities, predictions, stored
            del matrix, raw
            print(f"Independent replay complete: {surface} target layer {target_layer:02d}/16", flush=True)
    return replay


def quartet_layout(events: list[dict], quartets: list[dict]) -> tuple[list[np.ndarray], np.ndarray]:
    row_index = {row["event_id"]: index for index, row in enumerate(events)}
    qrows = []
    qlabels = np.empty(len(quartets), dtype=np.int64)
    for qi, quartet in enumerate(quartets):
        variants = quartet["variants"]
        if [row["variant_id"] for row in variants] != ["A", "C", "E", "P"]:
            raise RuntimeError("bootstrap quartet ordering mismatch")
        indexes = np.asarray([row_index[row["event_id"]] for row in variants], dtype=np.int64)
        if len(set(indexes.tolist())) != 4 or any(events[i]["input_sha256"] != row["input_sha256"] for i, row in zip(indexes, variants, strict=True)):
            raise RuntimeError("bootstrap quartet row identity mismatch")
        qrows.append(indexes)
        qlabels[qi] = int(quartet["exact_target"])
    if len(np.unique(np.concatenate(qrows))) != ROWS:
        raise RuntimeError("fresh quartet rows do not partition the evaluation panel")
    class_indexes = [np.flatnonzero(qlabels == target) for target in CLASSES]
    if any(len(class_indexes[i]) != QUOTAS[target] for i, target in enumerate(CLASSES)):
        raise RuntimeError("bootstrap class quartet counts differ from frozen quotas")
    return qrows, qlabels


def bootstrap_replay(quartets: list[dict], qrows: list[np.ndarray], qlabels: np.ndarray, replay: dict[str, dict]) -> dict:
    q_count = len(quartets)
    correct = np.zeros((2, 16, 16, q_count), dtype=np.uint8)
    q_rows_matrix = np.stack(qrows, axis=0)
    q_expected_targets = np.repeat(np.asarray([int(row["exact_target"]) for row in quartets], dtype=np.int64), 4).reshape(q_count, 4)
    for si, surface in enumerate(SURFACES):
        for source in LAYERS:
            for target in LAYERS:
                cell = replay[f"{surface}-src-{source:02d}-tgt-{target:02d}"]["predictions"]
                correct[si, source - 1, target - 1] = np.count_nonzero(cell[q_rows_matrix] == q_expected_targets, axis=1)

    off = [(i, j) for i in range(16) for j in range(16) if i != j]
    contributions = np.zeros((3, q_count), dtype=np.float64)
    # Direct cellwise decomposition, with the same frozen equal-cell/equal-distance weighting.
    f_values = correct[1, [i for i, _ in off], [j for _, j in off], :].astype(np.float64) / 4.0
    m_values = correct[0, [i for i, _ in off], [j for _, j in off], :].astype(np.float64) / 4.0
    contributions[0] = np.mean(f_values - m_values, axis=0)
    x = np.arange(1, 16, dtype=np.float64)
    xc = x - x.mean()
    coeff = xc / np.dot(xc, xc)
    for si in (0, 1):
        for d in range(1, 16):
            cells = [(i, j) for i in range(16) for j in range(16) if abs(i - j) == d]
            cell_data = correct[si, [i for i, _ in cells], [j for _, j in cells], :].astype(np.float64) / 4.0
            contributions[si + 1] += coeff[d - 1] * cell_data.mean(axis=0)

    observed = np.asarray([
        np.mean([contributions[0, qlabels == target].mean() for target in CLASSES]),
        np.mean([contributions[1, qlabels == target].mean() for target in CLASSES]),
        np.mean([contributions[2, qlabels == target].mean() for target in CLASSES]),
    ], dtype=np.float64)
    saved_plan = (ANALYSIS / "bootstrap-plan-v01.bin").open("rb")
    plan_hash = hashlib.sha256()
    rng = np.random.Generator(np.random.PCG64(SEED))
    samples = np.empty((REPLICATES, 3), dtype=np.float64)
    class_indexes = [np.flatnonzero(qlabels == target) for target in CLASSES]
    for b in range(REPLICATES):
        class_stats = []
        for indexes in class_indexes:
            selected = rng.choice(indexes, size=len(indexes), replace=True).astype("<u4", copy=False)
            payload = selected.tobytes(order="C")
            stored = saved_plan.read(len(payload))
            if stored != payload:
                raise RuntimeError(f"bootstrap shared-plan byte mismatch at replicate {b}")
            plan_hash.update(payload)
            class_stats.append(contributions[:, selected.astype(np.int64)].mean(axis=1))
        samples[b] = np.mean(np.stack(class_stats, axis=1), axis=1)
    if saved_plan.read(1):
        raise RuntimeError("bootstrap plan has unexpected trailing bytes")
    saved_plan.close()
    if plan_hash.hexdigest() != read_json(ANALYSIS / "s11-confirmatory-analysis-v01.json")["bootstrap"]["plan_sha256"]:
        raise RuntimeError("bootstrap shared-plan hash mismatch")
    saved_samples = np.load(ANALYSIS / "bootstrap-primary-values-v01.npy", allow_pickle=False)
    if not np.array_equal(samples, saved_samples):
        raise RuntimeError("independent primary bootstrap replay differs")
    sd = samples.std(axis=0, ddof=1)
    z = np.max(np.abs(samples - observed[None, :]) / sd[None, :], axis=1)
    critical = float(np.quantile(z, 0.95, method="linear"))
    intervals = np.stack((observed - critical * sd, observed + critical * sd), axis=1)
    return {"observed": observed, "samples": samples, "sd": sd, "critical": critical, "intervals": intervals, "plan_sha256": plan_hash.hexdigest()}


def main() -> int:
    started = time.perf_counter()
    manifest = read_json(MANIFEST)
    verify_ancestry(manifest)
    code_binding = verify_code_binding(manifest)
    token_seal, _ = verify_component(RUN / "tokenization-v01", "tokenization-seal-v01.json")
    feature_seal, feature_entries = verify_component(FEATURES, "feature-cache-seal-v01.json")
    transport_seal, transport_entries = verify_component(RESULTS, "transport-seal-v01.json")
    analysis_seal, analysis_entries = verify_component(ANALYSIS, "analysis-seal-v01.json")

    events = [row for _, row in jsonl_rows(EVENTS)]
    quartets = [row for _, row in jsonl_rows(QUARTETS)]
    if len(events) != ROWS or len(quartets) != 5318:
        raise RuntimeError("independent verification panel count mismatch")
    labels = np.asarray([int(row["exact_target"]) for row in events], dtype=np.int64)
    observers = load_frozen_observers()
    device = configure_determinism()
    replay = rebuild_prediction_files(observers, labels, device)
    transport = read_json(RESULTS / "transport-results-v01.json")
    transport_cells = {(cell["surface"], cell["source_observer_layer"], cell["target_representation_layer"]): cell for surface in SURFACES for cell in transport["surface_results"][surface]["cells"]}
    if len(transport_cells) != 512 or len(replay) != 512:
        raise RuntimeError("transport verification did not cover exactly 512 cells")
    for key, replayed in replay.items():
        parts = key.split("-")
        surface, source, target = parts[0], int(parts[2]), int(parts[4])
        stored = transport_cells[(surface, source, target)]
        if replayed["metrics"] != stored["metrics"] or replayed["prediction_ids_sha256"] != stored["prediction_ids_sha256"]:
            raise RuntimeError(f"independent metrics/hash mismatch for {key}")

    qrows, qlabels = quartet_layout(events, quartets)
    bootstrap = bootstrap_replay(quartets, qrows, qlabels, replay)
    analysis = read_json(ANALYSIS / "s11-confirmatory-analysis-v01.json")
    names = ("D_off", "M_distance_slope", "F_distance_slope")
    for i, name in enumerate(names):
        recorded = analysis["primary_estimands"][name]
        expected = (float(bootstrap["observed"][i]), float(bootstrap["sd"][i]), float(bootstrap["intervals"][i, 0]), float(bootstrap["intervals"][i, 1]))
        actual = (recorded["estimate"], recorded["bootstrap_sd"], recorded["lower"], recorded["upper"])
        if actual != expected:
            raise RuntimeError(f"independent bootstrap summary mismatch for {name}: {actual} vs {expected}")
    if analysis["simultaneous_interval"]["critical_value"] != bootstrap["critical"]:
        raise RuntimeError("independent simultaneous critical value mismatch")

    prediction_hash = hashlib.sha256()
    for key in sorted(replay):
        prediction_hash.update(bytes.fromhex(replay[key]["prediction_ids_sha256"]))
    verification = {
        "receipt_id": "FAS_S11_INDEPENDENT_VERIFICATION_V01",
        "complete": True,
        "implementation_code_manifest_sha256": code_binding["manifest_sha256"],
        "protocol_amendment_panel_tuple_verified": True,
        "tokenization_entries_verified": len(token_seal["entries"]),
        "feature_cache_entries_verified": len(feature_entries),
        "transport_entries_verified": len(transport_entries),
        "analysis_entries_verified": len(analysis_entries),
        "transport_cells_independently_replayed": len(replay),
        "prediction_and_metric_replay_exact": True,
        "bootstrap_replicates_independently_replayed": REPLICATES,
        "bootstrap_plan_sha256": bootstrap["plan_sha256"],
        "bootstrap_samples_exact": True,
        "primary_summaries_exact": True,
        "sorted_prediction_digest_stream_sha256": prediction_hash.hexdigest(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    verification_path = RUN / "independent-verification-v01.json"
    write_json(verification_path, verification)
    final_receipt = {
        "result_id": "FAS_S11_RESULT_RECEIPT_V01",
        "complete": True,
        "S11_RESULT_READY": True,
        "S11_MODEL_CONTACT_COMPLETE": True,
        "S11_FEATURE_CACHE_SEALED": True,
        "S11_512_TRANSPORT_CELLS_COMPLETE": True,
        "S11_SHARED_BOOTSTRAP_COMPLETE": True,
        "S11_INDEPENDENT_VERIFICATION_PASS": True,
        "joint_replication_status": analysis["status"],
        "primary_estimands": analysis["primary_estimands"],
        "ancestry": manifest["authoritative_s11_ancestry"],
        "feature_cache_root_sha256": feature_seal["root_sha256"],
        "transport_root_sha256": transport_seal["root_sha256"],
        "analysis_root_sha256": analysis_seal["root_sha256"],
    }
    write_json(RUN / "s11-result-receipt-v01.json", final_receipt)

    excluded = {"execution-manifest-v01.json", "s11-final-seal-v01.json"}
    final_entries = [entry(path, RUN) for path in RUN.rglob("*") if path.is_file() and path.name not in excluded]
    final_entries.sort(key=lambda item: item["path"])
    final_root = tree_root(final_entries)
    write_json(RUN / "s11-final-seal-v01.json", {"seal_id": "FAS_S11_FINAL_RESULT_SEAL_V01", "entries": final_entries, "root_sha256": final_root})
    run_manifest = read_json(MANIFEST)
    run_manifest["independent_verification_pass"] = True
    run_manifest["S11_RESULT_READY"] = True
    run_manifest["final_result_root_sha256"] = final_root
    run_manifest["status"] = analysis["status"]
    write_json(MANIFEST, run_manifest)
    print(f"S11 final result sealed: {final_root}; status={analysis['status']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
