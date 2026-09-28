from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011")
RUN = ROOT / "artifacts/runs/e011-20260925-causal-evidence-01"
ROLES = ("small", "large")
CONDITIONS = (
    "evidence-masked",
    "evidence-swapped",
    "repository-neutralized",
    "candidate-permuted",
)


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
    output_seal_path = RUN / "postrun-output-seal.json"
    if output_seal_path.exists():
        raise SystemExit(f"output seal already exists: {output_seal_path}")
    preseal_path = RUN / "pre-model-seal.json"
    preseal = json.loads(preseal_path.read_text(encoding="utf-8"))
    if preseal.get("state") != "SEALED_BEFORE_MODEL_CONTACT":
        raise SystemExit("pre-model seal is missing")
    for relative, expected in preseal["code_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"frozen E011 code hash mismatch: {relative}")
    entries = {}
    for role in ROLES:
        entries[role] = {}
        for condition in CONDITIONS:
            directory = RUN / "outputs" / role / condition
            records = sorted(directory.glob("*.json"))
            if len(records) != 16:
                raise RuntimeError(f"{role}/{condition}: expected 16 records, found {len(records)}")
            http_success = 0
            normalized = 0
            for path in records:
                record = json.loads(path.read_text(encoding="utf-8"))
                http_success += int(record.get("http_status") == 200)
                normalized += int(isinstance(record.get("normalized_output"), dict))
                if record.get("condition") != condition or record.get("role") != role:
                    raise RuntimeError(f"record identity mismatch: {path}")
            entries[role][condition] = {
                "record_count": len(records),
                "http_success_count": http_success,
                "normalized_output_count": normalized,
                "tree_sha256": tree_hash(directory),
            }
    seal = {
        "schema_version": 1,
        "state": "OUTPUTS_SEALED_BEFORE_SCORING",
        "run_id": preseal["run_id"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "pre_model_seal_sha256": sha256(preseal_path.read_bytes()),
        "output_tree_sha256": entries,
    }
    output_seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(seal, indent=2))


if __name__ == "__main__":
    main()
