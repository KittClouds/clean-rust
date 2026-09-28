from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
LINEAGE = ROOT / "models" / "bundle-lineage"
TARGET = r"D:\cargo-targets\rdc-e009"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def manifests(
    *,
    suffix: str,
    output_tokens: int,
    reasoning_mode: str,
    minimum_applicability: int,
    maximum_abstention: int,
    output_schema_version: int = 1,
    score_normalization: str | None = None,
) -> list[dict]:
    base = load_json(ROOT / "artifacts" / "runs" / "e009-20260925-pilot-01" / "protocol-source" / "models" / "bundle-input.json")["bundles"]
    templates = {
        item["role"]: item
        for item in load_json(ROOT / "models" / "chat-templates" / "capture-receipt.json")["templates"]
    }
    prompt_bytes = (ROOT / "prompts" / "system-observer-v1.txt").read_bytes()
    schema_bytes = (ROOT / "schemas" / "observer-output.v1.json").read_bytes()
    if output_schema_version == 2:
        prompt_bytes = (ROOT / "prompts" / "system-observer-v2.txt").read_bytes()
        schema_bytes = (ROOT / "schemas" / "observer-output.v2.json").read_bytes()
    prompt_sha = sha256(prompt_bytes)
    schema_sha = sha256(schema_bytes)
    representation_sha = (
        sha256(prompt_bytes + b"\0" + schema_bytes)
        if output_schema_version == 2
        else None
    )
    output = []
    for item in base:
        manifest = dict(item)
        old_id = manifest["bundle_id"]
        stem = old_id.removesuffix("-v1")
        manifest.update(
            {
                "bundle_schema_version": 2,
                "bundle_id": f"{stem}-{suffix}",
                "output_schema": f"rdc-coding-observer-output.v{output_schema_version}",
                "typed_head_schema_sha256": schema_sha,
                "typed_head_id": (
                    "json-schema-output-head-v2"
                    if output_schema_version == 2
                    else manifest["typed_head_id"]
                ),
                "representation_surface_id": (
                    "system-observer-v2+canonical-task-frame-v1"
                    if output_schema_version == 2
                    else manifest["representation_surface_id"]
                ),
                "representation_surface_sha256": (
                    representation_sha
                    if representation_sha is not None
                    else manifest["representation_surface_sha256"]
                ),
                "normalization_contract": (
                    score_normalization
                    if score_normalization is not None
                    else "line-endings-lf-v1"
                ),
                "maximum_output_tokens": output_tokens,
                "chat_template_id": templates["small" if stem.startswith("minicpm") else "large"]["chat_template_id"],
                "chat_template_sha256": templates["small" if stem.startswith("minicpm") else "large"]["chat_template_sha256"],
                "reasoning_mode": reasoning_mode,
                "system_prompt_sha256": prompt_sha,
                "output_schema_sha256": schema_sha,
                "minimum_applicability_milli": minimum_applicability,
                "maximum_abstention_milli": maximum_abstention,
            }
        )
        output.append(manifest)
    return output


def lock_group(name: str, bundle_manifests: list[dict]) -> None:
    directory = LINEAGE / name
    directory.mkdir(parents=True, exist_ok=True)
    input_path = directory / "bundle-input.json"
    lock_path = directory / "bundle-lock.json"
    write_json(input_path, {"bundles": bundle_manifests})
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = TARGET
    subprocess.run(
        [
            "cargo", "run", "--quiet", "--manifest-path", str(ROOT / "Cargo.toml"),
            "--bin", "e009-lock-bundles", "--", str(input_path), str(lock_path),
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )


def main() -> None:
    v2 = manifests(
        suffix="v2",
        output_tokens=1024,
        reasoning_mode="auto",
        minimum_applicability=700,
        maximum_abstention=600,
    )
    calibration = manifests(
        suffix="v3-calibration",
        output_tokens=1024,
        reasoning_mode="off",
        minimum_applicability=700,
        maximum_abstention=600,
    )
    lock_group("v2-attempt-reconstruction", v2)
    lock_group("v3-calibration", calibration)

    calibration_v5 = manifests(
        suffix="v5-calibration",
        output_tokens=1024,
        reasoning_mode="off",
        minimum_applicability=700,
        maximum_abstention=600,
        output_schema_version=2,
        score_normalization="percent-0-100-to-milli-x10-v1+line-endings-lf-v1",
    )
    lock_group("v5-calibration", calibration_v5)

    selected_path = LINEAGE / "selected-thresholds.json"
    if selected_path.is_file():
        selected = load_json(selected_path)
        values = selected["selected_thresholds"]
        final = manifests(
            suffix="v3",
            output_tokens=1024,
            reasoning_mode="off",
            minimum_applicability=int(values["minimum_applicability_milli"]),
            maximum_abstention=int(values["maximum_abstention_milli"]),
        )
        lock_group("v3-final", final)

    selected_v5_path = LINEAGE / "selected-thresholds-v5.json"
    if selected_v5_path.is_file():
        selected_v5 = load_json(selected_v5_path)
        values = selected_v5["selected_thresholds"]
        final_v5 = manifests(
            suffix="v5",
            output_tokens=1024,
            reasoning_mode="off",
            minimum_applicability=int(values["minimum_applicability_milli"]),
            maximum_abstention=int(values["maximum_abstention_milli"]),
            output_schema_version=2,
            score_normalization="percent-0-100-to-milli-x10-v1+line-endings-lf-v1",
        )
        lock_group("v5-final", final_v5)

    v1_lock = ROOT / "models" / "bundle-lock.json"
    original_lock = ROOT / "artifacts" / "runs" / "e009-20260925-pilot-01" / "protocol-source" / "models" / "bundle-lock.json"
    original_input = ROOT / "artifacts" / "runs" / "e009-20260925-pilot-01" / "protocol-source" / "models" / "bundle-input.json"
    original_frozen = load_json(ROOT / "artifacts" / "runs" / "e009-20260925-pilot-01" / "frozen-input-lock.json")
    checks = {
        "restored_v1_lock_sha256": sha256(v1_lock.read_bytes()),
        "archived_v1_lock_sha256": sha256(original_lock.read_bytes()),
        "restored_v1_input_sha256": sha256((ROOT / "models" / "bundle-input.json").read_bytes()),
        "archived_v1_input_sha256": sha256(original_input.read_bytes()),
        "frozen_pilot_v1_lock_sha256": original_frozen["sha256"]["bundle_lock"],
    }
    if checks["restored_v1_lock_sha256"] != checks["frozen_pilot_v1_lock_sha256"]:
        raise SystemExit(f"restored v1 bundle lock does not match frozen pilot: {checks}")
    if checks["restored_v1_lock_sha256"] != checks["archived_v1_lock_sha256"] or checks["restored_v1_input_sha256"] != checks["archived_v1_input_sha256"]:
        raise SystemExit(f"restored v1 manifest does not match archived pre-contact bytes: {checks}")
    write_json(LINEAGE / "v1-byte-identity-check.json", checks)
    print("locked v2 attempt reconstruction and v3 calibration bundles; v1 restored byte-for-byte")


if __name__ == "__main__":
    main()
