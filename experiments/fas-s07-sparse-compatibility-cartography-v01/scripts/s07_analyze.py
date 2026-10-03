from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import torch

from s07_common import (
    ANALYSIS_CONTRACT,
    FAS00_FEATURES,
    FAS00_HIDDEN,
    FAS00_PHASE1_EVENTS,
    FAS00_ROWS,
    FAS00_MEAN_PROBE,
    FAS00_ROOT,
    RUN,
    S01_CACHE,
    S01_CORPUS,
    S01_HIDDEN,
    S01_META,
    S01_PROBE_F,
    S01_PROBE_M,
    S01_ROWS,
    S02_FEATURES,
    S02_PROBE,
    S02_HIDDEN,
    SAE_CONTRACT,
    S05_POPULATIONS,
    FailClosed,
    load_probe,
    metrics,
    read_json,
    root_simple,
    semantic_logits,
    sha256_file,
    standardize,
    verify_protocol,
    write_json,
)
from s07_gate import _load_model, _read_fas00, _read_s01_test
from s07_sparse import (
    choose_feature_groups,
    candidate_slot_to_state,
    conditional_statistics,
    feature_statistics,
    metric_transitions,
    paired_margin_contributions,
    semantic_kappa,
    sparse_logits,
    top_coactivation_partners,
)


PAIR_IDS = ((0, 1), (0, 2), (1, 2))
PAIR_NAMES = ("class_0_vs_1", "class_0_vs_2", "class_1_vs_2")


def _verify_gate() -> tuple[dict[str, Any], dict[str, Any]]:
    protocol = verify_protocol()
    seal_path = RUN / "gate-tree-seal-v01.json"
    seal = read_json(seal_path)
    if seal.get("seal_id") != "FAS_S07_GATE_TREE_SEAL_V01" or seal.get("gate_status") != "PASS":
        raise FailClosed("S07 reconstruction gate is not PASS")
    if root_simple(seal.get("entries", [])) != seal.get("root_sha256"):
        raise FailClosed("S07 gate tree root mismatch")
    for item in seal["entries"]:
        path = RUN / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise FailClosed(f"S07 sealed gate artifact changed: {item['path']}")
    gate = read_json(RUN / "reconstruction-gate-v01.json")
    if gate.get("status") != "PASS" or gate.get("S07_FEATURE_ANALYSIS_AUTHORIZED_BY_GATE") is not True:
        raise FailClosed("S07 reconstruction-gate disposition is invalid")
    if gate.get("protocol_root_sha256") != protocol["root_sha256"]:
        raise FailClosed("S07 gate was produced under a different protocol")
    return protocol, seal


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8").rstrip("\x00")
    return str(value)


def _load_s01_metadata() -> dict[str, np.ndarray]:
    with np.load(S01_META, allow_pickle=False) as archive:
        required = {"row_index", "event_id", "quartet_id", "target", "state", "context_id", "entity_id", "split_bucket", "variant"}
        if not required.issubset(archive.files):
            raise FailClosed("S01 metadata is missing S07 conditioning fields")
        result = {key: np.asarray(archive[key]).copy() for key in required}
    if len(result["row_index"]) != S01_ROWS or not np.array_equal(result["row_index"], np.arange(S01_ROWS)):
        raise FailClosed("S01 metadata row identity is invalid")
    return result


