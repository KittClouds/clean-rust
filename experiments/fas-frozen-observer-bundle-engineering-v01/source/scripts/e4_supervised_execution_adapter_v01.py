"""Strict input binding for the Ledger-supervised E4-0 runner.

This module carries no stage authority and acquires no lease. The parent
KAMMI_LOCAL_EXECUTION_V1 worker owns authorization, fencing, process lifetime,
output import, and the external completion receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ADAPTER_ID = "FAS_FROZEN_OBSERVER_BUNDLE_E4_0_LEDGER_SUPERVISED_ADAPTER_V01"
SCHEMA = "FAS_E4_0_SUPERVISED_EXECUTION_BINDING_V01"
CONTRACT_SHA256 = "21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f"
CONTRACT_ROOT = "278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1"
LIBRARY_ACCEPTANCE_ID = "sha256:daae9a9496b6dc15f5a256d966323fcb8848387f3ce3c7d926db7039d7fe7c8c"
HANDOFF_SEAL_ROOT = "ad1ffbc9203fd0cac5553ea4a5d3c72654c22054e68348474414096e35dd8cc5"
VISIBLE_BRIDGE_ROOT = "aacfd286b6349f0b35adb853a2cd9717c2463fedfeccc052bafaf515c69b027b"

COMMON_ARTIFACTS = frozenset({
    "e4_contract", "e4_contract_seal_manifest", "e4_contract_audit",
    "e1_audit", "e2_audit", "e3_audit", "population_seal", "population_audit",
    "population_inputs", "population_rows", "parity_inputs", "parity_rows",
    "parity_selection_receipt",
})
MODE_ARTIFACTS = {
    "parity": frozenset({
        "representation_abi", "model_manifest", "tokenizer_manifest",
        "e2_cache", "e3_bundle", "parity_panel_seal",
    }),
    "extract-e4": frozenset({
        "representation_abi", "model_manifest", "tokenizer_manifest",
        "parity_panel_seal", "parity_receipt_seal", "parity_receipt",
        "online_feature_cache",
    }),
}
MODE_STAGE = {
    "parity": "ONLINE_CACHE_PARITY",
    "extract-e4": "FRESH_FEATURE_EXTRACTION",
}
OUTPUTS = {
    "parity": (
        "parity-online-features.f32le",
        "parity-receipt-v01.json",
        "stage-seal-v01.json",
    ),
    "extract-e4": (
        "V1_FINAL_POSITION.f32le",
        "feature-extraction-receipt-v01.json",
        "population-row-manifest-v01.jsonl",
        "stage-seal-v01.json",
    ),
}
MODE_OUTPUT_DIR = {"parity": "parity", "extract-e4": "features"}
PATH_KEYS = frozenset({
    "model_snapshot", "tokenizer_snapshot",
    "model_asset_manifest", "tokenizer_asset_manifest",
})
BASE_PREDECESSOR_ROOT_KEYS = frozenset({
    "e0_v10_root_sha256", "e1_v04_root_sha256", "e2_v07_root_sha256",
    "e3_v02_bundle_root_sha256", "e4_population_root_sha256",
    "e4_population_audit_root_sha256", "e4_parity_panel_root_sha256",
})
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class BindingError(ValueError):
    """The static Fabrique input binding is malformed or out of scope."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BindingError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_sha256(value: Any, name: str) -> None:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise BindingError(f"{name} must be lowercase SHA-256 hex")


