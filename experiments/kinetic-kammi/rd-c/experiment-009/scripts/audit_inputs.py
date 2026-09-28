from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
locked = json.loads((ROOT / "tasks" / "frames" / "frame-lock.json").read_text(encoding="utf-8"))
labels = json.loads((ROOT / "sealed" / "labels.json").read_text(encoding="utf-8"))["tasks"]
forbidden = ("gold patch", "mutant patch", "expected_task_completion", "correct action is", "label ledger")
positions = []
records = []
for item in locked["frames"]:
    frame = item["frame"]
    public_text = " ".join(
        [frame["task_prompt"]]
        + [entry["content"] for entry in frame["evidence"]]
        + [option["summary"] + " " + option["diff_excerpt"] for option in frame["action_options"]]
    ).lower()
    if any(marker in public_text for marker in forbidden):
        raise SystemExit(f"explicit label marker leaked into frame {frame['task_id']}")
    passing = {
        int(action_id)
        for action_id, outcome in labels[frame["task_id"]]["actions"].items()
        if outcome["expected_task_completion"]
    }
    if len(passing) != 1:
        raise SystemExit(f"task {frame['task_id']} does not have exactly one passing action")
    position = next(
        index for index, option in enumerate(frame["action_options"])
        if option["action"]["id"] in passing
    )
    positions.append(position)
    records.append({"task_id": frame["task_id"], "public_frame_blake3": item["blake3"], "passing_action_position": position})
if len(set(positions)) < 2:
    raise SystemExit("passing action position is constant across the bank")
result = {
    "schema_version": 1,
    "label_file_sha256": hashlib.sha256((ROOT / "sealed" / "labels.json").read_bytes()).hexdigest(),
    "public_frame_label_marker_scan": "pass",
    "passing_action_position_varies": True,
    "tasks": records,
}
path = ROOT / "sealed" / "input-audit.json"
path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(f"input audit passed for {len(records)} heldout task frames")
