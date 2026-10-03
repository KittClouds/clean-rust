"""Outcome-blind step-120 1x calibration for the R3 ratio-floor decision."""

from __future__ import annotations

import hashlib
import importlib.util
import argparse
import json
import math
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02")
TRAINING = RUN / "calibration-training-v02"
PREFLIGHT = RUN / "calibration-preflight-v03"
PANEL = RUN / "calibration-panel-v02"
FEATURES = RUN / "calibration-features-v01"
REPLAY = RUN / "continuation-replay-v02"
S80_SUMMARY = TRAINING / "pretreatment-s80-calibration-v02.json"
OUTPUT = RUN / "calibration-s1x-terminal-v01"

RUNNER_PATH = ROOT / "experiments/jev-information-density-v08q-r3-selectivity/source/run_r3_pretreatment_calibration_v01.py"
REPLAY_PATH = ROOT / "experiments/jev-information-density-v08q-r3-selectivity/source/run_r3_continuation_replay_v01.py"
SUMMARY_PATH = ROOT / "experiments/jev-information-density-v08q-r3-selectivity/source/summarize_r3_pretreatment_s80_v01.py"
PROBE_PATH = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
BATCHER_PATH = ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py"
OBJECTIVE_PATH = ROOT / "experiments/jev-information-density-v08q/source/q_weighted_objective_v02.py"

EXPECTED_TRAINING_SEAL_SHA = "5521b0a82b231dbe47e7b9f2235a8758f4ef29dbf4945c56ac6512e134c9150f"
EXPECTED_TRAINING_TREE_ROOT = "0fd972996eaf33a9199deeec3ebdf3cec63f28ad9393c3b76c020c2be23cde97"
EXPECTED_PREFLIGHT_ROOT = "fb962c44dfbb6c869957f54439cedec223159d88a427bbe44c7d6be641650795"
EXPECTED_PANEL_SHA = "6b813445b14bb8494962b2cc9b0cc8a229244177083c3a605d21ef4f880dbaef"
EXPECTED_CANDIDATE_SHA = "cc45c81e2b6d70d222170872e9ddd96e1b48dfe90d26e588d319a34a7f101b33"
EXPECTED_FEATURE_ROOT = "bd040d4b22eb3ba4098a593746cf8dcab9409e82b2359ddc185723c657db9e36"
EXPECTED_S80_SHA = "841a11b9f8d79e1a0353a38fb1fa38cb5b1a575039b952404a176679ef9f1e78"
EXPECTED_REPLAY_ROOT = "55c2297843876bbf502485af28e3810742ed509bbe6ef2d307323552d7e90abe"
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
DIRECTIONS = ("high_to_low", "low_to_high")
FLOORS = (0.01, 0.004)
RATIO_COVERAGE_COUNT = math.ceil(0.90 * 192)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def tree_root(entries: list[dict[str, Any]]) -> str:
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    return hashlib.sha256(body.encode()).hexdigest()


