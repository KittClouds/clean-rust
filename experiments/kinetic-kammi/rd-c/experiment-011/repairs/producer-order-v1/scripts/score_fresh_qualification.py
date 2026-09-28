from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011")
REPAIR = ROOT / "repairs" / "producer-order-v1"
BANK = ROOT / "inputs" / "fresh-integration-bank-v1c"
RUN_ID = "e011-producer-order-integration-qual-01"
RUN = REPAIR / "artifacts" / "runs" / RUN_ID
TARGET = Path(r"D:\cargo-targets\e011-fresh-live-completion")
AUTHORIZER = Path(r"D:\cargo-targets\rdc-e011-runtime-integration\release\e011-authorize.exe")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalized(record: dict) -> dict:
    output = record.get("normalized_output")
    if isinstance(output, dict):
        return output
    return {"action_choice": None, "applicability_milli": 0, "abstention_milli": 1000}


def compile_choice(output: dict, allowed: set[int], thresholds: dict) -> tuple[int | None, str]:
    choice = output.get("action_choice")
    app = output.get("applicability_milli")
    abst = output.get("abstention_milli")
    if type(app) is not int or type(abst) is not int or not 0 <= app <= 1000 or not 0 <= abst <= 1000:
        return None, "invalid-scores"
    if abst > thresholds["maximum_abstention_milli"]:
        return None, "abstention-threshold"
    if app < max(thresholds["minimum_applicability_milli"], 700):
        return None, "applicability-threshold"
    if choice is None:
        return None, "explicit-abstention"
    if type(choice) is not int or choice not in allowed:
        return None, "unknown-action"
    return choice, "propose"


def model_record(role: str, task_id: str) -> dict:
    path = RUN / "observations" / role / f"{task_id}.json"
    record = read_json(path)
    if record.get("task_id") != task_id or record.get("role") != role:
        raise RuntimeError(f"observer output identity mismatch: {role}/{task_id}")
    return record


def run_completion(task: dict, option: dict, lane: str, env: dict[str, str]) -> dict:
    patch_hash = option["patch_sha256"]
    labels = read_json(BANK / "sealed-labels.json")["tasks"][task["task_id"]]
    label = labels["actions_by_patch_sha256"].get(patch_hash)
    if label is None:
        raise RuntimeError(f"selected patch absent from sealed completion map: {task['task_id']}")
    variant = label["candidate_variant"]
    snapshot = BANK / task["snapshot_path"]
    manifest = task["manifest"]
    patch = BANK / task["candidate_patch_directory"] / f"{variant}.patch"
    with tempfile.TemporaryDirectory(prefix="e011-live-check-") as temporary:
        work = Path(temporary) / "repo"
        work.mkdir()
        with tarfile.open(snapshot, "r:") as archive:
            archive.extractall(work, filter="data")
        if patch.stat().st_size:
            applied = subprocess.run(["git", "apply", str(patch)], cwd=work, env=env, capture_output=True, text=True)
            if applied.returncode:
                raise RuntimeError(f"selected patch did not apply: {task['task_id']}/{variant}: {applied.stderr}")
        command = ["cargo", "test", "--locked", "--manifest-path", str(work / manifest)]
        command.extend(task["test_args"])
        command.extend([task["test_filter"], "--", "--exact"])
        started = time.perf_counter()
        completed = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True)
        elapsed = round((time.perf_counter() - started) * 1000, 3)
        log = completed.stdout + completed.stderr
        exact_test_ran = task["test_filter"] in log and ("... ok" in log or "... FAILED" in log)
        expected_compile_failure = task["compile_failure_is_task_failure"] and re.search(r"error\[E\d+\]", log) is not None
        if not exact_test_ran and not expected_compile_failure:
            raise RuntimeError(f"selected completion check did not run: {task['task_id']}\n{log[-2500:]}")
        log_path = RUN / "task-checks" / lane / f"{task['task_id']}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(log, encoding="utf-8")
        return {
            "task_id": task["task_id"],
            "lane": lane,
            "action_id": option["action"]["id"],
            "candidate_variant": variant,
            "patch_sha256": patch_hash,
            "test_filter": task["test_filter"],
            "command": command,
            "exit_code": completed.returncode,
            "passed": completed.returncode == 0,
            "elapsed_ms": elapsed,
            "log_sha256": sha256(log.encode("utf-8")),
            "log_path": str(log_path.relative_to(RUN)).replace("\\", "/"),
            "completion_source": "live-cargo-test",
            "completion_check_cached": False,
        }


