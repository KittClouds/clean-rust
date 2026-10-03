"""Independent read-only audit of the sealed Q-R1 panel construction tree."""

from __future__ import annotations

import hashlib
import json
import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01")
DEFAULT_RECEIPT = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01-independent-verification-v02.json")
CONTRACT = ROOT / "experiments/jev-information-density-v08q-r1/contracts/q-r1-panel-contract-v01.json"
PACKET_SEAL = ROOT / "experiments/jev-information-density-v08q-r1/seals/q-r1-packet-seal-and-authorization-v01.json"
TRAINING_SOURCE = Path(r"D:\codex-runs\jev-information-density-v08p-r1\v0.8P-R1\replay-attempt-03\training-scope-identities.jsonl")
E1_ID_SOURCE = Path(r"D:\codex-runs\jev-information-density-v08p-r1\v0.8P-R1\prior-reconstruction\prior-panel-identities.jsonl")
P_R2_SOURCE = Path(r"D:\codex-runs\jev-information-density-v08p-r2\v0.8P-R2\panel\panel-occurrence-identities.jsonl")
Q_SOURCE = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02\panel\panel-occurrence-identities.jsonl")
E1_SOURCE = Path(r"D:\codex-runs\jev-information-density-v08p-v05\identity\run-1\canonical-e1-neighborhood-hash-denylist.json")
FIELDS = ("world_id", "root_id", "episode_id", "full_rendered_input_hash", "selector_input_hash")
ROLES = ("anchor", "fact_flip", "sham", *(f"neutral_{i}" for i in range(1, 9)))
EXPECTED_SOURCE_SHA = {
    TRAINING_SOURCE: "0f5cd945f965c291b13375b16367085a8c4f3dced4e5996b0e1ffbadf279d191",
    E1_ID_SOURCE: "5936d6b4e9d6f651edc0406d844709c99108352459ae90494fa327ed7b110ebf",
    P_R2_SOURCE: "08ba6f9676ad6ec816a946f9bb1be37086c7401d7e1c4413f8c09ffe1e6b7573",
    Q_SOURCE: "97a4e45c1f868499e11faf612218d3d9ec44902e17263ca5238933ec0393fa31",
    E1_SOURCE: "50eebeb5790c29b4a75c6f8df849eb4c2865d3c864932bbd7f636b7a0e52a2cd",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def identity_digest(row: dict[str, Any], field: str) -> str:
    return sha256_bytes(f"jev-v08q-exclusion-v01:{field}:{row[field]}".encode("utf-8"))


def source_digest_sets(path: Path) -> dict[str, set[str]]:
    result = {field: set() for field in FIELDS}
    for row in read_jsonl(path):
        for field in FIELDS:
            result[field].add(identity_digest(row, field))
    return result


def verify_tree() -> tuple[dict[str, Any], dict[str, Any]]:
    seal_path = RUN_ROOT / "seals/q-r1-panel-construction-seal-v01.json"
    manifest_path = RUN_ROOT / "provenance/q-r1-panel-manifest-v01.json"
    seal = read_json(seal_path)
    manifest = read_json(manifest_path)
    if seal.get("status") != "Q_R1_PANEL_CONSTRUCTION_SEALED_FEATURE_EXTRACTION_PENDING":
        raise RuntimeError("sealed panel is not in the feature-pending state")
    if manifest.get("status") != "Q_R1_PANEL_CONSTRUCTION_AND_FIVE_FIELD_AUDIT_PASS":
        raise RuntimeError("Q-R1 panel manifest is not PASS")
    if seal.get("panel_manifest_sha256") != sha256_file(manifest_path):
        raise RuntimeError("Q-R1 panel manifest does not match seal")
    contract = read_json(CONTRACT)
    packet = read_json(PACKET_SEAL)
    if manifest.get("contract_sha256") != sha256_file(CONTRACT) or manifest.get("contract_bundle_root_sha256") != packet["contract_bundle_root_sha256"]:
        raise RuntimeError("Q-R1 panel contract/bundle binding mismatch")
    entry_map = {row["path"]: row for row in seal["entries"]}
    if len(entry_map) != len(seal["entries"]):
        raise RuntimeError("duplicate paths in Q-R1 construction seal")
    observed = {path.relative_to(RUN_ROOT).as_posix() for path in RUN_ROOT.rglob("*") if path.is_file() and path != seal_path}
    if observed != set(entry_map):
        raise RuntimeError(f"sealed Q-R1 construction tree has unexpected/missing files: {observed ^ set(entry_map)}")
    for rel, entry in entry_map.items():
        path = RUN_ROOT / Path(rel)
        if path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"Q-R1 panel seal mismatch: {rel}")
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(seal["entries"], key=lambda row: row["path"]))
    if sha256_bytes(payload.encode("utf-8")) != seal.get("root_sha256"):
        raise RuntimeError("Q-R1 panel construction tree root mismatch")
    for path, expected in EXPECTED_SOURCE_SHA.items():
        if sha256_file(path) != expected:
            raise RuntimeError(f"Q-R1 panel source identity changed: {path}")
    return seal, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    if args.receipt.exists():
        raise RuntimeError("refusing to overwrite the independent Q-R1 panel verification receipt")
    seal, manifest = verify_tree()
    exclusion_root = RUN_ROOT / "exclusions"
    exclusions = read_json(exclusion_root / "five-field-exclusion-sets.json")
    if sha256_file(exclusion_root / "five-field-exclusion-sets.json") != manifest["exclusion_sets"]["sha256"]:
        raise RuntimeError("Q exclusion set hash mismatch")
    if sha256_file(exclusion_root / "exclusion-set-receipt.json") != manifest["exclusion_sets"]["receipt_sha256"]:
        raise RuntimeError("Q exclusion receipt hash mismatch")
    training = {field: set(exclusions["training"][field]) for field in FIELDS}
    prior = {field: set(exclusions["prior_panel"][field]) for field in FIELDS}
    e1 = set(exclusions["e1_neighborhood_hashes"])
    if len(e1) != 2_000:
        raise RuntimeError("Q E1 denylist cardinality mismatch")
    if exclusions.get("training_source_sha256") != EXPECTED_SOURCE_SHA[TRAINING_SOURCE]:
        raise RuntimeError("Q-R1 training exclusion source binding mismatch")
    source_rows = [E1_ID_SOURCE, P_R2_SOURCE, Q_SOURCE]
    reconstructed_prior = {field: set() for field in FIELDS}
    for source in source_rows:
        for field, values in source_digest_sets(source).items():
            reconstructed_prior[field].update(values)
    if training != source_digest_sets(TRAINING_SOURCE) or prior != reconstructed_prior:
        raise RuntimeError("Q-R1 five-field exclusion values do not reconstruct from all bound sources")
    if exclusions.get("prior_source_sha256") != "40f0462f2f61e80d3f672222b6ce56c3c90a88d5944cbfcf47e0cb3b9b2901c3":
        raise RuntimeError("Q-R1 prior-source bundle identity mismatch")
    e1_source = read_json(E1_SOURCE)
    if e1 != set(e1_source.get("identity_sha256", [])) or e1_source.get("count") != 2_000:
        raise RuntimeError("Q E1 denylist values do not reconstruct from the bound source")

    panel = RUN_ROOT / "panel"
    identities = read_jsonl(panel / "panel-occurrence-identities.jsonl")
    scope = read_jsonl(panel / "panel-feature-scope.jsonl")
    candidates = read_jsonl(panel / "fresh-candidate-text-manifest.jsonl")
    admission = read_json(panel / "online-admission-receipt.json")
    audit = read_json(RUN_ROOT / "panel-audit/r1-final-panel-audit.json")
    if len(identities) != 22_000 or len(scope) != 22_000 or len(candidates) != 16:
        raise RuntimeError("Q-R1 panel construction cardinality mismatch")
    if admission.get("status") != "Q_R1_ONLINE_PANEL_ADMISSION_PASS" or audit.get("status") != "Q_R1_FRESH_PANEL_FINAL_AUDIT_PASS":
        raise RuntimeError("Q-R1 online or generator final audit not PASS")
    if audit.get("e1_neighborhood_id_collisions") != 0 or not audit.get("family_allocation_pass") or not audit.get("online_admission_keys_equal_final_panel"):
        raise RuntimeError("Q-R1 generator final-audit invariants do not pass")
    for report in audit.get("field_reports", {}).values():
        if report.get("training_intersections") != 0 or report.get("prior_panel_intersections") != 0 or report.get("internal_r1_cross_neighborhood_intersections") != 0:
            raise RuntimeError("Q-R1 generator final-audit field overlap is nonzero")

    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for i, (identity, row) in enumerate(zip(identities, scope, strict=True)):
        if row.get("index") != i or row.get("episode_id") != identity.get("episode_id") or row.get("input_sha256") != identity.get("full_rendered_input_hash"):
            raise RuntimeError(f"Q-R1 feature-scope identity mismatch at row {i}")
        if row.get("neighborhood_id") != identity.get("anchor_id") or row.get("family_slug") != identity.get("family_slug") or row.get("family_id") != identity.get("family_id") or row.get("sequence") != identity.get("sequence") or row.get("role") != identity.get("role"):
            raise RuntimeError(f"Q feature-scope row metadata mismatch at row {i}")
        if sha256_bytes(row["text"].encode("utf-8")) != row["input_sha256"]:
            raise RuntimeError(f"Q-R1 rendered input content hash mismatch at row {i}")
        if identity.get("partition_namespace") != "eval_v08q_r1":
            raise RuntimeError(f"Q-R1 namespace mismatch at row {i}")
        groups[(identity["family_slug"], int(identity["sequence"]))].append(identity)
        for field in FIELDS:
            digest = identity_digest(identity, field)
            if digest in training[field] or digest in prior[field]:
                raise RuntimeError(f"Q identity collision on {field} at row {i}")
    if len(groups) != 2_000:
        raise RuntimeError("Q neighborhood count mismatch")
    family_counts: dict[str, int] = defaultdict(int)
    anchor_ids: set[str] = set()
    global_seen = {field: set() for field in FIELDS}
    for (family, ordinal), rows in groups.items():
        if len(rows) != 11 or [row["role"] for row in rows] != list(ROLES):
            raise RuntimeError(f"Q role count/order mismatch: {family}/{ordinal}")
        if any(row["family_slug"] != family or row["sequence"] != ordinal for row in rows):
            raise RuntimeError(f"Q neighborhood identity mismatch: {family}/{ordinal}")
        anchor = rows[0]["anchor_id"]
        if anchor in anchor_ids:
            raise RuntimeError("duplicate Q neighborhood anchor")
        anchor_ids.add(anchor)
        if sha256_bytes(anchor.encode("utf-8")) in e1:
            raise RuntimeError("Q E1 denylist collision")
        for field in FIELDS:
            values = {identity_digest(row, field) for row in rows}
            if values & global_seen[field]:
                raise RuntimeError(f"Q cross-neighborhood identity collision on {field}")
            global_seen[field].update(values)
        family_counts[family] += 1
    if family_counts != {"exposure_control": 500, "respiratory_monitoring": 500, "salinity_control": 500, "vibration_monitoring": 500}:
        raise RuntimeError(f"Q family allocation mismatch: {dict(family_counts)}")

    log = read_jsonl(panel / "online-admission-log.jsonl")
    accepted = {(row["family"], int(row["candidate_ordinal"])) for row in log if row.get("accepted") is True}
    rejected = [row for row in log if row.get("rejected") is True]
    if len(log) != sum(admission["consumed_by_family"].values()) or any(int(row["candidate_ordinal"]) not in range(700) for row in log):
        raise RuntimeError("Q admission log budget/cardinality mismatch")
    if accepted != set(groups) or len(accepted) != 2_000:
        raise RuntimeError("Q admitted identities do not equal accepted online admission keys")
    if len(rejected) != sum(admission["rejected_by_family"].values()):
        raise RuntimeError("Q admission rejected-count mismatch")
    by_family_log: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in log:
        by_family_log[row["family"]].append(row)
        if row.get("accepted") is True and (row.get("rejected") is not False or row.get("collisions")):
            raise RuntimeError("Q admission accepted a collision or has conflicting disposition")
        if row.get("accepted") is False and (row.get("rejected") is not True or not row.get("collisions")):
            raise RuntimeError("Q rejected admission lacks its collision record")
    for family, rows in by_family_log.items():
        ordinals = [int(row["candidate_ordinal"]) for row in rows]
        if ordinals != list(range(len(rows))) or len(rows) > 700:
            raise RuntimeError(f"Q candidate stream is not the fixed ascending budget: {family}")
        if sum(row.get("accepted") is True for row in rows) != 500:
            raise RuntimeError(f"Q family did not reach exactly 500 admissions: {family}")
        if sum(row.get("rejected") is True for row in rows) != int(admission["rejected_by_family"].get(family, -1)):
            raise RuntimeError(f"Q per-family rejected count mismatch: {family}")
        if len(rows) != int(admission["consumed_by_family"].get(family, -1)):
            raise RuntimeError(f"Q consumed ordinal count mismatch: {family}")
    if set(by_family_log) != set(family_counts):
        raise RuntimeError("Q admission log family set mismatch")
    if len({row["candidate_semantic_id"] for row in candidates}) != 16 or len({row["schema_family_id"] for row in candidates}) != 4:
        raise RuntimeError("Q candidate catalog identity mismatch")
    candidate_schemas: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        candidate_schemas[row["schema_family_id"]].append(row)
        if sha256_bytes(row["text"].encode("utf-8")) != row["text_sha256"]:
            raise RuntimeError("Q candidate text hash mismatch")
    if any(len(rows) != 4 or sorted(int(row["candidate_order"]) for row in rows) != [0, 1, 2, 3] for rows in candidate_schemas.values()):
        raise RuntimeError("Q candidate catalog schema/order mismatch")

    result = {
        "status": "Q_R1_INDEPENDENT_PANEL_VERIFICATION_PASS",
        "panel_root_sha256": seal["root_sha256"],
        "panel_manifest_sha256": seal["panel_manifest_sha256"],
        "neighborhoods": len(groups),
        "occurrences": len(identities),
        "candidate_texts": len(candidates),
        "family_counts": dict(family_counts),
        "admission_log_rows": len(log),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "five_field_cross_neighborhood_collisions": {field: 0 for field in FIELDS},
        "training_prior_e1_collisions": 0,
        "head_initialization": False,
        "training": False,
        "inference": False,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
