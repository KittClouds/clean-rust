from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011\repairs\candidate-canonicalization-v1")
PARENT = Path(r"C:\rd-c\experiment-011")
PARENT_RUN = PARENT / "artifacts/runs/e011-20260925-causal-evidence-01"
RUN_ID = "e011-r1-20260925-candidate-canonicalization-01"
RUN = ROOT / "artifacts/runs" / RUN_ID
ADAPTER = ROOT / "rdc-candidate-canonicalizer.exe"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def copy_once(source: Path, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite repair input: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def canonicalize_file(frame: dict, directory: Path, name: str) -> dict:
    source = directory / f"{name}.json"
    destination = directory / f"{name}.canonical.json"
    source.write_bytes(json.dumps(frame, ensure_ascii=False, indent=2).encode("utf-8"))
    subprocess.run([str(ADAPTER), "canonicalize", str(source), str(destination)], check=True)
    return read_json(destination)


def main() -> None:
    if RUN.exists() and any(RUN.iterdir()):
        raise SystemExit(f"refusing to overwrite nonempty repair run: {RUN}")
    RUN.mkdir(parents=True, exist_ok=True)

    files = {
        PARENT / "inputs/e010-heldout-frame-lock.json": ROOT / "inputs/e010-heldout-frame-lock.json",
        PARENT / "inputs/e010-heldout-sealed-labels.json": ROOT / "inputs/e010-heldout-sealed-labels.json",
        PARENT / "inputs/e010-frozen-input-lock.json": ROOT / "inputs/e010-frozen-input-lock.json",
        PARENT / "inputs/e009-v5-bundle-lock.json": ROOT / "inputs/e009-v5-bundle-lock.json",
        PARENT / "inputs/e009-v5-thresholds.json": ROOT / "inputs/e009-v5-thresholds.json",
        PARENT / "inputs/system-observer-v2.txt": ROOT / "inputs/system-observer-v2.txt",
        PARENT / "inputs/observer-output.v2.json": ROOT / "inputs/observer-output.v2.json",
        PARENT / "inputs/chat-template-small.jinja": ROOT / "inputs/chat-template-small.jinja",
        PARENT / "inputs/chat-template-large.jinja": ROOT / "inputs/chat-template-large.jinja",
    }
    for source, destination in files.items():
        copy_once(source, destination)

    base_lock = read_json(ROOT / "inputs/e010-heldout-frame-lock.json")
    perm_lock = read_json(PARENT_RUN / "frame-lock-candidate-permuted.json")
    base_frames = {item["frame"]["task_id"]: item["frame"] for item in base_lock["frames"]}
    perm_frames = {item["pair_task_id"]: item["frame"] for item in perm_lock["frames"]}
    if set(base_frames) != set(perm_frames) or len(base_frames) != 16:
        raise RuntimeError("E010 and E011 candidate-permutation task banks do not pair exactly")

    canonical_entries = []
    with tempfile.TemporaryDirectory(prefix="e011-r1-canonical-") as temporary:
        scratch = Path(temporary)
        for index, task_id in enumerate(sorted(base_frames), start=1):
            full = canonicalize_file(base_frames[task_id], scratch, f"full-{index:02d}")
            permuted = canonicalize_file(perm_frames[task_id], scratch, f"perm-{index:02d}")
            if canonical(full["frame"]) != canonical(permuted["frame"]):
                raise RuntimeError(f"canonical input differs under order/ID permutation: {task_id}")
            full_map = {row["patch_sha256"]: row for row in full["receipt"]}
            perm_map = {row["patch_sha256"]: row for row in permuted["receipt"]}
            if full_map.keys() != perm_map.keys():
                raise RuntimeError(f"canonical receipts lost candidates: {task_id}")
            for patch, full_row in full_map.items():
                if full_row["canonical_action_id"] != perm_map[patch]["canonical_action_id"]:
                    raise RuntimeError(f"canonical IDs differ for the same patch: {task_id}")
            canonical_entries.append(
                {
                    "task_id": task_id,
                    "frame_sha256": sha256(canonical(full["frame"])),
                    "frame": full["frame"],
                    "receipt_full_frame": full["receipt"],
                    "receipt_candidate_permuted": permuted["receipt"],
                }
            )

    frame_lock_path = RUN / "canonical-frame-lock.json"
    write_json(frame_lock_path, {"schema_version": 1, "adapter_id": "candidate-canonicalization-v1", "frames": canonical_entries})
    identity_path = ROOT / "observer-adapter-identities.json"
    write_json(
        identity_path,
        {
            "schema_version": 1,
            "small_bundle_id": "minicpm5-2b-q8-local-v5+candidate-canonicalization-v1",
            "large_bundle_id": "ternary-bonsai-2-27b-ptq1-local-v5+candidate-canonicalization-v1",
            "base_weight_bundles": {
                "small": "minicpm5-2b-q8-local-v5",
                "large": "ternary-bonsai-2-27b-ptq1-local-v5",
            },
            "adapter_id": "candidate-canonicalization-v1",
            "action_sort_key": "patch_sha256 ascending",
            "canonical_action_ids": "1 through N in sorted order",
            "proposal_mapping": "canonical ID to original action ID through a recorded patch-digest receipt",
            "thresholds": {"minimum_applicability_milli": 850, "maximum_abstention_milli": 150},
        },
    )

    parent_links = {
        "e011_pre_model_seal_sha256": sha256((PARENT_RUN / "pre-model-seal.json").read_bytes()),
        "e011_postrun_output_seal_sha256": sha256((PARENT_RUN / "postrun-output-seal.json").read_bytes()),
        "e011_score_sha256": sha256((PARENT_RUN / "score-e011.json").read_bytes()),
        "e011_episode_autopsy_sha256": sha256((PARENT_RUN / "episode-autopsy-e011.json").read_bytes()),
        "parent_candidate_frame_lock_sha256": sha256((PARENT_RUN / "frame-lock-candidate-permuted.json").read_bytes()),
    }
    input_hashes = {
        path.relative_to(ROOT).as_posix(): sha256(path.read_bytes())
        for path in sorted((ROOT / "inputs").rglob("*"))
        if path.is_file()
    }
    input_hashes["observer-adapter-identities.json"] = sha256(identity_path.read_bytes())
    input_hashes["spec.md"] = sha256((ROOT / "spec.md").read_bytes())
    input_hashes["adapter/Cargo.toml"] = sha256((ROOT / "adapter/Cargo.toml").read_bytes())
    input_hashes["adapter/Cargo.lock"] = sha256((ROOT / "adapter/Cargo.lock").read_bytes())
    for path in sorted((ROOT / "adapter/src").rglob("*.rs")):
        input_hashes[path.relative_to(ROOT).as_posix()] = sha256(path.read_bytes())
    input_hashes["rdc-candidate-canonicalizer.exe"] = sha256(ADAPTER.read_bytes())

    lock = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_MODEL_CONTACT",
        "run_id": RUN_ID,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "post-E011 deterministic adapter repair test; same-bank diagnostic only",
        "task_bank": "E010 heldout bank reused; E010 labels previously opened",
        "observer_weights": "E009 v5 small and large unchanged",
        "observer_bundle_ids": {
            "small": "minicpm5-2b-q8-local-v5+candidate-canonicalization-v1",
            "large": "ternary-bonsai-2-27b-ptq1-local-v5+candidate-canonicalization-v1",
        },
        "prompt_schema_normalization": "E009 v5 unchanged",
        "thresholds": {"minimum_applicability_milli": 850, "maximum_abstention_milli": 150},
        "routing": "small first, large on small abstention or rejection",
        "authority": "map proposal to original action ID, then deterministic E002 authority; shadow-only, no action effect",
        "parent_e011_hashes": parent_links,
        "sha256": {
            "input_files": input_hashes,
            "canonical_frame_lock": sha256(frame_lock_path.read_bytes()),
            "canonical_action_count": 16,
            "full_and_permuted_frames_canonicalized_identically": True,
        },
    }
    write_json(RUN / "pre-model-input-lock.json", lock)
    print(json.dumps({"run_id": RUN_ID, "state": lock["state"], "canonical_frames": len(canonical_entries), "source_forms_per_frame": 2}, indent=2))


if __name__ == "__main__":
    main()
