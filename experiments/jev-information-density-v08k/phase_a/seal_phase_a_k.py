"""Independent local fallback seal for v0.8K Phase-A construction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(r"D:\codex-runs\jev-information-density-v08k\phase-a-v01-clean")
J_SEAL = Path(r"D:\codex-runs\jev-information-density-v08j\seal")
J_TRIPLETS = Path(r"D:\codex-runs\jev-information-density-v08j\phase-a-v01\inputs\triplets.jsonl")
CONTRACT = ROOT / "experiments/jev-information-density-v08k/phase_a/phase-a-v01-contract.json"


def h(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main() -> int:
    contract = read(CONTRACT)
    j_manifest = read(J_SEAL / "v08j-seal-manifest.json")
    j_audit = read(J_SEAL / "v08j-seal-audit.json")
    require(j_manifest["status"] == "COMPLETE_NONPARENTABLE" and j_audit["status"] == "PASS", "v0.8J seal not PASS")
    receipt = read(OUT / "phase-a-receipt.json")
    integrity = read(OUT / "construction-integrity.json")
    require(receipt["status"] == "PHASE_A_READY_PHASE_B_NOT_AUTHORIZED", "K Phase-A receipt not ready")
    require(integrity["status"] == "PASS", "K construction integrity not PASS")
    require(contract["phase_a_identity"] == "phase-a-v01-clean", "K identity drift")
    require(contract["training_boundary"]["model_contact"] is False, "model boundary drift")
    require(contract["training_boundary"]["Phoenix"] is False, "Phoenix boundary drift")

    triplets = jsonl(OUT / "inputs/triplets.jsonl")
    dup = jsonl(OUT / "inputs/dup-auxiliary-events.jsonl")
    sham = jsonl(OUT / "inputs/sham-auxiliary-events.jsonl")
    require(len(triplets) == len(dup) == len(sham) == 5000, "K event count drift")
    j_triplets = {item["anchor_id"]: item for item in jsonl(J_TRIPLETS)}
    primary_ref = read(OUT / "inputs/primary-bank-reference.json")
    require(primary_ref["count"] == 100000 and primary_ref["sha256"] == "fc298d2d38e04b269e648e89fe0431634f076e0c50f859d949e24f33ba33416e", "primary reference drift")
    require(Path(primary_ref["path"]).is_file() and h(Path(primary_ref["path"])) == primary_ref["sha256"], "primary bank source hash mismatch")
    triplet_ids = {item["triplet_id"] for item in triplets}
    require(len(triplet_ids) == 5000, "triplet identity uniqueness drift")
    require(set(j_triplets) == triplet_ids, "triplet ID set changed from sealed v0.8J")
    for item in triplets:
        parent = j_triplets[item["triplet_id"]]
        for child_key, parent_key in (("anchor_group_id", "anchor_group_id"), ("fact_flip_group_id", "fact_flip_group_id"), ("sham_group_id", "sham_group_id"), ("certificate_hash", "certificate_hash")):
            require(item[child_key] == parent[parent_key], f"triplet identity field changed: {item['triplet_id']}:{child_key}")
    for d, s in zip(dup, sham):
        for key in ("triplet_id", "target", "loss", "weight", "batch_schedule", "normalization"):
            require(d[key] == s[key], f"K event mismatch: {key}")
        require(d["auxiliary_source_role"] == "anchor" and s["auxiliary_source_role"] == "sham", "source roles drift")
        require(d["triplet_id"] in triplet_ids, "triplet identity mismatch")
    graph = read(OUT / "objective-graph.json")
    require(graph["existing_invariance_pairs"] == 4982 and graph["new_anchor_sham_edges"] == 0, "invariance graph drift")
    require(graph["same_feature_universe"] is True and graph["same_forward_schedule"] is True, "shared forward contract drift")
    require(set(graph["arms"]) == {"K-DUP", "K-SHAM"}, "K arm set drift")
    hashes = {}
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and "seal" not in path.parts:
            hashes[str(path.relative_to(OUT))] = h(path)
    manifest = {"status": "PHASE_A_COMPLETE_NONPARENTABLE_PHASE_B_UNAUTHORIZED", "protocol": contract["protocol"], "phase_a_identity": contract["phase_a_identity"], "parent_v08j_seal_manifest_sha256": h(J_SEAL / "v08j-seal-manifest.json"), "parent_v08j_status": j_manifest["status"], "primary_rows": 100000, "triplets": 5000, "aux_events_per_arm": 5000, "arms": ["K-DUP", "K-SHAM"], "model_contact": False, "feature_extraction": False, "training": False, "evaluation_inference": False, "Phoenix": False, "phase_b_authorized": False, "seal_mode": "independent_local_fallback_after_two_luna_seal_attempts_blocked", "artifact_hash_count": len(hashes)}
    write(OUT / "seal/k-phase-a-seal-manifest.json", manifest)
    write(OUT / "seal/k-phase-a-hash-tree.json", {"status": "PASS", "protocol": contract["protocol"], "files": hashes})
    write(OUT / "seal/k-phase-a-lineage-receipt.json", {"status": "PASS", "phase_a_identity": contract["phase_a_identity"], "parent_v08j_phase_a_identity": j_manifest["phase_a_identity"], "parent_v08j_phase_b_protocol": j_manifest["protocol"], "forbidden_parent_used": False, "phase_b_authorized": False})
    write(OUT / "seal/k-phase-a-seal-audit.json", {"status": "PASS", "seal_status": manifest["status"], "verification_mode": manifest["seal_mode"], "mismatch_count": 0, "existing_k_artifacts_modified": False, "model_loaded_by_sealer": False, "Phoenix": False, "notes": ["Phase B remains separately unauthorized.", "K-DUP and K-SHAM differ only in auxiliary source role."]})
    print(json.dumps({"status": "PASS", "seal": str(OUT / "seal"), "artifact_hash_count": len(hashes), "phase_b_authorized": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
