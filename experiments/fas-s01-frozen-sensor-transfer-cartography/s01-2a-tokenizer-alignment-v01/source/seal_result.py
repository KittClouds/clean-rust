from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
from typing import Any


def hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def canonical(entries: list[dict[str, Any]]) -> bytes:
    return b"".join(
        f"{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n".encode("utf-8")
        for entry in entries
    )


def validate_gates(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    report = json.loads((root / "tokenizer-alignment-report-v01.json").read_text(encoding="utf-8"))
    disposition = json.loads((root / "phase-disposition-v01.json").read_text(encoding="utf-8"))
    if report["complete"] is not True:
        raise RuntimeError("alignment report is incomplete")
    if report["corpus_sha256"] != "51a55212ba89d55bd6df532673ad4546c95def1f5d75622661f7c17b3e4a7ad1":
        raise RuntimeError("alignment report names an unexpected corpus")
    if report["protocol_bundle_root_sha256"] != "67644d4a99b9c84f312caac591e00e2a12903cea0433832868aa35dce2b5d6f9":
        raise RuntimeError("alignment report names an unexpected protocol bundle")
    if report["construction_tree_root_sha256"] != "f6065b8163799239e0d7b1200b5dda4aad169772ead14b999130a473ff9d9049":
        raise RuntimeError("alignment report names an unexpected parent construction tree")
    if report["tokenizer_repo_id"] != "LiquidAI/LFM2.5-1.2B-Base" or report["tokenizer_resolved_commit"] != "7453bca97ca1e67754c4035a4b4c584e1c9dd725":
        raise RuntimeError("alignment report names an unexpected tokenizer identity")
    if report["rendered_inputs_seen"] != 106496 or report["quartets_seen"] != 26624:
        raise RuntimeError("alignment report does not account for the complete sealed corpus")
    if report["model_instantiated"] or report["model_weights_downloaded_or_loaded"] or report["feature_extraction_performed"]:
        raise RuntimeError("alignment report violates the tokenizer-only boundary")
    alignment_path = root / "alignment-records-v01.jsonl"
    alignment_sha, alignment_bytes = hash_file(alignment_path)
    if alignment_sha != report["alignment_records_sha256"] or alignment_bytes != report["alignment_records_bytes"]:
        raise RuntimeError("alignment JSONL does not match the report hash")
    asset_path = root / "tokenizer-assets-manifest-v01.json"
    asset_sha, _ = hash_file(asset_path)
    if asset_sha != report["tokenizer_asset_manifest_sha256"]:
        raise RuntimeError("tokenizer asset manifest does not match the report hash")
    if disposition["S01_2_MODEL_CONTACT_AUTHORIZED"] is not False or disposition["S01_3_AUTHORIZED"] is not False:
        raise RuntimeError("alignment disposition exceeds its authorization")
    if disposition["S01_2_TOKEN_ALIGNMENT_READY"] != (report["status"] == "TOKENIZER_ALIGNMENT_PASS"):
        raise RuntimeError("alignment disposition disagrees with report status")
    if report["status"] not in ("TOKENIZER_ALIGNMENT_PASS", "TOKENIZER_ALIGNMENT_FAIL_CLOSED"):
        raise RuntimeError("alignment report has an unknown terminal status")
    if report["status"] == "TOKENIZER_ALIGNMENT_PASS":
        if report["rejected_input_count"] != 0 or not report["repeat_check_pass"] or not report["support_audit"]["all_cells_at_frozen_support"]:
            raise RuntimeError("pass disposition does not satisfy the frozen alignment gates")
        if any(value != "PASS" for value in report["gates"].values()):
            raise RuntimeError("pass report contains a failed gate")
    return report, disposition


def compute_entries(root: Path, seal_path: Path) -> list[dict[str, Any]]:
    relative_paths = sorted(
        (path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and path != seal_path),
        key=lambda value: value,
    )
    entries = []
    for relative in relative_paths:
        path = root.joinpath(*relative.split("/"))
        digest, size = hash_file(path)
        entries.append({"path": relative, "bytes": size, "sha256": digest})
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal or verify the S01-2A tokenizer-alignment result tree")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = args.run_root.resolve()
    seal_path = root / "seals" / "result-tree-seal-v01.json"
    report, _ = validate_gates(root)
    entries = compute_entries(root, seal_path)
    root_hash = hashlib.sha256(canonical(entries)).hexdigest()

    if args.verify_only:
        if not seal_path.is_file():
            raise SystemExit("result-tree seal is missing")
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        if seal["root_sha256"] != root_hash or seal["entries"] != entries:
            raise SystemExit("result-tree seal does not reproduce")
        print(f"verified_result_root_sha256={root_hash}")
        return 0

    if seal_path.exists():
        raise SystemExit("result-tree seal already exists; refusing to overwrite")
    tokenizer_cache = root / "tokenizer-cache"
    forbidden = [
        str(path.relative_to(root))
        for path in tokenizer_cache.rglob("*")
        if path.is_file() and any(fnmatch.fnmatchcase(path.name.lower(), pattern) for pattern in (
            "*.safetensors", "*.bin", "*.pt", "*.pth", "*.gguf", "*.onnx", "*.h5", "*.msgpack", "model*"
        ))
    ]
    if forbidden:
        raise RuntimeError(f"forbidden model artifact exists in tokenizer cache: {forbidden}")
    seal = {
        "seal_id": "FASS01_S01_2A_RESULT_TREE_SEAL_V01",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "S01-2A-v01",
        "algorithm": "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>; this seal excluded",
        "entries": entries,
        "root_sha256": root_hash,
        "corpus_sha256": report["corpus_sha256"],
        "protocol_bundle_root_sha256": report["protocol_bundle_root_sha256"],
        "construction_tree_root_sha256": report["construction_tree_root_sha256"],
        "tokenizer_loaded": True,
        "model_instantiated": False,
        "model_weights_downloaded_or_loaded": False,
        "feature_extraction_performed": False,
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    with seal_path.open("xb") as output:
        output.write(json.dumps(seal, ensure_ascii=True, indent=2).encode("utf-8") + b"\n")
        output.flush()
    print(f"sealed_result_root_sha256={root_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
