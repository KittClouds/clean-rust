from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011\repairs\candidate-canonicalization-v1")
RUN = ROOT / "artifacts/runs/e011-r1-20260925-candidate-canonicalization-01"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> None:
    seal_path = RUN / "postrun-output-seal.json"
    if seal_path.exists():
        raise SystemExit(f"repair output seal already exists: {seal_path}")
    preseal = json.loads((RUN / "pre-model-seal.json").read_text(encoding="utf-8"))
    if preseal.get("state") != "SEALED_BEFORE_MODEL_CONTACT":
        raise SystemExit("repair pre-model seal is missing")
    for relative, expected in preseal["code_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise RuntimeError(f"repair code changed after sealing: {relative}")
    outputs = {}
    for role in ("small", "large"):
        directory = RUN / "outputs" / role
        records = sorted(directory.glob("*.json"))
        if len(records) != 16:
            raise RuntimeError(f"{role}: expected 16 records, found {len(records)}")
        http_success = 0
        normalized = 0
        for path in records:
            record = json.loads(path.read_text(encoding="utf-8"))
            http_success += int(record.get("http_status") == 200)
            normalized += int(isinstance(record.get("normalized_output"), dict))
            if record.get("role") != role or record.get("input_adapter_id") != "candidate-canonicalization-v1":
                raise RuntimeError(f"repair output identity mismatch: {path}")
        outputs[role] = {
            "record_count": 16,
            "http_success_count": http_success,
            "normalized_output_count": normalized,
            "tree_sha256": tree_hash(directory),
        }
    result = {
        "schema_version": 1,
        "state": "OUTPUTS_SEALED_BEFORE_SCORING",
        "run_id": preseal["run_id"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "pre_model_seal_sha256": sha256((RUN / "pre-model-seal.json").read_bytes()),
        "outputs": outputs,
    }
    seal_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