def bind_inputs(runner: Any, replay: Any, summary: Any) -> dict[str, Any]:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing existing calibration output namespace: {OUTPUT}")
    training_seal = runner.read_json(TRAINING / "step80-training-seal.json")
    if sha_file(TRAINING / "step80-training-seal.json") != EXPECTED_TRAINING_SEAL_SHA:
        raise RuntimeError("step-80 training seal file identity mismatch")
    if training_seal.get("entries_root_sha256") != EXPECTED_TRAINING_TREE_ROOT:
        raise RuntimeError("step-80 training tree root identity mismatch")
    replay_seal = runner.read_json(REPLAY / "replay-root-seal.json")
    if replay_seal.get("entries_root_sha256") != EXPECTED_REPLAY_ROOT or "PASS" not in replay_seal.get("status", ""):
        raise RuntimeError("same-fork replay seal mismatch")
    preflight_seal = runner.read_json(PREFLIGHT / "pretraining-seal.json")
    if preflight_seal.get("entries_root_sha256") != EXPECTED_PREFLIGHT_ROOT:
        raise RuntimeError("calibration preflight root mismatch")
    manifest, primary, auxiliary, base_schedule, states, candidates = runner.verify_preflight_seal()
    if sha_file(RUNNER_PATH) != manifest["runner_sha256"]:
        raise RuntimeError("bound training runner changed")
    if sha_file(S80_SUMMARY) != EXPECTED_S80_SHA:
        raise RuntimeError("sealed S80 calibration summary identity mismatch")
    panel_path = PANEL / "calibration-panel-views.jsonl"
    candidate_path = PANEL / "candidate-texts.jsonl"
    if sha_file(panel_path) != EXPECTED_PANEL_SHA or sha_file(candidate_path) != EXPECTED_CANDIDATE_SHA:
        raise RuntimeError("calibration panel or candidate manifest identity mismatch")
    feature_seal = summary.read_json(FEATURES / "feature-cache-seal-v01.json")
    if tree_root(sorted(feature_seal["entries"], key=lambda row: row["path"])) != EXPECTED_FEATURE_ROOT:
        raise RuntimeError("calibration feature cache root mismatch")
    training = summary.verify_training_tree()
    if training["training_tree_root_sha256"] != EXPECTED_TRAINING_TREE_ROOT:
        raise RuntimeError("step-80 training tree verifier disagreement")
    s80 = summary.read_json(S80_SUMMARY)
    if len(s80.get("histories", [])) != 48 or s80.get("treatment_outcomes_opened") is not False:
        raise RuntimeError("S80 calibration scope or history count mismatch")
    if torch.__version__ != "2.11.0+cu128" or not torch.cuda.is_available() \
            or torch.version.cuda != "12.8" or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise RuntimeError("calibration continuation runtime identity mismatch")
    return {
        "manifest": manifest,
        "primary": primary,
        "auxiliary": auxiliary,
        "base_schedule": base_schedule,
        "states": states,
        "candidates": candidates,
        "training_seal": training_seal,
        "training_seal_sha256": sha_file(TRAINING / "step80-training-seal.json"),
        "preflight_seal_sha256": sha_file(PREFLIGHT / "pretraining-seal.json"),
        "preflight_manifest_sha256": sha_file(PREFLIGHT / "calibration-schedule-manifest.json"),
        "feature_seal_sha256": sha_file(FEATURES / "feature-cache-seal-v01.json"),
        "feature_root_sha256": EXPECTED_FEATURE_ROOT,
        "panel_sha256": EXPECTED_PANEL_SHA,
        "candidate_manifest_sha256": EXPECTED_CANDIDATE_SHA,
        "s80_summary_sha256": EXPECTED_S80_SHA,
        "replay_root_sha256": EXPECTED_REPLAY_ROOT,
        "training_tree_root_sha256": EXPECTED_TRAINING_TREE_ROOT,
        "seeds": manifest["seed_derivation"]["seeds"],
        "s80_histories": {int(row["seed"]): row for row in s80["histories"]},
    }


def restore_rng(state: dict[str, Any]) -> None:
    random.setstate(state["python"])
    torch.set_rng_state(state["torch_cpu"].cpu())
    torch.cuda.set_rng_state_all([value.cpu() for value in state["torch_cuda"]])


