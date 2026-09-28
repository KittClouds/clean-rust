"""Freeze the qualification-only F4 encoder amendment and feature schema."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


STUDY = Path(__file__).resolve().parents[1]
BASE_SHA = "6beb47c4784a7d6e37a91e45688dd86e50b15291a8f0dbf07c56c71aefbe47a7"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    feature_collection = STUDY / "runs/qualification-v2/f4-features-v1/F4-FEATURE-COLLECTION-RECEIPT.json"
    executor_source = STUDY / "executor/src/qualification.rs"
    if not feature_collection.is_file():
        raise SystemExit("F4 feature collection receipt is missing")
    spec = {
        "schema": "FLY-REACH-03-F4-encoder-spec-v1",
        "version": "1.0",
        "status": "FROZEN_QUALIFICATION_ONLY",
        "scientific_role": "estimator_capacity_calibration_ceiling",
        "not_a_filtration_rung": True,
        "exact_ceiling": "Omega(F4)=1 by deterministic replay reconstruction",
        "feature_source": {
            "encoding": "deterministic_replay_descriptor_v1",
            "descriptor_schema": "FLY-REACH-03-f4-replay-descriptor-v1",
            "reference_blind": True,
            "forbidden_inputs": [
                "reference_delta_into outputs",
                "reference vector values",
                "reference logits",
                "target values",
                "sample_reference_sha256",
                "sample_target_sha256",
            ],
            "feature_generation_source": "executor/src/qualification.rs::f4_features",
        },
        "feature_map": {
            "schema": "f4_ref_blind_coordinate_task_v1",
            "width": 80,
            "dtype": "float32",
            "normalization": "per-fold training-mean-and-standard-deviation; std below 1e-6 replaced by 1",
            "row_universe": "qualification-v2 common U* rows; target nonzero; S_N_signarm; row_index mod 256 == 0",
            "feature_groups": [
                {"name": "coordinate_graph_local_state", "offset": 0, "width": 21},
                {"name": "task_labels", "offset": 21, "width": 4},
                {"name": "expected_task_scores", "offset": 25, "width": 4},
                {"name": "cue_edge_incidence", "offset": 29, "width": 4},
                {"name": "current_schedule_pattern_ids", "offset": 33, "width": 13},
                {"name": "fixed_coordinate_task_sketches", "offset": 53, "width": 24},
                {"name": "reserved_zero_padding", "offset": 77, "width": 3},
            ],
            "sketches": {
                "kind": "deterministic_signed_count_sketch",
                "families": 4,
                "buckets_per_family": 6,
                "seed_rule": "stable_mix(coordinate + cue*0x9e3779b97f4a7c15 + pattern_edge_count*2^17 + family*2^32)",
                "reference_blind": True,
            },
        },
        "encoder": {
            "family": "numpy_mlp",
            "architecture": [80, 128, "GELU", 64, "GELU", 1],
            "output": "binary polarity logit",
            "optimizer": "Adam",
            "learning_rate": 0.001,
            "batch_size": 2048,
            "epochs": 200,
            "initialization_seed_base": 304000,
            "training_order": "row order in concatenated lexicographic feature streams; no shuffle",
            "class_handling": "binary Y in {-1,+1} only; no zero-channel rows",
            "scoring": "IPW-balanced error, q=1/p_inclusion",
            "hyperparameter_search": "none; all fields frozen",
        },
        "qualification": {
            "run_id": "qualification-v2",
            "folds": "four leave-one-Q-block-out folds, blocks 303000,303001,303002,303003",
            "gate": {
                "pooled_balanced_error_max": 0.10,
                "pooled_omega_hat_min": 0.80,
                "per_fold_omega_hat_min": 0.70,
                "fold_failure_disposition": "ESTIMATOR_CAPACITY_STOP",
            },
            "measured_blocks_allowed": False,
            "measured_namespace_created": False,
        },
        "implementation_hashes": {
            "feature_collector_source_sha256": sha(executor_source),
            "feature_collection_receipt_sha256": sha(feature_collection),
        },
    }
    spec_path = STUDY / "F4-ENCODER-SPEC-v1.json"
    write_json(spec_path, spec)
    spec_sha = sha(spec_path)
    (STUDY / "F4-ENCODER-SPEC-v1.sha256").write_text(spec_sha + "  F4-ENCODER-SPEC-v1.json\n", encoding="utf-8")
    amendment = {
        "schema": "FLY-REACH-03-execution-contract-v0.2-f4-encoder-amendment",
        "study_id": "FLY-REACH-03",
        "status": "FROZEN_QUALIFICATION_AMENDMENT",
        "base_execution_contract": "EXECUTION-CONTRACT-v0.1.json",
        "authoritative_math_contract_sha256": BASE_SHA,
        "f4_role": "calibration_ceiling_only; not a scientific filtration rung",
        "exact_reconstruction_invariant": "Omega(F4)=1",
        "feature_spec": {"path": "F4-ENCODER-SPEC-v1.json", "sha256": spec_sha},
        "qualification_input_run": "qualification-v2",
        "qualification_feature_identity": "f4-features-v1",
        "qualification_only": True,
        "measured_namespace_created": False,
        "measured_execution_authorized": False,
        "gate": spec["qualification"]["gate"],
        "no_post_gate_tuning": True,
    }
    amendment_path = STUDY / "EXECUTION-CONTRACT-v0.2-F4-ENCODER-AMENDMENT.json"
    write_json(amendment_path, amendment)
    receipt = {
        "schema": "FLY-REACH-03-F4-encoder-contract-freeze-receipt-v1",
        "status": "PASS",
        "base_contract_sha256": BASE_SHA,
        "spec_sha256": spec_sha,
        "amendment_sha256": sha(amendment_path),
        "measured_namespace_created": False,
        "measured_execution_authorized": False,
    }
    write_json(STUDY / "artifacts/preimplementation/F4-ENCODER-CONTRACT-FREEZE-RECEIPT.json", receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
