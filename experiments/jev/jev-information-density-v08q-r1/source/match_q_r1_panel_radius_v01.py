"""Frozen radius-only neutral selection and semantic-ID candidate join for Q-R1."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01")
PANEL_ROOT = RUN_ROOT / "panel"
FEATURE_ROOT = RUN_ROOT / "features"
OUTPUT_ROOT = RUN_ROOT / "matching"
CONTRACT = ROOT / "experiments/jev-information-density-v08q-r1/contracts/q-r1-panel-contract-v01.json"
PANEL_SEAL = RUN_ROOT / "seals/q-r1-panel-construction-seal-v01.json"
PANEL_MANIFEST = RUN_ROOT / "provenance/q-r1-panel-manifest-v01.json"
FEATURE_SEAL = RUN_ROOT / "seals/q-r1-feature-cache-seal-v01.json"
FEATURE_RECEIPT_NAME = "r1-feature-extraction-receipt.json"
FEATURE_KEY = "mean_full@16"
ROLE_ORDER = ["anchor", "fact_flip", "sham", *[f"neutral_{i}" for i in range(1, 9)]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")


def tie_hash(anchor_id: str, role: str) -> str:
    return sha256_bytes(f"{anchor_id}|{role}".encode("utf-8"))


def quantile95(values: list[float]) -> float:
    return float(torch.quantile(torch.tensor(values, dtype=torch.float64), torch.tensor(0.95, dtype=torch.float64)))


def self_test() -> None:
    anchor_id = "known-anchor"
    assert tie_hash(anchor_id, "neutral_1") == tie_hash(anchor_id, "neutral_1")
    assert tie_hash(anchor_id, "neutral_1") != tie_hash(anchor_id, "neutral_2")
    values = [0.0, 1.0, 2.0, 3.0]
    assert abs(quantile95(values) - 2.85) < 1e-12
    assert sha256_bytes(b"x") == "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, default=PANEL_ROOT)
    parser.add_argument("--features", type=Path, default=FEATURE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("Q-R1 matcher self-test PASS")
        return 0
    if args.output.exists():
        raise RuntimeError(f"refusing existing match output: {args.output}")
    contract = read_json(CONTRACT)
    seal = read_json(PANEL_SEAL)
    panel_manifest_sha = seal["panel_manifest_sha256"]
    if seal.get("status") != "Q_R1_PANEL_CONSTRUCTION_SEALED_FEATURE_EXTRACTION_PENDING":
        raise RuntimeError("Q-R1 panel construction seal state mismatch")
    if sha256_file(PANEL_MANIFEST) != panel_manifest_sha:
        raise RuntimeError("Q-R1 panel materialization manifest hash mismatch")
    panel_manifest = read_json(PANEL_MANIFEST)
    feature_receipt = read_json(args.features / FEATURE_RECEIPT_NAME)
    if feature_receipt.get("status") != "Q_R1_FROZEN_PANEL_FEATURE_EXTRACTION_PASS":
        raise RuntimeError("Q-R1 feature extraction receipt is not PASS")
    feature_seal = read_json(FEATURE_SEAL)
    if feature_seal.get("status") != "Q_R1_FEATURE_CACHE_SEALED" or feature_seal.get("feature_receipt_sha256") != sha256_file(args.features / FEATURE_RECEIPT_NAME):
        raise RuntimeError("Q-R1 feature-cache seal state or receipt binding mismatch")
    seal_payload = "".join(
        f"{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n"
        for entry in sorted(feature_seal["entries"], key=lambda item: item["path"])
    )
    if hashlib.sha256(seal_payload.encode("utf-8")).hexdigest() != feature_seal.get("root_sha256"):
        raise RuntimeError("Q-R1 feature-cache seal root mismatch")
    for entry in feature_seal["entries"]:
        feature_path = RUN_ROOT / entry["path"]
        if feature_path.stat().st_size != entry["bytes"] or sha256_file(feature_path) != entry["sha256"]:
            raise RuntimeError(f"Q-R1 feature-cache sealed entry mismatch: {entry['path']}")
    state_path = args.features / "r1-state-features.pt"
    candidate_path = args.features / "r1-candidate-features.pt"
    if feature_receipt["state_tensor"]["sha256"] != sha256_file(state_path) or feature_receipt["candidate_tensor"]["sha256"] != sha256_file(candidate_path):
        raise RuntimeError("Q-R1 feature tensor hash mismatch")
    state_manifest_path = args.features / "r1-state-feature-manifest.jsonl"
    candidate_manifest_path = args.features / "r1-candidate-feature-manifest.jsonl"
    if feature_receipt["state_manifest_sha256"] != sha256_file(state_manifest_path) or feature_receipt["candidate_manifest_sha256"] != sha256_file(candidate_manifest_path):
        raise RuntimeError("Q-R1 per-row feature manifest hash mismatch")
    scope_path = args.panel / "panel-feature-scope.jsonl"
    candidate_text_path = args.panel / "fresh-candidate-text-manifest.jsonl"
    panel_file_bindings = {row["name"]: row["sha256"] for row in panel_manifest["construction_outputs"]}
    panel_file_bindings["fresh-candidate-text-manifest.jsonl"] = panel_manifest["admission"]["candidate_text_manifest_sha256"]
    if panel_file_bindings.get("panel-feature-scope.jsonl") != sha256_file(scope_path) or panel_file_bindings.get("fresh-candidate-text-manifest.jsonl") != sha256_file(candidate_text_path):
        raise RuntimeError("Q-R1 panel feature-scope or candidate text hash differs from its seal")
    scope = read_jsonl(scope_path)
    candidate_texts = read_jsonl(candidate_text_path)
    if len(scope) != 22_000 or len(candidate_texts) != 16:
        raise RuntimeError("Q-R1 panel scope or candidate count mismatch")
    feature_tensor_data = torch.load(state_path, map_location="cpu", weights_only=True)
    features = feature_tensor_data["features"].to(dtype=torch.float64)
    if tuple(features.shape) != (22_000, 2_048) or feature_tensor_data.get("scope_sha256") != sha256_file(scope_path):
        raise RuntimeError("Q-R1 state feature tensor scope/shape mismatch")
    candidate_tensor_data = torch.load(candidate_path, map_location="cpu", weights_only=True)
    candidate_features = candidate_tensor_data["features"]
    if tuple(candidate_features.shape) != (16, 2_048) or candidate_features.dtype != torch.float32:
        raise RuntimeError("Q-R1 candidate feature tensor shape/dtype mismatch")
    candidate_feature_rows = read_jsonl(candidate_manifest_path)
    if candidate_tensor_data.get("candidate_ids") != [row["candidate_semantic_id"] for row in candidate_feature_rows]:
        raise RuntimeError("Q-R1 candidate tensor semantic-ID order differs from its feature manifest")
    if any(sha256_bytes(candidate_features[i].contiguous().numpy().tobytes()) != row["feature_sha256"] for i, row in enumerate(candidate_feature_rows)):
        raise RuntimeError("Q-R1 candidate feature row hash differs from its manifest")
    if not torch.isfinite(features).all() or not torch.isfinite(candidate_features).all():
        raise RuntimeError("Q-R1 feature cache contains non-finite values")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scope:
        groups[row["neighborhood_id"]].append(row)
    if len(groups) != 2_000 or any(len(rows) != 11 for rows in groups.values()):
        raise RuntimeError("Q-R1 feature-scope neighborhood cardinality mismatch")
    for rows in groups.values():
        rows.sort(key=lambda row: row["index"])
        if [row["role"] for row in rows] != ROLE_ORDER:
            raise RuntimeError("Q-R1 feature-scope role ordering mismatch")

    gate_contract = contract["matching"]["radius_gates"]
    selected: list[dict[str, Any]] = []
    relative_errors: list[float] = []
    absolute_errors: list[float] = []
    family_relative: dict[str, list[float]] = defaultdict(list)
    axis_counts: Counter[str] = Counter()
    for anchor_id, rows in sorted(groups.items()):
        indices = [int(row["index"]) for row in rows]
        neighborhood_features = features[indices]
        anchor, sham = neighborhood_features[0], neighborhood_features[2]
        neutrals = neighborhood_features[3:]
        sham_radius = float(torch.linalg.vector_norm(sham - anchor))
        neutral_radii = torch.linalg.vector_norm(neutrals - anchor, dim=1)
        candidates = []
        for index, radius in enumerate(neutral_radii.tolist(), start=1):
            role = f"neutral_{index}"
            error = abs(radius - sham_radius)
            candidates.append((error, tie_hash(anchor_id, role), index, radius))
        error, _, selected_index, neutral_radius = min(candidates, key=lambda value: (value[0], value[1]))
        chosen = rows[2 + selected_index]
        relative = error / max(sham_radius, torch.finfo(torch.float64).tiny)
        family = rows[0]["family_slug"]
        selected.append({
            "neighborhood_id": anchor_id,
            "family_slug": family,
            "family_id": rows[0]["family_id"],
            "template_id": rows[0]["template_id"],
            "anchor_episode_id": rows[0]["episode_id"],
            "fact_episode_id": rows[1]["episode_id"],
            "sham_episode_id": rows[2]["episode_id"],
            "matched_neutral_episode_id": chosen["episode_id"],
            "matched_neutral_role": chosen["role"],
            "sham_radius": sham_radius,
            "matched_neutral_radius": neutral_radius,
            "absolute_radius_error": error,
            "relative_radius_error": relative,
            "selection_rule": "argmin absolute sham-radius mismatch; SHA256(anchor_id|'|'|neutral_role) lexical tie-break",
        })
        relative_errors.append(relative)
        absolute_errors.append(error)
        family_relative[family].append(relative)
        axis_counts[chosen["role"]] += 1

    family_means = {family: sum(values) / len(values) for family, values in sorted(family_relative.items())}
    mean_relative = sum(relative_errors) / len(relative_errors)
    p95_absolute = quantile95(absolute_errors)
    gates = {
        "mean_relative_error_max": float(gate_contract["mean_relative_error_max"]),
        "p95_absolute_error_max": float(gate_contract["p95_absolute_error_max"]),
        "per_family_mean_relative_error_max": float(gate_contract["per_family_mean_relative_error_max"]),
    }
    decisions = {
        "mean_relative_pass": mean_relative <= gates["mean_relative_error_max"],
        "p95_absolute_pass": p95_absolute <= gates["p95_absolute_error_max"],
        "family_pass": all(value <= gates["per_family_mean_relative_error_max"] for value in family_means.values()) and len(family_means) == 4,
    }
    decisions["all_pass"] = all(decisions.values())

    if len(candidate_feature_rows) != 16:
        raise RuntimeError("candidate feature manifest row count mismatch")
    feature_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in candidate_feature_rows:
        key = (row["schema_family_id"], row["candidate_semantic_id"])
        if key in feature_lookup:
            raise RuntimeError("duplicate candidate semantic feature key")
        feature_lookup[key] = row
    candidate_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_texts:
        candidate_groups[row["schema_family_id"]].append(row)
    if len(candidate_groups) != 4 or any(len(rows) != 4 for rows in candidate_groups.values()):
        raise RuntimeError("candidate text catalog is not four schemas by four candidates")
    join_rows = []
    join_errors = []
    for anchor_id, rows in sorted(groups.items()):
        family_slug = rows[0]["family_slug"]
        schema_id = f"jev-v08n-schema:{family_slug}"
        candidates = sorted(candidate_groups.get(schema_id, []), key=lambda row: row["candidate_order"])
        if len(candidates) != 4:
            join_errors.append({"neighborhood_id": anchor_id, "reason": "candidate_schema_missing_or_wrong_count"})
            continue
        resolved = []
        for candidate in candidates:
            key = (schema_id, candidate["candidate_semantic_id"])
            feature = feature_lookup.get(key)
            if feature is None:
                join_errors.append({"neighborhood_id": anchor_id, "candidate_semantic_id_sha256": sha256_bytes(candidate["candidate_semantic_id"].encode()), "reason": "exact_semantic_key_missing"})
                continue
            if feature["input_text_sha256"] != candidate["text_sha256"]:
                join_errors.append({"neighborhood_id": anchor_id, "candidate_semantic_id_sha256": sha256_bytes(candidate["candidate_semantic_id"].encode()), "reason": "candidate_text_identity_mismatch"})
                continue
            resolved.append((candidate, feature))
        if len(resolved) != 4 or len({row[0]["candidate_semantic_id"] for row in resolved}) != 4:
            join_errors.append({"neighborhood_id": anchor_id, "reason": "not_exactly_four_unique_candidates"})
            continue
        for order, (candidate, feature) in enumerate(resolved):
            if int(candidate["candidate_order"]) != order:
                join_errors.append({"neighborhood_id": anchor_id, "reason": "authoritative_candidate_order_gap"})
            join_rows.append({
                "neighborhood_id": anchor_id,
                "schema_family_id": schema_id,
                "candidate_semantic_id": candidate["candidate_semantic_id"],
                "candidate_order": order,
                "candidate_text_sha256": candidate["text_sha256"],
                "feature_index_storage_only": feature["index"],
                "feature_sha256": feature["feature_sha256"],
                "join_key": "schema_family_id+candidate_semantic_id",
            })

    args.output.mkdir(parents=True, exist_ok=False)
    write_jsonl(args.output / "matched-neutral-selection.jsonl", selected)
    write_json(args.output / "radius-gate-report.json", {
        "status": "PASS" if decisions["all_pass"] else "FAIL",
        "selection": "frozen radius-only argmin; deterministic SHA tie-break",
        "gates": gates,
        "results": {
            "mean_relative_radius_error": mean_relative,
            "p95_absolute_radius_error": p95_absolute,
            "family_mean_relative_radius_error": family_means,
            "decisions": decisions,
        },
        "direction_or_cosine_used_for_selection": False,
        "outcomes_used_for_selection": False,
        "replacement_after_gate_failure": False,
    })
    write_json(args.output / "semantic-axis-composition.json", {
        "selected_count": len(selected),
        "selected_axis_counts": dict(sorted(axis_counts.items())),
        "selection_rule": "radius-only; no direction/cosine matching; no replacement selection",
    })
    write_jsonl(args.output / "whole-panel-candidate-join.jsonl", join_rows)
    join_pass = len(join_rows) == 8_000 and not join_errors
    write_json(args.output / "whole-panel-join-preflight.json", {
        "status": "PASS" if join_pass else "FAIL",
        "neighborhoods": len(groups),
        "expected_candidates_per_neighborhood": 4,
        "resolved_candidate_rows": len(join_rows),
        "missing_duplicate_extra": 0 if join_pass else len(join_errors),
        "join_key": "exact schema_family_id + candidate_semantic_id",
        "storage_row_number_used_as_identity": False,
        "errors": join_errors[:50],
    })
    receipt = {
        "status": "Q_R1_MATCHING_AND_JOIN_PASS" if decisions["all_pass"] and join_pass else "Q_R1_MATCHING_OR_JOIN_FAIL",
        "panel_materialization_manifest_sha256": panel_manifest_sha,
        "feature_receipt_sha256": sha256_file(args.features / FEATURE_RECEIPT_NAME),
        "state_feature_tensor_sha256": feature_receipt["state_tensor"]["tensor_sha256"],
        "candidate_feature_tensor_sha256": feature_receipt["candidate_tensor"]["tensor_sha256"],
        "selection_rows": len(selected),
        "join_rows": len(join_rows),
        "radius_gate_report_sha256": sha256_file(args.output / "radius-gate-report.json"),
        "axis_report_sha256": sha256_file(args.output / "semantic-axis-composition.json"),
        "selection_sha256": sha256_file(args.output / "matched-neutral-selection.jsonl"),
        "join_manifest_sha256": sha256_file(args.output / "whole-panel-candidate-join.jsonl"),
        "join_preflight_sha256": sha256_file(args.output / "whole-panel-join-preflight.json"),
        "training_targets_read": False,
        "heldout_outcomes_read": False,
        "head_loaded": False,
        "training": False,
        "inference": False,
        "phoenix_access": False,
    }
    receipt["matching_script_sha256"] = sha256_file(Path(__file__).resolve())
    receipt["panel_seal_sha256"] = sha256_file(PANEL_SEAL)
    receipt["feature_seal_sha256"] = sha256_file(FEATURE_SEAL)
    receipt["contract_sha256"] = sha256_file(CONTRACT)
    write_json(args.output / "r1-matching-and-join-receipt.json", receipt)
    print(json.dumps(receipt, indent=2), flush=True)
    return 0 if decisions["all_pass"] and join_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
