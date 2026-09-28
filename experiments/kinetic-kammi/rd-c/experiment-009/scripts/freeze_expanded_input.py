from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
RUN_ID = "e009-20260925-expanded-01"
RUN = ROOT / "artifacts" / "runs" / RUN_ID


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
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


def model_records(lock_path: Path, capture: dict) -> list[dict]:
    lock_bytes = lock_path.read_bytes()
    lock = json.loads(lock_bytes)
    template_by_role = {item["role"]: item for item in capture["templates"]}
    output = []
    for item in lock["bundles"]:
        manifest = item["manifest"]
        role = "small" if manifest["backbone_name"].startswith("MiniCPM") else "large"
        template = template_by_role[role]
        expected_prefix = "minicpm" if role == "small" else "ternary-bonsai"
        if not manifest["bundle_id"].startswith(expected_prefix):
            raise SystemExit(f"unexpected bundle role assignment: {manifest['bundle_id']}")
        if manifest.get("chat_template_sha256") != template["chat_template_sha256"]:
            raise SystemExit(f"bundle template hash differs from captured runtime template: {role}")
        output.append(
            {
                "role": role,
                "bundle_id": manifest["bundle_id"],
                "bundle_blake3": item["blake3"],
                "bundle_lock_path": str(lock_path.relative_to(ROOT)).replace("\\", "/"),
                "bundle_lock_sha256": sha256(lock_bytes),
                "backbone_sha256": manifest["backbone_sha256"],
                "runtime_sha256": manifest["runtime_sha256"],
                "reasoning_mode": manifest["reasoning_mode"],
                "maximum_output_tokens": manifest["maximum_output_tokens"],
                "minimum_applicability_milli": manifest["minimum_applicability_milli"],
                "maximum_abstention_milli": manifest["maximum_abstention_milli"],
                "chat_template_id": manifest["chat_template_id"],
                "chat_template_sha256": manifest["chat_template_sha256"],
                "chat_template_path": str(Path(template["template_path"]).relative_to(ROOT)).replace("\\", "/"),
                "server_alias": (
                    f"e009-{role}-v5"
                    if "-v5" in manifest["bundle_id"]
                    else ("e009-small-v3" if role == "small" else "e009-large-v3")
                ),
            }
        )
    if {item["role"] for item in output} != {"small", "large"}:
        raise SystemExit("bundle lock must contain one small and one large observer")
    return output


