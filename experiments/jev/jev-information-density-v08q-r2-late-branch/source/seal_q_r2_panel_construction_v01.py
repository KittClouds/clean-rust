"""Seal Q-R2's online-admitted fresh panel before feature extraction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\panel-v01")
CONTRACT = ROOT / "experiments/jev-information-density-v08q-r2-late-branch/contracts/q-r2-panel-contract-v01.json"
PACKET_SEAL = ROOT / "experiments/jev-information-density-v08q-r2-late-branch/seals/q-r2-phase-packet-seal-v01.json"
MANIFEST = RUN_ROOT / "provenance/q-r2-panel-manifest-v01.json"
SEAL = RUN_ROOT / "seals/q-r2-panel-construction-seal-v01.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def row_count(path: Path) -> int:
    with path.open("rb") as stream:
        return sum(1 for line in stream if line.strip())


def main() -> int:
    if MANIFEST.exists() or SEAL.exists():
        raise RuntimeError("refusing to replace an existing Q-R2 panel manifest or seal")
    packet_seal = read_json(PACKET_SEAL)
    contract = read_json(CONTRACT)
    if packet_seal["status"] != "SEALED_AUTHORIZED_FOR_PHASE_EXECUTION":
        raise RuntimeError("Q-R2 packet authorization is not active")
    expected_contract = {row["path"]: row["sha256"] for row in packet_seal["contracts"]}
    if expected_contract.get("contracts/q-r2-panel-contract-v01.json") != sha256_file(CONTRACT):
        raise RuntimeError("Q-R2 panel contract changed after packet seal")
    exclusion_root = RUN_ROOT / "exclusions"
    panel_root = RUN_ROOT / "panel"
    audit_path = RUN_ROOT / "panel-audit/r2-final-panel-audit.json"
    exclusion_receipt = read_json(exclusion_root / "exclusion-set-receipt.json")
    admission = read_json(panel_root / "online-admission-receipt.json")
    audit = read_json(audit_path)
    if admission.get("status") != "Q_R2_ONLINE_PANEL_ADMISSION_PASS" or admission.get("accepted_total") != 2_000 or admission.get("admitted_occurrences") != 22_000:
        raise RuntimeError("Q-R2 online admission did not fill the fixed panel")
    if audit.get("status") != "Q_R2_FRESH_PANEL_FINAL_AUDIT_PASS" or audit.get("neighborhoods") != 2_000 or audit.get("occurrences") != 22_000:
        raise RuntimeError("Q-R2 generator final audit failed")

    panel_names = [
        "panel-canonical-episodes.jsonl",
        "panel-exact-world-episodes.jsonl",
        "panel-contrast-certificates.jsonl",
        "panel-feature-scope.jsonl",
        "panel-neighborhoods.jsonl",
        "panel-occurrence-identities.jsonl",
        "online-admission-log.jsonl",
        "online-admission-receipt.json",
    ]
    output_rows = []
    for name in panel_names:
        path = panel_root / name
        output_rows.append({"name": name, "bytes": path.stat().st_size, "rows": row_count(path), "sha256": sha256_file(path)})
    candidate_path = panel_root / "fresh-candidate-text-manifest.jsonl"
    exclusion_path = exclusion_root / "five-field-exclusion-sets.json"
    exclusion_sha = sha256_file(exclusion_path)
    if exclusion_receipt.get("exclusion_set_sha256") != exclusion_sha:
        raise RuntimeError("Q exclusion-set receipt/hash mismatch")

    manifest = {
        "schema": "jev-v08q-r2-panel-materialization-manifest-v01",
        "identity": "JEV-V08Q-R2-fresh-panel-v01",
        "status": "Q_R2_PANEL_CONSTRUCTION_AND_FIVE_FIELD_AUDIT_PASS",
        "panel_root": str(panel_root),
        "contract_sha256": sha256_file(CONTRACT),
        "contract_bundle_root_sha256": packet_seal["contract_bundle_root_sha256"],
        "authorization_receipt_sha256": sha256_file(PACKET_SEAL),
        "admission": {
            "namespace": contract["namespace"],
            "seed_u32": contract["generator_seed"],
        "candidate_ordinals_per_family": "ascending 0..699; fixed R2 stream",
            "admitted_per_family": contract["population"]["neighborhoods_per_family"],
            "consumed_by_family": admission["consumed_by_family"],
            "rejected_by_family": admission["rejected_by_family"],
            "total_admitted": admission["accepted_total"],
            "total_occurrences": admission["admitted_occurrences"],
            "admission_receipt_sha256": sha256_file(panel_root / "online-admission-receipt.json"),
            "admission_log_sha256": sha256_file(panel_root / "online-admission-log.jsonl"),
            "candidate_text_manifest_sha256": sha256_file(candidate_path),
        },
        "construction_outputs": output_rows,
        "candidate_basis": {
            "rows": row_count(candidate_path),
            "source": "frozen family specifications materialized by the R2 generator",
            "hash_sha256": sha256_file(candidate_path),
            "training_catalog_overlap": 0,
        },
        "exclusion_sets": {
            "sha256": exclusion_sha,
            "receipt_sha256": sha256_file(exclusion_root / "exclusion-set-receipt.json"),
            "training_rows": 55_000,
            "prior_panel_rows": 88_000,
            "e1_neighborhood_hashes": 2_000,
        },
        "independent_final_audit": {
            "path": str(audit_path),
            "sha256": sha256_file(audit_path),
            **audit,
        },
        "semantic_validation": {
            "all_consumed_candidates_exact_world_validated_before_admission": True,
            "all_admitted_neighborhoods_passed_11_role_and_single_edit_gates": True,
            "fact_flip_exact_map_changes": True,
            "sham_and_neutral_targets_preserved_within_1e-12": True,
            "matching": "pending frozen Q-R2 feature extraction",
        },
        "authority": {
            "panel_construction": True,
            "feature_extraction": True,
            "head_initialization": False,
            "training": False,
            "heldout_inference": False,
            "outcome_analysis": False,
        },
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    expected = {
        *(f"exclusions/{name}" for name in ["five-field-exclusion-sets.json", "exclusion-set-receipt.json"]),
        *(f"panel/{name}" for name in [*panel_names, "fresh-candidate-text-manifest.jsonl"]),
        "panel-audit/r2-final-panel-audit.json",
        "provenance/q-r2-panel-manifest-v01.json",
    }
    entries = []
    for path in sorted((item for item in RUN_ROOT.rglob("*") if item.is_file()), key=lambda item: item.relative_to(RUN_ROOT).as_posix()):
        rel = path.relative_to(RUN_ROOT).as_posix()
        if rel not in expected:
            raise RuntimeError(f"unexpected file in pre-feature Q-R2 panel tree: {rel}")
        entries.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    if {entry["path"] for entry in entries} != expected:
        missing = sorted(expected - {entry["path"] for entry in entries})
        raise RuntimeError(f"Q-R2 panel construction tree incomplete: {missing}")
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    seal = {
        "schema": "jev-v08q-r2-panel-construction-seal-v01",
        "status": "Q_R2_PANEL_CONSTRUCTION_SEALED_FEATURE_EXTRACTION_PENDING",
        "panel_manifest_sha256": sha256_file(MANIFEST),
        "root_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "entries": entries,
        "entry_count": len(entries),
        "feature_extraction_complete": False,
        "head_initialization": False,
        "training": False,
        "heldout_inference": False,
    }
    SEAL.parent.mkdir(parents=True, exist_ok=True)
    SEAL.write_text(json.dumps(seal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": seal["status"], "root_sha256": seal["root_sha256"], "entry_count": len(entries)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
