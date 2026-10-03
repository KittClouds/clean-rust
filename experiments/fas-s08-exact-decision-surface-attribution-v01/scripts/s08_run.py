from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from s08_common import (
    FAS00_MEAN_FEATURES, FAS00_MEAN_PROBE, FEATURE_ROWS, FEATURE_WIDTH, HIDDEN, K_SIZES,
    PAIR_KEYS, PAIR_ORDER, PROJECT, RUN, S01_ACCESS_SEAL, S01_FINAL_FEATURES,
    S01_FINAL_PROBE, S01_MEAN_FEATURES, S01_MEAN_PROBE, S02_FINAL_FEATURES,
    S02_FINAL_PROBE, S05_POPULATIONS, S06_LEDGER, S06_RESULT_SEAL, S06_RUN,
    S07_GATE_ROOT, S07_GATE_SEAL, FailClosed, canonical_root, load_features,
    load_probe, load_s01_metadata, read_json, sha_file, verify_entries, write_json,
)
from s08_math import (
    classification_metrics, concentration_counts, describe, effective_geometry,
    matched_controls, subspace_comparison, top_indices, transition_counts,
    walsh_basis, walsh_transform,
)


S01_META = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-3-linear-accessibility-v01\metadata\event-metadata-v01.npz")
S01_FEATURE_ROWS = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\s01-2-feature-geometry-v01\feature-cache-v01\feature-rows-v01.jsonl")
S01_POPULATION_EVENTS = 19732
FAS00_MEAN_ROWS = 65536
FAS00_FINAL_ROWS = 32768
CHUNK = 256
PAIR_NAMES = [f"class_{a}_minus_class_{b}" for a, b in PAIR_ORDER]
FACTOR_CELL_ORDER = [f"R_{r}_C_{c}_D_{d}_W_{w}" for r in "MF" for c in "MF" for d in "MF" for w in "MF"]
SUBSET_NAMES = ["GRAND_MEAN"] + ["".join(f for bit, f in enumerate("RCDW") if mask & (1 << bit)) for mask in range(1, 16)]
S01_NATIVE_CELLS = {"M": "R_M_C_M_D_M_W_M", "F": "R_F_C_F_D_F_W_F"}
FAS00_NATIVE_CELLS = S01_NATIVE_CELLS
SELECTOR_NAMES = (
    "native_magnitude_M", "native_magnitude_F", "paired_surface_difference",
    "effective_normal_disagreement", "stable_signed_M", "stable_signed_F",
)


def _tree_verify(seal_path: Path, root: Path, *, with_bytes: bool, casefold: bool) -> dict[str, Any]:
    seal = read_json(seal_path)
    entries = seal.get("entries", seal.get("files", []))
    expected = seal.get("root_sha256")
    if not entries or canonical_root(entries, with_bytes=with_bytes, casefold=casefold) != expected:
        raise FailClosed(f"Parent seal root cannot be reconstructed: {seal_path}")
    verify_entries(root, entries, with_bytes=with_bytes, casefold=casefold)
    return seal


def verify_local_protocol() -> dict[str, Any]:
    seal_path = PROJECT / "seals" / "protocol-seal-v01.json"
    seal = read_json(seal_path)
    if seal.get("status") != "SEALED" or seal.get("seal_id") != "FAS_S08_PROTOCOL_SEAL_V01":
        raise FailClosed("S08 protocol seal missing or invalid")
    if canonical_root(seal["files"], with_bytes=True, casefold=False) != seal.get("root_sha256"):
        raise FailClosed("S08 protocol root metadata mismatch")
    verify_entries(PROJECT, seal["files"], with_bytes=True, casefold=False)
    return seal


def verify_parent_binding() -> tuple[dict[str, Any], dict[str, Any]]:
    binding_path = PROJECT / "contracts" / "parent-binding-v01.json"
    binding = read_json(binding_path)
    if binding.get("status") != "SEALED_INPUTS_VERIFIED_BEFORE_S08_ANALYSIS":
        raise FailClosed("S08 parent-binding status invalid")
    for item in binding["files"]:
        path = Path(item["path"])
        if not path.is_file() or path.stat().st_size != int(item["bytes"]) or sha_file(path) != item["sha256"]:
            raise FailClosed(f"S08 bound input changed: {item['name']}")
    if binding["expected_roots"].get("s06_result") != "b21e4cb026d0b3956f9a666c4928a79922e39ee33b9f64653181d6dbc9a0d1b0":
        raise FailClosed("S08 S06 root binding differs")
    s06 = _tree_verify(S06_RESULT_SEAL, S06_RUN, with_bytes=False, casefold=True)
    s01 = _tree_verify(S01_ACCESS_SEAL, S01_META.parents[1], with_bytes=True, casefold=False)
    if s06["root_sha256"] != binding["s06_root_sha256"] or s01["root_sha256"] != binding["s01_3_result_root_sha256"]:
        raise FailClosed("S08 parent seal roots changed")
    return binding, {"s06": s06, "s01_access": s01}


def load_row_population(dataset: str) -> tuple[list[dict[str, Any]], np.ndarray, dict[str, np.ndarray]]:
    meta = load_s01_metadata()
    ids = [item.decode("utf-8") for item in meta["event_id"]]
    id_to_row = {event_id: i for i, event_id in enumerate(ids)}
    if len(id_to_row) != FEATURE_ROWS:
        raise FailClosed("S01 event IDs are not unique")
    records: list[dict[str, Any]] = []
    margins = []
    metadata_rows = []
    with S06_LEDGER.open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record.get("dataset") != dataset:
                continue
            if set(record["cells"]) != set(FACTOR_CELL_ORDER):
                raise FailClosed(f"S06 cell inventory mismatch for {record['event_id']}")
            if dataset == "S01_CONTROLLED":
                row_idx = id_to_row.get(record["event_id"])
                if row_idx is None or int(meta["split_bucket"][row_idx]) != 0:
                    raise FailClosed(f"S06 S01 event does not bind to held-out row: {record['event_id']}")
                if int(record["target"]) != int(meta["state"][row_idx]):
                    raise FailClosed(f"S06 semantic target differs from S01 metadata: {record['event_id']}")
                if record["variant_id"] not in ("A", "C", "E", "P"):
                    raise FailClosed("Unexpected S01 counterfactual variant")
                metadata_rows.append(row_idx)
            margins.append([[float(record["cells"][cell]["margins"][key]) for key in PAIR_KEYS]
                            for cell in FACTOR_CELL_ORDER])
            records.append(record)
    expected = S01_POPULATION_EVENTS if dataset == "S01_CONTROLLED" else 512
    if len(records) != expected:
        raise FailClosed(f"S06 {dataset} population count {len(records)} != {expected}")
    row_indices = np.asarray(metadata_rows, dtype=np.int64) if dataset == "S01_CONTROLLED" else np.empty(0, dtype=np.int64)
    return records, np.asarray(margins, dtype=np.float64), {"meta": meta, "row_indices": row_indices, "ids": ids}


