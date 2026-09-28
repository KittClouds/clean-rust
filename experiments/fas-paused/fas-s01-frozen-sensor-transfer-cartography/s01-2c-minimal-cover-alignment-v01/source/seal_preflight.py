from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(entries: list[dict[str, Any]]) -> bytes:
    return b"".join(
        f"{item['path']}\t{item['bytes']}\t{item['sha256']}\n".encode("utf-8")
        for item in entries
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal the S01-2C pre-model-contact packet")
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root.resolve()
    seal_path = root / "seals" / "preflight-seal-v01.json"
    if seal_path.exists():
        raise SystemExit("preflight seal already exists; refusing to overwrite")

    contract_path = root / "inputs" / "minimal-cover-alignment-contract-v01.json"
    binding_path = root / "inputs" / "alignment-input-binding-v01.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    if contract.get("contract_id") != "FASS01_S01_2C_MINIMAL_COVER_ALIGNMENT_V01":
        raise SystemExit("unexpected S01-2C contract identity")
    contract_sha = sha256_bytes(contract_path.read_bytes())
    if binding.get("S01_2C_contract_sha256") != contract_sha:
        raise SystemExit("input binding does not name the frozen contract hash")
    if binding.get("phase_id") != "S01-2C-v01" or binding.get("project_id") != "fas-s01-frozen-sensor-transfer-cartography":
        raise SystemExit("input binding identity mismatch")
    if binding.get("tokenizer_loaded_during_S01_2C") is not False or binding.get("model_loaded_during_S01_2C") is not False:
        raise SystemExit("preflight packet exceeds the authorized model-contact boundary")

    required = [
        root / "README.md",
        contract_path,
        binding_path,
        root / "inputs" / "contracts" / "feature-extraction-contract-v01.json",
        root / "inputs" / "contracts" / "geometry-analysis-contract-v01.json",
        root / "inputs" / "contracts" / "boundary-audit-contract-v02.json",
        root / "source" / "align_minimal_cover.py",
        root / "source" / "seal_preflight.py",
        root / "source" / "seal_result.py",
    ]
    entries = []
    for path in sorted(required, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if not path.is_file():
            raise SystemExit(f"missing required preflight input: {relative}")
        payload = path.read_bytes()
        entries.append({"path": relative, "bytes": len(payload), "sha256": sha256_bytes(payload)})

    for rel, expected in binding["copied_contract_hashes"].items():
        path = root.joinpath(*rel.split("/"))
        if not path.is_file() or sha256_bytes(path.read_bytes()) != expected:
            raise SystemExit(f"copied frozen contract hash mismatch: {rel}")

    seal = {
        "seal_id": "FASS01_S01_2C_PREFLIGHT_SEAL_V01",
        "project_id": binding["project_id"],
        "phase_id": binding["phase_id"],
        "algorithm": "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>",
        "entries": entries,
        "root_sha256": hashlib.sha256(canonical(entries)).hexdigest(),
        "S01_2C_contract_sha256": contract_sha,
        "parents": binding["parent_roots"],
        "tokenizer_loaded": False,
        "model_loaded": False,
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    with seal_path.open("xb") as output:
        output.write(json.dumps(seal, ensure_ascii=True, indent=2).encode("utf-8") + b"\n")
        output.flush()
    print(f"preflight_root_sha256={seal['root_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
