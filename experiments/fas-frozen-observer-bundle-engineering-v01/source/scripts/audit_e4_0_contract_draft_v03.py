from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "plans"
CONTRACT = PLANS / "E4-0-CONTRACT-DRAFT-v03.json"
PREDECESSOR = PLANS / "E4-0-CONTRACT-DRAFT-v02.json"
SOURCE_MAP = PLANS / "E4-0-IMPLEMENTATION-SOURCE-MAP-v01.md"
SUPPORT = PLANS / "E4-0-SYMBOLIC-SUPPORT-PLAN-v09.json"
OUTPUT = PLANS / "E4-0-CONTRACT-DRAFT-v03-independent-audit.json"
REPO = ROOT.parents[1]
EXPECTED_PREDECESSOR_SHA256 = "5daa408426a54d5c54a53cf074d8c5ec44c904fa3c28abfb52de56e826c9c92d"


def sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fail(message: str) -> None:
    raise RuntimeError(message)


def resolve_bound_path(value: str) -> Path:
    path = Path(value)
    local = ROOT / path
    if local.is_file():
        return local
    external = REPO / path
    if external.is_file():
        return external
    fail(f"bound input is missing: {value}")


def normalized_v02(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result["contract_id"] = "<same-contract-family>"
    result["draft_revision"] = 2
    result.pop("supersedes", None)
    for key in (
        "implementation_source_map_v01_path",
        "implementation_source_map_v01_sha256",
        "implementation_source_map_v01_bytes",
    ):
        result["design_inputs"].pop(key, None)
    result["draft_builder"] = {"path": "<builder>", "sha256": "<hash>", "bytes": 0, "role": "<role>"}
    return result


def normalized_v03(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result["contract_id"] = "<same-contract-family>"
    result["draft_revision"] = 2
    result.pop("supersedes", None)
    for key in (
        "implementation_source_map_v01_path",
        "implementation_source_map_v01_sha256",
        "implementation_source_map_v01_bytes",
    ):
        result["design_inputs"].pop(key, None)
    result["draft_builder"] = {"path": "<builder>", "sha256": "<hash>", "bytes": 0, "role": "<role>"}
    return result


def main() -> int:
    contract = load(CONTRACT)
    predecessor = load(PREDECESSOR)
    support = load(SUPPORT)
    errors: list[str] = []

    previous_hash, _ = sha256(PREDECESSOR)
    if previous_hash != EXPECTED_PREDECESSOR_SHA256:
        errors.append("v02 predecessor bytes differ from the bound revision")
    if contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V03":
        errors.append("wrong v03 contract identity")
    if contract.get("status") != "DRAFT_NOT_SEALED_NOT_AUTHORIZED_SOURCE_HASHES_PENDING":
        errors.append("v03 is not marked as an unsealed, unauthorized draft")
    if contract.get("supersedes") != {
        "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V02",
        "sha256": previous_hash,
        "reason": "Bind the codebase-specific implementation source map; scientific and resource gates are unchanged.",
    }:
        errors.append("supersession receipt does not bind v02 exactly")

    source_map_hash, source_map_bytes = sha256(SOURCE_MAP)
    inputs = contract.get("design_inputs", {})
    if inputs.get("implementation_source_map_v01_path") != str(SOURCE_MAP.relative_to(ROOT)).replace("\\", "/"):
        errors.append("implementation source map path mismatch")
    if inputs.get("implementation_source_map_v01_sha256") != source_map_hash:
        errors.append("implementation source map SHA-256 mismatch")
    if inputs.get("implementation_source_map_v01_bytes") != source_map_bytes:
        errors.append("implementation source map byte count mismatch")

    for field in (
        "e4_0_design_v03",
        "template_manifest",
        "template_text_audit",
        "template_structural_audit",
        "symbolic_support_plan",
        "implementation_source_map_v01",
    ):
        path = resolve_bound_path(inputs[f"{field}_path"])
        digest, size = sha256(path)
        if digest != inputs[f"{field}_sha256"]:
            errors.append(f"design input hash mismatch: {field}")
        byte_key = f"{field}_bytes"
        if byte_key in inputs and size != inputs[byte_key]:
            errors.append(f"design input byte count mismatch: {field}")

    if normalized_v02(predecessor) != normalized_v03(contract):
        errors.append("v03 changed content outside version metadata/source-map binding")

    for section_name in ("authorization", "execution_identity"):
        section = contract.get(section_name, {})
        for key, value in section.items():
            if key.endswith("authorized") and value is not False:
                errors.append(f"authorization unexpectedly enabled: {section_name}.{key}")

    required_sources = (
        "e4_population_generator",
        "e4_online_feature_and_parity_runner",
        "e4_fresh_scorer",
        "e4_independent_auditor",
    )
    pending = contract.get("implementation_sources_not_yet_bound", {})
    if [name for name in required_sources if pending.get(name) is not None]:
        errors.append("runtime implementation source was bound without the required source review")
    if any(
        support.get(key)
        for key in ("population_rows_written", "tokenizer_contacted", "model_contacted", "labels_opened")
    ):
        errors.append("support planner receipt indicates prohibited execution")

    if errors:
        fail("; ".join(errors))

    auditor_hash, auditor_bytes = sha256(Path(__file__).resolve())
    result = {
        "receipt_id": "FAS_E4_0_CONTRACT_DRAFT_V03_INDEPENDENT_AUDIT",
        "status": "DRAFT_AUDIT_PASS_WITH_IMPLEMENTATION_SOURCE_BLOCKERS",
        "contract_path": str(CONTRACT.relative_to(ROOT)).replace("\\", "/"),
        "contract_sha256": sha256(CONTRACT)[0],
        "predecessor_contract_sha256": previous_hash,
        "implementation_source_map_sha256": source_map_hash,
        "implementation_source_map_bytes": source_map_bytes,
        "auditor_source_path": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
        "auditor_source_sha256": auditor_hash,
        "auditor_source_bytes": auditor_bytes,
        "unchanged_sections_compared": [
            "predecessors", "representation_abi", "population", "parity", "fresh_qualification",
            "truth_access", "resources", "phase_gates", "stop_rule", "E4_A_dependency",
        ],
        "execution_sources_pending": list(required_sources),
        "authorizations_open": False,
        "population_rows_written": False,
        "tokenizer_contacted": False,
        "model_contacted": False,
        "labels_opened": False,
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
