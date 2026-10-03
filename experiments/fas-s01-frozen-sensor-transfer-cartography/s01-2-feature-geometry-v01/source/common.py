from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(entries: list[dict[str, Any]]) -> bytes:
    return b"".join(
        f"{item['path']}\t{item['bytes']}\t{item['sha256']}\n".encode("utf-8")
        for item in entries
    )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def jsonl_rows(path: Path):
    with path.open("r", encoding="utf-8", newline="") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc


def tree_entries(root: Path, excluded: Path | None = None, allow_internal_symlinks: bool = False) -> list[dict[str, Any]]:
    entries = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            if not allow_internal_symlinks or not path.resolve().is_relative_to(root.resolve()):
                raise RuntimeError(f"symlink is forbidden or escapes the result identity: {path}")
        if path.is_file() and path != excluded:
            digest, size = sha256_file(path)
            entries.append({"path": path.relative_to(root).as_posix(), "bytes": size, "sha256": digest})
    return entries


def verify_sealed_tree(root: Path, seal_relative: str, expected_root: str) -> dict[str, Any]:
    seal_path = root.joinpath(*seal_relative.split("/"))
    seal = read_json(seal_path)
    if seal.get("root_sha256") != expected_root:
        raise RuntimeError(f"sealed parent identity mismatch: {root}")
    entries = tree_entries(root, excluded=seal_path, allow_internal_symlinks=True)
    if entries != seal.get("entries") or sha256_bytes(canonical(entries)) != expected_root:
        raise RuntimeError(f"sealed parent tree failed root verification: {root}")
    return seal


def verify_parent_bundle(binding: dict[str, Any], progress: bool = True) -> dict[str, Any]:
    verified = {}
    for name in ("S01_2", "S01_2A", "S01_2B", "S01_2C"):
        parent = binding["parent_roots"][name]
        verified[name] = verify_sealed_tree(Path(parent["path"]), parent["seal_path"], parent["result_tree_root_sha256"])
        if progress:
            print(f"verified_parent={name} root={parent['result_tree_root_sha256']}", flush=True)
    if verified["S01_2"].get("corpus_root_sha256") != binding["corpus_sha256"]:
        raise RuntimeError("S01-2 parent seal binds a different corpus")
    if verified["S01_2"].get("protocol_bundle_root_sha256") != binding["protocol_bundle_root_sha256"]:
        raise RuntimeError("S01-2 protocol bundle root differs")
    if verified["S01_2A"].get("corpus_sha256") != binding["corpus_sha256"]:
        raise RuntimeError("S01-2A corpus identity differs")
    if verified["S01_2B"].get("corpus_sha256") != binding["corpus_sha256"]:
        raise RuntimeError("S01-2B corpus identity differs")
    if verified["S01_2C"].get("parents", {}).get("S01_2") != binding["parent_roots"]["S01_2"]["result_tree_root_sha256"]:
        raise RuntimeError("S01-2C parent identity differs")

    a_root = Path(binding["parent_roots"]["S01_2A"]["path"])
    a_report = read_json(a_root / "tokenizer-alignment-report-v01.json")
    a_disp = read_json(a_root / "phase-disposition-v01.json")
    b_root = Path(binding["parent_roots"]["S01_2B"]["path"])
    b_report = read_json(b_root / "boundary-audit-report-v02.json")
    b_disp = read_json(b_root / "phase-disposition-v02.json")
    c_root = Path(binding["parent_roots"]["S01_2C"]["path"])
    c_report = read_json(c_root / "minimal-cover-alignment-report-v01.json")
    c_disp = read_json(c_root / "phase-disposition-v01.json")
    if a_disp.get("tokenizer_alignment_status") != "TOKENIZER_ALIGNMENT_FAIL_CLOSED" or a_report.get("repeat_check_pass") is not True:
        raise RuntimeError("historical S01-2A disposition or repeat provenance differs")
    if b_disp.get("S01_2B_BOUNDARY_AUDIT_COMPLETE") is not True or b_report.get("complete") is not True:
        raise RuntimeError("S01-2B boundary audit is not sealed complete")
    if c_disp.get("S01_2C_MINIMAL_COVER_ALIGNMENT") != "PASS" or c_disp.get("S01_2_FEATURE_EXTRACTION_ELIGIBLE") is not True:
        raise RuntimeError("S01-2C alignment is not eligible")
    if c_disp.get("S01_2_MODEL_CONTACT_AUTHORIZED") is not False or c_disp.get("S01_3_AUTHORIZED") is not False:
        raise RuntimeError("S01-2C disposition crossed its authority boundary")
    if c_report.get("alignment_assignments", {}).get("sha256") != binding["input_sha256"]["alignment_assignments"]:
        raise RuntimeError("S01-2C assignment hash differs")
    if a_report.get("tokenizer_resolved_commit") != binding["tokenizer_revision"]:
        raise RuntimeError("S01-2A tokenizer revision differs")
    return {
        "roots": {name: binding["parent_roots"][name]["result_tree_root_sha256"] for name in verified},
        "S01_2A_status": a_disp["tokenizer_alignment_status"],
        "S01_2A_repeat_check_pass": a_report["repeat_check_pass"],
        "S01_2B_complete": b_disp["S01_2B_BOUNDARY_AUDIT_COMPLETE"],
        "S01_2C_status": c_disp["S01_2C_MINIMAL_COVER_ALIGNMENT"],
        "S01_2C_feature_extraction_eligible": c_disp["S01_2_FEATURE_EXTRACTION_ELIGIBLE"],
        "S01_2C_assignments_sha256": binding["input_sha256"]["alignment_assignments"],
    }
