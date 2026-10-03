"""Create one immutable, stage-scoped E4-0 authorization from verified bindings.

This module is model-free. It hashes only the explicit binding files supplied by
the operator and does not open population labels, import inference runtimes, or
initialize CUDA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "FAS_E4_0_STAGE_AUTH_V01"
AUTHORIZATION_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_STAGE_AUTHORIZATION_V01"
CONTRACT_ID = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06"
ARTIFACT_SEAL_SCHEMA = "FAS_E4_0_ARTIFACT_SEAL_V01"
GPU_RESERVED_LIMIT_BYTES = 10 * 1024**3
GPU_QUIET_WINDOW_SECONDS = 30
GPU_POLL_INTERVAL_SECONDS = 5
DEFAULT_VALIDITY_SECONDS = 8 * 60 * 60
MAX_VALIDITY_SECONDS = 24 * 60 * 60

PREDECESSOR_ROOTS = {
    "e0_v10_root_sha256": "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd",
    "e1_v04_root_sha256": "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03",
    "e2_v07_root_sha256": "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a",
    "e3_v02_bundle_root_sha256": "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1",
}
ROOT_ORDER = (
    "e0_v10_root_sha256",
    "e1_v04_root_sha256",
    "e2_v07_root_sha256",
    "e3_v02_bundle_root_sha256",
    "e4_population_root_sha256",
    "e4_population_audit_root_sha256",
    "e4_parity_panel_root_sha256",
    "e4_parity_receipt_root_sha256",
    "e4_feature_cache_root_sha256",
)
SCOPE_KEYS = (
    "population_generation",
    "tokenizer_contact",
    "model_contact",
    "feature_extraction",
    "evaluation_label_opening",
    "scoring",
    "fitting",
    "e4_a",
    "heldout_template_label_opening",
    "joint_template_label_opening",
)
TRUE_SCOPES = {
    "POPULATION_GENERATION": {"population_generation"},
    "PARITY_PANEL_MATERIALIZATION": {"tokenizer_contact"},
    "ONLINE_CACHE_PARITY": {"model_contact", "feature_extraction"},
    "FRESH_FEATURE_EXTRACTION": {"model_contact", "feature_extraction"},
    "FRESH_SCORING": {"evaluation_label_opening", "scoring"},
}
BASE_ARTIFACTS = {
    "e4_contract",
    "e4_contract_seal_manifest",
    "e4_contract_audit",
    "e0_seal",
    "e0_audit",
    "e1_seal",
    "e1_audit",
    "e2_seal",
    "e2_audit",
    "e3_seal",
    "e3_audit",
    "representation_abi",
    "model_manifest",
    "tokenizer_manifest",
}
ARTIFACTS_BY_STAGE = {
    "POPULATION_GENERATION": BASE_ARTIFACTS | {
        "e1_inputs", "e1_rows", "e1_terms", "heldout_template_manifest",
        "support_plan", "population_generator",
    },
    "PARITY_PANEL_MATERIALIZATION": BASE_ARTIFACTS | {
        "e1_inputs", "e1_rows", "e1_splits", "e1_terms",
        "population_seal", "population_audit",
    },
    "ONLINE_CACHE_PARITY": BASE_ARTIFACTS | {
        "e1_inputs", "e1_rows", "e1_splits", "e1_terms", "e2_cache", "e3_bundle",
        "population_seal", "population_audit", "parity_panel_seal",
        "parity_inputs", "parity_rows", "parity_selection_receipt",
    },
    "FRESH_FEATURE_EXTRACTION": BASE_ARTIFACTS | {
        "population_seal", "population_audit", "parity_panel_seal",
        "parity_receipt_seal", "population_inputs", "population_rows",
    },
    # These source identities are used to derive and check the nine roots, but
    # are deliberately not emitted in a FRESH_SCORING receipt.
    "FRESH_SCORING": BASE_ARTIFACTS | {
        "population_seal", "population_audit", "parity_panel_seal",
        "parity_receipt_seal", "feature_cache_seal",
    },
}
PATH_KEYS = frozenset({
    "model_snapshot", "tokenizer_snapshot", "model_asset_manifest", "tokenizer_asset_manifest",
})
ROOT_FILE_ROLES = {
    "e0_v10_root_sha256": "e0_seal",
    "e1_v04_root_sha256": "e1_seal",
    "e2_v07_root_sha256": "e2_seal",
    "e3_v02_bundle_root_sha256": "e3_seal",
    "e4_population_root_sha256": "population_seal",
    "e4_parity_panel_root_sha256": "parity_panel_seal",
    "e4_parity_receipt_root_sha256": "parity_receipt_seal",
    "e4_feature_cache_root_sha256": "feature_cache_seal",
}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class AuthorizationError(RuntimeError):
    """Invalid or incomplete authorization material; no receipt was written."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuthorizationError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise AuthorizationError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _canonical_path(value: Any, *, must_exist: bool) -> Path:
    if not isinstance(value, str) or not value:
        raise AuthorizationError("all paths must be nonempty strings")
    path = Path(value)
    if not path.is_absolute():
        raise AuthorizationError(f"path is not absolute: {value}")
    try:
        resolved = path.resolve(strict=must_exist)
    except OSError as error:
        raise AuthorizationError(f"path cannot be resolved: {value}: {error}") from error
    if os.path.normpath(str(resolved)) != str(resolved):
        raise AuthorizationError(f"path is not normalized: {value}")
    return resolved


