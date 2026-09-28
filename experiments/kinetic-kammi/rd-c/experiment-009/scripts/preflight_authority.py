from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
OUT = ROOT / "artifacts" / "preflight-final-v2"
OUT.mkdir(parents=True, exist_ok=False)
frame_lock = json.loads((ROOT / "tasks" / "frames" / "frame-lock.json").read_text(encoding="utf-8"))
locked = frame_lock["frames"][0]
frame = locked["frame"]
choice = next(item for item in frame["action_options"] if item["action"]["id"] == 23)
input_data = {
    "task_id": "preflight-authority-replay",
    "frame_hash_hex": locked["blake3"],
    "selected_patch_sha256": choice["patch_sha256"],
    "action_ledger_path": str(OUT / "actions.bin"),
    "actions": [item["action"] for item in frame["action_options"]],
    "observer_output": {
        "action_choice": 23,
        "applicability_milli": 800,
        "abstention_milli": 200,
    },
    "thresholds": {
        "minimum_applicability_milli": 700,
        "maximum_abstention_milli": 600,
    },
    "completion_check_passed": True,
}
input_path = OUT / "input.json"
result_path = OUT / "receipt.json"
input_path.write_text(json.dumps(input_data, indent=2) + "\n", encoding="utf-8")
environment = os.environ.copy()
environment["CARGO_TARGET_DIR"] = r"D:\cargo-targets\rdc-e009"
subprocess.run(
    [
        "cargo", "run", "--quiet", "--manifest-path", str(ROOT / "Cargo.toml"),
        "--bin", "e009-authorize", "--", str(input_path), str(result_path),
    ],
    cwd=ROOT,
    env=environment,
    check=True,
)
result = json.loads(result_path.read_text(encoding="utf-8"))
assert result["final_state"] == "DONE"
assert result["illegal_commits"] == 0
assert result["replay_state_identical"] is True
assert result["unique_action_effects"] == 1
assert result["duplicate_action_effects"] == 0
assert result["idempotent_action_reuse"] is True
print(json.dumps({key: result[key] for key in (
    "final_state", "illegal_commits", "replay_identity", "replay_state_identical",
    "unique_action_effects", "duplicate_action_effects", "idempotent_action_reuse",
)}, indent=2))