def continue_one(seed: int, bindings: dict[str, Any], runner: Any, replay: Any,
                 probe: Any, batcher: Any, objective: Any, out_dir: Path) -> dict[str, Any]:
    source_rel = f"seed-{seed}/step-080.pt"
    source_path = TRAINING / source_rel
    source_entry = next((row for row in bindings["training_seal"]["entries"] if row["path"] == source_rel), None)
    if source_entry is None or sha_file(source_path) != source_entry["sha256"]:
        raise RuntimeError(f"unsealed or changed step-80 checkpoint: {seed}")
    fork = torch.load(source_path, map_location="cpu", weights_only=False)
    if fork.get("seed") != seed or fork.get("global_step") != 80 or fork.get("event_cursor") != 80 \
            or fork.get("auxiliary_multiplier") != 1.0 or fork.get("evaluation_panel_opened") is not False:
        raise RuntimeError(f"fork state is not the sealed common 1x prefix: {seed}")
    schedule = replay.epoch3_schedule(bindings["primary"], seed)
    schedule_bytes = b"".join(runner.canonical_jsonl(row) for row in schedule)
    seed_dir = out_dir / f"seed-{seed}"
    seed_dir.mkdir(parents=False, exist_ok=False)
    states, candidates = bindings["states"].to("cuda"), bindings["candidates"].to("cuda")
    head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
    head.load_state_dict(fork["head_state"], strict=True)
    head.train()
    optimizer = torch.optim.AdamW(head.parameters(), lr=0.002, weight_decay=0.01,
                                 betas=(0.9, 0.999), eps=1e-8, amsgrad=False)
    optimizer.load_state_dict(fork["optimizer_state"])
    if runner.state_sha(head.state_dict()) != fork["head_sha256"] \
            or runner.tree_sha(optimizer.state_dict()) != fork["optimizer_sha256"]:
        raise RuntimeError(f"step-80 model/optimizer restore mismatch: {seed}")
    restore_rng(fork["rng_state"])
    telemetry_path = seed_dir / "continuation-telemetry.jsonl"
    with telemetry_path.open("xb") as telemetry:
        for item in schedule:
            base = [bindings["primary"][index] for index in item["primary_occurrence_indices"]]
            auxiliary = [bindings["auxiliary"][index] for index in item["auxiliary_anchor_batch_slots"]]
            batch = [runner.prepare(row) for row in base] + [runner.prepare(row) for row in auxiliary]
            state, candidate, gold, mask, kinds, sources = batcher.fast_tensor_batch(
                batch, states, candidates, "name_definition", "cuda", reorder=True)
            weights = torch.ones(len(batch), device="cuda")
            optimizer.zero_grad(set_to_none=True)
            logits = head(state, candidate)
            loss, brier = objective.q_weighted_loss(logits, gold, mask, kinds, sources, 0.25, weights)
            if not bool(torch.isfinite(loss).item()) or not bool(torch.isfinite(brier).item()):
                raise RuntimeError(f"nonfinite 1x calibration continuation: {seed}/{item['global_step']}")
            loss.backward()
            grad_sq = torch.zeros((), device="cuda")
            for parameter in head.parameters():
                if parameter.grad is not None:
                    if not bool(torch.isfinite(parameter.grad).all().item()):
                        raise RuntimeError(f"nonfinite continuation gradient: {seed}/{item['global_step']}")
                    grad_sq += parameter.grad.detach().float().square().sum()
            optimizer.step()
            record = {"seed": seed, "global_step": item["global_step"], "epoch": 3,
                      "step_in_epoch": item["step"],
                      "primary_indices": item["primary_occurrence_indices"],
                      "auxiliary_anchor_batch_slots": item["auxiliary_anchor_batch_slots"],
                      "auxiliary_multiplier": 1.0, "loss": float(loss.detach()),
                      "brier": float(brier.detach()), "gradient_norm": float(grad_sq.sqrt()),
                      "calibration_panel_used_for_feedback": False, "half_branch": False}
            telemetry.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode() + b"\n")
            telemetry.flush()
            os.fsync(telemetry.fileno())
    if len(telemetry_path.read_bytes().splitlines()) != 40:
        raise RuntimeError(f"continuation telemetry incomplete: {seed}")
    torch.cuda.synchronize()
    payload = {"status": "R3_CALIBRATION_STEP120_1X_ONLY_NO_HALF",
               "seed": seed, "global_step": 120, "event_cursor": 120,
               "auxiliary_multiplier": 1.0, "head_state": runner.clone_cpu(head.state_dict()),
               "optimizer_state": runner.clone_cpu(optimizer.state_dict()),
               "head_sha256": runner.state_sha(head.state_dict()),
               "optimizer_sha256": runner.tree_sha(optimizer.state_dict()),
               "rng_state": runner.capture_rng(),
               "step80_checkpoint_sha256": source_entry["sha256"],
               "step80_training_seal_sha256": bindings["training_seal_sha256"],
               "epoch3_schedule_sha256": hashlib.sha256(schedule_bytes).hexdigest(),
               "calibration_panel_read_for_S80_previously": True,
               "HALF_branch": False, "confirmatory_panel": False}
    checkpoint_path = seed_dir / "step-120-1x.pt"
    checkpoint_sha = runner.save_payload(checkpoint_path, payload)
    receipt = {"status": "R3_CALIBRATION_STEP120_1X_COMPLETE", "seed": seed,
               "start_step": 80, "end_step": 120, "steps": 40,
               "auxiliary_multiplier": 1.0,
               "step80_checkpoint_sha256": source_entry["sha256"],
               "final_checkpoint_sha256": checkpoint_sha,
               "final_head_sha256": payload["head_sha256"],
               "final_optimizer_sha256": payload["optimizer_sha256"],
               "final_rng_tree_sha256": runner.tree_sha(payload["rng_state"]),
               "schedule_sha256": payload["epoch3_schedule_sha256"],
               "telemetry_sha256": sha_file(telemetry_path),
               "HALF_branch": False, "confirmatory_panel": False}
    write_json(seed_dir / "continuation-receipt.json", receipt)
    del head, optimizer, states, candidates
    torch.cuda.empty_cache()
    return receipt


