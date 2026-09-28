from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
RUN_ID = "e012-20260926-frame-decomposition-01"
RUN = ROOT / "artifacts/runs" / RUN_ID


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    lock_path = RUN / "frozen-input-lock.json"
    seal_path = RUN / "pre-model-seal.json"
    lock = read_json(lock_path)
    seal = read_json(seal_path)
    lock_hash = sha256(lock_path.read_bytes())
    if lock.get("state") != "FROZEN_BEFORE_MODEL_CONTACT" or lock.get("run_id") != RUN_ID:
        raise SystemExit("E012 frozen lock is invalid")
    if seal.get("state") != "SEALED_BEFORE_MODEL_CONTACT" or seal.get("frozen_input_lock_sha256") != lock_hash:
        raise SystemExit("E012 pre-model seal does not bind the frozen lock")

    dry_runs = {}
    for role in ("small", "large"):
        path = RUN / f"preflight/request-dry-run-{role}.json"
        record = read_json(path)
        if (
            record.get("state") != "DRY_RUN_NO_MODEL_CONTACT"
            or record.get("run_id") != RUN_ID
            or record.get("role") != role
            or record.get("frame_count") != 48
            or record.get("all_presentation_bindings_match") is not True
            or record.get("frozen_input_lock_sha256") != lock_hash
            or len(record.get("requests", [])) != 48
            or any(row.get("presentation_binding_matches") is not True for row in record["requests"])
        ):
            raise SystemExit(f"{role} dry-run contract check failed")
        dry_runs[role] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256(path.read_bytes()),
            "request_count": len(record["requests"]),
            "total_request_bytes": sum(int(row["request_bytes"]) for row in record["requests"]),
        }
    for role in ("small", "large"):
        output_dir = RUN / "outputs" / role
        if output_dir.exists() and any(output_dir.iterdir()):
            raise SystemExit("model output exists before the contact gate was sealed")

    gate = {
        "schema_version": 1,
        "state": "MODEL_CONTACT_GATE_PASS",
        "run_id": RUN_ID,
        "model_contact_authorized": True,
        "frozen_input_lock_sha256": lock_hash,
        "dry_runs": dry_runs,
        "model_requests_started": False,
    }
    target = RUN / "preflight/model-contact-gate.json"
    if target.exists():
        raise SystemExit("refusing to replace the model-contact gate")
    target.write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(gate, indent=2))


if __name__ == "__main__":
    main()

