"""Finalize the completed Lexi Phase 5 run without retraining or EVAL access."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = Path(r"C:/code land/clean-rust/experiments/s15-lexi-phase5-split-forge-v03")
RUN = Path(r"C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v03")
OUT = Path(r"C:/phoenix-target-overgraph/lexi-phase5-split-forge-20261002-v04")
sys.path.insert(0, str(SOURCE))

from lexi_contract import read as read_json, verify as verify_frozen_inputs
from report import Population, metrics
from comparison_v04 import compare_depths, count_mae_improvement, source_balanced_interval


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def same_tree(left, right, path="$", atol=0.0):
    """Exact metric replay; only floats use a tiny serialization-safe tolerance."""
    if isinstance(left, dict) and isinstance(right, dict):
        if left.keys() != right.keys():
            return False, f"{path}: key mismatch"
        for key in left:
            ok, reason = same_tree(left[key], right[key], f"{path}.{key}", atol)
            if not ok:
                return ok, reason
        return True, None
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return False, f"{path}: list length mismatch"
        for i, (a, b) in enumerate(zip(left, right)):
            ok, reason = same_tree(a, b, f"{path}[{i}]", atol)
            if not ok:
                return ok, reason
        return True, None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, float) or isinstance(right, float):
            return abs(float(left) - float(right)) <= atol, None if abs(float(left) - float(right)) <= atol else f"{path}: {left} != {right}"
    return (left == right), None if left == right else f"{path}: {left!r} != {right!r}"


def verify_dev_metric_replay(dev):
    reports = [
        ("INIT", read_json(RUN / "INIT-REPORT.json")),
        ("BRIDGE", read_json(RUN / "BRIDGE-REPORT.json")),
        ("A_DETERMINISTIC", read_json(RUN / "A-REPORT.json")),
    ]
    b_report = read_json(RUN / "B-REPORT.json")
    reports.extend(("B_STOCHASTIC", item) for item in [b_report["operational"], *b_report["diagnostic_seeds"]])
    checked = 0
    for identity, report in reports:
        for depth, expected in report["depths"].items():
            path = RUN / "predictions" / identity / f"{report['seed']}-T{depth}.npz"
            with np.load(path, allow_pickle=False) as saved:
                arrays = [saved[key] for key in ("g", "c", "action", "s", "e_stats")]
                for key, arr in zip(("g", "c", "action", "s", "e_stats"), arrays):
                    if key != "action" and not np.isfinite(arr).all():
                        raise ValueError(f"Non-finite {key} prediction: {path}")
                observed = metrics(dev, *arrays)
            ok, reason = same_tree(observed, expected, atol=0.0)
            if not ok:
                raise ValueError(f"DEV metric replay failed: {identity} T{depth}: {reason}")
            checked += 1
    return checked


def verify_bridge_frozen():
    import torch
    bridge = torch.load(RUN / "models" / "BRIDGE" / "best.pt", map_location="cpu", weights_only=True)
    checks = {}
    for arm in ("A_DETERMINISTIC", "B_STOCHASTIC"):
        state = torch.load(RUN / "models" / arm / "best.pt", map_location="cpu", weights_only=True)
        if set(bridge) - {key.removeprefix("seed.") for key in state if key.startswith("seed.")}:
            raise ValueError(f"Missing inherited bridge tensors in {arm}")
        compared = 0
        for key, value in bridge.items():
            if not torch.equal(value, state["seed." + key]):
                raise ValueError(f"Frozen bridge changed in {arm}: {key}")
            compared += 1
        checks[arm] = {"exact_tensor_match": True, "tensor_count": compared}
    return checks


def source_accessibility(readout_rows):
    # Preserve the full predeclared panel; no selection or refit occurs here.
    return readout_rows


def summarize_semantics(dev, a_report, b_report):
    a_saved_path = RUN / "predictions" / "A_DETERMINISTIC" / f"{a_report['seed']}-T4.npz"
    with np.load(a_saved_path, allow_pickle=False) as f:
        a_g = f["g"].copy()
        a_c = f["c"].copy()
    summaries = {}
    target_specs = [
        ("solvable", "global", 0),
        ("goal_satisfied", "global", 1),
        ("missing_information_present", "global", 2),
        ("candidate_legal", "candidate", 0),
        ("candidate_satisfies_goal", "candidate", 1),
    ]
    b_reports = [b_report["operational"], *b_report["diagnostic_seeds"]]
    for name, family, channel in target_specs:
        key = "g" if family == "global" else "c"
        av = a_report["depths"]["4"][family][name]["balanced_accuracy"]
        seeds = []
        for item in b_reports:
            seed = int(item["seed"])
            path = RUN / "predictions" / "B_STOCHASTIC" / f"{seed}-T4.npz"
            with np.load(path, allow_pickle=False) as f:
                b_pred = f[key][..., channel] >= 0
            a_pred = (a_g if key == "g" else a_c)[..., channel] >= 0
            interval = source_balanced_interval(dev, a_pred, b_pred, family, channel)
            bv = item["depths"]["4"][family][name]["balanced_accuracy"]
            seeds.append({"seed": seed, "B_balanced_accuracy": bv,
                          "B_minus_A": None if av is None or bv is None else bv - av,
                          "paired_root_interval": interval})
        summaries[name] = {"A_T4_balanced_accuracy": av, "B_T4_by_trajectory": seeds,
                           "available_labels": int(dev.arrays["ga"][:, channel].sum()) if family == "global" else int((dev.arrays["ca"][:, :, channel] & dev.arrays["mask"]).sum())}

    target = np.asarray(dev.arrays["gy"][:, 5])
    a_count_mae = float(np.abs(a_g[:, 5] - target).mean())
    count_rows = []
    for item in b_reports:
        seed = int(item["seed"])
        path = RUN / "predictions" / "B_STOCHASTIC" / f"{seed}-T4.npz"
        with np.load(path, allow_pickle=False) as f:
            b_g = f["g"].copy()
        count_rows.append({"seed": seed,
                           "A_minus_B_raw_MAE": count_mae_improvement(dev, a_g[:, 5], b_g[:, 5]),
                           "A_raw_MAE": a_count_mae,
                           "B_raw_MAE": float(np.abs(b_g[:, 5] - target).mean()),
                           "A_runtime_count_MAE": float(np.abs(np.maximum(0, np.floor(a_g[:, 5] + .5)) - target).mean()),
                           "B_runtime_count_MAE": float(np.abs(np.maximum(0, np.floor(b_g[:, 5] + .5)) - target).mean())})
    summaries["missing_cardinality"] = {
        "source_alias": "missing_information_present; one supervision source unit",
        "stratum_restricted": True,
        "rows": int(dev.arrays["ga"][:, 5].sum()),
        "A_minus_B_MAE_by_trajectory": count_rows,
    }
    # State preservation means no evidence of degradation; it is not an equivalence claim.
    no_detected_harm = True
    for name, row in summaries.items():
        if name == "missing_cardinality":
            intervals = [x["A_minus_B_raw_MAE"]["bootstrap95"] for x in row["A_minus_B_MAE_by_trajectory"]]
            no_detected_harm &= all(ci is not None and ci[1] >= 0 for ci in intervals)
        else:
            no_detected_harm &= all(x["paired_root_interval"]["bootstrap95"][1] >= 0 for x in row["B_T4_by_trajectory"])
    return summaries, no_detected_harm


def file_inventory(root: Path):
    entries = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        entries.append({"relative_path": path.relative_to(root).as_posix(),
                        "bytes": path.stat().st_size, "sha256": sha256(path)})
    return entries


def training_summary():
    names = ("BRIDGE", "A_DETERMINISTIC", "B_STOCHASTIC")
    result = {}
    for name in names:
        receipt = read_json(RUN / "models" / name / "RECEIPT.json")
        curves = read_json(RUN / "models" / name / "curves.json")
        result[name] = {
            "selected_epoch": receipt["selected_epoch"],
            "selection": receipt["selection"],
            "TRAIN_rows": receipt["TRAIN_rows"], "DEV_rows": receipt["DEV_rows"],
            "trainable_parameters": receipt["trainable_parameters"],
            "training_seconds": receipt["seconds"],
            "peak_cuda_bytes": receipt["peak_cuda_bytes"],
            "best_checkpoint_sha256": receipt["best_sha256"],
            "selected_DEV_objective": receipt.get("selected_DEV_objective"),
            "curve_first": curves[0], "curve_final": curves[-1],
            "curve_min_DEV": min(curves, key=lambda row: row["DEV_loss"]),
            "protected_contact": receipt["protected_contact"],
        }
    return result


def make_summary(pop, spec, adapter, bridge_checks, replay_count, semantic, no_state_harm, raw_comparison):
    a = read_json(RUN / "A-REPORT.json")
    b = read_json(RUN / "B-REPORT.json")
    bridge = read_json(RUN / "BRIDGE-REPORT.json")
    init = read_json(RUN / "INIT-REPORT.json")
    comparison = compare_depths(pop, a, b)
    comparison["semantic_preservation"] = semantic
    pre = comparison["disposition_before_semantic_preservation"]
    if pre == "B_REQUIRES_STATE_PRESERVATION_REVIEW":
        comparison["disposition"] = "B_SURVIVES_REPEATABLE_DEPTH_GAIN_NO_DETECTED_STATE_LOSS" if no_state_harm else "B_RETIRE_SEMANTIC_PRESERVATION_NOT_ESTABLISHED"
    else:
        comparison["disposition"] = pre
    comparison["no_detected_semantic_harm"] = no_state_harm
    comparison["semantic_interpretation"] = "Non-significant harm is not evidence of equivalence; all target values remain separate."
    b_op = b["operational"]
    a_action = [a["depths"][str(t)]["action"] for t in range(5)]
    b_action = {str(r["seed"]): [r["depths"][str(t)]["action"] for t in range(5)] for r in [b_op, *b["diagnostic_seeds"]]}
    report_files = ["INIT-REPORT.json", "BRIDGE-REPORT.json", "A-REPORT.json", "B-REPORT.json",
                    "BRIDGE-ABLATIONS.json", "A-ABLATIONS.json", "B-ABLATIONS.json", "ACCESSIBILITY.json"]
    source_reports = {name: read_json(RUN / name) for name in report_files}
    data_identity = {}
    for split in ("TRAIN", "DEV"):
        folder = RUN / "data" / split
        data_identity[split] = {p.name: sha256(p) for p in sorted(folder.iterdir()) if p.is_file()}
    return {
        "status": "PHASE5_LEXI_RUN_COMPLETE_FINALIZATION_READY_FOR_INDEPENDENT_REPLAY",
        "scope": "BANK-v3-core TRAIN/DEV only; protected evaluation unopened; engineering result, not external qualification",
        "identities": {
            "lane": "LEXI_LFM230M",
            "bank_v3_core_release_identity": adapter["release_identity"],
            "bank_v3_handoff_sha256": adapter["handoff_sha256"],
            "phase5_spec_sha256": sha256(RUN / "PHASE5-SPEC.json"),
            "source_run": str(RUN), "source_code": str(SOURCE),
            "surface": spec["surface"], "backbone": spec["model_path"],
            "backbone_hashes": spec["model_hashes"],
            "adapter_receipt_sha256": sha256(RUN / "ADAPTER-RECEIPT.json"),
        },
        "candidate_and_population": {
            "candidate_slots": int(pop.arrays["mask"].shape[1]),
            "maximum_live_candidates_TRAIN": int(adapter["splits"]["TRAIN"]["max_candidates"]),
            "maximum_live_candidates_DEV": int(pop.arrays["mask"].sum(axis=1).max()),
            "maximum_live_candidates_across_frozen_populations": max(int(adapter["splits"]["TRAIN"]["max_candidates"]), int(pop.arrays["mask"].sum(axis=1).max())),
            "candidate_count_distribution_DEV": {str(int(k)): int(v) for k, v in zip(*np.unique(pop.arrays["mask"].sum(axis=1), return_counts=True))},
            "candidate_truncation": 0,
            "TRAIN_rows": 24000, "TRAIN_roots": 12000,
            "DEV_rows": len(pop.meta), "DEV_roots": len(pop.meta) // 2,
            "paired_renderers_per_root": 2,
            "action_types": list(__import__("lexi_contract").VOCAB[1:]),
            "DEV_action_eligible_rows": int((pop.arrays["action"] >= 0).sum()),
            "DEV_action_eligible_roots": int((pop.arrays["action"].reshape(-1, 2)[:, 0] >= 0).sum()),
            "optimal_set_nonempty_rows": int(pop.arrays["optimal"].any(axis=1).sum()),
            "empty_optimal_rows": int((~pop.arrays["optimal"].any(axis=1)).sum()),
            "renderer_families": sorted({row["renderer"] for row in pop.meta}),
            "protected_test_truth_opened": False,
        },
        "training_contract": {
            "backbone_frozen": True, "inherited_bridge_frozen_in_A_B": bridge_checks,
            "training": training_summary(),
            "A_identity": "fixed epoch 20 deterministic shared-weight recurrence, T=4",
            "B_identity": "fixed epoch 20 single learned diagonal-noise trajectory, T=4; operational seed 20261002; two separate diagnostic seeds",
            "selection_contract": "Bridge lowest full DEV objective; A and B fixed final epoch 20; no sampled-DEV selection, no seed selection, no ensemble",
            "B_additional_trainable_parameters": int(b_op["additional_scale_parameters"]),
            "B_log_scale_bounds": b_op["log_scale_bounds"],
            "B_scale_RMS_by_step": b_op["scale_RMS"],
            "B_trajectory_variance": b.get("trajectory_variance"),
        },
        "results": {
            "initialization": init,
            "bridge": bridge,
            "A_deterministic": {"report": a, "action_by_depth": a_action,
                                "ablation": source_reports["A-ABLATIONS.json"]},
            "B_stochastic": {"report": b, "action_by_seed_and_depth": b_action,
                              "ablation": source_reports["B-ABLATIONS.json"]},
            "bridge_ablation": source_reports["BRIDGE-ABLATIONS.json"],
            "accessibility": source_accessibility(source_reports["ACCESSIBILITY.json"]),
            "comparison": comparison,
        },
        "metric_replay": {"DEV_depth_reports_exactly_recomputed": replay_count,
                          "candidate_predictions_masked_by_canonical_validity": True,
                          "replay_function": "frozen v03 report.metrics recomputed from saved predictions and DEV labels",
                          "protected_files_opened": 0},
        "split_identity_hashes": data_identity,
        "frozen_input_inventory": "INPUT-INVENTORY.json",
        "historical_failure": {
            "path": str(RUN / "FAILURE.txt"),
            "sha256": sha256(RUN / "FAILURE.txt"),
            "cause": "null capability-depth value was sorted together with integers in the original comparison finalizer",
            "repair": "versioned null-safe root-paired comparator in v04; original run and failure record preserved",
        },
        "disposition": comparison["disposition"],
        "limitations": [
            "DEV only; no protected evaluation or external qualification claim.",
            "Only MOVE clears the 200-root action-type reliability floor; all other action-type values are descriptive/support-only.",
            "Capability axes with null values are not applicable and excluded from depth-gain claims.",
            "Stochastic seeds are trajectories from one trained B model, not independent training seeds or an ensemble.",
            "Fixed epoch 20 was required by the frozen selection amendment; rising DEV objective is retained, not repaired by checkpoint fishing.",
            "No fixed accuracy gate was specified; B disposition follows repeatable action gain, depth-conditioned gain, and semantic-preservation evidence.",
        ],
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if any(OUT.iterdir()):
        raise FileExistsError(f"Finalization directory is not empty: {OUT}")
    spec = verify_frozen_inputs()
    adapter = read_json(RUN / "ADAPTER-RECEIPT.json")
    dev = Population("DEV", device="cpu")
    train_meta = read_json(RUN / "data" / "TRAIN" / "metadata.json")
    train_mask = np.load(RUN / "data" / "TRAIN" / "mask.npy", mmap_mode="r")
    if len(train_meta) != 24000 or len({x["root"] for x in train_meta}) != 12000:
        raise ValueError("TRAIN identity/count mismatch")
    if len(dev.meta) != 6000 or len({x["root"] for x in dev.meta}) != 3000:
        raise ValueError("DEV identity/count mismatch")
    if dev.arrays["mask"].shape[1] != 171 or train_mask.shape[1] != 171:
        raise ValueError("Candidate universe not exhaustive as frozen")
    actual_max = max(int(train_mask.sum(axis=1).max()), int(dev.arrays["mask"].sum(axis=1).max()))
    receipt_max = max(int(adapter["splits"][split]["max_candidates"]) for split in ("TRAIN", "DEV"))
    if actual_max != 171 or receipt_max != actual_max:
        raise ValueError(f"Exhaustive maximum mismatch: observed={actual_max}, receipt={receipt_max}")
    if any(x["truncated_candidates"] != 0 for x in adapter["splits"].values()):
        raise ValueError("Adapter reports candidate truncation")
    bridge_checks = verify_bridge_frozen()
    replay_count = verify_dev_metric_replay(dev)
    b_report = read_json(RUN / "B-REPORT.json")
    a_report = read_json(RUN / "A-REPORT.json")
    semantic, no_state_harm = summarize_semantics(dev, a_report, b_report)

    # Hash all source-run files, including the preserved failed comparator log and caches.
    inventory = file_inventory(RUN)
    inventory_record = {
        "source_run": str(RUN), "file_count": len(inventory),
        "total_bytes": sum(row["bytes"] for row in inventory), "files": inventory,
    }
    write_json(OUT / "INPUT-INVENTORY.json", inventory_record)
    summary = make_summary(dev, spec, adapter, bridge_checks, replay_count, semantic, no_state_harm, None)
    write_json(OUT / "PHASE5-COMPARISON.json", summary)
    comparison = summary["results"]["comparison"]
    a = summary["results"]["A_deterministic"]["report"]
    b = summary["results"]["B_stochastic"]["report"]
    lines = [
        "# Lexi Phase 5 — BANK-v3-core computation lane",
        "",
        f"Disposition: **{summary['disposition']}**.",
        "",
        "The full v03 training run completed. A and B both used fixed epoch 20, and the frozen bridge tensors match exactly inside both recurrent checkpoints. The original null-depth comparator failure remains preserved in v03; v04 adds a null-safe, root-paired finalizer.",
        "",
        "## Action by recurrent depth",
        "",
        "| Depth | A exact logged action | B operational | B−A (root-paired, 95% bootstrap) | A optimal-set hit | B optimal-set hit |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    seed0 = int(b["operational"]["seed"])
    for depth in range(5):
        row = next(x for x in comparison["depth_differences"] if x["seed"] == seed0 and x["depth"] == depth)
        ci = row["B_minus_A_exact_action"]["bootstrap95"]
        ci_text = "n/a" if ci is None else f"[{ci[0]:+.4f}, {ci[1]:+.4f}]"
        lines.append(
            f"| T{depth} | {a['depths'][str(depth)]['action']['exact_logged_accuracy']:.4f} | "
            f"{b['operational']['depths'][str(depth)]['action']['exact_logged_accuracy']:.4f} | "
            f"{row['B_minus_A_exact_action']['difference']:+.4f} {ci_text} | "
            f"{a['depths'][str(depth)]['action']['optimal_set_hit_all_eligible_nonempty']:.4f} | "
            f"{b['operational']['depths'][str(depth)]['action']['optimal_set_hit_all_eligible_nonempty']:.4f} |"
        )
    lines += [
        "",
        f"DEV action support is {comparison['eligible_roots']} eligible roots ({comparison['eligible_rows']} rows). MOVE has 249 roots and is the only action type above the 200-root reliability floor. The two other B trajectories are reported separately in `PHASE5-COMPARISON.json`; they are not averaged or selected.",
        "",
        "## Cost and state behavior",
        "",
        f"A trained for {a['seconds']:.1f}s with {summary['training_contract']['training']['A_DETERMINISTIC']['peak_cuda_bytes'] / 1024**2:.1f} MiB peak CUDA memory and {summary['training_contract']['training']['A_DETERMINISTIC']['trainable_parameters']:,} trainable parameters. B trained for {b['operational']['seconds']:.1f}s with {summary['training_contract']['training']['B_STOCHASTIC']['peak_cuda_bytes'] / 1024**2:.1f} MiB and {summary['training_contract']['training']['B_STOCHASTIC']['trainable_parameters']:,} parameters, including 4,288 scale parameters. B's measured per-step scale RMS is " + ", ".join(f"{x:.4f}" for x in b['operational']['scale_RMS']) + ".",
        "",
        "The machine-readable report preserves all five depth metrics, action-type denominators, optimal-set handling, renderer correctness decompositions, composition/transition slices, ablations, state diversity, update RMS, accessibility probes, training curves, costs, and per-file hashes.",
        "",
        "No protected evaluation files were opened. Results are an internal DEV engineering comparison, not external qualification.",
        "",
    ]
    with (OUT / "FINAL-REPORT.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines))

    source_inventory = file_inventory(SOURCE)
    receipt = {
        "status": "FINALIZATION_ARTIFACTS_WRITTEN_AWAITING_INDEPENDENT_REPLAY",
        "repair_version": "v04",
        "phase5_spec_sha256": sha256(RUN / "PHASE5-SPEC.json"),
        "v03_source_count": len(source_inventory),
        "v03_source_hashes": {row["relative_path"]: row["sha256"] for row in source_inventory},
        "outputs": {name: sha256(OUT / name) for name in ("INPUT-INVENTORY.json", "PHASE5-COMPARISON.json", "FINAL-REPORT.md")},
        "source_run_inventory_sha256": sha256(OUT / "INPUT-INVENTORY.json"),
        "dev_metric_reports_replayed": replay_count,
        "bridge_frozen_tensor_checks": bridge_checks,
        "protected_truth_opened": False,
    }
    write_json(OUT / "FINALIZATION-RECEIPT.json", receipt)
    print(json.dumps({"status": receipt["status"], "disposition": summary["disposition"],
                      "dev_metric_reports_replayed": replay_count, "source_files_hashed": len(inventory)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
