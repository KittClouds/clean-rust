from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011")
BASE_LOCK = ROOT / "inputs/e010-heldout-frame-lock.json"
R2_LOCK = ROOT / "repairs/candidate-presentation-factorial-v1/artifacts/runs/e011-r2-20260925-presentation-factorial-01/frame-lock-order-only.json"
OUT = ROOT / "repairs/producer-order-v1/artifacts/runs/e011-producer-order-restoration-01"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    if OUT.exists() and any(OUT.iterdir()):
        raise SystemExit(f"refusing to overwrite order restoration output: {OUT}")
    base_lock = read_json(BASE_LOCK)
    r2_lock = read_json(R2_LOCK)
    base_frames = {row["frame"]["task_id"]: row["frame"] for row in base_lock["frames"]}
    permuted_frames = {row["task_id"]: row["frame"] for row in r2_lock["frames"]}
    if len(base_frames) != 16 or base_frames.keys() != permuted_frames.keys():
        raise RuntimeError("order-restoration frames do not pair across all 16 tasks")

    results = []
    for task_id, baseline in base_frames.items():
        baseline_options = baseline["action_options"]
        ordinal_by_patch = {
            option["patch_sha256"]: ordinal for ordinal, option in enumerate(baseline_options)
        }
        permuted = permuted_frames[task_id]
        if set(ordinal_by_patch) != {option["patch_sha256"] for option in permuted["action_options"]}:
            raise RuntimeError(f"candidate set changed in order-only frame: {task_id}")
        sequenced = [
            (ordinal_by_patch[option["patch_sha256"]], option)
            for option in permuted["action_options"]
        ]
        sequenced.sort(key=lambda pair: pair[0])
        restored = dict(permuted)
        restored["action_options"] = [option for _, option in sequenced]
        same_frame = restored == baseline
        if not same_frame:
            raise RuntimeError(f"producer-order restoration did not reproduce the E010 frame: {task_id}")
        results.append({
            "task_id": task_id,
            "repository_id": baseline["repository_id"],
            "producer_order_restored": True,
            "baseline_frame_sha256": sha256(canonical(baseline)),
            "restored_frame_sha256": sha256(canonical(restored)),
        })

    output = {
        "schema_version": 1,
        "classification": "postrun deterministic input-adapter check; no model contact or labels",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "e010_frame_lock_sha256": sha256(BASE_LOCK.read_bytes()),
            "e011_r2_order_only_frame_lock_sha256": sha256(R2_LOCK.read_bytes()),
        },
        "task_count": len(results),
        "exact_frame_reconstruction_count": sum(row["producer_order_restored"] for row in results),
        "tasks": results,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "frame-restoration-report.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Producer Order Restoration Check",
        "",
        "- Classification: postrun deterministic input-adapter check; no model contact or labels.",
        f"- Exact E010 frame reconstructions: {output['exact_frame_reconstruction_count']}/{output['task_count']}.",
        "- Producer ordinals in this diagnostic come from each frozen E010 source-order sequence, matched by patch digest. Production assigns the ordinal when the candidate is created and carries it with the candidate.",
        "- Reordering is done by producer ordinal. Patch-hash ordering is not used.",
        "",
        "| Repository | Exact restored frames |",
        "| --- | ---: |",
    ]
    for repository in sorted({row["repository_id"] for row in results}):
        count = sum(row["repository_id"] == repository and row["producer_order_restored"] for row in results)
        lines.append(f"| {repository} | {count}/8 |")
    (OUT / "frame-restoration-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(OUT / "frame-restoration-report.md"), "exact_reconstructions": len(results)}, indent=2))


if __name__ == "__main__":
    main()
