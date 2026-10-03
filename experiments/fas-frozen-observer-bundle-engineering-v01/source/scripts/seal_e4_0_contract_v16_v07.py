#!/usr/bin/env python3
"""Seal the v16-v06 successor with a complete v06-v11 sealed-ancestor inventory."""
from __future__ import annotations
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT = "experiments/fas-frozen-observer-bundle-engineering-v01"
CONTRACT_REL = f"{PROJECT}/contracts/e4-0-contract-v16-v06-final.json"
MAP_REL = f"{PROJECT}/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v16-v08.md"
PRESEAL_REL = f"{PROJECT}/audits/e4-0-track-e/track-e-preseal-receipt-v16-v08.json"
OUTPUT_REL = f"{PROJECT}/seals/e4-0-contract-v16-v06-seal.json"
EXPECTED_ROOTS = {
    "e0_v10_root_sha256": "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd",
    "e1_v04_root_sha256": "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03",
    "e2_v07_root_sha256": "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a",
    "e3_v02_bundle_root_sha256": "899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1",
}


def digest(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            size += len(chunk)
            h.update(chunk)
    return size, h.hexdigest()


def safe_path(workspace: Path, value: str) -> Path:
    if (not value or value.startswith("/") or re.match(r"^[A-Za-z]:", value)
            or "\\" in value or any(ord(char) < 32 for char in value)
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise RuntimeError(f"unsafe or noncanonical POSIX path: {value!r}")
    root = workspace.resolve(strict=True)
    target = workspace
    for part in value.split("/"):
        target = target / part
        is_junction = getattr(target, "is_junction", None)
        if target.is_symlink() or (callable(is_junction) and is_junction()):
            raise RuntimeError(f"sealed path traverses a symlink or junction: {value}")
    resolved = target.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"sealed path escapes workspace root: {value}") from exc
    if not resolved.is_file():
        raise RuntimeError(f"sealed path must be a regular file: {value}")
    return resolved
def parse_tables(path: Path) -> list[tuple[list[str], list[list[str]]]]:
    tables = []
    header = None
    rows: list[list[str]] = []

    def close() -> None:
        nonlocal header, rows
        if header is not None and rows:
            tables.append((header, rows))
        header, rows = None, []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            close()
            continue
        cells = [part.strip().strip(chr(96) + " ") for part in line.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        if header is None:
            header = cells
        elif len(cells) == len(header):
            rows.append(cells)
    close()
    return tables


def find_table(path: Path, normalized: list[str]) -> list[list[str]]:
    found = [rows for header, rows in parse_tables(path)
             if ["".join(item.lower().split()).replace("-", "") for item in header] == normalized]
    if len(found) != 1:
        raise RuntimeError(f"expected one Markdown table {normalized}, found {len(found)}")
    return found[0]


def add_member(workspace: Path, by_path: dict[str, dict[str, Any]], by_identity: set[str], artifact_id: str,
               rel: str, expected_bytes: int, expected_sha: str) -> None:
    target = safe_path(workspace, rel)
    size, actual = digest(target)
    if size != expected_bytes or actual != expected_sha:
        raise RuntimeError(f"workspace member does not match bound identity: {rel}")
    identity = unicodedata.normalize("NFC", str(target.resolve(strict=True))).casefold()
    if identity in by_identity:
        raise RuntimeError(f"duplicate seal member resolved path: {rel}")
    if rel in by_path:
        raise RuntimeError(f"duplicate seal member path: {rel}")
    by_path[rel] = {"artifact_id": artifact_id, "path": rel, "bytes": size, "sha256": actual}
    by_identity.add(identity)


def add_input_member_once(
    workspace: Path,
    by_path: dict[str, dict[str, Any]],
    by_identity: set[str],
    artifact_id: str,
    rel: str,
    expected_bytes: int,
    expected_sha: str,
) -> None:
    """Do not duplicate a path already sealed as source; verify exact identity first."""
    target = safe_path(workspace, rel)
    size, actual = digest(target)
    if size != expected_bytes or actual != expected_sha:
        raise RuntimeError(f"workspace input does not match bound identity: {rel}")
    identity = unicodedata.normalize("NFC", str(target.resolve(strict=True))).casefold()
    if identity in by_identity:
        existing = by_path.get(rel)
        if existing is None or existing.get("bytes") != size or existing.get("sha256") != actual:
            raise RuntimeError(f"duplicate input path aliases another seal member: {rel}")
        return
    add_member(workspace, by_path, by_identity, artifact_id, rel, expected_bytes, expected_sha)


def derive_sealed_ancestor_closure(workspace: Path) -> list[dict[str, Any]]:
    """Follow sealed supersession links from v11 to the frozen v06 baseline."""
    current_version = 11
    successor_versions = {11: 10, 10: 8, 8: 7, 7: 6}
    contract_ids = {
        6: "E4_0_CONTRACT_V06_SCIENTIFIC_BASELINE",
        7: "E4_0_CONTRACT_V07_SUPERSEDED",
        8: "E4_0_CONTRACT_V08_SUPERSEDED",
        10: "E4_0_CONTRACT_V10_SUPERSEDED",
        11: "E4_0_CONTRACT_V11_SUPERSEDED",
    }
    seal_ids = {
        6: "E4_0_CONTRACT_V06_BASELINE_SEAL",
        7: "E4_0_CONTRACT_V07_SEAL_SUPERSEDED",
        8: "E4_0_CONTRACT_V08_SEAL_SUPERSEDED",
        10: "E4_0_CONTRACT_V10_SEAL_SUPERSEDED",
        11: "E4_0_CONTRACT_V11_SEAL_SUPERSEDED",
    }
    reverse_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen_versions: set[int] = set()
    while True:
        if current_version in seen_versions or current_version not in contract_ids:
            raise RuntimeError("sealed predecessor chain is cyclic or contains an unregistered version")
        seen_versions.add(current_version)
        contract_rel = f"{PROJECT}/contracts/e4-0-contract-v{current_version:02d}-final.json"
        seal_rel = f"{PROJECT}/seals/e4-0-contract-v{current_version:02d}-seal.json"
        contract_path = safe_path(workspace, contract_rel)
        seal_path = safe_path(workspace, seal_rel)
        contract_size, contract_sha = digest(contract_path)
        seal_size, seal_sha = digest(seal_path)
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        if (contract.get("contract_id") != f"FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V{current_version:02d}"
                or contract.get("status") != "SEALED"
                or seal.get("seal_id") != f"FAS_E4_0_CONTRACT_V{current_version:02d}_SEAL"
                or seal.get("status") != "SEALED"):
            raise RuntimeError(f"v{current_version:02d} ancestor contract/seal identity is not sealed")
        matching = [row for row in seal.get("entries", [])
                    if row.get("artifact_id") == f"E4_0_CONTRACT_V{current_version:02d}_FINAL"]
        if (len(matching) != 1 or matching[0].get("path") != contract_rel
                or matching[0].get("bytes") != contract_size or matching[0].get("sha256") != contract_sha):
            raise RuntimeError(f"v{current_version:02d} seal does not bind its exact contract")
        reverse_pairs.append((
            {"artifact_id": contract_ids[current_version], "path": contract_rel,
             "bytes": contract_size, "sha256": contract_sha},
            {"artifact_id": seal_ids[current_version], "path": seal_rel,
             "bytes": seal_size, "sha256": seal_sha},
        ))
        if current_version == 6:
            break
        predecessor_version = successor_versions.get(current_version)
        supersedes = contract.get("supersedes", {})
        prior_contract = supersedes.get("contract", {})
        prior_seal = supersedes.get("seal", {})
        expected_contract_rel = f"{PROJECT}/contracts/e4-0-contract-v{predecessor_version:02d}-final.json"
        expected_seal_rel = f"{PROJECT}/seals/e4-0-contract-v{predecessor_version:02d}-seal.json"
        if (predecessor_version is None or prior_contract.get("contract_id") !=
                f"FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V{predecessor_version:02d}"
                or prior_contract.get("path") != expected_contract_rel
                or prior_seal.get("seal_id") != f"FAS_E4_0_CONTRACT_V{predecessor_version:02d}_SEAL"
                or prior_seal.get("path") != expected_seal_rel
                or prior_seal.get("contract_member_artifact_id") != f"E4_0_CONTRACT_V{predecessor_version:02d}_FINAL"):
            raise RuntimeError(f"v{current_version:02d} supersedes metadata breaks the sealed ancestor chain")
        prior_contract_path = safe_path(workspace, expected_contract_rel)
        prior_seal_path = safe_path(workspace, expected_seal_rel)
        prior_contract_size, prior_contract_sha = digest(prior_contract_path)
        prior_seal_size, prior_seal_sha = digest(prior_seal_path)
        if (prior_contract.get("bytes") != prior_contract_size or prior_contract.get("sha256") != prior_contract_sha
                or prior_seal.get("manifest_bytes") != prior_seal_size
                or prior_seal.get("manifest_sha256") != prior_seal_sha
                or prior_seal.get("root_sha256") != json.loads(prior_seal_path.read_text(encoding="utf-8")).get("root_sha256")):
            raise RuntimeError(f"v{current_version:02d} supersedes metadata does not match exact predecessor bytes")
        current_version = predecessor_version
    if seen_versions != {6, 7, 8, 10, 11}:
        raise RuntimeError(f"sealed ancestor closure differs from expected v06-v11 chain: {sorted(seen_versions)}")
    return [row for pair in reversed(reverse_pairs) for row in pair]
    by_identity.add(identity)


def safe_output_path(workspace: Path, rel: str) -> Path:
    if (not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel)
            or "\\" in rel or any(ord(char) < 32 for char in rel)
            or any(part in ("", ".", "..") for part in rel.split("/"))):
        raise RuntimeError(f"unsafe output path: {rel!r}")
    root = workspace.resolve(strict=True)
    target = workspace
    parts = rel.split("/")
    for part in parts[:-1]:
        target = target / part
        is_junction = getattr(target, "is_junction", None)
        if target.is_symlink() or (callable(is_junction) and is_junction()):
            raise RuntimeError(f"seal output traverses a symlink or junction: {target}")
    parent = target.resolve(strict=True)
    try:
        parent.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"seal output parent escapes workspace: {rel}") from exc
    output = target / parts[-1]
    if output.exists() or output.is_symlink():
        raise RuntimeError(f"refusing existing contract seal output: {output}")
    return output


