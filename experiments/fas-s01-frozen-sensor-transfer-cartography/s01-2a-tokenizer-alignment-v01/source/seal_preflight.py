from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal the S01-2A tokenizer-only execution packet")
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root.resolve()
    seal_path = root / "seals" / "preflight-seal-v01.json"
    if seal_path.exists():
        raise SystemExit("preflight seal already exists; refusing to overwrite")
    inputs = [
        root / "README.md",
        root / "inputs" / "parent-construction-binding-v01.json",
        root / "inputs" / "tokenizer-alignment-execution-contract-v01.json",
        root / "source" / "align_tokenizer.py",
        root / "source" / "seal_result.py",
        root / "source" / "seal_preflight.py",
    ]
    entries = []
    for path in sorted(inputs, key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if not path.is_file():
            raise SystemExit(f"missing required preflight input: {relative}")
        payload = path.read_bytes()
        entries.append({"path": relative, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    canonical = b"".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n".encode("utf-8") for row in entries)
    seal = {
        "seal_id": "FASS01_S01_2A_PREFLIGHT_SEAL_V01",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "S01-2A-v01",
        "algorithm": "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>",
        "entries": entries,
        "root_sha256": hashlib.sha256(canonical).hexdigest(),
        "tokenizer_loaded": False,
        "model_loaded": False,
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    with seal_path.open("xb") as output:
        output.write(json.dumps(seal, ensure_ascii=True, indent=2).encode("utf-8") + b"\n")
        output.flush()
    print(seal["root_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
