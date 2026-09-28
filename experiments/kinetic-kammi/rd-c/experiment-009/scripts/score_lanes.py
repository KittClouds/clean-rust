from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
RUN = ROOT / "artifacts" / "runs" / os.environ.get("RDC_E009_RUN_ID", "e009-20260925-pilot-01")
MIN_APPLICABILITY = 700
MAX_ABSTENTION = 600
STOP_WORDS = {
    "and", "the", "to", "a", "an", "or", "with", "from", "by", "for", "in",
    "on", "of", "is", "are", "be", "it", "this", "that", "current", "one",
    "offered", "action", "keep", "include", "use", "when", "without", "only",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def model_record(stage: str, task_id: str) -> dict | None:
    path = RUN / stage / f"{task_id}.json"
    return read_json(path) if path.exists() else None


def compile_output(output: object, allowed_ids: set[int]) -> tuple[int | None, str]:
    if not isinstance(output, dict):
        return None, "invalid-output"
    choice = output.get("action_choice")
    applicability = output.get("applicability_milli")
    abstention = output.get("abstention_milli")
    if not isinstance(applicability, int) or not isinstance(abstention, int):
        return None, "invalid-output"
    if not 0 <= applicability <= 1000 or not 0 <= abstention <= 1000:
        return None, "score-out-of-range"
    if abstention > MAX_ABSTENTION:
        return None, "uncertain"
    if applicability < MIN_APPLICABILITY:
        return None, "not-applicable"
    if choice is None:
        return None, "explicit"
    if not isinstance(choice, int) or choice not in allowed_ids:
        return None, "unknown-action"
    return choice, "propose"


def hand_output(frame: dict) -> tuple[dict, dict[int, int]]:
    task_words = {
        word for word in re.findall(r"[a-z0-9_]+", frame["task_prompt"].lower())
        if len(word) > 2 and word not in STOP_WORDS
    }
    scores: dict[int, int] = {}
    for item in frame["action_options"]:
        text = (item["summary"] + " " + item["diff_excerpt"]).lower()
        action_words = {
            word for word in re.findall(r"[a-z0-9_]+", text)
            if len(word) > 2 and word not in STOP_WORDS
        }
        scores[item["action"]["id"]] = len(task_words & action_words)
    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    top_score = ordered[0][1]
    runner_up = ordered[1][1] if len(ordered) > 1 else 0
    unique = sum(value == top_score for value in scores.values()) == 1
    if unique and top_score >= 3 and top_score - runner_up >= 2:
        output = {
            "action_choice": ordered[0][0],
            "applicability_milli": 800,
            "abstention_milli": 200,
        }
    else:
        output = {"action_choice": None, "applicability_milli": 800, "abstention_milli": 900}
    return output, scores


def token_usage(record: dict | None) -> tuple[int, int]:
    usage = (record or {}).get("usage", {})
    prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0))
    completion = usage.get("completion_tokens", usage.get("output_tokens", 0))
    return int(prompt or 0), int(completion or 0)


