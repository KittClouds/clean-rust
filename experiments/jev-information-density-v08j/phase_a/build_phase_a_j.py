"""Build the v0.8J objective graph without model contact or eval-body access."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PHASE_A = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean")
MAT = PHASE_A / "materialized"
OUT = Path(r"D:\codex-runs\jev-information-density-v08j\phase-a-v01")
CONTRACT = Path(__file__).with_name("phase-a-v01-contract.json")
PARENT_CONTRACT = ROOT / "experiments/jev-information-density-v08i/phase_b/phase-b-v01-contract.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(payload, encoding="utf-8", newline="\n")
    return sha256_file(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return sha256_file(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def index_selected_certificates() -> tuple[list[dict[str, Any]], set[str], dict[str, dict[str, Any]]]:
    path = MAT / "selected-train-contrast-certificates.jsonl"
    certs = read_jsonl(path)
    require(len(certs) == 5000, f"selected certificate count changed: {len(certs)}")
    by_anchor: dict[str, dict[str, Any]] = {}
    episode_ids: set[str] = set()
    for cert in certs:
        anchor = cert.get("anchor_id")
        ids = cert.get("episode_ids", {})
        require(isinstance(anchor, str) and anchor, "certificate missing anchor_id")
        require(set(ids) == {"anchor", "fact_flip", "sham"}, f"incomplete certificate: {anchor}")
        require(anchor not in by_anchor, f"duplicate anchor certificate: {anchor}")
        require(cert.get("partition") == "train", f"non-training certificate: {anchor}")
        by_anchor[anchor] = cert
        episode_ids.update(str(value) for value in ids.values())
    require(len(by_anchor) == 5000 and len(episode_ids) == 15000, "triplet identity census mismatch")
    return certs, episode_ids, by_anchor


def collect_triplet_rows(episode_ids: set[str]) -> dict[str, dict[str, dict[str, Any]]]:
    found: dict[str, dict[str, dict[str, Any]]] = {"F100": {}, "S100": {}}
    for arm in ("F100", "S100"):
        path = MAT / f"{arm}-groups.jsonl"
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                episode_id = row.get("episode_id")
                if episode_id in episode_ids:
                    require(episode_id not in found[arm], f"duplicate {arm} row for {episode_id}")
                    found[arm][episode_id] = row
    return found


def count_existing_surface_invariance_pairs() -> int:
    by_key: dict[str, set[str]] = {}
    path = MAT / "F100-groups.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("split") != "train" or row.get("open_world"):
                continue
            key = row.get("invariant_key")
            perturbation = row.get("perturbation_class")
            if key is not None and perturbation in (None, "surfaceinvariance"):
                by_key.setdefault(key, set()).add("base" if perturbation is None else "surfaceinvariance")
    return sum(values == {"base", "surfaceinvariance"} for values in by_key.values())


def validate_triplets(
    certs: list[dict[str, Any]],
    found: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    triplets: list[dict[str, Any]] = []
    for cert in certs:
        ids = cert["episode_ids"]
        anchor = found["F100"].get(ids["anchor"])
        fact = found["F100"].get(ids["fact_flip"])
        sham = found["S100"].get(ids["sham"])
        require(anchor is not None and fact is not None and sham is not None, f"missing triplet rows: {cert['anchor_id']}")
        require(anchor["view"] == fact["view"] == sham["view"] == "choice", f"non-choice triplet: {cert['anchor_id']}")
        require(anchor["candidate_semantic_ids"] == fact["candidate_semantic_ids"] == sham["candidate_semantic_ids"], f"candidate semantics drift: {cert['anchor_id']}")
        require(anchor["candidate_indices"]["name_definition"] == fact["candidate_indices"]["name_definition"] == sham["candidate_indices"]["name_definition"], f"candidate index drift: {cert['anchor_id']}")
        anchor_gold = anchor["gold"]
        sham_gold = sham["gold"]
        require(len(anchor_gold) == len(sham_gold) and all(abs(float(a) - float(s)) <= 1e-12 for a, s in zip(anchor_gold, sham_gold)), f"sham target mismatch: {cert['anchor_id']}")
        old_index = max(range(len(anchor["gold"])), key=lambda index: anchor["gold"][index])
        new_index = max(range(len(fact["gold"])), key=lambda index: fact["gold"][index])
        require(old_index != new_index, f"fact flip does not change MAP: {cert['anchor_id']}")
        require(cert.get("expected_label_before") is not None and cert.get("expected_label_after") is not None, f"missing expected labels: {cert['anchor_id']}")
        triplets.append({
            "anchor_id": cert["anchor_id"],
            "family_id": cert["world_family_id"],
            "schema_family_id": cert["schema_family_id"],
            "anchor_group_id": anchor["group_id"],
            "fact_flip_group_id": fact["group_id"],
            "sham_group_id": sham["group_id"],
            "anchor_episode_id": ids["anchor"],
            "fact_flip_episode_id": ids["fact_flip"],
            "sham_episode_id": ids["sham"],
            "state_signature": cert["state_signature"],
            "candidate_semantic_ids": anchor["candidate_semantic_ids"],
            "anchor_gold": anchor_gold,
            "fact_flip_gold": fact["gold"],
            "sham_gold": sham_gold,
            "expected_old_winner_index": old_index,
            "expected_new_winner_index": new_index,
            "certificate_hash": cert["certificate_hash"],
        })
    require(len(triplets) == 5000, "validated triplet count mismatch")
    return triplets


def objective_event_signature(event: dict[str, Any]) -> str:
    return sha256_json(event)


def build_graph(triplets: list[dict[str, Any]], parent: dict[str, Any], source_hashes: dict[str, str], existing_pair_count: int) -> dict[str, Any]:
    # Existing L3 surface-invariance events are referenced by identity only.
    # Their implementation remains bound to the v0.8I code receipt.
    arms: dict[str, dict[str, Any]] = {}
    for arm, flags in read_json(CONTRACT)["arms"].items():
        events = {
            "base_pointwise": {"active": True, "count": 100000, "source": "F100"},
            "existing_surface_invariance": {"active": True, "count": existing_pair_count, "source": "F100"},
            "sham_pointwise": {"active": flags["sham_pointwise"], "count": 5000, "target": "anchor_gold"},
            "anchor_sham_invariance": {"active": flags["anchor_sham_invariance"], "count": 5000, "weight": 0.1},
        }
        event_records = []
        for event_name, event in events.items():
            record = {"arm": arm, "event_name": event_name, **event}
            record["objective_event_signature"] = objective_event_signature(record)
            event_records.append(record)
        arms[arm] = {"flags": flags, "events": event_records}
    graph = {
        "protocol": "jev-information-density/v0.8j-phase-a-v01",
        "primary_bank": {"arm": "F100", "path": str(MAT / "F100-groups.jsonl"), "sha256": source_hashes["F100-groups.jsonl"], "count": 100000},
        "auxiliary_sham_views": {"count": 5000, "source": "S100", "path": str(OUT / "inputs/sham-views.jsonl")},
        "triplet_count": len(triplets),
        "existing_surface_invariance": {"implementation": "v0.8i-probe.invariant_pairs/vectorized_invariant_loss", "sealed_count": existing_pair_count, "preserved": True},
        "normalization": read_json(CONTRACT)["loss"]["normalization"],
        "arms": arms,
        "parent_phase_b_contract_sha256": sha256_file(PARENT_CONTRACT),
        "parent_phase_a_identity": parent["primary_treatment"]["phase_a_identity"],
    }
    return graph


def main() -> int:
    contract = read_json(CONTRACT)
    parent = read_json(PARENT_CONTRACT)
    require(parent["primary_treatment"]["phase_a_identity"] == "phase-a-v02-clean", "unexpected parent identity")
    require(parent["boundaries"]["Phoenix"] is False, "parent Phoenix boundary changed")
    require(contract["lineage"]["quarantined_parent_forbidden"] == "phase-a-v01", "quarantined identity guard changed")
    source_hashes = {
        name: sha256_file(MAT / name)
        for name in ("F100-groups.jsonl", "S100-groups.jsonl", "selected-train-contrast-certificates.jsonl")
    }
    require(source_hashes["F100-groups.jsonl"] == parent["phase_a_seal"]["F100_sha256"], "F100 source hash drift")
    require(source_hashes["S100-groups.jsonl"] == parent["phase_a_seal"]["S100_sha256"], "S100 source hash drift")
    require(source_hashes["selected-train-contrast-certificates.jsonl"] == parent["phase_a_seal"]["selected_train_contrast_certificates_sha256"], "certificate source hash drift")
    certs, episode_ids, _ = index_selected_certificates()
    found = collect_triplet_rows(episode_ids)
    triplets = validate_triplets(certs, found)
    existing_pair_count = count_existing_surface_invariance_pairs()
    require(existing_pair_count == 4982, f"existing v0.8i invariance pair count changed: {existing_pair_count}")
    OUT.mkdir(parents=True, exist_ok=True)
    input_hash = write_jsonl(OUT / "inputs/sham-views.jsonl", [found["S100"][row["sham_episode_id"]] for row in triplets])
    triplet_hash = write_jsonl(OUT / "inputs/triplets.jsonl", triplets)
    graph = build_graph(triplets, parent, source_hashes, existing_pair_count)
    graph_hash = write_json(OUT / "objective-graph.json", graph)
    arm_rows = {
        arm: {
            "arm": arm,
            "primary_bank": "F100",
            "primary_bank_sha256": source_hashes["F100-groups.jsonl"],
            "auxiliary_sham_views_sha256": input_hash,
            "triplets_sha256": triplet_hash,
            "sham_pointwise": flags["sham_pointwise"],
            "anchor_sham_invariance": flags["anchor_sham_invariance"],
            "row_multiset_distance_from_other_arms": 0,
            "objective_graph_sha256": graph_hash,
        }
        for arm, flags in contract["arms"].items()
    }
    write_json(OUT / "arm-manifests.json", arm_rows)
    write_json(OUT / "phase-a-lineage-audit.json", {
        "status": "PASS",
        "phase_a_identity": "phase-a-v01-clean",
        "parent_phase_a_identity": "phase-a-v02-clean",
        "quarantined_v01_parentage": False,
        "model_contact": False,
        "feature_extraction": False,
        "phoenix_access": False,
        "source_hashes": source_hashes,
        "protected_eval_bodies_opened": False,
        "source_scope": "sealed_v08i_training_only_F100_and_selected_train_certificates",
    })
    write_json(OUT / "phase-a-triplet-audit.json", {
        "status": "PASS",
        "triplets": len(triplets),
        "families": dict(sorted(Counter(row["family_id"] for row in triplets).items())),
        "sham_target_max_abs_error": 0.0,
        "fact_flip_map_change_count": len(triplets),
        "auxiliary_sham_rows": len(triplets),
    })
    receipt = {
        "protocol": contract["protocol"],
        "status": "PHASE_A_OBJECTIVE_GRAPH_READY_NO_MODEL_CONTACT",
        "model_contact_authorized": False,
        "phase_b_model_contact_authorized": False,
        "phase_a_identity": "phase-a-v01-clean",
        "parent_phase_a_identity": "phase-a-v02-clean",
        "quarantined_parentage": False,
        "primary_bank": {"name": "F100", "count": 100000, "sha256": source_hashes["F100-groups.jsonl"]},
        "auxiliary_sham_views": {"count": 5000, "sha256": input_hash},
        "triplets": {"count": 5000, "sha256": triplet_hash},
        "existing_surface_invariance_pair_count": existing_pair_count,
        "objective_graph": {"sha256": graph_hash, "arms": list(contract["arms"])},
        "protected_eval_bodies_opened": False,
        "feature_extraction": False,
        "phoenix_access": False,
    }
    write_json(OUT / "phase-a-objective-graph-receipt.json", receipt)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
