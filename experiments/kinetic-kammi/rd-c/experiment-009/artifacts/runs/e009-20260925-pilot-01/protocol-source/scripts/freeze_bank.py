from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
FRAMES = ROOT / "tasks" / "frames"
LABELS = ROOT / "sealed" / "labels.json"
FRAMES.mkdir(parents=True, exist_ok=True)
LABELS.parent.mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evidence(kind: str, source_id: str, content: str) -> dict[str, str]:
    return {
        "kind": kind,
        "source_id": source_id,
        "content_blake3": "",
        "content": content,
    }


def option(action_id: int, summary: str, excerpt: str, patch: Path) -> dict:
    return {
        "action": {"id": action_id, "schema_id": 1},
        "summary": summary,
        "diff_excerpt": excerpt,
        "patch_sha256": sha256(patch),
    }


gpu = ROOT / "tasks" / "gpu-pick-invalidation-focused"
embed = ROOT / "tasks" / "embedding-batch-order-v2"
(gpu / "noop.patch").write_bytes(b"")
(embed / "noop.patch").write_bytes(b"")
frames = [
    {
        "schema_id": "rdc-real-coding-observation.v1",
        "task_id": "coding-gpu-pick-01",
        "task_family": "asynchronous-gpu-picking",
        "task_prompt": (
            "Update asynchronous GPU picking so a readback cannot apply after a newer "
            "pick request or viewport resize makes it stale. Preserve hover/selection "
            "behavior, fail closed on stale results, and add regression tests. Choose "
            "one offered patch."
        ),
        "repository_revision": "1344f4710148679f7cf0301f57c25b15b23188d4",
        "snapshot_sha256": sha256(gpu / "snapshot.tar"),
        "evidence": [
            evidence(
                "source_excerpt",
                "phoenix-native/crates/graph-render-wgpu/src/picking.rs",
                "PickRequest currently stores x, y, and intent. PickingPass stores a pending request and an inflight intent. resize recreates pick textures and clears pending work. poll maps the encoded slot and returns PickResult without checking whether the readback still belongs to the current request or viewport.",
            ),
            evidence(
                "baseline_tool_result",
                "cargo-test-graph-render-wgpu-base",
                "Frozen base commit: graph-render-wgpu library tests passed 38/38 and scene_contract integration tests passed 8/8. The task-specific stale-readback regression is absent from the base.",
            ),
        ],
        "action_options": [
            option(
                23,
                "Track request and viewport generations and return a mapped result only when both still match.",
                "Store request_epoch and viewport_revision on each PickRequest. In poll, require `request_epoch == epoch && request_viewport_revision == viewport_revision` before producing PickResult.",
                gpu / "reference.patch",
            ),
            option(
                71,
                "Keep the current asynchronous readback behavior.",
                "No generation values are attached to the in-flight readback; poll returns the mapped slot as a PickResult.",
                gpu / "noop.patch",
            ),
            option(
                14,
                "Track request and viewport generations and return a mapped result when either still matches.",
                "Store request_epoch and viewport_revision on each PickRequest. In poll, require `request_epoch == epoch || request_viewport_revision == viewport_revision` before producing PickResult.",
                gpu / "mutant.patch",
            ),
        ],
    },
    {
        "schema_id": "rdc-real-coding-observation.v1",
        "task_id": "coding-embedding-batch-01",
        "task_family": "embedding-length-batched-execution",
        "task_prompt": (
            "Reduce padding amplification in batched embedding inference by grouping "
            "similar-length inputs, restore output rows to their original positions, "
            "and expose padding telemetry. Preserve current model profiles and pooling. "
            "Add focused regression tests. Choose one offered patch."
        ),
        "repository_revision": "0263e3884d5370f7a9bd2c2217527f4fd87ab33d",
        "snapshot_sha256": sha256(embed / "snapshot.tar"),
        "evidence": [
            evidence(
                "source_excerpt",
                "rust-native/phoenix/crates/phoenix-embed/src/lib.rs",
                "embed_batched_flat clamps batch_size to at least one, allocates a result batch, then passes contiguous input-order chunks to embed_batch_into. It records no padding telemetry and performs no length ordering before inference.",
            ),
            evidence(
                "baseline_tool_result",
                "cargo-test-phoenix-embed-base",
                "Frozen base commit: phoenix-embed library tests passed 7/7. No length-bucket stability or padding telemetry tests exist in the base.",
            ),
        ],
        "action_options": [
            option(
                17,
                "Group by input length and restore the original order without an explicit tie-break key; include run telemetry.",
                "`order.sort_unstable_by_key(|&index| texts[index].as_ref().len());` then batch the ordered indices and scatter each output row back by its original index.",
                embed / "mutant.patch",
            ),
            option(
                42,
                "Keep contiguous input-order batching without length sorting or padding telemetry.",
                "`for chunk in texts.chunks(batch_size) { self.embed_batch_into(chunk, &mut scratch, &mut rows)?; }`",
                embed / "noop.patch",
            ),
            option(
                51,
                "Group by input length, break equal-length ties by original index, restore output order, and report padding telemetry.",
                "`order.sort_unstable_by_key(|&index| (texts[index].as_ref().len(), index));` then scatter outputs to original row indices and accumulate token and attention padding counters.",
                embed / "reference.patch",
            ),
        ],
    },
]