def run_completion_check(lane: str, frame: dict, choice: int | None) -> dict:
    task_id = frame["task_id"]
    check_record = {
        "task_id": task_id,
        "lane": lane,
        "action_id": choice,
        "tests": [],
    }
    if choice is None:
        check_record.update({"completed": False, "status": "abstain-no-action"})
    else:
        gpu_choice = {23: "gold", 14: "mutant", 71: "noop"}
        embed_choice = {51: "gold", 17: "mutant", 42: "noop"}
        mapping = gpu_choice if task_id == "coding-gpu-pick-01" else embed_choice
        variant = mapping.get(choice)
        if variant is None:
            raise ValueError(f"no task-check mapping for {task_id} action {choice}")
        if variant == "noop":
            check_record.update({"completed": False, "status": "task-regressions-absent-in-base"})
        else:
            task_dir = ROOT / "tasks" / (
                "gpu-pick-invalidation-focused" if task_id == "coding-gpu-pick-01" else "embedding-batch-order-v2"
            )
            candidate = task_dir / ("candidate-gold" if variant == "gold" else "candidate-mutant")
            if task_id == "coding-gpu-pick-01":
                package = "graph-render-wgpu"
                manifest = candidate / "phoenix-native" / "Cargo.toml"
                test_filters = ["picking::e009_epoch_tests::stale_async_pick_is_rejected_after_either_epoch_changes"]
                target = r"D:\cargo-targets\rdc-e009\gpu-focused-real-gold" if variant == "gold" else r"D:\cargo-targets\rdc-e009\gpu-focused-real-mutant"
            else:
                package = "phoenix-embed"
                manifest = candidate / "rust-native" / "phoenix" / "Cargo.toml"
                test_filters = [
                    "tests::length_bucket_order_is_stable_for_equal_lengths",
                    "tests::telemetry_reports_padding_amplification",
                ]
                target = r"D:\cargo-targets\rdc-e009\embed-full-gold-v2" if variant == "gold" else r"D:\cargo-targets\rdc-e009\embed-full-mutant-v2"
            results = []
            for test_filter in test_filters:
                command = [
                    "cargo", "test", "--manifest-path", str(manifest), "-p", package,
                    "--lib", test_filter, "--", "--exact",
                ]
                environment = os.environ.copy()
                environment["CARGO_TARGET_DIR"] = target
                started = time.perf_counter()
                result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True)
                elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
                output = result.stdout + result.stderr
                match = re.search(r"running\s+(\d+)\s+tests?", output)
                tests_run = int(match.group(1)) if match else 0
                passed = result.returncode == 0 and tests_run == 1 and "test result: ok" in output
                results.append(
                    {
                        "filter": test_filter,
                        "command": command,
                        "exit_code": result.returncode,
                        "tests_run": tests_run,
                        "passed": passed,
                        "elapsed_ms": elapsed_ms,
                        "output": output,
                    }
                )
            check_record["tests"] = results
            check_record["completed"] = bool(results) and all(item["passed"] for item in results)
            check_record["status"] = "passed" if check_record["completed"] else "failed-or-mutated"

    output_path = RUN / "task-checks" / lane / f"{task_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(check_record, indent=2) + "\n", encoding="utf-8")
    return check_record


def make_decision(lane: str, task_id: str, frame: dict) -> tuple[dict, list[dict], dict[int, int]]:
    allowed = {option["action"]["id"] for option in frame["action_options"]}
    if lane == "hand-written":
        output, scores = hand_output(frame)
        return output, [], scores
    if lane == "small":
        records = [model_record("lane-small", task_id)]
        output = (records[0] or {}).get("output")
        return output or {"action_choice": None, "applicability_milli": 0, "abstention_milli": 1000}, [r for r in records if r], {}
    if lane == "small-then-large-on-abstention":
        small = model_record("lane-hybrid-small", task_id)
        small_output = (small or {}).get("output")
        choice, _ = compile_output(small_output, allowed)
        records = [small] if small else []
        if choice is not None:
            return small_output, records, {}
        large = model_record("lane-hybrid-large", task_id)
        records.extend([large] if large else [])
        large_output = (large or {}).get("output")
        return large_output or {"action_choice": None, "applicability_milli": 0, "abstention_milli": 1000}, records, {}
    if lane == "always-large":
        record = model_record("lane-large", task_id)
        return (record or {}).get("output") or {"action_choice": None, "applicability_milli": 0, "abstention_milli": 1000}, [record] if record else [], {}
    raise ValueError(f"unknown lane: {lane}")


