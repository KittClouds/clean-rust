from __future__ import annotations

import hashlib
import os
import time

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np

from s11_exec_common_v03 import EVENTS, MANIFEST, QUARTETS, RESULTS, RUN, entry, jsonl_rows, read_json, sha256_file, tree_root, verify_ancestry, verify_code_binding, write_json


ANALYSIS = RUN / "analysis-v01"
SURFACES = ("M", "F")
LAYERS = tuple(range(1, 17))
CLASSES = (0, 1, 2)
QUOTAS = {0: 1733, 1: 1815, 2: 1770}
REPLICATES = 10_000
SEED = 18_020_131_653_510_978_038
PREDICTION_ROWS = 21_272


def load_transport() -> tuple[dict, np.ndarray, np.ndarray, list[dict], list[dict]]:
    seal = read_json(RESULTS / "transport-seal-v01.json")
    actual = [entry(RESULTS.joinpath(*row["path"].split("/")), RESULTS) for row in seal["entries"]]
    actual.sort(key=lambda row: row["path"])
    if actual != sorted(seal["entries"], key=lambda row: row["path"]) or tree_root(actual) != seal["root_sha256"]:
        raise RuntimeError("transport seal verification failed before bootstrap")
    transport = read_json(RESULTS / "transport-results-v01.json")
    panel_events_hash, _ = sha256_file(EVENTS)
    if panel_events_hash != read_json(MANIFEST)["authoritative_s11_ancestry"]["panel_events_sha256"]:
        raise RuntimeError("panel event identity changed before bootstrap")
    events = [row for _, row in jsonl_rows(EVENTS)]
    quartets = [row for _, row in jsonl_rows(QUARTETS)]
    if len(events) != PREDICTION_ROWS or len(quartets) != sum(QUOTAS.values()):
        raise RuntimeError("fresh panel row or quartet count mismatch")
    return transport, np.asarray([int(row["exact_target"]) for row in events], dtype=np.int64), np.asarray([str(row["event_id"]) for row in events]), events, quartets


def quartet_layout(events: list[dict], quartets: list[dict]) -> tuple[list[np.ndarray], np.ndarray, dict[str, int]]:
    event_index = {row["event_id"]: i for i, row in enumerate(events)}
    q_rows: list[np.ndarray] = []
    q_labels = np.empty(len(quartets), dtype=np.int64)
    for qi, quartet in enumerate(quartets):
        variants = quartet["variants"]
        if [row["variant_id"] for row in variants] != ["A", "C", "E", "P"]:
            raise RuntimeError(f"quartet variant order mismatch: {quartet['quartet_id']}")
        if any(int(row["exact_target"]) != int(quartet["exact_target"]) for row in variants):
            raise RuntimeError(f"quartet target invariance mismatch: {quartet['quartet_id']}")
        try:
            indexes = np.asarray([event_index[row["event_id"]] for row in variants], dtype=np.int64)
        except KeyError as exc:
            raise RuntimeError(f"quartet event missing from panel event table: {exc}") from exc
        if len(set(indexes.tolist())) != 4:
            raise RuntimeError(f"quartet event identity collision: {quartet['quartet_id']}")
        for variant, index in zip(variants, indexes, strict=True):
            if events[index]["input_sha256"] != variant["input_sha256"]:
                raise RuntimeError(f"event render identity mismatch: {variant['event_id']}")
        q_rows.append(indexes)
        q_labels[qi] = int(quartet["exact_target"])
    if sum(len(rows) for rows in q_rows) != PREDICTION_ROWS or len(set(np.concatenate(q_rows).tolist())) != PREDICTION_ROWS:
        raise RuntimeError("quartets do not partition all fresh event rows exactly once")
    class_indexes = [np.flatnonzero(q_labels == target) for target in CLASSES]
    if any(len(class_indexes[i]) != QUOTAS[target] for i, target in enumerate(CLASSES)):
        raise RuntimeError("exact-target class quartet counts differ from frozen quotas")
    return q_rows, q_labels, {str(target): len(class_indexes[i]) for i, target in enumerate(CLASSES)}


def observed_primary(matrices: dict[str, np.ndarray]) -> np.ndarray:
    m = matrices["M"]
    f = matrices["F"]
    off_diagonal = [(i, j) for i in range(16) for j in range(16) if i != j]
    d_off = float(np.mean([f[i, j] - m[i, j] for i, j in off_diagonal]))
    distances = np.arange(1, 16, dtype=np.float64)
    slopes = []
    for matrix in (m, f):
        curve = np.asarray([np.mean([matrix[i, j] for i in range(16) for j in range(16) if abs(i - j) == d]) for d in range(1, 16)], dtype=np.float64)
        centered = distances - distances.mean()
        slopes.append(float(np.dot(centered, curve) / np.dot(centered, centered)))
    return np.asarray([d_off, slopes[0], slopes[1]], dtype=np.float64)


