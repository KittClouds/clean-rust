"""Fail-closed Phase-B input and boundary preflight; never loads a model."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PHASE_B = Path(__file__).resolve().parent
CONTRACT_PATH = PHASE_B / "phase-b-v01-contract.json"
RUN = Path(r"D:\codex-runs\jev-information-density-v08i\phase-b-v01")
PHASE_A = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean")
PHASE_A_MAT = PHASE_A / "materialized"
PHASE_A_TRAIN = PHASE_A / "training-inputs"
V08G = Path(r"D:\codex-runs\jev-information-density-v08g")
V08G_MAT = V08G / "materialized-inputs"
V07 = Path(r"D:\codex-runs\jev-lfm-variable-v07")
MODEL_DIR = Path(r"D:\codex-runs\jev-lfm-variable-v07\models\lfm2.5-1.2b-base")

PHASE_B_CODE = (
    "preflight_phase_b.py",
    "materialize_phase_b.py",
    "extract_phase_b_features.py",
    "train_phase_b.py",
    "analyze_phase_b.py",
)
REFERENCE_CODE = (
    ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py",
    ROOT / "experiments/jev-frozen-readout-v01/probe.py",
    ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py",
    ROOT / "experiments/jev-information-density-v08g/train_v08g.py",
    ROOT / "experiments/jev-information-density-v08g/analyze_v08g.py",
    ROOT / "experiments/jev-information-density-v08i/assemble_phase_a.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify(path: Path, expected: str, label: str) -> str:
    require(path.is_file(), f"missing {label}: {path}")
    actual = sha256_file(path)
    require(actual == expected, f"{label} hash mismatch: expected {expected}, got {actual}")
    return actual


def indexed_source_hashes(contract: dict[str, Any]) -> dict[str, str]:
    seal = contract["phase_a_seal"]
    paths = {
        "contract_sha256": (ROOT / "experiments/jev-information-density-v08i/phase-a-v02-clean-contract.json", seal["contract_sha256"]),
        "generator_receipt_sha256": (PHASE_A / "generator-receipt.json", seal["generator_receipt_sha256"]),
        "scope_receipt_sha256": (PHASE_A_TRAIN / "scope-receipt.json", seal["scope_receipt_sha256"]),
        "bank_receipt_sha256": (PHASE_A_MAT / "phase-a-bank-receipt.json", seal["bank_receipt_sha256"]),
        "integrity_receipt_sha256": (PHASE_A_MAT / "phase-a-integrity-receipt.json", seal["integrity_receipt_sha256"]),
        "independent_bank_audit_sha256": (PHASE_A_MAT / "phase-a-v02-independent-audit.json", seal["independent_bank_audit_sha256"]),
        "exact_world_train_audit_sha256": (PHASE_A_MAT / "phase-a-v02-exact-world-train-audit.json", seal["exact_world_train_audit_sha256"]),
        "extra_fingerprint_audit_sha256": (PHASE_A_MAT / "phase-a-v02-extra-fingerprint-audit.json", seal["extra_fingerprint_audit_sha256"]),
        "S100_sha256": (PHASE_A_MAT / "S100-groups.jsonl", seal["S100_sha256"]),
        "F100_sha256": (PHASE_A_MAT / "F100-groups.jsonl", seal["F100_sha256"]),
        "selected_train_contrast_certificates_sha256": (PHASE_A_MAT / "selected-train-contrast-certificates.jsonl", seal["selected_train_contrast_certificates_sha256"]),
        "train_canonical_episodes_sha256": (PHASE_A / "train-canonical-episodes.jsonl", seal["train_canonical_episodes_sha256"]),
        "train_exact_world_episodes_sha256": (PHASE_A / "train-exact-world-episodes.jsonl", seal["train_exact_world_episodes_sha256"]),
        "train_contrast_certificates_sha256": (PHASE_A / "train-contrast-certificates.jsonl", seal["train_contrast_certificates_sha256"]),
        "heldout_canonical_episodes_sha256": (PHASE_A / "eval-canonical-episodes.jsonl", seal["heldout_canonical_episodes_sha256"]),
        "heldout_contrast_certificates_sha256": (PHASE_A / "eval-contrast-certificates.jsonl", seal["heldout_contrast_certificates_sha256"]),
        "state_inputs_sha256": (PHASE_A_MAT / "state-inputs.jsonl", seal["state_inputs_sha256"]),
        "candidate_name_definition_sha256": (PHASE_A_MAT / "candidate-inputs-name_definition.jsonl", seal["candidate_name_definition_sha256"]),
    }
    return {name: verify(path, expected, name) for name, (path, expected) in paths.items()}


def verify_phase_a_semantics(contract: dict[str, Any]) -> dict[str, Any]:
    generator = read_json(PHASE_A / "generator-receipt.json")
    scope = read_json(PHASE_A_TRAIN / "scope-receipt.json")
    bank = read_json(PHASE_A_MAT / "phase-a-bank-receipt.json")
    integrity = read_json(PHASE_A_MAT / "phase-a-integrity-receipt.json")
    independent = read_json(PHASE_A_MAT / "phase-a-v02-independent-audit.json")
    exact = read_json(PHASE_A_MAT / "phase-a-v02-exact-world-train-audit.json")
    extra = read_json(PHASE_A_MAT / "phase-a-v02-extra-fingerprint-audit.json")

    require(generator.get("protocol_contract_sha256") == contract["phase_a_seal"]["contract_sha256"], "generator is not bound to the sealed Phase-A contract")
    require(generator.get("train_pairs") == 12_000 and generator.get("eval_pairs") == 2_000, "Phase-A pair counts drifted")
    require(len(generator.get("train_family_ids", [])) == 12 and len(generator.get("eval_family_ids", [])) == 4, "Phase-A family split drifted")
    require(not set(generator["train_family_ids"]) & set(generator["eval_family_ids"]), "train/eval world-family overlap")
    require(not set(generator["train_template_ids"]) & set(generator["eval_template_ids"]), "train/eval template overlap")

    require(scope.get("source_scope") == "training_only" and scope.get("source_bank") == "R100-star", "representation scope is not training-only R100-star")
    require(scope.get("source_row_count") == 100_000, "training-only source count drifted")
    for key in ("contains_eval_ids", "contains_eval_family_ids", "contains_eval_text"):
        require(scope.get(key) is False, f"scope receipt does not prove {key}=false")
    require(scope.get("canonical_scan", {}).get("protected_eval_episode_bodies_parsed") == 0, "Phase-A scope parsed protected eval bodies")
    require(scope.get("canonical_scan", {}).get("nonselected_record_bodies_json_decoded") == 0, "Phase-A scope decoded nonselected bodies")
    require(scope.get("canonical_scan", {}).get("eval_text_materialized") is False, "Phase-A scope materialized protected eval text")

    require(bank.get("status") == "PHASE_A_BANKS_BUILT_NO_MODEL_CONTACT", "Phase-A bank receipt is not promotable")
    require(integrity.get("status") == "PASS_NO_MODEL_CONTACT", "Phase-A integrity receipt is not PASS")
    require(integrity.get("model_contact") is False and integrity.get("phase_b_authorization") is False, "Phase A crossed its model boundary")
    require(independent.get("status") == "PASS_NO_MODEL_CONTACT", "independent Phase-A audit failed")
    require(independent.get("contract_sha256") == contract["phase_a_seal"]["contract_sha256"], "independent audit contract hash mismatch")
    measurements = independent["independent_bank_recomputation"]
    require(measurements.get("S100_groups") == 100_000 and measurements.get("F100_groups") == 100_000, "Phase-A bank size mismatch")
    require(measurements.get("D_train") == contract["primary_treatment"]["expected_D_train"], "Phase-A D_train mismatch")
    require(measurements.get("common_skeleton_count") == 90_000 and measurements.get("common_skeleton_rows_equal") is True, "Phase-A common skeleton mismatch")
    require(all(measurements.get("profile_equal", {}).values()), "Phase-A matched profiles fail")
    require(exact.get("status") == "PASS" and exact.get("episodes") == 36_000 and exact.get("failed") == 0, "exact-world train audit failed")
    require(exact.get("heldout_episode_bodies_opened") is False, "Phase-A exact audit opened held-out bodies")
    require(extra.get("status") == "PASS", "supplemental protected-fingerprint audit failed")
    overlaps = extra.get("cross_scope_overlap_counts", {})
    require(len(overlaps) == 16 and all(value == 0 for value in overlaps.values()), "one or more available protected fingerprint classes overlap")
    require(extra.get("protected_evaluation_bodies_opened") is False and extra.get("canonical_evaluation_archive_opened") is False, "supplemental audit opened protected bodies")

    integrity_items = integrity.get("verified_files", {})
    for name, expected in bank.get("files", {}).items():
        path = PHASE_A_MAT / name
        require(sha256_file(path) == expected, f"Phase-A bank receipt file changed: {name}")
        item = integrity_items.get(name)
        require(item and item.get("verified") is True and item.get("sha256") == expected, f"Phase-A integrity receipt mismatch: {name}")
    return {"generator": generator, "scope": scope, "bank": bank, "integrity": integrity,
            "independent": independent, "exact": exact, "extra": extra}


def verify_reference_assets(contract: dict[str, Any]) -> dict[str, Any]:
    refs = contract["reference_assets"]
    manifest_path = V08G / "v08g-run-manifest.json"
    auth_path = V08G / "preflight/model-contact-authorization.json"
    materialization_path = V08G_MAT / "materialization-receipt.json"
    extraction_path = V08G / "feature-cache/extraction-receipt.json"
    checks = {
        "v08g_contract": (ROOT / "experiments/jev-information-density-v08g/v08g-contract.json", refs["v08g_contract_sha256"]),
        "v08g_run_manifest": (manifest_path, refs["v08g_run_manifest_sha256"]),
        "v08g_model_contact_receipt": (auth_path, refs["v08g_model_contact_receipt_sha256"]),
        "v08g_materialization_receipt": (materialization_path, refs["v08g_materialization_receipt_sha256"]),
        "v08g_extraction_receipt": (extraction_path, refs["v08g_extraction_receipt_sha256"]),
        "v08g_newtight_eval_groups": (V08G_MAT / "new_tight_eval-groups.jsonl", refs["v08g_newtight_eval_groups_sha256"]),
        "v08g_feature_cache": (V08G / "feature-cache/lfm-v08g-features.pt", refs["v08g_feature_cache_sha256"]),
        "v07_feature_cache": (V07 / "features/lfm2.5-1.2b-base-features.pt", refs["v07_feature_cache_sha256"]),
        "v07_feature_manifest": (V07 / "features/lfm2.5-1.2b-base-feature-manifest.json", refs["v07_feature_manifest_sha256"]),
        "v07_binding_feature_cache": (V07 / "features/binding/lfm2.5-1.2b-base-features.pt", refs["v07_binding_feature_cache_sha256"]),
        "v07_binding_feature_manifest": (V07 / "features/binding/lfm2.5-1.2b-base-feature-manifest.json", refs["v07_binding_feature_manifest_sha256"]),
    }
    hashes = {name: verify(path, expected, name) for name, (path, expected) in checks.items()}

    manifest = read_json(manifest_path)
    auth = read_json(auth_path)
    materialization = read_json(materialization_path)
    extraction = read_json(extraction_path)
    require(auth.get("status") == "PASS" and auth.get("model_contact_authorized") is True and auth.get("phoenix_access") is False, "v0.8G reference authorization receipt failed")
    require(auth.get("manifest_sha256") == refs["v08g_run_manifest_sha256"], "v0.8G manifest authorization mismatch")
    require(manifest.get("model", {}).get("revision") == contract["model"]["revision"], "pinned LFM revision differs from v0.8G")
    require(materialization.get("status") == "EXACT_ID_INPUTS_MATERIALIZED_NO_MODEL_LOADED", "v0.8G materialization receipt failed")
    require(extraction.get("status") == "FEATURE_EXTRACTION_COMPLETE", "v0.8G feature extraction receipt failed")
    require(extraction.get("model", {}).get("revision") == contract["model"]["revision"], "v0.8G feature revision mismatch")
    require(extraction.get("path", {}).get("batch_size") == 1 and extraction.get("path", {}).get("padding") is False, "v0.8G frozen extraction path mismatch")

    for table in materialization.get("representation_tables", {}).values():
        require(sha256_file(Path(table["path"])) == table["sha256"], f"v0.8G text table changed: {table['path']}")
    for name in ("random", "curated", "new_tight_eval"):
        row = materialization["group_files"][name]
        require(sha256_file(Path(row["path"])) == row["sha256"], f"v0.8G group file changed: {name}")
    for split, entry in manifest["frozen_inputs"]["legacy_protected"].items():
        require(sha256_file(Path(entry["path"])) == entry["sha256"], f"legacy {split} identity manifest changed")
    binding = manifest["frozen_inputs"]["contradictory_binding_eval"]
    for key in ("group_id_manifest", "feature_cache", "feature_manifest"):
        item = binding[key]
        require(sha256_file(Path(item["path"])) == item["sha256"], f"binding input changed: {key}")

    v07_manifest = read_json(V07 / "features/lfm2.5-1.2b-base-feature-manifest.json")
    binding_manifest = read_json(V07 / "features/binding/lfm2.5-1.2b-base-feature-manifest.json")
    for item in (v07_manifest, binding_manifest):
        require(item.get("revision") == contract["model"]["revision"] and item.get("backbone_frozen") is True, "v0.7 collateral feature cache has wrong model identity")
    return {"hashes": hashes, "manifest": manifest, "materialization": materialization,
            "extraction": extraction, "v07_feature_manifest": v07_manifest,
            "binding_feature_manifest": binding_manifest}


def verify_model_snapshot(contract: dict[str, Any]) -> dict[str, str]:
    result = {}
    for name, expected in contract["model"]["snapshot_file_sha256"].items():
        result[name] = verify(MODEL_DIR / name, expected, f"model snapshot {name}")
    return result


def verify_heldout_certificates(contract: dict[str, Any]) -> dict[str, Any]:
    path = PHASE_A / "eval-contrast-certificates.jsonl"
    counts: Counter[str] = Counter()
    total = 0
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            require(row.get("partition") == "eval", f"non-eval contrast certificate at line {line_no}")
            counts[str(row.get("world_family_id", ""))] += 1
            total += 1
    expected = set(read_json(PHASE_A / "generator-receipt.json")["eval_family_ids"])
    require(total == 2_000 and set(counts) == expected and all(value == 500 for value in counts.values()), "held-out contrast certificate composition mismatch")
    return {"pair_count": total, "family_counts": dict(sorted(counts.items())),
            "certificate_sha256": contract["phase_a_seal"]["heldout_contrast_certificates_sha256"],
            "canonical_episode_sha256": contract["phase_a_seal"]["heldout_canonical_episodes_sha256"]}


def main() -> int:
    contract = read_json(CONTRACT_PATH)
    require(contract.get("run_identity") == "phase-b-v01-clean", "wrong Phase-B run identity")
    require(contract["boundaries"]["modify_phase_a_v02_or_v01"] is False, "contract permits Phase-A mutation")
    require(contract["boundaries"]["Phoenix"] is False, "contract permits Phoenix")
    contract_hash = sha256_file(CONTRACT_PATH)

    phase_a_hashes = indexed_source_hashes(contract)
    phase_a = verify_phase_a_semantics(contract)
    references = verify_reference_assets(contract)
    model_files = verify_model_snapshot(contract)
    heldout = verify_heldout_certificates(contract)

    source_code_hashes: dict[str, str] = {}
    for relative, expected in read_json(ROOT / "experiments/jev-information-density-v08i/phase-a-v02-clean-contract.json")["source_code_sha256"].items():
        source_code_hashes[relative] = verify(ROOT / relative, expected, f"Phase-A source code {relative}")
    for path in REFERENCE_CODE:
        source_code_hashes[str(path.relative_to(ROOT))] = sha256_file(path)
    for name in PHASE_B_CODE:
        path = PHASE_B / name
        require(path.is_file(), f"missing Phase-B implementation file: {path}")
        source_code_hashes[str(path.relative_to(ROOT))] = sha256_file(path)

    require(not RUN.exists(), f"Phase-B run root already exists; refusing reuse: {RUN}")
    RUN.mkdir(parents=True)
    preflight_dir = RUN / "preflight"
    preflight_dir.mkdir()
    receipt = {
        "protocol": contract["protocol"],
        "run_identity": contract["run_identity"],
        "status": "PASS",
        "model_contact_authorized": True,
        "authorized_by": "explicit user authorization in current task, 2026-09-21",
        "contract_sha256": contract_hash,
        "phase_a_identity": "phase-a-v02-clean",
        "v01_parentage": False,
        "verified_phase_a_sha256": phase_a_hashes,
        "phase_a_bank": {
            "S100_groups": phase_a["independent"]["independent_bank_recomputation"]["S100_groups"],
            "F100_groups": phase_a["independent"]["independent_bank_recomputation"]["F100_groups"],
            "D_train": phase_a["independent"]["independent_bank_recomputation"]["D_train"],
            "common_skeleton_count": phase_a["independent"]["independent_bank_recomputation"]["common_skeleton_count"],
        },
        "heldout_contrasts": heldout,
        "verified_reference_assets": references["hashes"],
        "verified_model_snapshot_sha256": model_files,
        "source_code_sha256": source_code_hashes,
        "documentation_sha256": {
            "phase_b_protocol": sha256_file(ROOT / "docs/jev-information-density-v0.8i-phase-b.md"),
            "engineering_corrections": sha256_file(PHASE_B / "engineering-corrections.md"),
        },
        "protected_eval_boundary_receipts_pass": True,
        "model_loaded": False,
        "feature_extraction": False,
        "training": False,
        "evaluation_inference": False,
        "phoenix_access": False,
        "phase_b_started": False,
    }
    path = preflight_dir / "model-contact-authorization.json"
    path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "contract_sha256": contract_hash,
                      "D_train": receipt["phase_a_bank"]["D_train"],
                      "heldout_pairs": heldout["pair_count"], "model_loaded": False,
                      "authorization_receipt": str(path)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