def main() -> None:
    frames_lock = read_json(ROOT / "tasks" / "frames" / "frame-lock.json")
    labels = read_json(ROOT / "sealed" / "labels.json")["tasks"]
    lane_results = []
    environment = os.environ.copy()
    environment["CARGO_TARGET_DIR"] = r"D:\cargo-targets\rdc-e009"

    for lane in ("hand-written", "small", "small-then-large-on-abstention", "always-large"):
        for locked in frames_lock["frames"]:
            frame = locked["frame"]
            task_id = frame["task_id"]
            output, records, overlap = make_decision(lane, task_id, frame)
            allowed = {item["action"]["id"] for item in frame["action_options"]}
            choice, typed_result = compile_output(output, allowed)
            option = next((item for item in frame["action_options"] if item["action"]["id"] == choice), None)
            check_record = run_completion_check(lane, frame, choice)
            expected = check_record["completed"]
            labeled_expected = labels[task_id]["actions"].get(str(choice), {}).get("expected_task_completion", False) if choice is not None else False
            if expected != labeled_expected:
                raise RuntimeError(
                    f"task check disagrees with sealed label for {task_id} action {choice}: "
                    f"observed={expected} label={labeled_expected}"
                )
            ledger = RUN / "ledgers" / lane / f"{task_id}.actions.bin"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            input_path = RUN / "work" / f"{lane}-{task_id}-authorization-input.json"
            output_path = RUN / "receipts" / lane / f"{task_id}.json"
            input_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            auth_input = {
                "task_id": task_id,
                "frame_hash_hex": locked["blake3"],
                "selected_patch_sha256": option["patch_sha256"] if option else None,
                "action_ledger_path": str(ledger),
                "actions": [item["action"] for item in frame["action_options"]],
                "observer_output": output,
                "thresholds": {
                    "minimum_applicability_milli": MIN_APPLICABILITY,
                    "maximum_abstention_milli": MAX_ABSTENTION,
                },
                "completion_check_passed": bool(expected),
            }
            input_path.write_text(json.dumps(auth_input, indent=2) + "\n", encoding="utf-8")
            started = time.perf_counter()
            subprocess.run(
                [
                    "cargo", "run", "--quiet", "--manifest-path", str(ROOT / "Cargo.toml"),
                    "--bin", "e009-authorize", "--", str(input_path), str(output_path),
                ],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            authority_ms = round((time.perf_counter() - started) * 1000, 3)
            receipt = read_json(output_path)
            prompt_tokens = 0
            completion_tokens = 0
            observer_ms = 0.0
            for record in records:
                p_tokens, c_tokens = token_usage(record)
                prompt_tokens += p_tokens
                completion_tokens += c_tokens
                observer_ms += float(record.get("elapsed_ms", 0.0))
            task_check_ms = sum(test["elapsed_ms"] for test in check_record["tests"])
            lane_results.append(
                {
                    "lane": lane,
                    "task_id": task_id,
                    "frame_blake3": locked["blake3"],
                    "output": output,
                    "typed_result": typed_result,
                    "selected_action_id": choice,
                    "selected_patch_sha256": option["patch_sha256"] if option else None,
                    "task_completed": bool(expected),
                    "wrong_legal_action": choice is not None and not expected,
                    "abstained": choice is None,
                    "calls": len(records),
                    "large_calls": sum(record.get("bundle_id", "").startswith("ternary") for record in records),
                    "small_calls": sum(record.get("bundle_id", "").startswith("minicpm") for record in records),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "observer_wall_ms": round(observer_ms, 3),
                    "task_check_wall_ms": round(task_check_ms, 3),
                    "authority_wall_ms": authority_ms,
                    "total_task_wall_ms": round(observer_ms + task_check_ms + authority_ms, 3),
                    "local_inference_cost_proxy": {"tokens": prompt_tokens + completion_tokens, "wall_ms": round(observer_ms, 3)},
                    "billed_api_usd": 0,
                    "hand_overlap_scores": overlap,
                    "completion_check": {
                        "status": check_record["status"],
                        "tests": [
                            {"filter": test["filter"], "tests_run": test["tests_run"], "passed": test["passed"], "elapsed_ms": test["elapsed_ms"]}
                            for test in check_record["tests"]
                        ],
                    },
                    "authority": receipt,
                }
            )

    output_path = RUN / "lane-results.json"
    if output_path.exists():
        raise SystemExit(f"refusing to overwrite {output_path}")
    output_path.write_text(json.dumps({"schema_version": 1, "results": lane_results}, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(lane_results)} paired lane-task results: {output_path}")


if __name__ == "__main__":
    main()
