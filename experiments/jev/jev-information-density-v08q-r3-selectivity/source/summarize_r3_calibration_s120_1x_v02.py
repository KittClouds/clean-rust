"""Target-free S120 measurement over sealed R3 calibration 1x checkpoints."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
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
STEP120_V01 = RUN / "calibration-s1x-terminal-v01"
OUTPUT = RUN / "calibration-s1x-terminal-eval-v02"
SUMMARY_PATH = ROOT / "experiments/jev-information-density-v08q-r3-selectivity/source/summarize_r3_pretreatment_s80_v01.py"
PROBE_PATH = ROOT / "experiments/jev-frozen-readout-v01/probe.py"

EXPECTED_TRAINING_SEAL_SHA = "5521b0a82b231dbe47e7b9f2235a8758f4ef29dbf4945c56ac6512e134c9150f"
EXPECTED_STEP120_TREE_ROOT = "2ec37b7f57a039025f62705c9342993d0b61ed7e4c6c76e36422ed5d3fc77caf"
EXPECTED_PANEL_SHA = "6b813445b14bb8494962b2cc9b0cc8a229244177083c3a605d21ef4f880dbaef"
EXPECTED_CANDIDATE_SHA = "cc45c81e2b6d70d222170872e9ddd96e1b48dfe90d26e588d319a34a7f101b33"
EXPECTED_FEATURE_ROOT = "bd040d4b22eb3ba4098a593746cf8dcab9409e82b2359ddc185723c657db9e36"
EXPECTED_S80_SHA = "841a11b9f8d79e1a0353a38fb1fa38cb5b1a575039b952404a176679ef9f1e78"
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
DIRECTIONS = ("high_to_low", "low_to_high")
FLOORS = (0.01, 0.004)
REQUIRED_COVERAGE = math.ceil(0.90 * 192)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def tree_root(entries: list[dict[str, Any]]) -> str:
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    return hashlib.sha256(body.encode()).hexdigest()


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def binomial_tail(n: int, k: int, p: float) -> float:
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    logs = [math.lgamma(n + 1) - math.lgamma(j + 1) - math.lgamma(n - j + 1)
            + j * math.log(p) + (n - j) * math.log1p(-p) for j in range(k, n + 1)]
    high = max(logs)
    return min(1.0, math.exp(high) * sum(math.exp(value - high) for value in logs))


def wilson_interval(successes: int, total: int) -> list[float]:
    z = 1.959963984540054
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [max(0.0, center - radius), min(1.0, center + radius)]


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing existing corrected-evaluation namespace: {OUTPUT}")
    if sha_file(TRAINING / "step80-training-seal.json") != EXPECTED_TRAINING_SEAL_SHA:
        raise RuntimeError("step-80 training seal identity mismatch")
    if sha_file(PANEL / "calibration-panel-views.jsonl") != EXPECTED_PANEL_SHA \
            or sha_file(PANEL / "candidate-texts.jsonl") != EXPECTED_CANDIDATE_SHA:
        raise RuntimeError("calibration panel identity mismatch")
    if sha_file(TRAINING / "pretreatment-s80-calibration-v02.json") != EXPECTED_S80_SHA:
        raise RuntimeError("step-80 summary identity mismatch")
    training_seal = json.loads((STEP120_V01 / "step120-training-seal.json").read_text(encoding="utf-8"))
    training_seal_path = STEP120_V01 / "step120-training-seal.json"
    if sha_file(training_seal_path) != "d35cb9dbe44a6a306bd2d6aed8f80b2ff9109fb2cef77db0482289b29e3e47aa" \
            or training_seal.get("entries_root_sha256") != EXPECTED_STEP120_TREE_ROOT:
        raise RuntimeError("step-120 calibration training seal identity mismatch")
    entries = training_seal["entries"]
    if len(entries) != 144 or tree_root(entries) != EXPECTED_STEP120_TREE_ROOT:
        raise RuntimeError("step-120 calibration artifact tree malformed")
    for row in entries:
        path = STEP120_V01 / row["path"]
        if not path.is_file() or path.stat().st_size != row["bytes"] or sha_file(path) != row["sha256"]:
            raise RuntimeError(f"step-120 calibration artifact drift: {row['path']}")
    checkpoint_entries = {row["path"]: row for row in entries if row["path"].endswith("/step-120-1x.pt")}
    if len(checkpoint_entries) != 48:
        raise RuntimeError("step-120 checkpoint count mismatch")

    summary = load_module(SUMMARY_PATH, "r3_s120_eval_summary")
    panel_features, candidate_features, feature_binding = summary.verify_feature_cache()
    feature_seal = summary.read_json(FEATURES / "feature-cache-seal-v01.json")
    feature_entries = sorted(feature_seal["entries"], key=lambda row: row["path"])
    if tree_root(feature_entries) != EXPECTED_FEATURE_ROOT:
        raise RuntimeError("calibration feature cache root mismatch")
    panel_rows = summary.parse_panel_without_target(PANEL / "calibration-panel-views.jsonl")
    candidates = [json.loads(line) for line in (PANEL / "candidate-texts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    candidate_index = {row["candidate_semantic_id"]: index for index, row in enumerate(candidates)}
    if len(panel_rows) != 4_000 or len(candidates) != 16 or len(candidate_index) != 16:
        raise RuntimeError("target-free calibration input count mismatch")
    grouped: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(panel_rows):
        entry = grouped.setdefault(row["neighborhood_id"], {
            "family": row["family_slug"], "direction": row["direction"], "views": {}})
        if (entry["family"], entry["direction"]) != (row["family_slug"], row["direction"]):
            raise RuntimeError("calibration neighborhood metadata mismatch")
        if row["view"] in entry["views"]:
            raise RuntimeError("duplicate calibration view")
        entry["views"][row["view"]] = (index, row)
    if len(grouped) != 2_000 or any(set(item["views"]) != {"anchor", "fact"} for item in grouped.values()):
        raise RuntimeError("corrected target-free calibration view join failed")
    for family in FAMILIES:
        for direction in DIRECTIONS:
            count = sum(item["family"] == family and item["direction"] == direction for item in grouped.values())
            if count != 250:
                raise RuntimeError(f"family-polarity cell support mismatch: {family}/{direction}={count}")

    s80_data = summary.read_json(TRAINING / "pretreatment-s80-calibration-v02.json")
    s80_by_seed = {int(row["seed"]): row for row in s80_data["histories"]}
    preflight = json.loads((PREFLIGHT / "calibration-schedule-manifest.json").read_text(encoding="utf-8"))
    seeds = preflight["seed_derivation"]["seeds"]
    if len(seeds) != 48 or set(checkpoint_entries) != {f"seed-{seed}/step-120-1x.pt" for seed in seeds}:
        raise RuntimeError("calibration seed/checkpoint identity mismatch")

    probe = load_module(PROBE_PATH, "r3_s120_eval_probe")
    if torch.__version__ != "2.11.0+cu128" or not torch.cuda.is_available() \
            or torch.version.cuda != "12.8" or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise RuntimeError("target-free calibration evaluation runtime mismatch")
    result_rows = []
    for seed_index, seed in enumerate(seeds, start=1):
        checkpoint_rel = f"seed-{seed}/step-120-1x.pt"
        checkpoint_path = STEP120_V01 / checkpoint_rel
        payload = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        if payload.get("seed") != seed or payload.get("global_step") != 120 \
                or payload.get("auxiliary_multiplier") != 1.0 or payload.get("HALF_branch") is not False:
            raise RuntimeError(f"step-120 checkpoint content mismatch: {seed}")
        head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
        head.load_state_dict(payload["head_state"], strict=True)
        head.eval()
        cell_values: dict[tuple[str, str], list[float]] = {
            (family, direction): [] for family in FAMILIES for direction in DIRECTIONS}
        groups = list(grouped.items())
        with torch.inference_mode():
            for start in range(0, len(groups), 128):
                chunk = groups[start:start + 128]
                state_indices: list[int] = []
                candidate_rows: list[list[int]] = []
                role_slots: list[tuple[int, int]] = []
                for _identity, item in chunk:
                    anchor_idx, anchor = item["views"]["anchor"]
                    fact_idx, fact = item["views"]["fact"]
                    ids = anchor["candidate_semantic_ids"]
                    if ids != fact["candidate_semantic_ids"]:
                        raise RuntimeError("candidate order mismatch across anchor/fact views")
                    old_id, new_id = anchor["old_semantic_id"], anchor["new_semantic_id"]
                    if old_id not in ids or new_id not in ids:
                        raise RuntimeError("semantic role absent from exact candidate order")
                    role_slots.append((ids.index(old_id), ids.index(new_id)))
                    feature_indices = [candidate_index[candidate_id] for candidate_id in ids]
                    state_indices.extend((anchor_idx, fact_idx))
                    candidate_rows.extend((feature_indices, feature_indices))
                state_tensor = panel_features[torch.tensor(state_indices, dtype=torch.long)].to("cuda")
                candidate_tensor = candidate_features[torch.tensor(candidate_rows, dtype=torch.long)].to("cuda")
                logits = head(state_tensor, candidate_tensor)
                for local, (_identity, item) in enumerate(chunk):
                    old_slot, new_slot = role_slots[local]
                    anchor_gap = logits[2 * local, new_slot] - logits[2 * local, old_slot]
                    fact_gap = logits[2 * local + 1, new_slot] - logits[2 * local + 1, old_slot]
                    cell_values[(item["family"], item["direction"])].append(float(fact_gap - anchor_gap))
        cells, means, variance_terms = {}, [], []
        for family in FAMILIES:
            for direction in DIRECTIONS:
                values = np.asarray(cell_values[(family, direction)], dtype=np.float64)
                if values.size != 250 or not np.isfinite(values).all():
                    raise RuntimeError(f"nonfinite or incomplete score cell: {seed}/{family}/{direction}")
                mean = float(values.mean())
                variance = float(values.var(ddof=1))
                cells[f"{family}/{direction}"] = {"count": 250, "mean_S120_1x": mean,
                    "sample_variance": variance, "within_cell_mean_se": math.sqrt(variance / 250)}
                means.append(mean)
                variance_terms.append(variance / 250)
        s120 = float(np.mean(means))
        s120_se = math.sqrt(sum(variance_terms)) / len(variance_terms)
        result_rows.append({"seed": seed, "S80": s80_by_seed[seed]["S80_role_oriented"],
                            "S120_1X": s120, "within_history_measurement_se": s120_se,
                            "family_direction_cells": cells,
                            "step120_checkpoint_sha256": checkpoint_entries[checkpoint_rel]["sha256"]})
        del head, state_tensor, candidate_tensor, logits
        torch.cuda.empty_cache()
        print(json.dumps({"event": "target_free_s120_summary_complete", "index": seed_index,
                          "total": 48, "seed": seed}), flush=True)

    values = np.asarray([row["S120_1X"] for row in result_rows], dtype=np.float64)
    s80 = np.asarray([row["S80"] for row in result_rows], dtype=np.float64)
    correlation = float(np.corrcoef(s80, values)[0, 1])
    slope = float(np.polyfit(s80, values, 1)[0])
    floors = {}
    max_measurement_se = float(max(row["within_history_measurement_se"] for row in result_rows))
    for floor in FLOORS:
        eligible = int(np.count_nonzero(values >= floor))
        p_hat = eligible / len(values)
        floors[str(floor)] = {"step120_1x_floor_count": eligible,
            "history_count": len(values), "eligible_fraction": p_hat,
            "wilson_95_interval_for_calibration_fraction": wilson_interval(eligible, len(values)),
            "projected_expected_count_of_192": p_hat * 192,
            "plug_in_probability_of_at_least_173_of_192_baseline_eligible": binomial_tail(192, 173, p_hat),
            "floor_in_units_of_maximum_within_history_se": floor / max_measurement_se,
            "necessary_not_sufficient_for_half_branch_ratio_coverage": True}
    fail_attempt = STEP120_V01 / "failure-disposition.json"
    OUTPUT.mkdir(parents=True, exist_ok=False)
    analysis_contract = {"status": "R3_CALIBRATION_S120_TARGET_FREE_SUMMARY_V02",
        "view_schema_correction": "panel uses view='fact'; v01 expected 'fact_flip' and failed before head load",
        "estimand": "equal-weight mean of (new-old logit gap)_fact - (new-old logit gap)_anchor over four families x two polarities",
        "new_old_orientation": "semantic transition roles, not output position or pole",
        "panel": "calibration panel previously used for S80; no confirmatory panel",
        "input_seal_sha256": sha_file(STEP120_V01 / "step120-training-seal.json"),
        "analysis_source_sha256": sha_file(Path(__file__).resolve()),
        "target_fields_read": False, "predictions_saved": False, "half_branch": False}
    write_json(OUTPUT / "analysis-contract.json", analysis_contract)
    result = {"status": "R3_CALIBRATION_STEP120_1X_RATIO_FLOOR_FEASIBILITY_COMPLETE",
        "scope": "48 excluded calibration histories, 1x-only continuations, calibration panel; no HALF contrast",
        "history_count": 48, "histories": result_rows,
        "S120_1X_distribution": {key: float(value) for key, value in zip(
            ("min", "q05", "q10", "q25", "median", "q75", "q90", "q95", "max"),
            np.quantile(values, [0, .05, .1, .25, .5, .75, .9, .95, 1], method="linear"), strict=True)},
        "measurement_precision": {"median_within_history_se": float(np.median([row["within_history_measurement_se"] for row in result_rows])),
            "maximum_within_history_se": float(max(row["within_history_measurement_se"] for row in result_rows))},
        "floor_feasibility": floors,
        "S80_to_S120_1X_descriptive_only": {"pearson_r": correlation, "ols_slope": slope},
        "interpretation": {"D_floor": "If median S120_1X is below the eventual registered floor, a D interval containing zero means insufficient baseline discrimination to assess attenuation, not evidence of no effect.",
            "R_scope": "S120_1X eligibility is necessary but not sufficient; HALF eligibility remains unobserved. Even passing projected baseline support cannot guarantee the 173/192 joint ratio gate."},
        "bindings": {"step80_training_tree_root": "0fd972996eaf33a9199deeec3ebdf3cec63f28ad9393c3b76c020c2be23cde97",
            "step120_training_tree_root": EXPECTED_STEP120_TREE_ROOT,
            "feature_root": EXPECTED_FEATURE_ROOT, "panel_sha256": EXPECTED_PANEL_SHA,
            "candidate_manifest_sha256": EXPECTED_CANDIDATE_SHA, "S80_summary_sha256": EXPECTED_S80_SHA,
            "failed_v01_attempt_sha256": sha_file(fail_attempt) if fail_attempt.is_file() else None},
        "target_fields_read": False, "confirmatory_panel": False, "confirmatory_training_or_evaluation": False}
    result_path = OUTPUT / "step120-s1x-calibration-v02.json"
    write_json(result_path, result)
    files = []
    for path in sorted(OUTPUT.rglob("*")):
        if path.is_file() and path.name != "root-seal.json":
            files.append({"path": path.relative_to(OUTPUT).as_posix(), "bytes": path.stat().st_size,
                          "sha256": sha_file(path)})
    root = tree_root(files)
    seal = {"status": result["status"], "entries": files, "entry_count": len(files),
        "entries_root_sha256": root, "result_sha256": sha_file(result_path),
        "step120_training_seal_sha256": sha_file(STEP120_V01 / "step120-training-seal.json"),
        "target_fields_read": False, "half_branch": False, "confirmatory_panel": False}
    write_json(OUTPUT / "root-seal.json", seal)
    print(json.dumps({"status": result["status"], "S120_1X_distribution": result["S120_1X_distribution"],
        "measurement_precision": result["measurement_precision"], "floor_feasibility": floors,
        "S80_to_S120_1X_descriptive_only": result["S80_to_S120_1X_descriptive_only"],
        "result_sha256": sha_file(result_path), "root_sha256": root}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