def main() -> int:
    started = time.perf_counter()
    manifest = read_json(MANIFEST)
    verify_ancestry(manifest)
    code_binding = verify_code_binding(manifest)
    if ANALYSIS.exists() or ANALYSIS.with_name(ANALYSIS.name + ".tmp").exists():
        raise RuntimeError("analysis output already exists; preserve it and use a versioned attempt")
    transport, labels, event_ids, events, quartets = load_transport()
    q_rows, q_labels, class_counts = quartet_layout(events, quartets)
    event_lookup = {event_id: i for i, event_id in enumerate(event_ids.tolist())}
    prediction_arrays: dict[str, np.ndarray] = {}
    b_matrices: dict[str, np.ndarray] = {s: np.zeros((16, 16), dtype=np.float64) for s in SURFACES}
    correct_counts = np.zeros((2, 16, 16, len(quartets)), dtype=np.uint8)
    for surface_index, surface in enumerate(SURFACES):
        matrix = np.zeros((16, 16), dtype=np.float64)
        for source in LAYERS:
            for target in LAYERS:
                cell_id = f"{surface}-src-{source:02d}-tgt-{target:02d}"
                prediction_path = RESULTS / "predictions" / f"{cell_id}.npy"
                prediction = np.load(prediction_path, allow_pickle=False)
                prediction = np.asarray(prediction, dtype=np.int64)
                if prediction.shape != (PREDICTION_ROWS,):
                    raise RuntimeError(f"prediction shape mismatch: {cell_id}")
                prediction_arrays[cell_id] = prediction
                correct = prediction == labels
                matrix[source - 1, target - 1] = float(transport["surface_results"][surface]["balanced_accuracy_matrix_rows_source_cols_target"][source - 1][target - 1])
                for qi, indexes in enumerate(q_rows):
                    correct_counts[surface_index, source - 1, target - 1, qi] = np.count_nonzero(correct[indexes])
        b_matrices[surface] = matrix

    theta_observed = observed_primary(b_matrices)
    per_quartet = np.zeros((3, len(quartets)), dtype=np.float64)
    off_cells = [(i, j) for i in range(16) for j in range(16) if i != j]
    per_quartet[0] = np.mean(
        (correct_counts[1, [i for i, _ in off_cells], [j for _, j in off_cells], :].astype(np.float64)
         - correct_counts[0, [i for i, _ in off_cells], [j for _, j in off_cells], :].astype(np.float64)) / 4.0,
        axis=0,
    )
    distance_x = np.arange(1, 16, dtype=np.float64)
    distance_coeff = (distance_x - distance_x.mean()) / np.square(distance_x - distance_x.mean()).sum()
    for surface_index in (0, 1):
        slope_index = 1 + surface_index
        contribution = np.zeros(len(quartets), dtype=np.float64)
        for distance in range(1, 16):
            cells = [(i, j) for i in range(16) for j in range(16) if abs(i - j) == distance]
            vals = np.mean(correct_counts[surface_index, [i for i, _ in cells], [j for _, j in cells], :].astype(np.float64) / 4.0, axis=0)
            contribution += distance_coeff[distance - 1] * vals
        per_quartet[slope_index] = contribution

    class_indexes = [np.flatnonzero(q_labels == target) for target in CLASSES]
    linear_theta = np.mean(np.stack([per_quartet[:, indexes].mean(axis=1) for indexes in class_indexes], axis=1), axis=1)
    if not np.allclose(theta_observed, linear_theta, atol=1e-12, rtol=0.0):
        raise RuntimeError(f"observed primary estimator disagrees with quartet decomposition: {theta_observed} vs {linear_theta}")

    temp = ANALYSIS.with_name(ANALYSIS.name + ".tmp")
    temp.mkdir(parents=True)
    plan_path = temp / "bootstrap-plan-v01.bin"
    plan_hash = hashlib.sha256()
    bootstrap = np.empty((REPLICATES, 3), dtype=np.float64)
    rng = np.random.Generator(np.random.PCG64(SEED))
    with plan_path.open("wb") as plan_stream:
        for replicate in range(REPLICATES):
            by_class = []
            for indexes in class_indexes:
                selected = rng.choice(indexes, size=len(indexes), replace=True).astype("<u4", copy=False)
                payload = selected.tobytes(order="C")
                plan_stream.write(payload)
                plan_hash.update(payload)
                by_class.append(selected.astype(np.int64, copy=False))
            bootstrap[replicate] = np.mean(np.stack([
                per_quartet[:, selected].mean(axis=1) for selected in by_class
            ], axis=1), axis=1)
            if (replicate + 1) % 1000 == 0:
                print(f"S11 shared-plan bootstrap {replicate + 1}/{REPLICATES}", flush=True)
        plan_stream.flush()
        os.fsync(plan_stream.fileno())

    if not np.isfinite(bootstrap).all():
        raise RuntimeError("non-finite bootstrap statistic")
    sd = bootstrap.std(axis=0, ddof=1)
    if not np.isfinite(sd).all() or np.any(sd == 0.0):
        raise RuntimeError("zero or non-finite frozen bootstrap standard deviation")
    z = np.max(np.abs(bootstrap - theta_observed[None, :]) / sd[None, :], axis=1)
    critical = float(np.quantile(z, 0.95, method="linear"))
    intervals = np.stack((theta_observed - critical * sd, theta_observed + critical * sd), axis=1)
    names = ("D_off", "M_distance_slope", "F_distance_slope")
    interval_map = {name: {"estimate": float(theta_observed[i]), "bootstrap_sd": float(sd[i]), "lower": float(intervals[i, 0]), "upper": float(intervals[i, 1])} for i, name in enumerate(names)}
    joint_pass = bool(intervals[0, 0] > 0.0 and intervals[1, 1] < 0.0 and intervals[2, 1] < 0.0)

    distance_table = {}
    for distance in range(1, 16):
        m_values = [b_matrices["M"][i, j] for i in range(16) for j in range(16) if abs(i - j) == distance]
        f_values = [b_matrices["F"][i, j] for i in range(16) for j in range(16) if abs(i - j) == distance]
        distance_table[str(distance)] = {
            "M_raw_BA_mean": float(np.mean(m_values)),
            "F_raw_BA_mean": float(np.mean(f_values)),
            "paired_F_minus_M_mean": float(np.mean(np.asarray(f_values) - np.asarray(m_values))),
            "M_cells": len(m_values),
            "F_cells": len(f_values),
        }
    np.save(temp / "bootstrap-primary-values-v01.npy", bootstrap.astype("<f8", copy=False), allow_pickle=False)
    receipt = {
        "result_id": "FAS_S11_CONFIRMATORY_ANALYSIS_V01",
        "complete": True,
        "primary_estimands": interval_map,
        "simultaneous_interval": {"confidence_level": 0.95, "method": "max absolute standardized deviation across three primary summaries", "critical_value": critical, "quantile_method": "NumPy linear"},
        "joint_replication_rule": {"D_off_lower_gt_zero": bool(intervals[0, 0] > 0.0), "M_slope_upper_lt_zero": bool(intervals[1, 1] < 0.0), "F_slope_upper_lt_zero": bool(intervals[2, 1] < 0.0), "all_three": joint_pass},
        "transport_root_sha256": read_json(RESULTS / "transport-seal-v01.json")["root_sha256"],
        "implementation_code_manifest_sha256": code_binding["manifest_sha256"],
        "class_quartet_counts": class_counts,
        "quartet_count": len(quartets),
        "bootstrap": {"replicates": REPLICATES, "seed_label": "FAS-S11-V01-BOOTSTRAP-SEED", "seed_sha256": "f6594b9d435e14fa866626043f8898ec73c499eae05a08ce54c3538bfd595b92", "seed_u64": SEED, "rng": "NumPy Generator(PCG64)", "shared_plan": True, "resampling_unit": "whole quartets; all A/C/E/P rows remain together", "stratification": "independent within exact-target classes 0,1,2, exact observed counts", "plan_layout": "raw little-endian uint32 global quartet indices; replicate-major, class order 0,1,2", "plan_sha256": plan_hash.hexdigest(), "plan_bytes": plan_path.stat().st_size, "primary_values_file_sha256": sha256_file(temp / "bootstrap-primary-values-v01.npy")[0]},
        "distance_curve": distance_table,
        "scope": "quartet sampling uncertainty conditional on this fixed observer bank and fixed generator; excludes observer-training, model-seed, and generator-family variation",
        "status": "S11_CONFIRMATORY_JOINT_REPLICATION_SUPPORTED" if joint_pass else "S11_CONFIRMATORY_JOINT_REPLICATION_NOT_SUPPORTED",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(temp / "s11-confirmatory-analysis-v01.json", receipt)
    entries = [entry(path, temp) for path in temp.rglob("*") if path.is_file() and path.name != "analysis-seal-v01.json"]
    entries.sort(key=lambda row: row["path"])
    root = tree_root(entries)
    write_json(temp / "analysis-seal-v01.json", {"seal_id": "FAS_S11_ANALYSIS_SEAL_V01", "entries": entries, "root_sha256": root})
    temp.replace(ANALYSIS)
    run_manifest = read_json(MANIFEST)
    run_manifest["bootstrap_complete"] = True
    run_manifest["analysis_root_sha256"] = root
    run_manifest["status"] = "S11_ANALYSIS_SEALED_VERIFICATION_PENDING"
    write_json(MANIFEST, run_manifest)
    print(f"S11 bootstrap analysis sealed: {root}; joint={joint_pass}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
