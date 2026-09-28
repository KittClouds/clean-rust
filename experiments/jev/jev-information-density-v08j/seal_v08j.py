"""Independent read-only seal audit for completed v0.8J Phase B."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(r"D:\codex-runs\jev-information-density-v08j")
RUN = OUT / "phase-b-v01"
PHASE_A = OUT / "phase-a-v01"
SEAL = OUT / "seal"
CONTRACT = ROOT / "experiments/jev-information-density-v08j/phase_b/phase-b-v01-contract.json"
SEEDS = [20260927, 20260928, 20260929]
ARMS = ["J00", "J10", "J01", "J11"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest_state(state: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    import torch
    for key in sorted(state):
        digest.update(key.encode())
        digest.update(state[key].detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def verify() -> tuple[dict[str, Any], dict[str, str]]:
    contract = read_json(CONTRACT)
    contract_hash = sha256_file(CONTRACT)
    require(contract["phase_a_identity"] == "phase-a-v01-clean", "Phase-A identity drift")
    require(contract["parent_phase_a_identity"] == "phase-a-v02-clean", "Phase-A parent drift")
    require(contract["objective_graph_sha256"] == "99408b2aedb03c53c10f0aadb86e59bc26c4bdde2a402d9ac9d9017819cb541e", "objective graph drift")
    require(contract["model"]["revision"] == "7453bca97ca1e67754c4035a4b4c584e1c9dd725", "model revision drift")
    require(contract["compiler"]["trainable_parameters"] == 590081, "trainable parameter count drift")
    require(all(value is False for value in contract["boundaries"].values() if isinstance(value, bool)), "boundary mutation found")

    auth_path = RUN / "preflight/model-contact-authorization.json"
    auth = read_json(auth_path)
    require(auth["status"] == "PASS" and auth["training_authorized"] is True, "preflight authorization is not PASS")
    require(auth["contract_sha256"] == contract_hash, "preflight contract hash mismatch")
    require(auth["objective_graph_sha256"] == contract["objective_graph_sha256"], "preflight graph mismatch")

    graph = PHASE_A / "objective-graph.json"
    require(sha256_file(graph) == auth["objective_graph_sha256"], "objective graph file hash mismatch")
    graph_value = read_json(graph)
    require(graph_value["parent_phase_a_identity"] == "phase-a-v02-clean", "graph lineage mismatch")
    require(graph_value["existing_surface_invariance"]["sealed_count"] == 4982, "inherited pair count drift")
    require(set(graph_value["arms"]) == set(ARMS), "arm set drift")

    # The Phase-B authorization records hashes, while the canonical paths are
    # bound here independently rather than trusted from a mutable receipt.
    input_paths = {
        "F100": Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean\materialized\F100-groups.jsonl"),
        "sham_views": PHASE_A / "inputs/sham-views.jsonl",
        "triplets": PHASE_A / "inputs/triplets.jsonl",
    }
    input_hashes = {name: sha256_file(path) for name, path in input_paths.items()}
    require(input_hashes["F100"] == auth["verified_primary_bank_sha256"], "F100 hash mismatch")
    require(input_hashes["sham_views"] == auth["verified_sham_views_sha256"], "sham-view hash mismatch")
    require(input_hashes["triplets"] == auth["verified_triplets_sha256"], "triplet hash mismatch")
    require(sum(1 for _ in input_paths["sham_views"].open(encoding="utf-8")) == 5000, "sham count drift")
    require(sum(1 for _ in input_paths["triplets"].open(encoding="utf-8")) == 5000, "triplet count drift")

    summary_path = RUN / "reports/training-execution-summary.json"
    summary = read_json(summary_path)
    require(summary["status"] == "ALL_SCHEDULED_RUNS_COMPLETE_NO_EVALUATION", "training summary incomplete")
    require(summary["evaluation_access"] is False and summary["phoenix_access"] is False, "training boundary drift")
    require(len(summary["runs"]) == 12, "run summary count drift")

    artifact_hashes: dict[str, str] = {
        "contract": contract_hash,
        "authorization": sha256_file(auth_path),
        "objective_graph": sha256_file(graph),
        "training_summary": sha256_file(summary_path),
        "feature_receipt": sha256_file(RUN / "feature-cache/extraction-receipt.json"),
        "training_features": sha256_file(RUN / "feature-cache/phase-b-train-features.pt"),
        "F100": input_hashes["F100"],
        "sham_views": input_hashes["sham_views"],
        "triplets": input_hashes["triplets"],
    }
    run_records = []
    import torch
    for seed_index, seed in enumerate(SEEDS):
        initial_hashes = set()
        for arm in ARMS:
            run_dir = RUN / "runs" / f"seed-{seed_index + 1}" / arm
            report_path = run_dir / "run-report.json"
            config_path = run_dir / "run-config.json"
            require(report_path.is_file() and config_path.is_file(), f"missing run artifact: {run_dir}")
            report = read_json(report_path)
            config = read_json(config_path)
            require(report["status"] == "TRAINING_COMPLETE_NO_EVALUATION", f"run status drift: {run_dir}")
            require(report["seed"] == seed and report["arm"] == arm, f"run identity drift: {run_dir}")
            require(report["evaluation_access"] is False and report["phoenix_access"] is False, f"run boundary drift: {run_dir}")
            require(report["config_sha256"] == config["config_sha256"], f"config hash drift: {run_dir}")
            require(len(report["history"]) == 3 and report["trainable_parameters"] == 590081, f"budget drift: {run_dir}")
            initial_hashes.add(report["initial_head_sha256"])
            checkpoint_hashes = {}
            for epoch in (1, 2, 3):
                checkpoint = run_dir / f"checkpoint-epoch-{epoch}.pt"
                require(checkpoint.is_file(), f"missing checkpoint: {checkpoint}")
                payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
                require(payload["epoch"] == epoch and payload["config_sha256"] == report["config_sha256"], f"checkpoint binding drift: {checkpoint}")
                checkpoint_hashes[str(epoch)] = sha256_file(checkpoint)
            terminal = torch.load(run_dir / "checkpoint-epoch-3.pt", map_location="cpu", weights_only=True)
            require(digest_state(terminal["head_state"]) == report["terminal_head_sha256"], f"terminal head digest drift: {run_dir}")
            artifact_hashes[f"run:{seed_index + 1}/{arm}/report"] = sha256_file(report_path)
            artifact_hashes[f"run:{seed_index + 1}/{arm}/config"] = sha256_file(config_path)
            artifact_hashes.update({f"run:{seed_index + 1}/{arm}/checkpoint-{epoch}": value for epoch, value in checkpoint_hashes.items()})
            run_records.append({"seed": seed, "arm": arm, "report": str(report_path), "report_sha256": sha256_file(report_path), "checkpoints": checkpoint_hashes})
        require(len(initial_hashes) == 1, f"paired initialization drift for seed {seed}")

    unlock = read_json(RUN / "reports/evaluation-unlock.json")
    require(unlock["status"] == "EVALUATION_UNLOCKED_AFTER_TRAINING_SEAL", "evaluation unlock missing")
    require(unlock["run_count"] == 12 and unlock["checkpoint_count"] == 36, "unlock counts drift")
    for name in ("post-training-evaluation-integrity.json", "collateral-evaluation-integrity.json"):
        receipt = read_json(RUN / "reports" / name)
        require(receipt.get("phoenix_access") is False, f"Phoenix claim drift: {name}")
        artifact_hashes[f"report:{name}"] = sha256_file(RUN / "reports" / name)
    require(read_json(RUN / "reports/post-training-evaluation-integrity.json")["status"] == "POST_TRAINING_DIRECT_EVALUATION_COMPLETE", "direct evaluation incomplete")
    require(read_json(RUN / "reports/collateral-evaluation-integrity.json")["status"] == "PASS", "collateral evaluation incomplete")
    artifact_hashes["evaluation_unlock"] = sha256_file(RUN / "reports/evaluation-unlock.json")
    artifact_hashes["partial_quarantine"] = sha256_file(RUN / "partial-execution-quarantine.json")
    return {"protocol": contract["protocol"], "status": "COMPLETE_NONPARENTABLE", "contract_sha256": contract_hash,
            "phase_a_identity": contract["phase_a_identity"], "parent_phase_a_identity": contract["parent_phase_a_identity"],
            "objective_graph_sha256": contract["objective_graph_sha256"], "model": contract["model"],
            "seeds": SEEDS, "arms": ARMS, "run_count": len(run_records), "checkpoint_count": 36,
            "inherited_invariance_pairs": 4982, "trainable_parameters": 590081,
            "evaluation_opened_after_training_seal": True, "phoenix_access": False, "adaptation_access": False,
            "quarantined_v08i_partial_excluded": True, "runs": run_records}, artifact_hashes


def main() -> int:
    try:
        manifest, hashes = verify()
        manifest["artifact_hash_count"] = len(hashes)
        hash_tree = {"status": "PASS", "protocol": manifest["protocol"], "files": hashes}
        lineage = {"status": "PASS", "current_identity": manifest["phase_a_identity"],
                   "parent_identity": manifest["parent_phase_a_identity"], "phase_b_identity": "phase-b-v01-clean",
                   "quarantined_parent_forbidden": True, "v08j_disposition": {
                       "localized_control": "FAIL", "suppression_invariance_control": "OBSERVED",
                       "pointwise_sham_supervision": "POSITIVE_EMPIRICAL_RESULT", "causal_attribution": "UNRESOLVED"}}
        audit = {"status": "PASS", "seal_status": "COMPLETE_NONPARENTABLE", "verification_mode": "independent_read_only_local_seal",
                 "mismatch_count": 0, "existing_artifacts_modified": False, "model_loaded_by_sealer": False,
                 "phoenix_access": False, "notes": ["v0.8J is sealed research history.", "Only explicitly listed reports and identities may be used as parents."]}
        SEAL.mkdir(parents=True, exist_ok=True)
        write_json(SEAL / "v08j-seal-manifest.json", manifest)
        write_json(SEAL / "v08j-artifact-hash-tree.json", hash_tree)
        write_json(SEAL / "v08j-lineage-receipt.json", lineage)
        write_json(SEAL / "v08j-seal-audit.json", audit)
        print(json.dumps({"status": "PASS", "seal": str(SEAL), "artifact_hash_count": len(hashes)}, indent=2))
        return 0
    except Exception as error:
        SEAL.mkdir(parents=True, exist_ok=True)
        write_json(SEAL / "v08j-seal-audit.json", {"status": "FAIL", "error": str(error), "existing_artifacts_modified": False})
        print(json.dumps({"status": "FAIL", "error": str(error)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
