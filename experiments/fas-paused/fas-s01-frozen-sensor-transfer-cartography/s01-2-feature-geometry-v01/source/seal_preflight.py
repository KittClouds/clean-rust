from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common import sha256_file
from run_geometry import validate_corpus_support


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(entries: list[dict[str, Any]]) -> bytes:
    return b"".join(f"{v['path']}\t{v['bytes']}\t{v['sha256']}\n".encode("utf-8") for v in entries)


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze S01-2 extraction and geometry execution packet")
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root.resolve()
    seal_path = root / "seals" / "preflight-seal-v01.json"
    if seal_path.exists():
        raise SystemExit("preflight seal already exists; refusing to overwrite")

    binding = json.loads((root / "inputs" / "input-binding-v01.json").read_text(encoding="utf-8"))
    contracts = {
        "inputs/extraction-execution-contract-v01.json": binding["contract_sha256"]["extraction"],
        "inputs/geometry-implementation-contract-v01.json": binding["contract_sha256"]["geometry_implementation"],
        "inputs/authorization-packet-v01.json": binding["contract_sha256"]["authorization_packet"],
        "inputs/contracts/feature-extraction-contract-v01.json": binding["contract_sha256"]["feature"],
        "inputs/contracts/geometry-analysis-contract-v01.json": binding["contract_sha256"]["geometry"],
        "inputs/contracts/minimal-cover-alignment-contract-v01.json": binding["contract_sha256"]["S01_2C"],
    }
    for relative, expected in contracts.items():
        path = root.joinpath(*relative.split("/"))
        if not path.is_file() or digest(path.read_bytes()) != expected:
            raise SystemExit(f"frozen contract hash mismatch: {relative}")
    if binding.get("project_id") != "fas-s01-frozen-sensor-transfer-cartography" or binding.get("phase_id") != "S01-2-feature-geometry-v01":
        raise SystemExit("execution input identity mismatch")
    if binding.get("model_id") != "LiquidAI/LFM2.5-1.2B-Base" or binding.get("model_revision") != "7453bca97ca1e67754c4035a4b4c584e1c9dd725":
        raise SystemExit("execution model identity mismatch")
    if binding.get("S01_3_AUTHORIZED") is not False:
        raise SystemExit("preflight packet authorizes a forbidden follow-on")
    for key in ("corpus", "alignment_records", "alignment_assignments"):
        path = Path(binding["inputs"][key])
        actual_hash, _ = sha256_file(path)
        if actual_hash != binding["input_sha256"][key]:
            raise SystemExit(f"sealed input changed before preflight: {key}")
    corpus_support = validate_corpus_support(Path(binding["inputs"]["corpus"]))

    required = [
        root / "README.md",
        root / "inputs" / "input-binding-v01.json",
        root / "inputs" / "extraction-execution-contract-v01.json",
        root / "inputs" / "geometry-implementation-contract-v01.json",
        root / "inputs" / "authorization-packet-v01.json",
        root / "inputs" / "contracts" / "feature-extraction-contract-v01.json",
        root / "inputs" / "contracts" / "geometry-analysis-contract-v01.json",
        root / "inputs" / "contracts" / "minimal-cover-alignment-contract-v01.json",
        root / "source" / "common.py",
        root / "source" / "prepare_model.py",
        root / "source" / "run_extraction.py",
        root / "source" / "seal_feature_cache.py",
        root / "source" / "run_geometry.py",
        root / "source" / "test_preflight.py",
        root / "source" / "seal_result.py",
        root / "source" / "seal_preflight.py",
    ]
    entries = []
    for path in sorted(required, key=lambda value: value.relative_to(root).as_posix()):
        if not path.is_file():
            raise SystemExit(f"missing preflight file: {path.relative_to(root).as_posix()}")
        payload = path.read_bytes()
        entries.append({"path": path.relative_to(root).as_posix(), "bytes": len(payload), "sha256": digest(payload)})
    seal = {
        "seal_id": "FASS01_S01_2_EXTRACTION_GEOMETRY_PREFLIGHT_V01",
        "project_id": binding["project_id"],
        "phase_id": binding["phase_id"],
        "algorithm": "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>",
        "entries": entries,
        "root_sha256": hashlib.sha256(canonical(entries)).hexdigest(),
        "contracts": binding["contract_sha256"],
        "parents": {key: item["result_tree_root_sha256"] for key, item in binding["parent_roots"].items()},
        "corpus_support_preflight": corpus_support,
        "model_loaded": False,
        "feature_extraction_performed": False,
        "geometry_analysis_performed": False,
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    with seal_path.open("xb") as target:
        target.write(json.dumps(seal, ensure_ascii=True, indent=2).encode("utf-8") + b"\n")
        target.flush()
    print(f"preflight_root_sha256={seal['root_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
