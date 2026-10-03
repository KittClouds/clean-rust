from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from s07_analyze import (
    _dense_native_logits,
    _encode_rows,
    _event_contributions,
    _evaluate_logits,
    _load_fas_metadata,
    _metric_record,
    _masks,
    _read_gate_codes,
    _save_npz,
    _seal_folder,
    _verify_gate,
    _write_activation_stats,
    _write_contribution_bundle,
    _couplings,
)
from s07_common import (
    ANALYSIS_CONTRACT,
    FAS00_FEATURES,
    FAS00_HIDDEN,
    FAS00_MEAN_PROBE,
    FAS00_PHASE1_EVENTS,
    FAS00_ROWS,
    RUN,
    S02_FEATURES,
    S02_PROBE,
    S02_HIDDEN,
    S05_POPULATIONS,
    SAE_CONTRACT,
    FailClosed,
    load_probe,
    metrics,
    read_json,
    root_simple,
    semantic_logits,
    sha256_file,
    write_json,
)
from s07_gate import _load_model, _read_fas00
from s07_sparse import metric_transitions, paired_margin_contributions, sparse_logits


def _verify_s01_analysis(path: Path, protocol_root: str, gate_root: str) -> dict[str, Any]:
    seal_path = path / "s01-analysis-seal-v01.json"
    seal = read_json(seal_path)
    if seal.get("seal_id") != "FAS_S07_S01_ANALYSIS_SEAL_V01" or root_simple(seal.get("entries", [])) != seal.get("root_sha256"):
        raise FailClosed("S07 S01 analysis seal is invalid")
    if seal.get("protocol_root_sha256") != protocol_root or seal.get("gate_root_sha256") != gate_root:
        raise FailClosed("S07 S01 analysis parent roots mismatch")
    if seal.get("FAS00_FEATURE_VALUES_OPENED") is not False or seal.get("FAS00_SPARSE_CODES_OPENED") is not False:
        raise FailClosed("S07 S01 stage crossed the FAS-00 data firewall")
    for item in seal["entries"]:
        file = path / item["path"]
        if not file.is_file() or file.stat().st_size != item["bytes"] or sha256_file(file) != item["sha256"]:
            raise FailClosed(f"S07 S01 analysis artifact changed: {item['path']}")
    report = read_json(path / "s01-analysis-report-v01.json")
    if report.get("analysis_stage") != "S01_CONTROLLED_ONLY" or report.get("status") != "COMPLETE":
        raise FailClosed("S07 S01 stage report is invalid")
    return seal


def _metric_report(logits: np.ndarray, targets: np.ndarray) -> dict[str, Any]:
    result = metrics(logits, targets)
    return {key: value for key, value in result.items() if key not in {"predictions", "target_margins"}}