def main() -> None:
    global RUN_ID, RUN
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("development", "heldout"))
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--lock-suffix", default="")
    parser.add_argument("--heldout-bank", default="heldout-bank-v5")
    parser.add_argument("--split-manifest", default="split-manifest.json")
    args = parser.parse_args()
    if args.lock_suffix and not args.lock_suffix.replace("-", "").isalnum():
        raise SystemExit("lock suffix must contain only letters, digits, and hyphens")

    RUN_ID = args.run_id
    RUN = ROOT / "artifacts" / "runs" / RUN_ID

    split_path = ROOT / "tasks" / "expanded" / args.split_manifest
    split = read_json(split_path)
    dev_root = ROOT / "tasks" / "expanded" / "dev-bank-v4"
    heldout_root = ROOT / "tasks" / "expanded" / args.heldout_bank
    selected_path = ROOT / "models" / "bundle-lineage" / "selected-thresholds-v5.json"
    if args.stage == "development":
        bank_root = dev_root
        lock_path = ROOT / "models" / "bundle-lineage" / "v5-calibration" / "bundle-lock.json"
        lock_suffix = f"-{args.lock_suffix}" if args.lock_suffix else ""
        output_path = RUN / f"frozen-development-input-lock{lock_suffix}.json"
        stage = "DEVELOPMENT_SHADOW_CALIBRATION"
        if selected_path.exists():
            raise SystemExit("development lock must be frozen before threshold selection")
        threshold_contract = {
            "method": "full integer grid evaluated on development tasks only",
            "minimum_applicability_milli": {"min": 700, "max": 1000, "step": 1},
            "maximum_abstention_milli": {"min": 0, "max": 1000, "step": 1},
            "authority_execution_guard_milli": 700,
            "objective": [
                "maximize hybrid completions",
                "minimize large fallback calls",
                "minimize input plus generated tokens",
                "minimize measured observer wall time",
                "prefer higher minimum applicability",
                "prefer lower maximum abstention",
            ],
        }
    else:
        if not selected_path.is_file():
            raise SystemExit("held-out lock requires the frozen development threshold choice")
        bank_root = heldout_root
        lock_path = ROOT / "models" / "bundle-lineage" / "v5-final" / "bundle-lock.json"
        lock_suffix = f"-{args.lock_suffix}" if args.lock_suffix else ""
        output_path = RUN / f"frozen-heldout-input-lock{lock_suffix}.json"
        stage = "HELDOUT_PAIRED_LANES"
        selected = read_json(selected_path)
        threshold_contract = {
            "method": "frozen development thresholds",
            "selected_thresholds": selected["selected_thresholds"],
            "development_selection_sha256": sha256(selected_path.read_bytes()),
        }

    if output_path.exists():
        raise SystemExit(f"refusing to overwrite frozen {args.stage} input lock: {output_path}")
    capture_path = ROOT / "models" / "chat-templates" / "capture-receipt.json"
    capture = read_json(capture_path)
    prompt_path = ROOT / "prompts" / "system-observer-v2.txt"
    schema_path = ROOT / "schemas" / "observer-output.v2.json"
    model_data = model_records(lock_path, capture)
    expected_role_files = {
        role: {
            "runtime_props_sha256": sha256((RUN / role / "runtime-props.json").read_bytes()),
            "captured_template_sha256": next(item["chat_template_sha256"] for item in capture["templates"] if item["role"] == role),
        }
        for role in ("small", "large")
    }

    dev_frame_path = dev_root / "frame-lock.json"
    heldout_frame_path = heldout_root / "frame-lock.json"
    candidate_authority = read_json(ROOT / "artifacts" / "runs" / "e009-20260925-pilot-01" / "frozen-input-lock.json")["authority_dependencies"]
    base_lock = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "phase": stage,
        "state": "FROZEN_BEFORE_MODEL_CONTACT",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "task_bank": {
            "selection": split["selection_method"],
            "development_families": split["development"]["families"],
            "heldout_families": split["heldout"]["families"],
            "development_task_count": len(split["development"]["task_ids"]),
            "heldout_task_count": len(split["heldout"]["task_ids"]),
            "heldout_bank": args.heldout_bank,
            "heldout_unit": (
                f"{len(split['heldout']['families'])} fresh task families within the same product repository; "
                "not a repository holdout"
            ),
            "heldout_bank_previously_scored_in": (
                "e009-20260925-expanded-01" if args.heldout_bank == "heldout-bank-v5" else None
            ),
            "heldout_promotion_eligible": args.heldout_bank != "heldout-bank-v5",
            "previously_scored_pilot_families_excluded": split["previously_scored_pilot_families_excluded"],
            "previously_scored_heldout_families_excluded": split.get("previously_scored_heldout_families_excluded", []),
            "labels_are_scoring_only": True,
            "development_labels_sha256": split["development"]["label_file_sha256"],
            "heldout_labels_sha256": split["heldout"]["label_file_sha256"],
        },
        "contracts": {
            "authority": "E002 compiled authority and action simulator",
            "runtime_contracts": "rdc-runtime-contracts-v1",
            "runtime_authority": "observer proposes; deterministic authority owns state and action authorization",
            "normalization": "percent-0-100-to-milli-x10-v1+line-endings-lf-v1",
            "paid_inspection_default": "disabled",
            "lanes": ["hand-written", "small", "small-then-large-on-abstention", "always-large"],
        },
        "authority_dependencies": candidate_authority,
        "models": model_data,
        "threshold_contract": threshold_contract,
        "runtime_environment": {
            "inference": "local loopback only",
            "hardware": "RTX 3080 12GB; serial observer services",
            "small_loopback_port": 18089,
            "large_loopback_port": 18090,
            "small_target_path": r"D:\cargo-targets\rdc-e009-expanded\dev",
            "completion_target_path": str(TARGET := Path(r"D:\cargo-targets\rdc-e009-expanded\scoring")),
            "authority_target_path": r"D:\cargo-targets\rdc-e009",
            "billed_api_usd": 0,
            "cost_proxy": "input/generated tokens and measured wall time; energy/hardware-dollar cost not measured",
        },
        "sha256": {
            "system_prompt": sha256(prompt_path.read_bytes()),
            "output_schema": sha256(schema_path.read_bytes()),
            "split_manifest": sha256(split_path.read_bytes()),
            "dev_frame_lock": sha256(dev_frame_path.read_bytes()),
            "heldout_frame_lock": sha256(heldout_frame_path.read_bytes()),
            "dev_candidate_lock": sha256((dev_root / "candidate-lock.json").read_bytes()),
            "heldout_candidate_lock": sha256((heldout_root / "candidate-lock.json").read_bytes()),
            "dev_bank_tree": tree_hash(dev_root),
            "heldout_bank_tree": tree_hash(heldout_root),
            "dev_labels": sha256((dev_root / "sealed-labels.json").read_bytes()),
            "heldout_labels": sha256((heldout_root / "sealed-labels.json").read_bytes()),
            "bundle_lock": sha256(lock_path.read_bytes()),
            "v1_original_bundle_lock": split.get("v1_original_bundle_lock_sha256", sha256((ROOT / "models" / "bundle-lock.json").read_bytes())),
            "bundle_lineage_record": sha256((ROOT / "artifacts" / "provenance" / "e009-observer-bundle-lineage.md").read_bytes()),
            "chat_template_capture_receipt": sha256(capture_path.read_bytes()),
            "small_runtime_props": expected_role_files["small"]["runtime_props_sha256"],
            "large_runtime_props": expected_role_files["large"]["runtime_props_sha256"],
            "small_chat_template": expected_role_files["small"]["captured_template_sha256"],
            "large_chat_template": expected_role_files["large"]["captured_template_sha256"],
            "e009_cargo_manifest": sha256((ROOT / "Cargo.toml").read_bytes()),
            "e009_cargo_lock": sha256((ROOT / "Cargo.lock").read_bytes()),
            "bundle_schema_source": sha256((ROOT / "src" / "bundle.rs").read_bytes()),
            "frame_schema_source": sha256((ROOT / "src" / "frame.rs").read_bytes()),
            "authorizer_source": sha256((ROOT / "src" / "bin" / "e009-authorize.rs").read_bytes()),
            "expanded_observer_runner": sha256((ROOT / "scripts" / "run_observer_expanded.py").read_bytes()),
            "expanded_evaluator": sha256((ROOT / "scripts" / "evaluate_expanded.py").read_bytes()),
            "expanded_lock_builder": sha256((ROOT / "scripts" / "freeze_expanded_input.py").read_bytes()),
            "server_starter": sha256((ROOT / "scripts" / "start_observer_server.ps1").read_bytes()),
            "server_stopper": sha256((ROOT / "scripts" / "stop_observer_server.ps1").read_bytes()),
        },
        "chat_template_runtime_properties": expected_role_files,
    }
    write_json(output_path, base_lock)
    status_path = RUN / "run-status.json"
    status = read_json(status_path) if status_path.exists() else {"schema_version": 1, "run_id": RUN_ID}
    status["phase"] = stage
    status["state"] = "FROZEN_BEFORE_MODEL_CONTACT"
    status[f"{args.stage}_input_lock_sha256"] = sha256(output_path.read_bytes())
    status["heldout_labels_opened"] = args.stage == "heldout" and False
    write_json(status_path, status)
    print(output_path)


if __name__ == "__main__":
    main()