# Keep option IDs opaque and vary the answer position between task families.
frames[1]["action_options"] = sorted(
    frames[1]["action_options"],
    key=lambda item: {17: 0, 51: 1, 42: 2}[item["action"]["id"]],
)

unlocked = FRAMES / "frames-unlocked.json"
unlocked.write_text(json.dumps({"frames": frames}, indent=2) + "\n", encoding="utf-8")
locked = FRAMES / "frame-lock.json"
if locked.exists() and not (FRAMES / "frame-lock-pre-position-audit.json").exists():
    (FRAMES / "frame-lock-pre-position-audit.json").write_bytes(locked.read_bytes())
environment = os.environ.copy()
environment["CARGO_TARGET_DIR"] = r"D:\cargo-targets\rdc-e009"
subprocess.run(
    [
        "cargo",
        "run",
        "--quiet",
        "--manifest-path",
        str(ROOT / "Cargo.toml"),
        "--bin",
        "e009-freeze-frames",
        "--",
        str(unlocked),
        str(locked),
    ],
    cwd=ROOT,
    env=environment,
    check=True,
)

candidate_lock = {"schema_version": 1, "tasks": {}}
for task_id, directory in (("coding-gpu-pick-01", gpu), ("coding-embedding-batch-01", embed)):
    task_candidates = {}
    for action_id, candidate_name, patch_name in (
        ("gold", "candidate-gold", "reference.patch"),
        ("mutant", "candidate-mutant", "mutant.patch"),
    ):
        patch_paths = []
        for line in (directory / patch_name).read_text(encoding="utf-8").splitlines():
            if line.startswith("+++ b/"):
                patch_paths.append(line[6:])
        candidate_root = directory / candidate_name
        source_hashes = {}
        for relative in sorted(set(patch_paths)):
            path = candidate_root / relative
            if not path.is_file():
                raise SystemExit(f"missing applied candidate file: {path}")
            source_hashes[relative] = sha256(path)
        task_candidates[action_id] = source_hashes
    candidate_lock["tasks"][task_id] = task_candidates
candidate_lock_path = FRAMES / "candidate-lock.json"
if candidate_lock_path.exists() and not (FRAMES / "candidate-lock-pre-final.json").exists():
    (FRAMES / "candidate-lock-pre-final.json").write_bytes(candidate_lock_path.read_bytes())
candidate_lock_path.write_text(
    json.dumps(candidate_lock, indent=2) + "\n", encoding="utf-8"
)

labels = {
    "schema_version": 1,
    "access": "label-side only; exclude from all observer and routing inputs",
    "tasks": {
        "coding-gpu-pick-01": {
            "completion_check": "one task-specific e009_epoch_tests test must run and pass",
            "actions": {
                "23": {"expected_task_completion": True, "check": "AND implementation passes stale-generation regression"},
                "14": {"expected_task_completion": False, "check": "OR mutant fails stale-generation regression"},
                "71": {"expected_task_completion": False, "check": "base has no task-specific regression"},
            },
        },
        "coding-embedding-batch-01": {
            "completion_check": "stable-order and telemetry regression tests must both run and pass",
            "actions": {
                "51": {"expected_task_completion": True, "check": "both regression tests pass"},
                "17": {"expected_task_completion": False, "check": "stable-order regression fails; telemetry regression passes"},
                "42": {"expected_task_completion": False, "check": "base has neither task-specific regression"},
            },
        },
    },
}
LABELS.write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")
print(f"locked {len(frames)} frames: {locked}")
print(f"label ledger: {LABELS}")
