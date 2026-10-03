from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import numpy as np

import scorer
from output_artifacts import (
    artifact_entry,
    atomic_create_bytes,
    atomic_json,
    jsonl_bytes,
    label_open_receipt,
    metrics_and_bootstrap,
    stage_seal_payload,
    write_prediction_rows,
    write_scored_rows,
)


EXPECTED_ROOTS = {
    "e0_v10_root_sha256": "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd",
    "e1_v04_root_sha256": "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03",
    "e2_v07_root_sha256": "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a",
    "e3_v02_bundle_root_sha256": "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1",
}
SCORING_ROOT_KEYS = tuple(scorer.SCORING_PREDECESSOR_ROOT_KEYS)
CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06"
CONTRACT_STATUS = "SEALED"
CONTRACT_STAGE = "E4_0_CONTRACT"
CONTRACT_SEAL_ID = "FAS_E4_0_CONTRACT_V06_SEAL"
CONTRACT_ARTIFACT_ID = "E4_0_CONTRACT_V06_FINAL"
V05_CONTRACT_SUPERSEDES = {
    "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V05",
    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v05-final.json",
    "bytes": 39_944,
    "sha256": "ad709bd1496536e6fb1464bd89a06ec0eed552b89ef4159bfc1aa0f406fcc71a",
}
V05_SEAL_SUPERSEDES = {
    "seal_id": "FAS_E4_0_CONTRACT_V05_SEAL",
    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v05-seal.json",
    "manifest_bytes": 29_668,
    "manifest_sha256": "434e4472275adbd6514e5b6a0e8d905c7a283ea6ea294edc0068c050336cd9eb",
    "root_sha256": "38fa25b9433319fc706a1d7fc1e56f20a267f30d467c42ac75ff0850ec656fd1",
    "contract_member_artifact_id": "E4_0_CONTRACT_V05_FINAL",
}
V05_SUPERSEDED_CONTRACT_ARTIFACT_ID = "E4_0_CONTRACT_V05_SUPERSEDED"
V05_SUPERSEDED_SEAL_ARTIFACT_ID = "E4_0_CONTRACT_V05_SEAL_SUPERSEDED"
SEAL_SCHEMA = "FAS_E4_0_ARTIFACT_SEAL_V01"
E2_REFERENCE_CACHE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
E2_REFERENCE_CACHE_BYTES = 872_415_232
FEATURE_CACHE_ARTIFACT = "feature_cache"
FEATURE_ROW_MANIFEST_ARTIFACT = "population_row_manifest"
FEATURE_RECEIPT_ARTIFACT = "feature_extraction_receipt"
PARITY_PANEL_RECEIPT_ARTIFACT = "selection_receipt"
ROW_MANIFEST_ARTIFACT = "E4_POPULATION_ROW_MANIFEST_V01"
PRIMARY_LABEL_ARTIFACT = "E4_PRIMARY_TERMINAL_LABELS_V01"
ESCROW_LABEL_ARTIFACT = "E4_TEMPLATE_JOINT_ESCROW_LABELS_V01"
E3_HEAD_ARTIFACTS = tuple(
    f"e3_v02_{task}_{kind}"
    for task in scorer.TASKS
    for kind in ("mean", "scale", "weight", "bias")
)


@dataclass(frozen=True)
class ExecutionLayout:
    workspace_root: Path
    project_root: Path
    run_root: Path
    authorization_path: Path
    contract_path: Path
    contract_seal_path: Path
    e0_seal_path: Path
    e0_audit_path: Path
    e1_seal_path: Path
    e1_audit_path: Path
    e2_seal_path: Path
    e2_audit_path: Path
    e3_seal_path: Path
    e3_audit_path: Path
    population_seal_path: Path
    population_audit_path: Path
    parity_panel_seal_path: Path
    parity_seal_path: Path
    feature_seal_path: Path


@dataclass(frozen=True)
class SealedEntry:
    artifact_id: str
    path: Path
    relative_path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class VerifiedSeal:
    stage: str
    root_sha256: str
    manifest_sha256: str
    entries: Mapping[str, SealedEntry]
    manifest_path: Path


@dataclass(frozen=True)
class ScoringInputs:
    authorization: Mapping[str, Any]
    auth_identity: scorer.ScoringAuthIdentity
    predecessor_roots: Mapping[str, str]
    contract_sha256: str
    contract_seal_manifest_sha256: str
    contract_seal_root_sha256: str
    population_seal: VerifiedSeal
    feature_seal: VerifiedSeal
    manifest: list[dict[str, Any]]
    primary_manifest: list[dict[str, Any]]
    feature_cache: np.memmap
    heads: Mapping[str, scorer.LinearHead]
    primary_label_entry: SealedEntry


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise RuntimeError(f"invalid JSONL at {path.name}:{line_no}") from error
            if not isinstance(value, dict):
                raise RuntimeError(f"JSONL row is not an object at {path.name}:{line_no}")
            rows.append(value)
    return rows