def verify_row_manifest(meta: dict[str, np.ndarray]) -> None:
    count = 0
    with S01_FEATURE_ROWS.open("r", encoding="utf-8") as stream:
        for count, line in enumerate(stream, start=1):
            row = json.loads(line)
            index = count - 1
            if int(row.get("row_index", -1)) != index or row.get("event_id") != meta["event_id"][index].decode("utf-8"):
                raise FailClosed(f"S01 feature-row manifest mismatch at row {index}")
    if count != FEATURE_ROWS:
        raise FailClosed(f"S01 feature-row manifest rows {count} != {FEATURE_ROWS}")


def _json_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metrics.items() if key not in {"predictions", "correct"}}


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _stats_by_axis(values: np.ndarray, names: list[str]) -> dict[str, Any]:
    return {name: describe(values[:, i]) for i, name in enumerate(names)}


def _add_metric_deltas(after: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    after["delta_accuracy"] = after["accuracy"] - before["accuracy"]
    after["delta_balanced_accuracy"] = after["balanced_accuracy"] - before["balanced_accuracy"]
    after["delta_recall_by_class"] = (np.asarray(after["recall_by_class"]) - np.asarray(before["recall_by_class"])).tolist()
    after["delta_pairwise_margin_mean"] = (np.asarray(after["pairwise_margin_mean"]) - np.asarray(before["pairwise_margin_mean"])).tolist()
    after["delta_pairwise_margin_median"] = [
        after["pairwise_margins"][key]["median"] - before["pairwise_margins"][key]["median"]
        for key in PAIR_KEYS
    ]
    after["delta_target_margin_mean"] = after["target_margin"]["mean"] - before["target_margin"]["mean"]
    after["delta_target_margin_median"] = after["target_margin"]["median"] - before["target_margin"]["median"]
    return after


def _save_npz(path: Path, **arrays: np.ndarray) -> None:
    if path.exists():
        raise FailClosed(f"Refusing to overwrite S08 array: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)


def _seal_tree(directory: Path, seal_name: str, seal_id: str, status: str) -> dict[str, Any]:
    entries = []
    for path in sorted((p for p in directory.rglob("*") if p.is_file() and p.name != seal_name), key=lambda p: p.relative_to(directory).as_posix()):
        entries.append({"path": path.relative_to(directory).as_posix(), "bytes": path.stat().st_size, "sha256": sha_file(path)})
    root = canonical_root(entries, with_bytes=True, casefold=False)
    seal = {"seal_id": seal_id, "status": status, "root_sha256": root, "entries": entries}
    write_json(directory / seal_name, seal)
    return seal


def _verify_stage_seal(directory: Path, seal_name: str) -> dict[str, Any]:
    seal = read_json(directory / seal_name)
    if canonical_root(seal["entries"], with_bytes=True, casefold=False) != seal.get("root_sha256"):
        raise FailClosed(f"S08 stage root does not reconstruct: {directory}")
    verify_entries(directory, seal["entries"], with_bytes=True, casefold=False)
    return seal


def preflight(protocol: dict[str, Any], binding: dict[str, Any]) -> tuple[list[str], np.ndarray, dict[str, np.ndarray]]:
    meta = load_s01_metadata()
    verify_row_manifest(meta)
    train = np.flatnonzero(np.isin(meta["split_bucket"], np.array([1, 2, 3, 4], dtype=np.uint8)))
    if len(train) != 85224:
        raise FailClosed(f"S01 train split count {len(train)} != 85224")
    records, _, joined = load_row_population("S01_CONTROLLED")
    test_rows = joined["row_indices"]
    if len(np.unique(test_rows)) != S01_POPULATION_EVENTS or np.intersect1d(train, test_rows).size:
        raise FailClosed("S01 training and S06 held-out rows overlap or are duplicated")
    for record, row_idx in zip(records, test_rows):
        cell_m = record["cells"][S01_NATIVE_CELLS["M"]]
        cell_f = record["cells"][S01_NATIVE_CELLS["F"]]
        slot_target = int(meta["target"][row_idx])
        if int(cell_m["candidate_position_prediction"] == slot_target) != int(cell_m["correct"]):
            raise FailClosed(f"S06 M exact-target parity mismatch: {record['event_id']}")
        if int(cell_f["candidate_position_prediction"] == slot_target) != int(cell_f["correct"]):
            raise FailClosed(f"S06 F exact-target parity mismatch: {record['event_id']}")
    if (protocol.get("root_sha256") is None or binding.get("s06_root_sha256") != "b21e4cb026d0b3956f9a666c4928a79922e39ee33b9f64653181d6dbc9a0d1b0"):
        raise FailClosed("S08 root inputs missing")
    receipt = {
        "receipt_id": "FAS_S08_PREFLIGHT_RECEIPT_V01",
        "status": "PASS",
        "protocol_root_sha256": protocol["root_sha256"],
        "parent_binding_sha256": sha_file(PROJECT / "contracts" / "parent-binding-v01.json"),
        "s06_rows": len(records),
        "s01_rows": FEATURE_ROWS,
        "s01_train_rows": len(train),
        "s01_heldout_rows": len(test_rows),
        "row_manifest_identity": "PASS",
        "s06_native_correctness_identity": "PASS",
        "fas00_values_loaded": False,
        "probe_fitting": False,
        "model_contact": False,
    }
    write_json(RUN / "preflight-receipt-v01.json", receipt)
    return [r["event_id"] for r in records], test_rows, {"meta": meta, "train_rows": train, "records": records}


def geometry_stage(dataset: str, row_ids: np.ndarray, observer_states: dict[str, dict[str, np.ndarray]],
                   feature_paths: dict[str, Path], feature_rows: dict[str, int]) -> dict[str, Any]:
    geoms = {name: effective_geometry(state) for name, state in observer_states.items()}
    comparison = subspace_comparison(geoms["M"], geoms["F"])
    per_observer = {}
    for name, geom in geoms.items():
        per_observer[name] = {
            "rank": geom["rank"],
            "rank_tolerance": geom["rank_tolerance"],
            "singular_values": geom["singular_values"].tolist(),
            "pair_norms": np.linalg.norm(geom["pair_normals"], axis=1).tolist(),
            "pair_intercepts": geom["pair_intercepts"].tolist(),
        }
    projections: dict[str, Any] = {"dataset": dataset, "subspace_comparison": comparison, "observer_geometry": per_observer, "margins": {}}
    self_residual = 0.0
    for rep in ("M", "F"):
        mm = load_features(feature_paths[rep], feature_rows[rep])
        idx = row_ids[rep] if isinstance(row_ids, dict) else row_ids
        h = np.asarray(mm[idx], dtype=np.float64)
        for observer in ("M", "F"):
            geom = geoms[observer]
            full = h @ geom["pair_normals"].T + geom["pair_intercepts"][None, :]
            for plane in ("M", "F"):
                q = geoms[plane]["basis"]
                projected = (h @ q.T) @ (geom["pair_normals"] @ q.T).T + geom["pair_intercepts"][None, :]
                key = f"representation_{rep}_observer_{observer}_plane_{plane}"
                projections["margins"][key] = {
                    "unprojected": _stats_by_axis(full, PAIR_NAMES),
                    "projected": _stats_by_axis(projected, PAIR_NAMES),
                    "projected_minus_full": _stats_by_axis(projected - full, PAIR_NAMES),
                    "max_abs_margin_difference": float(np.max(np.abs(projected - full))),
                }
                if plane == observer:
                    self_residual = max(self_residual, float(np.max(np.abs(projected - full))))
    if self_residual > 1e-8:
        raise FailClosed(f"Self-plane projection changed pair margins by {self_residual}")
    projections["self_plane_max_abs_residual"] = self_residual
    projections["coordinate_system"] = "original frozen hidden coordinates; affine intercept remains unprojected"
    return {"geometry": per_observer, "comparison": comparison, "projections": projections,
            "arrays": geoms}


def factorial_stage(dataset: str, records: list[dict[str, Any]], margins: np.ndarray,
                    meta: dict[str, np.ndarray] | None, row_indices: np.ndarray | None,
                    out_dir: Path, fas00_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    basis, subset_names = walsh_basis(FACTOR_CELL_ORDER)
    coefficients, residual = walsh_transform(margins, basis)
    if residual > 1e-10:
        raise FailClosed(f"Walsh reconstruction residual {residual} exceeds tolerance")
    targets = np.asarray([int(record["target"]) for record in records], dtype=np.int8)
    native_m = [bool(r["cells"][S01_NATIVE_CELLS["M"]]["correct"]) for r in records]
    native_f = [bool(r["cells"][S01_NATIVE_CELLS["F"]]["correct"]) for r in records]
    transitions = np.asarray(["both_correct" if a and b else "M_only" if a else "F_only" if b else "both_wrong"
                              for a, b in zip(native_m, native_f)], dtype="U12")
    event_values = [record["event_id"] for record in records]
    event_ids = np.asarray(event_values, dtype=f"U{max(map(len, event_values))}")
    groups: dict[str, np.ndarray] = {"ALL": np.ones(len(records), dtype=bool)}
    metadata_arrays: dict[str, np.ndarray] = {}
    if dataset == "S01_CONTROLLED":
        assert meta is not None and row_indices is not None
        metadata_arrays = {
            "target_slot": meta["target"][row_indices].astype(np.int8),
            "variant": np.asarray([r["variant_id"] for r in records], dtype="U1"),
            "context_split": meta["context_split"][row_indices],
            "entity_split": meta["entity_split"][row_indices],
            "world_family": meta["world_family"][row_indices],
            "context_id": meta["context_id"][row_indices],
            "entity_id": meta["entity_id"][row_indices],
        }
        for value in sorted(set(targets.tolist())):
            groups[f"target_state_{value}"] = targets == value
        for value in sorted(set(transitions.tolist())):
            groups[f"native_transition_{value}"] = transitions == value
        for name, values in (("variant", metadata_arrays["variant"]), ("context_split", metadata_arrays["context_split"]),
                             ("entity_split", metadata_arrays["entity_split"]), ("world_family", metadata_arrays["world_family"])):
            for value in sorted(set(values.tolist()), key=str):
                groups[f"{name}_{value}"] = values == value
        for c in (0, 1):
            for e in (0, 1):
                groups[f"context_split_{c}_x_entity_split_{e}"] = (metadata_arrays["context_split"] == c) & (metadata_arrays["entity_split"] == e)
    else:
        if fas00_rows is None or len(fas00_rows) != len(records):
            raise FailClosed("FAS-00 factorial metadata is missing or misaligned")
        slices = [set(r.get("slices", [])) for r in records]
        for slice_name in ("CONTEXT_TERM_3", "ENTITY_TERM_7"):
            groups[slice_name] = np.asarray([slice_name in s for s in slices], dtype=bool)
        for value in sorted(set(targets.tolist())):
            groups[f"target_class_{value}"] = targets == value
        for field in ("world_family", "task_structure", "feedback_condition"):
            values = np.asarray([row[field] for row in fas00_rows], dtype="U64")
            for value in sorted(set(values.tolist())):
                groups[f"{field}_{value}"] = values == value

    summary: dict[str, Any] = {
        "dataset": dataset,
        "event_count": len(records),
        "pair_order": PAIR_NAMES,
        "factor_order": ["R", "C", "D", "W"],
        "cell_order": FACTOR_CELL_ORDER,
        "subset_order": subset_names,
        "max_reconstruction_residual": residual,
        "grouped_coefficients": {},
    }
    for group_name, mask in groups.items():
        if not np.any(mask):
            continue
        payload: dict[str, Any] = {"n": int(mask.sum()), "by_pair": {}}
        for pair_index, pair_name in enumerate(PAIR_NAMES):
            payload["by_pair"][pair_name] = {}
            for subset_index, subset_name in enumerate(subset_names):
                values = coefficients[mask, pair_index, subset_index]
                detail = describe(values)
                if subset_index:
                    detail["balanced_high_minus_low_effect"] = 2.0 * detail["mean"]
                payload["by_pair"][pair_name][subset_name] = detail
        summary["grouped_coefficients"][group_name] = payload

    arrays = {
        "event_ids": event_ids,
        "coefficients": coefficients.astype(np.float64),
        "targets": targets,
        "native_transition": transitions,
        "basis": basis,
    }
    arrays.update(metadata_arrays)
    filename = "s01-factorial-coefficients-v01.npz" if dataset == "S01_CONTROLLED" else "fas00-factorial-coefficients-v01.npz"
    _save_npz(out_dir / filename, **arrays)
    summary["coefficient_file"] = filename
    return summary


def _rank_desc(values: np.ndarray) -> np.ndarray:
    order = np.argsort(-np.asarray(values), kind="stable")
    ranks = np.empty(len(order), dtype=np.int64)
    ranks[order] = np.arange(len(order))
    return ranks


def _stability_half(quartet: str) -> int:
    digest = hashlib.sha256(("FAS-S08-STABILITY-HALF-V01|" + quartet).encode("utf-8")).digest()
    return digest[0] & 1


def _concentration_summary(k_values: np.ndarray, target_slots: np.ndarray) -> dict[str, Any]:
    fractions = ("K50", "K80", "K90", "K95")
    output: dict[str, Any] = {"overall": {}, "by_target_slot": {}}
    for pair_idx, pair in enumerate(PAIR_NAMES):
        output["overall"][pair] = {frac: describe(k_values[:, pair_idx, j]) for j, frac in enumerate(fractions)}
        output["by_target_slot"][pair] = {}
        for target in range(3):
            selected = target_slots == target
            if np.any(selected):
                output["by_target_slot"][pair][str(target)] = {
                    frac: describe(k_values[selected, pair_idx, j]) for j, frac in enumerate(fractions)
                }
    return output


def coordinate_stage(test_records: list[dict[str, Any]], test_rows: np.ndarray,
                     meta: dict[str, np.ndarray], out_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    train_rows = np.flatnonzero(np.isin(meta["split_bucket"], np.array([1, 2, 3, 4], dtype=np.uint8)))
    if len(train_rows) != 85224:
        raise FailClosed("S08 coordinate selection train row count changed")
    if len(test_rows) != S01_POPULATION_EVENTS:
        raise FailClosed("S08 coordinate test population count changed")
    states = {"M": load_probe(S01_MEAN_PROBE, "S01_CONTROLLED"),
              "F": load_probe(S01_FINAL_PROBE, "S01_CONTROLLED")}
    geoms = {name: effective_geometry(state) for name, state in states.items()}
    feature_maps = {"M": load_features(S01_MEAN_FEATURES, FEATURE_ROWS),
                    "F": load_features(S01_FINAL_FEATURES, FEATURE_ROWS)}
    ntrain = len(train_rows)
    sum_abs = {v: np.zeros((3, HIDDEN), dtype=np.float64) for v in ("M", "F")}
    sum_signed = {v: np.zeros((3, HIDDEN), dtype=np.float64) for v in ("M", "F")}
    sum_abs_diff = np.zeros((3, HIDDEN), dtype=np.float64)
    sum_z = {v: np.zeros(HIDDEN, dtype=np.float64) for v in ("M", "F")}
    sum_z2 = {v: np.zeros(HIDDEN, dtype=np.float64) for v in ("M", "F")}
    half_abs = {v: np.zeros((2, 3, HIDDEN), dtype=np.float64) for v in ("M", "F")}
    sign_same = np.zeros(3, dtype=np.int64)
    sign_valid = np.zeros(3, dtype=np.int64)
    max_identity = 0.0
    quartets = [x.decode("utf-8") for x in meta["quartet_id"][train_rows]]
    halves = np.asarray([_stability_half(q) for q in quartets], dtype=np.uint8)
    gM = geoms["M"]
    gF = geoms["F"]

    for start in range(0, ntrain, CHUNK):
        indices = train_rows[start:start + CHUNK]
        hm = np.asarray(feature_maps["M"][indices], dtype=np.float64)
        hf = np.asarray(feature_maps["F"][indices], dtype=np.float64)
        cm = (hm - states["M"]["replay_mean"][None, :])[:, None, :] * gM["pair_normals"][None, :, :]
        cf = (hf - states["F"]["replay_mean"][None, :])[:, None, :] * gF["pair_normals"][None, :, :]
        for name, values in (("M", cm), ("F", cf)):
            sum_abs[name] += np.abs(values).sum(axis=0)
            sum_signed[name] += values.sum(axis=0)
            z = (hm if name == "M" else hf) - states[name]["replay_mean"][None, :]
            z = z / states[name]["replay_scale"][None, :]
            sum_z[name] += z.sum(axis=0)
            sum_z2[name] += np.square(z).sum(axis=0)
            for half in (0, 1):
                local = halves[start:start + len(indices)] == half
                if np.any(local):
                    half_abs[name][half] += np.abs(values[local]).sum(axis=0)
        sum_abs_diff += np.abs(cf - cm).sum(axis=0)
        valid = (cm != 0) & (cf != 0)
        sign_same += np.sum(valid & (np.sign(cm) == np.sign(cf)), axis=(0, 2))
        sign_valid += np.sum(valid, axis=(0, 2))
        for values, geom in ((cm, gM), (cf, gF)):
            reconstructed = values.sum(axis=2) + geom["pair_intercepts"][None, :]
            direct = (hm if geom is gM else hf) @ geom["pair_normals"].T + geom["pair_intercepts"][None, :]
            max_identity = max(max_identity, float(np.max(np.abs(reconstructed - direct))))
    if max_identity > 1e-8:
        raise FailClosed(f"S08 train coordinate margin identity error {max_identity}")

    mag_m = sum_abs["M"].mean(axis=0)
    mag_f = sum_abs["F"].mean(axis=0)
    diff_score = sum_abs_diff.mean(axis=0)
    normal_disagreement = np.sqrt(np.mean(np.square(gM["pair_normals"] - gF["pair_normals"]), axis=0))
    stable_m = np.abs(sum_signed["M"] / ntrain).mean(axis=0)
    stable_f = np.abs(sum_signed["F"] / ntrain).mean(axis=0)
    selector_scores = {
        "native_magnitude_M": mag_m,
        "native_magnitude_F": mag_f,
        "paired_surface_difference": diff_score,
        "effective_normal_disagreement": normal_disagreement,
        "stable_signed_M": stable_m,
        "stable_signed_F": stable_f,
    }
    variance_m = np.maximum(sum_z2["M"] / ntrain - np.square(sum_z["M"] / ntrain), 0.0)
    variance_f = np.maximum(sum_z2["F"] / ntrain - np.square(sum_z["F"] / ntrain), 0.0)
    covariates = np.stack([np.log1p(variance_m), np.log1p(variance_f), np.log1p(mag_m), np.log1p(mag_f)], axis=1)

    groups: dict[str, Any] = {}
    for name, score in selector_scores.items():
        for k in K_SIZES:
            selected = top_indices(score, k)
            control = matched_controls(selected, score, covariates)
            groups[f"{name}/k{k}"] = {"selector": name, "k": k, "selected": selected, "control": control,
                                        "selected_score": score[selected].tolist(), "control_score": score[control].tolist()}

    overlaps: dict[str, Any] = {"aggregate": {}, "by_pair": {}}
    for pair_idx, pair in enumerate(PAIR_NAMES):
        scores_by_view = {v: sum_abs[v][pair_idx] for v in ("M", "F")}
        overlaps["by_pair"][pair] = {}
        for k in K_SIZES:
            a = set(top_indices(scores_by_view["M"], k)); b = set(top_indices(scores_by_view["F"], k))
            overlaps["by_pair"][pair][str(k)] = {"intersection": len(a & b), "jaccard": len(a & b) / len(a | b)}
    for k in K_SIZES:
        a = set(top_indices(sum_abs["M"].mean(axis=0), k)); b = set(top_indices(sum_abs["F"].mean(axis=0), k))
        overlaps["aggregate"][str(k)] = {"intersection": len(a & b), "jaccard": len(a & b) / len(a | b)}

    stability: dict[str, Any] = {}
    for view in ("M", "F"):
        stability[view] = {}
        for pair_idx, pair in enumerate(PAIR_NAMES):
            a = half_abs[view][0, pair_idx] / max(int((halves == 0).sum()), 1)
            b = half_abs[view][1, pair_idx] / max(int((halves == 1).sum()), 1)
            ra, rb = _rank_desc(a), _rank_desc(b)
            corr = float(np.corrcoef(ra, rb)[0, 1])
            ta, tb = set(top_indices(a, 32)), set(top_indices(b, 32))
            stability[view][pair] = {"spearman_rank_correlation": corr,
                                     "top32_intersection": len(ta & tb), "top32_jaccard": len(ta & tb) / len(ta | tb)}

    test_k: dict[str, list[np.ndarray]] = {v: [] for v in ("M", "F")}
    sign_test_same = np.zeros(3, dtype=np.int64); sign_test_valid = np.zeros(3, dtype=np.int64)
    ntest = len(test_rows)
    for start in range(0, ntest, CHUNK):
        indices = test_rows[start:start + CHUNK]
        hm = np.asarray(feature_maps["M"][indices], dtype=np.float64)
        hf = np.asarray(feature_maps["F"][indices], dtype=np.float64)
        cm = (hm - states["M"]["replay_mean"][None, :])[:, None, :] * gM["pair_normals"][None, :, :]
        cf = (hf - states["F"]["replay_mean"][None, :])[:, None, :] * gF["pair_normals"][None, :, :]
        test_k["M"].append(concentration_counts(np.abs(cm)))
        test_k["F"].append(concentration_counts(np.abs(cf)))
        valid = (cm != 0) & (cf != 0)
        sign_test_same += np.sum(valid & (np.sign(cm) == np.sign(cf)), axis=(0, 2))
        sign_test_valid += np.sum(valid, axis=(0, 2))
    target_slots = meta["target"][test_rows].astype(np.int8)
    k_arrays = {v: np.concatenate(test_k[v]) for v in ("M", "F")}
    concentrations = {v: _concentration_summary(k_arrays[v], target_slots) for v in ("M", "F")}
    _save_npz(
        out_dir / "s01-heldout-coordinate-concentration-v01.npz",
        event_ids=np.asarray([r["event_id"] for r in test_records], dtype=f"U{max(len(r['event_id']) for r in test_records)}"),
        target_slots=target_slots,
        K_M=k_arrays["M"],
        K_F=k_arrays["F"],
    )
    _save_npz(
        out_dir / "s01-coordinate-selector-scores-v01.npz",
        selector_names=np.asarray(list(selector_scores), dtype="U40"),
        scores=np.stack([selector_scores[name] for name in selector_scores]),
        coordinate_ids=np.arange(HIDDEN, dtype=np.uint16),
    )
    census = {
        "training_rows": ntrain,
        "heldout_rows": ntest,
        "training_margin_identity_max_abs_error": max_identity,
        "pair_names_output_slot_order": PAIR_NAMES,
        "training_contribution_summaries": {
            v: {pair: {"absolute_contribution": describe(sum_abs[v][p] / ntrain),
                       "signed_mean_contribution": describe(sum_signed[v][p] / ntrain)}
                for p, pair in enumerate(PAIR_NAMES)} for v in ("M", "F")
        },
        "heldout_concentration_K": concentrations,
        "native_M_F_sign_agreement_training": {pair: {"same_sign_fraction": float(sign_same[p] / sign_valid[p]) if sign_valid[p] else None,
                                                         "valid_pairs": int(sign_valid[p])} for p, pair in enumerate(PAIR_NAMES)},
        "native_M_F_sign_agreement_heldout": {pair: {"same_sign_fraction": float(sign_test_same[p] / sign_test_valid[p]) if sign_test_valid[p] else None,
                                                        "valid_pairs": int(sign_test_valid[p])} for p, pair in enumerate(PAIR_NAMES)},
        "native_top_coordinate_overlap": overlaps,
        "training_rank_stability_by_quartet_hash_half": stability,
        "selector_score_top_coordinates": {name: [{"coordinate": int(i), "score": float(score[i])}
                                                    for i in top_indices(score, 64)] for name, score in selector_scores.items()},
    }

    interventions = run_s01_interventions(groups, states, feature_maps, test_rows, meta, test_records)
    coordinate_group_output = {"selectors": _json_safe(groups), "k_sizes": K_SIZES,
                               "selection_rows": ntrain, "test_rows": ntest,
                               "selection_source": "S01 split_bucket 1..4 only; FAS-00 untouched"}
    return census, coordinate_group_output, interventions


def run_s01_interventions(groups: dict[str, Any], states: dict[str, dict[str, np.ndarray]],
                          feature_maps: dict[str, np.memmap], test_rows: np.ndarray,
                          meta: dict[str, np.ndarray], records: list[dict[str, Any]]) -> dict[str, Any]:
    targets = meta["target"][test_rows].astype(np.int64)
    by_id = {record["event_id"]: record for record in records}
    native_prediction_expected = {v: np.asarray([by_id[meta["event_id"][i].decode()]["cells"][S01_NATIVE_CELLS[v]]["candidate_position_prediction"]
                                                   for i in test_rows], dtype=np.int64) for v in ("M", "F")}
    baseline: dict[str, dict[str, Any]] = {}
    prepared: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for observer in ("M", "F"):
        state = states[observer]
        mm = feature_maps[observer]
        hidden = np.asarray(mm[test_rows], dtype=np.float32)
        z = (hidden - state["replay_mean"].astype(np.float32)[None, :]) / state["replay_scale"].astype(np.float32)[None, :]
        logits = z @ state["weights"].astype(np.float32).T + state["bias"].astype(np.float32)[None, :]
        pred = np.argmax(logits, axis=1)
        if not np.array_equal(pred, native_prediction_expected[observer]):
            mismatches = int(np.count_nonzero(pred != native_prediction_expected[observer]))
            raise FailClosed(f"S08 raw S01 {observer} predictions differ from S06 diagonal by {mismatches}")
        metric = classification_metrics(logits, targets)
        baseline[observer] = _json_metrics(metric)
        prepared[observer] = (z, logits)

    result: dict[str, Any] = {"baseline_native": baseline, "interventions": {}}
    for group_name, entry in groups.items():
        result["interventions"][group_name] = {}
        for kind in ("selected", "control"):
            indexes = np.asarray(entry[kind], dtype=np.int64)
            for observer in ("M", "F"):
                z, logits = prepared[observer]
                state = states[observer]
                delta = z[:, indexes] @ state["weights"][:, indexes].astype(np.float32).T
                changed_logits = logits - delta
                changed = classification_metrics(changed_logits, targets)
                before = classification_metrics(logits, targets)
                changed_summary = _json_metrics(changed)
                changed_summary = _add_metric_deltas(changed_summary, _json_metrics(before))
                changed_summary["transitions"] = transition_counts(before["predictions"], changed["predictions"], targets)
                result["interventions"][group_name][f"{kind}_{observer}"] = changed_summary
    return result


def _write_s01_stage(protocol: dict[str, Any], records: list[dict[str, Any]], margins: np.ndarray,
                     test_rows: np.ndarray, preflight_state: dict[str, Any]) -> dict[str, Any]:
    out_dir = RUN / "s01-analysis"
    meta = preflight_state["meta"]
    states = {"M": load_probe(S01_MEAN_PROBE, "S01_CONTROLLED"),
              "F": load_probe(S01_FINAL_PROBE, "S01_CONTROLLED")}
    geo = geometry_stage("S01_CONTROLLED", test_rows, states,
                         {"M": S01_MEAN_FEATURES, "F": S01_FINAL_FEATURES},
                         {"M": FEATURE_ROWS, "F": FEATURE_ROWS})
    write_json(out_dir / "s01-native-subspaces-v01.json", _json_safe({"geometry": geo["geometry"], "comparison": geo["comparison"], "projections": geo["projections"]}))
    _save_npz(out_dir / "s01-native-decision-geometry-v01.npz", **{
        f"{observer}_{name}": np.asarray(value)
        for observer, values in geo["arrays"].items()
        for name, value in values.items()
        if name in {"class_normals", "class_intercepts", "pair_normals", "pair_intercepts", "basis", "singular_values"}
    })
    factorial = factorial_stage("S01_CONTROLLED", records, margins, meta, test_rows, out_dir)
    write_json(out_dir / "s01-walsh-summary-v01.json", factorial)
    census, groups, interventions = coordinate_stage(records, test_rows, meta, out_dir)
    write_json(out_dir / "s01-coordinate-census-v01.json", _json_safe(census))
    write_json(out_dir / "s01-coordinate-groups-v01.json", _json_safe(groups))
    write_json(out_dir / "s01-coordinate-interventions-v01.json", _json_safe(interventions))
    receipt = {
        "receipt_id": "FAS_S08_S01_ANALYSIS_RECEIPT_V01",
        "status": "COMPLETE",
        "protocol_root_sha256": protocol["root_sha256"],
        "s06_result_root_sha256": preflight_state["binding"]["s06_root_sha256"],
        "s01_3_result_root_sha256": preflight_state["binding"]["s01_3_result_root_sha256"],
        "train_rows": 85224,
        "heldout_rows": len(records),
        "factorial_cells": 16,
        "factorial_walsh_max_residual": factorial["max_reconstruction_residual"],
        "selectors": list(SELECTOR_NAMES),
        "group_sizes": list(K_SIZES),
        "fas00_values_opened": False,
        "model_contact": False,
        "feature_extraction": False,
        "probe_fitting": False,
        "significance_tests": False,
    }
    write_json(out_dir / "s01-execution-receipt-v01.json", receipt)
    seal = _seal_tree(out_dir, "s01-analysis-seal-v01.json", "FAS_S08_S01_ANALYSIS_SEAL_V01", "SEALED")
    return {"seal": seal, "groups": groups, "census": census, "interventions": interventions,
            "factorial": factorial, "geometry": geo}


def _factorial_fas00(records: list[dict[str, Any]], margins: np.ndarray,
                     fas00_rows: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    return factorial_stage("FAS00_ORIGINAL", records, margins, None, None, out_dir, fas00_rows)


def _fas00_metrics(logits: np.ndarray, labels: np.ndarray, rows: list[dict[str, Any]]) -> dict[str, Any]:
    output = {}
    masks = {"UNION": np.ones(len(rows), dtype=bool),
             "CONTEXT_TERM_3": np.asarray(["CONTEXT_TERM_3" in r.get("slices", []) for r in rows]),
             "ENTITY_TERM_7": np.asarray(["ENTITY_TERM_7" in r.get("slices", []) for r in rows])}
    for name, mask in masks.items():
        if not np.any(mask):
            raise FailClosed(f"Empty FAS-00 slice: {name}")
        output[name] = _json_metrics(classification_metrics(logits[mask], labels[mask]))
    return output


def _run_fas00_transfer(s01_seal: dict[str, Any], s01_result: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    _verify_stage_seal(RUN / "s01-analysis", "s01-analysis-seal-v01.json")
    out_dir = RUN / "fas00-transfer"
    # FAS-00 values are opened only after the S01 stage tree has been sealed and reverified.
    populations = json.loads(S05_POPULATIONS.read_text(encoding="utf-8"))["FAS00_ORIGINAL"]["rows"]
    if len(populations) != 512:
        raise FailClosed("FAS-00 S06-bound population count differs")
    records, margins, _ = load_row_population("FAS00_ORIGINAL")
    by_id = {record["event_id"]: record for record in records}
    rows = [row for row in populations if row["event_id"] in by_id]
    if len(rows) != len(populations):
        raise FailClosed("FAS-00 event population and S06 ledger IDs differ")
    rows.sort(key=lambda x: x["row_index"])
    labels = np.asarray([int(row["label"]) for row in rows], dtype=np.int64)
    for row in rows:
        if int(by_id[row["event_id"]]["target"]) != int(row["label"]):
            raise FailClosed(f"FAS-00 S06 target identity mismatch: {row['event_id']}")

    states = {"M": load_probe(FAS00_MEAN_PROBE, "FAS00_ORIGINAL"),
              "F": load_probe(S02_FINAL_PROBE, "FAS00_ORIGINAL")}
    geometries = {name: effective_geometry(state) for name, state in states.items()}
    fpaths = {"M": FAS00_MEAN_FEATURES, "F": S02_FINAL_FEATURES}
    row_indexes = {"M": np.asarray([int(r["mean_feature_row"]) for r in rows], dtype=np.int64),
                   "F": np.asarray([int(r["final_feature_row"]) for r in rows], dtype=np.int64)}
    if row_indexes["M"].max() >= FAS00_MEAN_ROWS or row_indexes["F"].max() >= FAS00_FINAL_ROWS:
        raise FailClosed("FAS-00 feature row index exceeds its sealed cache")
    geo = geometry_stage("FAS00_ORIGINAL", row_indexes, states, fpaths,
                         {"M": FAS00_MEAN_ROWS, "F": FAS00_FINAL_ROWS})
    write_json(out_dir / "fas00-native-subspaces-v01.json", _json_safe({"geometry": geo["geometry"], "comparison": geo["comparison"], "projections": geo["projections"]}))
    _save_npz(out_dir / "fas00-native-decision-geometry-v01.npz", **{
        f"{observer}_{name}": np.asarray(value)
        for observer, values in geo["arrays"].items()
        for name, value in values.items()
        if name in {"class_normals", "class_intercepts", "pair_normals", "pair_intercepts", "basis", "singular_values"}
    })
    population_by_id = {row["event_id"]: row for row in rows}
    factorial_rows = [population_by_id[record["event_id"]] for record in records]
    factorial = _factorial_fas00(records, margins, factorial_rows, out_dir)
    write_json(out_dir / "fas00-walsh-summary-v01.json", factorial)

    selected_groups = s01_result["groups"]["selectors"]
    transfer: dict[str, Any] = {"baseline_native": {}, "groups": {}}
    feat_arrays = {"M": load_features(FAS00_MEAN_FEATURES, FAS00_MEAN_ROWS),
                   "F": load_features(S02_FINAL_FEATURES, FAS00_FINAL_ROWS)}
    native_data: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for observer in ("M", "F"):
        state = states[observer]
        hidden = np.asarray(feat_arrays[observer][row_indexes[observer]], dtype=np.float64)
        z = (hidden - state["replay_mean"][None, :]) / state["replay_scale"][None, :]
        logits = z @ state["weights"].T + state["bias"][None, :]
        expected = np.asarray([int(by_id[row["event_id"]]["cells"][FAS00_NATIVE_CELLS[observer]]["prediction"]) for row in rows])
        pred = np.argmax(logits, axis=1)
        if not np.array_equal(pred, expected):
            raise FailClosed(f"FAS-00 {observer} diagonal predictions differ from S06")
        transfer["baseline_native"][observer] = _fas00_metrics(logits, labels, rows)
        native_data[observer] = (z, logits, state["weights"])

    group_metrics: dict[str, Any] = {}
    for group_name, group in selected_groups.items():
        group_metrics[group_name] = {}
        for kind in ("selected", "control"):
            idx = np.asarray(group[kind], dtype=np.int64)
            for observer in ("M", "F"):
                z, logits, weights = native_data[observer]
                after = logits - z[:, idx] @ weights[:, idx].T
                before_metric = classification_metrics(logits, labels)
                group_metric: dict[str, Any] = {}
                for slice_name, mask in {
                    "UNION": np.ones(len(rows), dtype=bool),
                    "CONTEXT_TERM_3": np.asarray(["CONTEXT_TERM_3" in r.get("slices", []) for r in rows]),
                    "ENTITY_TERM_7": np.asarray(["ENTITY_TERM_7" in r.get("slices", []) for r in rows]),
                }.items():
                    before = classification_metrics(logits[mask], labels[mask])
                    after_m = classification_metrics(after[mask], labels[mask])
                    item = _json_metrics(after_m)
                    item = _add_metric_deltas(item, _json_metrics(before))
                    item["transitions"] = transition_counts(before["predictions"], after_m["predictions"], labels[mask])
                    group_metric[slice_name] = item
                group_metrics[group_name][f"{kind}_{observer}"] = group_metric
    transfer["groups"] = group_metrics
    transfer["provenance"] = {"coordinate_groups_from_s01_seal": s01_seal["root_sha256"],
                               "fas00_used_for_selection": False, "model_contact": False,
                               "probe_fitting": False, "feature_extraction": False}
    write_json(out_dir / "fas00-coordinate-transfer-v01.json", _json_safe(transfer))
    write_json(out_dir / "fas00-execution-receipt-v01.json", {
        "receipt_id": "FAS_S08_FAS00_TRANSFER_RECEIPT_V01", "status": "COMPLETE",
        "protocol_root_sha256": protocol["root_sha256"],
        "parent_s01_seal_root_sha256": s01_seal["root_sha256"],
        "events": 512, "coordinate_groups_applied": len(selected_groups),
        "fas00_coordinate_selection": False, "model_contact": False,
        "feature_extraction": False, "probe_fitting": False,
    })
    seal = _seal_tree(out_dir, "fas00-transfer-seal-v01.json", "FAS_S08_FAS00_TRANSFER_SEAL_V01", "SEALED")
    return {"seal": seal, "factorial": factorial, "geometry": geo, "transfer": transfer}


def _write_report(s01: dict[str, Any], fas00: dict[str, Any], protocol: dict[str, Any]) -> None:
    g = s01["geometry"]["comparison"]
    lines = [
        "# FAS-S08 Results: Exact Decision-Surface Attribution", "",
        f"Protocol root: `{protocol['root_sha256']}`", "",
        "S08 used only sealed feature arrays, probes, metadata, and the S06 16-cell replay. No model contact, feature extraction, probe fitting, SAE analysis, or significance testing occurred.", "",
        "## Native decision subspaces", "",
        f"S01 rank M/F: {s01['geometry']['geometry']['M']['rank']} / {s01['geometry']['geometry']['F']['rank']}",
        f"S01 principal angles: {g['principal_angle_degrees']}",
        f"S01 projection overlap fraction: {g['projection_overlap_fraction']:.6f}",
        f"S01 corresponding pair-normal cosines: {g['corresponding_pair_normal_cosines']}", "",
        "## Four-factor margin decomposition", "",
        f"S01 rows: {s01['factorial']['event_count']:,}; maximum Walsh reconstruction residual: {s01['factorial']['max_reconstruction_residual']:.3e}.",
        f"FAS-00 external rows: {fas00['factorial']['event_count']:,}; maximum Walsh reconstruction residual: {fas00['factorial']['max_reconstruction_residual']:.3e}.",
        "The sealed JSON summaries report all main effects and interactions by pair margin, target class, native correctness transition, and declared factor groups.", "",
        "## Coordinate census and interventions", "",
        f"Coordinate selectors: {len(s01['groups']['selectors'])}; group sizes: {list(K_SIZES)}; all selectors used S01 training rows only.",
        "Held-out S01 interventions preserve the native scaler and probe and zero only selected standardized coordinates. FAS-00 interventions apply the S01-frozen coordinate lists after the S01 analysis seal.", "",
        "## Limits", "",
        "Coordinate ablations are fixed-readout interventions in the frozen feature vectors. They do not identify transformer circuits or semantic feature meanings. S07 remains closed at `SAE_NOT_FAITHFUL_FOR_COMPATIBILITY_ANALYSIS`; FAS-00 remains `SENSOR_FAIL_NO_SIGNAL`; neither disposition is changed by S08.", "",
    ]
    path = RUN / "S08-RESULTS.md"
    if path.exists():
        raise FailClosed("Refusing to overwrite S08 report")
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    protocol = verify_local_protocol()
    binding, _ = verify_parent_binding()
    event_ids, test_rows, state = preflight(protocol, binding)
    records = state["records"]
    _, margins, _ = load_row_population("S01_CONTROLLED")
    state["binding"] = binding
    s01_result = _write_s01_stage(protocol, records, margins, test_rows, state)
    _verify_stage_seal(RUN / "s01-analysis", "s01-analysis-seal-v01.json")
    fas00_result = _run_fas00_transfer(s01_result["seal"], s01_result, protocol)
    _verify_stage_seal(RUN / "fas00-transfer", "fas00-transfer-seal-v01.json")
    _write_report(s01_result, fas00_result, protocol)
    execution = {
        "receipt_id": "FAS_S08_EXECUTION_RECEIPT_V01", "status": "COMPLETE",
        "protocol_root_sha256": protocol["root_sha256"],
        "parent_binding_sha256": sha_file(PROJECT / "contracts" / "parent-binding-v01.json"),
        "s01_analysis_root_sha256": s01_result["seal"]["root_sha256"],
        "fas00_transfer_root_sha256": fas00_result["seal"]["root_sha256"],
        "S08_RESULT_READY": True,
        "FAS00_SENSOR_PASS": False, "FAS00_PHASE4_AUTHORIZED": False,
        "S08_MODEL_CONTACT": False, "S08_PROBE_FITTING": False, "S08_LAYERWISE_AUTHORIZED": False,
        "adaptive_mechanisms": False, "sae": False, "significance_tests": False,
        "feature_extraction": False,
    }
    write_json(RUN / "execution-receipt-v01.json", execution)
    _seal_tree(RUN, "result-tree-seal-v01.json", "FAS_S08_RESULT_TREE_SEAL_V01", "SEALED")
    print(f"FAS_S08_COMPLETE s01={len(records)} fas00=512 root={read_json(RUN / 'result-tree-seal-v01.json')['root_sha256']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAS_S08_FAIL_CLOSED: {type(exc).__name__}: {exc}")
        raise
