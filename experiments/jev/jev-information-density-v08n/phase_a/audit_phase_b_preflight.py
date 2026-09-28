"""Outcome-blind Phase-B preflight audit; never loads a head or evaluator."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
N_RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01")
EVAL_RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-eval-panel-v01")


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


def quantiles(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "max": None}
    x = torch.tensor(values, dtype=torch.float64)
    return {
        "count": len(values),
        "mean": float(x.mean()),
        "p50": float(torch.quantile(x, torch.tensor(0.5, dtype=x.dtype))),
        "p95": float(torch.quantile(x, torch.tensor(0.95, dtype=x.dtype))),
        "max": float(x.max()),
    }


def target(row: dict[str, Any]) -> list[float]:
    return [float(item["probability"]) for item in row["gold_targets"][0]["target"]["distribution"]]


def surface(row: dict[str, Any]) -> str:
    return row["renderings"][0]["text"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execution-inputs", type=Path)
    args = parser.parse_args()

    n_contract_path = ROOT / "experiments/jev-information-density-v08n/phase-a-v01-contract.json"
    n_contract = read_json(n_contract_path)
    road_b_manifest = read_json(N_RUN / "road-b/arm-objective-manifest.json")
    road_b_validation = read_json(N_RUN / "road-b/independent-validation.json")
    eval_seal = read_json(EVAL_RUN / "seal/seal-manifest.json")
    eval_validation = read_json(EVAL_RUN / "seal/independent-validation.json")
    eval_scope = read_jsonl(EVAL_RUN / "semantic-scope/heldout-feature-scope.jsonl")
    train_scope = read_jsonl(N_RUN / "shared-feature-cache/training-only-feature-scope.jsonl")
    train_selected = read_jsonl(N_RUN / "selection/selected-training-neighborhoods.jsonl")
    eval_selected = read_jsonl(EVAL_RUN / "semantic-scope/heldout-neighborhoods.jsonl")
    train_cert = {row["anchor_id"]: row for row in read_jsonl(N_RUN / "train-contrast-certificates.jsonl")}
    eval_cert = {row["anchor_id"]: row for row in read_jsonl(N_RUN / "eval-contrast-certificates.jsonl")}
    generator = read_json(N_RUN / "generator-receipt.json")

    train_ids = {row["episode_id"] for row in train_scope}
    eval_ids = {row["episode_id"] for row in eval_scope}
    train_input_hashes = {row["input_sha256"] for row in train_scope}
    eval_input_hashes = {row["input_sha256"] for row in eval_scope}
    train_templates = set(generator.get("train_template_ids", []))
    eval_templates = {row["template_id"] for row in eval_scope}

    surface_diff: dict[str, list[int]] = defaultdict(list)
    role_lengths: dict[str, list[int]] = defaultdict(list)
    for row in train_scope + eval_scope:
        role_lengths[row["role"]].append(len(row["text"]))
    for certificate_set, scope in ((train_cert, train_scope), (eval_cert, eval_scope)):
        by_neighborhood: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in scope:
            by_neighborhood[row["neighborhood_id"]].append(row)
        for anchor_id, rows in by_neighborhood.items():
            rows.sort(key=lambda row: row["index"])
            anchor_text = rows[0]["text"]
            for row in rows[1:]:
                surface_diff[row["role"]].append(sum(a != b for a, b in zip(anchor_text, row["text"])))

    feature_cache = torch.load(N_RUN / "shared-feature-cache/shared-training-features.pt", map_location="cpu", weights_only=True)["features"].to(torch.float64).reshape(5000, 11, 2048)
    heldout_cache = torch.load(EVAL_RUN / "feature-cache/heldout-features.pt", map_location="cpu", weights_only=True)["features"].to(torch.float64).reshape(2000, 11, 2048)

    def geometry_report(features: torch.Tensor, selected: list[dict[str, Any]], scope_rows: list[dict[str, Any]], matched_path: Path) -> dict[str, Any]:
        matched_rows = read_jsonl(matched_path)
        matched = {
            (row["anchor_id"] if "anchor_id" in row else row["neighborhood_id"]): row
            for row in matched_rows
        }
        feature_index = {row["neighborhood_id"]: int(row["index"]) // 11 for row in scope_rows if row["role"] == "anchor"}
        sf: list[float] = []
        nf: list[float] = []
        sn: list[float] = []
        s_radius: list[float] = []
        n_radius: list[float] = []
        family: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for row in selected:
            row_key = row["anchor_id"] if "anchor_id" in row else row["neighborhood_id"]
            chosen = matched[row_key]
            index = feature_index[row["anchor_id"]]
            a, f, s = features[index, 0], features[index, 1], features[index, 2]
            neutral_role = chosen.get("matched_neutral_axis", chosen.get("selected_neutral_role"))
            if neutral_role is None:
                neutral_role = chosen["matched_neutral_episode_id"].rsplit("-", 1)[-1]
            n_index = int(neutral_role.split("_")[-1]) + 2
            n = features[index, n_index]
            d_s, d_n, d_f = s - a, n - a, f - a
            rs, rn = torch.linalg.vector_norm(d_s), torch.linalg.vector_norm(d_n)
            sf.append(float(torch.dot(d_s, d_f) / (torch.linalg.vector_norm(d_s) * torch.linalg.vector_norm(d_f))))
            nf.append(float(torch.dot(d_n, d_f) / (torch.linalg.vector_norm(d_n) * torch.linalg.vector_norm(d_f))))
            sn.append(float(torch.dot(d_s, d_n) / (torch.linalg.vector_norm(d_s) * torch.linalg.vector_norm(d_n))))
            s_radius.append(float(rs)); n_radius.append(float(rn))
            family[row["family_id"]]["s_radius"].append(float(rs))
            family[row["family_id"]]["n_radius"].append(float(rn))
        return {"sham_radius": quantiles(s_radius), "matched_neutral_radius": quantiles(n_radius), "cosine_sham_neutral": quantiles(sn), "cosine_sham_fact": quantiles(sf), "cosine_neutral_fact": quantiles(nf), "by_family": {key: {name: quantiles(values) for name, values in value.items()} for key, value in sorted(family.items())}}

    execution_input_audit: dict[str, Any]
    if args.execution_inputs is None:
        execution_input_audit = {
            "status": "NOT_PROVIDED",
            "passed": False,
            "blocking_reason": "No materialized Phase-B execution-input receipt was supplied.",
        }
    else:
        execution_root = args.execution_inputs
        receipt_path = execution_root / "execution-inputs-receipt.json"
        hash_tree_path = execution_root / "execution-inputs-hash-tree.json"
        primary_path = execution_root / "common-primary-occurrence-manifest.jsonl"
        catalog_path = execution_root / "candidate-catalog.json"
        schedule_path = execution_root / "fixed-training-schedule.jsonl"
        arms = ("B-DUP", "B-MATCHED", "B-SHAM")
        manifest_paths = {arm: execution_root / f"head-input-manifest-{arm}.jsonl" for arm in arms}
        execution_receipt = read_json(receipt_path)
        hash_tree = read_json(hash_tree_path)
        primary_rows = read_jsonl(primary_path)
        schedule_rows = read_jsonl(schedule_path)
        head_rows = {arm: read_jsonl(path) for arm, path in manifest_paths.items()}
        catalog = read_json(catalog_path)
        primary_equal = all(
            [{key: value for key, value in row.items() if key != "arm"} for row in head_rows[arm][:10_000]]
            == [{key: value for key, value in row.items() if key != "arm"} for row in head_rows["B-DUP"][:10_000]]
            for arm in arms
        )
        primary_counts = {arm: sum(row["event_kind"] == "primary" for row in rows) for arm, rows in head_rows.items()}
        auxiliary_counts = {arm: sum(row["event_kind"] == "auxiliary" for row in rows) for arm, rows in head_rows.items()}
        hash_checks = {
            "primary": sha256_file(primary_path) == hash_tree["common_primary_occurrence_manifest"],
            "catalog": sha256_file(catalog_path) == hash_tree["candidate_catalog"],
            "schedule": sha256_file(schedule_path) == hash_tree["fixed_training_schedule"],
            **{arm: sha256_file(path) == hash_tree[f"head_input_{arm}"] for arm, path in manifest_paths.items()},
        }
        execution_pass = (
            execution_receipt["status"] == "V08N_PHASE_B_INPUTS_MATERIALIZED_NO_MODEL_CONTACT"
            and len(primary_rows) == 10_000
            and sum(row["role"] == "anchor" for row in primary_rows) == 5_000
            and sum(row["role"] == "fact_flip" for row in primary_rows) == 5_000
            and all(primary_counts[arm] == 10_000 and auxiliary_counts[arm] == 5_000 for arm in arms)
            and primary_equal
            and len(schedule_rows) == 360
            and catalog["feature_dimension"] == 2048
            and all(hash_checks.values())
        )
        execution_input_audit = {
            "status": "PASS" if execution_pass else "FAIL",
            "passed": execution_pass,
            "receipt_sha256": sha256_file(receipt_path),
            "hash_tree_sha256": sha256_file(hash_tree_path),
            "common_primary_manifest_sha256": sha256_file(primary_path),
            "common_primary_count": len(primary_rows),
            "common_primary_anchor_count": sum(row["role"] == "anchor" for row in primary_rows),
            "common_primary_fact_flip_count": sum(row["role"] == "fact_flip" for row in primary_rows),
            "head_input_primary_counts": primary_counts,
            "head_input_auxiliary_counts": auxiliary_counts,
            "head_input_manifests_equal_on_primary": primary_equal,
            "candidate_catalog_count": len(catalog["rows"]),
            "candidate_feature_dimension": catalog["feature_dimension"],
            "schedule_row_count": len(schedule_rows),
            "schedule_seed_rule": execution_receipt["schedule"]["seed_rule"],
            "hash_checks": hash_checks,
            "candidate_tensor_extraction_deferred_until_authorized_phase_b": True,
        }

    execution_passed = execution_input_audit.get("passed") is True
    report = {
        "status": "V08N_PHASE_B_PREFLIGHT_PASS_READY_NOT_AUTHORIZED" if execution_passed else "V08N_PHASE_B_PREFLIGHT_BLOCKED_PRIMARY_STREAM_UNRESOLVED",
        "identity": "v0.8N-road-b-phase-b-preflight-v02",
        "phase_b_authorized": False,
        "construction_receipts": {
            "road_b_validation": road_b_validation["status"],
            "heldout_panel_seal": eval_seal["status"],
            "heldout_panel_validation": eval_validation["status"],
        },
        "split_audit": {
            "train_scope_rows": len(train_scope),
            "eval_scope_rows": len(eval_scope),
            "train_eval_episode_overlap": len(train_ids & eval_ids),
            "train_eval_input_hash_overlap": len(train_input_hashes & eval_input_hashes),
            "train_eval_template_overlap": len(train_templates & eval_templates),
            "generator_train_eval_family_overlap": len(set(generator.get("train_family_ids", [])) & set(generator.get("eval_family_ids", []))),
            "generator_train_eval_template_overlap": len(set(generator.get("train_template_ids", [])) & set(generator.get("eval_template_ids", []))),
        },
        "surface_audit": {"role_character_length": {role: quantiles(values) for role, values in sorted(role_lengths.items())}, "anchor_sibling_changed_character_counts": {role: quantiles(values) for role, values in sorted(surface_diff.items())}},
        "geometry_audit": {
            "training": geometry_report(feature_cache, train_selected, train_scope, N_RUN / "road-b/selected-control-manifest.jsonl"),
            "heldout": geometry_report(heldout_cache, eval_selected, eval_scope, EVAL_RUN / "matched-panel-v02/heldout-matched-panel-manifest.jsonl"),
            "selection_is_radius_only": True,
            "direction_or_cosine_used_for_selection": False,
            "diagnostic_only": True,
        },
        "primary_stream_audit": {
            "road_b_arm_manifest_exists": True,
            "materialized_common_primary_group_manifest_exists": execution_passed,
            "materialized_common_primary_group_count": execution_input_audit.get("common_primary_count"),
            "observed_selected_neighborhood_episode_count": len(train_scope),
            "declared_primary_bank_label": road_b_manifest["primary_bank"]["identity"],
            "resolved_primary_occurrence_count": execution_input_audit.get("common_primary_count"),
            "blocking_reason": None if execution_passed else "Road-B sealed auxiliary arms but did not materialize/hash the common primary occurrence stream.",
        },
        "schedule_audit": {
            "schedule_identity": road_b_manifest["arms"]["B-DUP"]["schedule"]["identity"],
            "resolved_from_contract": execution_passed,
            "materialized_schedule_rows": execution_input_audit.get("schedule_row_count"),
            "training_executed": False,
            "blocking_reason": None if execution_passed else "Auxiliary event positions/order and primary-to-auxiliary interleaving are not resolved in a frozen Phase-B contract.",
        },
        "feature_space_audit": {
            "state_feature_cache_rows": 55000,
            "state_feature_cache_dim": 2048,
            "candidate_feature_cache_for_head_exists": False,
            "head_input_manifest_exists": execution_passed,
            "candidate_catalog_count": execution_input_audit.get("candidate_catalog_count"),
            "candidate_feature_dimension": execution_input_audit.get("candidate_feature_dimension"),
            "blocking_reason": None if execution_passed else "Road-B construction sealed state-radius features but no complete Phase-B head-input materialization receipt exists.",
        },
        "execution_input_audit": execution_input_audit,
        "model_contact": False,
        "head_training": False,
        "evaluation_inference": False,
        "newtight_access": False,
        "phoenix_access": False,
        "phase_b_ready": execution_passed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if execution_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
