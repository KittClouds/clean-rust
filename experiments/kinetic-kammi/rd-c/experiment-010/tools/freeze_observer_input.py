from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "e010-20260925-cross-repo-01"
BANK = ROOT / "tasks" / "heldout-bank-v1"
RUN = ROOT / "artifacts" / "runs" / RUN_ID


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    bank_freeze = read_json(BANK / "bank-freeze.json")
    if bank_freeze.get("state") != "FROZEN_BEFORE_MODEL_CONTACT":
        raise SystemExit("task bank is not frozen before model contact")
    if bank_freeze.get("task_count") != 16 or bank_freeze.get("thresholds_fitted_on_e010") is not False:
        raise SystemExit("held-out bank or no-fit contract mismatch")
    frame_lock_path = BANK / "frame-lock.json"
    prompt_path = ROOT / "prompts" / "system-observer-v2.txt"
    schema_path = ROOT / "schemas" / "observer-output.v2.json"
    threshold_path = ROOT / "models" / "bundle-lineage" / "selected-thresholds-v5.json"
    bundle_path = ROOT / "models" / "bundle-lineage" / "v5-final" / "bundle-lock.json"
    capture_path = ROOT / "models" / "chat-templates" / "capture-receipt.json"
    thresholds = read_json(threshold_path)["selected_thresholds"]
    bundle_lock_bytes = bundle_path.read_bytes()
    bundle_lock = json.loads(bundle_lock_bytes)
    capture = read_json(capture_path)
    template_by_role = {item["role"]: Path(item["template_path"]).name for item in capture["templates"]}
    aliases = {"small": "e009-small-v5", "large": "e009-large-v5"}
    expected_models = []
    for role in ("small", "large"):
        candidates = [item for item in bundle_lock["bundles"] if item["manifest"]["backbone_name"].lower().startswith("minicpm" if role == "small" else "ternary")]
        if len(candidates) != 1:
            raise SystemExit(f"cannot identify exactly one frozen {role} bundle")
        item = candidates[0]
        manifest = item["manifest"]
        if (
            manifest["minimum_applicability_milli"] != thresholds["minimum_applicability_milli"]
            or manifest["maximum_abstention_milli"] != thresholds["maximum_abstention_milli"]
            or manifest["reasoning_mode"] != "off"
            or manifest["maximum_output_tokens"] != 1024
            or manifest["normalization_contract"] != "percent-0-100-to-milli-x10-v1+line-endings-lf-v1"
        ):
            raise SystemExit(f"frozen {role} bundle no longer matches E009 v5 settings")
        template_path = ROOT / "models" / "chat-templates" / template_by_role[role]
        if sha256(template_path.read_bytes()) != manifest["chat_template_sha256"]:
            raise SystemExit(f"captured {role} chat template hash mismatch")
        expected_models.append({
            "role": role,
            "bundle_id": manifest["bundle_id"],
            "bundle_blake3": item["blake3"],
            "bundle_lock_sha256": sha256(bundle_lock_bytes),
            "bundle_lock_path": "models/bundle-lineage/v5-final/bundle-lock.json",
            "server_alias": aliases[role],
            "chat_template_path": template_path.relative_to(ROOT).as_posix(),
            "model_sha256": manifest["backbone_sha256"],
            "runtime_sha256": manifest["runtime_sha256"],
            "thresholds": thresholds,
        })
    lock = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_MODEL_CONTACT",
        "run_id": RUN_ID,
        "selection_source": "E009 v5 frozen observer bundles and thresholds; no E010 fit",
        "sha256": {
            "heldout_frame_lock": sha256(frame_lock_path.read_bytes()),
            "system_prompt": sha256(prompt_path.read_bytes()),
            "output_schema": sha256(schema_path.read_bytes()),
            "thresholds": sha256(threshold_path.read_bytes()),
            "bundle_lock": sha256(bundle_lock_bytes),
            "bank_freeze": sha256((BANK / "bank-freeze.json").read_bytes()),
        },
        "models": expected_models,
        "routing": {"kind": "small-then-large-on-abstention", "minimum_applicability_milli": thresholds["minimum_applicability_milli"], "maximum_abstention_milli": thresholds["maximum_abstention_milli"]},
        "authority": {"source_root": r"C:\rd-c\experiment-009", "binary_name": "e009-authorize", "contract": "E002 standard compiled authority"},
    }
    output = RUN / "frozen-input-lock.json"
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing precontact lock: {output}")
    write_json(output, lock)
    write_json(ROOT / "artifacts" / "provenance" / "e010-precontact-lock.json", lock)
    print(json.dumps(lock, indent=2))


if __name__ == "__main__":
    main()
