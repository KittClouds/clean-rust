from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .constants import (
    CONTRACT_ID,
    CONTRACT_SEAL_ID,
    CONTRACT_STAGE,
    E4_ROOT_KEYS,
    EXPECTED_PREDECESSORS,
    SEAL_SCHEMA,
)


class AuditError(RuntimeError):
    """A sealed-artifact check failed; no outputs are repaired in place."""


@dataclass(frozen=True)
class Member:
    artifact_id: str
    path: Path
    relative_path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class Seal:
    stage: str
    root_sha256: str
    manifest_sha256: str
    entries: Mapping[str, Member]
    value: Mapping[str, Any]


def sha256_file(path: Path, chunk_bytes: int = 8 << 20) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
            count += len(chunk)
    return digest.hexdigest(), count


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AuditError(f"invalid JSONL {path.name}:{number}") from exc
                if not isinstance(row, dict):
                    raise AuditError(f"JSONL row is not an object {path.name}:{number}")
                rows.append(row)
    except OSError as exc:
        raise AuditError(f"cannot read JSONL {path}: {exc}") from exc
    return rows


def read_jsonl_stream(path: Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AuditError(f"invalid JSONL {path.name}:{number}") from exc
                if not isinstance(row, dict):
                    raise AuditError(f"JSONL row is not an object {path.name}:{number}")
                yield row
    except OSError as exc:
        raise AuditError(f"cannot read JSONL {path}: {exc}") from exc


def canonical_seal_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AuditError(f"seal manifest is not canonical JSON data: {exc}") from exc


def e4_root(entries: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: str(item["artifact_id"]).encode("utf-8")):
        line = f'{entry["artifact_id"]}\t{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def legacy_artifact_root(entries: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: str(item["artifact_id"]).encode("utf-8")):
        digest.update(f'{entry["artifact_id"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def legacy_path_root(entries: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: str(item["path"]).encode("utf-8")):
        digest.update(f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def safe_member_path(relative: Any, root: Path) -> tuple[Path, str]:
    if not isinstance(relative, str) or not relative:
        raise AuditError("seal member has an empty or non-text path")
    if any(char in relative for char in "\\\t\r\n"):
        raise AuditError("seal member path has a forbidden separator")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or any(part in ("", ".", "..") for part in parsed.parts):
        raise AuditError("seal member path is absolute or traverses directories")
    if parsed.as_posix() != relative:
        raise AuditError("seal member path is not normalized POSIX text")
    base = root.resolve(strict=True)
    member = base.joinpath(*parsed.parts).resolve(strict=False)
    if not member.is_relative_to(base):
        raise AuditError("seal member resolves outside its root")
    return member, parsed.as_posix()


def verify_e4_seal(
    seal_path: Path,
    *,
    root: Path,
    expected_stage: str,
    contract_sha256: str | None = None,
    contract_seal_root_sha256: str | None = None,
    expected_predecessors: Mapping[str, str] | None = None,
    deferred_member_ids: frozenset[str] = frozenset(),
    allowed_entry_ids: frozenset[str] | None = None,
) -> Seal:
    try:
        raw = seal_path.read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read stage seal {seal_path}: {exc}") from exc
    fields = {
        "schema", "status", "seal_id", "stage", "path_root_kind", "created_utc",
        "contract_sha256", "contract_seal_root_sha256", "exact_predecessor_roots",
        "entries", "entry_count", "root_sha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != fields:
        raise AuditError("E4 seal top-level schema mismatch")
    if raw != canonical_seal_bytes(manifest):
        raise AuditError("E4 seal manifest serialization is not canonical")
    if manifest.get("schema") != SEAL_SCHEMA or manifest.get("status") != "SEALED":
        raise AuditError("unsupported E4 seal schema/status")
    if manifest.get("stage") != expected_stage:
        raise AuditError("E4 seal stage mismatch")
    expected_kind = "WORKSPACE_ROOT" if expected_stage == CONTRACT_STAGE else "E4_RUN_ROOT"
    if manifest.get("path_root_kind") != expected_kind:
        raise AuditError("E4 seal path-root kind mismatch")
    if contract_sha256 is not None and manifest.get("contract_sha256") != contract_sha256:
        raise AuditError("stage seal binds different contract bytes")
    if manifest.get("contract_seal_root_sha256") != contract_seal_root_sha256:
        raise AuditError("stage seal binds different contract seal root")
    preds = manifest.get("exact_predecessor_roots")
    if not isinstance(preds, dict):
        raise AuditError("stage seal predecessor roots are malformed")
    if expected_predecessors is not None and dict(preds) != dict(expected_predecessors):
        raise AuditError("stage seal predecessor roots differ from expected roots")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries or manifest.get("entry_count") != len(entries):
        raise AuditError("stage seal entry list/count is invalid")
    by_id: dict[str, Member] = {}
    seen_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"artifact_id", "path", "bytes", "sha256"}:
            raise AuditError("stage seal member schema mismatch")
        artifact_id = entry["artifact_id"]
        size, digest = entry["bytes"], entry["sha256"]
        if not isinstance(artifact_id, str) or not artifact_id or artifact_id in by_id:
            raise AuditError("stage seal has duplicate/empty artifact ID")
        if type(size) is not int or size < 0 or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise AuditError(f"invalid byte length/SHA-256 for {artifact_id}")
        path, normalized = safe_member_path(entry["path"], root)
        if normalized in seen_paths:
            raise AuditError("stage seal has duplicate member path")
        seen_paths.add(normalized)
        member = Member(artifact_id, path, normalized, size, digest)
        if artifact_id not in deferred_member_ids:
            actual_sha, actual_bytes = sha256_file(path)
            if actual_sha != digest or actual_bytes != size:
                raise AuditError(f"sealed member bytes/hash mismatch: {artifact_id}")
        by_id[artifact_id] = member
    if allowed_entry_ids is not None and set(by_id) != set(allowed_entry_ids):
        raise AuditError("seal member IDs differ from the frozen stage schema")
    computed = e4_root(entries)
    if manifest.get("root_sha256") != computed:
        raise AuditError("E4 seal root mismatch")
    return Seal(
        str(expected_stage), computed, hashlib.sha256(raw).hexdigest(), by_id, manifest,
    )


def verify_legacy_head_seal(seal_path: Path, expected_root: str) -> dict[str, Path]:
    """Verify E3 seal root and only the 20 head files; never opens E3 label files."""
    manifest = read_json(seal_path)
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise AuditError("E3 head seal has no entries")
    if legacy_artifact_root(entries) != expected_root or manifest.get("root_sha256") != expected_root:
        raise AuditError("E3 frozen head seal root mismatch")
    result: dict[str, Path] = {}
    for entry in entries:
        artifact_id = entry.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id.startswith("e3_v02_"):
            continue
        stem = artifact_id[len("e3_v02_"):]
        if not any(stem.endswith("_" + kind) for kind in ("mean", "scale", "weight", "bias")):
            continue
        path_text = entry.get("path")
        if not isinstance(path_text, str) or not Path(path_text).is_absolute():
            raise AuditError(f"E3 head path is not absolute: {artifact_id}")
        path = Path(path_text)
        if path.is_symlink():
            raise AuditError(f"E3 head member cannot be a symlink: {artifact_id}")
        actual_sha, actual_bytes = sha256_file(path)
        if actual_sha != entry.get("sha256") or actual_bytes != entry.get("bytes"):
            raise AuditError(f"E3 head file hash/length mismatch: {artifact_id}")
        result[artifact_id] = path
    required = {
        f"e3_v02_{task}_{kind}"
        for task in ("context_identity", "entity_identity", "relation", "observed_state", "exact_target")
        for kind in ("mean", "scale", "weight", "bias")
    }
    if set(result) != required:
        raise AuditError("E3 seal does not provide exactly the five frozen four-file heads")
    return result


def validate_contract_seal(workspace: Path, contract_path: Path, seal_path: Path) -> dict[str, Any]:
    contract_raw = contract_path.read_bytes()
    contract = read_json(contract_path)
    if contract.get("contract_id") != CONTRACT_ID or contract.get("status") != "SEALED":
        raise AuditError("final E4-0 contract identity/status mismatch")
    contract_sha = hashlib.sha256(contract_raw).hexdigest()
    seal = verify_e4_seal(
        seal_path,
        root=workspace,
        expected_stage=CONTRACT_STAGE,
        contract_sha256=contract_sha,
        contract_seal_root_sha256=None,
        expected_predecessors=EXPECTED_PREDECESSORS,
    )
    manifest = dict(seal.value)
    if manifest.get("seal_id") != CONTRACT_SEAL_ID:
        raise AuditError("E4-0 contract seal identity mismatch")
    candidates = [member for member in seal.entries.values() if member.sha256 == contract_sha and member.bytes == len(contract_raw)]
    if len(candidates) != 1:
        raise AuditError("contract seal does not bind exactly one matching contract artifact")
    if candidates[0].relative_path != (
        "experiments/fas-frozen-observer-bundle-engineering-v01/"
        "contracts/e4-0-contract-v05-final.json"
    ):
        raise AuditError("contract seal binds the matching bytes under an unexpected path")
    required_roots = contract.get("predecessors")
    if not isinstance(required_roots, dict) or any(required_roots.get(k) != v for k, v in EXPECTED_PREDECESSORS.items()):
        raise AuditError("final contract historical predecessor identities mismatch")
    endpoint_order = contract.get("fresh_qualification", {}).get("gate", {}).get("endpoint_order")
    if not isinstance(endpoint_order, list) or tuple(endpoint_order) != ENDPOINT_NAMES:
        raise AuditError("final contract endpoint order differs from the frozen order")
    return {
        "status": "PASS_CONTRACT_SEAL",
        "contract_sha256": contract_sha,
        "contract_seal_root_sha256": seal.root_sha256,
        "contract_seal_manifest_sha256": seal.manifest_sha256,
        "source_entries": len(seal.entries),
    }


ENDPOINT_NAMES = (
    "context_identity", "entity_identity", "relation", "observed_state",
    "exact_target_in_domain", "exact_target_context_novel",
    "exact_target_entity_novel", "exact_target_both_novel",
)


def validate_source_map(workspace: Path, source_map_path: Path) -> dict[str, Any]:
    """Check SHA-256 declarations in the final map without importing source code."""
    raw = source_map_path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    text = raw
    checked: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    def check_member(rel: str, expected: str, expected_bytes: Any = None) -> None:
        if rel in seen_paths:
            raise AuditError(f"source map binds a path more than once: {rel}")
        member, normalized = safe_member_path(rel, workspace)
        if normalized != rel:
            raise AuditError(f"source-map path is not normalized POSIX text: {rel}")
        actual, size = sha256_file(member)
        if actual != expected:
            raise AuditError(f"source-map SHA-256 mismatch: {rel}")
        if expected_bytes is not None and (type(expected_bytes) is not int or expected_bytes != size):
            raise AuditError(f"source-map byte length mismatch: {rel}")
        seen_paths.add(rel)
        checked.append({"path": rel, "bytes": size, "sha256": actual})

    if isinstance(parsed, dict):
        rows = parsed.get("implementation_sources", parsed.get("source_files", parsed.get("entries", [])))
        if isinstance(rows, dict):
            rows = list(rows.values())
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                rel = row.get("path")
                expected = row.get("sha256")
                if isinstance(rel, str) and isinstance(expected, str):
                    check_member(rel, expected, row.get("bytes"))
    else:
        for line in text.splitlines():
            cells = [cell.strip().strip("`") for cell in line.split("|")]
            paths = [
                cell for cell in cells
                if re.fullmatch(
                    r"(?:experiments/fas-frozen-observer-bundle-engineering-v01|source|contracts|plans|audits)/[^\s`]+",
                    cell,
                )
            ]
            hashes = [cell for cell in cells if re.fullmatch(r"[0-9a-f]{64}", cell)]
            if not paths or not hashes:
                continue
            rel = paths[0]
            expected = hashes[0]
            check_member(rel, expected)
    if not checked:
        raise AuditError("source map contains no parseable path/hash bindings")
    required_units = (
        "e4_population_generator",
        "e4_online_feature_and_parity_runner",
        "e4_fresh_scorer",
        "e4_independent_auditor",
    )
    declared_units = parsed.get("implementation_units", []) if isinstance(parsed, dict) else []
    if isinstance(declared_units, list) and declared_units:
        declared = {unit for unit in declared_units if isinstance(unit, str)}
        missing = [unit for unit in required_units if unit not in declared]
    else:
        required_paths = {
            "e4_population_generator": (
                "experiments/fas-frozen-observer-bundle-engineering-v01/"
                "source/e4-population-v01/src/bin/e4-population-v01.rs",
            ),
            "e4_online_feature_and_parity_runner": (
                "experiments/fas-frozen-observer-bundle-engineering-v01/"
                "source/scripts/e4_online_parity_v01.py",
                "experiments/fas-frozen-observer-bundle-engineering-v01/"
                "source/scripts/e4_runner_common_v01.py",
                "experiments/fas-frozen-observer-bundle-engineering-v01/"
                "source/scripts/e4_runner_modes_v01.py",
                "experiments/fas-frozen-observer-bundle-engineering-v01/"
                "source/scripts/e4_runner_artifacts_v01.py",
            ),
            "e4_fresh_scorer": (
                "experiments/fas-frozen-observer-bundle-engineering-v01/"
                "source/scripts/e4_fresh_scorer_v01/runner.py",
                "experiments/fas-frozen-observer-bundle-engineering-v01/"
                "source/scripts/e4_fresh_scorer_v01/scorer.py",
            ),
            "e4_independent_auditor": (
                "experiments/fas-frozen-observer-bundle-engineering-v01/"
                "source/scripts/e4_independent_audit_v01/cli.py",
                "experiments/fas-frozen-observer-bundle-engineering-v01/"
                "source/scripts/e4_independent_audit_v01/integrity.py",
                "experiments/fas-frozen-observer-bundle-engineering-v01/"
                "source/scripts/e4_independent_audit_v01/population.py",
                "experiments/fas-frozen-observer-bundle-engineering-v01/"
                "source/scripts/e4_independent_audit_v01/features.py",
                "experiments/fas-frozen-observer-bundle-engineering-v01/"
                "source/scripts/e4_independent_audit_v01/replay.py",
            ),
        }
        missing = [
            unit for unit, members in required_paths.items()
            if any(member not in seen_paths for member in members)
        ]
    if missing:
        raise AuditError(f"source map omits E4-0 implementation units: {missing}")
    return {"status": "PASS_SOURCE_MAP", "checked_members": len(checked), "members": checked}
