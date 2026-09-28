from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
BASE_MANIFEST = CONSTRUCTION / "feasibility-input-manifest-v1.3.json"
MANIFEST_OUT = CONSTRUCTION / "task-construction-input-manifest-v1.1.json"
LOCK_OUT = CONSTRUCTION / "task-construction-lock-v1.1.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def add_file(rows: dict[str, dict[str, object]], path: Path, label: str | None = None) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    key = label or path.resolve().as_posix()
    data = path.read_bytes()
    row = {"path": key, "sha256": sha256(data), "bytes": len(data)}
    prior = rows.get(key)
    if prior is not None and prior != row:
        raise ValueError(f"conflicting input path: {key}")
    rows[key] = row


def add_tree_sources(rows: dict[str, dict[str, object]], root: Path) -> None:
    for fixed in (root / "Cargo.toml", root / "Cargo.lock"):
        if fixed.exists():
            add_file(rows, fixed)
    source_dirs = [root / "src", root / "tests"]
    for source_dir in source_dirs:
        if not source_dir.exists():
            continue
        for path in sorted(source_dir.rglob("*.rs")):
            add_file(rows, path)
    for path in sorted(root.glob("build.rs")):
        add_file(rows, path)


def command_version(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return (result.stdout or result.stderr).strip().splitlines()[0]


def main() -> None:
    if MANIFEST_OUT.exists() or LOCK_OUT.exists():
        raise SystemExit("refusing to overwrite E012 task-construction lock")
    if (CONSTRUCTION / "scored-bank-v1").exists():
        raise SystemExit("scored task fixtures already exist; this freezer is pre-fixture only")

    rows: dict[str, dict[str, object]] = {}
    prior = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    prior_rows = prior["files"]
    for item in prior_rows:
        path = ROOT / item["path"]
        data = path.read_bytes()
        if len(data) != item["bytes"] or sha256(data) != item["sha256"]:
            raise ValueError(f"frozen v1.3 input changed: {item['path']}")
        add_file(rows, path, item["path"])
    add_file(rows, BASE_MANIFEST, "bank/construction-01/feasibility-input-manifest-v1.3.json")

    internal = [
        ROOT / "protocol-lock-v0.3.json",
        ROOT / "channel-contract-v0.json",
        ROOT / "observer-frame-projection-v0.md",
        CONSTRUCTION / "family-design-v1.1.json",
        CONSTRUCTION / "family-design-lock-v1.3.json",
        CONSTRUCTION / "repository-source-inventory.json",
        CONSTRUCTION / "repository-source-audit-v1.json",
        CONSTRUCTION / "feasibility-audit-v2.json",
        ROOT / "amendments" / "bank-amendment-04.md",
        ROOT / "amendments" / "bank-amendment-04.json",
        ROOT / "amendments" / "bank-amendment-05.md",
        ROOT / "amendments" / "bank-amendment-05.json",
        ROOT / "task-construction-spec-v1.1.md",
        ROOT / "task-construction-spec-v1.1.json",
        ROOT / "scripts" / "build_task_sources_e012_v1.py",
        ROOT / "scripts" / "run_scored_checks_e012_v1.py",
        ROOT / "scripts" / "project_frames_e012_v1.py",
        ROOT / "scripts" / "audit_task_bank_e012_v1.py",
        ROOT / "scripts" / "freeze_task_construction_e012_v1_1.py",
    ]
    for path in internal:
        add_file(rows, path, path.relative_to(ROOT).as_posix())

    runtime_root = ROOT / "repairs" / "producer-order-v1" / "runtime-integration"
    for path in sorted(runtime_root.rglob("*")):
        if path.is_file() and path.suffix in {".rs", ".toml", ".lock"}:
            add_file(rows, path, path.relative_to(ROOT).as_posix())

    # Lock the local code and manifest inputs reached by the E011 runtime's path dependencies.
    dependency_roots = [
        Path(r"C:\rd-c\experiment-002"),
        Path(r"C:\rd-c\experiment-002\baseline\rdc-experiment-001"),
        Path(r"C:\rd-c\experiment-009"),
        Path(r"C:\rd-c\rdc-runtime-contracts-v1"),
    ]
    for dependency_root in dependency_roots:
        add_tree_sources(rows, dependency_root)

    observer_inputs = [
        Path(r"C:\rd-c\experiment-010\prompts\system-observer-v2.txt"),
        Path(r"C:\rd-c\experiment-010\schemas\observer-output.v2.json"),
        Path(r"C:\rd-c\experiment-010\models\bundle-lineage\v5-final\bundle-lock.json"),
        Path(r"C:\rd-c\experiment-010\models\bundle-lineage\selected-thresholds-v5.json"),
        Path(r"C:\rd-c\experiment-010\models\chat-templates\minicpm5-2b-q8-local-v3.jinja"),
        Path(r"C:\rd-c\experiment-010\models\chat-templates\ternary-bonsai-2-27b-ptq1-local-v3.jinja"),
    ]
    for path in observer_inputs:
        add_file(rows, path, f"observer-input::{path.as_posix()}")

    ordered_rows = sorted(rows.values(), key=lambda item: str(item["path"]))
    manifest = {
        "schema_version": 1,
        "state": "FROZEN_TASK_CONSTRUCTION_INPUTS_BEFORE_FIXTURES",
        "hash_algorithm": "sha256",
        "model_contact_authorized": False,
        "base_feasibility_manifest_sha256": sha256(BASE_MANIFEST.read_bytes()),
        "files": ordered_rows,
    }
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    manifest_hash = sha256(manifest_bytes)
    MANIFEST_OUT.write_bytes(manifest_bytes)
    lock = {
        "schema_version": 1,
        "program": "Selective Cognition / Action Region Program",
        "experiment": "E012 Prospective Frame Decomposition",
        "state": "FROZEN_BEFORE_SCORED_TASK_FIXTURES",
        "model_contact_authorized": False,
        "scored_fixtures_created": False,
        "specification": "task-construction-spec-v1.1.json",
        "specification_sha256": sha256((ROOT / "task-construction-spec-v1.1.json").read_bytes()),
        "amendments": ["E012-BANK-A04", "E012-BANK-A05"],
        "input_manifest": "bank/construction-01/task-construction-input-manifest-v1.1.json",
        "input_manifest_sha256": manifest_hash,
        "input_file_count": len(ordered_rows),
        "freeze_script_sha256": sha256(Path(__file__).read_bytes()),
        "toolchain": {
            "python": sys.version.split()[0],
            "cargo": command_version(["cargo", "--version"]),
            "rustc": command_version(["rustc", "--version"]),
            "cargo_target_dir": r"D:\rdc-e012-target\scored-checks",
        },
        "sha256_self_excluded": True,
    }
    LOCK_OUT.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": lock["state"], "files": len(ordered_rows), "manifest_sha256": manifest_hash, "lock": str(LOCK_OUT)}, indent=2))


if __name__ == "__main__":
    main()
