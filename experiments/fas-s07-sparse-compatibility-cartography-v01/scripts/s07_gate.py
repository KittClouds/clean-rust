from __future__ import annotations

import os

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import json
from pathlib import Path
from typing import Any

import numpy as np
import torch

from s07_common import (
    ANALYSIS_CONTRACT, SAE_CONTRACT, FAS00_FEATURES, FAS00_HIDDEN, FAS00_MEAN_PROBE,
    PARENT_BINDING, PROTOCOL_SEAL, RUN, S01_CACHE, S01_HIDDEN, S01_META,
    S01_PROBE_F, S01_PROBE_M, S01_ROWS, S02_FEATURES, S02_HIDDEN,
    S05_POPULATIONS, S06_LEDGER, FailClosed, apply_probe, load_probe, metrics,
    read_json, root_simple, semantic_logits, sha256_file, standardize,
    verify_protocol, write_json,
)
from s07_model import SharedTopKSAE
from s07_sparse import candidate_slot_to_state


M_CELL = "R_M_C_M_D_M_W_M"
F_CELL = "R_F_C_F_D_F_W_F"


def _verify_training() -> tuple[dict, dict]:
    protocol = verify_protocol()
    seal = read_json(RUN / "training-tree-seal-v01.json")
    if seal.get("seal_id") != "FAS_S07_TRAINING_TREE_SEAL_V01" or root_simple(seal.get("entries", [])) != seal.get("root_sha256"):
        raise FailClosed("S07 training seal invalid")
    for entry in seal["entries"]:
        path = RUN / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise FailClosed(f"S07 training artifact changed: {entry['path']}")
    receipt = read_json(RUN / "training-receipt-v01.json")
    compatible_training_roots = set(protocol.get("training_compatible_prior_protocol_roots", []))
    compatible_training_roots.add(protocol["root_sha256"])
    if receipt.get("status") != "COMPLETE" or receipt.get("protocol_root_sha256") not in compatible_training_roots or receipt.get("training_contract_sha256") != sha256_file(SAE_CONTRACT) or receipt.get("evaluation_features_loaded") is not False:
        raise FailClosed("S07 training receipt invalid")
    return protocol, seal