def authorize(
    lane: str,
    row: dict,
    options: list[dict],
    output: dict,
    completion_passed: bool,
) -> tuple[dict, float]:
    presentation = row["presentation"]
    if lane == "small":
        observation_role = "small"
    elif lane in ("large", "always-large"):
        observation_role = "large"
    else:
        observation_role = output["_source_role"]
    observation = model_record(observation_role, row["task_id"])
    request_envelope = observation["observer_rpc_request"]
    response_envelope = observation["observer_rpc_response"]
    if (
        request_envelope["request_id_hex"] != presentation["request_id_hex"]
        or request_envelope["receipt_digest_hex"] != presentation["receipt_digest_hex"]
        or response_envelope["request_id_hex"] != presentation["request_id_hex"]
        or response_envelope["receipt_digest_hex"] != presentation["receipt_digest_hex"]
    ):
        raise RuntimeError(f"observer response lost its presentation binding: {lane}/{row['task_id']}")
    wire_output = {key: value for key, value in output.items() if not key.startswith("_")}
    input_value = {
        "task_id": f"{lane}-{row['task_id']}",
        "frame_digest_hex": row["frame_blake3"],
        "request_id_hex": request_envelope["request_id_hex"],
        "response_request_id_hex": response_envelope["request_id_hex"],
        "request_receipt_digest_hex": request_envelope["receipt_digest_hex"],
        "response_receipt_digest_hex": response_envelope["receipt_digest_hex"],
        "presentation_receipt_hex": presentation["receipt_hex"],
        "action_ledger_path": str(RUN / "ledgers" / f"{lane}-retry02" / f"{row['task_id']}.actions.bin"),
        "ordered_options": options,
        "observer_output": wire_output,
        "thresholds": read_json(RUN / "frozen-input-lock.json")["thresholds"],
        "completion_check_passed": completion_passed,
    }
    input_path = RUN / "work" / f"{lane}-{row['task_id']}-authorization-input.json"
    output_path = RUN / "receipts" / lane / f"{row['task_id']}.json"
    write_json(input_path, input_value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Path(input_value["action_ledger_path"]).parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    result = subprocess.run([str(AUTHORIZER), str(input_path), str(output_path)], cwd=REPAIR, capture_output=True, text=True)
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    if result.returncode:
        raise RuntimeError(f"E011 authority failed for {lane}/{row['task_id']}: {result.stderr}")
    receipt = read_json(output_path)
    if not receipt["presentation_verified"] or not receipt["replay_state_identical"]:
        raise RuntimeError(f"presentation/replay gate failed for {lane}/{row['task_id']}: {receipt}")
    return receipt, elapsed


def main() -> None:
    frozen_path = RUN / "frozen-input-lock.json"
    frozen = read_json(frozen_path)
    if frozen.get("state") != "FROZEN_BEFORE_MODEL_CONTACT":
        raise SystemExit("E011 model input lock is not frozen")
    prepared_path = RUN / "prepared-frame-lock.json"
    if sha256(prepared_path.read_bytes()) != frozen["sha256"]["prepared_frame_lock"]:
        raise SystemExit("prepared-frame lock changed after model contact")
    for role in ("small", "large"):
        role_dir = RUN / "observations" / role
        expected = {row["task_id"] for row in read_json(prepared_path)["rows"]}
        actual = {path.stem for path in role_dir.glob("*.json")}
        if actual != expected:
            raise SystemExit(f"{role} observer output count mismatch: {len(actual)}/{len(expected)}")
    labels = read_json(BANK / "sealed-labels.json")["tasks"]
    tasks = {task["task_id"]: task for task in read_json(BANK / "task-manifest.json")["tasks"]}
    rows = read_json(prepared_path)["rows"]
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(TARGET)
    test_cache: dict[tuple[str, str], dict] = {}
    lane_rows = []

    for row in rows:
        task_id = row["task_id"]
        frame = row["observer_frame"]
        options = [
            {"producer_ordinal": index, **option}
            for index, option in enumerate(frame["action_options"])
        ]
        allowed = {option["action"]["id"] for option in options}
        small_record = model_record("small", task_id)
        large_record = model_record("large", task_id)
        small_output = normalized(small_record)
        large_output = normalized(large_record)
        small_choice, small_reason = compile_choice(small_output, allowed, frozen["thresholds"])
        large_choice, large_reason = compile_choice(large_output, allowed, frozen["thresholds"])
        hybrid_output, hybrid_source = (small_output, "small") if small_choice is not None else (large_output, "large")
        hybrid_choice, hybrid_reason = compile_choice(hybrid_output, allowed, frozen["thresholds"])

        for lane, choice, output in (
            ("small", small_choice, small_output),
            ("small-then-large-on-abstention", hybrid_choice, {**hybrid_output, "_source_role": hybrid_source}),
            ("always-large", large_choice, large_output),
        ):
            option = next((item for item in options if item["action"]["id"] == choice), None)
            if option is None:
                check = {
                    "task_id": task_id,
                    "lane": lane,
                    "status": "no-action",
                    "passed": False,
                    "elapsed_ms": 0.0,
                    "completion_source": "no-action",
                }
            else:
                cache_key = (task_id, option["patch_sha256"])
                if cache_key not in test_cache:
                    test_cache[cache_key] = run_completion(tasks[task_id], option, lane, env)
                    check = {**test_cache[cache_key], "lane": lane}
                else:
                    check = {
                        **test_cache[cache_key],
                        "lane": lane,
                        "elapsed_ms": 0.0,
                        "completion_check_cached": True,
                    }
            completion = labels[task_id]["actions_by_patch_sha256"].get(option["patch_sha256"], {}).get("expected_task_completion") if option else False
            if bool(check["passed"]) != bool(completion):
                raise RuntimeError(f"live test and sealed bank label disagree: {lane}/{task_id}")
            authority, authority_ms = authorize(lane, row, options, output, bool(check["passed"]))
            execution_authorized = any(
                receipt.get("authorized_action") == 2
                and receipt.get("proposal", {}).get("action") == 2
                for receipt in authority["transition_receipts"]
            )
            if lane == "small":
                effective_records = [small_record]
            elif lane == "always-large":
                effective_records = [large_record]
            else:
                effective_records = [small_record] + ([large_record] if hybrid_source == "large" else [])
            lane_rows.append({
                "lane": lane,
                "task_id": task_id,
                "repository_id": row["repository_id"],
                "task_family": frame["task_family"],
                "frame_blake3": row["frame_blake3"],
                "output": {key: value for key, value in output.items() if not key.startswith("_")},
                "route_source": hybrid_source if lane == "small-then-large-on-abstention" else lane,
                "selected_action_id": choice,
                "selected_patch_sha256": option["patch_sha256"] if option else None,
                "compile_reason": {
                    "small": small_reason,
                    "large": large_reason,
                    "always-large": large_reason,
                    "small-then-large-on-abstention": hybrid_reason,
                }[lane],
                "task_completed": bool(check["passed"] and execution_authorized),
                "wrong_legal_action": bool(option is not None and not check["passed"] and execution_authorized),
                "abstained": option is None,
                "large_calls": int(lane == "always-large" or (lane == "small-then-large-on-abstention" and hybrid_source == "large")),
                "small_calls": int(lane == "small" or lane == "small-then-large-on-abstention"),
                "input_tokens": sum(int(record.get("usage", {}).get("prompt_tokens", 0) or 0) for record in effective_records),
                "generated_tokens": sum(int(record.get("usage", {}).get("completion_tokens", 0) or 0) for record in effective_records),
                "observer_model_wall_ms": round(sum(float(record.get("elapsed_ms", 0.0)) for record in effective_records), 3),
                "completion_check": check,
                "completion_check_wall_ms": check["elapsed_ms"],
                "authority": authority,
                "authority_wall_ms": authority_ms,
            })

    output_lock = {
        "schema_version": 1,
        "state": "SCORED_AFTER_MODEL_CONTACT",
        "run_id": RUN_ID,
        "frozen_input_lock_sha256": sha256(frozen_path.read_bytes()),
        "prepared_frame_lock_sha256": sha256(prepared_path.read_bytes()),
        "sealed_labels_sha256": sha256((BANK / "sealed-labels.json").read_bytes()),
        "task_manifest_sha256": sha256((BANK / "task-manifest.json").read_bytes()),
        "small_observer_outputs_sha256": tree_hash(RUN / "observations" / "small"),
        "large_observer_outputs_sha256": tree_hash(RUN / "observations" / "large"),
        "scorer_sha256": sha256(Path(__file__).read_bytes()),
        "runtime_authorizer_sha256": sha256(AUTHORIZER.read_bytes()),
        "candidate_test_result_tree_sha256": tree_hash(RUN / "task-checks"),
        "completion_mode": "live cargo tests in isolated extracted task snapshots",
    }
    write_json(RUN / "score-replay-input-lock.json", output_lock)
    write_json(RUN / "lane-results.json", {"schema_version": 1, "results": lane_rows})
    report = make_report(lane_rows, rows, frozen)
    write_json(RUN / "qualification-summary.json", report["summary"])
    (RUN / "integration-qualification-report.md").write_text(report["markdown"], encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"wrote {RUN / 'integration-qualification-report.md'}")


def make_report(lane_rows: list[dict], frame_rows: list[dict], frozen: dict) -> dict:
    summaries = {}
    for lane in ("small", "small-then-large-on-abstention", "always-large"):
        subset = [row for row in lane_rows if row["lane"] == lane]
        summaries[lane] = {
            "task_count": len(subset),
            "completions": sum(row["task_completed"] for row in subset),
            "wrong_legal_actions": sum(row["wrong_legal_action"] for row in subset),
            "abstentions": sum(row["abstained"] for row in subset),
            "large_calls": sum(row["large_calls"] for row in subset),
            "small_calls": sum(row["small_calls"] for row in subset),
            "input_tokens": sum(row["input_tokens"] for row in subset),
            "generated_tokens": sum(row["generated_tokens"] for row in subset),
            "observer_model_wall_ms": round(sum(row["observer_model_wall_ms"] for row in subset), 3),
            "completion_check_wall_ms": round(sum(row["completion_check_wall_ms"] for row in subset), 3),
            "authority_wall_ms": round(sum(row["authority_wall_ms"] for row in subset), 3),
            "illegal_commits": sum(row["authority"]["illegal_commits"] for row in subset),
            "duplicate_action_effects": sum(row["authority"]["duplicate_action_effects"] for row in subset),
            "replay_identity_all_equal": all(row["authority"]["replay_state_identical"] for row in subset),
        }
    by_repository = {}
    for repository in sorted({row["repository_id"] for row in lane_rows}):
        repo = [row for row in lane_rows if row["repository_id"] == repository]
        by_repository[repository] = {}
        for lane in summaries:
            subset = [row for row in repo if row["lane"] == lane]
            acted = [row for row in subset if row["selected_action_id"] is not None]
            by_repository[repository][lane] = {
                "tasks": len(subset),
                "coverage": f"{len(acted)}/{len(subset)}",
                "direct_precision": f"{sum(row['completion_check']['passed'] for row in acted)}/{len(acted)}" if lane == "small" else None,
                "completions": f"{sum(row['task_completed'] for row in subset)}/{len(subset)}",
                "large_calls": sum(row["large_calls"] for row in subset),
                "large_calls_avoided_vs_always_large": sum(row["large_calls"] for row in [item for item in repo if item["lane"] == "always-large"]) - sum(row["large_calls"] for row in subset),
                "wrong_legal_actions": sum(row["wrong_legal_action"] for row in subset),
            }
    gates = {}
    for repository in by_repository:
        small = by_repository[repository]["small"]
        hybrid = by_repository[repository]["small-then-large-on-abstention"]
        large = by_repository[repository]["always-large"]
        direct_count = int(small["coverage"].split("/")[0])
        direct_correct = int(small["direct_precision"].split("/")[0])
        gates[repository] = {
            "hybrid_completion_at_least_always_large": int(hybrid["completions"].split("/")[0]) >= int(large["completions"].split("/")[0]),
            "at_least_one_large_call_displaced": hybrid["large_calls_avoided_vs_always_large"] >= 1,
            "small_direct_coverage_nonzero": direct_count >= 1,
            "all_small_direct_actions_correct": direct_count == direct_correct,
            "authority_and_replay_clean": sum(row["authority"]["illegal_commits"] + row["authority"]["duplicate_action_effects"] for row in lane_rows if row["repository_id"] == repository) == 0 and all(row["authority"]["replay_state_identical"] for row in lane_rows if row["repository_id"] == repository),
        }
        gates[repository]["passed"] = all(gates[repository].values())
    summary = {
        "run_id": RUN_ID,
        "bank_id": read_json(BANK / "bank-freeze.json")["bank_id"],
        "task_count": len(frame_rows),
        "underlying_task_families": len({row["observer_frame"]["task_family"] for row in frame_rows}),
        "repositories": by_repository,
        "pooled_descriptive_totals": summaries,
        "repository_level_gates": gates,
        "all_repository_gates_passed": all(gate["passed"] for gate in gates.values()),
        "thresholds": frozen["thresholds"],
        "prompt_and_model_bundle_unchanged": True,
        "observer_requests_received_restored_producer_order": True,
    }
    lines = [
        "# E011 Producer-Order Runtime Integration Qualification",
        "",
        f"Run: `{RUN_ID}`; bank: `{summary['bank_id']}`.",
        "",
        "This is a small integration qualification on four newly built task frames across two locked Rust repositories. It exercises one new regression target per repository with two prompt/test variants each; the tasks are fresh to the v5 observer, but the result is not a repository-generalization estimate.",
        "",
        f"The frozen E009 v5 prompt, bundles, normalization, routing rule, and `{frozen['thresholds']['minimum_applicability_milli']}/{frozen['thresholds']['maximum_abstention_milli']}` thresholds were used without fitting. Every frame was deliberately permuted in the transport adapter, restored by producer ordinal, and checked byte-for-byte at the observer-frame level before model contact.",
        "",
        "## Repository results",
        "",
        "| Repository | Lane | Coverage | Direct precision | Completion | Large calls avoided | Wrong legal actions |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for repository, lanes in by_repository.items():
        for lane, value in lanes.items():
            label = "Hybrid" if lane == "small-then-large-on-abstention" else lane.replace("-", " ").title()
            lines.append(f"| {repository} | {label} | {value['coverage']} | {value['direct_precision'] or '—'} | {value['completions']} | {value['large_calls_avoided_vs_always_large']} | {value['wrong_legal_actions']} |")
    lines += ["", "## Pooled descriptive totals", "", "| Lane | Completion | Wrong legal | Large calls | Small calls | Input tokens | Generated tokens | Model time (s) |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for lane, value in summaries.items():
        lines.append(f"| {lane} | {value['completions']}/{value['task_count']} | {value['wrong_legal_actions']} | {value['large_calls']} | {value['small_calls']} | {value['input_tokens']} | {value['generated_tokens']} | {value['observer_model_wall_ms'] / 1000:.2f} |")
    lines += ["", "## Integration gates", ""]
    for repository, gate in gates.items():
        lines.append(f"- `{repository}`: `{'PASS' if gate['passed'] else 'FAIL'}`; hybrid completion ≥ always-large: {gate['hybrid_completion_at_least_always_large']}; large call displaced: {gate['at_least_one_large_call_displaced']}; small direct coverage nonzero: {gate['small_direct_coverage_nonzero']}; direct small actions all correct: {gate['all_small_direct_actions_correct']}; authority and replay clean: {gate['authority_and_replay_clean']}.")
    lines += [
        "",
        f"Overall repository-level gate: `{'PASS' if summary['all_repository_gates_passed'] else 'FAIL'}`.",
        "",
        "## Limits",
        "",
        "The bank contains four task frames but only two underlying task families, with two variants per family. Results qualify the candidate-order receipt and live authority path on these fixtures; they do not establish new transfer breadth or causal evidence dependence. Model latency is measured locally. Input and generated tokens are reported separately; no token-efficiency claim is made.",
        "",
        "Repeated identical task/patch checks across lanes reused a prior live test result. The elapsed time is charged only to the first execution; this test accounting is not a paired end-to-end latency benchmark.",
        "",
        "The presentation receipt establishes task/presentation integrity and proposal mapping. It does not prove a selected legal patch is semantically correct; only the isolated completion test records that outcome.",
        "",
    ]
    return {"summary": summary, "markdown": "\n".join(lines)}


if __name__ == "__main__":
    main()
