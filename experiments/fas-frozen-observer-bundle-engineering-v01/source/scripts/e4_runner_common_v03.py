"""Shared E4-0 identity, authorization, and parity-panel selection primitives."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence


PROJECT = "fas-frozen-observer-bundle-engineering-v01"
E0_ROOT = "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd"
E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
E2_ROOT = "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a"
E3_BUNDLE_ROOT = "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1"
INHERITED_E4_V06_CONTRACT_SHA256 = "ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958"
INHERITED_E4_V06_CONTRACT_ROOT = "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64"
ARTIFACT_SEAL_SCHEMA = "FAS_E4_0_ARTIFACT_SEAL_V01"
E1_CACHE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
E1_CACHE_BYTES = 872_415_232
E1_ROWS = 106_496
DIMENSION = 2_048
FEATURE_ROW_BYTES = DIMENSION * 4
E4_QUARTETS = 18_667
E4_ROWS = 149_336
E4_CACHE_BYTES = E4_ROWS * FEATURE_ROW_BYTES
PARITY_QUARTETS = 256
PARITY_ROWS = PARITY_QUARTETS * 4
GPU_RESERVED_LIMIT_BYTES = 10 * 1024**3
HOST_RAM_LIMIT_BYTES = 25 * 1024**3
VARIANTS = ("A", "C", "E", "P")
PRIMARY_SURFACE = "PRIMARY_SEEN"
HELDOUT_SURFACE = "HELDOUT_TEMPLATE"
PRIMARY_CUSTODY = "PRIMARY_TERMINAL"
ESCROW_CUSTODY = "TEMPLATE_ESCROW"
PARITY_DOMAIN = b"FAS-E4-0-PARITY-v01\x00"

QUERY_TEMPLATES = (
    "What is {relation} for {entity} in {context}?",
    "Find the {relation} of {entity} at {context}.",
    "Select {relation}({context}, {entity}).",
    "Report {entity}'s {relation} within {context}.",
    "Return current {relation}: {context} / {entity}.",
    "Which value is stored for {relation} and {entity} under {context}?",
    "Give the {relation} linked to {entity} in {context}.",
    "Look up {context} -> {entity} -> {relation}.",
)
RELATION_TERMS = frozenset(("kelmori", "vethaku"))
HEADS = {
    "context_identity": 32,
    "entity_identity": 32,
    "relation": 2,
    "observed_state": 3,
    "exact_target": 3,
}
CONTRACT_STAGES = {
    "parity": ("ONLINE_CACHE_PARITY", ("model_contact", "feature_extraction")),
    "extract-e4": ("FRESH_FEATURE_EXTRACTION", ("model_contact", "feature_extraction")),
}


class E4RunnerError(RuntimeError):
    """Fail-closed runner error; callers preserve any created attempt files."""


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_json_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.partial")
    with temp.open("xb", buffering=0) as stream:
        stream.write(canonical_json_bytes(value))
        os.fsync(stream.fileno())
    os.replace(temp, path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise E4RunnerError(f"expected a JSON object: {path}")
    return value


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise E4RunnerError(f"invalid JSONL at {path.name}:{line_number}") from error
            if not isinstance(value, dict):
                raise E4RunnerError(f"JSONL item is not an object at {path.name}:{line_number}")
            yield value


def file_identity(path_value: str | Path, expected_sha256: str, expected_bytes: int) -> dict[str, Any]:
    path = Path(path_value).resolve(strict=True)
    digest, size = sha256_file(path)
    if digest != expected_sha256 or size != expected_bytes:
        raise E4RunnerError(f"bound input identity mismatch: {path}")
    return {"path": str(path), "sha256": digest, "bytes": size}


def verify_bound_artifacts(authorization: Mapping[str, Any], names: Iterable[str]) -> dict[str, dict[str, Any]]:
    artifacts = authorization.get("artifacts")
    if not isinstance(artifacts, dict):
        raise E4RunnerError("authorization has no explicit artifact map")
    verified: dict[str, dict[str, Any]] = {}
    for name in names:
        entry = artifacts.get(name)
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}:
            raise E4RunnerError(f"authorization is missing a complete identity for artifact {name}")
        if type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise E4RunnerError(f"authorization has an invalid byte length for artifact {name}")
        if not isinstance(entry["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None:
            raise E4RunnerError(f"authorization has an invalid SHA-256 identity for artifact {name}")
        verified[name] = file_identity(entry["path"], entry["sha256"], int(entry["bytes"]))
    return verified


def verify_contract_binding(authorization: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(authorization.get("artifacts"), dict):
        raise E4RunnerError("authorization has no artifact identities")
    identities = verify_bound_artifacts(
        authorization, ("e4_contract", "e4_contract_seal_manifest", "e4_contract_audit"),
    )
    if authorization.get("contract_sha256") != identities["e4_contract"]["sha256"]:
        raise E4RunnerError("top-level contract hash differs from the bound contract artifact")
    if authorization.get("contract_seal_manifest_sha256") != identities["e4_contract_seal_manifest"]["sha256"]:
        raise E4RunnerError("top-level seal-manifest hash differs from its bound artifact")
    contract = read_json(Path(identities["e4_contract"]["path"]))
    seal = read_json(Path(identities["e4_contract_seal_manifest"]["path"]))
    audit = read_json(Path(identities["e4_contract_audit"]["path"]))
    if contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V07":
        raise E4RunnerError("unexpected E4-0 contract identity")
    status = str(contract.get("status", "")).upper()
    if "DRAFT" in status or "SEALED" not in status:
        raise E4RunnerError("E4-0 contract is not sealed")
    root = authorization.get("contract_seal_root_sha256")
    if (
        seal.get("schema") != ARTIFACT_SEAL_SCHEMA
        or seal.get("status") != "SEALED"
        or seal.get("seal_id") != "FAS_E4_0_CONTRACT_V07_SEAL"
        or seal.get("stage") != "E4_0_CONTRACT"
        or seal.get("path_root_kind") != "WORKSPACE_ROOT"
        or seal.get("root_sha256") != root
    ):
        raise E4RunnerError("E4-0 seal root differs from the authorized root")
    entries = seal.get("entries")
    if not isinstance(entries, list) or not entries or seal.get("entry_count") != len(entries):
        raise E4RunnerError("E4-0 seal member list or count is invalid")
    sorted_entries = sorted(entries, key=lambda item: str(item.get("artifact_id", "")).encode("utf-8"))
    if entries != sorted_entries:
        raise E4RunnerError("E4-0 seal members are not in canonical artifact-ID order")
    root_builder = hashlib.sha256()
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"artifact_id", "path", "bytes", "sha256"}:
            raise E4RunnerError("E4-0 seal member schema is invalid")
        artifact_id = entry["artifact_id"]
        relative = entry["path"]
        if (not isinstance(artifact_id, str) or not artifact_id or artifact_id in seen_ids
                or not isinstance(relative, str) or relative.startswith("/") or "\\" in relative
                or any(part in ("", ".", "..") for part in relative.split("/"))
                or relative in seen_paths or type(entry["bytes"]) is not int or entry["bytes"] < 0
                or not isinstance(entry["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None):
            raise E4RunnerError("E4-0 seal member identity is malformed or duplicated")
        seen_ids.add(artifact_id)
        seen_paths.add(relative)
        root_builder.update(f"{artifact_id}\t{relative}\t{entry['bytes']}\t{entry['sha256']}\n".encode("utf-8"))
    if root_builder.hexdigest() != root:
        raise E4RunnerError("E4-0 seal root failed independent recomputation")
    if any(contract.get("predecessors", {}).get(key) != value for key, value in seal.get("exact_predecessor_roots", {}).items()):
        raise E4RunnerError("E4-0 seal predecessor roots differ from the final contract")
    audit_root = audit.get(
        "e4_0_contract_root_sha256",
        audit.get("contract_root_sha256", audit.get("contract_seal_root_sha256",
            audit.get("final_seal", {}).get("root_sha256") if isinstance(audit.get("final_seal"), dict) else None)),
    )
    if (audit_root != root or audit.get("pass") is not True
            or audit.get("status") != "E4_0_TRACK_E_POSTSEAL_PASS_V07_SEAL_ROOT_AND_MEMBERS_RECOMPUTED"):
        raise E4RunnerError("independent E4-0 contract audit is absent or not bound to the sealed root")
    contract_members = [item for item in entries if isinstance(item, dict)
                        and item.get("artifact_id") == "E4_0_CONTRACT_V07_FINAL"]
    if len(contract_members) != 1 or (
        contract_members[0].get("path") != "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v07-final.json"
        or contract_members[0].get("sha256") != identities["e4_contract"]["sha256"]
        or contract_members[0].get("bytes") != identities["e4_contract"]["bytes"]
    ):
        raise E4RunnerError("contract seal manifest does not contain the bound contract bytes")
    return {"contract": contract, "seal": seal, "audit": audit, "root_sha256": root, **identities}


def validate_stage_authorization(
    authorization: Mapping[str, Any], mode: str, now: datetime | None = None,
) -> dict[str, Any]:
    if mode not in CONTRACT_STAGES:
        raise E4RunnerError(f"unknown execution mode: {mode}")
    stage, _ = CONTRACT_STAGES[mode]
    schema_path = Path(__file__).resolve().parents[2] / "contracts" / "e4-0-stage-authorization-schema-v01.json"
    normative = read_json(schema_path)
    if authorization.get("schema") != normative.get("schema"):
        raise E4RunnerError("stage authorization schema identity is absent or changed")
    required_top = normative.get("required_top_level_fields")
    if not isinstance(required_top, list) or any(name not in authorization for name in required_top):
        raise E4RunnerError("stage authorization omits a normative top-level field")
    if authorization.get("authorization_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_STAGE_AUTHORIZATION_V01":
        raise E4RunnerError("E4-0 stage authorization identity is absent")
    if authorization.get("status") != "AUTHORIZED" or authorization.get("stage") != stage:
        raise E4RunnerError("E4-0 authorization is absent or bound to a different stage")
    if authorization.get("authorized_by") != normative.get("authorized_by_value"):
        raise E4RunnerError("stage authorization is not attributed to the active user request")
    output_root = authorization.get("output_root")
    if not isinstance(output_root, str) or not Path(output_root).is_absolute():
        raise E4RunnerError("stage authorization output_root must be an exact absolute path")
    expected_scopes = set(normative.get("scope_fields_exact", []))
    scope = authorization.get("scope")
    if not isinstance(scope, dict) or set(scope) != expected_scopes or any(type(value) is not bool for value in scope.values()):
        raise E4RunnerError("stage authorization must bind all ten boolean scope keys")
    stage_definition = normative.get("stages", {}).get(stage)
    if not isinstance(stage_definition, dict):
        raise E4RunnerError("stage is absent from the normative authorization schema")
    true_scopes = set(stage_definition.get("true_scope_fields", []))
    if {key for key, enabled in scope.items() if enabled} != true_scopes:
        raise E4RunnerError("stage authorization contains missing or overbroad true scopes")
    if scope.get("evaluation_label_opening") or scope.get("scoring"):
        raise E4RunnerError("E4-0 runner authorization improperly opens fresh labels or scoring")
    issued, start, end = (authorization.get(k) for k in (
        "issued_utc_unix_seconds", "valid_from_utc_unix_seconds", "valid_until_utc_unix_seconds",
    ))
    if any(type(value) is not int for value in (issued, start, end)) or not issued <= start < end:
        raise E4RunnerError("authorization does not bind a valid finite UTC execution interval")
    current = int((now or datetime.now(timezone.utc)).timestamp())
    if start > current or current >= end:
        raise E4RunnerError("current time is outside the authorized interval")
    verified_contract = verify_contract_binding(authorization)
    roots = authorization.get("exact_predecessor_roots")
    expected_historical = {
        "e0_v10_root_sha256": E0_ROOT,
        "e1_v04_root_sha256": E1_ROOT,
        "e2_v07_root_sha256": E2_ROOT,
        "e3_v02_bundle_root_sha256": E3_BUNDLE_ROOT,
    }
    if not isinstance(roots, dict) or any(roots.get(k) != v for k, v in expected_historical.items()):
        raise E4RunnerError("authorization does not bind the exact sealed historical roots")
    if set(normative.get("predecessor_roots_always_required", [])) - set(roots):
        raise E4RunnerError("authorization omits a normative historical predecessor root")
    contract_predecessors = verified_contract["contract"].get("predecessors", {})
    for key, expected in expected_historical.items():
        if contract_predecessors.get(key) != expected:
            raise E4RunnerError(f"sealed E4-0 contract predecessor mismatch: {key}")
    required_e4_roots = stage_definition.get("required_additional_roots", [])
    for key in required_e4_roots:
        value = roots.get(key)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise E4RunnerError(f"stage authorization lacks exact prerequisite root: {key}")
    return verified_contract


def load_term_sets(path: Path) -> tuple[frozenset[str], frozenset[str]]:
    inventory = read_json(path)
    contexts, entities = inventory.get("context_terms"), inventory.get("entity_terms")
    if not isinstance(contexts, list) or not isinstance(entities, list) or len(contexts) != 32 or len(entities) != 32:
        raise E4RunnerError("E1 term inventory does not contain the registered context/entity tables")
    return frozenset(contexts), frozenset(entities)


def infer_query_template_id(input_text: str, contexts: frozenset[str], entities: frozenset[str]) -> int:
    lines = input_text.splitlines()
    if len(lines) < 3 or not lines[-1].startswith("Options: "):
        raise E4RunnerError("E1 input does not have the registered observation/query/options shape")
    query_line = lines[-2]
    matches: list[int] = []
    for index, template in enumerate(QUERY_TEMPLATES):
        pattern = re.escape(template)
        for name in ("relation", "entity", "context"):
            pattern = pattern.replace(re.escape("{" + name + "}"), f"(?P<{name}>.+?)")
        match = re.fullmatch(pattern, query_line)
        if match is None:
            continue
        values = match.groupdict()
        if values["relation"] in RELATION_TERMS and values["context"] in contexts and values["entity"] in entities:
            matches.append(index)
    if len(matches) != 1:
        raise E4RunnerError(f"query line has {len(matches)} matches in the frozen E1 template set")
    return matches[0]


def build_parity_quartets(
    input_rows: Iterable[Mapping[str, Any]], manifest_rows: Iterable[Mapping[str, Any]],
    split_rows: Iterable[Mapping[str, Any]], contexts: frozenset[str], entities: frozenset[str],
    tokenize: Callable[[str], Sequence[int]],
) -> list[dict[str, Any]]:
    splits: dict[str, str] = {}
    for row in split_rows:
        if set(row) != {"exact_target_stratum", "quartet_id", "split", "split_assignment"}:
            raise E4RunnerError("E1 split row schema differs from its sealed contract")
        quartet, split = row.get("quartet_id"), row.get("split")
        if not isinstance(quartet, str) or split not in ("FIT", "TEST") or quartet in splits:
            raise E4RunnerError("E1 split manifest has a malformed or duplicate quartet")
        splits[quartet] = split
    groups: dict[str, dict[str, Any]] = {}
    sentinel = object()
    count = 0
    for count, pair in enumerate(zip_longest(input_rows, manifest_rows, fillvalue=sentinel), start=1):
        input_row, manifest = pair
        if input_row is sentinel or manifest is sentinel:
            raise E4RunnerError("E1 inputs and row manifest have different row counts")
        if set(input_row) != {"row_id", "quartet_id", "variant_id", "input_text"}:
            raise E4RunnerError("E1 model input row contains extra fields or labels")
        if set(manifest) != {"row_index", "row_id", "quartet_id", "variant_id", "quartet_split"}:
            raise E4RunnerError("E1 row manifest schema differs from its sealed contract")
        if type(manifest["row_index"]) is not int or manifest["row_index"] != count - 1:
            raise E4RunnerError("E1 cache row index is not the sealed manifest order")
        if any(not isinstance(input_row[key], str) or not input_row[key] for key in (
            "row_id", "quartet_id", "variant_id", "input_text",
        )):
            raise E4RunnerError("E1 model input identity/text fields must be nonempty strings")
        if any(not isinstance(manifest[key], str) or not manifest[key] for key in (
            "row_id", "quartet_id", "variant_id", "quartet_split",
        )):
            raise E4RunnerError("E1 row manifest identity/split fields must be nonempty strings")
        if any(input_row.get(key) != manifest.get(key) for key in ("row_id", "quartet_id", "variant_id")):
            raise E4RunnerError("E1 row identity differs between inputs and manifest")
        quartet = str(manifest["quartet_id"])
        split = splits.get(quartet)
        if split is None or manifest["quartet_split"] != split:
            raise E4RunnerError("E1 row manifest disagrees with its sealed split manifest")
        if split != "FIT":
            continue
        variant = manifest["variant_id"]
        if variant not in VARIANTS:
            raise E4RunnerError("E1 FIT row has an unknown variant")
        group = groups.setdefault(quartet, {
            "quartet_id": quartet, "rows": [], "variants": set(), "query_ids": set(), "max_token_count": 0,
        })
        if variant in group["variants"]:
            raise E4RunnerError("E1 FIT quartet repeats a variant")
        text = input_row["input_text"]
        query_id = infer_query_template_id(text, contexts, entities)
        token_ids = tokenize(text)
        if not token_ids or len(token_ids) > 2048:
            raise E4RunnerError(f"registered tokenizer returned an invalid length for {manifest['row_id']}")
        group["variants"].add(variant)
        group["query_ids"].add(query_id)
        group["max_token_count"] = max(group["max_token_count"], len(token_ids))
        group["rows"].append({
            "row_id": input_row["row_id"], "quartet_id": quartet, "variant_id": variant,
            "input_text": text, "cache_row_index": int(manifest["row_index"]),
            "query_template_id": query_id, "token_count": len(token_ids),
        })
    if count != E1_ROWS:
        raise E4RunnerError(f"E1 ordered panel row count mismatch: {count} != {E1_ROWS}")
    result = []
    for quartet, group in groups.items():
        if group["variants"] != set(VARIANTS) or len(group["rows"]) != 4:
            raise E4RunnerError(f"E1 FIT quartet is not exactly A/C/E/P: {quartet}")
        if len(group["query_ids"]) != 1:
            raise E4RunnerError(f"E1 FIT quartet rows disagree on query template identity: {quartet}")
        group["rows"].sort(key=lambda row: VARIANTS.index(row["variant_id"]))
        group["query_template_id"] = next(iter(group["query_ids"]))
        group.pop("variants")
        group.pop("query_ids")
        result.append(group)
    return result


def select_parity_quartets(quartets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    cells: dict[tuple[int, int], list[dict[str, Any]]] = {}
    by_query: dict[int, list[dict[str, Any]]] = {query: [] for query in range(8)}
    seen_ids: set[str] = set()
    for raw in quartets:
        row = dict(raw)
        quartet_id, query_id, max_length = row.get("quartet_id"), row.get("query_template_id"), row.get("max_token_count")
        if not isinstance(quartet_id, str) or quartet_id in seen_ids or query_id not in range(8) or not isinstance(max_length, int):
            raise E4RunnerError("malformed or duplicate quartet in parity selector")
        seen_ids.add(quartet_id)
        by_query[query_id].append(row)
    for query_id, query_rows in by_query.items():
        query_rows.sort(key=lambda row: (row["max_token_count"], row["quartet_id"].encode("utf-8")))
        total = len(query_rows)
        if total < 32:
            raise E4RunnerError(f"query-template stratum {query_id} cannot fill four 8-quartet parity cells")
        for rank, row in enumerate(query_rows):
            quartile = next(k for k in range(4) if (k * total) // 4 <= rank < ((k + 1) * total) // 4)
            cells.setdefault((query_id, quartile), []).append(row)
    selected: list[dict[str, Any]] = []
    for query_id in range(8):
        for quartile in range(4):
            candidates = cells.get((query_id, quartile), [])
            if len(candidates) < 8:
                raise E4RunnerError(f"parity selector cell ({query_id},{quartile}) has fewer than eight quartets")
            ranked = sorted(candidates, key=lambda row: (
                hashlib.sha256(
                    PARITY_DOMAIN + str(query_id).encode("ascii") + b"\x00" + str(quartile).encode("ascii") +
                    b"\x00" + row["quartet_id"].encode("utf-8")
                ).digest(), row["quartet_id"].encode("utf-8"),
            ))
            selected.extend({**row, "quartile_id": quartile} for row in ranked[:8])
    if len(selected) != PARITY_QUARTETS:
        raise E4RunnerError("parity selector did not select exactly 256 whole quartets")
    selected.sort(key=lambda row: min(item["cache_row_index"] for item in row["rows"]))
    return selected
