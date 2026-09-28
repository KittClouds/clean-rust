from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
RUN_ID = "e012-20260926-frame-decomposition-01"
BANK = ROOT / "bank/construction-01/scored-bank-a14"
RUN = ROOT / "artifacts/runs" / RUN_ID


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refusing to replace existing artifact: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    frame_doc = read_json(BANK / "observer-frames.json")
    truth_rows = read_json(BANK / "vault/frame-truth-index.json")
    receipt_rows = read_json(BANK / "vault/presentation-receipts.json")
    label_doc = read_json(BANK / "vault/candidate-check-labels-final-v3.json")

    frame_by_identity = {}
    for row in frame_doc["frames"]:
        identity = (row["task_id"], sha256(canonical(row)))
        frame_by_identity[identity] = row
    receipts = {
        (row["task_id"], row["condition"], row["frame_sha256"]): row
        for row in receipt_rows
    }
    labels_by_task: dict[str, list[dict]] = {}
    for row in label_doc["candidate_rows"]:
        labels_by_task.setdefault(row["task_id"], []).append(row)

    selected_truth = [row for row in truth_rows if row["condition"] == "full_frame"]
    if len(selected_truth) != 48:
        raise RuntimeError(f"expected 48 full-frame truth rows, got {len(selected_truth)}")

    public_frames: list[dict] = []
    presentation_bindings: list[dict] = []
    private_labels: list[dict] = []
    seen_identity: set[tuple[str, str]] = set()
    for truth in selected_truth:
        public_id = truth["presentation_task_id"]
        frame = frame_by_identity.get((public_id, truth["frame_sha256"]))
        if frame is None:
            raise RuntimeError(f"missing projected public frame: {public_id}")
        frame_hash = sha256(canonical(frame))
        if frame_hash != truth["frame_sha256"]:
            raise RuntimeError(f"projected frame hash mismatch: {public_id}")
        if frame.get("task_id") != public_id:
            raise RuntimeError(f"frame task ID mismatch: {public_id}")
        identity = (public_id, frame_hash)
        if identity in seen_identity:
            raise RuntimeError(f"duplicate full-frame public ID and digest: {public_id}")
        seen_identity.add(identity)
        sample_id = f"{public_id}__{frame_hash[:12]}"
        if any("hidden" in key.lower() or "gold" in key.lower() for key in frame):
            raise RuntimeError(f"hidden truth field leaked into public frame: {public_id}")

        receipt = receipts.get((public_id, "full_frame", frame_hash))
        if receipt is None:
            raise RuntimeError(f"missing presentation receipt: {public_id}")
        candidate_ids = [item["action"]["id"] for item in frame["action_options"]]
        if candidate_ids != receipt["ordered_action_ids"]:
            raise RuntimeError(f"producer order differs from receipt: {public_id}")
        if receipt["frame_sha256"] != frame_hash or receipt["task_digest_hex"] != frame_hash:
            raise RuntimeError(
                f"presentation receipt frame binding mismatch: {public_id}; "
                f"frame={frame_hash}; receipt_frame={receipt['frame_sha256']}; "
                f"task_digest={receipt['task_digest_hex']}; receipt_task={receipt['task_id']}"
            )

        public_frames.append({
            "sample_id": sample_id, "task_id": public_id,
            "frame_sha256": frame_hash, "frame": frame,
        })
        presentation_bindings.append({
            "sample_id": sample_id, "task_id": public_id,
            "frame_digest_hex": receipt["task_digest_hex"],
            "request_id_hex": receipt["request_id_hex"],
            "receipt_digest_hex": receipt["receipt_digest_hex"],
            "receipt_hex": receipt["receipt_hex"],
            "ordered_action_ids": receipt["ordered_action_ids"],
            "frame_sha256": receipt["frame_sha256"],
        })

        task_labels = labels_by_task.get(truth["task_id"], [])
        if len(task_labels) != 4:
            raise RuntimeError(f"expected four candidate labels for {truth['task_id']}")
        label_by_id = {row["action_id_hidden"]: row for row in task_labels}
        if set(label_by_id) != set(candidate_ids):
            raise RuntimeError(f"label/action IDs differ for {truth['task_id']}")
        candidate_outcomes = []
        for option in frame["action_options"]:
            label = label_by_id[option["action"]["id"]]
            if label["patch_sha256_hidden"] != option["patch_sha256"]:
                raise RuntimeError(f"candidate patch label mismatch: {truth['task_id']}")
            candidate_outcomes.append({
                "action_id": option["action"]["id"],
                "patch_sha256": option["patch_sha256"],
                "task_candidate_passed": bool(label["task_candidate_passed"]),
                "compile_failed": bool(label["compile_failed"]),
            })
        private_labels.append({
            "sample_id": sample_id, "task_id": public_id,
            "internal_task_id": truth["task_id"],
            "family": truth["family_hidden"],
            "repository": truth["repository_hidden"],
            "stratum": truth["stratum_hidden"],
            "truth_support": truth["truth_support_hidden"],
            "primary_gold_action_id": truth["primary_gold_action_id_hidden"],
            "expected_valid_action_ids": truth["expected_valid_action_ids_hidden"],
            "direct_decision": truth["direct_decision_hidden"],
            "pair_id": truth["pair_id_hidden"],
            "candidate_outcomes": candidate_outcomes,
        })

    write_new(RUN / "inputs/full-frame-lock.json", {
        "schema_version": 1, "run_id": RUN_ID, "frame_count": len(public_frames),
        "selection": "condition == full_frame; original producer order preserved",
        "frames": public_frames,
    })
    write_new(RUN / "inputs/presentation-bindings.json", {
        "schema_version": 1, "run_id": RUN_ID, "frame_count": len(presentation_bindings),
        "presentation_receipts_are_not_model_inputs": True, "bindings": presentation_bindings,
    })
    write_new(RUN / "vault/evaluation-labels.json", {
        "schema_version": 1, "run_id": RUN_ID,
        "sealed_for_post-inference-scoring": True, "task_count": len(private_labels),
        "tasks": private_labels,
    })
    print(json.dumps({
        "state": "FULL_FRAME_INPUTS_PREPARED", "run_id": RUN_ID,
        "frames": len(public_frames), "presentation_bindings": len(presentation_bindings),
        "private_label_tasks": len(private_labels),
        "frame_lock_sha256": sha256((RUN / "inputs/full-frame-lock.json").read_bytes()),
        "presentation_lock_sha256": sha256((RUN / "inputs/presentation-bindings.json").read_bytes()),
        "private_labels_sha256": sha256((RUN / "vault/evaluation-labels.json").read_bytes()),
    }, indent=2))


if __name__ == "__main__":
    main()
