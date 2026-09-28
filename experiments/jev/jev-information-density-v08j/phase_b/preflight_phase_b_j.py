"""Fail-closed Phase-B authorization for v0.8J."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PHASE_A_CODE = ROOT / "experiments/jev-information-density-v08j/phase_a"
PHASE_B_CODE = Path(__file__).resolve().parent
PHASE_A_RUN = Path(r"D:\codex-runs\jev-information-density-v08j\phase-a-v01")
PHASE_B_RUN = Path(r"D:\codex-runs\jev-information-density-v08j\phase-b-v01")
PHASE_A_PARENT = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean")
CONTRACT_PATH = PHASE_B_CODE / "phase-b-v01-contract.json"


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


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    contract = read_json(CONTRACT_PATH)
    contract_hash = sha256_file(CONTRACT_PATH)
    required_code = {
        "preflight_phase_b_j.py": Path(__file__),
        "extract_phase_b_j_features.py": PHASE_B_CODE / "extract_phase_b_j_features.py",
        "train_phase_b_j.py": PHASE_B_CODE / "train_phase_b_j.py",
        "probe.py": ROOT / "experiments/jev-frozen-readout-v01/probe.py",
        "train_v05.py": ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py",
        "extract_lfm.py": ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py",
    }
    for name, path in required_code.items():
        require(path.is_file(), f"required Phase-B source missing: {name}")
    phase_a_contract_path = PHASE_A_CODE / "phase-a-v01-contract.json"
    phase_a_contract = read_json(phase_a_contract_path)
    receipt = read_json(PHASE_A_RUN / "phase-a-objective-graph-receipt.json")
    graph = read_json(PHASE_A_RUN / "objective-graph.json")
    lineage = read_json(PHASE_A_RUN / "phase-a-lineage-audit.json")
    triplet_audit = read_json(PHASE_A_RUN / "phase-a-triplet-audit.json")
    manifests = read_json(PHASE_A_RUN / "arm-manifests.json")
    triplets = read_jsonl(PHASE_A_RUN / "inputs/triplets.jsonl")
    sham_views = read_jsonl(PHASE_A_RUN / "inputs/sham-views.jsonl")

    require(contract["phase_a_identity"] == "phase-a-v01-clean", "wrong Phase-A identity")
    require(contract["parent_phase_a_identity"] == "phase-a-v02-clean", "wrong parent Phase-A identity")
    require(contract["quarantined_parent_forbidden"] == "phase-a-v01", "quarantined parent guard changed")
    require(receipt["phase_a_identity"] == "phase-a-v01-clean", "receipt identity mismatch")
    require(receipt["parent_phase_a_identity"] == "phase-a-v02-clean", "receipt parent mismatch")
    require(receipt["objective_graph"]["sha256"] == contract["objective_graph_sha256"], "receipt objective graph hash mismatch")
    require(sha256_file(PHASE_A_RUN / "objective-graph.json") == contract["objective_graph_sha256"], "objective graph changed")
    require(lineage["status"] == "PASS" and lineage["quarantined_v01_parentage"] is False, "Phase-A lineage audit failed")
    require(lineage["model_contact"] is False and lineage["feature_extraction"] is False and lineage["phoenix_access"] is False, "Phase-A boundary was crossed")
    require(lineage["protected_eval_bodies_opened"] is False, "Phase-A opened protected evaluation bodies")
    require(triplet_audit["status"] == "PASS", "triplet audit failed")
    require(triplet_audit["triplets"] == 5000 and triplet_audit["auxiliary_sham_rows"] == 5000, "triplet capacity mismatch")
    require(triplet_audit["sham_target_max_abs_error"] <= 1e-12, "sham target tolerance failed")
    require(triplet_audit["fact_flip_map_change_count"] == 5000, "fact-flip MAP certificate count mismatch")
    require(graph["triplet_count"] == 5000, "objective graph triplet count mismatch")
    require(graph["existing_surface_invariance"]["sealed_count"] == 4982, "inherited invariance count mismatch")
    require(graph["primary_bank"]["count"] == 100000, "primary bank count mismatch")
    require(set(graph["arms"]) == {"J00", "J10", "J01", "J11"}, "arm set mismatch")
    require(len(triplets) == 5000 and len(sham_views) == 5000, "physical triplet/sham count mismatch")
    require(len({row["anchor_id"] for row in triplets}) == 5000, "triplet anchor IDs are not unique")
    require(len({row["group_id"] for row in sham_views}) == 5000, "sham group IDs are not unique")
    require(all(row.get("split") == "train" for row in sham_views), "sham view is not training-only")
    for arm, flags in contract["arms"].items():
        require(graph["arms"][arm]["flags"] == flags, f"objective flags mismatch: {arm}")
        manifest = manifests[arm]
        require(manifest["primary_bank"] == "F100", f"primary bank mismatch: {arm}")
        require(manifest["row_multiset_distance_from_other_arms"] == 0, f"row distance mismatch: {arm}")
        require(manifest["primary_bank_sha256"] == receipt["primary_bank"]["sha256"], f"manifest primary hash mismatch: {arm}")
        require(manifest["auxiliary_sham_views_sha256"] == receipt["auxiliary_sham_views"]["sha256"], f"manifest sham hash mismatch: {arm}")
        require(manifest["triplets_sha256"] == receipt["triplets"]["sha256"], f"manifest triplet hash mismatch: {arm}")
        require(manifest["objective_graph_sha256"] == contract["objective_graph_sha256"], f"manifest graph hash mismatch: {arm}")
        graph_events = {item["event_name"]: item for item in graph["arms"][arm]["events"]}
        for event in graph_events.values():
            unsigned = {key: value for key, value in event.items() if key != "objective_event_signature"}
            require(event["objective_event_signature"] == sha256_json(unsigned), f"event signature mismatch: {arm}/{event['event_name']}")
        require(graph["arms"][arm]["flags"] == flags, f"graph flags mismatch: {arm}")
    require(len({item["primary_bank_sha256"] for item in manifests.values()}) == 1, "primary bank differs across arms")
    require(len({item["auxiliary_sham_views_sha256"] for item in manifests.values()}) == 1, "sham views differ across arms")

    source_bank = PHASE_A_PARENT / "materialized/F100-groups.jsonl"
    require(sha256_file(source_bank) == receipt["primary_bank"]["sha256"], "sealed F100 source hash mismatch")
    sham_path = PHASE_A_RUN / "inputs/sham-views.jsonl"
    triplet_path = PHASE_A_RUN / "inputs/triplets.jsonl"
    require(sha256_file(sham_path) == receipt["auxiliary_sham_views"]["sha256"], "sham view hash mismatch")
    require(sha256_file(triplet_path) == receipt["triplets"]["sha256"], "triplet hash mismatch")

    pair_cells: dict[str, set[str]] = {}
    with source_bank.open("r", encoding="utf-8") as stream:
        physical_rows = 0
        physical_ids: set[str] = set()
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            physical_rows += 1
            require(row["group_id"] not in physical_ids, "duplicate F100 group ID")
            physical_ids.add(row["group_id"])
            if row.get("split") == "train" and not row.get("open_world") and row.get("perturbation_class") in (None, "surfaceinvariance"):
                pair_cells.setdefault(row["invariant_key"], set()).add("base" if row["perturbation_class"] is None else "surfaceinvariance")
    require(physical_rows == 100000 and len(physical_ids) == 100000, "F100 physical row count mismatch")
    recomputed_pairs = sum(values == {"base", "surfaceinvariance"} for values in pair_cells.values())
    require(recomputed_pairs == 4982, f"independent inherited invariance count mismatch: {recomputed_pairs}")
    require(contract["compiler"]["normalization"]["existing_invariance_events_per_step"] == 16, "existing invariance step policy changed")
    require(
        contract["compiler"]["normalization"]["formula"]
        == "(N_base*L_base + S*N_sham*L_sham + I*lambda_edge*N_edge*L_edge)/(N_base + S*N_sham + I*lambda_edge*N_edge) + lambda_existing*L_existing",
        "factorial normalization changed",
    )
    require(
        contract["compiler"]["normalization"]["existing_invariance_application"]
        == "inherited_v08i_additive_term_outside_factorial_event_normalization",
        "inherited invariance application changed",
    )
    require(
        contract["compiler"]["normalization"]["existing_pair_policy"]
        == "v08i_first_16_pairs_each_optimizer_step",
        "inherited pair ordering policy changed",
    )

    parent_contract = read_json(ROOT / "experiments/jev-information-density-v08i/phase_b/phase-b-v01-contract.json")
    require(parent_contract["primary_treatment"]["phase_a_identity"] == "phase-a-v02-clean", "parent v0.8I contract was not clean")
    require(sha256_file(PHASE_A_PARENT / "materialized/F100-groups.jsonl") == parent_contract["phase_a_seal"]["F100_sha256"], "v0.8I F100 lineage mismatch")
    require(phase_a_contract["lineage"]["quarantined_parent_forbidden"] == "phase-a-v01", "Phase-A quarantine contract mismatch")

    auth = {
        "status": "PASS",
        "protocol": contract["protocol"],
        "contract_sha256": contract_hash,
        "phase_a_contract_sha256": sha256_file(phase_a_contract_path),
        "objective_graph_sha256": contract["objective_graph_sha256"],
        "phase_a_identity": contract["phase_a_identity"],
        "parent_phase_a_identity": contract["parent_phase_a_identity"],
        "model_contact_authorized": True,
        "feature_extraction_authorized": True,
        "training_authorized": True,
        "protected_eval_bodies_opened": False,
        "phoenix_access": False,
        "verified_primary_bank_sha256": receipt["primary_bank"]["sha256"],
        "verified_sham_views_sha256": receipt["auxiliary_sham_views"]["sha256"],
        "verified_triplets_sha256": receipt["triplets"]["sha256"],
        "verified_existing_invariance_pairs": 4982,
        "verified_existing_invariance_events_per_step": 16,
        "source_code_sha256": {name: sha256_file(path) for name, path in required_code.items()},
    }
    target = PHASE_B_RUN / "preflight/model-contact-authorization.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(auth, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(auth, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