def main() -> int:
    workspace = Path(__file__).resolve().parents[4]
    output = safe_output_path(workspace, OUTPUT_REL)
    contract_path = workspace / CONTRACT_REL
    map_path = workspace / MAP_REL
    preseal_path = workspace / PRESEAL_REL
    contract_size, contract_sha = digest(contract_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    map_size, map_sha = digest(map_path)
    preseal_size, preseal_sha = digest(preseal_path)
    preseal = json.loads(preseal_path.read_text(encoding="utf-8"))
    if contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V16" or contract.get("status") != "SEALED":
        raise RuntimeError("final contract identity/status mismatch")
    if contract.get("design_inputs", {}).get("implementation_source_map_v16_sha256") != map_sha:
        raise RuntimeError("final contract does not bind this exact v16 source map")
    if preseal.get("status") != "E4_0_TRACK_E_PRESEAL_PASS_V16_V08_CONTRACT_AND_SOURCE_MAP_CLOSED" or preseal.get("pass") is not True:
        raise RuntimeError("Track E preseal audit did not pass")
    if preseal.get("contract", {}).get("sha256") != contract_sha or preseal.get("source_map", {}).get("sha256") != map_sha:
        raise RuntimeError("Track E preseal receipt binds different contract or source map bytes")
    if not contract.get("predecessors"):
        raise RuntimeError("final contract predecessor roots are missing")
    if any(contract["predecessors"].get(key) != value for key, value in EXPECTED_ROOTS.items()):
        raise RuntimeError("final contract historical predecessor roots differ from the frozen values")
    by_path: dict[str, dict[str, Any]] = {}
    by_identity: set[str] = set()
    add_member(workspace, by_path, by_identity, "E4_0_CONTRACT_V16_V06_FINAL", CONTRACT_REL, contract_size, contract_sha)
    add_member(workspace, by_path, by_identity, "E4_0_SOURCE_MAP_V16_V08", MAP_REL, map_size, map_sha)
    add_member(workspace, by_path, by_identity, "E4_0_TRACK_E_PRESEAL_RECEIPT_V16_V08", PRESEAL_REL, preseal_size, preseal_sha)
    supersedes = contract.get("supersedes", {})
    prior_contract = supersedes.get("contract", {})
    prior_seal = supersedes.get("seal", {})
    if prior_contract != {
        "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V11",
        "path": f"{PROJECT}/contracts/e4-0-contract-v11-final.json",
        "bytes": 72068,
        "sha256": "9cefc7cf9ca8f367bceff3c1c9b7e84ab3e15f684326edf94354e33e3d1fb2fd",
    } or prior_seal != {
        "seal_id": "FAS_E4_0_CONTRACT_V11_SEAL",
        "path": f"{PROJECT}/seals/e4-0-contract-v11-seal.json",
        "manifest_bytes": 90814,
        "manifest_sha256": "7f27371f3cb886208ff67ea7a19e2ca51577bfbc74e4f6611ca496ab9c13ebcd",
        "root_sha256": "dc7ec0731a6f637bd8aa6416bd74aba8e074e8bf0c936a1bda830e79c0afa6c3",
        "contract_member_artifact_id": "E4_0_CONTRACT_V11_FINAL",
    }:
        raise RuntimeError("v16 contract supersedes metadata differs from immutable v11 lineage")

    transitive = contract.get("engineering_amendment", {}).get("prior_v12_lineage", {}).get("transitive_seal_members")
    expected_closure = derive_sealed_ancestor_closure(workspace)
    if transitive != expected_closure:
        raise RuntimeError("v16 amendment does not bind the derived complete v06-v11 sealed-ancestor closure")
    for row in transitive:
        add_member(workspace, by_path, by_identity, row["artifact_id"], row["path"], row["bytes"], row["sha256"])

    baseline_contract = contract.get("engineering_amendment", {}).get("prior_v12_lineage", {}).get("scientific_baseline", {})
    if (baseline_contract.get("contract_id") != "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06"
            or baseline_contract.get("contract_sha256") != "ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958"
            or baseline_contract.get("seal_root_sha256") != "7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64"):
        raise RuntimeError("v16 engineering amendment does not preserve exact v06 science baseline")

    source_rows = find_table(map_path, ["path", "bytes", "sha256", "role"])
    for rel, size_text, sha, _role in source_rows:
        add_member(workspace, by_path, by_identity, "workspace-source/" + rel, rel, int(size_text), sha)

    input_rows = find_table(map_path, ["inputpath", "bytes", "sha256", "role"])
    for rel, size_text, sha, _role in input_rows:
        if Path(rel).is_absolute():
            continue
        if rel in {
            f"{PROJECT}/contracts/e4-0-contract-v06-final.json",
            f"{PROJECT}/seals/e4-0-contract-v06-seal.json",
            f"{PROJECT}/contracts/e4-0-contract-v07-final.json",
            f"{PROJECT}/seals/e4-0-contract-v07-seal.json",
            f"{PROJECT}/contracts/e4-0-contract-v08-final.json",
            f"{PROJECT}/seals/e4-0-contract-v08-seal.json",
            f"{PROJECT}/contracts/e4-0-contract-v10-final.json",
            f"{PROJECT}/seals/e4-0-contract-v10-seal.json",
            f"{PROJECT}/contracts/e4-0-contract-v11-final.json",
            f"{PROJECT}/seals/e4-0-contract-v11-seal.json",
        }:
            # These immutable lineage files have dedicated artifact IDs above.
            continue
        add_input_member_once(workspace, by_path, by_identity, "workspace-input/" + rel, rel, int(size_text), sha)

    receipt_rows = find_table(map_path, ["track", "path", "bytes", "sha256", "status"])
    for _track, rel, size_text, sha, _status in receipt_rows:
        add_member(workspace, by_path, by_identity, "workspace-receipt/" + rel, rel, int(size_text), sha)

    entries = sorted(by_path.values(), key=lambda item: item["artifact_id"].encode("utf-8"))
    if len({item["artifact_id"] for item in entries}) != len(entries):
        raise RuntimeError("artifact IDs are not unique")
    root_builder = hashlib.sha256()
    for entry in entries:
        root_builder.update(
            f"{entry['artifact_id']}\t{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n".encode("utf-8")
        )
    manifest = {
        "schema": "FAS_E4_0_ARTIFACT_SEAL_V01",
        "status": "SEALED",
        "seal_id": "FAS_E4_0_CONTRACT_V16_V06_SEAL",
        "stage": "E4_0_CONTRACT",
        "path_root_kind": "WORKSPACE_ROOT",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "contract_sha256": contract_sha,
        "contract_seal_root_sha256": None,
        "exact_predecessor_roots": EXPECTED_ROOTS,
        "entries": entries,
        "entry_count": len(entries),
        "root_sha256": root_builder.hexdigest(),
    }
    encoded = (json.dumps(manifest, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": "E4_0_CONTRACT_V16_V06_SEALED", "path": OUTPUT_REL,
                      "manifest_bytes": len(encoded), "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
                      "root_sha256": manifest["root_sha256"], "entry_count": len(entries)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

