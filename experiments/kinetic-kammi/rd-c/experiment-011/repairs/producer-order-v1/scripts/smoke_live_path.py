from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011")
REPAIR = ROOT / "repairs" / "producer-order-v1"
RUN = REPAIR / "artifacts" / "runs" / "e011-producer-order-integration-qual-01"
TARGET = Path(r"D:\cargo-targets\rdc-e011-runtime-integration")
PRESENTATION = TARGET / "release" / "e011-presentation.exe"
AUTHORIZER = TARGET / "release" / "e011-authorize.exe"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def call_prepare(name: str, task_digest: str, options: list[dict]) -> dict:
    input_path = RUN / "smoke" / f"{name}-prepare-input.json"
    output_path = RUN / "smoke" / f"{name}-prepared.json"
    write_json(input_path, {"task_digest_hex": task_digest, "options": options})
    subprocess.run([str(PRESENTATION), str(input_path), str(output_path)], check=True, capture_output=True, text=True)
    return read_json(output_path)


def call_authorizer(name: str, payload: dict) -> dict:
    input_path = RUN / "smoke" / f"{name}-authorization-input.json"
    output_path = RUN / "smoke" / f"{name}-authorization-result.json"
    write_json(input_path, payload)
    subprocess.run([str(AUTHORIZER), str(input_path), str(output_path)], check=True, capture_output=True, text=True)
    return read_json(output_path)


def options_with_ordinals(frame: dict) -> list[dict]:
    return [
        {"producer_ordinal": ordinal, **option}
        for ordinal, option in enumerate(frame["action_options"])
    ]


def authorization_payload(name: str, row: dict, prepared: dict, options: list[dict], output_id: int) -> dict:
    presentation = row["presentation"]
    return {
        "task_id": f"smoke-{name}",
        "frame_digest_hex": row["frame_blake3"],
        "request_id_hex": prepared["request_id_hex"],
        "response_request_id_hex": prepared["request_id_hex"],
        "request_receipt_digest_hex": prepared["receipt_digest_hex"],
        "response_receipt_digest_hex": prepared["receipt_digest_hex"],
        "presentation_receipt_hex": prepared["receipt_hex"],
        "action_ledger_path": str(RUN / "smoke" / f"{name}.actions.bin"),
        "ordered_options": options,
        "observer_output": {
            "action_choice": output_id,
            "applicability_milli": 990,
            "abstention_milli": 10,
        },
        "thresholds": {
            "minimum_applicability_milli": 850,
            "maximum_abstention_milli": 150,
        },
        "completion_check_passed": True,
    }


def main() -> None:
    rows = read_json(RUN / "prepared-frame-lock.json")["rows"]
    row = rows[0]
    frame = row["observer_frame"]
    ordered = options_with_ordinals(frame)
    normal = call_prepare("normal", row["frame_blake3"], ordered)
    normal_options = normal["ordered_options"]

    # The preparation report already exercises a deterministic transport shuffle in the real adapter.
    report = read_json(RUN / "presentation-preparation-report.json")
    if report["transport_permuted_and_restored"] != report["task_count"]:
        raise RuntimeError("not every task passed transport-order restoration")
    normal_result = call_authorizer(
        "normal",
        authorization_payload("normal", row, normal, normal_options, normal_options[0]["action"]["id"]),
    )
    if not normal_result["presentation_verified"] or not normal_result["replay_state_identical"]:
        raise RuntimeError("normal E011 authorization path failed receipt or replay verification")

    mutated = list(normal_options)
    mutated[0], mutated[1] = mutated[1], mutated[0]
    mutation_result = call_authorizer(
        "mutation-after-receipt",
        authorization_payload("mutation-after-receipt", row, normal, mutated, mutated[0]["action"]["id"]),
    )
    if (
        mutation_result["presentation_verified"]
        or mutation_result["safe_fallback"] != "ABSTAIN_AND_ABORT_ACTION"
        or mutation_result["action_choice"] is not None
        or mutation_result["unique_action_effects"] != 0
        or not mutation_result["replay_state_identical"]
    ):
        raise RuntimeError("post-receipt presentation mutation did not reject into the safe fallback")

    reversed_options = [
        {"producer_ordinal": len(ordered) - 1 - index, **option}
        for index, option in enumerate(frame["action_options"])
    ]
    other_presentation = call_prepare("alternate-presentation", row["frame_blake3"], reversed_options)
    replay_payload = authorization_payload(
        "wrong-presentation-replay", row, normal, normal_options, normal_options[0]["action"]["id"]
    )
    replay_payload["response_request_id_hex"] = other_presentation["request_id_hex"]
    replay_payload["response_receipt_digest_hex"] = other_presentation["receipt_digest_hex"]
    replay_result = call_authorizer("wrong-presentation-replay", replay_payload)
    if (
        replay_result["presentation_verified"]
        or replay_result["safe_fallback"] != "ABSTAIN_AND_ABORT_ACTION"
        or replay_result["action_choice"] is not None
        or replay_result["unique_action_effects"] != 0
        or not replay_result["replay_state_identical"]
    ):
        raise RuntimeError("observer response replay against another presentation was not rejected")

    results = {
        "schema_version": 1,
        "normal_producer_order": {
            "passed": bool(normal_result["presentation_verified"] and normal_result["unique_action_effects"] == 1),
            "presentation_verified": normal_result["presentation_verified"],
            "replay_state_identical": normal_result["replay_state_identical"],
            "unique_action_effects": normal_result["unique_action_effects"],
        },
        "transport_scramble_before_serialization": {
            "passed": report["exact_original_frame_reconstructions"] == report["task_count"],
            "tasks_restored": report["exact_original_frame_reconstructions"],
            "tasks_total": report["task_count"],
        },
        "mutation_after_receipt": {
            "passed": True,
            "rejection": mutation_result["presentation_rejection"],
            "safe_fallback": mutation_result["safe_fallback"],
            "action_effects": mutation_result["unique_action_effects"],
        },
        "response_replay_wrong_presentation": {
            "passed": True,
            "rejection": replay_result["presentation_rejection"],
            "safe_fallback": replay_result["safe_fallback"],
            "action_effects": replay_result["unique_action_effects"],
        },
        "invariants": {
            "illegal_commits": normal_result["illegal_commits"] + mutation_result["illegal_commits"] + replay_result["illegal_commits"],
            "duplicate_effects": normal_result["duplicate_action_effects"] + mutation_result["duplicate_action_effects"] + replay_result["duplicate_action_effects"],
            "all_replay_identical": all(result["replay_state_identical"] for result in (normal_result, mutation_result, replay_result)),
        },
    }
    if not all(results[key]["passed"] for key in (
        "normal_producer_order",
        "transport_scramble_before_serialization",
        "mutation_after_receipt",
        "response_replay_wrong_presentation",
    )):
        raise RuntimeError("one or more E011 live-path integration cases failed")
    write_json(RUN / "live-path-smoke-report.json", results)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
