from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(r"C:\rd-c\experiment-011")
E010 = Path(r"C:\rd-c\experiment-010")
REPAIR = ROOT / "repairs" / "producer-order-v1"
BANK = ROOT / "inputs" / "fresh-integration-bank-v1c"
RUN = REPAIR / "artifacts" / "runs" / "e011-producer-order-integration-qual-01"
RUNTIME = REPAIR / "runtime-integration"
CONTRACT = Path(r"C:\rd-c\rdc-runtime-contracts-v1")
AUTHORIZER = Path(r"D:\cargo-targets\rdc-e011-runtime-integration\release\e011-authorize.exe")
SCORER = REPAIR / "scripts" / "score_fresh_qualification.py"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def tree_hash(directory: Path, *, skip_build_dirs: bool = False) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if skip_build_dirs and ("target" in path.parts or ".git" in path.parts):
            continue
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def main() -> None:
    frozen = read_json(RUN / "frozen-input-lock.json")
    replay = read_json(RUN / "score-replay-input-lock.json")
    bank_freeze = read_json(BANK / "bank-freeze.json")
    prepared = read_json(RUN / "prepared-frame-lock.json")
    prepared_report = read_json(RUN / "presentation-preparation-report.json")
    summary = read_json(RUN / "qualification-summary.json")
    smoke = read_json(RUN / "live-path-smoke-report.json")
    lanes = read_json(RUN / "lane-results.json")["results"]

    require(frozen["state"] == "FROZEN_BEFORE_MODEL_CONTACT", "input lock is not frozen")
    require(frozen["labels_opened"] is False, "input-lock label boundary changed")
    require(bank_freeze["state"] == "FROZEN_BEFORE_MODEL_CONTACT", "bank is not precontact frozen")
    require(sha256_file(BANK / "frame-lock.json") == frozen["sha256"]["frame_lock"], "frame lock hash")
    require(sha256_file(BANK / "bank-freeze.json") == frozen["sha256"]["bank_freeze"], "bank freeze hash")
    require(sha256_file(BANK / "sealed-labels.json") == frozen["sha256"]["sealed_labels"], "sealed label hash")
    require(sha256_file(RUN / "prepared-frame-lock.json") == frozen["sha256"]["prepared_frame_lock"], "prepared lock hash")

    prompt = E010 / "prompts" / "system-observer-v2.txt"
    schema = E010 / "schemas" / "observer-output.v2.json"
    bundle = E010 / "models" / "bundle-lineage" / "v5-final" / "bundle-lock.json"
    thresholds = E010 / "models" / "bundle-lineage" / "selected-thresholds-v5.json"
    require(sha256_file(prompt) == frozen["sha256"]["system_prompt"], "frozen prompt hash")
    require(sha256_file(schema) == frozen["sha256"]["output_schema"], "frozen schema hash")
    require(sha256_file(bundle) == frozen["sha256"]["bundle_lock"], "frozen bundle hash")
    require(sha256_file(thresholds) == frozen["sha256"]["thresholds"], "frozen threshold hash")
    require(tree_hash(RUNTIME, skip_build_dirs=True) == frozen["sha256"]["runtime_integration_source_tree"], "runtime source tree hash")
    require(
        sha256_file(CONTRACT / "src" / "candidate_presentation.rs")
        == frozen["sha256"]["runtime_contract_candidate_presentation"],
        "candidate-presentation contract hash",
    )

    require(replay["state"] == "SCORED_AFTER_MODEL_CONTACT", "score replay lock state")
    require(sha256_file(RUN / "frozen-input-lock.json") == replay["frozen_input_lock_sha256"], "scored input-lock hash")
    require(sha256_file(RUN / "prepared-frame-lock.json") == replay["prepared_frame_lock_sha256"], "scored prepared-lock hash")
    require(sha256_file(BANK / "sealed-labels.json") == replay["sealed_labels_sha256"], "scored label hash")
    require(sha256_file(BANK / "task-manifest.json") == replay["task_manifest_sha256"], "scored task-manifest hash")
    require(tree_hash(RUN / "observations" / "small") == replay["small_observer_outputs_sha256"], "small output tree hash")
    require(tree_hash(RUN / "observations" / "large") == replay["large_observer_outputs_sha256"], "large output tree hash")
    require(tree_hash(RUN / "task-checks") == replay["candidate_test_result_tree_sha256"], "completion-test tree hash")
    require(sha256_file(SCORER) == replay["scorer_sha256"], "scorer source hash")
    require(sha256_file(AUTHORIZER) == replay["runtime_authorizer_sha256"], "runtime authorizer hash")
    require(prepared_report["transport_permuted_and_restored"] == 4, "not all transport cases restored")
    require(prepared_report["exact_original_frame_reconstructions"] == 4, "not all prepared frames matched")
    require(len(prepared["rows"]) == 4, "unexpected prepared frame count")

    by_task = {row["task_id"]: row for row in prepared["rows"]}
    require(len(by_task) == 4, "duplicate prepared task IDs")
    model_by_role = {item["role"]: item for item in frozen["models"]}
    for task_id, row in by_task.items():
        presentation = row["presentation"]
        require(presentation["transport_permuted_before_restore"] is True, f"transport case missing: {task_id}")
        require(presentation["producer_ordinals"] == [0, 1, 2, 3], f"producer sequence changed: {task_id}")
        for role in ("small", "large"):
            observed = read_json(RUN / "observations" / role / f"{task_id}.json")
            request = observed["observer_rpc_request"]
            response = observed["observer_rpc_response"]
            observer_request = observed["request"]
            messages = observer_request["messages"]
            require(observed["http_status"] == 200, f"observer response missing: {role}/{task_id}")
            require(observed["frame_blake3"] == row["frame_blake3"], f"observer frame mismatch: {role}/{task_id}")
            require(observed["serialized_frame_sha256"] == row["serialized_frame_sha256"], f"serialized frame hash mismatch: {role}/{task_id}")
            require(sha256_bytes(messages[0]["content"].encode("utf-8")) == frozen["sha256"]["system_prompt"], f"observer prompt drift: {role}/{task_id}")
            require(messages[1]["content"] == json.dumps(row["observer_frame"], ensure_ascii=False, separators=(",", ":")), f"observer frame bytes differ: {role}/{task_id}")
            require(observer_request["model"] == model_by_role[role]["server_alias"], f"observer bundle alias drift: {role}/{task_id}")
            require(observed["bundle_id"] == model_by_role[role]["bundle_id"], f"observer bundle ID drift: {role}/{task_id}")
            require(observed["system_prompt_sha256"] == frozen["sha256"]["system_prompt"], f"recorded prompt hash drift: {role}/{task_id}")
            require(observed["output_schema_sha256"] == frozen["sha256"]["output_schema"], f"recorded schema hash drift: {role}/{task_id}")
            require(observed["reasoning_mode"] == "off" and observed["maximum_output_tokens"] == 1024, f"observer runtime setting drift: {role}/{task_id}")
            require(request["request_id_hex"] == presentation["request_id_hex"], f"request ID mismatch: {role}/{task_id}")
            require(response["request_id_hex"] == presentation["request_id_hex"], f"response ID mismatch: {role}/{task_id}")
            require(request["receipt_digest_hex"] == presentation["receipt_digest_hex"], f"request receipt mismatch: {role}/{task_id}")
            require(response["receipt_digest_hex"] == presentation["receipt_digest_hex"], f"response receipt mismatch: {role}/{task_id}")

    require(len(lanes) == 12, "expected four tasks in each of three lanes")
    for row in lanes:
        task_id = row["task_id"]
        authority = row["authority"]
        presentation = by_task[task_id]["presentation"]
        require(authority["presentation_verified"] is True, f"receipt not verified: {row['lane']}/{task_id}")
        require(authority["request_id_hex"] == presentation["request_id_hex"], f"authorization request mismatch: {row['lane']}/{task_id}")
        require(authority["receipt_digest_hex"] == presentation["receipt_digest_hex"], f"authorization receipt mismatch: {row['lane']}/{task_id}")
        require(authority["replay_state_identical"] is True, f"replay mismatch: {row['lane']}/{task_id}")
        require(authority["illegal_commits"] == 0, f"illegal commit: {row['lane']}/{task_id}")
        require(authority["duplicate_action_effects"] == 0, f"duplicate action effect: {row['lane']}/{task_id}")
        require(row["completion_check"]["passed"] is True, f"completion check failed: {row['lane']}/{task_id}")
        receipt_path = RUN / "receipts" / row["lane"] / f"{task_id}.json"
        require(read_json(receipt_path) == authority, f"standalone authority receipt drift: {row['lane']}/{task_id}")

    require(smoke["invariants"] == {"illegal_commits": 0, "duplicate_effects": 0, "all_replay_identical": True}, "smoke invariants")
    require(all(item["passed"] for item in summary["repository_level_gates"].values()), "repository gate failure")
    require(summary["all_repository_gates_passed"] is True, "overall gate failure")
    print(json.dumps({
        "verified": True,
        "frozen_hashes": 10,
        "observer_bindings": 8,
        "authorized_lane_receipts": len(lanes),
        "integration_cases": 4,
        "repository_gates": summary["repository_level_gates"],
    }, indent=2))


if __name__ == "__main__":
    main()