def main() -> None:
    protocol, gate_seal = _verify_gate()
    root = RUN / "sparse-analysis-v01"
    s01_path = root / "s01-analysis-v01"
    s01_seal = _verify_s01_analysis(s01_path, protocol["root_sha256"], gate_seal["root_sha256"])
    output = root / "fas00-external-v01"
    if output.exists() and any(output.iterdir()):
        raise FailClosed("S07 FAS-00 external analysis output already exists")
    output.mkdir(parents=True, exist_ok=True)

    population = read_json(S05_POPULATIONS)
    rows = _read_fas00(population)
    observed_state = _load_fas_metadata(rows)["observed_state"]
    targets = np.asarray([row["target"] for row in rows], dtype=np.int64)
    labels = {
        "target": targets,
        "observed_state": observed_state,
        "context_id": np.asarray([row["context_id"] for row in rows]),
        "entity_id": np.asarray([row["entity_id"] for row in rows]),
    }
    probes = {
        "M": load_probe(FAS00_MEAN_PROBE, precision="float64"),
        "F": load_probe(S02_PROBE, precision="float64"),
    }
    raw_maps = {
        "M": np.memmap(FAS00_FEATURES, mode="r", dtype="<f4", shape=(FAS00_ROWS, FAS00_HIDDEN)),
        "F": np.memmap(S02_FEATURES, mode="r", dtype="<f4", shape=(32_768, S02_HIDDEN)),
    }
    feature_rows = {
        "M": np.asarray([row["mean_feature_row"] for row in rows], dtype=np.int64),
        "F": np.asarray([row["final_feature_row"] for row in rows], dtype=np.int64),
    }
    slot_map = np.tile(np.arange(3, dtype=np.uint8), (len(rows), 1))
    masks = _masks("FAS00_ORIGINAL", rows)
    gate = read_json(RUN / "reconstruction-gate-v01.json")
    training_receipt = read_json(RUN / "training-receipt-v01.json")
    seeds = [int(item["seed"]) for item in training_receipt["seed_results"]]
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    if not torch.cuda.is_available() or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise FailClosed("S07 FAS-00 transfer device changed")

    summaries = []
    cfg = read_json(ANALYSIS_CONTRACT)
    for seed in seeds:
        checkpoint = RUN / "sae-seeds-v01" / f"shared-topk-seed-{seed}.npz"
        model = _load_model(checkpoint, torch.device("cuda"))
        with np.load(checkpoint, allow_pickle=False) as archive:
            decoder = np.asarray(archive["decoder"], dtype=np.float32).copy()
            decoder_bias = np.asarray(archive["decoder_bias"], dtype=np.float32).copy()

        codes = {surface: _encode_rows(model, raw_maps[surface], feature_rows[surface], probes[surface], "float64") for surface in ("M", "F")}
        for surface in ("M", "F"):
            gate_codes = _read_gate_codes(seed, "FAS00_ORIGINAL", surface)
            if not np.array_equal(codes[surface]["indices"], gate_codes["indices"]) or not np.array_equal(codes[surface]["values"], gate_codes["values"]):
                raise FailClosed(f"FAS-00 post-S01 re-encoding differs from sealed gate codes: seed={seed}/{surface}")
        _save_npz(output / f"seed-{seed}-fresh-external-sparse-codes-v01.npz", **{
            "M_indices": codes["M"]["indices"], "M_values": codes["M"]["values"],
            "F_indices": codes["F"]["indices"], "F_values": codes["F"]["values"],
        })
        stats, _ = _write_activation_stats(output, seed, "FAS00_EXTERNAL", codes, labels)
        couplings: dict[str, np.ndarray] = {}
        for readout in ("M", "F"):
            mean, variance = _couplings(probes[readout]["weights"], decoder, slot_map)
            couplings[f"{readout}_mean"] = mean
            couplings[f"{readout}_variance"] = variance
        _save_npz(output / f"seed-{seed}-external-decoder-couplings-v01.npz", **couplings)
        contribution = paired_margin_contributions(
            codes["M"], codes["F"], decoder,
            probes["M"]["weights"], probes["F"]["weights"], slot_map,
        )
        _save_npz(output / f"seed-{seed}-external-paired-feature-margin-contributions-v01.npz", **contribution)
        _write_contribution_bundle(
            output / f"seed-{seed}-external-event-contributions-v01.npz", rows,
            codes["M"], codes["F"], probes["M"]["weights"], probes["F"]["weights"], decoder, slot_map,
        )
        selection_path = s01_path / f"seed-{seed}-selected-feature-groups-v01.json"
        selection = read_json(selection_path)
        if selection.get("control_features_overlap_selected") is True or selection.get("control_features_are_unique") is not True:
            raise FailClosed(f"S07 selected groups have invalid training-only controls: seed={seed}")

        eval_records = []
        predictions: dict[str, np.ndarray] = {}
        native_logits: dict[str, np.ndarray] = {}
        native_predictions: dict[str, np.ndarray] = {}
        coupling_swap_records = []
        for code_surface in ("M", "F"):
            for readout in ("M", "F"):
                if code_surface == readout:
                    logits = _dense_native_logits(model, codes[code_surface], probes[readout], None, "float64")
                    for slice_name, mask in masks.items():
                        expected = next((record for record in gate["checks"] if record["seed"] == seed and record["dataset"] == "FAS00_ORIGINAL" and record["surface"] == code_surface and record["population"] == slice_name), None)
                        if expected is None or _metric_report(logits[mask], targets[mask])["confusion_matrix_true_rows_predicted_columns"] != expected["reconstruction"]["confusion_matrix_true_rows_predicted_columns"]:
                            raise FailClosed(f"FAS-00 native re-encoding differs from sealed gate: seed={seed}/{code_surface}/{slice_name}")
                    native_logits[code_surface] = logits
                    native_predictions[code_surface] = np.argmax(logits, axis=1).astype(np.int16)
                else:
                    logits = sparse_logits(codes[code_surface], decoder, decoder_bias, probes[readout])
                key = f"{code_surface}_codes_{readout}_readout"
                predictions[f"{key}_logits"] = logits.astype(np.float32)
                predictions[f"{key}_predictions"] = np.argmax(logits, axis=1).astype(np.int16)
                slice_metrics = {}
                for slice_name, mask in masks.items():
                    report, _pred, margin = _metric_record(logits[mask], targets[mask])
                    slice_metrics[slice_name] = report
                    predictions[f"{key}_{slice_name}_target_margins"] = margin
                    eval_records.append({"kind": "coupling_swap", "slice": slice_name, "code_surface": code_surface, "readout": readout, "metrics": report})
                coupling_swap_records.append({"code_surface": code_surface, "readout": readout, "metrics_by_slice": slice_metrics})

        for surface in ("M", "F"):
            analytic_base = sparse_logits(codes[surface], decoder, decoder_bias, probes[surface])
            for boundary, selected in selection["selected_groups"].items():
                controls = selection["matched_control_groups"][boundary]
                for group_name, feature_ids in (("selected", selected), ("matched_control", controls)):
                    analytic_after = sparse_logits(codes[surface], decoder, decoder_bias, probes[surface], zero_features=feature_ids)
                    logits = native_logits[surface] + (analytic_after - analytic_base)
                    after = np.argmax(logits, axis=1).astype(np.int16)
                    transition = metric_transitions(native_predictions[surface], after, targets)
                    prefix = f"{surface}_{boundary}_{group_name}"
                    predictions[f"{prefix}_logits"] = logits.astype(np.float32)
                    predictions[f"{prefix}_predictions"] = after
                    prediction_transitions = np.asarray(transition["prediction_transition_counts_rows_before_columns_after"], dtype=np.int64)
                    predictions[f"{prefix}_transition_counts"] = prediction_transitions
                    eval_records.append({
                        "kind": "sparse_reconstruction_ablation",
                        "code_surface": surface,
                        "native_readout": surface,
                        "boundary_group": boundary,
                        "intervention": group_name,
                        "feature_ids": feature_ids,
                        "feature_count": len(feature_ids),
                        "against": "faithful_unablated_reconstruction",
                        "transition": transition,
                        "metrics_by_slice": {name: _metric_report(logits[mask], targets[mask]) for name, mask in masks.items()},
                    })

        _save_npz(output / f"seed-{seed}-external-intervention-predictions-v01.npz", **predictions)
        write_json(output / f"seed-{seed}-external-intervention-metrics-v01.json", {"seed": seed, "records": eval_records})
        write_json(output / f"seed-{seed}-external-coupling-swap-v01.json", {"seed": seed, "records": coupling_swap_records})
        summaries.append({
            "seed": seed,
            "rows": len(rows),
            "gate_code_reencoding_exact": True,
            "selected_feature_union_size": selection["selected_feature_union_size"],
            "control_features_unique": selection["control_features_are_unique"],
            "control_features_overlap_selected": selection["control_features_overlap_selected"],
            "activation_frequency_median_M": float(np.median(stats["M"]["activation_frequency"])),
            "activation_frequency_median_F": float(np.median(stats["F"]["activation_frequency"])),
            "coupling_swap_count": len(coupling_swap_records),
            "ablation_count": sum(record["kind"] == "sparse_reconstruction_ablation" for record in eval_records),
        })
        del model
        torch.cuda.empty_cache()
        print(f"S07_FAS00_EXTERNAL_SEED_COMPLETE seed={seed}", flush=True)

    report = {
        "analysis_stage": "FAS00_EXTERNAL_TRANSFER_AFTER_SEALED_S01",
        "status": "COMPLETE",
        "protocol_root_sha256": protocol["root_sha256"],
        "gate_root_sha256": gate_seal["root_sha256"],
        "s01_analysis_root_sha256": s01_seal["root_sha256"],
        "analysis_contract_sha256": sha256_file(ANALYSIS_CONTRACT),
        "fas00_feature_values_opened_after_s01_seal": True,
        "probe_fitting": False,
        "feature_names_assigned": False,
        "maximally_activating_examples_inspected": False,
        "seed_summaries": summaries,
    }
    write_json(output / "fas00-external-report-v01.json", report)
    fas_seal = _seal_folder(output, "fas00-external-seal-v01.json", "FAS_S07_FAS00_EXTERNAL_SEAL_V01", {
        "protocol_root_sha256": protocol["root_sha256"],
        "gate_root_sha256": gate_seal["root_sha256"],
        "s01_analysis_root_sha256": s01_seal["root_sha256"],
    })
    write_json(root / "s07-result-report-v01.json", {
        "result_id": "FAS_S07_SPARSE_COMPATIBILITY_CARTOGRAPHY_V01",
        "status": "COMPLETE",
        "protocol_root_sha256": protocol["root_sha256"],
        "gate_root_sha256": gate_seal["root_sha256"],
        "s01_analysis_root_sha256": s01_seal["root_sha256"],
        "fas00_external_root_sha256": fas_seal["root_sha256"],
        "analysis_contract_sha256": sha256_file(ANALYSIS_CONTRACT),
        "sae_training_contract_sha256": sha256_file(SAE_CONTRACT),
        "feature_extraction": False,
        "transformer_contact": False,
        "probe_fitting": False,
        "feature_names_assigned": False,
        "maximally_activating_examples_inspected": False,
        "FAS00_SENSOR_PASS": False,
        "FAS00_PHASE4_AUTHORIZED": False,
        "S07_LAYERWISE_AUTHORIZED": False,
        "adaptive_mechanism_authorized": False,
    })
    entries = [{"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in root.rglob("*") if path.is_file() and path.name != "result-tree-seal-v01.json"]
    entries.sort(key=lambda item: item["path"].casefold())
    result_seal = {
        "seal_id": "FAS_S07_RESULT_TREE_SEAL_V01",
        "status": "SEALED",
        "entries": entries,
        "root_sha256": root_simple(entries),
        "protocol_root_sha256": protocol["root_sha256"],
        "gate_root_sha256": gate_seal["root_sha256"],
        "s01_analysis_root_sha256": s01_seal["root_sha256"],
        "fas00_external_root_sha256": fas_seal["root_sha256"],
        "S07_RESULT_READY": True,
        "FAS00_SENSOR_PASS": False,
        "FAS00_PHASE4_AUTHORIZED": False,
        "S07_LAYERWISE_AUTHORIZED": False,
        "adaptive_mechanism_authorized": False,
    }
    write_json(root / "result-tree-seal-v01.json", result_seal)
    print(f"S07_RESULT_SEALED root={result_seal['root_sha256']} files={len(entries)}")


if __name__ == "__main__":
    try:
        main()
    except FailClosed as exc:
        print(f"S07_EXTERNAL_FAIL_CLOSED {exc}")
        raise SystemExit(2)
