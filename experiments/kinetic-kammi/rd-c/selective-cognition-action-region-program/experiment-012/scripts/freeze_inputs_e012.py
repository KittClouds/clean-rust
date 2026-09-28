from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
RUN_ID = "e012-20260926-frame-decomposition-01"
RUN = ROOT / "artifacts/runs" / RUN_ID
BANK = ROOT / "bank/construction-01"
V5 = ROOT / "inputs/e009-v5"
TARGET = RUN / "frozen-input-lock.json"
SEAL = RUN / "pre-model-seal.json"
AUTHORITY_TARGET = r"D:\rdc-e012-target\e012-authority-20260926\release\e011-authorize.exe"
MODEL_PATHS = {
    "small_runtime": r"D:\phoenix-runtimes\llama.cpp\b10982\runtime\llama-server.exe",
    "small_model": r"D:\phoenix-models\candidates\minicpm5-2b\2079a22f3beaa4e306449978533478fe0522f4b3\MiniCPM5-2B-Q8_0.gguf",
    "large_runtime": r"D:\phoenix-runtimes\prism-llama.cpp\prism-b10685-7dffb15\win-cuda-12.4\runtime\llama-server.exe",
    "large_model": r"D:\phoenix-models\candidates\ternary-bonsai-2-27b\6ed5e12bf84b7a63069882c91dd9e9218647d17b\Ternary-Bonsai-2-27B-PTQ1_0.gguf",
}
EXPECTED_ROLES = {
    "small": "minicpm5-2b-q8-local-v5",
    "large": "ternary-bonsai-2-27b-ptq1-local-v5",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(path: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    total = 0
    for item in files:
        rel = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(b"\0")
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
                total += len(chunk)
        digest.update(b"\0")
    return digest.hexdigest(), len(files), total


def local_entry(relative: str) -> dict:
    path = ROOT / Path(relative)
    if not path.is_file():
        raise RuntimeError(f"missing frozen local file: {relative}")
    return {
        "path": Path(relative).as_posix(),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }


def main() -> None:
    if TARGET.exists() or SEAL.exists():
        raise SystemExit("refusing to replace an existing pre-model lock or seal")

    a21_lock_path = BANK / "precontact-audit-lock-a21-v1.json"
    a21 = json.loads(a21_lock_path.read_text(encoding="utf-8"))
    if a21.get("state") != "FROZEN_BEFORE_A21_PRECONTACT_AUDIT" or a21.get("model_contact_authorized") is not False:
        raise RuntimeError("A21 precontact audit lock is not the expected sealed input")
    for item in a21["files"]:
        path = ROOT / Path(item["path"])
        if not path.is_file() or file_sha256(path) != item["sha256"]:
            raise RuntimeError(f"A21 locked bank input changed: {item['path']}")
    precontact = BANK / "scored-bank-a14/vault/precontact-audit-a14-v1.json"
    precontact_report = json.loads(precontact.read_text(encoding="utf-8"))
    if (
        precontact_report.get("state") != "PRECONTACT_AUDIT_PASS_NO_MODEL_CONTACT"
        or precontact_report.get("model_contact_authorized") is not False
        or precontact_report.get("frame_count") != 1248
        or precontact_report.get("presentation_receipt_replays") != 1248
    ):
        raise RuntimeError("A21 bank gate report does not pass")

    a16 = json.loads((BANK / "scored-bank-a14/vault/paired-truth-audit-a16-v1.json").read_text(encoding="utf-8"))
    if a16.get("state") != "A16_PAIRED_TRUTH_AUDIT_PASS_NO_MODEL_CONTACT":
        raise RuntimeError("A16 paired-truth audit does not pass")
    a19 = json.loads((BANK / "scored-bank-a14/vault/nuisance-baselines-a19-v1.json").read_text(encoding="utf-8"))
    if a19.get("state") != "A19_NUISANCE_BASELINE_AUDIT_COMPLETE_NO_MODEL_CONTACT":
        raise RuntimeError("A19 nuisance audit is incomplete")

    rust_manifest = ROOT / "inputs/authority/source/e011-runtime/Cargo.toml"
    rust_lock = ROOT / "inputs/authority/source/e011-runtime/Cargo.lock"
    build_log = RUN / "preflight/authority-cargo-test.log"
    if not rust_manifest.is_file() or not rust_lock.is_file() or not build_log.is_file():
        raise RuntimeError("authority source snapshot or D: target test log is missing")
    if "test result: ok. 4 passed; 0 failed" not in build_log.read_text(encoding="utf-8").lower():
        raise RuntimeError("producer-order live-path integration tests did not all pass")

    bundle_lock = json.loads((V5 / "e009-v5-bundle-lock.json").read_text(encoding="utf-8"))
    e010 = json.loads((V5 / "e010-frozen-input-lock.json").read_text(encoding="utf-8"))
    if e010.get("state") != "FROZEN_BEFORE_MODEL_CONTACT":
        raise RuntimeError("copied E010 v5 observer selection lock is not frozen")
    for role, bundle_id in EXPECTED_ROLES.items():
        selected = [row for row in e010["models"] if row["role"] == role]
        bundle = [row for row in bundle_lock["bundles"] if row["manifest"]["bundle_id"] == bundle_id]
        if len(selected) != 1 or len(bundle) != 1:
            raise RuntimeError(f"missing frozen E009 v5 {role} bundle")
        if selected[0]["bundle_id"] != bundle_id or selected[0]["bundle_blake3"] != bundle[0]["blake3"]:
            raise RuntimeError(f"E009 v5 {role} bundle selection mismatch")
        if selected[0]["thresholds"] != {
            "minimum_applicability_milli": 850,
            "maximum_abstention_milli": 150,
        }:
            raise RuntimeError(f"E009 v5 {role} thresholds changed")

    required = [
        "bank/phase-03-full-frame-baseline-v1.md",
        "bank/phase-03-full-frame-baseline-v1.json",
        "PROTOCOL.md",
        "channel-contract-v0.json",
        "bank-construction-plan-v1.4.md",
        "task-construction-spec-v1.2.md",
        "task-construction-spec-v1.1.md",
        "task-construction-spec-v1.1.json",
        "scripts/build_task_sources_e012_v1.py",
        "scripts/freeze_task_construction_e012_v1_1.py",
        "scripts/freeze_scored_check_runner_e012_a14_v1.py",
        "scripts/finalize_pair_locked_bank_e012_a14_v3.py",
        "scripts/freeze_label_finalization_e012_v1.py",
        "scripts/project_frames_e012_a14_v1.py",
        "scripts/freeze_frame_projection_e012_a14_v1.py",
        "scripts/audit_task_bank_e012_a21_v1.py",
        "scripts/freeze_precontact_audit_e012_a21_v1.py",
        "scripts/audit_paired_truth_e012_a16_v1.py",
        "scripts/freeze_paired_truth_audit_e012_a16_v1.py",
        "scripts/audit_nuisance_baselines_e012_a19_v1.py",
        "scripts/freeze_nuisance_audit_e012_a19_v1.py",
        "scripts/prepare_full_frame_lock_e012.py",
        "scripts/preflight_authority_e012.py",
        "scripts/run_observer_e012.py",
        "scripts/start_observer_e012.ps1",
        "scripts/stop_observer_e012.ps1",
        "scripts/score_full_frame_e012.py",
        "scripts/seal_model_contact_gate_e012.py",
        "scripts/freeze_inputs_e012.py",
        "amendments/bank-amendment-14.md",
        "amendments/bank-amendment-14.json",
        "amendments/bank-amendment-15.md",
        "amendments/bank-amendment-15.json",
        "amendments/bank-amendment-16.md",
        "amendments/bank-amendment-16.json",
        "amendments/bank-amendment-17.md",
        "amendments/bank-amendment-17.json",
        "amendments/bank-amendment-18.md",
        "amendments/bank-amendment-18.json",
        "amendments/bank-amendment-19.md",
        "amendments/bank-amendment-19.json",
        "amendments/bank-amendment-20.md",
        "amendments/bank-amendment-20.json",
        "amendments/bank-amendment-21.md",
        "amendments/bank-amendment-21.json",
        "bank/construction-01/precontact-audit-lock-a21-v1.json",
        "bank/construction-01/precontact-audit-lock-a20-v1.json",
        "bank/construction-01/paired-truth-audit-lock-a16-v1.json",
        "bank/construction-01/nuisance-audit-lock-a19-v1.json",
        "bank/construction-01/a14-design-lock-v1.json",
        "bank/construction-01/scored-check-run-lock-a14-v1.json",
        "bank/construction-01/frame-projection-lock-a14-v1.json",
        "bank/construction-01/label-finalization-lock-v1.json",
        "bank/construction-01/task-construction-input-manifest-v1.1.json",
        "bank/construction-01/repository-source-audit-v1.json",
        "bank/construction-01/scored-bank-a14/vault/precontact-audit-a14-v1.json",
        "bank/construction-01/scored-bank-a14/vault/paired-truth-audit-a16-v1.json",
        "bank/construction-01/scored-bank-a14/vault/nuisance-baselines-a19-v1.json",
        "bank/construction-01/scored-bank-a14/vault/task-source-fixtures-final-v3.json",
        "bank/construction-01/scored-bank-a14/vault/candidate-check-labels-final-v3.json",
        "bank/construction-01/scored-bank-a14/vault/candidate-check-results-precheck-v3.json",
        "bank/construction-01/scored-bank-a14/vault/label-finalization-report-v3.json",
        "bank/construction-01/scored-bank-a14/vault/task-source-fixtures-precheck-v3.json",
        "bank/construction-01/scored-bank-a14/observer-frames.json",
        "bank/construction-01/scored-bank-a14/vault/frame-truth-index.json",
        "bank/construction-01/scored-bank-a14/vault/presentation-receipts.json",
        "bank/construction-01/scored-bank-a14/attempts/precontact-audit-attempt-a14-01.json",
        "bank/construction-01/scored-bank-a14/attempts/precontact-audit-attempt-a20-01.json",
        "artifacts/runs/e012-20260926-frame-decomposition-01/attempts/full-frame-preparation-attempt-01.json",
        "artifacts/runs/e012-20260926-frame-decomposition-01/attempts/full-frame-preparation-attempt-02.json",
        "artifacts/runs/e012-20260926-frame-decomposition-01/attempts/full-frame-preparation-attempt-03.json",
        "artifacts/runs/e012-20260926-frame-decomposition-01/attempts/freeze-input-attempt-01.json",
        "artifacts/runs/e012-20260926-frame-decomposition-01/inputs/full-frame-lock.json",
        "artifacts/runs/e012-20260926-frame-decomposition-01/inputs/presentation-bindings.json",
        "artifacts/runs/e012-20260926-frame-decomposition-01/preflight/authority-cargo-test.log",
        "artifacts/runs/e012-20260926-frame-decomposition-01/preflight/authority-probe/input.json",
        "artifacts/runs/e012-20260926-frame-decomposition-01/preflight/authority-probe/result.json",
        "artifacts/runs/e012-20260926-frame-decomposition-01/preflight/authority-probe/action-ledger.bin",
        "inputs/e009-v5/e009-v5-bundle-lock.json",
        "inputs/e009-v5/e009-v5-thresholds.json",
        "inputs/e009-v5/e010-frozen-input-lock.json",
        "inputs/e009-v5/system-observer-v2.txt",
        "inputs/e009-v5/observer-output.v2.json",
        "inputs/e009-v5/chat-template-small.jinja",
        "inputs/e009-v5/chat-template-large.jinja",
        "inputs/authority/e011-authorize.exe",
        "inputs/authority/source/e011-runtime/Cargo.toml",
        "inputs/authority/source/e011-runtime/Cargo.lock",
        "inputs/authority/source/e011-runtime/src/lib.rs",
        "inputs/authority/source/e011-runtime/src/bin/e011-authorize.rs",
        "inputs/authority/source/e011-runtime/src/bin/e011-hash.rs",
        "inputs/authority/source/e011-runtime/src/bin/e011-presentation.rs",
        "inputs/authority/source/e011-runtime/tests/live_path.rs",
    ]
    required.extend(f"amendments/bank-amendment-{index:02d}.{suffix}" for index in range(14, 20) for suffix in ("md", "json"))
    local_entries = {item["path"]: item for item in (local_entry(path) for path in required)}
    for row in a21["files"]:
        local_entries[row["path"]] = local_entry(row["path"])
    local_entries["artifacts/runs/e012-20260926-frame-decomposition-01/vault/evaluation-labels.json"] = local_entry(
        "artifacts/runs/e012-20260926-frame-decomposition-01/vault/evaluation-labels.json"
    )

    source_tree_paths = [
        "bank/construction-01/task-harnesses-a14",
        "bank/construction-01/repositories/bytes",
        "bank/construction-01/repositories/clap",
        "bank/construction-01/repositories/serde",
        "inputs/authority/source",
    ]
    source_trees = []
    for relative in source_tree_paths:
        digest, count, total = tree_digest(ROOT / relative)
        source_trees.append({
            "path": relative,
            "sha256": digest,
            "file_count": count,
            "bytes": total,
        })

    model_by_role = {row["role"]: row for row in e010["models"]}
    external = []
    for name, path_text in MODEL_PATHS.items():
        path = Path(path_text)
        if not path.is_file():
            raise RuntimeError(f"required frozen model/runtime file is missing: {name}")
        role = "small" if name.startswith("small_") else "large"
        field = "runtime_sha256" if name.endswith("runtime") else "model_sha256"
        expected = model_by_role[role][field]
        actual = file_sha256(path)
        if actual != expected:
            raise RuntimeError(f"frozen {name} hash mismatch")
        external.append({
            "name": name,
            "path": path_text,
            "sha256": actual,
            "bytes": path.stat().st_size,
            "verified_before_freeze": True,
            "reverified_by_start_script": True,
        })

    frames = json.loads((RUN / "inputs/full-frame-lock.json").read_text(encoding="utf-8"))
    bindings = json.loads((RUN / "inputs/presentation-bindings.json").read_text(encoding="utf-8"))
    eval_path = RUN / "vault/evaluation-labels.json"
    if len(frames["frames"]) != 48 or len(bindings["bindings"]) != 48:
        raise RuntimeError("full-frame inputs are not complete")
    public_ids = {row["task_id"] for row in frames["frames"]}
    if len(public_ids) != 26:
        raise RuntimeError(f"expected paired public ID reuse across 26 IDs, got {len(public_ids)}")

    rdc = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_MODEL_CONTACT",
        "run_id": RUN_ID,
        "experiment": "R&D-C E012 Prospective Frame Decomposition",
        "phase": "Phase 3 frozen full-frame admission baseline only",
        "model_contact_authorized": True,
        "authorization_basis": "User instructed continuation of the frozen E012 program after precontact gates passed.",
        "frozen_claim": "No threshold fitting, prompts, models, observers, routing, authority, or candidate presentation may change.",
        "observer_identity": {
            "small_bundle_id": EXPECTED_ROLES["small"],
            "large_bundle_id": EXPECTED_ROLES["large"],
            "small_thresholds_milli": model_by_role["small"]["thresholds"],
            "large_thresholds_milli": model_by_role["large"]["thresholds"],
            "normalization": "percent-0-100-to-milli-x10-v1+line-endings-lf-v1",
            "reasoning_mode": "off",
            "maximum_output_tokens": 1024,
            "seed": 0,
            "temperature": 0,
            "top_p": 1,
            "context_tokens": 4096,
            "candidate_order": "producer order preserved and bound by E011 presentation receipts",
        },
        "precontact_gate": {
            "report_path": "bank/construction-01/scored-bank-a14/vault/precontact-audit-a14-v1.json",
            "report_state": precontact_report["state"],
            "tasks": precontact_report["task_count"],
            "families": precontact_report["family_count"],
            "repositories": precontact_report["repository_count"],
            "conditions": precontact_report["condition_count"],
            "frames": precontact_report["frame_count"],
            "receipt_replays": precontact_report["presentation_receipt_replays"],
        },
        "authority": {
            "implementation": "E011 producer-order runtime integration with E001/E002/E009 contracts",
            "binary_path": "inputs/authority/e011-authorize.exe",
            "compiled_target": AUTHORITY_TARGET,
            "compiled_to": "D:",
            "copied_and_tested_from": "C:",
            "producer_order_live_path_tests": 4,
            "synthetic_preflight": "AUTHORITY_PREFLIGHT_PASS_NO_MODEL_CONTACT",
            "ledger_idempotency": "stable action ID; unique effect once; deterministic replay",
        },
        "task_bank": {
            "candidate_tasks": 48,
            "paired_items": len({row["pair_id"] for row in json.loads(eval_path.read_text(encoding="utf-8"))["tasks"]}),
            "unique_public_task_ids": len(public_ids),
            "repository_ids": sorted({row["frame"]["repository_id"] for row in frames["frames"]}),
            "families": sorted({row["frame"]["task_family"] for row in frames["frames"]}),
            "full_frame_hash": file_sha256(RUN / "inputs/full-frame-lock.json"),
            "presentation_bindings_hash": file_sha256(RUN / "inputs/presentation-bindings.json"),
            "hidden_label_hash": file_sha256(eval_path),
            "hidden_labels_separated_from_model_payload": True,
        },
        "input_contract": {
            "same_full_frame_sent_to_each_observer": True,
            "frame_channels": ["E_t", "E_c.content", "E_x", "E_r", "E_p"],
            "no_interventions_in_this_phase": True,
            "no_development_fit_or_threshold_selection": True,
        },
        "local_files": sorted(local_entries.values(), key=lambda row: row["path"]),
        "evaluation_files": [
            local_entry("artifacts/runs/e012-20260926-frame-decomposition-01/vault/evaluation-labels.json"),
            local_entry("bank/construction-01/scored-bank-a14/vault/candidate-check-labels-final-v3.json"),
            local_entry("bank/construction-01/scored-bank-a14/vault/frame-truth-index.json"),
        ],
        "source_trees": source_trees,
        "external_files": external,
        "run_artifacts": {
            "full_frame_lock_sha256": file_sha256(RUN / "inputs/full-frame-lock.json"),
            "presentation_bindings_sha256": file_sha256(RUN / "inputs/presentation-bindings.json"),
            "evaluation_labels_sha256": file_sha256(eval_path),
        },
        "build_environment": {
            "cargo": subprocess.run(["cargo", "--version"], capture_output=True, text=True, check=True).stdout.strip(),
            "rustc": subprocess.run(["rustc", "--version"], capture_output=True, text=True, check=True).stdout.strip(),
            "target_directory": r"D:\rdc-e012-target\e012-authority-20260926",
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(rdc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    seal_value = {
        "schema_version": 1,
        "state": "SEALED_BEFORE_MODEL_CONTACT",
        "run_id": RUN_ID,
        "frozen_input_lock_sha256": file_sha256(TARGET),
        "local_file_count": len(rdc["local_files"]),
        "evaluation_file_count": len(rdc["evaluation_files"]),
        "source_tree_count": len(source_trees),
        "external_file_count": len(external),
        "model_contact_started": False,
    }
    SEAL.write_text(json.dumps(seal_value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": rdc["state"],
        "model_contact_authorized": rdc["model_contact_authorized"],
        "local_files": len(rdc["local_files"]),
        "source_trees": len(source_trees),
        "external_files": len(external),
        "lock_sha256": file_sha256(TARGET),
        "seal_sha256": file_sha256(SEAL),
    }, indent=2))


if __name__ == "__main__":
    main()