def artifact_identity(path_value: str | Path) -> dict[str, Any]:
    path = _canonical_path(str(path_value), must_exist=True)
    if not path.is_file():
        raise AuthorizationError(f"bound artifact is not a regular file: {path}")
    digest, size = _sha256(path)
    return {"path": str(path), "sha256": digest, "bytes": size}


def _artifact_identities(raw: Any, stage: str) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict) or set(raw) != ARTIFACTS_BY_STAGE[stage]:
        missing = sorted(ARTIFACTS_BY_STAGE[stage] - set(raw) if isinstance(raw, dict) else ARTIFACTS_BY_STAGE[stage])
        extra = sorted(set(raw) - ARTIFACTS_BY_STAGE[stage]) if isinstance(raw, dict) else []
        raise AuthorizationError(f"artifact role set mismatch; missing={missing}, extra={extra}")
    result: dict[str, dict[str, Any]] = {}
    for role, path_value in raw.items():
        folded_role = role.casefold()
        path_text = str(path_value).replace("\\", "/").casefold()
        if "label" in folded_role or "escrow" in folded_role or "/labels/" in path_text or "terminal-label" in path_text or "escrow" in path_text:
            raise AuthorizationError(f"pre-scoring authorization cannot bind truth/escrow artifact: {role}")
        result[role] = artifact_identity(path_value)
    return result


def _contract_binding(artifacts: Mapping[str, Mapping[str, Any]]) -> tuple[str, str, str, dict[str, Any]]:
    contract_entry = artifacts["e4_contract"]
    manifest_entry = artifacts["e4_contract_seal_manifest"]
    audit_entry = artifacts["e4_contract_audit"]
    contract = _read_json(Path(contract_entry["path"]))
    seal = _read_json(Path(manifest_entry["path"]))
    audit = _read_json(Path(audit_entry["path"]))
    if contract.get("contract_id") != CONTRACT_ID or "SEALED" not in str(contract.get("status", "")).upper() or "DRAFT" in str(contract.get("status", "")).upper():
        raise AuthorizationError("bound E4 contract is not the final sealed v06 contract")
    contract_hash = str(contract_entry["sha256"])
    if seal.get("schema") != ARTIFACT_SEAL_SCHEMA or seal.get("stage") != "E4_0_CONTRACT":
        raise AuthorizationError("bound contract seal manifest identity is malformed")
    root = seal.get("root_sha256")
    if not isinstance(root, str) or HEX64.fullmatch(root) is None:
        raise AuthorizationError("contract seal root is malformed")
    if seal.get("contract_sha256") != contract_hash:
        raise AuthorizationError("contract seal manifest binds different contract bytes")
    if not any(isinstance(row, dict) and row.get("sha256") == contract_hash for row in seal.get("entries", [])):
        raise AuthorizationError("contract seal manifest does not contain the bound contract")
    audit_root = audit.get("e4_0_contract_root_sha256", audit.get("contract_root_sha256", audit.get("contract_seal_root_sha256")))
    if audit_root != root or "PASS" not in str(audit.get("status", "")).upper():
        raise AuthorizationError("independent contract audit does not pass on the exact sealed root")
    predecessors = contract.get("predecessors")
    if not isinstance(predecessors, dict) or any(predecessors.get(key) != value for key, value in PREDECESSOR_ROOTS.items()):
        raise AuthorizationError("final E4 contract does not preserve exact E0/E1/E2/E3 predecessors")
    return contract_hash, str(manifest_entry["sha256"]), root, contract


