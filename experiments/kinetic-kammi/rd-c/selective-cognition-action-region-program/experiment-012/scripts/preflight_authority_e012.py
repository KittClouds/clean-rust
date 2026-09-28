from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
RUN = ROOT / "artifacts/runs/e012-20260926-frame-decomposition-01"
AUTHORIZER = ROOT / "inputs/authority/e011-authorize.exe"


def main() -> None:
    frames = json.loads((RUN / "inputs/full-frame-lock.json").read_text(encoding="utf-8"))
    bindings = json.loads((RUN / "inputs/presentation-bindings.json").read_text(encoding="utf-8"))
    frame = frames["frames"][0]
    binding = next(row for row in bindings["bindings"] if row["sample_id"] == frame["sample_id"])
    options = [
        {
            "producer_ordinal": index,
            "action": option["action"],
            "summary": option["summary"],
            "diff_excerpt": option["diff_excerpt"],
            "patch_sha256": option["patch_sha256"],
        }
        for index, option in enumerate(frame["frame"]["action_options"])
    ]
    test_root = RUN / "preflight/authority-probe"
    test_root.mkdir(parents=True, exist_ok=True)
    input_path = test_root / "input.json"
    output_path = test_root / "result.json"
    ledger_path = test_root / "action-ledger.bin"
    if input_path.exists() or output_path.exists() or ledger_path.exists():
        raise SystemExit("refusing to replace existing authority probe artifact")
    chosen = frame["frame"]["action_options"][0]["action"]["id"]
    value = {
        "task_id": "e012-synthetic-authority-probe",
        "frame_digest_hex": binding["frame_digest_hex"],
        "request_id_hex": binding["request_id_hex"],
        "response_request_id_hex": binding["request_id_hex"],
        "request_receipt_digest_hex": binding["receipt_digest_hex"],
        "response_receipt_digest_hex": binding["receipt_digest_hex"],
        "presentation_receipt_hex": binding["receipt_hex"],
        "action_ledger_path": str(ledger_path),
        "ordered_options": options,
        "observer_output": {
            "action_choice": chosen,
            "applicability_milli": 1000,
            "abstention_milli": 0,
        },
        "thresholds": {
            "minimum_applicability_milli": 850,
            "maximum_abstention_milli": 150,
        },
        "completion_check_passed": True,
    }
    input_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    subprocess.run([str(AUTHORIZER), str(input_path), str(output_path)], check=True)
    result = json.loads(output_path.read_text(encoding="utf-8"))
    passed = (
        result["presentation_verified"]
        and result["replay_state_identical"]
        and result["illegal_commits"] == 0
        and result["duplicate_action_effects"] == 0
        and result["final_state"] == "DONE"
        and result["action_choice"] == chosen
    )
    if not passed:
        raise SystemExit(f"authority preflight failed: {result}")
    print(json.dumps({
        "state": "AUTHORITY_PREFLIGHT_PASS_NO_MODEL_CONTACT",
        "presentation_verified": result["presentation_verified"],
        "replay_state_identical": result["replay_state_identical"],
        "illegal_commits": result["illegal_commits"],
        "duplicate_action_effects": result["duplicate_action_effects"],
        "final_state": result["final_state"],
    }, indent=2))


if __name__ == "__main__":
    main()

