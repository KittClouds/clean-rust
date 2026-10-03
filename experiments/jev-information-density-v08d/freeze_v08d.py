"""Validate and seal the metadata-only v0.8D support-capacity protocol."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONTRACT_PATH = HERE / "v08d-contract.json"
RUN_DIR = Path(r"D:\codex-runs\jev-information-density-v08d\common-support-v01")
FREEZE_PATH = RUN_DIR / "freeze-receipt.json"

STATIC_SOURCES = (
    "docs/jev-information-density-v0.8d-common-support.md",
    "experiments/jev-information-density-v08d/v08d-contract.json",
    "experiments/jev-information-density-v08d/discover_v08d_common_support.py",
    "experiments/jev-information-density-v08d/freeze_v08d.py",
    "experiments/jev-information-density-v08d/tests/test_v08d_support.py",
    "experiments/jev-information-density-v08/v08-contract.json",
    "experiments/jev-information-density-v08/select_banks.py",
    "experiments/jev-information-density-v08/audit_generator_outputs.py",
    "experiments/jev-information-density-v08c/phase2c_training_signatures.py",
    "experiments/jev-information-density-v08c/audit_phase2c_training_signatures.py",
    "experiments/jev-information-density-v08c/freeze_phase2c_audit.py",
    "experiments/jev-information-density-v08c/v08c-phase2c-contract.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_contract_and_inputs(contract: dict[str, Any]) -> dict[str, dict[str, str]]:
    require(contract.get("status") == "frozen_before_support_construction", "contract status is not frozen")
    scope = contract["scope"]
    for key in (
        "metadata_only", "training_materialized", "phoenix_access", "model_contact_authorized",
        "prior_banks_or_phases_mutated",
    ):
        expected = key == "metadata_only"
        require(scope.get(key) is expected, f"scope field {key} must be {expected}")
    require(scope.get("model_or_tokenizer_access") is False, "model/tokenizer access must remain disabled")
    require(scope.get("feature_cache_access") is False, "feature-cache access must remain disabled")
    require(scope.get("policy_arms_constructed") is False, "policy arms must not exist in this stage")

    external: dict[str, dict[str, str]] = {}
    for name, item in contract["inputs"].items():
        path = Path(item["path"])
        require(path.is_file(), f"missing input {name}: {path}")
        actual = sha256_file(path)
        require(actual == item["sha256"], f"input hash mismatch for {name}")
        external[name] = {"path": str(path), "sha256": actual}

    parent = contract["parent"]["v08c_integrity_receipt"]
    parent_path = Path(parent["path"])
    require(parent_path.is_file(), "pinned v0.8C integrity receipt is missing")
    parent_hash = sha256_file(parent_path)
    require(parent_hash == parent["sha256"], "pinned v0.8C integrity receipt hash mismatch")
    parent_body = read_json(parent_path)
    require(parent_body.get("status") == "SEALED_BOUNDED_SEARCH_OUTCOME", "v0.8C outcome is not sealed")
    require(parent_body.get("scope", {}).get("model_or_tokenizer_access") is False, "parent records model access")
    require(parent_body.get("scope", {}).get("phoenix_access") is False, "parent records Phoenix access")
    external["v08c_integrity_receipt"] = {"path": str(parent_path), "sha256": parent_hash}

    generation = read_json(Path(contract["inputs"]["generation_receipt"]["path"]))
    require(
        (generation.get("atomic_group_count"), generation.get("family_bundle_count"),
         generation.get("phoenix_in_scope"), generation.get("model_contact_authorized"))
        == (500_000, 24, False, False),
        "generation receipt differs from the frozen expected source",
    )
    preselection = read_json(Path(contract["inputs"]["preselection_audit"]["path"]))
    overlap = read_json(Path(contract["inputs"]["source_overlap_report"]["path"]))
    require(preselection.get("status") == "ready_for_selection", "preselection audit is not ready")
    require(preselection.get("contract_sha256") == sha256_file(ROOT / "experiments/jev-information-density-v08/v08-contract.json"),
            "preselection audit does not reference the local frozen v0.8 contract")
    require(overlap.get("selector_source_sha256") == sha256_file(ROOT / "experiments/jev-information-density-v08/select_banks.py"),
            "preselection audit selector source differs from the local source")
    require(preselection.get("legacy_firewall_collision_group_count") == 0, "legacy firewall collision count is nonzero")
    require(preselection.get("group_records_sha256") == contract["inputs"]["group_records"]["sha256"],
            "preselection audit group-record hash mismatch")
    require((preselection.get("raw_valid_group_count"), preselection.get("eligible_training_group_count"),
             preselection.get("new_tight_eval_group_count")) == (500_000, 416_672, 83_328),
            "preselection population counts differ from the frozen source")

    for registry_path, expected_hash in preselection.get("registry_sha256", {}).items():
        path = Path(registry_path)
        require(path.is_file() and sha256_file(path) == expected_hash, f"firewall registry mismatch: {path}")
        external[f"firewall_registry:{path.name}"] = {"path": str(path), "sha256": expected_hash}

    require(overlap.get("collision_group_count") == 0, "source overlap report contains collisions")
    require(overlap.get("group_records_sha256") == contract["inputs"]["group_records"]["sha256"],
            "source overlap report group-record hash mismatch")
    consistency = read_json(Path(contract["inputs"]["input_target_consistency"]["path"]))
    consistency_detail = consistency.get("input_target_consistency", {})
    require(
        consistency.get("status") == "PASS"
        and consistency.get("group_records_sha256") == contract["inputs"]["group_records"]["sha256"]
        and consistency.get("canonical_group_count") == 500_000
        and consistency.get("metadata_group_count") == 500_000
        and consistency.get("unmatched_metadata_group_count") == 0
        and consistency.get("missing_metadata_group_count") == 0
        and consistency.get("cross_language_model_input_hash_mismatches") == 0
        and consistency.get("cross_language_structural_hash_mismatches") == 0
        and consistency_detail.get("groups") == 500_000
        and consistency_detail.get("conflicting_inputs") == 0,
        "input/target consistency does not pass",
    )
    signatures = read_json(Path(contract["inputs"]["training_equivalence_audit"]["path"]))
    require(signatures.get("status") == "PASS_METADATA_SIGNATURES_RECONSTRUCTED", "signature audit did not pass")
    require(signatures.get("source_hashes", {}).get("group_records_sha256") == contract["inputs"]["group_records"]["sha256"],
            "signature audit is not tied to the pinned group records")
    require(signatures.get("source_row_counts", {}).get("eligible_closed_v05_training_groups") == 416_672,
            "signature audit eligible count mismatch")
    require(signatures.get("source_row_counts", {}).get("held_out_closed_v05_groups") == 83_328,
            "signature audit holdout count mismatch")

    db_path = Path(contract["inputs"]["training_signature_index"]["path"])
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True)
    try:
        counts = (
            connection.execute("SELECT COUNT(*) FROM training_groups").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM training_groups WHERE held_out=0").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM training_groups WHERE held_out=1").fetchone()[0],
        )
    finally:
        connection.close()
    require(counts == (416_672, 416_672, 0), f"training-only signature index row counts mismatch: {counts}")
    return external


def main() -> int:
    if RUN_DIR.exists():
        raise FileExistsError(f"refusing to reuse existing v0.8D run directory: {RUN_DIR}")
    contract = read_json(CONTRACT_PATH)
    external = validate_contract_and_inputs(contract)

    repository_sources = {relative: sha256_file(ROOT / relative) for relative in STATIC_SOURCES}
    # Pin the Rust generator implementation that produced the source receipt.
    generator_root = ROOT / "experiments/jev-information-density-v08/generator"
    generator_files = sorted(
        path for path in generator_root.rglob("*")
        if path.is_file() and (path.suffix == ".rs" or path.name in {"Cargo.toml", "Cargo.lock"})
        and "target" not in path.parts
    )
    require(bool(generator_files), "no v0.8 generator source files found to pin")
    for path in generator_files:
        relative = path.relative_to(ROOT).as_posix()
        repository_sources[relative] = sha256_file(path)

    RUN_DIR.mkdir(parents=True, exist_ok=False)
    receipt = {
        "protocol": contract["protocol"],
        "status": "SEALED_BEFORE_V08D_SUPPORT_CONSTRUCTION",
        "contract_sha256": sha256_file(CONTRACT_PATH),
        "repository_sources": repository_sources,
        "external_inputs": external,
        "design_summary": {
            "target_groups": contract["design"]["target_groups"],
            "support_multiplier": contract["design"]["minimum_support_replays_per_quota"],
            "witness_attempts": contract["design"]["witness_attempts"],
            "exact_training_distance_gate": contract["design"]["exact_training_distance_gate"],
        },
        "authorization": {
            "metadata_only_support_construction": True,
            "policy_arm_construction": False,
            "model_contact": False,
            "model_or_tokenizer_access": False,
            "training_materialized": False,
            "phoenix_access": False,
            "prior_banks_or_phases_mutated": False,
        },
    }
    with FREEZE_PATH.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "status": receipt["status"],
        "contract_sha256": receipt["contract_sha256"],
        "repository_source_count": len(repository_sources),
        "external_input_count": len(external),
        "freeze_receipt": str(FREEZE_PATH),
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