def _read_s01_test(populations: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    quartets = populations["S01_CONTROLLED"]["quartets"]
    if len(quartets) != 4_933:
        raise FailClosed(f"S01 heldout quartet count mismatch: {len(quartets)}")
    with np.load(S01_META, allow_pickle=False) as meta:
        event_ids = [bytes(value).decode("utf-8").rstrip("\x00") for value in meta["event_id"]]
        buckets = meta["split_bucket"]
        targets = meta["target"]
        states = meta["state"]
        contexts = meta["context_id"]
        entities = meta["entity_id"]
        row_by_event = {event_id: i for i, event_id in enumerate(event_ids)}
        for quartet in quartets:
            if len(quartet["events"]) != 4:
                raise FailClosed("Malformed S01 test quartet")
            for item in quartet["events"]:
                row = int(item["feature_row_index"])
                event_id = item["event_id"]
                if row != row_by_event.get(event_id, -1) or int(buckets[row]) != 0:
                    raise FailClosed(f"S01 heldout event identity or split mismatch: {event_id}")
                meta_row = item["sealed_test_metadata"]
                target = int(item["target_state_id"])
                order = [int(value) for value in item["candidate_identity_order"]]
                state_by_identity = {int(key): int(value) for key, value in item["state_by_candidate_identity"].items()}
                target_slot = int(meta_row["exact_target"])
                if len(order) != 3 or set(order) != {0, 1, 2} or set(state_by_identity) != {0, 1, 2} or set(state_by_identity.values()) != {0, 1, 2}:
                    raise FailClosed(f"S01 candidate-to-state metadata is not a permutation: {event_id}")
                target_state = candidate_slot_to_state(np.asarray([state_by_identity[identity] for identity in order]), target_slot)
                if int(targets[row]) != target_slot or target_state != target or int(states[row]) != int(meta_row["state_id"]):
                    raise FailClosed(f"S01 heldout labels disagree with sealed metadata: {event_id}")
                events.append({
                    "event_id": event_id,
                    "feature_row": row,
                    "target": target,
                    "state": int(states[row]),
                    "context_id": int(contexts[row]),
                    "entity_id": int(entities[row]),
                    "relation_id": int(meta_row["relation_id"]),
                    "observation_template_id": int(meta_row["observation_template_id"]),
                    "query_template_id": int(meta_row["query_template_id"]),
                    "quartet_id": item["quartet_id"],
                    "variant_id": item["variant_id"],
                    "candidate_identity_order": item["candidate_identity_order"],
                    "state_by_candidate_identity": item["state_by_candidate_identity"],
                })
    if len(events) != 19_732 or len({row["event_id"] for row in events}) != 19_732:
        raise FailClosed("S01 heldout event support or uniqueness mismatch")
    return events


def _read_fas00(populations: dict[str, Any]) -> list[dict[str, Any]]:
    rows = populations["FAS00_ORIGINAL"]["rows"]
    if len(rows) != 512:
        raise FailClosed(f"FAS-00 external row count mismatch: {len(rows)}")
    result = []
    for item in rows:
        row = int(item["row_index"])
        if int(item["mean_feature_row"]) != 2 * row or int(item["final_feature_row"]) != row:
            raise FailClosed(f"FAS-00 feature row mapping mismatch: {item['event_id']}")
        result.append({
            "event_id": item["event_id"],
            "mean_feature_row": int(item["mean_feature_row"]),
            "final_feature_row": int(item["final_feature_row"]),
            "target": int(item["exact_target"]),
            "context_id": int(item["context_term_id"]),
            "entity_id": int(item["entity_term_id"]),
            "slices": item["slices"],
        })
    if len({row["event_id"] for row in result}) != 512:
        raise FailClosed("FAS-00 external event IDs are not unique")
    return result


def _read_s06_predictions(event_rows: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, dict[str, int]]]:
    requested = {dataset: {row["event_id"] for row in rows} for dataset, rows in event_rows.items()}
    found = {dataset: {} for dataset in event_rows}
    with S06_LEDGER.open("r", encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            dataset = item["dataset"]
            event_id = item["event_id"]
            if dataset in requested and event_id in requested[dataset]:
                found[dataset][event_id] = {
                    "M": int(item["cells"][M_CELL]["prediction"]),
                    "F": int(item["cells"][F_CELL]["prediction"]),
                    "target": int(item["target"]),
                }
    for dataset in requested:
        if set(found[dataset]) != requested[dataset]:
            raise FailClosed(f"S06 sealed diagonal event coverage mismatch: {dataset}")
    return found


def _load_model(path: Path, device: torch.device) -> SharedTopKSAE:
    with np.load(path, allow_pickle=False) as archive:
        model = SharedTopKSAE().to(device)
        with torch.no_grad():
            model.encoder.weight.copy_(torch.from_numpy(archive["encoder_weight"].copy()).to(device))
            model.encoder.bias.copy_(torch.from_numpy(archive["encoder_bias"].copy()).to(device))
            model.decoder.copy_(torch.from_numpy(archive["decoder"].copy()).to(device))
            model.decoder_bias.copy_(torch.from_numpy(archive["decoder_bias"].copy()).to(device))
    model.eval()
    return model


def _encode_eval(model: SharedTopKSAE, raw: np.ndarray, probe: dict[str, np.ndarray], precision: str, batch_size: int = 256) -> tuple[dict[str, np.ndarray], np.ndarray, dict[str, float]]:
    n = len(raw)
    indices = np.empty((n, model.k), dtype=np.uint16)
    values = np.empty((n, model.k), dtype=np.float32)
    logits_parts = []
    squared_error = 0.0
    total_input_sq = 0.0
    total_elements = 0
    with torch.inference_mode():
        for start in range(0, n, batch_size):
            stop = min(n, start + batch_size)
            x_np = standardize(np.asarray(raw[start:stop]), probe, precision=precision)
            x = torch.from_numpy(np.asarray(x_np, dtype=np.float32)).cuda()
            index_t, value_t = model.encode_sparse(x)
            xhat_t = model.decode_sparse(index_t, value_t)
            idx = index_t.cpu().numpy().astype(np.uint16, copy=False)
            val = value_t.cpu().numpy().astype(np.float32, copy=False)
            indices[start:stop] = idx
            values[start:stop] = val
            xhat = xhat_t.cpu().numpy().astype(np.float32, copy=False)
            diff = xhat - x_np.astype(np.float32, copy=False)
            squared_error += float(np.sum(diff.astype(np.float64) ** 2))
            total_input_sq += float(np.sum(x_np.astype(np.float64) ** 2))
            total_elements += diff.size
            scoring_x = xhat.astype(np.float64) if precision == "float64" else xhat
            logits_parts.append(apply_probe(scoring_x, probe))
    logits = np.concatenate(logits_parts, axis=0)
    mse = squared_error / total_elements
    r2 = 1.0 - squared_error / max(total_input_sq, 1e-12)
    return {"indices": indices, "values": values}, logits, {"reconstruction_mse": mse, "reconstruction_r2_zero_baseline": r2}


def _semantic_rows(logits: np.ndarray, rows: list[dict[str, Any]], dataset: str) -> np.ndarray:
    if dataset != "S01_CONTROLLED":
        return np.asarray(logits, dtype=np.float64)
    return np.stack([semantic_logits(row_logits, row) for row_logits, row in zip(logits, rows)])


def _summarize_population(base_logits: np.ndarray, recon_logits: np.ndarray, targets: np.ndarray, label: str, thresholds: dict[str, float]) -> dict[str, Any]:
    base = metrics(base_logits, targets)
    recon = metrics(recon_logits, targets)
    ba_drop = max(0.0, base["balanced_accuracy"] - recon["balanced_accuracy"])
    recall_drop = [max(0.0, a - b) for a, b in zip(base["recall_by_class"], recon["recall_by_class"])]
    passed = ba_drop <= thresholds["balanced_accuracy_max_degradation"] and max(recall_drop) <= thresholds["per_class_recall_max_degradation"]
    def clean(value: dict[str, Any]) -> dict[str, Any]:
        return {key: item for key, item in value.items() if key not in {"predictions", "target_margins"}}
    return {
        "population": label,
        "n": int(len(targets)),
        "baseline": clean(base),
        "reconstruction": clean(recon),
        "balanced_accuracy_degradation": float(base["balanced_accuracy"] - recon["balanced_accuracy"]),
        "per_class_recall_degradation": [float(a - b) for a, b in zip(base["recall_by_class"], recon["recall_by_class"])],
        "gate_pass": bool(passed),
    }


def main() -> None:
    protocol, training_seal = _verify_training()
    cfg = read_json(ANALYSIS_CONTRACT)
    populations = read_json(S05_POPULATIONS)
    s01_events = _read_s01_test(populations)
    fas_rows = _read_fas00(populations)
    expected_preds = _read_s06_predictions({"S01_CONTROLLED": s01_events, "FAS00_ORIGINAL": fas_rows})
    s01_m_probe = load_probe(S01_PROBE_M, precision="float32")
    s01_f_probe = load_probe(S01_PROBE_F, precision="float32")
    fas_m_probe = load_probe(FAS00_MEAN_PROBE, precision="float64")
    from s07_common import S02_PROBE
    fas_f_probe = load_probe(S02_PROBE, precision="float64")
    probes = {
        "S01_CONTROLLED": {"M": s01_m_probe, "F": s01_f_probe},
        "FAS00_ORIGINAL": {"M": fas_m_probe, "F": fas_f_probe},
    }
    rows_by_dataset = {"S01_CONTROLLED": s01_events, "FAS00_ORIGINAL": fas_rows}
    targets = {dataset: np.asarray([row["target"] for row in rows], dtype=np.int64) for dataset, rows in rows_by_dataset.items()}
    raw_by_dataset: dict[str, dict[str, np.ndarray]] = {}
    s01_m = np.memmap(S01_CACHE / "V0_MEAN_FULL.f32le", mode="r", dtype="<f4", shape=(S01_ROWS, S01_HIDDEN))
    s01_f = np.memmap(S01_CACHE / "V1_FINAL_POSITION.f32le", mode="r", dtype="<f4", shape=(S01_ROWS, S01_HIDDEN))
    fas_m = np.memmap(FAS00_FEATURES, mode="r", dtype="<f4", shape=(65_536, FAS00_HIDDEN))
    fas_f = np.memmap(S02_FEATURES, mode="r", dtype="<f4", shape=(32_768, S02_HIDDEN))
    raw_by_dataset["S01_CONTROLLED"] = {
        "M": np.asarray(s01_m[np.asarray([row["feature_row"] for row in s01_events], dtype=np.int64)]),
        "F": np.asarray(s01_f[np.asarray([row["feature_row"] for row in s01_events], dtype=np.int64)]),
    }
    raw_by_dataset["FAS00_ORIGINAL"] = {
        "M": np.asarray(fas_m[np.asarray([row["mean_feature_row"] for row in fas_rows], dtype=np.int64)]),
        "F": np.asarray(fas_f[np.asarray([row["final_feature_row"] for row in fas_rows], dtype=np.int64)]),
    }

    base_logits: dict[str, dict[str, np.ndarray]] = {dataset: {} for dataset in rows_by_dataset}
    for dataset, rows in rows_by_dataset.items():
        for surface in ("M", "F"):
            precision = "float32" if dataset == "S01_CONTROLLED" else "float64"
            x = standardize(raw_by_dataset[dataset][surface], probes[dataset][surface], precision=precision)
            logits = apply_probe(x, probes[dataset][surface])
            logits = _semantic_rows(logits, rows, dataset)
            for row, pred, target in zip(rows, np.argmax(logits, axis=1), targets[dataset]):
                expected = expected_preds[dataset][row["event_id"]]
                if int(target) != expected["target"] or int(pred) != expected[surface]:
                    raise FailClosed(f"S07 raw native replay fails sealed S06 diagonal: {dataset}/{row['event_id']}/{surface}")
            base_logits[dataset][surface] = logits

    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    if not torch.cuda.is_available() or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise FailClosed("S07 frozen evaluation device changed")
    codes_root = RUN / "gate-codes-v01"
    if codes_root.exists() and any(codes_root.rglob("*.npz")):
        raise FailClosed("S07 gate-code directory already has outputs")
    records = []
    all_codes: dict[int, dict[str, dict[str, dict[str, np.ndarray]]]] = {}
    gate_pass = True
    for seed in read_json(RUN / "training-receipt-v01.json")["seed_results"]:
        seed_id = int(seed["seed"])
        model = _load_model(RUN / "sae-seeds-v01" / seed["checkpoint_path"], torch.device("cuda"))
        all_codes[seed_id] = {dataset: {} for dataset in rows_by_dataset}
        for dataset, rows in rows_by_dataset.items():
            for surface in ("M", "F"):
                code, slot_recon, recon_quality = _encode_eval(
                    model,
                    raw_by_dataset[dataset][surface],
                    probes[dataset][surface],
                    "float32" if dataset == "S01_CONTROLLED" else "float64",
                )
                recon_logits = _semantic_rows(slot_recon, rows, dataset)
                all_codes[seed_id][dataset][surface] = code
                if dataset == "S01_CONTROLLED":
                    masks = {"S01_FACTORIAL_TEST": np.ones(len(rows), dtype=bool)}
                else:
                    masks = {
                        "FAS00_UNION": np.ones(len(rows), dtype=bool),
                        "FAS00_CONTEXT_TERM_3": np.asarray(["CONTEXT_TERM_3" in row["slices"] for row in rows]),
                        "FAS00_ENTITY_TERM_7": np.asarray(["ENTITY_TERM_7" in row["slices"] for row in rows]),
                    }
                for slice_name, mask in masks.items():
                    detail = _summarize_population(
                        base_logits[dataset][surface][mask],
                        recon_logits[mask],
                        targets[dataset][mask],
                        slice_name,
                        cfg["faithfulness_gate"],
                    )
                    detail.update({"seed": seed_id, "dataset": dataset, "surface": surface})
                    if slice_name == "S01_FACTORIAL_TEST" or slice_name.startswith("FAS00_"):
                        detail["reconstruction_quality"] = recon_quality
                    records.append(detail)
                    gate_pass = gate_pass and detail["gate_pass"]
        del model
        torch.cuda.empty_cache()

    code_files = []
    for seed, datasets in all_codes.items():
        for dataset, surfaces in datasets.items():
            for surface, code in surfaces.items():
                path = codes_root / f"seed-{seed}" / f"{dataset}-{surface}-sparse-codes-v01.npz"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("wb") as stream:
                    np.savez_compressed(stream, indices=code["indices"], values=code["values"])
                code_files.append(path)
    gate = {
        "gate_id": "FAS_S07_RECONSTRUCTION_GATE_V01",
        "status": "PASS" if gate_pass else "SAE_NOT_FAITHFUL_FOR_COMPATIBILITY_ANALYSIS",
        "protocol_root_sha256": protocol["root_sha256"],
        "training_root_sha256": training_seal["root_sha256"],
        "raw_diagonal_replay_parity": "PASS",
        "gate_thresholds": cfg["faithfulness_gate"],
        "checks": records,
        "S07_FEATURE_ANALYSIS_AUTHORIZED_BY_GATE": bool(gate_pass),
        "S07_LAYERWISE_AUTHORIZED": False,
        "S07_MODEL_CONTACT": False,
        "FAS00_PHASE4_AUTHORIZED": False,
    }
    gate_path = RUN / "reconstruction-gate-v01.json"
    write_json(gate_path, gate)
    entries = [{"path": gate_path.relative_to(RUN).as_posix(), "bytes": gate_path.stat().st_size, "sha256": sha256_file(gate_path)}]
    for path in code_files:
        entries.append({"path": path.relative_to(RUN).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    entries.sort(key=lambda item: item["path"].casefold())
    seal = {
        "seal_id": "FAS_S07_GATE_TREE_SEAL_V01",
        "status": "SEALED",
        "entries": entries,
        "root_sha256": root_simple(entries),
        "gate_status": gate["status"],
        "protocol_root_sha256": protocol["root_sha256"],
        "training_root_sha256": training_seal["root_sha256"],
        "feature_interpretation_complete": False,
        "layerwise_authorized": False,
    }
    write_json(RUN / "gate-tree-seal-v01.json", seal)
    print(f"S07_RECONSTRUCTION_GATE_{gate['status']} checks={len(records)} root={seal['root_sha256']}")
    if not gate_pass:
        raise SystemExit(3)


if __name__ == "__main__":
    try:
        main()
    except FailClosed as exc:
        print(f"S07_GATE_FAIL_CLOSED {exc}")
        raise SystemExit(2)
