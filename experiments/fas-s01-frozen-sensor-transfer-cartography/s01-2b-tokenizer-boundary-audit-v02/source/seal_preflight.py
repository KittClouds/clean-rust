from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Seal the S01-2B read-only audit packet")
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root.resolve()
    seal_path = root / "seals" / "preflight-seal-v02.json"
    if seal_path.exists():
        raise SystemExit("preflight seal already exists; refusing to overwrite")
    inputs = [
        root / "README.md",
        root / "inputs" / "boundary-audit-contract-v02.json",
        root / "inputs" / "audit-input-binding-v02.json",
        root / "source" / "boundary_audit.py",
        root / "source" / "seal_preflight.py",
        root / "source" / "seal_result.py",
    ]
    entries = []
    for path in sorted(inputs, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if not path.is_file():
            raise SystemExit(f"missing required preflight input: {relative}")
        payload = path.read_bytes()
        entries.append({"path": relative, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    canonical = b"".join(f"{item['path']}\t{item['bytes']}\t{item['sha256']}\n".encode("utf-8") for item in entries)
    seal = {
        "seal_id": "FASS01_S01_2B_PREFLIGHT_SEAL_V02",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "S01-2B-v02",
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