def _seal_root(artifact: Mapping[str, Any], role: str, expected_stage: str | None = None) -> str:
    value = _read_json(Path(artifact[role]["path"]))
    if expected_stage is not None and value.get("stage") != expected_stage:
        raise AuthorizationError(f"{role} names stage {value.get('stage')!r}, expected {expected_stage!r}")
    if value.get("schema") != ARTIFACT_SEAL_SCHEMA or value.get("status") != "SEALED":
        raise AuthorizationError(f"{role} is not a sealed E4 artifact manifest")
    root = value.get("root_sha256")
    if not isinstance(root, str) or HEX64.fullmatch(root) is None:
        raise AuthorizationError(f"{role} root is malformed")
    return root


def _verify_historical(artifacts: Mapping[str, Mapping[str, Any]]) -> None:
    for root_key, role in ROOT_FILE_ROLES.items():
        if root_key in PREDECESSOR_ROOTS:
            value = _read_json(Path(artifacts[role]["path"]))
            root = value.get("root_sha256", value.get("e3_root_sha256"))
            if root != PREDECESSOR_ROOTS[root_key]:
                raise AuthorizationError(f"{role} does not match frozen historical root {root_key}")
    audit_expectations = {
        "e0_audit": ("seal_root_sha256", PREDECESSOR_ROOTS["e0_v10_root_sha256"]),
        "e1_audit": ("e1_root_sha256", PREDECESSOR_ROOTS["e1_v04_root_sha256"]),
        "e2_audit": ("e2_root_sha256", PREDECESSOR_ROOTS["e2_v07_root_sha256"]),
        "e3_audit": ("e3_root_sha256", PREDECESSOR_ROOTS["e3_v02_bundle_root_sha256"]),
    }
    for role, (root_key, expected) in audit_expectations.items():
        audit = _read_json(Path(artifacts[role]["path"]))
        if "PASS" not in str(audit.get("status", "")).upper() or audit.get(root_key) != expected:
            raise AuthorizationError(f"{role} is not a passing audit for its exact historical root")


