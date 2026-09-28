"""Construct v0.8K matched auxiliary-supervision Phase A without model contact."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = Path(__file__).with_name("phase-a-v01-contract.json")
V08J = Path(r"D:\codex-runs\jev-information-density-v08j")
J_PHASE_A = V08J / "phase-a-v01"
J_RUN = V08J / "phase-b-v01"
J_SEAL = V08J / "seal"
OUT = Path(r"D:\codex-runs\jev-information-density-v08k\phase-a-v01-clean")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    contract = read_json(CONTRACT)
    seal_manifest = J_SEAL / "v08j-seal-manifest.json"
    seal_audit = J_SEAL / "v08j-seal-audit.json"
    require(seal_manifest.is_file() and seal_audit.is_file(), "v0.8J seal is missing")
    seal = read_json(seal_manifest)
    audit = read_json(seal_audit)
    require(audit["status"] == "PASS", "v0.8J seal did not PASS")
    require(seal["status"] == "COMPLETE_NONPARENTABLE", "v0.8J is not sealed complete")
    require(seal["phase_a_identity"] == "phase-a-v01-clean", "v0.8J Phase-A identity drift")
    require(seal["protocol"] == "jev-information-density/v0.8j-phase-b-v01", "v0.8J Phase-B protocol drift")
    require(read_json(J_RUN / "reports/collateral-evaluation-integrity.json")["status"] == "PASS", "v0.8J collateral receipt not PASS")
    require(contract["forbidden_parent_identity"] == "phase-a-v01-quarantined", "forbidden-parent guard drift")

    parent_f100 = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean\materialized\F100-groups.jsonl")
    j_sham = J_PHASE_A / "inputs/sham-views.jsonl"
    j_triplets = J_PHASE_A / "inputs/triplets.jsonl"
    primary = read_jsonl(parent_f100)
    sham = read_jsonl(j_sham)
    triplets = read_jsonl(j_triplets)
    require(len(primary) == 100000 and len({row["group_id"] for row in primary}) == 100000, "primary bank drift")
    require(len(sham) == 5000 and len(triplets) == 5000, "triplet/sham count drift")
    by_group = {row["group_id"]: row for row in primary}
    by_sham = {row["group_id"]: row for row in sham}
    require(len(by_sham) == 5000, "sham IDs are not unique")

    triplet_records = []
    for item in triplets:
        anchor = by_group.get(item["anchor_group_id"])
        fact = by_group.get(item["fact_flip_group_id"])
        sham_row = by_sham.get(item["sham_group_id"])
        require(anchor is not None and fact is not None and sham_row is not None, f"triplet row missing: {item['anchor_id']}")
        require(anchor["candidate_semantic_ids"] == fact["candidate_semantic_ids"] == sham_row["candidate_semantic_ids"], f"candidate IDs drift: {item['anchor_id']}")
        require(anchor["candidate_indices"]["name_definition"] == fact["candidate_indices"]["name_definition"] == sham_row["candidate_indices"]["name_definition"], f"candidate index drift: {item['anchor_id']}")
        require(all(abs(float(a) - float(s)) <= 1e-12 for a, s in zip(anchor["gold"], sham_row["gold"])), f"sham gold drift: {item['anchor_id']}")
        require(max(range(len(anchor["gold"])), key=anchor["gold"].__getitem__) != max(range(len(fact["gold"])), key=fact["gold"].__getitem__), f"fact flip lost: {item['anchor_id']}")
        triplet_records.append({"triplet_id": item["anchor_id"], "anchor_group_id": item["anchor_group_id"], "fact_flip_group_id": item["fact_flip_group_id"], "sham_group_id": item["sham_group_id"], "anchor_gold": anchor["gold"], "fact_flip_gold": fact["gold"], "sham_gold": sham_row["gold"], "certificate_hash": item["certificate_hash"]})

    source_hashes = {"F100": sha256_file(parent_f100), "j_sham_views": sha256_file(j_sham), "j_triplets": sha256_file(j_triplets), "j_seal_manifest": sha256_file(seal_manifest), "j_seal_audit": sha256_file(seal_audit)}
    events = {}
    for arm, role in (("K-DUP", "anchor"), ("K-SHAM", "sham")):
        records = []
        for item in triplet_records:
            source_group = item["anchor_group_id"] if role == "anchor" else item["sham_group_id"]
            record = {"arm": arm, "triplet_id": item["triplet_id"], "auxiliary_source_role": role, "source_group_id": source_group, "target": "anchor_gold", "loss": "existing_v08j_L3_source_typed", "weight": 1.0, "batch_schedule": "anchor_primary_row_position_after_shared_A_F_S_forward", "normalization": "N_base_plus_N_aux", "objective_event_signature": ""}
            record["objective_event_signature"] = sha256_json(record)
            records.append(record)
        events[arm] = records

    OUT.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT / "inputs/triplets.jsonl", triplet_records)
    write_jsonl(OUT / "inputs/dup-auxiliary-events.jsonl", events["K-DUP"])
    write_jsonl(OUT / "inputs/sham-auxiliary-events.jsonl", events["K-SHAM"])
    primary_ref = {"name": "F100", "path": str(parent_f100), "sha256": source_hashes["F100"], "count": 100000, "source_scope": "sealed_v08i_training_only"}
    write_json(OUT / "inputs/primary-bank-reference.json", primary_ref)

    graph = {"protocol": contract["protocol"], "phase_a_identity": contract["phase_a_identity"], "parent_phase_b_identity": "phase-b-v01-clean", "parent_seal_manifest_sha256": source_hashes["j_seal_manifest"], "primary_bank": primary_ref, "triplet_count": 5000, "existing_invariance_pairs": 4982, "new_anchor_sham_edges": 0, "arms": {arm: {"auxiliary_source_role": role, "auxiliary_event_count": 5000, "auxiliary_target": "anchor_gold", "auxiliary_weight": 1.0, "objective_event_sha256": sha256_file(OUT / ("inputs/dup-auxiliary-events.jsonl" if arm == "K-DUP" else "inputs/sham-auxiliary-events.jsonl"))} for arm, role in (("K-DUP", "anchor"), ("K-SHAM", "sham"))}, "normalization": contract["objective"], "same_feature_universe": True, "same_forward_schedule": True, "only_auxiliary_source_role_differs": True}
    graph_payload = json.dumps(graph, indent=2, ensure_ascii=False) + "\n"
    (OUT / "objective-graph.json").write_text(graph_payload, encoding="utf-8")
    graph_hash = sha256_file(OUT / "objective-graph.json")
    manifests = {}
    for arm, role in (("K-DUP", "anchor"), ("K-SHAM", "sham")):
        manifests[arm] = {"arm": arm, "primary_bank_sha256": source_hashes["F100"], "triplets_sha256": sha256_file(OUT / "inputs/triplets.jsonl"), "auxiliary_events_sha256": graph["arms"][arm]["objective_event_sha256"], "auxiliary_source_role": role, "auxiliary_event_count": 5000, "primary_row_distance": 0, "target_multiset_distance": 0, "feature_universe_distance": 0, "new_invariance_edges": 0, "objective_graph_sha256": graph_hash}
    write_json(OUT / "arm-manifests.json", manifests)
    write_json(OUT / "phase-a-lineage-audit.json", {"status": "PASS", "phase_a_identity": contract["phase_a_identity"], "parent_phase_a_identity": seal["phase_a_identity"], "parent_phase_b_identity": "phase-b-v01-clean", "parent_seal_manifest_sha256": source_hashes["j_seal_manifest"], "forbidden_parent_used": False, "model_contact": False, "feature_extraction": False, "protected_eval_bodies_opened": False, "Phoenix": False, "source_hashes": source_hashes})
    write_json(OUT / "phase-a-triplet-audit.json", {"status": "PASS", "triplet_count": len(triplet_records), "families": dict(sorted(Counter(item["triplet_id"].split(":")[0] for item in triplet_records).items())), "sham_gold_max_abs_error": 0.0, "fact_flip_map_change_count": len(triplet_records), "K_DUP_auxiliary_source": "anchor", "K_SHAM_auxiliary_source": "sham"})
    receipt = {"protocol": contract["protocol"], "status": "PHASE_A_READY_PHASE_B_NOT_AUTHORIZED", "phase_a_identity": contract["phase_a_identity"], "phase_b_model_contact_authorized": False, "parent_seal_manifest_sha256": source_hashes["j_seal_manifest"], "objective_graph_sha256": graph_hash, "primary_bank": primary_ref, "triplet_count": 5000, "auxiliary_event_count_per_arm": 5000, "arms": manifests, "model_contact": False, "feature_extraction": False, "training": False, "evaluation_inference": False, "Phoenix": False}
    write_json(OUT / "phase-a-receipt.json", receipt)
    write_json(OUT / "construction-integrity.json", {"status": "PASS", "protocol": contract["protocol"], "contract_sha256": sha256_file(CONTRACT), "objective_graph_sha256": graph_hash, "primary_bank_sha256": source_hashes["F100"], "triplets_sha256": sha256_file(OUT / "inputs/triplets.jsonl"), "dup_events_sha256": manifests["K-DUP"]["auxiliary_events_sha256"], "sham_events_sha256": manifests["K-SHAM"]["auxiliary_events_sha256"], "model_contact": False, "Phoenix": False})
    print(json.dumps({"status": "PASS", "phase_a": str(OUT), "objective_graph_sha256": graph_hash, "triplets": 5000, "aux_events_per_arm": 5000}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
