from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011")
RUN = ROOT / "artifacts/runs/e011-20260925-causal-evidence-01"
HASH_TOOL = ROOT / "tools/artifact-hash.exe"
CONDITIONS = (
    "evidence-masked",
    "evidence-swapped",
    "repository-neutralized",
    "candidate-permuted",
)
ROLES = ("small", "large")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def repo_rewrite(value: object) -> object:
    if isinstance(value, str):
        for name in ("ripgrep", "turbovec"):
            value = re.sub(re.escape(name), "repository", value, flags=re.IGNORECASE)
        return value
    if isinstance(value, list):
        return [repo_rewrite(item) for item in value]
    if isinstance(value, dict):
        return {key: repo_rewrite(item) for key, item in value.items()}
    return value


def blake3_strings(values: list[str]) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="e011-seal-b3-") as temporary:
        paths = []
        for index, value in enumerate(values):
            path = Path(temporary) / f"content-{index:04d}.bin"
            path.write_bytes(value.encode("utf-8"))
            paths.append(path)
        completed = subprocess.run(
            [str(HASH_TOOL), *[str(path) for path in paths]],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return [line.rsplit("\t", 1)[1] for line in completed.stdout.splitlines()]


def audit_frame_changes(base: dict, condition: str, frame: dict, donor: dict | None) -> None:
    if condition == "evidence-masked":
        for key in base:
            if key != "evidence" and frame[key] != base[key]:
                raise RuntimeError(f"evidence mask changed unrelated field {key}/{base['task_id']}")
        if len(frame["evidence"]) != len(base["evidence"]):
            raise RuntimeError("evidence mask changed the evidence item count")
        for before, after in zip(base["evidence"], frame["evidence"], strict=True):
            if before["kind"] != after["kind"] or after["source_id"].startswith("redacted-source-") is False:
                raise RuntimeError("evidence mask did not preserve kind and redact source")
            if "task-specific evidence body removed" not in after["content"]:
                raise RuntimeError("evidence mask content is not neutral")
    elif condition == "evidence-swapped":
        expected = copy.deepcopy(base)
        expected["evidence"] = copy.deepcopy(donor["evidence"])
        if frame != expected:
            raise RuntimeError(f"evidence swap changed more than its intended field: {base['task_id']}")
    elif condition == "repository-neutralized":
        expected = repo_rewrite(copy.deepcopy(base))
        expected["task_id"] = frame["task_id"]
        expected["repository_id"] = "repository-neutral"
        expected["repository_revision"] = "revision-neutralized"
        expected["snapshot_sha256"] = "0" * 64
        if frame["task_family"] != re.sub(r"^(ripgrep|turbovec)-", "family-", base["task_family"]):
            family_number = frame["task_family"]
            if not re.fullmatch(r"family-[0-9]{2}", family_number):
                raise RuntimeError("repository-neutralized family ID is malformed")
        expected["task_family"] = frame["task_family"]
        expected["task_id"] = frame["task_id"]
        for expected_evidence, actual_evidence in zip(expected["evidence"], frame["evidence"], strict=True):
            expected_evidence["content_blake3"] = actual_evidence["content_blake3"]
        if frame != expected:
            raise RuntimeError(f"repository neutralization changed unrelated fields: {base['task_id']}")
    elif condition == "candidate-permuted":
        if frame.keys() != base.keys():
            raise RuntimeError("candidate permutation changed frame schema")
        for key in base:
            if key != "action_options" and frame[key] != base[key]:
                raise RuntimeError(f"candidate permutation changed unrelated field {key}/{base['task_id']}")
        before = {item["patch_sha256"]: item for item in base["action_options"]}
        after = {item["patch_sha256"]: item for item in frame["action_options"]}
        if before.keys() != after.keys():
            raise RuntimeError("candidate permutation lost or added an action")
        for digest, original in before.items():
            changed = after[digest]
            if changed["summary"] != original["summary"] or changed["diff_excerpt"] != original["diff_excerpt"]:
                raise RuntimeError("candidate permutation changed action content")
            if changed["action"]["id"] == original["action"]["id"]:
                raise RuntimeError("candidate permutation retained an original action ID")


def main() -> None:
    seal_path = RUN / "pre-model-seal.json"
    if seal_path.exists():
        raise SystemExit(f"pre-model seal already exists: {seal_path}")
    frozen_path = RUN / "frozen-input-lock.json"
    frozen = read_json(frozen_path)
    if frozen.get("state") != "FROZEN_BEFORE_MODEL_CONTACT":
        raise SystemExit("pre-model lock is not frozen")
    if any((RUN / role / "server-process.json").exists() for role in ROLES):
        raise SystemExit("observer server was already started; pre-model sealing is too late")
    if (RUN / "outputs").exists():
        raise SystemExit("observer outputs exist; pre-model sealing is too late")

    source_lock = read_json(ROOT / "inputs/e010-heldout-frame-lock.json")
    base = {item["frame"]["task_id"]: item["frame"] for item in source_lock["frames"]}
    auxiliary = read_json(RUN / "transform-auxiliary-lock.json")
    checked_content: list[str] = []
    for condition in CONDITIONS:
        lock_path = RUN / f"frame-lock-{condition}.json"
        if sha256(lock_path.read_bytes()) != frozen["sha256"]["transformed_frame_locks"][condition]:
            raise RuntimeError(f"frame lock hash mismatch: {condition}")
        lock = read_json(lock_path)
        if len(lock["frames"]) != 16:
            raise RuntimeError(f"wrong task count in {condition}")
        seen: set[str] = set()
        for entry in lock["frames"]:
            pair_id = entry["pair_task_id"]
            frame = entry["frame"]
            if pair_id in seen or pair_id not in base:
                raise RuntimeError(f"bad pair identity in {condition}/{pair_id}")
            seen.add(pair_id)
            if sha256(canonical(frame)) != entry["frame_sha256"]:
                raise RuntimeError(f"frame hash mismatch: {condition}/{pair_id}")
            donor = None
            if condition == "evidence-swapped":
                donor_id = auxiliary["evidence_swap_donors"][pair_id]
                donor = base[donor_id]
                if donor["repository_id"] != base[pair_id]["repository_id"]:
                    raise RuntimeError("evidence donor crossed repository boundary")
                if donor["task_variant"] != base[pair_id]["task_variant"]:
                    raise RuntimeError("evidence donor crossed prompt-variant boundary")
            audit_frame_changes(base[pair_id], condition, frame, donor)
            checked_content.extend(item["content"] for item in frame.get("evidence", []))
            forbidden = {"expected_task_completion", "is_correct", "ground_truth", "sealed_label", "oracle_action"}
            if forbidden.intersection(frame.keys()):
                raise RuntimeError(f"evaluation label key leaked into frame: {pair_id}")
        if len(seen) != 16:
            raise RuntimeError(f"paired task coverage is incomplete in {condition}")

    hashes = blake3_strings(checked_content)
    cursor = 0
    for condition in CONDITIONS:
        lock = read_json(RUN / f"frame-lock-{condition}.json")
        for entry in lock["frames"]:
            for evidence in entry["frame"].get("evidence", []):
                if evidence["content_blake3"] != hashes[cursor]:
                    raise RuntimeError(f"evidence hash mismatch: {condition}/{entry['pair_task_id']}")
                cursor += 1

    for role, source in (
        ("small", Path(r"C:\rd-c\experiment-010\artifacts\runs\e010-20260925-cross-repo-01\heldout-shadow-small")),
        ("large", Path(r"C:\rd-c\experiment-010\artifacts\runs\e010-20260925-cross-repo-01\heldout-shadow-large")),
    ):
        copied = RUN / "full-frame-baseline" / role
        if tree_hash(source) != tree_hash(copied):
            raise RuntimeError(f"copied E010 {role} baseline differs from source output tree")

    code_paths = (
        ROOT / "spec/E011-causal-evidence-dependence.md",
        ROOT / "scripts/prepare_e011.py",
        ROOT / "scripts/run_observer_e011.py",
        ROOT / "scripts/score_e011.py",
        ROOT / "scripts/seal_e011.py",
        ROOT / "scripts/start_observer_e011.ps1",
        ROOT / "scripts/stop_observer_e011.ps1",
        HASH_TOOL,
    )
    code_hashes = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()) for path in code_paths}
    for relative, expected in frozen["sha256"]["inputs"].items():
        if relative.startswith("e010-"):
            continue
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise RuntimeError(f"frozen input file changed: {relative}")

    for role in ROLES:
        source_tree_key = f"e010-{role}-output-tree"
        if tree_hash(RUN / "full-frame-baseline" / role) != frozen["sha256"]["inputs"][source_tree_key]:
            raise RuntimeError(f"baseline tree hash mismatch for {role}")

    seal = {
        "schema_version": 1,
        "state": "SEALED_BEFORE_MODEL_CONTACT",
        "run_id": frozen["run_id"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_input_lock_sha256": sha256(frozen_path.read_bytes()),
        "code_sha256": code_hashes,
        "transformed_frame_locks_sha256": frozen["sha256"]["transformed_frame_locks"],
        "e010_baseline_tree_sha256": {
            role: tree_hash(RUN / "full-frame-baseline" / role) for role in ROLES
        },
        "task_count_per_condition": 16,
        "model_contact_started": False,
        "transformation_audit": "PASS",
    }
    seal_path.write_text(json.dumps(seal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": seal["state"], "seal_sha256": sha256(seal_path.read_bytes()), "audited_frames": cursor}, indent=2))


if __name__ == "__main__":
    main()