def _predecessor_roots(stage: str, artifacts: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    _verify_historical(artifacts)
    roots = dict(PREDECESSOR_ROOTS)
    if stage == "POPULATION_GENERATION":
        return roots
    population_root = _seal_root(artifacts, "population_seal", "POPULATION_GENERATION")
    population_audit = _read_json(Path(artifacts["population_audit"]["path"]))
    if population_audit.get("population_root_sha256") != population_root or not (
        "PASS" in str(population_audit.get("status", "")).upper() or population_audit.get("all_checks_passed") is True
    ):
        raise AuthorizationError("population audit does not independently pass the bound population seal")
    roots["e4_population_root_sha256"] = population_root
    roots["e4_population_audit_root_sha256"] = artifacts["population_audit"]["sha256"]
    if stage == "PARITY_PANEL_MATERIALIZATION":
        return roots
    panel_root = _seal_root(artifacts, "parity_panel_seal", "PARITY_PANEL_MATERIALIZATION")
    roots["e4_parity_panel_root_sha256"] = panel_root
    if stage == "ONLINE_CACHE_PARITY":
        return roots
    parity_root = _seal_root(artifacts, "parity_receipt_seal", "ONLINE_CACHE_PARITY")
    parity_seal = _read_json(Path(artifacts["parity_receipt_seal"]["path"]))
    parity_entries = parity_seal.get("entries", [])
    receipt_entry = next((row for row in parity_entries if isinstance(row, dict) and row.get("artifact_id") == "parity_receipt"), None)
    if receipt_entry is None:
        raise AuthorizationError("online/cache parity seal does not bind the expected parity_receipt member")
    receipt_path = Path(artifacts["parity_receipt_seal"]["path"]).parent.parent / receipt_entry["path"]
    parity_receipt = _read_json(receipt_path)
    if parity_receipt.get("status") != "ONLINE_CACHE_PARITY_PASS":
        raise AuthorizationError("online/cache parity receipt is not passing")
    roots["e4_parity_receipt_root_sha256"] = parity_root
    if stage == "FRESH_FEATURE_EXTRACTION":
        return roots
    feature_root = _seal_root(artifacts, "feature_cache_seal", "FRESH_FEATURE_EXTRACTION")
    feature_seal = _read_json(Path(artifacts["feature_cache_seal"]["path"]))
    feature_entry = next((row for row in feature_seal.get("entries", []) if isinstance(row, dict) and row.get("artifact_id") == "feature_extraction_receipt"), None)
    if feature_entry is None:
        raise AuthorizationError("fresh feature seal does not bind the expected extraction receipt member")
    feature_path = Path(artifacts["feature_cache_seal"]["path"]).parent.parent / feature_entry["path"]
    feature_receipt = _read_json(feature_path)
    if feature_receipt.get("status") != "FEATURE_CACHE_COMPLETE_GATE_PASS":
        raise AuthorizationError("fresh feature extraction receipt is not passing")
    roots["e4_feature_cache_root_sha256"] = feature_root
    return roots


def _paths(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or set(raw) != PATH_KEYS:
        raise AuthorizationError(f"paths must contain exactly: {sorted(PATH_KEYS)}")
    return {key: str(_canonical_path(value, must_exist=True)) for key, value in raw.items()}


def _gpu_lease(raw: Any, stage: str) -> tuple[dict[str, Any], bool]:
    if not isinstance(raw, dict) or set(raw) != {"lock_path"}:
        raise AuthorizationError("gpu_lease input must contain only lock_path")
    lock_path = _canonical_path(raw["lock_path"], must_exist=False)
    lease = {
        "lock_path": str(lock_path),
        "expected_reserved_ceiling_bytes": GPU_RESERVED_LIMIT_BYTES,
        "quiet_window_seconds": GPU_QUIET_WINDOW_SECONDS,
        "poll_interval_seconds": GPU_POLL_INTERVAL_SECONDS,
    }
    required = stage in {"ONLINE_CACHE_PARITY", "FRESH_FEATURE_EXTRACTION"}
    return lease, required


def build_authorization(
    *,
    stage: str,
    bindings: Mapping[str, Any],
    now_unix_seconds: int | None = None,
) -> dict[str, Any]:
    """Build and validate an auth object without writing it or touching ML runtimes."""
    if stage not in ARTIFACTS_BY_STAGE:
        raise AuthorizationError(f"unsupported E4 stage: {stage}")
    duration = bindings.get("valid_for_seconds", DEFAULT_VALIDITY_SECONDS)
    if type(duration) is not int or not 1 <= duration <= MAX_VALIDITY_SECONDS:
        raise AuthorizationError(f"valid_for_seconds must be an integer in [1,{MAX_VALIDITY_SECONDS}]")
    output_root = _canonical_path(bindings.get("output_root"), must_exist=False)
    artifacts = _artifact_identities(bindings.get("artifacts"), stage)
    contract_sha, seal_manifest_sha, contract_root, _contract = _contract_binding(artifacts)
    _verify_historical(artifacts)
    roots = _predecessor_roots(stage, artifacts)
    expected_count = 4 + len(roots) - len(PREDECESSOR_ROOTS)
    expected_roles = set(ROOT_ORDER[:expected_count])
    if set(roots) != expected_roles:
        raise AuthorizationError("derived predecessor-root set differs from the normative stage prefix")
    for key, value in roots.items():
        if not isinstance(value, str) or HEX64.fullmatch(value) is None:
            raise AuthorizationError(f"derived predecessor root is malformed: {key}")
    issued = int(time.time()) if now_unix_seconds is None else now_unix_seconds
    if isinstance(issued, bool) or not isinstance(issued, int) or issued < 0:
        raise AuthorizationError("issued time must be a finite nonnegative Unix integer")
    true_scope = TRUE_SCOPES[stage]
    auth: dict[str, Any] = {
        "schema": SCHEMA,
        "authorization_id": AUTHORIZATION_ID,
        "status": "AUTHORIZED",
        "stage": stage,
        "contract_sha256": contract_sha,
        "contract_seal_manifest_sha256": seal_manifest_sha,
        "contract_seal_root_sha256": contract_root,
        "exact_predecessor_roots": roots,
        "output_root": str(output_root),
        "scope": {key: key in true_scope for key in SCOPE_KEYS},
        "authorized_by": "ACTIVE_USER_REQUEST",
        "issued_utc_unix_seconds": issued,
        "valid_from_utc_unix_seconds": issued,
        "valid_until_utc_unix_seconds": issued + duration,
    }
    if stage != "FRESH_SCORING":
        auth["artifacts"] = artifacts
        paths = _paths(bindings.get("paths"))
        for path_key, artifact_key in (
            ("model_asset_manifest", "model_manifest"),
            ("tokenizer_asset_manifest", "tokenizer_manifest"),
        ):
            if paths[path_key] != artifacts[artifact_key]["path"]:
                raise AuthorizationError(f"paths.{path_key} differs from its artifact-map identity")
        auth["paths"] = paths
        lease, required = _gpu_lease(bindings.get("gpu_lease"), stage)
        auth["gpu_lease"] = lease
        auth["gpu_lease_required_before_model_contact"] = required
    expected_keys = {
        "schema", "authorization_id", "status", "stage", "contract_sha256",
        "contract_seal_manifest_sha256", "contract_seal_root_sha256", "exact_predecessor_roots",
        "output_root", "scope", "authorized_by", "issued_utc_unix_seconds",
        "valid_from_utc_unix_seconds", "valid_until_utc_unix_seconds",
    }
    if stage != "FRESH_SCORING":
        expected_keys |= {"artifacts", "paths", "gpu_lease", "gpu_lease_required_before_model_contact"}
    if set(auth) != expected_keys:
        raise AuthorizationError("internal stage authorization field set mismatch")
    return auth


def create_once(path: Path, authorization: Mapping[str, Any]) -> tuple[int, str]:
    """Durably create one receipt and refuse replacement of an earlier attempt."""
    if not path.parent.is_dir():
        raise AuthorizationError(f"authorization output directory must already exist: {path.parent}")
    payload = (json.dumps(dict(authorization), ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise AuthorizationError(f"authorization receipt already exists; preserving it: {path}") from error
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        # Preserve a partial create-once attempt rather than silently replacing it.
        raise
    return len(payload), hashlib.sha256(payload).hexdigest()


def _load_bindings(path: Path) -> dict[str, Any]:
    value = _read_json(path.resolve(strict=True))
    expected = {"output_root", "artifacts", "paths", "gpu_lease", "valid_for_seconds"}
    if set(value) != expected:
        raise AuthorizationError(f"bindings file must contain exactly: {sorted(expected)}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create one model-free, stage-scoped E4-0 authorization receipt.")
    parser.add_argument("--stage", choices=tuple(ARTIFACTS_BY_STAGE), required=True)
    parser.add_argument("--bindings", type=Path, required=True, help="JSON map of exact paths and stage artifacts")
    parser.add_argument("--output", type=Path, required=True, help="new receipt path; existing files are never replaced")
    args = parser.parse_args(argv)
    try:
        bindings = _load_bindings(args.bindings)
        authorization = build_authorization(stage=args.stage, bindings=bindings)
        count, digest = create_once(args.output, authorization)
    except Exception as error:
        print(f"E4-0 authorization stopped: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "AUTHORIZED", "stage": args.stage, "path": str(args.output.resolve()), "bytes": count, "sha256": digest}, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
