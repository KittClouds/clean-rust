from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
RUN = ROOT / "artifacts" / "runs" / "e009-20260925-pilot-01"
RUN.mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_tree_sha256(directory: Path) -> str:
    digest = hashlib.sha256()
    files = sorted([*directory.rglob("*.rs"), directory / "Cargo.toml"])
    for path in files:
        if not path.is_file():
            continue
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


bundle_lock_path = ROOT / "models" / "bundle-lock.json"
bundle_lock = json.loads(bundle_lock_path.read_text(encoding="utf-8"))
frames_lock_path = ROOT / "tasks" / "frames" / "frame-lock.json"
frames_lock = json.loads(frames_lock_path.read_text(encoding="utf-8"))
fixtures = {
    "coding-gpu-pick-01": ROOT / "tasks" / "gpu-pick-invalidation-focused",
    "coding-embedding-batch-01": ROOT / "tasks" / "embedding-batch-order-v2",
}

task_files = {}
for task_id, directory in fixtures.items():
    task_files[task_id] = {
        filename: sha256(directory / filename)
        for filename in (
            "snapshot.tar", "reference.patch", "mutant.patch", "noop.patch",
            "completion-gold.log", "completion-mutant.log",
        )
    }

lock_path = RUN / "frozen-input-lock.json"
if lock_path.exists():
    revision = 1
    while (RUN / f"frozen-input-lock-rev{revision}.json").exists():
        revision += 1
    previous_path = RUN / f"frozen-input-lock-rev{revision}.json"
    lock_path.replace(previous_path)

manifest = {
    "schema_version": 1,
    "run_id": RUN.name,
    "state": "FROZEN_BEFORE_MODEL_CONTACT",
    "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
    "task_bank": {
        "selection": "frozen local commit tasks, user-selected",
        "tasks": [
            {"task_id": item["frame"]["task_id"], "family": item["frame"]["task_family"], "frame_blake3": item["blake3"]}
            for item in frames_lock["frames"]
        ],
        "development_task_count": 0,
        "heldout_unit": "task family; two families total",
        "labels_file_sha256": sha256(ROOT / "sealed" / "labels.json"),
    },
    "contracts": {
        "authority": "E002 compiled authority and action simulator",
        "runtime_contracts": "rdc-runtime-contracts-v1",
        "paid_inspection_default": "disabled",
        "thresholds": {
            "minimum_applicability_milli": 700,
            "maximum_abstention_milli": 600,
        },
        "normalization": "line-endings-lf-v1",
    },
    "authority_dependencies": {
        "rdc-experiment-002": source_tree_sha256(Path(r"C:\rd-c\experiment-002")),
        "rdc-experiment-001": source_tree_sha256(Path(r"C:\rd-c\experiment-002\baseline\rdc-experiment-001")),
        "rdc-runtime-contracts-v1": source_tree_sha256(Path(r"C:\rd-c\rdc-runtime-contracts-v1")),
    },
    "lanes": ["hand-written", "small", "small-then-large-on-abstention", "always-large"],
    "models": [
        {
            "bundle_id": item["manifest"]["bundle_id"],
            "bundle_blake3": item["blake3"],
            "backbone_sha256": item["manifest"]["backbone_sha256"],
            "runtime_sha256": item["manifest"]["runtime_sha256"],
            "qualification_status": (
                "qualified_for_live_trial"
                if item["manifest"]["bundle_id"].startswith("minicpm")
                else "experimental_runtime_only"
            ),
        }
        for item in bundle_lock["bundles"]
    ],
    "decoding": {"temperature": 0, "top_p": 1, "seed": 0, "maximum_output_tokens": 128},
    "runtime_environment": {
        "inference": "local loopback only",
        "hardware": "RTX 3080 12GB; serial model service use",
        "small_target_path": r"D:\cargo-targets\rdc-e009\mini",
        "large_target_path": r"D:\cargo-targets\rdc-e009\large",
        "small_loopback_port": 18089,
        "large_loopback_port": 18090,
        "billed_api_usd": 0,
        "cost_proxy": "tokens and measured wall time; energy and hardware-dollar cost not measured",
    },
    "sha256": {
        "spec": sha256(ROOT / "SPEC.md"),
        "readme": sha256(ROOT / "README.md"),
        "e008_closeout": sha256(ROOT / "E008_CLOSEOUT.md"),
        "system_prompt": sha256(ROOT / "prompts" / "system-observer-v1.txt"),
        "output_schema": sha256(ROOT / "schemas" / "observer-output.v1.json"),
        "frame_lock": sha256(frames_lock_path),
        "candidate_lock": sha256(ROOT / "tasks" / "frames" / "candidate-lock.json"),
        "bundle_lock": sha256(bundle_lock_path),
        "model_artifact_locations": sha256(ROOT / "models" / "artifact-paths.json"),
        "task_artifacts": task_files,
        "cargo_lock": sha256(ROOT / "Cargo.lock"),
        "cargo_manifest": sha256(ROOT / "Cargo.toml"),
        "e009_source_tree": source_tree_sha256(ROOT / "src"),
        "label_ledger": sha256(ROOT / "sealed" / "labels.json"),
        "input_audit": sha256(ROOT / "sealed" / "input-audit.json"),
        "observer_runner": sha256(ROOT / "scripts" / "run_observer.py"),
        "lane_scorer": sha256(ROOT / "scripts" / "score_lanes.py"),
        "report_generator": sha256(ROOT / "scripts" / "report_e009.py"),
        "frame_freezer": sha256(ROOT / "scripts" / "freeze_bank.py"),
        "bundle_freezer": sha256(ROOT / "scripts" / "freeze_bundles.py"),
        "task_input_auditor": sha256(ROOT / "scripts" / "audit_inputs.py"),
        "run_lock_builder": sha256(ROOT / "scripts" / "freeze_run.py"),
        "authority_preflight": sha256(ROOT / "scripts" / "preflight_authority.py"),
        "input_auditor": sha256(ROOT / "scripts" / "audit_inputs.py"),
        "server_starter": sha256(ROOT / "scripts" / "start_observer_server.ps1"),
        "server_stopper": sha256(ROOT / "scripts" / "stop_observer_server.ps1"),
        "authorizer_source": sha256(ROOT / "src" / "bin" / "e009-authorize.rs"),
        "frame_schema_source": sha256(ROOT / "src" / "frame.rs"),
        "observer_schema_source": sha256(ROOT / "src" / "observer.rs"),
        "bundle_schema_source": sha256(ROOT / "src" / "bundle.rs"),
        "preflight_receipt": sha256(ROOT / "artifacts" / "preflight-final-v2" / "receipt.json"),
        "preflight_task_check_gold_gpu": sha256(ROOT / "artifacts" / "runs" / "e009-20260925-pilot-01" / "task-checks" / "preflight-gold-v2" / "coding-gpu-pick-01.json"),
    },
}
lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(lock_path)