def path_tree_root(entries: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["path"].encode("utf-8")):
        digest.update(f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def legacy_artifact_tree_root(entries: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["artifact_id"]):
        digest.update(f'{entry["artifact_id"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def e4_artifact_tree_root(entries: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["artifact_id"].encode("utf-8")):
        digest.update(
            f'{entry["artifact_id"]}\t{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8")
        )
    return digest.hexdigest()


def _safe_member_path(raw_path: Any, root: Path) -> tuple[Path, str]:
    if not isinstance(raw_path, str) or not raw_path:
        raise RuntimeError("artifact seal contains an invalid relative path")
    if "\\" in raw_path or "\t" in raw_path or "\n" in raw_path or "\r" in raw_path:
        raise RuntimeError("artifact seal path contains a forbidden separator")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        raise RuntimeError("artifact seal path is absolute or contains traversal")
    if relative.as_posix() != raw_path:
        raise RuntimeError("artifact seal path is not normalized POSIX text")
    base = root.resolve()
    target = base.joinpath(*relative.parts).resolve()
    if not target.is_relative_to(base):
        raise RuntimeError("artifact seal member escapes its bound root")
    return target, relative.as_posix()


def verify_artifact_seal(
    seal_path: Path,
    *,
    path_root: Path,
    expected_stage: str,
    contract_sha256: str,
    contract_seal_root_sha256: str | None,
    expected_predecessors: Mapping[str, str],
    deferred_member_ids: frozenset[str] = frozenset(),
) -> VerifiedSeal:
    raw_bytes = seal_path.read_bytes()
    manifest = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != SEAL_SCHEMA:
        raise RuntimeError(f"unsupported E4 artifact seal schema: {seal_path}")
    required_fields = {
        "schema", "status", "seal_id", "stage", "path_root_kind", "created_utc",
        "contract_sha256", "contract_seal_root_sha256", "exact_predecessor_roots",
        "entries", "entry_count", "root_sha256",
    }
    if set(manifest) != required_fields:
        raise RuntimeError(f"E4 artifact seal top-level fields differ from the frozen schema: {seal_path}")
    if raw_bytes != canonical_json(manifest):
        raise RuntimeError(f"E4 artifact seal JSON serialization is not canonical: {seal_path}")
    if not isinstance(manifest.get("seal_id"), str) or not manifest["seal_id"] or not isinstance(manifest.get("created_utc"), str):
        raise RuntimeError(f"E4 artifact seal identity/timestamp is malformed: {seal_path}")
    if raw_bytes != canonical_json(manifest):
        raise RuntimeError(f"E4 artifact seal JSON serialization is not canonical: {seal_path}")
    if not isinstance(manifest.get("seal_id"), str) or not manifest["seal_id"] or not isinstance(manifest.get("created_utc"), str):
        raise RuntimeError(f"E4 artifact seal identity/timestamp is malformed: {seal_path}")
    if manifest.get("status") != "SEALED" or manifest.get("stage") != expected_stage:
        raise RuntimeError(f"artifact seal status/stage mismatch: {seal_path}")
    expected_root_kind = "WORKSPACE_ROOT" if expected_stage == CONTRACT_STAGE else "E4_RUN_ROOT"
    if manifest.get("path_root_kind") != expected_root_kind:
        raise RuntimeError(f"artifact seal path root kind mismatch: {seal_path}")
    if manifest.get("contract_sha256") != contract_sha256:
        raise RuntimeError(f"artifact seal binds a different contract: {seal_path}")
    if manifest.get("contract_seal_root_sha256") != contract_seal_root_sha256:
        raise RuntimeError(f"artifact seal binds a different contract seal root: {seal_path}")
    actual_predecessors = manifest.get("exact_predecessor_roots")
    if not isinstance(actual_predecessors, dict):
        raise RuntimeError("artifact seal predecessor roots are malformed")
    for key, value in actual_predecessors.items():
        if key not in expected_predecessors or expected_predecessors[key] != value:
            raise RuntimeError(f"artifact seal predecessor root mismatch for {key}")
    if not set(actual_predecessors).issuperset(expected_predecessors):
        missing = sorted(set(expected_predecessors) - set(actual_predecessors))
        raise RuntimeError(f"artifact seal is missing predecessor roots: {missing}")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("artifact seal has no members")
    if manifest.get("entry_count") != len(entries):
        raise RuntimeError("artifact seal entry count mismatch")
    by_id: dict[str, SealedEntry] = {}
    seen_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"artifact_id", "path", "bytes", "sha256"}:
            raise RuntimeError("artifact seal member fields differ from the frozen schema")
        artifact_id = entry["artifact_id"]
        if not isinstance(artifact_id, str) or not artifact_id or artifact_id in by_id:
            raise RuntimeError("artifact seal has an empty or duplicate artifact ID")
        if isinstance(entry["bytes"], bool) or not isinstance(entry["bytes"], int) or entry["bytes"] < 0:
            raise RuntimeError(f"artifact byte length is malformed for {artifact_id}")
        digest = entry["sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise RuntimeError(f"artifact SHA-256 is malformed for {artifact_id}")
        path, relative_path = _safe_member_path(entry["path"], path_root)
        if relative_path in seen_paths:
            raise RuntimeError(f"artifact seal contains duplicate relative path: {relative_path}")
        seen_paths.add(relative_path)
        if artifact_id not in deferred_member_ids:
            actual_digest, actual_bytes = sha256_file(path)
            if actual_digest != digest or actual_bytes != entry["bytes"]:
                raise RuntimeError(f"sealed artifact bytes/hash mismatch: {artifact_id}")
        by_id[artifact_id] = SealedEntry(
            artifact_id, path, relative_path, entry["bytes"], digest
        )
    computed_root = e4_artifact_tree_root(entries)
    if manifest.get("root_sha256") != computed_root:
        raise RuntimeError(f"artifact seal root mismatch: {seal_path}")
    return VerifiedSeal(
        stage=expected_stage,
        root_sha256=computed_root,
        manifest_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        entries=by_id,
        manifest_path=seal_path,
    )


def verify_legacy_seal(
    path: Path,
    *,
    expected_root: str,
    root_kind: str,
) -> dict[str, Any]:
    seal = read_json(path)
    entries = seal.get("entries")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"legacy seal has no entries: {path}")
    if seal.get("entry_count") != len(entries):
        raise RuntimeError(f"legacy seal entry count mismatch: {path}")
    computed = path_tree_root(entries) if root_kind == "PATH" else legacy_artifact_tree_root(entries)
    if computed != expected_root or seal.get("root_sha256") != expected_root:
        raise RuntimeError(f"legacy predecessor root mismatch: {path}")
    return seal


def _require_audit(path: Path, *, expected_root_key: str, expected_root: str) -> dict[str, Any]:
    audit = read_json(path)
    status = audit.get("status")
    passed_status = status == "PASS" or (isinstance(status, str) and (status.startswith("PASS_") or status.endswith("_PASS") or "_AUDIT_PASS_" in status))
    if audit.get("all_checks_passed") is not True and not passed_status:
        raise RuntimeError(f"independent audit did not pass: {path}")
    root = audit.get(expected_root_key)
    if root != expected_root:
        raise RuntimeError(f"independent audit binds a different root: {path}")
    return audit


def _required_entry(seal: VerifiedSeal, artifact_id: str) -> SealedEntry:
    try:
        return seal.entries[artifact_id]
    except KeyError as error:
        raise RuntimeError(f"required sealed artifact is missing: {artifact_id}") from error


def _require_artifact_content_status(entry: SealedEntry, allowed_statuses: set[str]) -> dict[str, Any]:
    value = read_json(entry.path)
    if value.get("status") not in allowed_statuses:
        raise RuntimeError(f"sealed stage receipt did not pass: {entry.artifact_id}")
    return value


def _require_predecessor_subset(actual: Mapping[str, str], expected: Mapping[str, str], required: Sequence[str]) -> None:
    for key in required:
        if actual.get(key) != expected.get(key):
            raise RuntimeError(f"stage seal does not bind required predecessor {key}")


def _verify_frozen_contract(contract: Mapping[str, Any], static_roots: Mapping[str, str]) -> None:
    if contract.get("contract_id") != CONTRACT_ID:
        raise RuntimeError("final E4-0 contract identity mismatch")
    if contract.get("status") != CONTRACT_STATUS:
        raise RuntimeError("final E4-0 contract is not sealed")
    supersedes = contract.get("supersedes")
    if (
        not isinstance(supersedes, Mapping)
        or set(supersedes) != {"contract", "seal"}
        or supersedes.get("contract") != V05_CONTRACT_SUPERSEDES
        or supersedes.get("seal") != V05_SEAL_SUPERSEDES
    ):
        raise RuntimeError("final E4-0 v06 contract does not bind the exact immutable v05 contract/seal lineage")
    predecessors = contract.get("predecessors")
    if not isinstance(predecessors, Mapping) or set(predecessors) != set(static_roots):
        raise RuntimeError("final E4-0 contract lacks predecessor identities")
    for key, root in static_roots.items():
        if predecessors.get(key) != root:
            raise RuntimeError(f"final E4-0 contract predecessor mismatch: {key}")
    fresh = contract.get("fresh_qualification", {})
    bootstrap = fresh.get("bootstrap", {})
    gate = fresh.get("gate", {})
    population = contract.get("population", {}).get("support", {})
    if (
        bootstrap.get("replicates") != scorer.BOOTSTRAP_REPLICATES
        or bootstrap.get("seed") != scorer.BOOTSTRAP_SEED
        or bootstrap.get("chunk_replicates") != scorer.BOOTSTRAP_CHUNK_REPLICATES
        or bootstrap.get("lower_tail_alpha_per_endpoint") != scorer.BOOTSTRAP_ALPHA
        or tuple(gate.get("endpoint_order", ())) != scorer.ENDPOINT_ORDER
        or gate.get("balanced_accuracy_lower_bound_minimum") != scorer.PERFORMANCE_FLOOR
        or population.get("scoring_minimum_rows_per_class") != scorer.MINIMUM_ROWS_PER_CLASS
    ):
        raise RuntimeError("sealed E4 contract scoring gates differ from the frozen scorer")


def _verify_legacy_predecessors(layout: ExecutionLayout) -> dict[str, str]:
    e0 = verify_legacy_seal(layout.e0_seal_path, expected_root=EXPECTED_ROOTS["e0_v10_root_sha256"], root_kind="PATH")
    e1 = verify_legacy_seal(layout.e1_seal_path, expected_root=EXPECTED_ROOTS["e1_v04_root_sha256"], root_kind="PATH")
    e2 = verify_legacy_seal(layout.e2_seal_path, expected_root=EXPECTED_ROOTS["e2_v07_root_sha256"], root_kind="ARTIFACT")
    e3 = verify_legacy_seal(layout.e3_seal_path, expected_root=EXPECTED_ROOTS["e3_v02_bundle_root_sha256"], root_kind="ARTIFACT")
    if e0.get("status") != "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT":
        raise RuntimeError("E0 v10 predecessor seal status mismatch")
    if e1.get("root_sha256") != EXPECTED_ROOTS["e1_v04_root_sha256"]:
        raise RuntimeError("E1 v04 predecessor identity mismatch")
    if (
        e2.get("feature_cache_sha256") != E2_REFERENCE_CACHE_SHA256
        or e2.get("feature_cache_bytes") != E2_REFERENCE_CACHE_BYTES
    ):
        raise RuntimeError("E2 v07 seal does not bind the frozen E2 v01 comparator cache")
    e2_cache = next(
        (entry for entry in e2["entries"] if entry.get("artifact_id") == "e2_v07_feature_cache"),
        None,
    )
    if (
        not isinstance(e2_cache, Mapping)
        or e2_cache.get("sha256") != E2_REFERENCE_CACHE_SHA256
        or e2_cache.get("bytes") != E2_REFERENCE_CACHE_BYTES
    ):
        raise RuntimeError("E2 v07 seal omits or changes the sealed feature-cache member identity")
    _require_audit(layout.e0_audit_path, expected_root_key="seal_root_sha256", expected_root=EXPECTED_ROOTS["e0_v10_root_sha256"])
    _require_audit(layout.e1_audit_path, expected_root_key="e1_root_sha256", expected_root=EXPECTED_ROOTS["e1_v04_root_sha256"])
    e2_audit = _require_audit(
        layout.e2_audit_path,
        expected_root_key="e2_root_sha256",
        expected_root=EXPECTED_ROOTS["e2_v07_root_sha256"],
    )
    if (
        e2_audit.get("feature_cache_sha256") != E2_REFERENCE_CACHE_SHA256
        or e2_audit.get("feature_cache_bytes") != E2_REFERENCE_CACHE_BYTES
    ):
        raise RuntimeError("independent E2 audit does not bind the frozen comparator cache identity")
    _require_audit(layout.e3_audit_path, expected_root_key="e3_root_sha256", expected_root=EXPECTED_ROOTS["e3_v02_bundle_root_sha256"])
    return dict(EXPECTED_ROOTS)


def _resolved(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def build_layout(workspace_root: Path, authorization_path: Path) -> tuple[ExecutionLayout, dict[str, Any]]:
    """Read only the small authorization JSON, then derive all run paths from it."""
    workspace = workspace_root.resolve()
    project = workspace / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
    authorization = read_json(authorization_path)
    output_root = authorization.get("output_root")
    if not isinstance(output_root, str) or not output_root:
        raise RuntimeError("scoring authorization lacks output_root")
    run = _resolved(output_root)
    e1 = run.parent / "e1-panel-v04"
    e2 = run.parent / "e2-v07"
    e3 = run.parent / "e3-v02"
    return ExecutionLayout(
        workspace_root=workspace,
        project_root=project,
        run_root=run,
        authorization_path=authorization_path.resolve(),
        contract_path=project / "contracts" / "e4-0-contract-v06-final.json",
        contract_seal_path=project / "seals" / "e4-0-contract-v06-seal.json",
        e0_seal_path=project / "seals" / "e0-seal-v10.json",
        e0_audit_path=project / "audits" / "e0-v10-independent-audit-v01.json",
        e1_seal_path=e1 / "e1-seal-v01.json",
        e1_audit_path=project / "audits" / "e1-independent-audit-v04.json",
        e2_seal_path=e2 / "e2-v07-seal.json",
        e2_audit_path=project / "audits" / "e2-v07-independent-audit-v01.json",
        e3_seal_path=e3 / "e3-v02-seal.json",
        e3_audit_path=e3 / "e3-v02-independent-audit-v01.json",
        population_seal_path=run / "seals" / "e4-0-population-v01-seal.json",
        population_audit_path=project / "audits" / "e4-0-population-v01-independent-audit.json",
        parity_panel_seal_path=run / "parity-panel" / "stage-seal-v01.json",
        parity_seal_path=run / "parity" / "stage-seal-v01.json",
        feature_seal_path=run / "features" / "stage-seal-v01.json",
    ), authorization


def _contract_stage_seal(
    layout: ExecutionLayout,
    static_roots: Mapping[str, str],
) -> tuple[VerifiedSeal, str, str]:
    contract_hash, contract_bytes = sha256_file(layout.contract_path)
    seal = verify_artifact_seal(
        layout.contract_seal_path,
        path_root=layout.workspace_root,
        expected_stage=CONTRACT_STAGE,
        contract_sha256=contract_hash,
        contract_seal_root_sha256=None,
        expected_predecessors=static_roots,
    )
    seal_manifest = read_json(layout.contract_seal_path)
    if seal_manifest.get("seal_id") != CONTRACT_SEAL_ID:
        raise RuntimeError("contract seal does not use the exact E4-0 v06 seal identity")
    contract_entry = next(
        (entry for entry in seal.entries.values()
         if entry.artifact_id == CONTRACT_ARTIFACT_ID),
        None,
    )
    if (
        contract_entry is None
        or contract_entry.relative_path != "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v06-final.json"
        or contract_entry.sha256 != contract_hash
        or contract_entry.bytes != contract_bytes
    ):
        raise RuntimeError("contract seal does not bind the exact final v06 contract artifact")
    superseded_members = (
        (
            V05_SUPERSEDED_CONTRACT_ARTIFACT_ID,
            V05_CONTRACT_SUPERSEDES["path"],
            V05_CONTRACT_SUPERSEDES["bytes"],
            V05_CONTRACT_SUPERSEDES["sha256"],
        ),
        (
            V05_SUPERSEDED_SEAL_ARTIFACT_ID,
            V05_SEAL_SUPERSEDES["path"],
            V05_SEAL_SUPERSEDES["manifest_bytes"],
            V05_SEAL_SUPERSEDES["manifest_sha256"],
        ),
    )
    for artifact_id, relative_path, byte_count, digest in superseded_members:
        entry = seal.entries.get(artifact_id)
        if (
            entry is None
            or entry.relative_path != relative_path
            or entry.bytes != byte_count
            or entry.sha256 != digest
        ):
            raise RuntimeError(f"contract seal does not bind exact superseded v05 member {artifact_id}")
    contract = read_json(layout.contract_path)
    _verify_frozen_contract(contract, static_roots)
    return seal, contract_hash, hashlib.sha256(layout.contract_seal_path.read_bytes()).hexdigest()


def _verify_e4_stages(
    layout: ExecutionLayout,
    authorization: Mapping[str, Any],
    contract_hash: str,
    contract_seal: VerifiedSeal,
    static_roots: Mapping[str, str],
) -> tuple[VerifiedSeal, VerifiedSeal, VerifiedSeal, VerifiedSeal, list[dict[str, Any]], list[dict[str, Any]], np.memmap, Path, SealedEntry]:
    roots = authorization.get("exact_predecessor_roots")
    if not isinstance(roots, Mapping):
        raise RuntimeError("scoring authorization predecessor roots are malformed")
    required_keys = set(scorer.SCORING_PREDECESSOR_ROOT_KEYS)
    if set(roots) != required_keys:
        raise RuntimeError("scoring authorization does not bind the exact frozen predecessor-root set")
    for key, value in static_roots.items():
        if roots.get(key) != value:
            raise RuntimeError(f"scoring authorization has the wrong frozen predecessor root: {key}")
    contract_root = contract_seal.root_sha256
    contract_manifest = contract_seal.manifest_sha256
    if (
        authorization.get("contract_sha256") != contract_hash
        or authorization.get("contract_seal_root_sha256") != contract_root
        or authorization.get("contract_seal_manifest_sha256") != contract_manifest
    ):
        raise RuntimeError("scoring authorization is not bound to the independently verified final contract seal")

    pop_expected = dict(static_roots)
    population = verify_artifact_seal(
        layout.population_seal_path,
        path_root=layout.run_root,
        expected_stage="POPULATION_GENERATION",
        contract_sha256=contract_hash,
        contract_seal_root_sha256=contract_root,
        expected_predecessors=pop_expected,
        deferred_member_ids=frozenset({PRIMARY_LABEL_ARTIFACT, ESCROW_LABEL_ARTIFACT}),
    )
    if roots.get("e4_population_root_sha256") != population.root_sha256:
        raise RuntimeError("scoring authorization population root differs from its sealed population")
    population_audit_hash, _ = sha256_file(layout.population_audit_path)
    if roots.get("e4_population_audit_root_sha256") != population_audit_hash:
        raise RuntimeError("scoring authorization does not bind the exact population audit receipt bytes")
    population_audit = _require_audit(
        layout.population_audit_path,
        expected_root_key="population_root_sha256",
        expected_root=population.root_sha256,
    )
    if population_audit.get("status") not in ("PASS_INDEPENDENT_POPULATION_AUDIT", "PASS") and population_audit.get("all_checks_passed") is not True:
        raise RuntimeError("independent E4 population audit status is not PASS")

    panel_expected = {
        **static_roots,
        "e4_population_root_sha256": population.root_sha256,
        "e4_population_audit_root_sha256": population_audit_hash,
    }
    panel = verify_artifact_seal(
        layout.parity_panel_seal_path,
        path_root=layout.run_root,
        expected_stage="PARITY_PANEL_MATERIALIZATION",
        contract_sha256=contract_hash,
        contract_seal_root_sha256=contract_root,
        expected_predecessors=panel_expected,
    )
    if roots.get("e4_parity_panel_root_sha256") != panel.root_sha256:
        raise RuntimeError("scoring authorization parity-panel root differs from its sealed panel")
    _require_artifact_content_status(
        _required_entry(panel, PARITY_PANEL_RECEIPT_ARTIFACT), {"PARITY_PANEL_SEALED"}
    )

    parity_expected = {
        **panel_expected,
        "e4_parity_panel_root_sha256": panel.root_sha256,
    }
    parity = verify_artifact_seal(
        layout.parity_seal_path,
        path_root=layout.run_root,
        expected_stage="ONLINE_CACHE_PARITY",
        contract_sha256=contract_hash,
        contract_seal_root_sha256=contract_root,
        expected_predecessors=parity_expected,
    )
    if roots.get("e4_parity_receipt_root_sha256") != parity.root_sha256:
        raise RuntimeError("scoring authorization parity root differs from its sealed parity receipt")
    parity_receipt = _require_artifact_content_status(_required_entry(parity, "parity_receipt"), {"ONLINE_CACHE_PARITY_PASS"})
    if parity_receipt.get("feature_byte_identical") is not True:
        raise RuntimeError("online/cache parity receipt does not confirm byte-identical features")
    comparator = parity_receipt.get("e2_reference_cache")
    if (
        not isinstance(comparator, Mapping)
        or comparator.get("sha256") != E2_REFERENCE_CACHE_SHA256
        or comparator.get("bytes") != E2_REFERENCE_CACHE_BYTES
    ):
        raise RuntimeError("online/cache parity receipt does not bind the frozen E2 comparator identity")
    maximum_deviation = parity_receipt.get("feature_max_abs_deviation")
    if isinstance(maximum_deviation, bool) or not isinstance(maximum_deviation, (int, float)) or maximum_deviation != 0.0:
        raise RuntimeError("online/cache parity receipt does not report exact zero feature deviation")
    agreement = parity_receipt.get("prediction_agreement_by_head")
    if not isinstance(agreement, Mapping) or set(agreement) != set(scorer.TASKS) or any(value != 1.0 for value in agreement.values()):
        raise RuntimeError("online/cache parity receipt lacks 100 percent agreement for all five heads")

    feature_expected = {
        **parity_expected,
        "e4_parity_receipt_root_sha256": parity.root_sha256,
    }
    features = verify_artifact_seal(
        layout.feature_seal_path,
        path_root=layout.run_root,
        expected_stage="FRESH_FEATURE_EXTRACTION",
        contract_sha256=contract_hash,
        contract_seal_root_sha256=contract_root,
        expected_predecessors=feature_expected,
    )
    if roots.get("e4_feature_cache_root_sha256") != features.root_sha256:
        raise RuntimeError("scoring authorization feature-cache root differs from its sealed extraction")
    feature_receipt = _require_artifact_content_status(
        _required_entry(features, FEATURE_RECEIPT_ARTIFACT), {"FEATURE_CACHE_COMPLETE_GATE_PASS"}
    )
    forbidden_claims = ("predictions_emitted", "labels_opened", "heldout_template_or_joint_labels_opened")
    if any(feature_receipt.get(key) is not False for key in forbidden_claims):
        raise RuntimeError("feature extraction receipt records forbidden predictions or label access")

    row_manifest_entry = _required_entry(population, ROW_MANIFEST_ARTIFACT)
    feature_row_map = _required_entry(features, FEATURE_ROW_MANIFEST_ARTIFACT)
    cache_entry = _required_entry(features, FEATURE_CACHE_ARTIFACT)
    label_entry = _required_entry(population, PRIMARY_LABEL_ARTIFACT)
    _required_entry(population, ESCROW_LABEL_ARTIFACT)  # seal membership only; bytes remain unopened
    if feature_row_map.sha256 != row_manifest_entry.sha256 or feature_row_map.bytes != row_manifest_entry.bytes:
        raise RuntimeError("feature row mapping is not byte-identical to the population row manifest")
    if not label_entry.path.is_file() or label_entry.path.stat().st_size != label_entry.bytes:
        raise RuntimeError("sealed primary terminal label member is absent or has the wrong metadata length")
    if not cache_entry.path.is_file():
        raise RuntimeError("sealed feature cache is absent")

    manifest = read_jsonl(row_manifest_entry.path)
    primary = scorer.validate_primary_manifest(manifest)
    expected_cache_bytes = len(manifest) * scorer.DIMENSION * np.dtype("<f4").itemsize
    if cache_entry.bytes != expected_cache_bytes:
        raise RuntimeError("sealed feature-cache bytes do not equal full row-manifest shape")
    feature_cache_info = feature_receipt.get("feature_cache")
    if not isinstance(feature_cache_info, Mapping):
        raise RuntimeError("feature extraction receipt lacks the frozen feature_cache identity")
    if (
        feature_cache_info.get("path") != cache_entry.relative_path
        or feature_cache_info.get("rows") != len(manifest)
        or feature_cache_info.get("row_count") != len(manifest)
        or feature_cache_info.get("dimension") != scorer.DIMENSION
        or feature_cache_info.get("bytes") != expected_cache_bytes
        or feature_cache_info.get("dtype") != "<f4"
        or feature_cache_info.get("layout") != "C_ROW_MAJOR"
        or feature_cache_info.get("sha256") != cache_entry.sha256
    ):
        raise RuntimeError("feature extraction receipt shape/dtype/hash differs from the sealed feature member")
    row_identity = feature_receipt.get("row_identity")
    if not isinstance(row_identity, Mapping) or (
        row_identity.get("manifest_sha256") != row_manifest_entry.sha256
        or row_identity.get("row_count") != len(manifest)
        or row_identity.get("ordered_row_identity_match") is not True
        or row_identity.get("quartet_atomicity_and_order_verified") is not True
        or row_identity.get("surface_id_values") != ["PRIMARY_SEEN", "HELDOUT_TEMPLATE"]
        or row_identity.get("truth_partition_values") != ["PRIMARY_TERMINAL", "TEMPLATE_ESCROW"]
    ):
        raise RuntimeError("feature extraction receipt row identity differs from the sealed population manifest")
    feature_cache = np.memmap(cache_entry.path, mode="r", dtype="<f4", shape=(len(manifest), scorer.DIMENSION), order="C")
    for start in range(0, len(manifest), 4096):
        stop = min(start + 4096, len(manifest))
        if not np.isfinite(feature_cache[start:stop]).all():
            raise RuntimeError("E4 sealed feature cache contains non-finite values")

    e3_seal = verify_legacy_seal(
        layout.e3_seal_path,
        expected_root=EXPECTED_ROOTS["e3_v02_bundle_root_sha256"],
        root_kind="ARTIFACT",
    )
    e3_entries = e3_seal.get("entries", [])
    e3_by_id = {entry.get("artifact_id"): entry for entry in e3_entries if isinstance(entry, dict)}
    for artifact_id in E3_HEAD_ARTIFACTS:
        entry = e3_by_id.get(artifact_id)
        if not isinstance(entry, dict):
            raise RuntimeError(f"frozen E3 bundle omits required head member {artifact_id}")
        path = Path(entry.get("path", ""))
        if not path.is_absolute() or not path.is_file():
            raise RuntimeError(f"frozen E3 head member path is absent or not absolute: {artifact_id}")
        digest, size = sha256_file(path)
        if digest != entry.get("sha256") or size != entry.get("bytes"):
            raise RuntimeError(f"frozen E3 head member bytes/hash mismatch: {artifact_id}")
        task_kind = artifact_id.removeprefix("e3_v02_")
        task, kind = task_kind.rsplit("_", 1)
        expected_name = f"{task}.{kind}.f32le"
        if path.name != expected_name:
            raise RuntimeError(f"frozen E3 head member path/name mismatch: {artifact_id}")
    return population, panel, parity, features, manifest, primary, feature_cache, layout.e3_seal_path.parent, label_entry


def prepare_scoring_inputs(layout: ExecutionLayout, authorization: Mapping[str, Any]) -> ScoringInputs:
    """Verify all sealed identities and cache/head bytes before any label stream is opened."""
    authorized_output = authorization.get("output_root")
    if not isinstance(authorized_output, str) or _resolved(authorized_output) != layout.run_root:
        raise RuntimeError("CLI run root differs from the exact scoring authorization output_root")
    static_roots = _verify_legacy_predecessors(layout)
    contract_seal, contract_hash, contract_manifest_hash = _contract_stage_seal(layout, static_roots)
    (
        population,
        _panel,
        _parity,
        features,
        manifest,
        primary,
        feature_cache,
        e3_root,
        primary_label_entry,
    ) = _verify_e4_stages(layout, authorization, contract_hash, contract_seal, static_roots)
    roots = dict(authorization["exact_predecessor_roots"])
    expected = scorer.ScoringAuthIdentity(
        contract_sha256=contract_hash,
        contract_seal_manifest_sha256=contract_manifest_hash,
        contract_seal_root_sha256=contract_seal.root_sha256,
        exact_predecessor_roots=roots,
        output_root=str(layout.run_root),
    )
    # Last preflight action before cache inference. This validates stage-only authority.
    scorer.validate_scoring_authorization(authorization, expected)
    # Observer tensor reads occur only after the stage-only authorization is valid.
    heads = scorer.load_frozen_heads(e3_root)
    return ScoringInputs(
        authorization=authorization,
        auth_identity=expected,
        predecessor_roots=roots,
        contract_sha256=contract_hash,
        contract_seal_manifest_sha256=contract_manifest_hash,
        contract_seal_root_sha256=contract_seal.root_sha256,
        population_seal=population,
        feature_seal=features,
        manifest=manifest,
        primary_manifest=primary,
        feature_cache=feature_cache,
        heads=heads,
        primary_label_entry=primary_label_entry,
    )


def execute_scoring(layout: ExecutionLayout, inputs: ScoringInputs) -> dict[str, Any]:
    score_root = layout.run_root / "score"
    if score_root.exists():
        raise RuntimeError(f"scoring output path already exists; preserving prior attempt: {score_root}")
    score_root.mkdir(parents=True, exist_ok=False)
    label_reader: scorer.OneShotPrimaryLabelReader | None = None
    label_receipt: dict[str, Any] | None = None
    try:
        scorer.validate_scoring_authorization(inputs.authorization, inputs.auth_identity)
        primary, predictions = scorer.predict_primary_rows(
            inputs.feature_cache, inputs.manifest, inputs.heads
        )
        if len(primary) != len(inputs.primary_manifest):
            raise RuntimeError("preflight and inference primary row selection counts differ")
        prediction_path = score_root / "predictions-v01.jsonl"
        write_prediction_rows(prediction_path, primary, predictions)

        entry = inputs.primary_label_entry
        label_reader = scorer.OneShotPrimaryLabelReader(
            entry.path,
            expected_sha256=entry.sha256,
            expected_bytes=entry.bytes,
            expected_rows=len(primary),
        )
        label_rows, raw_label_receipt = label_reader.read_once(
            inputs.authorization, inputs.auth_identity
        )
        label_receipt = label_open_receipt(raw_label_receipt)
        label_receipt["label_artifact_id"] = entry.artifact_id
        label_receipt["label_relative_path"] = entry.relative_path
        joined = scorer.join_primary_labels(primary, label_rows, predictions)
        metrics = scorer.score_primary_population(joined)

        scored_rows_path = score_root / "scored-rows-v01.jsonl"
        write_scored_rows(scored_rows_path, joined)
        metrics_out, bootstrap_payload = metrics_and_bootstrap(metrics)
        metrics_path = score_root / "metrics-v01.json"
        bootstrap_path = score_root / "bootstrap-v01.npz"
        label_receipt_path = score_root / "label-open-receipt-v01.json"
        atomic_json(metrics_path, metrics_out)
        atomic_create_bytes(bootstrap_path, bootstrap_payload)
        atomic_json(label_receipt_path, label_receipt)

        disposition = metrics["terminal_disposition"]
        terminal_receipt = {
            "schema": "FAS_E4_0_FRESH_SCORING_TERMINAL_V01",
            "status": "SCORING_EXECUTION_COMPLETE",
            "authorization_id": inputs.authorization["authorization_id"],
            "authorization_sha256": sha256_file(layout.authorization_path)[0],
            "authorized_by": inputs.authorization["authorized_by"],
            "contract_sha256": inputs.contract_sha256,
            "contract_seal_manifest_sha256": inputs.contract_seal_manifest_sha256,
            "contract_seal_root_sha256": inputs.contract_seal_root_sha256,
            "exact_predecessor_roots": dict(inputs.predecessor_roots),
            "primary_rows_scored": len(primary),
            "heldout_template_rows_inferred": 0,
            "heldout_template_labels_opened": False,
            "joint_template_labels_opened": False,
            "primary_label_file_open_count": 1,
            "refit_performed": False,
            "tuning_performed": False,
            "alternate_view_used": False,
            "terminal_disposition": disposition,
            "passed_endpoints": metrics["passed_endpoints"],
            "failed_endpoints": metrics["failed_endpoints"],
            "outputs": {
                "predictions": "score/predictions-v01.jsonl",
                "scored_rows": "score/scored-rows-v01.jsonl",
                "metrics": "score/metrics-v01.json",
                "bootstrap": "score/bootstrap-v01.npz",
                "label_open_receipt": "score/label-open-receipt-v01.json",
                "stage_seal": "score/stage-seal-v01.json",
            },
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        terminal_path = score_root / "terminal-receipt-v01.json"
        atomic_json(terminal_path, terminal_receipt)
        entries = [
            artifact_entry("E4_SCORING_PREDICTIONS_V01", prediction_path, run_root=layout.run_root),
            artifact_entry("E4_SCORING_SCORED_ROWS_V01", scored_rows_path, run_root=layout.run_root),
            artifact_entry("E4_SCORING_METRICS_V01", metrics_path, run_root=layout.run_root),
            artifact_entry("E4_SCORING_BOOTSTRAP_V01", bootstrap_path, run_root=layout.run_root),
            artifact_entry("E4_SCORING_LABEL_OPEN_RECEIPT_V01", label_receipt_path, run_root=layout.run_root),
            artifact_entry("E4_SCORING_TERMINAL_RECEIPT_V01", terminal_path, run_root=layout.run_root),
        ]
        stage_seal = stage_seal_payload(
            entries=entries,
            contract_sha256=inputs.contract_sha256,
            contract_seal_root_sha256=inputs.contract_seal_root_sha256,
            predecessor_roots=inputs.predecessor_roots,
        )
        stage_seal_path = score_root / "stage-seal-v01.json"
        atomic_json(stage_seal_path, stage_seal)
        return {
            "status": terminal_receipt["status"],
            "terminal_disposition": disposition,
            "passed_endpoints": metrics["passed_endpoints"],
            "failed_endpoints": metrics["failed_endpoints"],
            "scoring_stage_root_sha256": stage_seal["root_sha256"],
            "scoring_stage_seal_path": str(stage_seal_path),
        }
    except Exception as error:
        stop_path = score_root / "score-stop-v01.json"
        stop = {
            "schema": "FAS_E4_0_FRESH_SCORING_STOP_V01",
            "status": "SCORING_ATTEMPT_STOPPED_AND_PRESERVED",
            "authorization_id": inputs.authorization.get("authorization_id"),
            "error_type": type(error).__name__,
            "error": str(error),
            "label_open_attempted": bool(label_reader and label_reader.attempted),
            "label_file_open_count": 1 if label_reader and label_reader.attempted else 0,
            "label_open_partial_receipt": None if label_reader is None else dict(label_reader.last_attempt_receipt),
            "heldout_template_labels_opened": False,
            "joint_template_labels_opened": False,
            "known_label_open_receipt": label_receipt,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        if not stop_path.exists():
            atomic_json(stop_path, stop)
        raise


def default_authorization_path(project_root: Path) -> Path:
    return project_root / "audits" / "e4-0-fresh-scoring-authorization-v01.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one sealed, authorized E4-0 fresh scoring stage.")
    parser.add_argument("--workspace-root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--preflight-only", action="store_true", help="verify all bound identities without inference or label access")
    arguments = parser.parse_args(argv)
    workspace = arguments.workspace_root.resolve()
    project = workspace / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
    authorization_path = (arguments.authorization or default_authorization_path(project)).resolve()
    try:
        layout, authorization = build_layout(workspace, authorization_path)
        prepared = prepare_scoring_inputs(layout, authorization)
        if arguments.preflight_only:
            result = {
                "status": "SCORING_PREFLIGHT_PASS_LABELS_UNOPENED",
                "authorization_id": authorization["authorization_id"],
                "primary_rows": len(prepared.primary_manifest),
                "manifest_rows": len(prepared.manifest),
                "heldout_template_rows_inferred": 0,
                "labels_opened": False,
                "model_or_tokenizer_contact": False,
                "scoring_authorized": True,
            }
        else:
            result = execute_scoring(layout, prepared)
        sys.stdout.write(json.dumps(result, ensure_ascii=True, indent=2) + "\n")
        return 0
    except Exception as error:
        sys.stderr.write(f"E4-0 fresh scoring stopped before a sealed result: {type(error).__name__}: {error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