def evaluate_s120(bindings: dict[str, Any], runner: Any, summary: Any,
                  probe: Any, out_dir: Path) -> dict[str, Any]:
    panel_path = PANEL / "calibration-panel-views.jsonl"
    candidate_path = PANEL / "candidate-texts.jsonl"
    rows = summary.parse_panel_without_target(panel_path)
    candidates = [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    candidate_index = {row["candidate_semantic_id"]: index for index, row in enumerate(candidates)}
    panel_features, candidate_features, feature_binding = summary.verify_feature_cache()
    if len(rows) != 4_000 or len(candidate_index) != 16:
        raise RuntimeError("target-free calibration panel schema/count mismatch")
    grouped: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        entry = grouped.setdefault(row["neighborhood_id"], {
            "family": row["family_slug"], "direction": row["direction"], "views": {}})
        if row["family_slug"] != entry["family"] or row["direction"] != entry["direction"]:
            raise RuntimeError("calibration neighborhood metadata disagreement")
        if row["view"] in entry["views"]:
            raise RuntimeError("duplicate calibration panel view")
        entry["views"][row["view"]] = (index, row)
    if len(grouped) != 2_000 or any(set(row["views"]) != {"anchor", "fact_flip"} for row in grouped.values()):
        raise RuntimeError("target-free calibration panel pair join failed")
    for family in FAMILIES:
        for direction in DIRECTIONS:
            count = sum(row["family"] == family and row["direction"] == direction for row in grouped.values())
            if count != 250:
                raise RuntimeError(f"calibration family/polarity cell count mismatch: {family}/{direction}/{count}")

    result_rows = []
    checkpoint_entries = {row["path"]: row for row in bindings["continuation_entries"]}
    with torch.inference_mode():
        for seed in bindings["seeds"]:
            checkpoint_rel = f"seed-{seed}/step-120-1x.pt"
            path = OUTPUT / checkpoint_rel
            if checkpoint_rel not in checkpoint_entries or sha_file(path) != checkpoint_entries[checkpoint_rel]["sha256"]:
                raise RuntimeError(f"step-120 checkpoint is not sealed: {seed}")
            payload = torch.load(path, map_location="cpu", weights_only=False)
            if payload.get("global_step") != 120 or payload.get("auxiliary_multiplier") != 1.0 \
                    or payload.get("HALF_branch") is not False:
                raise RuntimeError(f"unexpected calibration checkpoint identity: {seed}")
            head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
            head.load_state_dict(payload["head_state"], strict=True)
            head.eval()
            cell_values: dict[tuple[str, str], list[float]] = {
                (family, direction): [] for family in FAMILIES for direction in DIRECTIONS}
            groups = list(grouped.items())
            for start in range(0, len(groups), 128):
                chunk = groups[start:start + 128]
                state_indices: list[int] = []
                candidate_rows: list[list[int]] = []
                role_slots: list[tuple[int, int]] = []
                for _identity, item in chunk:
                    anchor_idx, anchor = item["views"]["anchor"]
                    fact_idx, fact = item["views"]["fact_flip"]
                    ids = anchor["candidate_semantic_ids"]
                    if ids != fact["candidate_semantic_ids"]:
                        raise RuntimeError("candidate order differs across calibration views")
                    old_id, new_id = anchor["old_semantic_id"], anchor["new_semantic_id"]
                    if old_id not in ids or new_id not in ids:
                        raise RuntimeError("semantic role identity absent from exact candidate set")
                    slot_pair = (ids.index(old_id), ids.index(new_id))
                    feature_indices = [candidate_index[value] for value in ids]
                    state_indices.extend((anchor_idx, fact_idx))
                    candidate_rows.extend((feature_indices, feature_indices))
                    role_slots.append(slot_pair)
                state_tensor = panel_features[torch.tensor(state_indices, dtype=torch.long)].to("cuda")
                candidate_tensor = candidate_features[torch.tensor(candidate_rows, dtype=torch.long)].to("cuda")
                logits = head(state_tensor, candidate_tensor)
                for local, (_identity, item) in enumerate(chunk):
                    old_slot, new_slot = role_slots[local]
                    anchor_gap = logits[2 * local, new_slot] - logits[2 * local, old_slot]
                    fact_gap = logits[2 * local + 1, new_slot] - logits[2 * local + 1, old_slot]
                    cell_values[(item["family"], item["direction"])].append(float(fact_gap - anchor_gap))
            cells = {}
            cell_means, cell_var_terms = [], []
            for family in FAMILIES:
                for direction in DIRECTIONS:
                    values = np.asarray(cell_values[(family, direction)], dtype=np.float64)
                    if values.size != 250 or not np.isfinite(values).all():
                        raise RuntimeError(f"invalid S120 cell values: {seed}/{family}/{direction}")
                    mean = float(values.mean())
                    variance = float(values.var(ddof=1))
                    cells[f"{family}/{direction}"] = {
                        "count": int(values.size), "mean_S120_1x": mean,
                        "within_cell_sample_variance": variance,
                        "within_cell_mean_se": math.sqrt(variance / values.size)}
                    cell_means.append(mean)
                    cell_var_terms.append(variance / values.size)
            overall = float(np.mean(cell_means))
            measurement_se = math.sqrt(sum(cell_var_terms)) / len(cell_var_terms)
            result_rows.append({"seed": seed, "S80": bindings["s80_histories"][seed]["S80_role_oriented"],
                                "S120_1X": overall, "within_history_measurement_se": measurement_se,
                                "family_direction_cells": cells,
                                "step120_checkpoint_sha256": checkpoint_entries[checkpoint_rel]["sha256"]})
            del head, state_tensor, candidate_tensor, logits
            torch.cuda.empty_cache()

    s80_values = np.asarray([row["S80"] for row in result_rows], dtype=np.float64)
    s120_values = np.asarray([row["S120_1X"] for row in result_rows], dtype=np.float64)
    if not np.isfinite(s80_values).all() or not np.isfinite(s120_values).all():
        raise RuntimeError("nonfinite S80/S120 summary inputs")
    slope = float(np.polyfit(s80_values, s120_values, 1)[0])
    correlation = float(np.corrcoef(s80_values, s120_values)[0, 1])
    floors = {}
    for floor in FLOORS:
        eligible = int(np.count_nonzero(s120_values >= floor))
        p_hat = eligible / len(s120_values)
        floors[str(floor)] = {"step120_1x_baseline_eligible_count": eligible,
                              "calibration_history_count": len(s120_values),
                              "empirical_fraction": p_hat,
                              "expected_count_in_192_at_empirical_fraction": 192 * p_hat,
                              "plug_in_probability_at_least_173_of_192": binomial_tail(192, 173, p_hat),
                              "is_necessary_not_sufficient_for_R_coverage": True}
    s80_seal = runner.read_json(TRAINING / "pretreatment-s80-calibration-v02-seal.json")
    summary_out = {
        "status": "R3_CALIBRATION_STEP120_1X_RATIO_FLOOR_FEASIBILITY_COMPLETE",
        "scope": "48 excluded calibration histories; 1x-only continuation; calibration panel only; no HALF branch or contrast",
        "definition": "equal-weight mean over four families x two polarities of (new-old logit gap on fact minus anchor), with semantic-role orientation",
        "history_count": len(result_rows), "histories": result_rows,
        "distribution": distribution(s120_values),
        "measurement_precision": {"median_within_history_se": float(np.median([r["within_history_measurement_se"] for r in result_rows])),
                                  "maximum_within_history_se": float(max(r["within_history_measurement_se"] for r in result_rows))},
        "floor_feasibility": floors,
        "floor_rule_note": "S120_1X eligibility is necessary but not sufficient for R eligibility; HALF branch eligibility is unobserved by design.",
        "D_weak_baseline_note": "If the calibration median S120_1X is below the eventual frozen measurement floor, a D interval containing zero must be described as insufficient baseline discrimination to assess attenuation, not as evidence of no effect.",
        "S80_to_S120_1X_descriptive": {"pearson_r": correlation, "ols_slope_raw_scale": slope,
                                         "no_treatment_moderation_or_half_contrast": True},
        "bindings": {"step80_training_seal_sha256": bindings["training_seal_sha256"],
                     "step80_tree_root_sha256": bindings["training_tree_root_sha256"],
                     "preflight_root_sha256": bindings["preflight_seal_sha256"],
                     "feature_root_sha256": feature_binding["feature_root_sha256"],
                     "panel_sha256": EXPECTED_PANEL_SHA,
                     "candidate_manifest_sha256": EXPECTED_CANDIDATE_SHA,
                     "step80_summary_sha256": EXPECTED_S80_SHA,
                     "step120_training_root_sha256": bindings["continuation_root_sha256"],
                     "step120_training_seal_sha256": bindings["continuation_seal_sha256"],
                     "step120_analysis_source_sha256": sha_file(Path(__file__).resolve())},
        "target_fields_read": False, "predictions_saved": False,
        "half_branch": False, "confirmatory_panel": False,
        "confirmatory_training_or_evaluation": False,
    }
    write_json(out_dir / "step120-s1x-calibration.json", summary_out)
    return summary_out


def binomial_tail(n: int, k: int, p: float) -> float:
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    terms = [math.lgamma(n + 1) - math.lgamma(j + 1) - math.lgamma(n - j + 1)
             + j * math.log(p) + (n - j) * math.log1p(-p) for j in range(k, n + 1)]
    maximum = max(terms)
    return min(1.0, math.exp(maximum) * sum(math.exp(value - maximum) for value in terms))


def distribution(values: np.ndarray) -> dict[str, float]:
    quantiles = np.quantile(values, [0, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 1], method="linear")
    names = ("min", "q05", "q10", "q25", "median", "q75", "q90", "q95", "max")
    return {name: float(value) for name, value in zip(names, quantiles, strict=True)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    runner = load_module(RUNNER_PATH, "r3_s120_calibration_runner")
    replay = load_module(REPLAY_PATH, "r3_s120_calibration_replay")
    summary = load_module(SUMMARY_PATH, "r3_s120_calibration_summary")
    bindings = bind_inputs(runner, replay, summary)
    if args.preflight:
        print(json.dumps({"status": "R3_CALIBRATION_S120_PREFLIGHT_PASS",
                          "history_count": len(bindings["seeds"]),
                          "training_seal_sha256": bindings["training_seal_sha256"],
                          "training_tree_root_sha256": bindings["training_tree_root_sha256"],
                          "feature_root_sha256": bindings["feature_root_sha256"],
                          "replay_root_sha256": bindings["replay_root_sha256"],
                          "output_namespace_absent": not OUTPUT.exists(),
                          "half_branch": False, "confirmatory_panel": False}, indent=2))
        return 0
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = False
    if torch.are_deterministic_algorithms_enabled():
        raise RuntimeError("calibration runner requires the recorded default deterministic-algorithm mode")
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json(OUTPUT / "measurement-contract.json", {
        "status": "R3_CALIBRATION_S120_1X_MEASUREMENT_CONTRACT",
        "scope": "complete 1x continuation of existing 48 step-80 calibration histories; no HALF branch",
        "checkpoint": 120, "auxiliary_multiplier": 1.0,
        "panel": "previously opened calibration panel only",
        "metric": "equal-weight mean across 4 families x 2 polarity cells of fact-minus-anchor new-vs-old logit-gap change",
        "ratio_floor_sensitivities": list(FLOORS),
        "required_ratio_coverage_count_for_future_192": RATIO_COVERAGE_COUNT,
        "confirmatory_panel_or_metrics": False})
    write_json(OUTPUT / "input-binding.json", {
        "status": "R3_CALIBRATION_S120_INPUTS_BOUND",
        "training_seal_sha256": bindings["training_seal_sha256"],
        "training_tree_root_sha256": bindings["training_tree_root_sha256"],
        "preflight_seal_sha256": bindings["preflight_seal_sha256"],
        "preflight_manifest_sha256": bindings["preflight_manifest_sha256"],
        "feature_seal_sha256": bindings["feature_seal_sha256"],
        "feature_root_sha256": bindings["feature_root_sha256"],
        "panel_sha256": bindings["panel_sha256"],
        "candidate_manifest_sha256": bindings["candidate_manifest_sha256"],
        "s80_summary_sha256": bindings["s80_summary_sha256"],
        "continuation_replay_root_sha256": bindings["replay_root_sha256"],
        "seed_count": len(bindings["seeds"]), "seeds_sha256": hashlib.sha256(
            json.dumps(bindings["seeds"], separators=(",", ":")).encode()).hexdigest(),
        "half_branch": False, "confirmatory_panel": False})
    probe = load_module(PROBE_PATH, "r3_s120_calibration_probe")
    batcher = load_module(BATCHER_PATH, "r3_s120_calibration_batcher")
    objective = load_module(OBJECTIVE_PATH, "r3_s120_calibration_objective")
    receipts = []
    started = time.perf_counter()
    try:
        for index, seed in enumerate(bindings["seeds"], start=1):
            receipt = continue_one(seed, bindings, runner, replay, probe, batcher, objective, OUTPUT)
            receipts.append(receipt)
            print(json.dumps({"event": "calibration_1x_step120_complete", "index": index,
                              "total": 48, "seed": seed,
                              "checkpoint_sha256": receipt["final_checkpoint_sha256"]}), flush=True)
        if len(receipts) != 48:
            raise RuntimeError("incomplete 48-history calibration continuation")
        files = []
        for path in sorted(OUTPUT.rglob("*")):
            if path.is_file() and path.name not in {"step120-training-seal.json", "step120-root-seal.json"}:
                files.append({"path": path.relative_to(OUTPUT).as_posix(), "bytes": path.stat().st_size,
                              "sha256": sha_file(path)})
        training_files = [row for row in files if row["path"].endswith(("step-120-1x.pt", "continuation-telemetry.jsonl", "continuation-receipt.json"))]
        training_seal = {"status": "R3_ALL_48_CALIBRATION_1X_STEP120_CHECKPOINTS_SEALED_BEFORE_PANEL_SUMMARY",
                         "history_count": 48, "checkpoint_count": 48,
                         "entries": training_files, "entry_count": len(training_files),
                         "entries_root_sha256": tree_root(training_files),
                         "step80_training_seal_sha256": bindings["training_seal_sha256"],
                         "half_branch": False, "confirmatory_panel": False,
                         "evaluation_feedback_during_training": False}
        write_json(OUTPUT / "step120-training-seal.json", training_seal)
        bindings["continuation_entries"] = training_files
        bindings["continuation_root_sha256"] = training_seal["entries_root_sha256"]
        bindings["continuation_seal_sha256"] = sha_file(OUTPUT / "step120-training-seal.json")
        result = evaluate_s120(bindings, runner, summary, probe, OUTPUT)
        result_path = OUTPUT / "step120-s1x-calibration.json"
        files = []
        for path in sorted(OUTPUT.rglob("*")):
            if path.is_file() and path.name != "step120-root-seal.json":
                files.append({"path": path.relative_to(OUTPUT).as_posix(), "bytes": path.stat().st_size,
                              "sha256": sha_file(path)})
        root = tree_root(files)
        final_seal = {"status": result["status"], "entries": files,
                      "entry_count": len(files), "entries_root_sha256": root,
                      "result_sha256": sha_file(result_path),
                      "step120_training_seal_sha256": sha_file(OUTPUT / "step120-training-seal.json"),
                      "no_half_branch": True, "confirmatory_panel": False,
                      "target_fields_read": False, "elapsed_seconds": time.perf_counter() - started}
        write_json(OUTPUT / "step120-root-seal.json", final_seal)
        print(json.dumps({"status": result["status"], "history_count": 48,
                          "s120_distribution": result["distribution"],
                          "floor_feasibility": result["floor_feasibility"],
                          "result_sha256": final_seal["result_sha256"],
                          "root_sha256": root}, indent=2), flush=True)
        return 0
    except Exception as error:
        write_json(OUTPUT / "failure-disposition.json", {
            "status": "R3_CALIBRATION_S120_1X_FAILED_CLOSED",
            "error_type": type(error).__name__, "error": str(error),
            "completed_history_count": len(receipts),
            "completed_seeds": [row["seed"] for row in receipts],
            "half_branch": False, "confirmatory_panel": False,
            "failure_source_sha256": sha_file(Path(__file__).resolve())})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
