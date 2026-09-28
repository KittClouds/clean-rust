from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011\repairs\candidate-canonicalization-v1")
PARENT_RUN = Path(r"C:\rd-c\experiment-011\artifacts\runs\e011-20260925-causal-evidence-01")
RUN = ROOT / "artifacts/runs/e011-r1-20260925-candidate-canonicalization-01"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    seal_path = RUN / "pre-model-seal.json"
    if seal_path.exists():
        raise SystemExit(f"repair pre-model seal already exists: {seal_path}")
    lock_path = RUN / "pre-model-input-lock.json"
    lock = read_json(lock_path)
    if lock.get("state") != "FROZEN_BEFORE_MODEL_CONTACT":
        raise SystemExit("repair input lock is not frozen")
    if any((RUN / role / "server-process.json").exists() for role in ("small", "large")):
        raise SystemExit("an observer server was started before the repair seal")
    if (RUN / "outputs").exists():
        raise SystemExit("observer outputs exist before the repair seal")
    parent_hashes = lock["parent_e011_hashes"]
    parent_paths = {
        "e011_pre_model_seal_sha256": PARENT_RUN / "pre-model-seal.json",
        "e011_postrun_output_seal_sha256": PARENT_RUN / "postrun-output-seal.json",
        "e011_score_sha256": PARENT_RUN / "score-e011.json",
        "e011_episode_autopsy_sha256": PARENT_RUN / "episode-autopsy-e011.json",
        "parent_candidate_frame_lock_sha256": PARENT_RUN / "frame-lock-candidate-permuted.json",
    }
    for key, path in parent_paths.items():
        if sha256(path.read_bytes()) != parent_hashes[key]:
            raise RuntimeError(f"parent E011 artifact changed: {path}")
    for relative, expected in lock["sha256"]["input_files"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise RuntimeError(f"repair input changed: {relative}")
    frame_path = RUN / "canonical-frame-lock.json"
    if sha256(frame_path.read_bytes()) != lock["sha256"]["canonical_frame_lock"]:
        raise RuntimeError("canonical frame lock changed after preparation")
    entries = read_json(frame_path)["frames"]
    if len(entries) != 16:
        raise RuntimeError("canonical frame count is not 16")
    for entry in entries:
        for key in ("receipt_full_frame", "receipt_candidate_permuted"):
            receipt = entry[key]
            ids = [row["canonical_action_id"] for row in receipt]
            patches = [row["patch_sha256"] for row in receipt]
            if ids != list(range(1, len(ids) + 1)) or len(patches) != len(set(patches)):
                raise RuntimeError(f"invalid canonical receipt: {entry['task_id']}/{key}")
            frame_patches = {
                option["patch_sha256"]: option["action"]["id"]
                for option in entry["frame"]["action_options"]
            }
            if any(frame_patches.get(row["patch_sha256"]) != row["canonical_action_id"] for row in receipt):
                raise RuntimeError(f"receipt does not map the canonical frame: {entry['task_id']}/{key}")

    code_paths = (
        ROOT / "spec.md",
        ROOT / "scripts/prepare_repair.py",
        ROOT / "scripts/seal_repair_inputs.py",
        ROOT / "scripts/run_repair_observer.py",
        ROOT / "scripts/seal_repair_outputs.py",
        ROOT / "scripts/score_repair.py",
        ROOT / "scripts/start_repair_observer.ps1",
        ROOT / "scripts/stop_repair_observer.ps1",
        ROOT / "adapter/Cargo.toml",
        ROOT / "adapter/Cargo.lock",
        ROOT / "adapter/src/lib.rs",
        ROOT / "adapter/src/main.rs",
        ROOT / "rdc-candidate-canonicalizer.exe",
    )
    code_hashes = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()) for path in code_paths}
    seal = {
        "schema_version": 1,
        "state": "SEALED_BEFORE_MODEL_CONTACT",
        "run_id": lock["run_id"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input_lock_sha256": sha256(lock_path.read_bytes()),
        "code_sha256": code_hashes,
        "canonical_frame_lock_sha256": sha256(frame_path.read_bytes()),
        "model_contact_started": False,
        "authority_mode": "shadow-only",
    }
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": seal["state"], "seal_sha256": sha256(seal_path.read_bytes()), "frames": len(entries)}, indent=2))


if __name__ == "__main__":
    main()
