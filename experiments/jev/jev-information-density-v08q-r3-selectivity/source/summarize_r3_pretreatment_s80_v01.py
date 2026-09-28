"""Target-field-free S80 calibration from already sealed common-history heads."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02")
TRAINING = RUN / "calibration-training-v02"
PANEL = RUN / "calibration-panel-v02"
FEATURES = RUN / "calibration-features-v01"
PREFLIGHT = RUN / "calibration-preflight-v03"
PROBE = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
EXPECTED_PANEL_SHA = "6b813445b14bb8494962b2cc9b0cc8a229244177083c3a605d21ef4f880dbaef"
EXPECTED_CANDIDATE_SHA = "cc45c81e2b6d70d222170872e9ddd96e1b48dfe90d26e588d319a34a7f101b33"
EXPECTED_PROBE_SHA = "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1"
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
DIRECTIONS = ("high_to_low", "low_to_high")


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tensor_sha(value: torch.Tensor) -> str:
    array = value.detach().cpu().contiguous().numpy()
    return sha_bytes(memoryview(array).cast("B"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load head implementation: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_panel_without_target(path: Path) -> list[dict[str, Any]]:
    """Parse only the JSON prefix preceding the final target field."""
    rows = []
    with path.open("rb") as stream:
        for line_number, raw in enumerate(stream, start=1):
            line = raw.rstrip(b"\r\n")
            marker = b',"target":'
            if not line.endswith(b"]}") or marker not in line:
                raise RuntimeError(f"panel row schema mismatch at line {line_number}")
            prefix = line.rsplit(marker, 1)[0] + b"}"
            row = json.loads(prefix)
            rows.append({key: row[key] for key in (
                "neighborhood_id", "family_slug", "direction", "view", "old_semantic_id",
                "new_semantic_id", "candidate_semantic_ids", "full_rendered_input_hash")})
    return rows


def verify_training_tree() -> dict[str, Any]:
    seal_path = TRAINING / "step80-training-seal.json"
    seal = read_json(seal_path)
    if seal.get("status") != "R3_ALL_48_STEP80_COMMON_HISTORIES_SEALED_BEFORE_CALIBRATION_PANEL_READ":
        raise RuntimeError("R3 step-80 training tree is not sealed")
    body = "".join(f"{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n" for entry in seal["entries"])
    if hashlib.sha256(body.encode()).hexdigest() != seal.get("entries_root_sha256"):
        raise RuntimeError("R3 step-80 training tree root mismatch")
    for entry in seal["entries"]:
        path = TRAINING / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"R3 step-80 training artifact drift: {entry['path']}")
    preflight_manifest = read_json(PREFLIGHT / "calibration-schedule-manifest.json")
    seeds = preflight_manifest["seed_derivation"]["seeds"]
    if len(seeds) != 48 or len(set(seeds)) != 48 or seal.get("checkpoint_count") != 48:
        raise RuntimeError("R3 calibration seed/checkpoint count mismatch")
    return {"training_seal_sha256": sha_file(seal_path), "training_tree_root_sha256": seal["entries_root_sha256"],
            "preflight_manifest_sha256": sha_file(PREFLIGHT / "calibration-schedule-manifest.json"), "seeds": seeds}


def verify_feature_cache() -> tuple[torch.Tensor, torch.Tensor, dict[str, Any]]:
    seal = read_json(FEATURES / "feature-cache-seal-v01.json")
    body = "".join(f"{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n" for entry in sorted(seal["entries"], key=lambda row: row["path"]))
    root = hashlib.sha256(body.encode()).hexdigest()
    if root != seal.get("entries_root_sha256"):
        raise RuntimeError("R3 calibration feature seal root mismatch")
    for entry in seal["entries"]:
        path = FEATURES / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha_file(path) != entry["sha256"]:
            raise RuntimeError(f"R3 calibration feature artifact drift: {entry['path']}")
    panel = torch.load(FEATURES / "calibration-panel-state-features.pt", map_location="cpu", weights_only=True)["features"]
    candidates = torch.load(FEATURES / "calibration-candidate-features.pt", map_location="cpu", weights_only=True)["features"]
    if tuple(panel.shape) != (4_000, 2048) or tuple(candidates.shape) != (16, 2048):
        raise RuntimeError("R3 calibration feature shape mismatch")
    if not torch.isfinite(panel).all() or not torch.isfinite(candidates).all():
        raise RuntimeError("R3 calibration features are nonfinite")
    return panel, candidates, {"feature_seal_sha256": sha_file(FEATURES / "feature-cache-seal-v01.json"), "feature_root_sha256": root}


def main() -> int:
    if (torch.__version__ != "2.11.0+cu128" or not torch.cuda.is_available()
            or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080"):
        raise RuntimeError("R3 S80 calibration runtime mismatch")
    panel_path = PANEL / "calibration-panel-views.jsonl"
    candidate_path = PANEL / "candidate-texts.jsonl"
    if sha_file(panel_path) != EXPECTED_PANEL_SHA or sha_file(candidate_path) != EXPECTED_CANDIDATE_SHA:
        raise RuntimeError("R3 calibration panel input identity mismatch")
    training = verify_training_tree()
    panel_features, candidate_features, feature_binding = verify_feature_cache()
    panel_rows = parse_panel_without_target(panel_path)
    candidates = [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(panel_rows) != 4_000 or len(candidates) != 16:
        raise RuntimeError("R3 S80 panel/candidate row count mismatch")
    candidate_index = {row["candidate_semantic_id"]: i for i, row in enumerate(candidates)}
    if len(candidate_index) != 16:
        raise RuntimeError("R3 S80 candidate IDs not unique")
    grouped: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(panel_rows):
        entry = grouped.setdefault(row["neighborhood_id"], {"family": row["family_slug"], "direction": row["direction"], "views": {}})
        if row["family_slug"] != entry["family"] or row["direction"] != entry["direction"]:
            raise RuntimeError("R3 S80 neighborhood metadata mismatch")
        if row["view"] in entry["views"]:
            raise RuntimeError("R3 S80 duplicate view identity")
        entry["views"][row["view"]] = (index, row)
    if len(grouped) != 2_000 or any(set(item["views"]) != {"anchor", "fact"} for item in grouped.values()):
        raise RuntimeError("R3 S80 neighborhood view join failure")
    s80_records: list[dict[str, Any]] = []
    checkpoint_hashes = []
    probe = load_module(PROBE, "r3_s80_calibration_probe")
    for seed in training["seeds"]:
        checkpoint = TRAINING / f"seed-{seed}" / "step-080.pt"
        payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
        if payload.get("seed") != seed or payload.get("global_step") != 80 or payload.get("auxiliary_multiplier") != 1.0:
            raise RuntimeError(f"R3 S80 checkpoint identity mismatch for seed {seed}")
        if payload.get("evaluation_panel_opened") is not False:
            raise RuntimeError(f"R3 calibration checkpoint claims prior panel access: {seed}")
        head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
        head.load_state_dict(payload["head_state"], strict=True)
        head.eval()
        seed_cells: dict[tuple[str, str], list[float]] = {(family, direction): [] for family in FAMILIES for direction in DIRECTIONS}
        ordered = list(grouped.items())
        with torch.inference_mode():
            for start in range(0, len(ordered), 128):
                chunk = ordered[start : start + 128]
                state_idx: list[int] = []
                candidate_idx: list[list[int]] = []
                role_slots: list[tuple[int, int]] = []
                meta: list[tuple[str, str]] = []
                for _neighborhood, item in chunk:
                    anchor_index, anchor = item["views"]["anchor"]
                    fact_index, fact = item["views"]["fact"]
                    if anchor["candidate_semantic_ids"] != fact["candidate_semantic_ids"]:
                        raise RuntimeError("R3 S80 candidate order differs across paired views")
                    ids = anchor["candidate_semantic_ids"]
                    old_id, new_id = anchor["old_semantic_id"], anchor["new_semantic_id"]
                    if old_id not in ids or new_id not in ids or old_id not in candidate_index or new_id not in candidate_index:
                        raise RuntimeError("R3 S80 semantic role not represented in candidate basis")
                    if fact["old_semantic_id"] != old_id or fact["new_semantic_id"] != new_id:
                        raise RuntimeError("R3 S80 role orientation changed across views")
                    old_slot, new_slot = ids.index(old_id), ids.index(new_id)
                    state_idx.extend((anchor_index, fact_index))
                    candidate_idx.extend(([candidate_index[value] for value in ids], [candidate_index[value] for value in ids]))
                    role_slots.append((old_slot, new_slot))
                    meta.append((item["family"], item["direction"]))
                state = panel_features[torch.tensor(state_idx, dtype=torch.long)].to("cuda")
                candidate = candidate_features[torch.tensor(candidate_idx, dtype=torch.long)].to("cuda")
                logits = head(state, candidate)
                for pair_index, key in enumerate(meta):
                    old_slot, new_slot = role_slots[pair_index]
                    anchor_gap = float(logits[2 * pair_index, new_slot] - logits[2 * pair_index, old_slot])
                    fact_gap = float(logits[2 * pair_index + 1, new_slot] - logits[2 * pair_index + 1, old_slot])
                    seed_cells[key].append(fact_gap - anchor_gap)
        if any(len(values) != 250 for values in seed_cells.values()):
            raise RuntimeError(f"R3 S80 family/direction support mismatch for seed {seed}")
        family_direction_cells = {}
        all_cell_means = []
        all_cell_variances = []
        for family in FAMILIES:
            for direction in DIRECTIONS:
                values = seed_cells[(family, direction)]
                mean = sum(values) / len(values)
                variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
                all_cell_means.append(mean)
                all_cell_variances.append(variance)
                family_direction_cells[f"{family}/{direction}"] = {
                    "count": len(values),
                    "mean_S80": mean,
                    "sample_variance": variance,
                    "within_cell_se": (variance / len(values)) ** 0.5,
                }
        # Equal-weight the eight prospectively balanced family × polarity cells.
        # This keeps the role-oriented moderator invariant to storage order.
        s80 = sum(all_cell_means) / len(all_cell_means)
        s80_se = (sum(value / 250 for value in all_cell_variances) / (8 ** 2)) ** 0.5
        by_family = {}
        for family in FAMILIES:
            high_to_low = family_direction_cells[f"{family}/high_to_low"]["mean_S80"]
            low_to_high = family_direction_cells[f"{family}/low_to_high"]["mean_S80"]
            by_family[family] = {
                "role_mean": (high_to_low + low_to_high) / 2,
                "pole_component": (high_to_low - low_to_high) / 2,
            }
        s80_records.append({
            "seed": seed,
            "step": 80,
            "S80_role_oriented": s80,
            "within_history_measurement_se": s80_se,
            "family_direction_cells": family_direction_cells,
            "family_role_and_pole_components": by_family,
        })
        checkpoint_hashes.append({"seed": seed, "checkpoint_sha256": sha_file(checkpoint)})
        del head, state, candidate, logits, payload
        torch.cuda.empty_cache()

    if len(s80_records) != 48 or [record["seed"] for record in s80_records] != training["seeds"]:
        raise RuntimeError("R3 S80 history identity/count mismatch")
    values = sorted(record["S80_role_oriented"] for record in s80_records)
    measurement_ses = sorted(record["within_history_measurement_se"] for record in s80_records)

    def quantile(sorted_values: list[float], probability: float) -> float:
        position = (len(sorted_values) - 1) * probability
        lower = int(position)
        upper = min(lower + 1, len(sorted_values) - 1)
        fraction = position - lower
        return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction

    result = {
        "status": "R3_PRETREATMENT_S80_CALIBRATION_COMPLETE",
        "scope": "pre-treatment-only calibration; 48 common SHAM-1.0 histories through step 80; no HALF branches, no confirmatory panel, no treatment outcomes",
        "role_oriented_definition": "mean over equally weighted family × polarity cells of (fact [logit_new-logit_old] - anchor [logit_new-logit_old]); new/old are generator semantic roles",
        "panel_sha256": EXPECTED_PANEL_SHA,
        "candidate_text_manifest_sha256": EXPECTED_CANDIDATE_SHA,
        "training_seal_sha256": training["training_seal_sha256"],
        "training_tree_root_sha256": training["training_tree_root_sha256"],
        "feature_seal_sha256": feature_binding["feature_seal_sha256"],
        "feature_root_sha256": feature_binding["feature_root_sha256"],
        "checkpoint_hashes": checkpoint_hashes,
        "history_count": len(s80_records),
        "S80_distribution": {
            "min": values[0],
            "q05_linear": quantile(values, 0.05),
            "q25_linear": quantile(values, 0.25),
            "median_linear": quantile(values, 0.5),
            "q75_linear": quantile(values, 0.75),
            "q95_linear": quantile(values, 0.95),
            "max": values[-1],
            "mean": sum(values) / len(values),
            "sd_sample": (sum((value - sum(values) / len(values)) ** 2 for value in values) / (len(values) - 1)) ** 0.5,
        },
        "measurement_precision": {
            "median_within_history_se": quantile(measurement_ses, 0.5),
            "max_within_history_se": max(measurement_ses),
            "median_between_history_sd_to_median_se_ratio": (
                (sum((value - sum(values) / len(values)) ** 2 for value in values) / (len(values) - 1)) ** 0.5
                / quantile(measurement_ses, 0.5)
            ),
        },
        "family_role_pole_summary": {
            family: {
                "median_role_mean": quantile(sorted(record["family_role_and_pole_components"][family]["role_mean"] for record in s80_records), 0.5),
                "median_pole_component": quantile(sorted(record["family_role_and_pole_components"][family]["pole_component"] for record in s80_records), 0.5),
            }
            for family in FAMILIES
        },
        "histories": s80_records,
        "treatment_outcomes_opened": False,
        "confirmatory_panel_opened": False,
    }
    output = TRAINING / "pretreatment-s80-calibration-v02.json"
    write_json(output, result)
    output_sha = sha_file(output)
    seal = {
        "status": "SEALED_PRETREATMENT_ONLY_R3_S80_CALIBRATION",
        "summary_path": output.name,
        "summary_bytes": output.stat().st_size,
        "summary_sha256": output_sha,
        "summarizer_source_sha256": sha_file(Path(__file__)),
        "training_seal_sha256": training["training_seal_sha256"],
        "panel_sha256": EXPECTED_PANEL_SHA,
        "feature_seal_sha256": feature_binding["feature_seal_sha256"],
        "checkpoint_count": 48,
        "cells_per_history": 8,
        "rows_per_cell": 250,
        "treatment_outcomes_opened": False,
        "confirmatory_panel_opened": False,
    }
    seal["supersedes_artifact_sha256"] = "e606702f18e442944f6ab0376b0ffdfe6eb22f0381a91f1acec62307732cb7ee"
    write_json(TRAINING / "pretreatment-s80-calibration-v02-seal.json", seal)
    print(json.dumps({"status": seal["status"], "summary_sha256": output_sha,
                      "S80_distribution": result["S80_distribution"],
                      "measurement_precision": result["measurement_precision"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