def _load_s01_slot_maps(metadata: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    event_to_row = {_decode(event): i for i, event in enumerate(metadata["event_id"])}
    metadata_quartets = np.asarray([_decode(value) for value in metadata["quartet_id"]])
    if len(event_to_row) != S01_ROWS:
        raise FailClosed("S01 event IDs are not unique")
    slot_to_state = np.full((S01_ROWS, 3), 255, dtype=np.uint8)
    semantic_targets = np.full(S01_ROWS, 255, dtype=np.uint8)
    seen = np.zeros(S01_ROWS, dtype=np.bool_)
    variant_code = {"A": 0, "C": 1, "E": 2, "P": 3}
    with S01_CORPUS.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            quartet = json.loads(line)
            candidates = quartet.get("latent_world", {}).get("candidate_semantics", [])
            by_identity = {int(item["candidate_identity"]): int(item["state_id"]) for item in candidates}
            if set(by_identity) != {0, 1, 2} or set(by_identity.values()) != {0, 1, 2}:
                raise FailClosed(f"Invalid S01 candidate semantics at corpus line {line_number}")
            variants = quartet.get("variants", [])
            if len(variants) != 4:
                raise FailClosed(f"S01 quartet variant count invalid at corpus line {line_number}")
            for event in variants:
                event_id = event["event_id"]
                row = event_to_row.get(event_id, -1)
                if row < 0 or seen[row]:
                    raise FailClosed(f"S01 corpus event identity missing or repeated: {event_id}")
                event_quartet_id = event_id.rsplit(":", 1)[0]
                if event_quartet_id != quartet.get("quartet_id") or metadata_quartets[row] != quartet.get("quartet_id"):
                    raise FailClosed(f"S01 event/quartet identity mismatch: {event_id}")
                variant = event.get("variant_id")
                if int(metadata["variant"][row]) != variant_code.get(variant, -1):
                    raise FailClosed(f"S01 event variant does not match metadata: {event_id}")
                order = [int(value) for value in event["candidate_identity_order"]]
                if len(order) != 3 or set(order) != {0, 1, 2}:
                    raise FailClosed(f"S01 candidate ordering is not a permutation: {event_id}")
                mapping = np.asarray([by_identity[value] for value in order], dtype=np.uint8)
                target_slot = int(event["exact_target"])
                if target_slot not in (0, 1, 2) or int(metadata["target"][row]) != target_slot:
                    raise FailClosed(f"S01 target slot does not match row metadata: {event_id}")
                target_identity = int(event["target_candidate_identity"])
                if order[target_slot] != target_identity:
                    raise FailClosed(f"S01 target slot and candidate identity disagree: {event_id}")
                target_state = candidate_slot_to_state(mapping, target_slot)
                if target_state != by_identity[target_identity]:
                    raise FailClosed(f"S01 target state and candidate map disagree: {event_id}")
                slot_to_state[row] = mapping
                semantic_targets[row] = target_state
                seen[row] = True
    if not np.all(seen) or np.any(slot_to_state == 255):
        raise FailClosed(f"S01 corpus-to-feature row coverage incomplete: {int(np.count_nonzero(~seen))}")
    if np.any(semantic_targets == 255):
        raise FailClosed("S01 semantic target reconstruction is incomplete")
    return slot_to_state, semantic_targets


def _load_fas_metadata(rows: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    requested = {row["event_id"]: i for i, row in enumerate(rows)}
    observed_state = np.full(len(rows), 3, dtype=np.uint8)  # 3 denotes no prior observation.
    seen = np.zeros(len(rows), dtype=np.bool_)
    with FAS00_PHASE1_EVENTS.open("r", encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            row = requested.get(item.get("event_id"))
            if row is None:
                continue
            if seen[row]:
                raise FailClosed(f"FAS-00 Phase-1 event is duplicated: {item['event_id']}")
            if int(item["exact_target"]) != int(rows[row]["target"]):
                raise FailClosed(f"FAS-00 target metadata mismatch: {item['event_id']}")
            if int(item["context_term_id"]) != int(rows[row]["context_id"]) or int(item["entity_term_id"]) != int(rows[row]["entity_id"]):
                raise FailClosed(f"FAS-00 term metadata mismatch: {item['event_id']}")
            state = item.get("observation_answer_index")
            if state is not None:
                state = int(state)
                if state not in (0, 1, 2):
                    raise FailClosed(f"FAS-00 observed-state value invalid: {item['event_id']}")
                observed_state[row] = state
            seen[row] = True
    if not np.all(seen):
        raise FailClosed(f"FAS-00 Phase-1 metadata lacks {int(np.count_nonzero(~seen))} diagnostic events")
    return {"observed_state": observed_state}


def _save_npz(path: Path, **arrays: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        np.savez_compressed(stream, **arrays)


def _encode_rows(model: Any, raw: np.memmap, row_indices: np.ndarray, probe: dict[str, np.ndarray], precision: str, batch_size: int = 256) -> dict[str, np.ndarray]:
    rows = np.asarray(row_indices, dtype=np.int64)
    indices = np.empty((len(rows), model.k), dtype=np.uint16)
    values = np.empty((len(rows), model.k), dtype=np.float32)
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(rows), batch_size):
            stop = min(len(rows), start + batch_size)
            x_np = standardize(np.asarray(raw[rows[start:stop]]), probe, precision=precision)
            x = torch.from_numpy(np.asarray(x_np, dtype=np.float32)).cuda()
            ids, acts = model.encode_sparse(x)
            indices[start:stop] = ids.cpu().numpy().astype(np.uint16, copy=False)
            values[start:stop] = acts.cpu().numpy().astype(np.float32, copy=False)
    if not np.isfinite(values).all() or np.any(indices >= model.dictionary_width):
        raise FailClosed("S07 sparse encoder produced invalid codes")
    return {"indices": indices, "values": values}


def _read_gate_codes(seed: int, dataset: str, surface: str) -> dict[str, np.ndarray]:
    path = RUN / "gate-codes-v01" / f"seed-{seed}" / f"{dataset}-{surface}-sparse-codes-v01.npz"
    with np.load(path, allow_pickle=False) as archive:
        result = {key: np.asarray(archive[key]).copy() for key in ("indices", "values")}
    return result


def _compact_labels(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    labels = np.asarray(values, dtype=np.int64)
    categories, inverse = np.unique(labels, return_inverse=True)
    return categories, inverse.astype(np.int64)


def _write_activation_stats(output: Path, seed: int, population: str, codes: dict[str, dict[str, np.ndarray]], labels: dict[str, np.ndarray]) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, dict[str, np.ndarray]]]:
    stats: dict[str, dict[str, np.ndarray]] = {}
    frequencies: dict[str, np.ndarray] = {}
    nonzero_means: dict[str, np.ndarray] = {}
    arrays: dict[str, np.ndarray] = {}
    descriptors: dict[str, Any] = {"seed": seed, "population": population, "conditioning": {}}
    for surface in ("M", "F"):
        code = codes[surface]
        current = feature_statistics(code["indices"], code["values"])
        stats[surface] = current
        frequencies[surface] = current["activation_frequency"]
        nonzero_means[surface] = current["mean_nonzero"]
        for key, value in current.items():
            arrays[f"{surface}_{key}"] = np.asarray(value)
        for label_name, original in labels.items():
            categories, compact = _compact_labels(original)
            conditional = conditional_statistics(code["indices"], code["values"], compact, len(categories))
            descriptors["conditioning"].setdefault(label_name, categories.astype(int).tolist())
            for key, value in conditional.items():
                arrays[f"{surface}_{label_name}_{key}"] = np.asarray(value)
    _save_npz(output / f"seed-{seed}-{population}-activation-statistics-v01.npz", **arrays)
    write_json(output / f"seed-{seed}-{population}-activation-statistics-metadata-v01.json", descriptors)
    return stats, {"frequency": frequencies, "mean_nonzero": nonzero_means}


def _couplings(weights: np.ndarray, decoder: np.ndarray, slot_map: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    moments = [semantic_kappa(weights, decoder, slot_map, pair) for pair in PAIR_IDS]
    means = np.stack([item[0] for item in moments])
    variances = np.stack([item[1] for item in moments])
    return means, variances


def _event_contributions(code: dict[str, np.ndarray], weights: np.ndarray, decoder: np.ndarray, slot_map: np.ndarray) -> np.ndarray:
    ids = code["indices"].astype(np.int64, copy=False)
    values = code["values"].astype(np.float64, copy=False)
    if len(ids) != len(slot_map):
        raise FailClosed("Event contribution and slot-map row counts differ")
    inverse = np.empty_like(slot_map, dtype=np.int64)
    inverse[np.arange(len(slot_map))[:, None], slot_map] = np.arange(3)[None, :]
    slot_coupling = np.asarray(weights, dtype=np.float64) @ np.asarray(decoder, dtype=np.float64)
    output = np.empty((len(ids), 3, ids.shape[1]), dtype=np.float32)
    for pair_index, (left, right) in enumerate(PAIR_IDS):
        left_slot = inverse[:, left, None]
        right_slot = inverse[:, right, None]
        delta = slot_coupling[left_slot, ids] - slot_coupling[right_slot, ids]
        output[:, pair_index, :] = (values * delta).astype(np.float32)
    return output


def _metric_record(logits: np.ndarray, targets: np.ndarray) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    value = metrics(logits, targets)
    report = {key: item for key, item in value.items() if key not in {"predictions", "target_margins"}}
    return report, value["predictions"].astype(np.int16), value["target_margins"].astype(np.float32)


def _evaluate_logits(code: dict[str, np.ndarray], decoder: np.ndarray, decoder_bias: np.ndarray, probe: dict[str, np.ndarray], slot_map: np.ndarray | None, zero_features: list[int] | None) -> np.ndarray:
    return sparse_logits(code, decoder, decoder_bias, probe, slot_map=slot_map, zero_features=zero_features)


def _dense_native_logits(model: Any, code: dict[str, np.ndarray], probe: dict[str, np.ndarray], slot_map: np.ndarray | None, precision: str, batch_size: int = 256) -> np.ndarray:
    rows = len(code["indices"])
    parts = []
    with torch.inference_mode():
        for start in range(0, rows, batch_size):
            stop = min(rows, start + batch_size)
            ids = torch.from_numpy(code["indices"][start:stop].astype(np.int64, copy=False)).cuda()
            values = torch.from_numpy(code["values"][start:stop].astype(np.float32, copy=False)).cuda()
            reconstructed = model.decode_sparse(ids, values).cpu().numpy().astype(np.float32, copy=False)
            scoring = reconstructed.astype(np.float64) if precision == "float64" else reconstructed
            parts.append(scoring @ probe["weights"].T + probe["bias"])
    logits = np.concatenate(parts, axis=0)
    if slot_map is not None:
        semantic = np.empty_like(logits)
        semantic[np.arange(len(slot_map))[:, None], slot_map] = logits
        logits = semantic
    return logits


def _masks(dataset: str, rows: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    if dataset == "S01_CONTROLLED":
        return {"S01_FACTORIAL_TEST": np.ones(len(rows), dtype=np.bool_)}
    return {
        "FAS00_UNION": np.ones(len(rows), dtype=np.bool_),
        "FAS00_CONTEXT_TERM_3": np.asarray(["CONTEXT_TERM_3" in row["slices"] for row in rows], dtype=np.bool_),
        "FAS00_ENTITY_TERM_7": np.asarray(["ENTITY_TERM_7" in row["slices"] for row in rows], dtype=np.bool_),
    }


def _write_contribution_bundle(path: Path, rows: list[dict[str, Any]], codes_m: dict[str, np.ndarray], codes_f: dict[str, np.ndarray], weights_m: np.ndarray, weights_f: np.ndarray, decoder: np.ndarray, slot_map: np.ndarray) -> None:
    m = _event_contributions(codes_m, weights_m, decoder, slot_map)
    f = _event_contributions(codes_f, weights_f, decoder, slot_map)
    _save_npz(
        path,
        event_id=np.asarray([row["event_id"] for row in rows], dtype="U80"),
        mean_feature_ids=codes_m["indices"],
        final_feature_ids=codes_f["indices"],
        mean_native_contributions=m,
        final_native_contributions=f,
    )


def _analyze_seed(seed: int, output: Path, train_rows: np.ndarray, metadata: dict[str, np.ndarray], train_slot_map: np.ndarray, s01_test_rows: list[dict[str, Any]], slot_maps: dict[str, np.ndarray], raw_maps: dict[str, np.memmap], probes: dict[str, dict[str, dict[str, np.ndarray]]], targets: dict[str, np.ndarray], gate: dict[str, Any], *, include_fas: bool = False) -> dict[str, Any]:
    checkpoint = RUN / "sae-seeds-v01" / f"shared-topk-seed-{seed}.npz"
    model = _load_model(checkpoint, torch.device("cuda"))
    with np.load(checkpoint, allow_pickle=False) as archive:
        decoder = np.asarray(archive["decoder"], dtype=np.float32).copy()
        decoder_bias = np.asarray(archive["decoder_bias"], dtype=np.float32).copy()

    populations: dict[str, dict[str, Any]] = {
        "SAE_TRAIN": {
            "rows": None,
            "row_indices": train_rows,
            "slot_map": train_slot_map,
            "labels": {
                "target": metadata["semantic_target"][train_rows],
                "observed_state": metadata["state"][train_rows],
                "context_id": metadata["context_id"][train_rows],
                "entity_id": metadata["entity_id"][train_rows],
            },
        },
        "S01_FACTORIAL_TEST": {
            "rows": s01_test_rows,
            "row_indices": np.asarray([row["feature_row"] for row in s01_test_rows], dtype=np.int64),
            "slot_map": slot_maps["S01_FACTORIAL_TEST"],
            "labels": {
                "target": targets["S01_CONTROLLED"],
                "observed_state": np.asarray([row["state"] for row in s01_test_rows]),
                "context_id": np.asarray([row["context_id"] for row in s01_test_rows]),
                "entity_id": np.asarray([row["entity_id"] for row in s01_test_rows]),
            },
        },
    }
    if include_fas:
        fas_rows = slot_maps["FAS00_ROWS"]
        populations["FAS00_EXTERNAL"] = {
            "rows": fas_rows,
            "row_indices": {
                "M": np.asarray([row["mean_feature_row"] for row in fas_rows], dtype=np.int64),
                "F": np.asarray([row["final_feature_row"] for row in fas_rows], dtype=np.int64),
            },
            "slot_map": slot_maps["FAS00_ORIGINAL"],
            "labels": {
                "target": targets["FAS00_ORIGINAL"],
                "observed_state": slot_maps["FAS00_OBSERVED_STATE"],
                "context_id": np.asarray([row["context_id"] for row in fas_rows]),
                "entity_id": np.asarray([row["entity_id"] for row in fas_rows]),
            },
        }
    code_by_pop: dict[str, dict[str, dict[str, np.ndarray]]] = {}
    stat_by_pop: dict[str, dict[str, dict[str, np.ndarray]]] = {}
    for pop_name, info in populations.items():
        codes: dict[str, dict[str, np.ndarray]] = {}
        for surface in ("M", "F"):
            if pop_name == "SAE_TRAIN":
                probe = probes["S01_CONTROLLED"][surface]
                codes[surface] = _encode_rows(model, raw_maps[f"S01_{surface}"], info["row_indices"], probe, "float32")
            elif pop_name == "S01_FACTORIAL_TEST":
                codes[surface] = _read_gate_codes(seed, "S01_CONTROLLED", surface)
            elif pop_name == "FAS00_EXTERNAL":
                codes[surface] = _read_gate_codes(seed, "FAS00_ORIGINAL", surface)
        code_by_pop[pop_name] = codes
        labels = info["labels"]
        stats, _measurements = _write_activation_stats(output, seed, pop_name, codes, labels)
        stat_by_pop[pop_name] = stats
        if pop_name == "SAE_TRAIN":
            coactivation = top_coactivation_partners(
                {surface: codes[surface]["indices"] for surface in ("M", "F")},
                {surface: codes[surface]["values"] for surface in ("M", "F")},
                {surface: stats[surface]["activation_frequency"] for surface in ("M", "F")},
            )
            write_json(output / f"seed-{seed}-training-coactivation-partners-v01.json", coactivation)
            _save_npz(output / f"seed-{seed}-training-sparse-codes-v01.npz", **{
                "M_indices": codes["M"]["indices"], "M_values": codes["M"]["values"],
                "F_indices": codes["F"]["indices"], "F_values": codes["F"]["values"],
            })

    coupling_records: dict[str, dict[str, dict[str, np.ndarray]]] = {}
    coupling_arrays: dict[str, np.ndarray] = {}
    native_train_means: dict[str, np.ndarray] = {}
    for pop_name, info in populations.items():
        if pop_name == "SAE_TRAIN":
            smap = info["slot_map"]
            dataset = "S01_CONTROLLED"
        elif pop_name == "S01_FACTORIAL_TEST":
            smap = info["slot_map"]
            dataset = "S01_CONTROLLED"
        else:
            smap = info["slot_map"]
            dataset = "FAS00_ORIGINAL"
        coupling_records[pop_name] = {}
        for readout in ("M", "F"):
            means, variances = _couplings(probes[dataset][readout]["weights"], decoder, smap)
            coupling_records[pop_name][readout] = {"mean": means, "variance": variances}
            coupling_arrays[f"{pop_name}_{readout}_mean"] = means
            coupling_arrays[f"{pop_name}_{readout}_variance"] = variances
        if pop_name == "SAE_TRAIN":
            native_train_means["M"] = coupling_records[pop_name]["M"]["mean"]
            native_train_means["F"] = coupling_records[pop_name]["F"]["mean"]
    _save_npz(output / f"seed-{seed}-decoder-couplings-v01.npz", **coupling_arrays)

    train_stats = stat_by_pop["SAE_TRAIN"]
    contribution_by_pop: dict[str, dict[str, np.ndarray]] = {}
    for pop_name, info in populations.items():
        dataset = "FAS00_ORIGINAL" if pop_name == "FAS00_EXTERNAL" else "S01_CONTROLLED"
        contrib = paired_margin_contributions(
            code_by_pop[pop_name]["M"], code_by_pop[pop_name]["F"], decoder,
            probes[dataset]["M"]["weights"], probes[dataset]["F"]["weights"], info["slot_map"],
        )
        contribution_by_pop[pop_name] = contrib
        _save_npz(output / f"seed-{seed}-{pop_name}-paired-feature-margin-contributions-v01.npz", **contrib)
        if pop_name != "SAE_TRAIN":
            event_rows = info["rows"]
            if event_rows is not None:
                _write_contribution_bundle(
                    output / f"seed-{seed}-{pop_name}-event-contributions-v01.npz",
                    event_rows,
                    code_by_pop[pop_name]["M"], code_by_pop[pop_name]["F"],
                    probes[dataset]["M"]["weights"], probes[dataset]["F"]["weights"], decoder, info["slot_map"],
                )

    # Training-only selection: no held-out labels or feature rows enter this step.
    training_contrib = contribution_by_pop["SAE_TRAIN"]
    selection = choose_feature_groups(
        training_contrib,
        train_stats["M"]["activation_frequency"], train_stats["F"]["activation_frequency"],
        train_stats["M"]["mean_nonzero"], train_stats["F"]["mean_nonzero"], decoder,
        count=int(read_json(ANALYSIS_CONTRACT)["group_selection"]["count_per_boundary_per_seed"]),
    )
    write_json(output / f"seed-{seed}-selected-feature-groups-v01.json", selection)

    activation_m = train_stats["M"]
    activation_f = train_stats["F"]
    activation_score = (
        np.abs(activation_f["mean"] - activation_m["mean"])
        / np.sqrt(activation_f["variance"] + activation_m["variance"] + 1e-8)
        + np.abs(activation_f["activation_frequency"] - activation_m["activation_frequency"])
    )
    k_m = native_train_means["M"]
    k_f = native_train_means["F"]
    coupling_score = np.linalg.norm(k_f - k_m, axis=0) / (
        np.linalg.norm(k_f, axis=0) + np.linalg.norm(k_m, axis=0) + 1e-8
    )
    activation_cut = float(np.median(activation_score))
    coupling_cut = float(np.median(coupling_score))
    activation_high = activation_score > activation_cut
    coupling_high = coupling_score > coupling_cut
    category_counts = {
        "same_activation_same_coupling": int(np.count_nonzero(~activation_high & ~coupling_high)),
        "same_activation_different_coupling": int(np.count_nonzero(~activation_high & coupling_high)),
        "different_activation_same_coupling": int(np.count_nonzero(activation_high & ~coupling_high)),
        "different_activation_different_coupling": int(np.count_nonzero(activation_high & coupling_high)),
        "activation_score_median": activation_cut,
        "coupling_score_median": coupling_cut,
        "activation_score_median_absolute_deviation": float(np.median(np.abs(activation_score - activation_cut))),
        "coupling_score_median_absolute_deviation": float(np.median(np.abs(coupling_score - coupling_cut))),
    }
    write_json(output / f"seed-{seed}-mechanism-category-counts-v01.json", category_counts)

    eval_records: list[dict[str, Any]] = []
    prediction_arrays: dict[str, np.ndarray] = {}
    coupling_swap_records: list[dict[str, Any]] = []
    baseline_native: dict[tuple[str, str], np.ndarray] = {}
    native_logits: dict[tuple[str, str], np.ndarray] = {}
    for pop_name in tuple(populations):
        if pop_name == "SAE_TRAIN":
            continue
        info = populations[pop_name]
        dataset = "FAS00_ORIGINAL" if pop_name == "FAS00_EXTERNAL" else "S01_CONTROLLED"
        rows = info["rows"]
        masks = _masks(dataset, rows)
        for code_surface in ("M", "F"):
            for readout in ("M", "F"):
                if code_surface == readout:
                    logits = _dense_native_logits(
                        model, code_by_pop[pop_name][code_surface], probes[dataset][readout],
                        info["slot_map"] if dataset == "S01_CONTROLLED" else None,
                        "float32" if dataset == "S01_CONTROLLED" else "float64",
                    )
                    for slice_name, mask in _masks(dataset, info["rows"]).items():
                        expected = next((record for record in gate["checks"] if record["seed"] == seed and record["dataset"] == dataset and record["surface"] == code_surface and record["population"] == slice_name), None)
                        if expected is None:
                            raise FailClosed(f"Missing sealed reconstruction gate slice: {dataset}/{code_surface}/{slice_name}")
                        actual, _pred, _margin = _metric_record(logits[mask], targets[dataset][mask])
                        if actual["confusion_matrix_true_rows_predicted_columns"] != expected["reconstruction"]["confusion_matrix_true_rows_predicted_columns"]:
                            raise FailClosed(f"Sparse-code native replay differs from the sealed SAE gate: {dataset}/{code_surface}/{slice_name}")
                else:
                    logits = _evaluate_logits(
                        code_by_pop[pop_name][code_surface], decoder, decoder_bias,
                        probes[dataset][readout], info["slot_map"] if dataset == "S01_CONTROLLED" else None,
                        None,
                    )
                pred = np.argmax(logits, axis=1).astype(np.int16)
                key = f"{pop_name}_{code_surface}_codes_{readout}_readout"
                prediction_arrays[f"{key}_logits"] = logits.astype(np.float32)
                prediction_arrays[f"{key}_predictions"] = pred
                if readout == code_surface:
                    native_logits[(pop_name, code_surface)] = logits
                    baseline_native[(pop_name, code_surface)] = pred
                for slice_name, mask in masks.items():
                    report, _pred, margins = _metric_record(logits[mask], targets[dataset][mask])
                    eval_records.append({
                        "kind": "coupling_swap",
                        "population": slice_name,
                        "code_surface": code_surface,
                        "readout": readout,
                        "metrics": report,
                    })
                    prediction_arrays[f"{key}_{slice_name}_target_margins"] = margins
                coupling_swap_records.append({"population": pop_name, "codes": code_surface, "readout": readout})

        for code_surface in ("M", "F"):
            base_pred = baseline_native[(pop_name, code_surface)]
            for boundary_name, feature_ids in selection["selected_groups"].items():
                control_ids = selection["matched_control_groups"][boundary_name]
                for intervention_name, group in (("selected", feature_ids), ("matched_control", control_ids)):
                    analytical_base = _evaluate_logits(
                        code_by_pop[pop_name][code_surface], decoder, decoder_bias,
                        probes[dataset][code_surface], info["slot_map"] if dataset == "S01_CONTROLLED" else None,
                        None,
                    )
                    analytical_after = _evaluate_logits(
                        code_by_pop[pop_name][code_surface], decoder, decoder_bias,
                        probes[dataset][code_surface], info["slot_map"] if dataset == "S01_CONTROLLED" else None,
                        group,
                    )
                    logits = native_logits[(pop_name, code_surface)] + (analytical_after - analytical_base)
                    after_pred = np.argmax(logits, axis=1).astype(np.int16)
                    transition = metric_transitions(base_pred, after_pred, targets[dataset])
                    prefix = f"{pop_name}_{code_surface}_{boundary_name}_{intervention_name}"
                    prediction_arrays[f"{prefix}_logits"] = logits.astype(np.float32)
                    prediction_arrays[f"{prefix}_predictions"] = after_pred
                    eval_records.append({
                        "kind": "sparse_reconstruction_ablation",
                        "population": pop_name,
                        "code_surface": code_surface,
                        "native_readout": code_surface,
                        "boundary_group": boundary_name,
                        "intervention": intervention_name,
                        "feature_count": len(group),
                        "feature_ids": group,
                        "against": "faithful_unablated_reconstruction",
                        "transition": transition,
                        "metrics_by_slice": {
                            slice_name: _metric_record(logits[mask], targets[dataset][mask])[0]
                            for slice_name, mask in masks.items()
                        },
                    })
                    prediction_arrays[f"{prefix}_transition_counts"] = np.asarray(transition["prediction_transition_counts_rows_before_columns_after"], dtype=np.int64)
                    prediction_arrays[f"{prefix}_correctness_transitions"] = np.asarray(list(transition["correctness_transitions"].values()), dtype=np.int64)

    _save_npz(output / f"seed-{seed}-intervention-predictions-v01.npz", **prediction_arrays)
    write_json(output / f"seed-{seed}-intervention-metrics-v01.json", {"seed": seed, "records": eval_records})
    write_json(output / f"seed-{seed}-coupling-swap-v01.json", {"seed": seed, "records": coupling_swap_records})

    del model
    torch.cuda.empty_cache()
    return {
        "seed": seed,
        "training_rows_per_surface": int(len(train_rows)),
        "populations": {"S01_FACTORIAL_TEST": 19_732} | ({"FAS00_EXTERNAL": 512} if include_fas else {}),
        "selected_feature_union_size": selection["selected_feature_union_size"],
        "control_features_unique": selection["control_features_are_unique"],
        "control_features_overlap_selected": selection["control_features_overlap_selected"],
        "mechanism_category_counts": category_counts,
        "coupling_swap_record_count": len(coupling_swap_records),
        "intervention_record_count": sum(record["kind"] == "sparse_reconstruction_ablation" for record in eval_records),
        "feature_names_assigned": False,
        "maximally_activating_examples_inspected": False,
    }


def _seal_folder(folder: Path, name: str, seal_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    paths = [path for path in folder.rglob("*") if path.is_file() and path.name != name]
    entries = [{"path": path.relative_to(folder).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in paths]
    entries.sort(key=lambda item: item["path"].casefold())
    seal = {"seal_id": seal_id, "status": "SEALED", "entries": entries, "root_sha256": root_simple(entries), **extra}
    write_json(folder / name, seal)
    return seal


def main() -> None:
    protocol, gate_seal = _verify_gate()
    cfg = read_json(ANALYSIS_CONTRACT)
    if cfg.get("status") != "FROZEN_PRE_FIT":
        raise FailClosed("S07 analysis contract is not frozen")
    root = RUN / "sparse-analysis-v01"
    output = root / "s01-analysis-v01"
    if root.exists() and any(root.iterdir()):
        raise FailClosed("S07 sparse-analysis output already exists")
    output.mkdir(parents=True, exist_ok=True)
    populations = read_json(S05_POPULATIONS)
    s01_test_rows = _read_s01_test(populations)
    metadata = _load_s01_metadata()
    slot_maps_all, semantic_targets = _load_s01_slot_maps(metadata)
    metadata["semantic_target"] = semantic_targets
    train_rows = np.asarray(np.load(RUN / "train-row-indices-v01.npy", allow_pickle=False), dtype=np.int64)
    if len(train_rows) != 85_224 or np.any(metadata["split_bucket"][train_rows] == 0):
        raise FailClosed("S07 training row selection is invalid")
    train_slot_map = slot_maps_all[train_rows]
    test_slot = slot_maps_all[np.asarray([row["feature_row"] for row in s01_test_rows], dtype=np.int64)]
    targets = {"S01_CONTROLLED": np.asarray([row["target"] for row in s01_test_rows], dtype=np.int64)}
    probes = {"S01_CONTROLLED": {
        "M": load_probe(S01_PROBE_M, precision="float32"),
        "F": load_probe(S01_PROBE_F, precision="float32"),
    }}
    raw_maps = {
        "S01_M": np.memmap(S01_CACHE / "V0_MEAN_FULL.f32le", mode="r", dtype="<f4", shape=(S01_ROWS, S01_HIDDEN)),
        "S01_F": np.memmap(S01_CACHE / "V1_FINAL_POSITION.f32le", mode="r", dtype="<f4", shape=(S01_ROWS, S01_HIDDEN)),
    }
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    if not torch.cuda.is_available() or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise FailClosed("S07 frozen analysis device changed")
    seeds = [int(item["seed"]) for item in read_json(RUN / "training-receipt-v01.json")["seed_results"]]
    summaries = []
    for seed in seeds:
        summaries.append(_analyze_seed(
            seed, output, train_rows, metadata, train_slot_map, s01_test_rows,
            {"S01_FACTORIAL_TEST": test_slot}, raw_maps, probes, targets,
            read_json(RUN / "reconstruction-gate-v01.json"), include_fas=False,
        ))
        print(f"S07_S01_ANALYSIS_SEED_COMPLETE seed={seed}", flush=True)
    report = {
        "analysis_stage": "S01_CONTROLLED_ONLY",
        "status": "COMPLETE",
        "protocol_root_sha256": protocol["root_sha256"],
        "gate_root_sha256": gate_seal["root_sha256"],
        "analysis_contract_sha256": sha256_file(ANALYSIS_CONTRACT),
        "sae_training_contract_sha256": sha256_file(SAE_CONTRACT),
        "FAS00_FEATURE_VALUES_OPENED": False,
        "FAS00_SPARSE_CODES_OPENED": False,
        "feature_extraction": False,
        "transformer_contact": False,
        "probe_fitting": False,
        "feature_names_assigned": False,
        "maximally_activating_examples_inspected": False,
        "seed_summaries": summaries,
    }
    write_json(output / "s01-analysis-report-v01.json", report)
    seal = _seal_folder(output, "s01-analysis-seal-v01.json", "FAS_S07_S01_ANALYSIS_SEAL_V01", {
        "protocol_root_sha256": protocol["root_sha256"],
        "gate_root_sha256": gate_seal["root_sha256"],
        "FAS00_FEATURE_VALUES_OPENED": False,
        "FAS00_SPARSE_CODES_OPENED": False,
    })
    print(f"S07_S01_ANALYSIS_SEALED root={seal['root_sha256']} files={len(seal['entries'])}")


if __name__ == "__main__":
    try:
        main()
    except FailClosed as exc:
        print(f"S07_ANALYSIS_FAIL_CLOSED {exc}")
        raise SystemExit(2)