def validate_binding_document(value: Any, mode: str) -> dict[str, Any]:
    """Validate the non-authoritative E4 input map before scientific imports."""
    if mode not in MODE_ARTIFACTS:
        raise BindingError(f"unsupported E4 supervised mode: {mode}")
    if not isinstance(value, dict):
        raise BindingError("execution binding must be a JSON object")
    expected_fields = {
        "schema", "adapter_id", "mode", "stage", "contract_sha256",
        "contract_seal_manifest_sha256", "contract_seal_root_sha256",
        "output_root", "supervised_output_root", "inherited_stage_root",
        "expected_outputs", "exact_predecessor_roots",
        "artifacts", "paths", "library_handoff",
    }
    if set(value) != expected_fields:
        raise BindingError("execution binding fields differ from the frozen v1 schema")
    if value["schema"] != SCHEMA or value["adapter_id"] != ADAPTER_ID:
        raise BindingError("execution binding schema or adapter identity mismatch")
    if value["mode"] != mode or value["stage"] != MODE_STAGE[mode]:
        raise BindingError("execution binding is bound to another mode/stage")
    if value["contract_sha256"] != CONTRACT_SHA256:
        raise BindingError("execution binding does not identify E4-0 v16-v09 contract bytes")
    if value["contract_seal_root_sha256"] != CONTRACT_ROOT:
        raise BindingError("execution binding does not identify the sealed E4-0 v16-v09 root")
    _require_sha256(value["contract_seal_manifest_sha256"], "contract seal manifest hash")
    if not isinstance(value["output_root"], str) or not Path(value["output_root"]).is_absolute():
        raise BindingError("output_root must be an absolute path")
    if not isinstance(value["inherited_stage_root"], str) or not Path(value["inherited_stage_root"]).is_absolute():
        raise BindingError("inherited_stage_root must be an absolute path")
    expected_worker_root = Path(value["output_root"]).resolve() / MODE_OUTPUT_DIR[mode]
    if (not isinstance(value["supervised_output_root"], str)
            or Path(value["supervised_output_root"]).resolve() != expected_worker_root):
        raise BindingError("Ledger worker output_root must be the fresh mode-specific child of output_root")
    if value["expected_outputs"] != list(OUTPUTS[mode]):
        raise BindingError("output inventory differs from the fixed supervised E4 inventory")
    roots = value["exact_predecessor_roots"]
    expected_root_keys = BASE_PREDECESSOR_ROOT_KEYS | (
        {"e4_parity_receipt_root_sha256"} if mode == "extract-e4" else set()
    )
    if not isinstance(roots, dict) or set(roots) != expected_root_keys:
        raise BindingError("exact predecessor root set differs from the E4-0 contract")
    for key, digest in roots.items():
        _require_sha256(digest, key)
    required_artifacts = COMMON_ARTIFACTS | MODE_ARTIFACTS[mode]
    artifacts = value["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != required_artifacts:
        raise BindingError("artifact inventory differs from the fixed mode input inventory")
    for name, entry in artifacts.items():
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}:
            raise BindingError(f"artifact identity is malformed: {name}")
        if not isinstance(entry["path"], str) or not Path(entry["path"]).is_absolute():
            raise BindingError(f"artifact path is not absolute: {name}")
        _require_sha256(entry["sha256"], f"{name}.sha256")
        if type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise BindingError(f"artifact byte length is invalid: {name}")
    paths = value["paths"]
    if not isinstance(paths, dict) or set(paths) != PATH_KEYS:
        raise BindingError("local model/tokenizer path inventory differs from v1")
    if any(not isinstance(path, str) or not Path(path).is_absolute() for path in paths.values()):
        raise BindingError("model/tokenizer asset paths must be absolute")
    handoff = value["library_handoff"]
    if not isinstance(handoff, dict) or set(handoff) != {
        "library_acceptance_id", "handoff_seal_root_sha256",
        "visible_inheritance_bridge_root_sha256",
    }:
        raise BindingError("Library handoff identity fields differ from the qualified handoff")
    if handoff != {
        "library_acceptance_id": LIBRARY_ACCEPTANCE_ID,
        "handoff_seal_root_sha256": HANDOFF_SEAL_ROOT,
        "visible_inheritance_bridge_root_sha256": VISIBLE_BRIDGE_ROOT,
    }:
        raise BindingError("Library handoff or visible-only bridge identity mismatch")

    # Reject authority-shaped fields anywhere in the static input object. Actual
    # run/stage grants, authorization, lease, and fence are handled by the parent
    # Ledger worker and are deliberately absent from this child binding.
    forbidden = {"authorization_id", "authorized_by", "status", "scope", "gpu_lease",
                 "lease_id", "resource_id", "fencing_token", "actor_token", "grant_id"}
    if forbidden.intersection(value):
        raise BindingError("static input binding must not carry authority or lease fields")
    return value


def load_binding(path: Path, mode: str) -> tuple[dict[str, Any], str]:
    resolved = path.resolve(strict=True)
    raw = resolved.read_bytes()
    value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    binding = validate_binding_document(value, mode)
    return binding, hashlib.sha256(raw).hexdigest()
