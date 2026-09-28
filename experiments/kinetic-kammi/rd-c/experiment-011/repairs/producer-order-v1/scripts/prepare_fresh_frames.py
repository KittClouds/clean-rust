from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011")
E010 = Path(r"C:\rd-c\experiment-010")
BANK = ROOT / "inputs" / "fresh-integration-bank-v1c"
REPAIR = ROOT / "repairs" / "producer-order-v1"
RUN_ID = "e011-producer-order-integration-qual-01"
RUN = REPAIR / "artifacts" / "runs" / RUN_ID
TARGET = Path(r"D:\cargo-targets\rdc-e011-runtime-integration")
RUNTIME = REPAIR / "runtime-integration"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if "target" in path.parts or ".git" in path.parts:
            continue
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> None:
    if RUN.exists() and any(RUN.iterdir()):
        raise SystemExit(f"refusing to overwrite nonempty E011 run: {RUN}")
    freeze_path = BANK / "bank-freeze.json"
    frames_path = BANK / "frame-lock.json"
    labels_path = BANK / "sealed-labels.json"
    bank_freeze = read_json(freeze_path)
    if bank_freeze.get("state") != "FROZEN_BEFORE_MODEL_CONTACT":
        raise RuntimeError("fresh task bank is not frozen before model contact")
    if bank_freeze.get("frame_lock_sha256") != sha256(frames_path.read_bytes()):
        raise RuntimeError("fresh frame lock changed after bank freeze")
    if bank_freeze.get("sealed_labels_sha256") != sha256(labels_path.read_bytes()):
        raise RuntimeError("sealed completion labels changed after bank freeze")

    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(TARGET)
    subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--manifest-path",
            str(RUNTIME / "Cargo.toml"),
            "--bin",
            "e011-presentation",
            "--bin",
            "e011-authorize",
        ],
        cwd=RUNTIME,
        env=env,
        check=True,
    )
    presentation_bin = TARGET / "release" / "e011-presentation.exe"
    prepared_rows = []
    original_rows = read_json(frames_path)["frames"]
    for locked in original_rows:
        frame = locked["frame"]
        ordinals = locked["producer_ordinals"]
        options = frame["action_options"]
        if len(options) != len(ordinals) or ordinals != list(range(len(options))):
            raise RuntimeError(f"producer ordinals are missing or malformed for {frame['task_id']}")
        sequenced = [
            {
                "producer_ordinal": ordinal,
                **option,
            }
            for ordinal, option in zip(ordinals, options, strict=True)
        ]
        # Exercise the transport seam on every task; the model sees restored producer order.
        transport_order = sequenced[2:] + sequenced[:2] if len(sequenced) > 2 else list(reversed(sequenced))
        input_path = RUN / "work" / f"{frame['task_id']}-prepare-input.json"
        output_path = RUN / "work" / f"{frame['task_id']}-prepared.json"
        write_json(input_path, {"task_digest_hex": locked["blake3"], "options": transport_order})
        subprocess.run(
            [str(presentation_bin), str(input_path), str(output_path)],
            cwd=RUNTIME,
            check=True,
            capture_output=True,
            text=True,
        )
        prepared = read_json(output_path)
        restored_options = [
            {key: value for key, value in option.items() if key != "producer_ordinal"}
            for option in prepared["ordered_options"]
        ]
        if restored_options != options:
            raise RuntimeError(f"transport order was not restored exactly for {frame['task_id']}")
        observer_frame = dict(frame)
        observer_frame["action_options"] = restored_options
        if observer_frame != frame:
            raise RuntimeError(f"presentation preparation changed the observer frame for {frame['task_id']}")
        prepared_rows.append(
            {
                "task_id": frame["task_id"],
                "repository_id": locked["repository_id"],
                "frame_blake3": locked["blake3"],
                "observer_frame": observer_frame,
                "serialized_frame_sha256": sha256(
                    json.dumps(observer_frame, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                ),
                "presentation": {
                    "schema_id": prepared["schema_id"],
                    "task_digest_hex": prepared["task_digest_hex"],
                    "request_id_hex": prepared["request_id_hex"],
                    "receipt_hex": prepared["receipt_hex"],
                    "receipt_digest_hex": prepared["receipt_digest_hex"],
                    "producer_ordinals": ordinals,
                    "transport_permuted_before_restore": True,
                },
            }
        )

    prepared_lock_path = RUN / "prepared-frame-lock.json"
    write_json(prepared_lock_path, {"schema_version": 1, "rows": prepared_rows})
    prompt_path = E010 / "prompts" / "system-observer-v2.txt"
    schema_path = E010 / "schemas" / "observer-output.v2.json"
    bundle_path = E010 / "models" / "bundle-lineage" / "v5-final" / "bundle-lock.json"
    threshold_path = E010 / "models" / "bundle-lineage" / "selected-thresholds-v5.json"
    e010_lock_path = E010 / "artifacts" / "runs" / "e010-20260925-cross-repo-01" / "frozen-input-lock.json"
    thresholds = read_json(threshold_path)["selected_thresholds"]
    if thresholds != bank_freeze["thresholds"]:
        raise RuntimeError("fresh bank threshold copy differs from the frozen E009 v5 thresholds")
    e010_lock = read_json(e010_lock_path)
    if e010_lock.get("sha256", {}).get("bundle_lock") != sha256(bundle_path.read_bytes()):
        raise RuntimeError("v5 observer bundle lock no longer matches E010's frozen input lock")
    if e010_lock.get("sha256", {}).get("system_prompt") != sha256(prompt_path.read_bytes()):
        raise RuntimeError("v5 observer prompt no longer matches E010's frozen input lock")
    if e010_lock.get("sha256", {}).get("output_schema") != sha256(schema_path.read_bytes()):
        raise RuntimeError("v5 output schema no longer matches E010's frozen input lock")

    model_records = [
        {
            "role": item["role"],
            "bundle_id": item["bundle_id"],
            "bundle_blake3": item["bundle_blake3"],
            "bundle_lock_sha256": item["bundle_lock_sha256"],
            "bundle_lock_path": item["bundle_lock_path"],
            "server_alias": item["server_alias"],
            "model_sha256": item["model_sha256"],
            "runtime_sha256": item["runtime_sha256"],
            "chat_template_path": item["chat_template_path"],
        }
        for item in e010_lock["models"]
    ]
    frozen_input = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_MODEL_CONTACT",
        "run_id": RUN_ID,
        "bank_id": bank_freeze["bank_id"],
        "sha256": {
            "frame_lock": sha256(frames_path.read_bytes()),
            "prepared_frame_lock": sha256(prepared_lock_path.read_bytes()),
            "bank_freeze": sha256(freeze_path.read_bytes()),
            "sealed_labels": sha256(labels_path.read_bytes()),
            "system_prompt": sha256(prompt_path.read_bytes()),
            "output_schema": sha256(schema_path.read_bytes()),
            "bundle_lock": sha256(bundle_path.read_bytes()),
            "thresholds": sha256(threshold_path.read_bytes()),
            "runtime_integration_source_tree": source_tree_hash(RUNTIME),
            "runtime_contract_candidate_presentation": sha256(
                (ROOT.parent / "rdc-runtime-contracts-v1" / "src" / "candidate_presentation.rs").read_bytes()
            ),
        },
        "bundle_lock_path": str(bundle_path),
        "prompt_path": str(prompt_path),
        "schema_path": str(schema_path),
        "thresholds": thresholds,
        "normalization_contract": "percent-0-100-to-milli-x10-v1+line-endings-lf-v1",
        "reasoning_mode": "off",
        "maximum_output_tokens": 1024,
        "models": model_records,
        "routing": "small-then-large-on-abstention at frozen E009 v5 thresholds",
        "response_binding": "request and response envelopes carry request ID and receipt digest; observer prompt remains unchanged",
        "labels_opened": False,
    }
    write_json(RUN / "frozen-input-lock.json", frozen_input)
    write_json(
        RUN / "presentation-preparation-report.json",
        {
            "schema_version": 1,
            "run_id": RUN_ID,
            "bank_id": bank_freeze["bank_id"],
            "task_count": len(prepared_rows),
            "transport_permuted_and_restored": sum(
                row["presentation"]["transport_permuted_before_restore"] for row in prepared_rows
            ),
            "exact_original_frame_reconstructions": len(prepared_rows),
            "frame_lock_sha256": frozen_input["sha256"]["frame_lock"],
            "prepared_frame_lock_sha256": frozen_input["sha256"]["prepared_frame_lock"],
        },
    )
    print(json.dumps({"run": str(RUN), "tasks": len(prepared_rows), "state": frozen_input["state"]}, indent=2))


if __name__ == "__main__":
    main()
