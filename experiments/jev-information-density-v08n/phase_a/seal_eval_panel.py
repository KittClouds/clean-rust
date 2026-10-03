"""Independently validate and seal the held-out matched-neutral panel."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "experiments/jev-information-density-v08n/eval-panel-v01-contract.json"
ROLES = ["anchor", "fact_flip", "sham", *[f"neutral_{i}" for i in range(1, 9)]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def tie_hash(anchor_id: str, role: str) -> str:
    return hashlib.sha256(f"{anchor_id}|{role}".encode("utf-8")).hexdigest()


def target(row: dict[str, Any]) -> list[float]:
    return [float(item["probability"]) for item in row["gold_targets"][0]["value"]["probabilities"]]


def target_hash(value: list[float]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def map_index(value: list[float]) -> int:
    return max(range(len(value)), key=lambda index: (value[index], -index))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--matched", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(CONTRACT)
    semantic_receipt = read_json(args.panel / "semantic-scope-receipt.json")
    feature_receipt = read_json(args.features / "heldout-feature-cache-receipt.json")
    matched_receipt = read_json(args.matched / "matched-panel-receipt.json")
    selected = read_jsonl(args.matched / "selected-heldout-matched-neutral.jsonl")
    manifest = read_jsonl(args.matched / "heldout-matched-panel-manifest.jsonl")
    scope = read_jsonl(args.panel / "heldout-feature-scope.jsonl")
    features = torch.load(args.features / "heldout-features.pt", map_location="cpu", weights_only=True)["features"].to(dtype=torch.float64)
    certificates = {row["anchor_id"]: row for row in read_jsonl(args.source_run / "eval-contrast-certificates.jsonl")}
    episodes = {row["episode_id"]: row for row in read_jsonl(args.source_run / "eval-exact-world-episodes.jsonl")}

    failures: list[str] = []
    if semantic_receipt["status"] != "V08N_HELDOUT_PANEL_SEMANTIC_SCOPE_PASS":
        failures.append("semantic scope status")
    if feature_receipt["status"] != "V08N_HELDOUT_FEATURE_CACHE_SEALED_FROZEN_BACKBONE_ONLY":
        failures.append("feature cache status")
    if matched_receipt["status"] != "V08N_HELDOUT_MATCHED_PANEL_RADIUS_GATE_PASS":
        failures.append("matched panel gate status")
    if len(selected) != 2_000 or len(manifest) != 2_000 or len(scope) != 22_000:
        failures.append("panel counts")
    if tuple(features.shape) != (22_000, 2_048):
        failures.append("feature shape")
    if len({row["neighborhood_id"] for row in selected}) != 2_000:
        failures.append("duplicate selected neighborhoods")
    if {row["neighborhood_id"] for row in selected} != {row["neighborhood_id"] for row in manifest}:
        failures.append("selected/manifest identity mismatch")

    scope_by_neighborhood: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scope:
        scope_by_neighborhood[row["neighborhood_id"]].append(row)
    selected_by_id = {row["neighborhood_id"]: row for row in selected}
    order = sorted(scope_by_neighborhood)
    if len(order) != 2_000:
        failures.append("scope neighborhood count")
    relative: list[float] = []
    absolute: list[float] = []
    family_relative: dict[str, list[float]] = defaultdict(list)
    for index, anchor_id in enumerate(order):
        rows = sorted(scope_by_neighborhood[anchor_id], key=lambda row: row["index"])
        if [row["role"] for row in rows] != ROLES:
            failures.append(f"role order:{anchor_id}")
            continue
        selected_row = selected_by_id.get(anchor_id)
        if selected_row is None:
            failures.append(f"missing selection:{anchor_id}")
            continue
        anchor_target = rows[0]["target"]
        if target_hash(anchor_target) != selected_row["target_hash"]:
            failures.append(f"target hash:{anchor_id}")
        if rows[0]["partition"] != "eval" or any(row["partition"] != "eval" for row in rows):
            failures.append(f"partition:{anchor_id}")
        certificate = certificates.get(anchor_id)
        if certificate is None or certificate.get("partition") != "eval":
            failures.append(f"certificate scope:{anchor_id}")
            continue
        episode_ids = certificate["episode_ids"]
        selected_neutral_id = selected_row["matched_neutral_episode_id"]
        if selected_neutral_id not in episode_ids["neutrals"]:
            failures.append(f"neutral identity:{anchor_id}")
        anchor_episode = episodes.get(episode_ids["anchor"])
        fact_episode = episodes.get(episode_ids["fact_flip"])
        sham_episode = episodes.get(episode_ids["sham"])
        neutral_episode = episodes.get(selected_neutral_id)
        if any(item is None for item in [anchor_episode, fact_episode, sham_episode, neutral_episode]):
            failures.append(f"source episode:{anchor_id}")
            continue
        anchor_value = target(anchor_episode)
        if max(abs(a - b) for a, b in zip(anchor_value, target(sham_episode))) > 1e-12 or max(abs(a - b) for a, b in zip(anchor_value, target(neutral_episode))) > 1e-12:
            failures.append(f"target invariance:{anchor_id}")
        if map_index(anchor_value) == map_index(target(fact_episode)):
            failures.append(f"fact MAP transition:{anchor_id}")
        anchor_feature = features[index * 11]
        sham_feature = features[index * 11 + 2]
        neutral_index = ROLES.index(next(row["role"] for row in rows if row["episode_id"] == selected_neutral_id))
        neutral_feature = features[index * 11 + neutral_index]
        sham_radius = float(torch.linalg.vector_norm(sham_feature - anchor_feature))
        neutral_radius = float(torch.linalg.vector_norm(neutral_feature - anchor_feature))
        abs_error = abs(neutral_radius - sham_radius)
        rel_error = abs_error / max(sham_radius, torch.finfo(torch.float64).tiny)
        if abs_error != selected_row["absolute_radius_error"] or rel_error != selected_row["relative_radius_error"]:
            failures.append(f"radius bookkeeping:{anchor_id}")
        candidates = []
        for candidate_index in range(1, 9):
            radius = float(torch.linalg.vector_norm(features[index * 11 + 2 + candidate_index] - anchor_feature))
            candidates.append((abs(radius - sham_radius), tie_hash(anchor_id, f"neutral_{candidate_index}"), candidate_index))
        if min(candidates, key=lambda item: (item[0], item[1]))[2] != neutral_index - 2:
            failures.append(f"radius-only argmin:{anchor_id}")
        relative.append(rel_error)
        absolute.append(abs_error)
        family_relative[rows[0]["family_id"]].append(rel_error)

    relative_tensor = torch.tensor(relative, dtype=torch.float64)
    absolute_tensor = torch.tensor(absolute, dtype=torch.float64)
    mean_relative = float(relative_tensor.mean())
    p95_absolute = float(torch.quantile(absolute_tensor, torch.tensor(0.95, dtype=torch.float64)))
    family_means = {family: sum(values) / len(values) for family, values in sorted(family_relative.items())}
    gates = contract["representation"]["gates"]
    if mean_relative > gates["mean_relative_radius_difference_max"] or p95_absolute > gates["p95_absolute_radius_difference_max"] or any(value > gates["per_family_mean_relative_difference_max"] for value in family_means.values()):
        failures.append("radius gates")
    if failures:
        raise RuntimeError("held-out panel independent seal failed: " + "; ".join(failures[:12]))

    args.output.mkdir(parents=True, exist_ok=False)
    firewall = {
        "status": "V08N_HELDOUT_PANEL_FIREWALL_LOCKED",
        "identity": contract["identity"],
        "panel_manifest_sha256": sha256_file(args.matched / "heldout-matched-panel-manifest.jsonl"),
        "selected_control_sha256": sha256_file(args.matched / "selected-heldout-matched-neutral.jsonl"),
        "body_access_granted": False,
        "training_process_may_read_panel": False,
        "evaluation_process_may_read_panel": False,
        "unlock_requires_explicit_phase_b_authorization": True,
        "newtight_access": False,
        "legacy_evaluation_access": False,
        "phoenix_access": False,
    }
    write_json(args.output / "evaluation-firewall-lock.json", firewall)
    hash_tree = {
        "contract": sha256_file(CONTRACT),
        "semantic_scope_receipt": sha256_file(args.panel / "semantic-scope-receipt.json"),
        "semantic_scope": sha256_file(args.panel / "heldout-feature-scope.jsonl"),
        "feature_cache_receipt": sha256_file(args.features / "heldout-feature-cache-receipt.json"),
        "feature_tensor": sha256_file(args.features / "heldout-features.pt"),
        "matched_receipt": sha256_file(args.matched / "matched-panel-receipt.json"),
        "selected": sha256_file(args.matched / "selected-heldout-matched-neutral.jsonl"),
        "panel_manifest": sha256_file(args.matched / "heldout-matched-panel-manifest.jsonl"),
        "radius_report": sha256_file(args.matched / "radius-gate-report.json"),
        "axis_report": sha256_file(args.matched / "semantic-axis-composition.json"),
        "firewall_lock": sha256_file(args.output / "evaluation-firewall-lock.json"),
    }
    write_json(args.output / "heldout-panel-hash-tree.json", hash_tree)
    validation = {
        "status": "PASS",
        "identity": contract["identity"],
        "independently_recomputed": True,
        "neighborhood_count": 2_000,
        "families": sorted(family_relative),
        "mean_relative_radius_difference": mean_relative,
        "p95_absolute_radius_difference": p95_absolute,
        "per_family_mean_relative_radius_difference": family_means,
        "selection_rule": "radius-only with deterministic hash tie-break",
        "direction_or_cosine_used": False,
        "replacement_selection_after_geometry": False,
        "evaluation_outcomes_used": False,
        "exact_world_invariance_rechecked": True,
        "fact_map_transition_rechecked": True,
        "firewall": firewall["status"],
        "head_load": False,
        "head_training": False,
        "evaluation_inference": False,
        "newtight_access": False,
        "phoenix_access": False,
    }
    write_json(args.output / "independent-validation.json", validation)
    seal = {
        "status": "V08N_HELDOUT_MATCHED_PANEL_SEALED_PHASE_B_GATE_PASS",
        "identity": contract["identity"],
        "contract_sha256": sha256_file(CONTRACT),
        "validation_sha256": sha256_file(args.output / "independent-validation.json"),
        "hash_tree_sha256": sha256_file(args.output / "heldout-panel-hash-tree.json"),
        "firewall_sha256": sha256_file(args.output / "evaluation-firewall-lock.json"),
        "phase_b_ready": True,
        "phase_b_authorized": False,
        "panel_locked": True,
        "luna_status": "NOT_DISPATCHED",
    }
    write_json(args.output / "seal-manifest.json", seal)
    print(json.dumps(seal, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
