from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
RUN_ID = "e009-20260925-expanded-01"
RUN = ROOT / "artifacts" / "runs" / RUN_ID
OBSERVATION_RUN_ID = RUN_ID
OBSERVATION_RUN = RUN
HELDOUT_BANK_NAME = "heldout-bank-v5"
TARGET = Path(r"D:\cargo-targets\rdc-e009-expanded\scoring")
COMPLETION_MODE = "live"
AUTH_TARGET = Path(r"D:\cargo-targets\rdc-e009")
AUTHORITY_EXECUTION_MINIMUM_MILLI = 700
EMPTY_PATCH_SHA256 = hashlib.sha256(b"").hexdigest()
STOP_WORDS = {
    "and", "the", "to", "a", "an", "or", "with", "from", "by", "for", "in", "on", "of", "is",
    "are", "be", "it", "this", "that", "current", "one", "offered", "action", "keep", "include",
    "use", "when", "without", "only", "must", "choose", "patch", "test", "frozen", "task", "snapshot",
}
CANDIDATE_LOCK_CACHE: dict[str, dict] = {}
BANK_BUILD_RECEIPT_CACHE: dict[str, dict] = {}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def frames_path(bank: str) -> Path:
    dirname = "dev-bank-v4" if bank == "development" else HELDOUT_BANK_NAME
    return ROOT / "tasks" / "expanded" / dirname


def output_stage(bank: str, role: str) -> str:
    prefix = "dev" if bank == "development" else "heldout"
    return f"{prefix}-shadow-{role}"


def model_record(bank: str, role: str, task_id: str) -> dict:
    path = OBSERVATION_RUN / output_stage(bank, role) / f"{task_id}.json"
    record = read_json(path)
    if record.get("http_status") != 200:
        raise RuntimeError(f"observer call failed for {bank}/{role}/{task_id}: {record.get('error', record.get('http_status'))}")
    return record


def normalized_output(record: dict) -> object:
    return record.get("normalized_output")


def token_counts(record: dict | None) -> tuple[int, int]:
    usage = (record or {}).get("usage", {})
    prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0))
    generated = usage.get("completion_tokens", usage.get("output_tokens", 0))
    return int(prompt or 0), int(generated or 0)


def score_value(output: object, key: str, default: int) -> int:
    if not isinstance(output, dict):
        return default
    value = output.get(key)
    return value if type(value) is int and 0 <= value <= 1000 else default


def compile_choice(output: object, allowed: set[int], minimum_app: int, maximum_abst: int) -> tuple[int | None, str]:
    if not isinstance(output, dict):
        return None, "invalid-output"
    choice = output.get("action_choice")
    app = output.get("applicability_milli")
    abst = output.get("abstention_milli")
    if type(app) is not int or type(abst) is not int or not 0 <= app <= 1000 or not 0 <= abst <= 1000:
        return None, "invalid-scores"
    if abst > maximum_abst:
        return None, "abstention-threshold"
    if app < max(minimum_app, AUTHORITY_EXECUTION_MINIMUM_MILLI):
        return None, "applicability-threshold"
    if choice is None:
        return None, "explicit-abstention"
    if type(choice) is not int or choice not in allowed:
        return None, "unknown-action"
    return choice, "propose"


def route_hybrid(
    small_output: dict,
    large_output: dict,
    allowed: set[int],
    minimum_app: int,
    maximum_abst: int,
) -> tuple[dict, bool]:
    small_choice, _ = compile_choice(small_output, allowed, minimum_app, maximum_abst)
    if small_choice is not None:
        return small_output, False
    return large_output, True


def frame_action_labels(frame: dict, task_labels: dict) -> dict[int, bool]:
    by_patch = task_labels["actions_by_patch_sha256"]
    return {
        option["action"]["id"]: bool(by_patch[option["patch_sha256"]]["expected_task_completion"])
        for option in frame["action_options"]
    }


