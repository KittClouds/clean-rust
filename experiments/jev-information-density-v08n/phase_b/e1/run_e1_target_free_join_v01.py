"""Seal an identity-only candidate-feature join for all v0.8N held-out rows.

The panel neighborhood file is hashed as sealed input, but only anchor_id and
schema_family_id string fields are projected from each row. Targets, body text,
feature scope, candidate outcomes, heads, predictions, and metrics are never
parsed or used. No panel unlock is created or modified.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[4]
E1 = ROOT / "experiments/jev-information-density-v08n/phase_b/e1"
CONTRACT_PATH = E1 / "e1-repair-contract-v01.json"
AUTH_PATH = E1 / "e1-candidate-extraction-authorization-v01.json"
MANIFEST_PATH = E1 / "e1-candidate-text-manifest-v01.jsonl"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-eval-panel-v01")
E1_ROOT = Path(r"D:\codex-runs\jev-information-density-v08n-e1\v0.8N-E1-heldout-candidate-basis-v01")
EXPECTED = {
    "contract": "770d2e3a548e4e31e6a1e7af878f19db925f901666c5bceecd0c11454ee858e2",
    "authorization": "e1b0c2894eaa9330cabdb500330570d6d0edad9bba7a3067d2df41b10f32552f",
    "manifest": "7987ae385454b32ddec548e48ef6543253b7b061ee1f077c064363c06304a285",
    "neighborhoods": "031e834e784868c16e3a71cd8f1c5ccab88c81ff496c6b062d535266a33028ac",
    "panel_manifest": "80e09c0f203b8a6505e062a2091a594273dca808258ff2f4539ab8414db9eabe",
    "panel_seal": "425cef320df94e2b47b448203f8a916ebcbb2019539b2d09e51f5b4ced92f614",
    "panel_tree": "fc0adf7f8d1b9a10914dd9aa85282a42b0cd4bbe185f8b09710498b556d0f08f",
    "unlock": "e8ff5e4548ab5e0b2b96433d844c64836aa03ff878034381c1933db913cb3ec0",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_new_json(path: Path, value: Any) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()


def write_new_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows).encode("utf-8")
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def project_string_field(line: str, key: str) -> str:
    """Decode exactly one JSON string field without parsing other values."""
    pattern = re.compile(r'"' + re.escape(key) + r'"\s*:\s*("(?:\\.|[^"\\])*")')
    matches = pattern.findall(line)
    if len(matches) != 1:
        raise ValueError(f"identity projection expected exactly one {key!r} field")
    value = json.loads(matches[0])
    if not isinstance(value, str) or not value:
        raise ValueError(f"identity projection field {key!r} is not a non-empty string")
    return value


def project_neighborhood_identities(path: Path) -> list[dict[str, str]]:
    projected: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            projected.append({
                "anchor_id": project_string_field(line, "anchor_id"),
                "schema_family_id": project_string_field(line, "schema_family_id"),
            })
    return projected


def project_panel_neighborhood_ids(path: Path) -> list[str]:
    projected: list[str] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                projected.append(project_string_field(line, "neighborhood_id"))
    return projected


def main() -> int:
    for key, path in (("contract", CONTRACT_PATH), ("authorization", AUTH_PATH), ("manifest", MANIFEST_PATH)):
        if sha256_file(path) != EXPECTED[key]:
            raise RuntimeError(f"E1 sealed input hash mismatch: {key}")
    contract = load_json(CONTRACT_PATH)
    authorization = load_json(AUTH_PATH)
    if authorization["status"] != "EXPLICITLY_AUTHORIZED_EXTRACTION_AND_TARGET_FREE_JOIN_ONLY":
        raise RuntimeError("separate E1 extraction/join authorization missing")
    if authorization["second_panel_opening_authorized"] is not False or authorization["head_inference_authorized"] is not False:
        raise RuntimeError("authorization permits an out-of-scope panel opening or inference")

    feature_dir = E1_ROOT / "feature-cache"
    tensor_path = feature_dir / "heldout-candidate-features.pt"
    feature_receipt_path = feature_dir / "heldout-candidate-feature-receipt.json"
    token_path = feature_dir / "heldout-candidate-token-lengths.json"
    parity_path = feature_dir / "repeat-parity-receipt.json"
    tree_path = E1_ROOT / "extraction-artifact-hash-tree.json"
    for path in (tensor_path, feature_receipt_path, token_path, parity_path, tree_path):
        if not path.is_file():
            raise FileNotFoundError(f"sealed E1 feature artifact missing: {path}")
    extraction_tree = load_json(tree_path)
    if extraction_tree["status"] != "E1_FEATURE_BASIS_HASH_TREE_SEALED_PENDING_TARGET_FREE_JOIN_AUDIT":
        raise RuntimeError("E1 extraction tree status is not eligible for the join audit")
    for relpath, expected in extraction_tree["files"].items():
        if sha256_file(E1_ROOT / relpath) != expected:
            raise RuntimeError(f"E1 extraction artifact hash mismatch: {relpath}")
    feature_receipt = load_json(feature_receipt_path)
    parity = load_json(parity_path)
    if feature_receipt["status"] != "E1_CANDIDATE_BASIS_EXTRACTED_REPEAT_PASS_PENDING_JOIN_AUDIT":
        raise RuntimeError("E1 feature receipt status mismatch")
    if parity["status"] != "PASS_INDEPENDENT_CLEAN_PROCESS_REPEAT" or parity["max_absolute_error"] > 1e-5:
        raise RuntimeError("independent extraction repeat did not pass the frozen tolerance")
    tensor = torch.load(tensor_path, map_location="cpu", weights_only=True)
    if tuple(tensor.shape) != (16, 2048) or tensor.dtype != torch.float32 or not torch.isfinite(tensor).all().item():
        raise RuntimeError("E1 candidate feature tensor shape/dtype/finite validation failed")

    neighborhoods_path = PANEL / "semantic-scope/heldout-neighborhoods.jsonl"
    panel_manifest_path = PANEL / "matched-panel-v02/heldout-matched-panel-manifest.jsonl"
    panel_seal_path = PANEL / "seal/seal-manifest.json"
    panel_tree_path = PANEL / "seal/heldout-panel-hash-tree.json"
    unlock_path = RUN / "panel-unlock-receipt.json"
    source_paths = {
        "neighborhood_identities": neighborhoods_path,
        "panel_manifest": panel_manifest_path,
        "panel_seal": panel_seal_path,
        "panel_hash_tree": panel_tree_path,
        "original_unlock": unlock_path,
    }
    source_hashes = {key: sha256_file(path) for key, path in source_paths.items()}
    expected_source_hashes = {
        "neighborhood_identities": EXPECTED["neighborhoods"],
        "panel_manifest": EXPECTED["panel_manifest"],
        "panel_seal": EXPECTED["panel_seal"],
        "panel_hash_tree": EXPECTED["panel_tree"],
        "original_unlock": EXPECTED["unlock"],
    }
    if source_hashes != expected_source_hashes:
        raise RuntimeError(f"sealed panel metadata or opening receipt hash mismatch: {source_hashes}")
    panel_seal = load_json(panel_seal_path)
    panel_tree = load_json(panel_tree_path)
    unlock = load_json(unlock_path)
    if unlock.get("opening_count") != 1 or unlock.get("panel_identity") != "v0.8N-eval-panel-v01/matched-panel-v02":
        raise RuntimeError("original panel opening identity/count changed")
    if panel_seal.get("identity") != "v0.8N-eval-panel-v01" or panel_tree.get("panel_manifest") != EXPECTED["panel_manifest"]:
        raise RuntimeError("sealed held-out panel identity does not reconcile")

    candidate_rows = load_jsonl(MANIFEST_PATH)
    candidate_rows.sort(key=lambda row: int(row["candidate_vector_index"]))
    feature_records = feature_receipt["row_records"]
    if len(candidate_rows) != 16 or len(feature_records) != 16:
        raise RuntimeError("E1 candidate/feature row count differs from 16")
    by_schema: dict[str, list[dict[str, Any]]] = {}
    feature_index: dict[str, int] = {}
    feature_hash_by_id: dict[str, str] = {}
    for row, feature in zip(candidate_rows, feature_records):
        semantic_id = row["candidate_semantic_id"]
        index = int(row["candidate_vector_index"])
        if feature["candidate_semantic_id"] != semantic_id or feature["schema_family_id"] != row["schema_family_id"] or int(feature["candidate_vector_index"]) != index:
            raise RuntimeError(f"feature identity does not bind exact text-manifest row {index}")
        if semantic_id in feature_index:
            raise RuntimeError(f"duplicate candidate semantic identity: {semantic_id}")
        feature_index[semantic_id] = index
        feature_hash_by_id[semantic_id] = feature["feature_sha256"]
        by_schema.setdefault(row["schema_family_id"], []).append(row)
    if any(len(rows) != 4 for rows in by_schema.values()) or len(by_schema) != 4:
        raise RuntimeError("E1 feature basis must contain four ordered unique candidates per schema")

    neighborhood_rows = project_neighborhood_identities(neighborhoods_path)
    panel_ids = project_panel_neighborhood_ids(panel_manifest_path)
    if len(neighborhood_rows) != 2000 or len({row["anchor_id"] for row in neighborhood_rows}) != 2000:
        raise RuntimeError("held-out neighborhood identity projection is not 2000 unique rows")
    if len(panel_ids) != 2000 or len(set(panel_ids)) != 2000:
        raise RuntimeError("sealed held-out panel manifest does not contain 2000 unique neighborhoods")
    if set(panel_ids) != {row["anchor_id"] for row in neighborhood_rows}:
        raise RuntimeError("held-out schema identities do not exactly join to the sealed panel manifest")

    expected_counts = contract["evaluation_panel"]["schema_counts"]
    observed_counts: Counter[str] = Counter(row["schema_family_id"] for row in neighborhood_rows)
    if dict(sorted(observed_counts.items())) != dict(sorted(expected_counts.items())):
        raise RuntimeError(f"held-out schema counts differ from the sealed E1 contract: {dict(observed_counts)}")
    if set(observed_counts) != set(by_schema):
        raise RuntimeError("held-out schemas and E1 candidate basis namespaces differ")

    joined: list[dict[str, Any]] = []
    for neighborhood in sorted(neighborhood_rows, key=lambda row: row["anchor_id"]):
        schema_id = neighborhood["schema_family_id"]
        candidates = by_schema[schema_id]
        semantic_ids = [row["candidate_semantic_id"] for row in candidates]
        if len(semantic_ids) != 4 or len(set(semantic_ids)) != 4:
            raise RuntimeError(f"schema candidate order is ambiguous: {schema_id}")
        if any(feature_index.get(identity) is None for identity in semantic_ids):
            raise RuntimeError(f"missing exact candidate feature identity for neighborhood {neighborhood['anchor_id']}")
        joined.append({
            "neighborhood_id": neighborhood["anchor_id"],
            "schema_family_id": schema_id,
            "candidate_semantic_ids": semantic_ids,
            "candidate_feature_rows": [
                {
                    "candidate_semantic_id": identity,
                    "feature_row_index": feature_index[identity],
                    "feature_sha256": feature_hash_by_id[identity],
                }
                for identity in semantic_ids
            ],
            "join_key": "exact schema_family_id + candidate_semantic_id",
            "candidate_order_source": "sealed E1 manifest derived from authoritative generator FamilySpec order",
        })
    if len(joined) != 2000 or any(len(row["candidate_feature_rows"]) != 4 for row in joined):
        raise RuntimeError("not all held-out neighborhoods resolved to exactly four candidate feature rows")

    # Confirm the hashed identity inputs did not drift while the target-free
    # projection was read. Targets/body fields are not decoded or used above.
    if {key: sha256_file(path) for key, path in source_paths.items()} != source_hashes:
        raise RuntimeError("sealed panel metadata changed during the target-free join preflight")

    join_path = E1_ROOT / "target-free-schema-candidate-join-v01.jsonl"
    join_receipt_path = E1_ROOT / "target-free-schema-candidate-join-receipt-v01.json"
    basis_seal_path = E1_ROOT / "e1-candidate-basis-seal-v01.json"
    for path in (join_path, join_receipt_path, basis_seal_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite sealed E1 join artifact: {path}")
    write_new_jsonl(join_path, joined)
    join_receipt = {
        "status": "PASS_TARGET_FREE_EXACT_IDENTITY_JOIN_2000_OF_2000",
        "identity": "v0.8N-E1-target-free-schema-candidate-join-v01",
        "contract_sha256": EXPECTED["contract"],
        "authorization_receipt_sha256": EXPECTED["authorization"],
        "candidate_manifest_sha256": EXPECTED["manifest"],
        "feature_basis_tensor_sha256": feature_receipt["canonical_tensor_sha256"],
        "feature_basis_tensor_file_sha256": sha256_file(tensor_path),
        "feature_basis_receipt_sha256": sha256_file(feature_receipt_path),
        "join_implementation_sha256": sha256_file(Path(__file__).resolve()),
        "panel_metadata_source_sha256": source_hashes,
        "panel_opening_count_before_and_after": 1,
        "second_unlock_created": False,
        "neighborhood_count": len(joined),
        "neighborhoods_joined": len(joined),
        "schema_counts": dict(sorted(observed_counts.items())),
        "candidate_feature_rows_per_neighborhood": 4,
        "missing_candidate_identity_joins": 0,
        "duplicate_candidate_identity_joins": 0,
        "extra_candidate_identity_joins": 0,
        "join_key": "exact schema_family_id + candidate_semantic_id",
        "manifest_row_index_role": "storage index only; never used as candidate-slot mapping",
        "panel_fields_projected": ["anchor_id", "schema_family_id", "neighborhood_id"],
        "heldout_targets_decoded_or_used": False,
        "heldout_body_text_decoded_or_used": False,
        "head_checkpoints_loaded": False,
        "head_inference": False,
        "predictions_or_metrics": False,
        "newtight_or_legacy_access": False,
        "phoenix_access": False,
        "join_manifest_path": str(join_path),
        "join_manifest_sha256": sha256_file(join_path),
    }
    write_new_json(join_receipt_path, join_receipt)

    seal = {
        "status": "E1_CANDIDATE_BASIS_AND_TARGET_FREE_JOIN_SEALED",
        "identity": "v0.8N-E1-heldout-candidate-semantic-basis-recovery-v01",
        "original_phase_b_status": "EVALUATION_INPUT_CONTRACT_INCOMPLETE",
        "contract_sha256": EXPECTED["contract"],
        "authorization_receipt_sha256": EXPECTED["authorization"],
        "candidate_manifest_sha256": EXPECTED["manifest"],
        "candidate_count": 16,
        "feature_shape": [16, 2048],
        "feature_dtype": "float32",
        "feature_tensor_sha256": feature_receipt["canonical_tensor_sha256"],
        "repeat_parity_sha256": sha256_file(parity_path),
        "repeat_max_absolute_error": parity["max_absolute_error"],
        "join_receipt_sha256": sha256_file(join_receipt_path),
        "join_manifest_sha256": sha256_file(join_path),
        "neighborhoods_resolved": 2000,
        "panel_opening_count": 1,
        "second_panel_opening_authorized": False,
        "head_inference_authorized": False,
        "heldout_targets_or_body_text_used": False,
        "predictions_or_metrics": False,
        "next_gate": "STOP; a separate explicit authorization is required before any second panel opening, head loading, or inference.",
    }
    write_new_json(basis_seal_path, seal)
    print(json.dumps({
        "status": seal["status"],
        "features": seal["candidate_count"],
        "tensor_shape": seal["feature_shape"],
        "repeat_max_abs_error": seal["repeat_max_absolute_error"],
        "joins": f"{seal['neighborhoods_resolved']}/2000",
        "panel_opening_count": seal["panel_opening_count"],
        "second_opening": False,
        "head_inference": False,
        "seal_sha256": sha256_file(basis_seal_path),
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
