from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .constants import E4_ROOT_KEYS, EXPECTED_PREDECESSORS
from .features import verify_feature_stage, verify_parity_stage
from .integrity import AuditError, e4_root, read_json, sha256_file, validate_contract_seal, validate_source_map
from .population import audit_population
from .replay import audit_scoring_stage


def _auth(path: Path, expected_stage: str, project_root: Path) -> dict[str, Any]:
    auth = read_json(path)
    base_fields = {
        "schema", "authorization_id", "status", "stage", "contract_sha256",
        "contract_seal_manifest_sha256", "contract_seal_root_sha256", "exact_predecessor_roots",
        "output_root", "scope", "authorized_by", "issued_utc_unix_seconds",
        "valid_from_utc_unix_seconds", "valid_until_utc_unix_seconds",
    }
    artifact_stages = {
        "POPULATION_GENERATION", "PARITY_PANEL_MATERIALIZATION",
        "ONLINE_CACHE_PARITY", "FRESH_FEATURE_EXTRACTION",
    }
    runtime_extensions = {"artifacts", "paths", "gpu_lease", "gpu_lease_required_before_model_contact"}
    expected_fields = base_fields | (runtime_extensions if expected_stage in artifact_stages else set())
    if set(auth) != expected_fields or auth.get("schema") != "FAS_E4_0_STAGE_AUTH_V01" or auth.get("status") != "AUTHORIZED":
        raise AuditError("stage authorization does not match the normative E4-0 schema")
    if auth.get("stage") != expected_stage or auth.get("authorized_by") != "ACTIVE_USER_REQUEST":
        raise AuditError("stage authorization identity/scope does not match the audited stage")
    scope = auth.get("scope")
    scope_keys = {
        "population_generation", "tokenizer_contact", "model_contact", "feature_extraction",
        "evaluation_label_opening", "scoring", "fitting", "e4_a",
        "heldout_template_label_opening", "joint_template_label_opening",
    }
    true_by_stage = {
        "POPULATION_GENERATION": {"population_generation"},
        "PARITY_PANEL_MATERIALIZATION": {"tokenizer_contact"},
        "ONLINE_CACHE_PARITY": {"model_contact", "feature_extraction"},
        "FRESH_FEATURE_EXTRACTION": {"model_contact", "feature_extraction"},
        "FRESH_SCORING": {"evaluation_label_opening", "scoring"},
    }
    if not isinstance(scope, dict) or set(scope) != scope_keys or any(type(value) is not bool for value in scope.values()):
        raise AuditError("stage authorization scope fields are incomplete or non-boolean")
    if {key for key, value in scope.items() if value} != true_by_stage[expected_stage]:
        raise AuditError("stage authorization has incorrect or overbroad scope flags")
    roots = auth.get("exact_predecessor_roots")
    expected_root_count = {
        "POPULATION_GENERATION": 4,
        "PARITY_PANEL_MATERIALIZATION": 6,
        "ONLINE_CACHE_PARITY": 7,
        "FRESH_FEATURE_EXTRACTION": 8,
        "FRESH_SCORING": 9,
    }[expected_stage]
    expected_root_keys = set(E4_ROOT_KEYS[:expected_root_count])
    if (
        not isinstance(roots, dict)
        or set(roots) != expected_root_keys
        or any(roots.get(key) != value for key, value in EXPECTED_PREDECESSORS.items())
        or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in roots.values())
    ):
        raise AuditError("stage authorization historical predecessor roots mismatch")
    if auth.get("output_root") != str(Path(auth.get("output_root", "")).resolve()):
        raise AuditError("stage authorization output root must be an absolute normalized path")
    for field in ("contract_sha256", "contract_seal_manifest_sha256", "contract_seal_root_sha256"):
        if not isinstance(auth.get(field), str) or re.fullmatch(r"[0-9a-f]{64}", auth[field]) is None:
            raise AuditError(f"stage authorization {field} is malformed")
    issued = auth.get("issued_utc_unix_seconds")
    valid_from = auth.get("valid_from_utc_unix_seconds")
    valid_until = auth.get("valid_until_utc_unix_seconds")
    if any(type(value) is not int for value in (issued, valid_from, valid_until)) or not (issued <= valid_from < valid_until):
        raise AuditError("stage authorization issue/validity interval is malformed")
    now = int(time.time())
    if not valid_from <= now <= valid_until:
        raise AuditError("stage authorization is outside its frozen validity interval")
    if expected_stage in artifact_stages:
        paths = auth.get("paths")
        path_keys = {"model_snapshot", "tokenizer_snapshot", "model_asset_manifest", "tokenizer_asset_manifest"}
        if not isinstance(paths, dict) or set(paths) != path_keys:
            raise AuditError("runtime authorization paths differ from the issuer's exact path schema")
        for name, value in paths.items():
            if not isinstance(value, str) or not Path(value).is_absolute() or os.path.normpath(value) != value:
                raise AuditError(f"runtime authorization path is not an absolute normalized path: {name}")
        lease = auth.get("gpu_lease")
        lease_keys = {"lock_path", "expected_reserved_ceiling_bytes", "quiet_window_seconds", "poll_interval_seconds"}
        if not isinstance(lease, dict) or set(lease) != lease_keys:
            raise AuditError("runtime authorization GPU lease differs from the issuer's exact lease schema")
        lock_path = lease.get("lock_path")
        if not isinstance(lock_path, str) or not Path(lock_path).is_absolute() or os.path.normpath(lock_path) != lock_path:
            raise AuditError("runtime authorization GPU lease lock path is not absolute and normalized")
        if (
            type(lease.get("expected_reserved_ceiling_bytes")) is not int
            or lease["expected_reserved_ceiling_bytes"] != 10 * 1024**3
            or type(lease.get("quiet_window_seconds")) is not int
            or lease["quiet_window_seconds"] != 30
            or type(lease.get("poll_interval_seconds")) is not int
            or lease["poll_interval_seconds"] != 5
        ):
            raise AuditError("runtime authorization GPU lease resource/contention gates differ from the frozen values")
        lease_required = expected_stage in {"ONLINE_CACHE_PARITY", "FRESH_FEATURE_EXTRACTION"}
        if type(auth.get("gpu_lease_required_before_model_contact")) is not bool or auth["gpu_lease_required_before_model_contact"] is not lease_required:
            raise AuditError("runtime authorization GPU lease requirement differs from stage semantics")
        artifact_map = auth.get("artifacts")
        if not isinstance(artifact_map, dict) or not artifact_map:
            raise AuditError("runtime stage authorization lacks its explicit artifact map")
        for name, identity in artifact_map.items():
            if not isinstance(name, str) or not name or not isinstance(identity, dict) or set(identity) != {"path", "sha256", "bytes"}:
                raise AuditError("runtime authorization artifact identity is malformed")
            artifact_path = identity.get("path")
            if not isinstance(artifact_path, str) or not Path(artifact_path).is_absolute():
                raise AuditError(f"runtime authorization artifact path is not absolute: {name}")
            normalized_name = name.casefold()
            normalized_path = artifact_path.replace("\\", "/").casefold()
            if "label" in normalized_name or "escrow" in normalized_name or "/labels/" in normalized_path or "terminal-label" in normalized_path or "escrow" in normalized_path:
                raise AuditError("pre-scoring runtime authorization must not bind terminal-label or escrow files")
            if type(identity.get("bytes")) is not int or identity["bytes"] < 0:
                raise AuditError(f"runtime authorization artifact byte count is malformed: {name}")
            expected_sha = identity.get("sha256")
            if not isinstance(expected_sha, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None:
                raise AuditError(f"runtime authorization artifact SHA-256 is malformed: {name}")
            actual_sha, actual_bytes = sha256_file(Path(artifact_path))
            if actual_sha != expected_sha or actual_bytes != identity["bytes"]:
                raise AuditError(f"runtime authorization artifact differs from its declared identity: {name}")
        required_contract_artifacts = {"e4_contract", "e4_contract_seal_manifest", "e4_contract_audit"}
        if not required_contract_artifacts.issubset(artifact_map):
            raise AuditError("runtime authorization omits a contract, seal-manifest, or independent-audit binding")
        if artifact_map["e4_contract"]["sha256"] != auth["contract_sha256"] or artifact_map["e4_contract_seal_manifest"]["sha256"] != auth["contract_seal_manifest_sha256"]:
            raise AuditError("runtime authorization contract hashes differ from their explicit artifact map")
        contract = read_json(Path(artifact_map["e4_contract"]["path"]))
        if contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V05" or "SEALED" not in str(contract.get("status", "")).upper() or "DRAFT" in str(contract.get("status", "")).upper():
            raise AuditError("runtime authorization artifact is not the sealed E4-0 v05 contract")
        seal_manifest = read_json(Path(artifact_map["e4_contract_seal_manifest"]["path"]))
        seal_entries = seal_manifest.get("entries")
        if (
            seal_manifest.get("schema") != "FAS_E4_0_ARTIFACT_SEAL_V01"
            or seal_manifest.get("stage") != "E4_0_CONTRACT"
            or seal_manifest.get("root_sha256") != auth["contract_seal_root_sha256"]
            or not isinstance(seal_entries, list)
            or e4_root(seal_entries) != auth["contract_seal_root_sha256"]
            or not any(entry.get("sha256") == auth["contract_sha256"] for entry in seal_entries if isinstance(entry, dict))
        ):
            raise AuditError("runtime authorization contract seal artifact/root does not bind the frozen contract")
        contract_audit = read_json(Path(artifact_map["e4_contract_audit"]["path"]))
        audit_root = contract_audit.get(
            "e4_0_contract_root_sha256",
            contract_audit.get("contract_root_sha256", contract_audit.get("contract_seal_root_sha256")),
        )
        if audit_root != auth["contract_seal_root_sha256"] or "PASS" not in str(contract_audit.get("status", "")).upper():
            raise AuditError("runtime authorization lacks a passing independent audit for the sealed contract")
    if not isinstance(project_root, Path):
        raise AuditError("internal project-root error")
    return auth


def _root_subset(auth: Mapping[str, Any], stage: str) -> dict[str, str]:
    roots = dict(auth["exact_predecessor_roots"])
    allowed = {
        "POPULATION_GENERATION": 4,
        "PARITY_PANEL_MATERIALIZATION": 6,
        "ONLINE_CACHE_PARITY": 7,
        "FRESH_FEATURE_EXTRACTION": 8,
        "FRESH_SCORING": 9,
    }[stage]
    return {key: roots[key] for key in E4_ROOT_KEYS[:allowed]}


def _emit_receipt(path: Path | None, audit_type: str, result: Mapping[str, Any]) -> None:
    if path is None:
        print(json.dumps(dict(result), ensure_ascii=True, indent=2, allow_nan=False))
        return
    receipt = {
        "schema": "FAS_E4_0_INDEPENDENT_AUDIT_RECEIPT_V01",
        "audit_type": audit_type,
        "issued_utc": datetime.now(timezone.utc).isoformat(),
        **dict(result),
    }
    payload = (json.dumps(receipt, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": result.get("status"), "receipt": str(path), "sha256": hashlib.sha256(payload).hexdigest()}, ensure_ascii=True))


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--contract-root-sha256", required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Independent, fail-closed E4-0 sealed artifact auditor")
    sub = parser.add_subparsers(dest="mode", required=True)

    contract = sub.add_parser("contract", help="audit final contract seal and bound implementation source map")
    contract.add_argument("--workspace-root", type=Path, required=True)
    contract.add_argument("--contract", type=Path, required=True)
    contract.add_argument("--contract-seal", type=Path, required=True)
    contract.add_argument("--source-map", type=Path, required=True)
    contract.add_argument("--receipt", type=Path)

    population = sub.add_parser("population", help="audit model-free population freshness, schedule, and primary support")
    _common(population)
    population.add_argument("--run-root", type=Path, required=True)
    population.add_argument("--population-seal", type=Path, required=True)
    population.add_argument("--e1-inputs", type=Path, required=True)
    population.add_argument("--e1-manifest", type=Path, required=True)
    population.add_argument("--support-plan", type=Path, required=True)

    parity = sub.add_parser("parity", help="audit parity panel, exact feature bytes and five-head agreement")
    _common(parity)
    parity.add_argument("--run-root", type=Path, required=True)
    parity.add_argument("--panel-seal", type=Path, required=True)
    parity.add_argument("--parity-seal", type=Path, required=True)
    parity.add_argument("--e1-inputs", type=Path, required=True)
    parity.add_argument("--e1-manifest", type=Path, required=True)
    parity.add_argument("--e1-feature-cache", type=Path, required=True)
    parity.add_argument("--e1-feature-cache-sha256", required=True)
    parity.add_argument("--e3-seal", type=Path, required=True)

    features = sub.add_parser("features", help="audit fresh feature seal, cache integrity and ordered row mapping")
    _common(features)
    features.add_argument("--run-root", type=Path, required=True)
    features.add_argument("--feature-seal", type=Path, required=True)

    scoring = sub.add_parser("score", help="independently reconstruct frozen head predictions and qualification")
    _common(scoring)
    scoring.add_argument("--run-root", type=Path, required=True)
    scoring.add_argument("--score-seal", type=Path, required=True)
    scoring.add_argument("--population-seal", type=Path, required=True)
    scoring.add_argument("--population-audit", type=Path, required=True)
    scoring.add_argument("--panel-seal", type=Path, required=True)
    scoring.add_argument("--parity-seal", type=Path, required=True)
    scoring.add_argument("--feature-seal", type=Path, required=True)
    scoring.add_argument("--population-manifest", type=Path, required=True)
    scoring.add_argument("--feature-cache", type=Path, required=True)
    scoring.add_argument("--e1-inputs", type=Path, required=True)
    scoring.add_argument("--e1-manifest", type=Path, required=True)
    scoring.add_argument("--e1-feature-cache", type=Path, required=True)
    scoring.add_argument("--e1-feature-cache-sha256", required=True)
    scoring.add_argument("--support-plan", type=Path, required=True)
    scoring.add_argument("--e3-seal", type=Path, required=True)
    return parser


def resolve_workspace_root(module_file: str | Path) -> Path:
    """Resolve the repository root from experiments/<project>/source/scripts/<package>."""
    return Path(module_file).resolve().parents[5]


def run(args: argparse.Namespace, workspace_root: Path) -> dict[str, Any]:
    if args.mode == "contract":
        result = validate_contract_seal(args.workspace_root, args.contract, args.contract_seal)
        source = validate_source_map(args.workspace_root, args.source_map)
        return {**result, "source_map": source, "all_checks_passed": True}
    auth = _auth(args.authorization, {
        "population": "POPULATION_GENERATION",
        "parity": "ONLINE_CACHE_PARITY",
        "features": "FRESH_FEATURE_EXTRACTION",
        "score": "FRESH_SCORING",
    }[args.mode], workspace_root)
    if Path(auth["output_root"]).resolve() != args.run_root.resolve():
        raise AuditError("audited run root differs from the stage authorization")
    if auth["contract_sha256"] != args.contract_sha256 or auth["contract_seal_root_sha256"] != args.contract_root_sha256:
        raise AuditError("CLI contract identity differs from stage authorization")
    predecessors = _root_subset(auth, auth["stage"])
    if args.mode == "population":
        result = audit_population(
            seal_path=args.population_seal,
            run_root=args.run_root,
            contract_sha256=args.contract_sha256,
            contract_root_sha256=args.contract_root_sha256,
            expected_predecessors=predecessors,
            e1_inputs=args.e1_inputs,
            e1_manifest=args.e1_manifest,
            support_plan_path=args.support_plan,
        )
        if result["population_root_sha256"] != auth["exact_predecessor_roots"].get("e4_population_root_sha256", result["population_root_sha256"]):
            raise AuditError("population audit root does not match the later-stage authorization root")
        return result
    if args.mode == "parity":
        panel_predecessors = _root_subset(auth, "PARITY_PANEL_MATERIALIZATION")
        parity_predecessors = _root_subset(auth, "ONLINE_CACHE_PARITY")
        # When called at parity stage the population roots are in its authorization; the panel
        # and parity seals carry their own exact predecessor subset.
        result = verify_parity_stage(
            panel_seal_path=args.panel_seal,
            parity_seal_path=args.parity_seal,
            run_root=args.run_root,
            contract_sha256=args.contract_sha256,
            contract_root_sha256=args.contract_root_sha256,
            panel_predecessors=panel_predecessors,
            parity_predecessors=parity_predecessors,
            e1_inputs=args.e1_inputs,
            e1_manifest=args.e1_manifest,
            e1_feature_cache=args.e1_feature_cache,
            e1_feature_cache_sha256=args.e1_feature_cache_sha256,
            e3_seal_path=args.e3_seal,
        )
        return result
    if args.mode == "features":
        return verify_feature_stage(
            seal_path=args.feature_seal,
            run_root=args.run_root,
            contract_sha256=args.contract_sha256,
            contract_root_sha256=args.contract_root_sha256,
            expected_predecessors=predecessors,
        )
    if args.mode == "score":
        pop_result = audit_population(
            seal_path=args.population_seal,
            run_root=args.run_root,
            contract_sha256=args.contract_sha256,
            contract_root_sha256=args.contract_root_sha256,
            expected_predecessors=_root_subset(auth, "POPULATION_GENERATION"),
            e1_inputs=args.e1_inputs,
            e1_manifest=args.e1_manifest,
            support_plan_path=args.support_plan,
        )
        if pop_result["population_root_sha256"] != auth["exact_predecessor_roots"].get("e4_population_root_sha256"):
            raise AuditError("score authorization does not bind the population root replayed by audit")
        audit_sha, _ = sha256_file(args.population_audit)
        if audit_sha != auth["exact_predecessor_roots"].get("e4_population_audit_root_sha256"):
            raise AuditError("score authorization does not bind the population audit receipt bytes")
        pop_audit = read_json(args.population_audit)
        if pop_audit.get("status") != "PASS_POPULATION_FRESHNESS_SUPPORT" or pop_audit.get("population_root_sha256") != pop_result["population_root_sha256"]:
            raise AuditError("sealed population audit receipt is missing or mismatched")
        verify_parity_stage(
            panel_seal_path=args.panel_seal,
            parity_seal_path=args.parity_seal,
            run_root=args.run_root,
            contract_sha256=args.contract_sha256,
            contract_root_sha256=args.contract_root_sha256,
            panel_predecessors=_root_subset(auth, "PARITY_PANEL_MATERIALIZATION"),
            parity_predecessors=_root_subset(auth, "ONLINE_CACHE_PARITY"),
            e1_inputs=args.e1_inputs,
            e1_manifest=args.e1_manifest,
            e1_feature_cache=args.e1_feature_cache,
            e1_feature_cache_sha256=args.e1_feature_cache_sha256,
            e3_seal_path=args.e3_seal,
        )
        feature_result = verify_feature_stage(
            seal_path=args.feature_seal,
            run_root=args.run_root,
            contract_sha256=args.contract_sha256,
            contract_root_sha256=args.contract_root_sha256,
            expected_predecessors=_root_subset(auth, "FRESH_FEATURE_EXTRACTION"),
        )
        population_manifest_sha, _ = sha256_file(args.population_manifest)
        feature_seal = read_json(args.feature_seal)
        feature_manifest_entry = next(
            (item for item in feature_seal.get("entries", []) if item.get("artifact_id") == "population_row_manifest"),
            None,
        )
        pop_seal = read_json(args.population_seal)
        pop_manifest_entry = next(
            (item for item in pop_seal.get("entries", []) if item.get("artifact_id") == "E4_POPULATION_ROW_MANIFEST_V01"),
            None,
        )
        if not isinstance(feature_manifest_entry, dict) or not isinstance(pop_manifest_entry, dict) or feature_manifest_entry.get("sha256") != population_manifest_sha or feature_manifest_entry.get("sha256") != pop_manifest_entry.get("sha256"):
            raise AuditError("feature cache row mapping is not the exact population row manifest")
        feature_entry = next((item for item in feature_seal.get("entries", []) if item.get("artifact_id") == "feature_cache"), None)
        if not isinstance(feature_entry, dict) or Path(args.feature_cache).resolve() != (args.run_root / Path(feature_entry["path"])).resolve():
            raise AuditError("supplied feature cache path is not the cache bound by the feature seal")
        result = audit_scoring_stage(
            score_seal_path=args.score_seal,
            run_root=args.run_root,
            contract_sha256=args.contract_sha256,
            contract_root_sha256=args.contract_root_sha256,
            expected_predecessors=predecessors,
            feature_cache_path=args.feature_cache,
            population_manifest_path=args.population_manifest,
            e3_seal_path=args.e3_seal,
            expected_e3_root=EXPECTED_PREDECESSORS["e3_v02_bundle_root_sha256"],
        )
        result["population_audit_root_sha256"] = pop_audit.get("population_root_sha256")
        result["feature_cache_root_sha256"] = feature_result.get("feature_root_sha256")
        return result
    raise AuditError(f"unsupported audit mode: {args.mode}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workspace_root = resolve_workspace_root(__file__)
    try:
        result = run(args, workspace_root)
        _emit_receipt(args.receipt, args.mode, result)
        return 0
    except Exception as exc:
        print(f"E4-0 audit stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