def fit_dev_thresholds() -> None:
    bank_root = frames_path("development")
    frame_lock_path = bank_root / "frame-lock.json"
    candidate_lock_path = bank_root / "candidate-lock.json"
    labels_path = bank_root / "sealed-labels.json"
    frames = read_json(frame_lock_path)["frames"]
    labels = read_json(labels_path)["tasks"]
    prepared = []
    for locked in frames:
        frame = locked["frame"]
        task_id = frame["task_id"]
        allowed = {option["action"]["id"] for option in frame["action_options"]}
        small = model_record("development", "small", task_id)
        large = model_record("development", "large", task_id)
        small_out = normalized_output(small)
        large_out = normalized_output(large)
        success = frame_action_labels(frame, labels[task_id])
        small_choice = small_out.get("action_choice") if isinstance(small_out, dict) else None
        large_choice = large_out.get("action_choice") if isinstance(large_out, dict) else None
        small_valid = type(small_choice) is int and small_choice in allowed
        large_valid = type(large_choice) is int and large_choice in allowed
        prepared.append(
            {
                "task_id": task_id,
                "small_app": score_value(small_out, "applicability_milli", -1),
                "small_abst": score_value(small_out, "abstention_milli", 1001),
                "small_choice": small_choice if small_valid else None,
                "small_success": bool(success.get(small_choice, False)) if small_valid else False,
                "large_app": score_value(large_out, "applicability_milli", -1),
                "large_abst": score_value(large_out, "abstention_milli", 1001),
                "large_choice": large_choice if large_valid else None,
                "large_success": bool(success.get(large_choice, False)) if large_valid else False,
                "small_tokens": sum(token_counts(small)),
                "large_tokens": sum(token_counts(large)),
                "small_ms": float(small.get("elapsed_ms", 0.0)),
                "large_ms": float(large.get("elapsed_ms", 0.0)),
            }
        )

    best_key: tuple | None = None
    best: dict | None = None
    for minimum_app in range(AUTHORITY_EXECUTION_MINIMUM_MILLI, 1001):
        for maximum_abst in range(1001):
            completions = 0
            large_calls = 0
            tokens = 0
            model_ms = 0.0
            small_accepted = 0
            small_correct = 0
            for item in prepared:
                tokens += item["small_tokens"]
                model_ms += item["small_ms"]
                small_accepted_for_task = (
                    item["small_choice"] is not None
                    and item["small_app"] >= minimum_app
                    and item["small_abst"] <= maximum_abst
                )
                if small_accepted_for_task:
                    small_accepted += 1
                    small_correct += int(item["small_success"])
                    completions += int(item["small_success"])
                else:
                    large_calls += 1
                    tokens += item["large_tokens"]
                    model_ms += item["large_ms"]
                    large_accepted = (
                        item["large_choice"] is not None
                        and item["large_app"] >= minimum_app
                        and item["large_abst"] <= maximum_abst
                    )
                    completions += int(large_accepted and item["large_success"])
            key = (completions, -large_calls, -tokens, -model_ms, minimum_app, -maximum_abst)
            if best_key is None or key > best_key:
                best_key = key
                best = {
                    "minimum_applicability_milli": minimum_app,
                    "maximum_abstention_milli": maximum_abst,
                    "development_task_count": len(prepared),
                    "hybrid_completions": completions,
                    "hybrid_completion_rate": completions / len(prepared),
                    "large_calls": large_calls,
                    "large_call_rate": large_calls / len(prepared),
                    "small_accepted": small_accepted,
                    "small_correct_among_accepted": small_correct,
                    "input_plus_generated_tokens": tokens,
                    "modeled_observer_wall_ms": round(model_ms, 3),
                }

    if best is None:
        raise RuntimeError("threshold search produced no candidates")
    threshold_path = ROOT / "models" / "bundle-lineage" / "selected-thresholds-v5.json"
    if threshold_path.exists():
        raise SystemExit(f"refusing to overwrite frozen development thresholds: {threshold_path}")
    dev_lock = RUN / "frozen-development-input-lock.json"
    write_json(
        threshold_path,
        {
            "schema_version": 1,
            "selection_source": "development bank only",
            "selection_objective": [
                "maximize complete tasks",
                "minimize large model calls",
                "minimize input plus generated tokens",
                "minimize measured observer wall time",
                "prefer higher minimum applicability",
                "prefer lower maximum abstention",
            ],
            "search_grid": {
                "minimum_applicability_milli": {"min": AUTHORITY_EXECUTION_MINIMUM_MILLI, "max": 1000, "step": 1},
                "maximum_abstention_milli": {"min": 0, "max": 1000, "step": 1},
                "candidate_pairs": 301301,
            },
            "selected_thresholds": {
                "minimum_applicability_milli": best["minimum_applicability_milli"],
                "maximum_abstention_milli": best["maximum_abstention_milli"],
            },
            "development_fit": best,
            "development_frame_lock_sha256": sha256(frame_lock_path.read_bytes()),
            "development_candidate_lock_sha256": sha256(candidate_lock_path.read_bytes()),
            "development_labels_sha256": sha256(labels_path.read_bytes()),
            "development_small_outputs_sha256": tree_hash(RUN / "dev-shadow-small"),
            "development_large_outputs_sha256": tree_hash(RUN / "dev-shadow-large"),
            "frozen_development_input_lock_sha256": sha256(dev_lock.read_bytes()),
            "heldout_labels_read": False,
            "authority_execution_guard_milli": AUTHORITY_EXECUTION_MINIMUM_MILLI,
            "normalization_contract": "percent-0-100-to-milli-x10-v1+line-endings-lf-v1",
        },
    )
    print(json.dumps(best, indent=2))
    print(f"wrote frozen threshold choice: {threshold_path}")


def tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def percentile_nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, int((percentile * len(ordered) + 99.999) // 100))
    return round(ordered[min(rank, len(ordered)) - 1], 3)


def hand_output(frame: dict) -> dict:
    prompt_words = {
        word for word in re.findall(r"[a-z0-9_]+", frame["task_prompt"].lower())
        if len(word) > 2 and word not in STOP_WORDS
    }
    evidence_words = {
        word
        for evidence in frame.get("evidence", [])
        for word in re.findall(
            r"[a-z0-9_]+",
            (evidence.get("source_id", "") + " " + evidence.get("content", "")).lower(),
        )
        if len(word) > 2 and word not in STOP_WORDS
    }
    scores: dict[int, int] = {}
    for option in frame["action_options"]:
        text = (option["summary"] + " " + option["diff_excerpt"]).lower()
        action_words = {
            word for word in re.findall(r"[a-z0-9_]+", text)
            if len(word) > 2 and word not in STOP_WORDS
        }
        scores[option["action"]["id"]] = 2 * len(prompt_words & action_words) + len(evidence_words & action_words)
    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    top = ordered[0][1] if ordered else 0
    second = ordered[1][1] if len(ordered) > 1 else 0
    unique = sum(score == top for score in scores.values()) == 1
    if unique and top >= 5 and top - second >= 2:
        return {"action_choice": ordered[0][0], "applicability_milli": 900, "abstention_milli": 0}
    return {"action_choice": None, "applicability_milli": 800, "abstention_milli": 900}


def selected_option(frame: dict, choice: int | None) -> dict | None:
    return next((item for item in frame["action_options"] if item["action"]["id"] == choice), None)


def sanitize_for_authority(output: object) -> dict:
    if isinstance(output, dict):
        choice = output.get("action_choice")
        app = output.get("applicability_milli")
        abst = output.get("abstention_milli")
        if (
            (choice is None or type(choice) is int)
            and type(app) is int and 0 <= app <= 1000
            and type(abst) is int and 0 <= abst <= 1000
        ):
            return output
    return {"action_choice": None, "applicability_milli": 0, "abstention_milli": 1000}


def completion_check(bank: str, frame: dict, option: dict | None, lane: str) -> dict:
    if option is None:
        return {
            "task_id": frame["task_id"],
            "status": "no-action",
            "passed": False,
            "elapsed_ms": 0.0,
            "completion_source": "no-action",
        }
    patch_hash = option["patch_sha256"]
    bank_root = frames_path(bank)
    if bank not in CANDIDATE_LOCK_CACHE:
        CANDIDATE_LOCK_CACHE[bank] = read_json(bank_root / "candidate-lock.json")
    candidate_lock = CANDIDATE_LOCK_CACHE[bank]
    family_lock = candidate_lock["families"][frame["task_family"]]
    variant = next(
        name for name, candidate in family_lock["variants"].items()
        if candidate["patch_sha256"] == patch_hash
    )
    manifest = ROOT / family_lock["variants"][variant]["manifest"]
    test_filter = family_lock["test_filter"]
    if COMPLETION_MODE == "frozen-bank-receipt":
        if bank not in BANK_BUILD_RECEIPT_CACHE:
            BANK_BUILD_RECEIPT_CACHE[bank] = read_json(bank_root / "bank-build-receipt.json")
        receipt = BANK_BUILD_RECEIPT_CACHE[bank]
        if receipt.get("source_repository_revision") != candidate_lock.get("repository_revision"):
            raise RuntimeError(f"bank build receipt revision mismatch for {bank}")
        family_receipts = receipt.get("completion_checks", {}).get(frame["task_family"], {})
        recorded = family_receipts.get(variant)
        if not isinstance(recorded, dict) or family_receipts.get("test_filter") != test_filter:
            raise RuntimeError(f"missing exact completion receipt for {frame['task_family']}/{variant}")
        log_path = ROOT / recorded["log"]
        log_bytes = log_path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        log_hash = sha256(log_bytes)
        if log_hash != recorded.get("log_sha256"):
            raise RuntimeError(f"completion log hash mismatch for {frame['task_family']}/{variant}")
        passed = recorded.get("passed") is True
        failed_as_expected = recorded.get("failed_as_expected") is True
        if not (passed or failed_as_expected):
            raise RuntimeError(f"completion receipt is neither passing nor an expected failing candidate: {frame['task_family']}/{variant}")
        return {
            "task_id": frame["task_id"],
            "lane": lane,
            "action_id": option["action"]["id"],
            "patch_sha256": patch_hash,
            "candidate_variant": variant,
            "test_filter": test_filter,
            "status": "passed" if passed else "failed-test",
            "passed": passed,
            "elapsed_ms": 0.0,
            "completion_source": "precontact-bank-build-receipt",
            "completion_log_sha256": log_hash,
            "bank_build_receipt_sha256": sha256((bank_root / "bank-build-receipt.json").read_bytes()),
        }

    environment = os.environ.copy()
    environment["CARGO_TARGET_DIR"] = str(TARGET)
    clean_cmd = ["cargo", "clean", "--manifest-path", str(manifest), "-p", "gpui-animated-gradient-text"]
    clean = subprocess.run(clean_cmd, cwd=manifest.parent, env=environment, capture_output=True, text=True)
    if clean.returncode != 0:
        raise RuntimeError(f"candidate package clean failed: {clean.stderr}")
    command = ["cargo", "test", "--manifest-path", str(manifest), "-p", "gpui-animated-gradient-text"]
    features = family_lock.get("features", [])
    if features:
        command.extend(["--features", ",".join(features)])
    command.extend(["--lib", test_filter, "--", "--exact"])
    started = time.perf_counter()
    result = subprocess.run(command, cwd=manifest.parent, env=environment, capture_output=True, text=True)
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    output = result.stdout + result.stderr
    test_name_ran = re.search(rf"test\s+{re.escape(test_filter)}\s+\.\.\. (?:ok|FAILED)", output) is not None
    passed = result.returncode == 0 and "test result: ok. 1 passed;" in output
    if not test_name_ran:
        raise RuntimeError(f"completion test did not run as expected for {frame['task_id']}/{variant}: {output[-2000:]}")
    return {
        "task_id": frame["task_id"],
        "lane": lane,
        "action_id": option["action"]["id"],
        "patch_sha256": patch_hash,
        "candidate_variant": variant,
        "test_filter": test_filter,
        "command": command,
        "exit_code": result.returncode,
        "status": "passed" if passed else "failed-test",
        "passed": passed,
        "elapsed_ms": elapsed,
        "completion_source": "live-cargo-test",
        "output_sha256": sha256(output.encode("utf-8")),
        "output": output,
    }


def ensure_authority_binary() -> Path:
    binary = AUTH_TARGET / "debug" / "e009-authorize.exe"
    environment = os.environ.copy()
    environment["CARGO_TARGET_DIR"] = str(AUTH_TARGET)
    subprocess.run(
        ["cargo", "build", "--manifest-path", str(ROOT / "Cargo.toml"), "--bin", "e009-authorize"],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    if not binary.is_file():
        raise RuntimeError("E002 authorizer executable missing after build")
    return binary


def run_authority(
    binary: Path,
    lane: str,
    locked: dict,
    frame: dict,
    option: dict | None,
    output: dict,
    thresholds: dict,
    completion_passed: bool,
) -> tuple[dict, float]:
    task_id = frame["task_id"]
    lane_key = lane.replace("/", "-")
    ledger = RUN / "ledgers" / lane_key / f"{task_id}.actions.bin"
    input_path = RUN / "work" / f"{lane_key}-{task_id}-authorization-input.json"
    receipt_path = RUN / "receipts" / lane_key / f"{task_id}.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    actions = [item["action"] for item in frame["action_options"]]
    auth_input = {
        "task_id": task_id,
        "frame_hash_hex": locked["blake3"],
        "selected_patch_sha256": option["patch_sha256"] if option else None,
        "action_ledger_path": str(ledger),
        "actions": actions,
        "observer_output": sanitize_for_authority(output),
        "thresholds": thresholds,
        "completion_check_passed": completion_passed,
    }
    write_json(input_path, auth_input)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    result = subprocess.run(
        [str(binary), str(input_path), str(receipt_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    if result.returncode != 0:
        raise RuntimeError(f"E002 authority failed for {lane}/{task_id}: {result.stderr}")
    return read_json(receipt_path), elapsed


def routed_lanes(frame: dict, bank: str, thresholds: dict) -> dict[str, tuple[dict, int, int]]:
    task_id = frame["task_id"]
    small_record = model_record(bank, "small", task_id)
    large_record = model_record(bank, "large", task_id)
    small_output = sanitize_for_authority(normalized_output(small_record))
    large_output = sanitize_for_authority(normalized_output(large_record))
    allowed = {item["action"]["id"] for item in frame["action_options"]}
    minimum_app = int(thresholds["minimum_applicability_milli"])
    maximum_abst = int(thresholds["maximum_abstention_milli"])

    hybrid_output, used_large_fallback = route_hybrid(
        small_output, large_output, allowed, minimum_app, maximum_abst
    )
    hybrid_choice, _ = compile_choice(hybrid_output, allowed, minimum_app, maximum_abst)

    return {
        "hand-written": (hand_output(frame), 0, 0),
        "small": (small_output, 1, 0),
        "small-then-large-on-abstention": (hybrid_output, 1, int(used_large_fallback)),
        "always-large": (large_output, 0, 1),
    }


def score_heldout() -> None:
    threshold_path = ROOT / "models" / "bundle-lineage" / "selected-thresholds-v5.json"
    thresholds_document = read_json(threshold_path)
    thresholds = thresholds_document["selected_thresholds"]
    final_lock_path = ROOT / "models" / "bundle-lineage" / "v5-final" / "bundle-lock.json"
    final_lock = read_json(final_lock_path)
    for bundle in final_lock["bundles"]:
        manifest = bundle["manifest"]
        if (
            manifest["minimum_applicability_milli"] != thresholds["minimum_applicability_milli"]
            or manifest["maximum_abstention_milli"] != thresholds["maximum_abstention_milli"]
            or manifest["reasoning_mode"] != "off"
            or manifest["maximum_output_tokens"] != 1024
            or manifest["output_schema"] != "rdc-coding-observer-output.v2"
            or manifest["typed_head_id"] != "json-schema-output-head-v2"
            or manifest["normalization_contract"] != "percent-0-100-to-milli-x10-v1+line-endings-lf-v1"
        ):
            raise SystemExit("v5 final bundle lock does not match the frozen development thresholds")

    bank_root = frames_path("heldout")
    frame_lock_path = bank_root / "frame-lock.json"
    labels_path = bank_root / "sealed-labels.json"
    if OBSERVATION_RUN_ID != RUN_ID:
        replay_lock_path = RUN / "score-replay-input-lock.json"
        if not replay_lock_path.is_file():
            raise SystemExit("separate observer and score runs require score-replay-input-lock.json")
        replay_lock = read_json(replay_lock_path)
        checks = {
            "observation_run_id": replay_lock.get("observation_run_id") == OBSERVATION_RUN_ID,
            "heldout_frame_lock_sha256": replay_lock.get("heldout_frame_lock_sha256") == sha256(frame_lock_path.read_bytes()),
            "heldout_labels_sha256": replay_lock.get("heldout_labels_sha256") == sha256(labels_path.read_bytes()),
            "small_observer_outputs_sha256": replay_lock.get("small_observer_outputs_sha256") == tree_hash(OBSERVATION_RUN / "heldout-shadow-small"),
            "large_observer_outputs_sha256": replay_lock.get("large_observer_outputs_sha256") == tree_hash(OBSERVATION_RUN / "heldout-shadow-large"),
            "thresholds_sha256": replay_lock.get("thresholds_sha256") == sha256(threshold_path.read_bytes()),
            "bundle_lock_sha256": replay_lock.get("bundle_lock_sha256") == sha256(final_lock_path.read_bytes()),
            "evaluator_sha256": replay_lock.get("evaluator_sha256") == sha256((ROOT / "scripts" / "evaluate_expanded.py").read_bytes()),
            "heldout_candidate_lock_sha256": replay_lock.get("heldout_candidate_lock_sha256") == sha256((bank_root / "candidate-lock.json").read_bytes()),
            "heldout_bank_tree_sha256": replay_lock.get("heldout_bank_tree_sha256") == tree_hash(bank_root),
            "heldout_build_receipt_sha256": replay_lock.get("heldout_build_receipt_sha256") == sha256((bank_root / "bank-build-receipt.json").read_bytes()),
            "completion_mode": replay_lock.get("completion_mode") == COMPLETION_MODE,
        }
        if not all(checks.values()):
            raise SystemExit(f"score replay input lock mismatch: {checks}")
    frames = read_json(frame_lock_path)["frames"]
    labels = read_json(labels_path)["tasks"]
    if (RUN / "lane-results.json").exists():
        raise SystemExit("refusing to overwrite held-out lane results")
    binary = ensure_authority_binary()
    lane_names = ("hand-written", "small", "small-then-large-on-abstention", "always-large")
    results: list[dict] = []

    for lane in lane_names:
        for locked in frames:
            frame = locked["frame"]
            routes = routed_lanes(frame, "heldout", thresholds)
            output, small_calls, large_calls = routes[lane]
            allowed = {item["action"]["id"] for item in frame["action_options"]}
            choice, compile_reason = compile_choice(
                output,
                allowed,
                int(thresholds["minimum_applicability_milli"]),
                int(thresholds["maximum_abstention_milli"]),
            )
            option = selected_option(frame, choice)
            check = completion_check("heldout", frame, option, lane)
            label = labels[frame["task_id"]]
            expected = (
                label["actions_by_patch_sha256"][option["patch_sha256"]]["expected_task_completion"]
                if option is not None else False
            )
            if check["passed"] != expected:
                raise RuntimeError(f"live held-out completion check disagrees with sealed label for {frame['task_id']}/{lane}")
            authority, authority_ms = run_authority(
                binary,
                lane,
                locked,
                frame,
                option,
                output,
                thresholds,
                check["passed"],
            )
            execution_authorized = any(
                receipt.get("authorized_action") == 2
                and receipt.get("proposal", {}).get("action") == 2
                for receipt in authority["transition_receipts"]
            )
            task_completed = bool(check["passed"] and execution_authorized)

            small_record = model_record("heldout", "small", frame["task_id"])
            large_record = model_record("heldout", "large", frame["task_id"])
            small_tokens = token_counts(small_record) if small_calls else (0, 0)
            large_tokens = token_counts(large_record) if large_calls else (0, 0)
            observer_ms = (
                (float(small_record.get("elapsed_ms", 0.0)) if small_calls else 0.0)
                + (float(large_record.get("elapsed_ms", 0.0)) if large_calls else 0.0)
            )
            prompt_tokens = small_tokens[0] + large_tokens[0]
            generated_tokens = small_tokens[1] + large_tokens[1]
            elapsed_ms = observer_ms + check["elapsed_ms"] + authority_ms
            selected_small_wrong = False
            if lane in ("small", "small-then-large-on-abstention"):
                raw_small = normalized_output(small_record)
                raw_choice = raw_small.get("action_choice") if isinstance(raw_small, dict) else None
                raw_option = selected_option(frame, raw_choice if type(raw_choice) is int else None)
                if raw_option is not None:
                    raw_correct = label["actions_by_patch_sha256"][raw_option["patch_sha256"]]["expected_task_completion"]
                    selected_small_wrong = (
                        not raw_correct
                        and score_value(raw_small, "applicability_milli", -1) >= thresholds["minimum_applicability_milli"]
                        and score_value(raw_small, "abstention_milli", 1001) <= thresholds["maximum_abstention_milli"]
                    )

            row = {
                "lane": lane,
                "task_id": frame["task_id"],
                "task_family": frame["task_family"],
                "difficulty": label["difficulty"],
                "frame_blake3": locked["blake3"],
                "output": output,
                "compile_reason": compile_reason,
                "selected_action_id": choice,
                "selected_patch_sha256": option["patch_sha256"] if option else None,
                "task_completed": task_completed,
                "wrong_legal_action": choice is not None and execution_authorized and not check["passed"],
                "authority_rejected_proposal": choice is not None and not execution_authorized,
                "abstained": choice is None,
                "small_confident_wrong_action": selected_small_wrong,
                "small_calls": small_calls,
                "large_calls": large_calls,
                "input_tokens": prompt_tokens,
                "generated_tokens": generated_tokens,
                "total_tokens": prompt_tokens + generated_tokens,
                "observer_model_wall_ms": round(observer_ms, 3),
                "completion_check_wall_ms": check["elapsed_ms"],
                "authority_wall_ms": authority_ms,
                "total_elapsed_wall_ms": round(elapsed_ms, 3),
                "billed_api_usd": 0.0,
                "completion_check": check,
                "authority": authority,
            }
            result_path = RUN / "task-checks" / lane / f"{frame['task_id']}.json"
            write_json(result_path, check)
            results.append(row)

    output_path = RUN / "lane-results.json"
    write_json(output_path, {"schema_version": 1, "results": results})
    summary = summarize_heldout(results, frames, labels, thresholds, thresholds_document)
    write_json(RUN / "benchmark-summary.json", summary)
    write_json(RUN / "coverage-error-curve.json", summary["small_coverage_error_curve"])
    (RUN / "benchmark-report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary["lanes"], indent=2))
    print(f"wrote held-out report: {RUN / 'benchmark-report.md'}")


def summarize_heldout(results: list[dict], frames: list[dict], labels: dict, thresholds: dict, threshold_doc: dict) -> dict:
    summaries: dict[str, dict] = {}
    for lane in ("hand-written", "small", "small-then-large-on-abstention", "always-large"):
        rows = [item for item in results if item["lane"] == lane]
        completions = sum(item["task_completed"] for item in rows)
        illegal = sum(item["authority"]["illegal_commits"] for item in rows)
        rejected = sum(item["authority"]["rejected_transitions"] for item in rows)
        duplicates = sum(item["authority"]["duplicate_action_effects"] for item in rows)
        replay_ok = all(item["authority"]["replay_state_identical"] for item in rows)
        summaries[lane] = {
            "task_count": len(rows),
            "completions": completions,
            "completion_rate": completions / len(rows) if rows else 0,
            "wrong_legal_actions": sum(item["wrong_legal_action"] for item in rows),
            "authority_rejected_proposals": sum(item["authority_rejected_proposal"] for item in rows),
            "abstentions": sum(item["abstained"] for item in rows),
            "small_calls": sum(item["small_calls"] for item in rows),
            "large_calls": sum(item["large_calls"] for item in rows),
            "input_tokens": sum(item["input_tokens"] for item in rows),
            "generated_tokens": sum(item["generated_tokens"] for item in rows),
            "total_tokens": sum(item["total_tokens"] for item in rows),
            "observer_model_wall_ms": round(sum(item["observer_model_wall_ms"] for item in rows), 3),
            "observer_time_p50_ms": percentile_nearest_rank([item["observer_model_wall_ms"] for item in rows], 50),
            "observer_time_p95_ms": percentile_nearest_rank([item["observer_model_wall_ms"] for item in rows], 95),
            "completion_check_wall_ms": round(sum(item["completion_check_wall_ms"] for item in rows), 3),
            "authority_wall_ms": round(sum(item["authority_wall_ms"] for item in rows), 3),
            "total_elapsed_wall_ms": round(sum(item["total_elapsed_wall_ms"] for item in rows), 3),
            "task_time_p50_ms": percentile_nearest_rank([item["total_elapsed_wall_ms"] for item in rows], 50),
            "task_time_p95_ms": percentile_nearest_rank([item["total_elapsed_wall_ms"] for item in rows], 95),
            "small_confident_wrong_actions": sum(item["small_confident_wrong_action"] for item in rows),
            "illegal_commits": illegal,
            "rejected_transitions": rejected,
            "duplicate_action_effects": duplicates,
            "replay_identity_all_equal": replay_ok,
            "billed_api_usd": 0.0,
        }

    family_rows: dict[str, list[dict]] = defaultdict(list)
    for row in results:
        family_rows[row["task_family"]].append(row)
    by_family = {}
    for family, rows in sorted(family_rows.items()):
        by_family[family] = {}
        for lane in ("hand-written", "small", "small-then-large-on-abstention", "always-large"):
            subset = [row for row in rows if row["lane"] == lane]
            by_family[family][lane] = {
                "tasks": len(subset),
                "completions": sum(row["task_completed"] for row in subset),
                "wrong_legal_actions": sum(row["wrong_legal_action"] for row in subset),
                "authority_rejected_proposals": sum(row["authority_rejected_proposal"] for row in subset),
                "abstentions": sum(row["abstained"] for row in subset),
                "large_calls": sum(row["large_calls"] for row in subset),
            }

    curve = coverage_error_curve(frames, labels, thresholds)
    lane_ref = summaries["always-large"]
    comparisons = {}
    for lane, values in summaries.items():
        comparisons[lane] = {
            "completion_difference_from_always_large": values["completions"] - lane_ref["completions"],
            "total_token_difference_from_always_large": values["total_tokens"] - lane_ref["total_tokens"],
            "elapsed_ms_difference_from_always_large": round(values["total_elapsed_wall_ms"] - lane_ref["total_elapsed_wall_ms"], 3),
            "large_call_difference_from_always_large": values["large_calls"] - lane_ref["large_calls"],
        }
    return {
        "schema_version": 1,
        "run_id": RUN_ID,
        "observer_run_id": OBSERVATION_RUN_ID,
        "task_bank": {
            "bank_name": HELDOUT_BANK_NAME,
            "task_count": len(frames),
            "family_count": len({item["frame"]["task_family"] for item in frames}),
            "unit_for_variation": "task family; two prompt variants per family are not independent worlds",
            "same_repository_as_development": True,
            "cross_repository_generalization_claim": False,
            "promotion_eligible": HELDOUT_BANK_NAME != "heldout-bank-v5",
        },
        "frozen_thresholds": thresholds,
        "completion_check_mode": COMPLETION_MODE,
        "completion_check_wall_time_in_task_latency": COMPLETION_MODE == "live",
        "hand_written_policy": "evidence-weighted-token-overlap-v2; unique top score >=5 and margin >=2",
        "development_fit": threshold_doc["development_fit"],
        "lanes": summaries,
        "by_family": by_family,
        "differences_from_always_large": comparisons,
        "small_coverage_error_curve": curve,
        "authority_gates": {
            "illegal_commits": sum(item["authority"]["illegal_commits"] for item in results),
            "rejected_transitions": sum(item["authority"]["rejected_transitions"] for item in results),
            "duplicate_action_effects": sum(item["authority"]["duplicate_action_effects"] for item in results),
            "replay_identity_all_equal": all(item["authority"]["replay_state_identical"] for item in results),
        },
        "model_call_accounting": {
            "shadow_calls_per_model_for_data_capture": len(frames),
            "lane_costs_use_only_calls_that_lane_would_make": True,
            "input_tokens_and_generated_tokens_separate": True,
        },
        "cost_limits": "Local model calls are unbilled; GPU energy and hardware-dollar cost are not measured.",
    }


def coverage_error_curve(frames: list[dict], labels: dict, selected: dict) -> dict:
    heldout_records = {role: {} for role in ("small", "large")}
    for locked in frames:
        frame = locked["frame"]
        allowed = {item["action"]["id"] for item in frame["action_options"]}
        task_id = frame["task_id"]
        outcome = frame_action_labels(frame, labels[task_id])
        small = normalized_output(model_record("heldout", "small", task_id))
        if not isinstance(small, dict):
            small = {}
        choice = small.get("action_choice")
        heldout_records["small"][task_id] = {
            "valid": type(choice) is int and choice in allowed,
            "choice": choice,
            "success": bool(outcome.get(choice, False)) if type(choice) is int else False,
            "app": small.get("applicability_milli", -1),
            "abst": small.get("abstention_milli", 1001),
        }
    app_values = sorted(set(range(0, 1001, 50)) | {int(selected["minimum_applicability_milli"]), 0, 1000})
    abst_values = sorted(set(range(0, 1001, 50)) | {int(selected["maximum_abstention_milli"]), 0, 1000})
    at_fixed_abst = []
    for minimum_app in app_values:
        covered = [
            item for item in heldout_records["small"].values()
            if item["valid"] and item["app"] >= max(minimum_app, AUTHORITY_EXECUTION_MINIMUM_MILLI) and item["abst"] <= selected["maximum_abstention_milli"]
        ]
        at_fixed_abst.append({
            "minimum_applicability_milli": minimum_app,
            "maximum_abstention_milli": selected["maximum_abstention_milli"],
            "covered": len(covered),
            "coverage": len(covered) / len(frames),
            "correct": sum(item["success"] for item in covered),
            "wrong": sum(not item["success"] for item in covered),
            "error_rate_when_covered": (sum(not item["success"] for item in covered) / len(covered)) if covered else None,
        })
    at_fixed_app = []
    for maximum_abst in abst_values:
        covered = [
            item for item in heldout_records["small"].values()
            if item["valid"] and item["app"] >= max(selected["minimum_applicability_milli"], AUTHORITY_EXECUTION_MINIMUM_MILLI) and item["abst"] <= maximum_abst
        ]
        at_fixed_app.append({
            "minimum_applicability_milli": selected["minimum_applicability_milli"],
            "maximum_abstention_milli": maximum_abst,
            "covered": len(covered),
            "coverage": len(covered) / len(frames),
            "correct": sum(item["success"] for item in covered),
            "wrong": sum(not item["success"] for item in covered),
            "error_rate_when_covered": (sum(not item["success"] for item in covered) / len(covered)) if covered else None,
        })
    return {
        "scope": "post-hoc descriptive curve on held-out outputs; no threshold selection or bundle change",
        "at_fixed_selected_maximum_abstention": at_fixed_abst,
        "at_fixed_selected_minimum_applicability": at_fixed_app,
    }


def render_report(summary: dict) -> str:
    heldout_status = (
        "This scoring bank contains fresh task families that were frozen after the v5 observer contract and was not scored in earlier E009 runs."
        if summary["task_bank"]["promotion_eligible"]
        else "This corrected-v5 replay reuses the held-out bank scored in e009-20260925-expanded-01, so it is a regression diagnostic, not promotion evidence."
    )
    lines = [
        "# E009 expanded observer benchmark",
        "",
        f"Run: `{summary['run_id']}`",
        "",
        f"Thresholds were fit using development labels only. {heldout_status} The bank contains {summary['task_bank']['family_count']} task families from one frozen product repository, with two prompt variants per family.",
        "",
        "## Lane results",
        "",
        "| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls | Input tokens | Generated tokens | Model time (s) | Task p50/p95 (s) | Total elapsed (s) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for lane, values in summary["lanes"].items():
        lines.append(
            f"| {lane} | {values['completions']}/{values['task_count']} | {values['wrong_legal_actions']} | {values['abstentions']} | {values['authority_rejected_proposals']} | {values['large_calls']} | {values['input_tokens']} | {values['generated_tokens']} | {values['observer_model_wall_ms'] / 1000:.2f} | {values['task_time_p50_ms'] / 1000:.2f}/{values['task_time_p95_ms'] / 1000:.2f} | {values['total_elapsed_wall_ms'] / 1000:.2f} |"
        )
    thresholds = summary["frozen_thresholds"]
    lines += [
        "",
        "## Frozen gate and authority",
        "",
        f"Selected on development: minimum applicability `{thresholds['minimum_applicability_milli']}`, maximum abstention `{thresholds['maximum_abstention_milli']}`.",
        f"Hand-written baseline: `{summary['hand_written_policy']}`.",
        f"Illegal commits: {summary['authority_gates']['illegal_commits']}; rejected transitions: {summary['authority_gates']['rejected_transitions']}; duplicate action effects: {summary['authority_gates']['duplicate_action_effects']}; replay identity: {summary['authority_gates']['replay_identity_all_equal']}.",
        "",
        "## Family results",
        "",
    ]
    for family, lanes in summary["by_family"].items():
        lines.append(f"### {family}")
        lines.append("")
        lines.append("| Lane | Complete | Wrong legal | Abstain | Rejected proposals | Large calls |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for lane, values in lanes.items():
            lines.append(f"| {lane} | {values['completions']}/{values['tasks']} | {values['wrong_legal_actions']} | {values['abstentions']} | {values['authority_rejected_proposals']} | {values['large_calls']} |")
        lines.append("")
    lines += [
        "## Limits",
        "",
        (
            "This is task-family transfer within one repository, not a cross-repository result. Exact completion outcomes "
            "were reused from hash-verified bank-build test receipts captured before model contact; their one-time build "
            "and test time is excluded from lane task latency. Local model requests are unbilled; energy and hardware-dollar "
            "cost are not measured. The post-hoc coverage/error curve is descriptive and did not change the selected threshold or v5 bundle."
            if summary["completion_check_mode"] == "frozen-bank-receipt"
            else "This is task-family transfer within one repository, not a cross-repository result. Local model requests are unbilled; energy and hardware-dollar cost were not measured. The post-hoc coverage/error curve is descriptive and did not change the selected threshold or v5 bundle."
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    global RUN_ID, RUN, OBSERVATION_RUN_ID, OBSERVATION_RUN, HELDOUT_BANK_NAME, COMPLETION_MODE
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("fit-dev", "score-heldout", "fit-dev-v5", "score-heldout-v5"))
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--observation-run-id", default=None)
    parser.add_argument("--heldout-bank", default=HELDOUT_BANK_NAME)
    parser.add_argument("--completion-mode", choices=("live", "frozen-bank-receipt"), default="live")
    args = parser.parse_args()
    RUN_ID = args.run_id
    RUN = ROOT / "artifacts" / "runs" / RUN_ID
    OBSERVATION_RUN_ID = args.observation_run_id or RUN_ID
    OBSERVATION_RUN = ROOT / "artifacts" / "runs" / OBSERVATION_RUN_ID
    HELDOUT_BANK_NAME = args.heldout_bank
    COMPLETION_MODE = args.completion_mode
    if args.mode in ("fit-dev", "fit-dev-v5"):
        fit_dev_thresholds()
    else:
        score_heldout()


if __name__ == "__main__":
    main()
