from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
RUN = ROOT / "artifacts" / "runs" / "e009-20260925-pilot-01"
lock = json.loads((RUN / "frozen-input-lock.json").read_text(encoding="utf-8"))
source_root = RUN / "protocol-source"
source_files = [
    ROOT / "Cargo.toml",
    ROOT / "Cargo.lock",
    ROOT / "README.md",
    ROOT / "SPEC.md",
    ROOT / "E008_CLOSEOUT.md",
    ROOT / "prompts" / "system-observer-v1.txt",
    ROOT / "schemas" / "observer-output.v1.json",
    ROOT / "models" / "bundle-input.json",
    ROOT / "models" / "bundle-lock.json",
    ROOT / "models" / "artifact-paths.json",
    ROOT / "tasks" / "frames" / "frame-lock.json",
    ROOT / "tasks" / "frames" / "candidate-lock.json",
    ROOT / "sealed" / "labels.json",
    ROOT / "sealed" / "input-audit.json",
]
source_files.extend((ROOT / "src").rglob("*.rs"))
source_files.extend((ROOT / "scripts").glob("*"))

for source in source_files:
    if not source.is_file():
        continue
    relative = source.relative_to(ROOT)
    destination = source_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)

lock_copy = RUN / "frozen-input-lock.json"
copied_spec = source_root / "SPEC.md"
if hashlib.sha256(copied_spec.read_bytes()).hexdigest() != lock["sha256"]["spec"]:
    raise SystemExit("archived SPEC.md does not match the frozen input lock")
copied_runner = source_root / "scripts" / "run_observer.py"
if hashlib.sha256(copied_runner.read_bytes()).hexdigest() != lock["sha256"]["observer_runner"]:
    raise SystemExit("archived observer runner does not match the frozen input lock")

calls = []
for path in sorted((RUN / "shadow-small").glob("*.json")):
    record = json.loads(path.read_text(encoding="utf-8"))
    calls.append(
        {
            "task_id": record["task_id"],
            "http_status": record.get("http_status"),
            "finish_reason": record.get("response", {}).get("choices", [{}])[0].get("finish_reason"),
            "content_present": bool(record.get("content")),
            "completion_tokens": record.get("usage", {}).get("completion_tokens"),
            "request_sha256": record["request_sha256"],
            "raw_record_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )
status = {
    "schema_version": 1,
    "run_id": RUN.name,
    "state": "ABORTED_BEFORE_SCORING_INTERFACE_FAILURE",
    "reason": "Both small-observer shadow responses exhausted the frozen 128-token output budget with empty final content; no typed proposal was available.",
    "calls_completed": len(calls),
    "expected_small_shadow_calls": 2,
    "large_shadow_calls": 0,
    "lane_calls": 0,
    "task_labels_opened_by_runner": False,
    "task_scores_emitted": False,
    "calls": calls,
}
(RUN / "run-status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
print(f"archived pilot 01 protocol and {len(calls)} failed shadow records")
