from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011\repairs\order-robust-prompt-v1")
E011 = Path(r"C:\rd-c\experiment-011")
E010_RUN = Path(r"C:\rd-c\experiment-010\artifacts\runs\e010-20260925-cross-repo-01")
E011_RUN = E011 / "artifacts/runs/e011-20260925-causal-evidence-01"
R2_RUN = E011 / "repairs/candidate-presentation-factorial-v1/artifacts/runs/e011-r2-20260925-presentation-factorial-01"
RUN_ID = "e011-r3-20260925-order-robust-prompt-01"
RUN = ROOT / "artifacts/runs" / RUN_ID
CONDITIONS = ("full-frame", "order-only")
MIN_APP = 850
MAX_ABST = 150
SMALL_ALIAS = "e009-small-v5"
SMALL_BUNDLE_ID = "minicpm5-2b-q8-local-v5+candidate-order-instruction-v1"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_json(path: Path) -> object:
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


def copy_once(source: Path, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite repair input: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())


def parent_artifacts() -> dict[str, str]:
    e010_lock_path = E010_RUN / "score-replay-input-lock.json"
    e010_lock = read_json(e010_lock_path)
    small_tree = tree_hash(E010_RUN / "heldout-shadow-small")
    large_tree = tree_hash(E010_RUN / "heldout-shadow-large")
    if small_tree != e010_lock["small_observer_outputs_sha256"]:
        raise RuntimeError("E010 small observer output tree does not match its replay lock")
    if large_tree != e010_lock["large_observer_outputs_sha256"]:
        raise RuntimeError("E010 large observer output tree does not match its replay lock")

    r2_seal = read_json(R2_RUN / "postrun-output-seal.json")
    r2_large = R2_RUN / "outputs/large/order-only"
    if tree_hash(r2_large) != r2_seal["trees"]["large"]["order-only"]["tree_sha256"]:
        raise RuntimeError("E011-R2 order-only large output tree does not match its output seal")
    r2_small = R2_RUN / "outputs/small/order-only"
    if tree_hash(r2_small) != r2_seal["trees"]["small"]["order-only"]["tree_sha256"]:
        raise RuntimeError("E011-R2 order-only small output tree does not match its output seal")

    paths = {
        "e010_replay_lock": e010_lock_path,
        "e010_small_tree_lock": E010_RUN / "heldout-shadow-small",
        "e010_large_tree_lock": E010_RUN / "heldout-shadow-large",
        "e011_pre_model_seal": E011_RUN / "pre-model-seal.json",
        "e011_output_seal": E011_RUN / "postrun-output-seal.json",
        "e011_score": E011_RUN / "score-e011.json",
        "e011_candidate_permuted_frames": E011_RUN / "frame-lock-candidate-permuted.json",
        "r2_pre_model_seal": R2_RUN / "pre-model-seal.json",
        "r2_output_seal": R2_RUN / "postrun-output-seal.json",
        "r2_score": R2_RUN / "factorial-score.json",
        "r2_order_only_frames": R2_RUN / "frame-lock-order-only.json",
        "r2_small_order_only_tree": r2_small,
        "r2_large_order_only_tree": r2_large,
    }
    result = {}
    for name, path in paths.items():
        result[name] = tree_hash(path) if path.is_dir() else sha256(path.read_bytes())
    return result


def prepare() -> None:
    if RUN.exists() and any(RUN.iterdir()):
        raise SystemExit(f"refusing to overwrite nonempty prompt-repair run: {RUN}")
    RUN.mkdir(parents=True, exist_ok=True)
    copies = {
        E011 / "inputs/e010-heldout-frame-lock.json": ROOT / "inputs/e010-heldout-frame-lock.json",
        E011 / "inputs/e010-heldout-sealed-labels.json": ROOT / "inputs/e010-heldout-sealed-labels.json",
        E011 / "inputs/e009-v5-bundle-lock.json": ROOT / "inputs/e009-v5-bundle-lock.json",
        E011 / "inputs/e010-frozen-input-lock.json": ROOT / "inputs/e010-frozen-input-lock.json",
        E011 / "inputs/observer-output.v2.json": ROOT / "inputs/observer-output.v2.json",
        E011 / "inputs/chat-template-small.jinja": ROOT / "inputs/chat-template-small.jinja",
        E011 / "repairs/candidate-presentation-factorial-v1/artifacts/runs/e011-r2-20260925-presentation-factorial-01/frame-lock-order-only.json": ROOT / "inputs/r2-order-only-frame-lock.json",
    }
    for source, destination in copies.items():
        copy_once(source, destination)

    base_lock = read_json(ROOT / "inputs/e010-heldout-frame-lock.json")
    order_lock = read_json(ROOT / "inputs/r2-order-only-frame-lock.json")
    base_frames = {item["frame"]["task_id"]: item["frame"] for item in base_lock["frames"]}
    order_frames = {item["task_id"]: item["frame"] for item in order_lock["frames"]}
    if len(base_frames) != 16 or base_frames.keys() != order_frames.keys():
        raise RuntimeError("E010 and E011-R2 candidate-order frames do not pair")
    condition_hashes = {}
    for condition, frames in (("full-frame", base_frames), ("order-only", order_frames)):
        entries = [
            {
                "task_id": task_id,
                "frame_sha256": sha256(canonical(frame)),
                "frame": frame,
            }
            for task_id, frame in frames.items()
        ]
        frame_path = RUN / f"frame-lock-{condition}.json"
        write_json(frame_path, {"schema_version": 1, "condition": condition, "frames": entries})
        condition_hashes[condition] = sha256(frame_path.read_bytes())

    input_hashes = {
        path.relative_to(ROOT).as_posix(): sha256(path.read_bytes())
        for path in sorted((ROOT / "inputs").rglob("*"))
        if path.is_file()
    }
    input_hashes["spec.md"] = sha256((ROOT / "spec.md").read_bytes())
    input_hashes["inputs/system-observer-order-robust-v1.txt"] = sha256(
        (ROOT / "inputs/system-observer-order-robust-v1.txt").read_bytes()
    )
    input_hashes["scripts/prompt_repair.py"] = sha256(Path(__file__).read_bytes())
    input_hashes["scripts/start_small_observer.ps1"] = sha256(
        (ROOT / "scripts/start_small_observer.ps1").read_bytes()
    )
    input_hashes["scripts/stop_small_observer.ps1"] = sha256(
        (ROOT / "scripts/stop_small_observer.ps1").read_bytes()
    )
    lock = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_MODEL_CONTACT",
        "run_id": RUN_ID,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "posthoc same-bank prompt repair diagnostic; shadow-only",
        "bundle_id": SMALL_BUNDLE_ID,
        "model_bundle_parent": "minicpm5-2b-q8-local-v5",
        "prompt_sha256": sha256((ROOT / "inputs/system-observer-order-robust-v1.txt").read_bytes()),
        "thresholds": {"minimum_applicability_milli": MIN_APP, "maximum_abstention_milli": MAX_ABST},
        "conditions": list(CONDITIONS),
        "labels": "E010 labels already opened before this repair diagnostic",
        "parent_hashes": parent_artifacts(),
        "sha256": {"inputs": input_hashes, "condition_frame_locks": condition_hashes},
    }
    write_json(RUN / "pre-model-input-lock.json", lock)
    print(json.dumps({"run_id": RUN_ID, "state": lock["state"], "condition_frame_locks": condition_hashes}, indent=2))


def seal_inputs() -> None:
    lock_path = RUN / "pre-model-input-lock.json"
    seal_path = RUN / "pre-model-seal.json"
    if seal_path.exists():
        raise SystemExit("prompt-repair pre-model seal already exists")
    lock = read_json(lock_path)
    if lock.get("state") != "FROZEN_BEFORE_MODEL_CONTACT":
        raise SystemExit("prompt-repair inputs are not frozen")
    if (RUN / "outputs").exists() or (RUN / "small/server-process.json").exists():
        raise SystemExit("model contact began before prompt-repair sealing")
    verify_input_hashes(lock)
    verify_parent_hashes(lock)
    frame_hashes = {}
    for condition in CONDITIONS:
        path = RUN / f"frame-lock-{condition}.json"
        expected = lock["sha256"]["condition_frame_locks"][condition]
        if sha256(path.read_bytes()) != expected:
            raise RuntimeError(f"prompt-repair frame lock changed: {condition}")
        frame_hashes[condition] = expected
    code_paths = (ROOT / "spec.md", ROOT / "scripts/prompt_repair.py", ROOT / "scripts/start_small_observer.ps1", ROOT / "scripts/stop_small_observer.ps1")
    seal = {
        "schema_version": 1,
        "state": "SEALED_BEFORE_MODEL_CONTACT",
        "run_id": RUN_ID,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input_lock_sha256": sha256(lock_path.read_bytes()),
        "code_sha256": {
            path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()) for path in code_paths
        },
        "condition_frame_locks_sha256": frame_hashes,
        "model_contact_started": False,
    }
    write_json(seal_path, seal)
    print(json.dumps({"state": seal["state"], "seal_sha256": sha256(seal_path.read_bytes())}, indent=2))


def verify_input_hashes(lock: dict) -> None:
    for relative, expected in lock["sha256"]["inputs"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise SystemExit(f"prompt-repair input hash mismatch: {relative}")


def verify_parent_hashes(lock: dict) -> None:
    if parent_artifacts() != lock["parent_hashes"]:
        raise SystemExit("a parent E010/E011/R2 artifact changed after prompt-repair preparation")


def verify_run() -> tuple[dict, dict]:
    lock_path = RUN / "pre-model-input-lock.json"
    seal_path = RUN / "pre-model-seal.json"
    lock = read_json(lock_path)
    seal = read_json(seal_path)
    if seal.get("state") != "SEALED_BEFORE_MODEL_CONTACT" or seal.get("input_lock_sha256") != sha256(lock_path.read_bytes()):
        raise SystemExit("prompt-repair input lock/seal mismatch")
    verify_input_hashes(lock)
    verify_parent_hashes(lock)
    for relative, expected in seal["code_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise SystemExit(f"prompt-repair code hash mismatch: {relative}")
    for condition, expected in seal["condition_frame_locks_sha256"].items():
        if sha256((RUN / f"frame-lock-{condition}.json").read_bytes()) != expected:
            raise SystemExit(f"prompt-repair frame lock mismatch: {condition}")
    return lock, seal


def normalize(raw: object) -> tuple[dict | None, str | None]:
    if not isinstance(raw, dict):
        return None, "invalid-output-object"
    choice = raw.get("action_choice")
    app = raw.get("applicability_percent")
    abst = raw.get("abstention_percent")
    if choice is not None and (type(choice) is not int or not 0 <= choice <= 65535):
        return None, "invalid-action-choice"
    if type(app) is not int or type(abst) is not int or not 0 <= app <= 100 or not 0 <= abst <= 100:
        return None, "score-outside-percent-range"
    return {"action_choice": choice, "applicability_milli": app * 10, "abstention_milli": abst * 10}, None


def run_small(condition: str, base_url: str) -> None:
    lock, seal = verify_run()
    parsed = urllib.parse.urlparse(base_url)
    if parsed.hostname not in {"127.0.0.1", "::1", "localhost"} or parsed.port != 18491:
        raise SystemExit("prompt-repair endpoint must use the frozen loopback port 18491")
    server = read_json(RUN / "small/server-process.json")
    if server.get("base_url") != base_url or server.get("alias") != SMALL_ALIAS or server.get("reasoning_mode") != "off":
        raise SystemExit("small server record differs from the prompt-repair runtime contract")

    model_lock = read_json(ROOT / "inputs/e010-frozen-input-lock.json")
    model = next(item for item in model_lock["models"] if item["role"] == "small")
    bundle_lock = read_json(ROOT / "inputs/e009-v5-bundle-lock.json")
    bundle = next(item for item in bundle_lock["bundles"] if item["manifest"]["bundle_id"] == model["bundle_id"])
    manifest = bundle["manifest"]
    prompt_path = ROOT / "inputs/system-observer-order-robust-v1.txt"
    schema_path = ROOT / "inputs/observer-output.v2.json"
    template_path = ROOT / "inputs/chat-template-small.jinja"
    prompt = prompt_path.read_text(encoding="utf-8")
    schema = read_json(schema_path)
    if sha256(prompt_path.read_bytes()) != lock["prompt_sha256"]:
        raise SystemExit("prompt differs from the repair bundle lock")
    if sha256(schema_path.read_bytes()) != manifest["output_schema_sha256"]:
        raise SystemExit("prompt-repair output schema differs from E009 v5")
    if sha256(template_path.read_bytes()) != manifest["chat_template_sha256"]:
        raise SystemExit("prompt-repair chat template differs from E009 v5")
    if server.get("model_sha256") != model["model_sha256"] or server.get("runtime_sha256") != model["runtime_sha256"]:
        raise SystemExit("prompt-repair weights or runtime differ from E009 v5")

    frame_lock_path = RUN / f"frame-lock-{condition}.json"
    frame_lock = read_json(frame_lock_path)
    out_dir = RUN / "outputs/small" / condition
    out_dir.mkdir(parents=True, exist_ok=False)
    for entry in frame_lock["frames"]:
        frame = entry["frame"]
        if sha256(canonical(frame)) != entry["frame_sha256"]:
            raise SystemExit(f"prompt-repair frame hash mismatch: {entry['task_id']}")
        payload = {
            "model": SMALL_ALIAS,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(frame, ensure_ascii=False, separators=(",", ":"))},
            ],
            "temperature": 0,
            "top_p": 1,
            "seed": 0,
            "max_tokens": 1024,
            "stream": False,
            "response_format": {"type": "json_schema", "json_schema": {"name": "rdc_coding_observer_output_v1", "strict": True, "schema": schema}},
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        started = time.perf_counter()
        request = urllib.request.Request(base_url + "/v1/chat/completions", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=180) as response:
            response_body = response.read()
            status = response.status
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        response_json = json.loads(response_body)
        content = response_json["choices"][0]["message"].get("content", "")
        try:
            parsed_output = json.loads(content)
        except json.JSONDecodeError:
            parsed_output = None
        normalized, normalization_error = normalize(parsed_output)
        record = {
            "schema_version": 1,
            "run_id": RUN_ID,
            "condition": condition,
            "role": "small",
            "bundle_id": SMALL_BUNDLE_ID,
            "parent_weights_bundle_id": model["bundle_id"],
            "server_alias": SMALL_ALIAS,
            "server_process_id": server["process_id"],
            "model_sha256": model["model_sha256"],
            "runtime_sha256": model["runtime_sha256"],
            "prompt_sha256": lock["prompt_sha256"],
            "input_lock_sha256": sha256((RUN / "pre-model-input-lock.json").read_bytes()),
            "pre_model_seal_sha256": sha256((RUN / "pre-model-seal.json").read_bytes()),
            "frame_lock_sha256": sha256(frame_lock_path.read_bytes()),
            "frame_sha256": entry["frame_sha256"],
            "task_id": entry["task_id"],
            "request_sha256": sha256(body),
            "request": payload,
            "normalization_contract": "percent-0-100-to-milli-x10-v1+line-endings-lf-v1",
            "thresholds": lock["thresholds"],
            "http_status": status,
            "response": response_json,
            "content": content,
            "output": parsed_output,
            "normalized_output": normalized,
            "normalization_error": normalization_error,
            "usage": response_json.get("usage", {}),
            "finish_reason": response_json["choices"][0].get("finish_reason"),
            "elapsed_ms": elapsed_ms,
        }
        write_json(out_dir / f"{entry['task_id']}.json", record)
        print(f"small/{condition} {entry['task_id']} {status} {elapsed_ms} ms")


def seal_outputs() -> None:
    lock, _ = verify_run()
    seal_path = RUN / "postrun-output-seal.json"
    if seal_path.exists():
        raise SystemExit("prompt-repair output seal already exists")
    trees = {}
    for condition in CONDITIONS:
        directory = RUN / "outputs/small" / condition
        records = list(directory.glob("*.json"))
        if len(records) != 16:
            raise RuntimeError(f"expected 16 small outputs for {condition}, got {len(records)}")
        for path in records:
            record = read_json(path)
            if record.get("http_status") != 200 or record.get("normalized_output") is None:
                raise RuntimeError(f"invalid small output before sealing: {path}")
        trees[condition] = {"record_count": 16, "tree_sha256": tree_hash(directory)}
    seal = {
        "schema_version": 1,
        "state": "OUTPUTS_SEALED_BEFORE_SCORING",
        "run_id": RUN_ID,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "pre_model_seal_sha256": sha256((RUN / "pre-model-seal.json").read_bytes()),
        "conditions": trees,
    }
    write_json(seal_path, seal)
    print(json.dumps(seal, indent=2))


def view(record: dict, frame: dict, labels: dict) -> dict:
    output = record.get("normalized_output")
    if not isinstance(output, dict):
        return {"accepted": False, "correct": False, "raw_correct": False, "reason": "invalid-output", "tokens": 0, "elapsed_ms": 0.0}
    choice = output.get("action_choice")
    option = next((item for item in frame["action_options"] if type(choice) is int and item["action"]["id"] == choice), None)
    patch = option["patch_sha256"] if option else None
    raw_correct = bool(patch and labels["actions_by_patch_sha256"].get(patch, {}).get("expected_task_completion", False))
    app = output.get("applicability_milli")
    abst = output.get("abstention_milli")
    if choice is None:
        reason = "explicit-abstention"
    elif option is None:
        reason = "unknown-action"
    elif type(app) is not int or type(abst) is not int:
        reason = "invalid-scores"
    elif abst > MAX_ABST:
        reason = "abstention-threshold"
    elif app < MIN_APP:
        reason = "applicability-threshold"
    else:
        reason = "accepted"
    return {
        "accepted": reason == "accepted",
        "correct": bool(reason == "accepted" and raw_correct),
        "raw_correct": raw_correct,
        "patch": patch,
        "reason": reason,
        "tokens": int(record.get("usage", {}).get("total_tokens", 0) or 0),
        "elapsed_ms": float(record.get("elapsed_ms", 0.0)),
    }


def score() -> None:
    lock, _ = verify_run()
    output_seal = read_json(RUN / "postrun-output-seal.json")
    if output_seal.get("state") != "OUTPUTS_SEALED_BEFORE_SCORING" or output_seal.get("pre_model_seal_sha256") != sha256((RUN / "pre-model-seal.json").read_bytes()):
        raise SystemExit("prompt-repair output seal mismatch")
    for condition in CONDITIONS:
        seal = output_seal["conditions"][condition]
        if tree_hash(RUN / "outputs/small" / condition) != seal["tree_sha256"]:
            raise RuntimeError(f"sealed prompt-repair outputs changed: {condition}")

    frames_by_condition = {
        condition: {item["task_id"]: item["frame"] for item in read_json(RUN / f"frame-lock-{condition}.json")["frames"]}
        for condition in CONDITIONS
    }
    labels = read_json(ROOT / "inputs/e010-heldout-sealed-labels.json")["tasks"]
    repos: dict[str, list[str]] = defaultdict(list)
    for item in read_json(ROOT / "inputs/e010-heldout-frame-lock.json")["frames"]:
        repos[item["frame"]["repository_id"]].append(item["frame"]["task_id"])

    old_small_root = {"full-frame": E010_RUN / "heldout-shadow-small", "order-only": R2_RUN / "outputs/small/order-only"}
    large_root = {"full-frame": E010_RUN / "heldout-shadow-large", "order-only": R2_RUN / "outputs/large/order-only"}
    result = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "scored_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "posthoc same-bank prompt repair diagnostic; shadow-only",
        "prompt_sha256": lock["prompt_sha256"],
        "thresholds": lock["thresholds"],
        "conditions": {},
    }
    for condition in CONDITIONS:
        condition_rows = []
        for repository, task_ids in sorted(repos.items()):
            old_small = []
            new_small = []
            large = []
            for task_id in task_ids:
                frame = frames_by_condition[condition][task_id]
                old_small.append(view(read_json(old_small_root[condition] / f"{task_id}.json"), frame, labels[task_id]))
                new_small.append(view(read_json(RUN / "outputs/small" / condition / f"{task_id}.json"), frame, labels[task_id]))
                large.append(view(read_json(large_root[condition] / f"{task_id}.json"), frame, labels[task_id]))
            new_hybrid = [new if new["accepted"] else fallback for new, fallback in zip(new_small, large, strict=True)]
            old_hybrid = [old if old["accepted"] else fallback for old, fallback in zip(old_small, large, strict=True)]

            def summarize(items: list[dict]) -> dict:
                coverage = sum(item["accepted"] for item in items)
                return {
                    "coverage": coverage,
                    "direct_correct": sum(item["correct"] for item in items),
                    "wrong_accepted": sum(item["accepted"] and not item["raw_correct"] for item in items),
                    "reasons": {reason: sum(item["reason"] == reason for item in items) for reason in sorted({item["reason"] for item in items})},
                    "tokens": sum(item["tokens"] for item in items),
                    "observer_ms": round(sum(item["elapsed_ms"] for item in items), 3),
                }

            condition_rows.append({
                "repository": repository,
                "tasks": len(task_ids),
                "v5_small": summarize(old_small),
                "repair_small": summarize(new_small),
                "large": summarize(large),
                "v5_hybrid_completions": sum(item["correct"] for item in old_hybrid),
                "repair_hybrid_completions": sum(item["correct"] for item in new_hybrid),
                "repair_hybrid_large_calls": sum(not item["accepted"] for item in new_small),
                "repair_hybrid_large_calls_avoided": sum(item["accepted"] for item in new_small),
                "repair_hybrid_tokens": sum(new["tokens"] + (fallback["tokens"] if not new["accepted"] else 0) for new, fallback in zip(new_small, large, strict=True)),
                "repair_hybrid_observer_ms": round(sum(new["elapsed_ms"] + (fallback["elapsed_ms"] if not new["accepted"] else 0.0) for new, fallback in zip(new_small, large, strict=True)), 3),
                "always_large_completions": sum(item["correct"] for item in large),
            })
        result["conditions"][condition] = condition_rows

    write_json(RUN / "score-e011-r3.json", result)
    (RUN / "prompt-repair-report.md").write_text(render_report(result), encoding="utf-8")
    print(json.dumps({"report": str(RUN / "prompt-repair-report.md")}, indent=2))


def render_report(result: dict) -> str:
    lines = [
        "# E011-R3 — Candidate Order Prompt Repair",
        "",
        f"- Run: {RUN_ID}",
        "- Posthoc same-bank diagnostic; E010 labels were already open.",
        "- Frozen E009 v5 small weights, schema, normalization, runtime, and thresholds; prompt has a new wrapper identity.",
        "- Large fallback outputs are reused from sealed runs on identical condition frames.",
        "",
        "## Repository-level results",
        "",
        "| Condition | Repository | v5 small coverage / precision | Repair coverage / precision | Repair wrong accepted | v5 hybrid | Repair hybrid | Always large | Large calls avoided | Repair hybrid tokens |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition, rows in result["conditions"].items():
        for row in rows:
            old, new = row["v5_small"], row["repair_small"]
            old_precision = "n/a" if not old["coverage"] else f"{old['direct_correct']}/{old['coverage']}"
            new_precision = "n/a" if not new["coverage"] else f"{new['direct_correct']}/{new['coverage']}"
            lines.append(
                f"| {condition} | {row['repository']} | {old['coverage']}/{row['tasks']} / {old_precision} | "
                f"{new['coverage']}/{row['tasks']} / {new_precision} | {new['wrong_accepted']} | "
                f"{row['v5_hybrid_completions']}/{row['tasks']} | {row['repair_hybrid_completions']}/{row['tasks']} | "
                f"{row['always_large_completions']}/{row['tasks']} | {row['repair_hybrid_large_calls_avoided']} | {row['repair_hybrid_tokens']} |"
            )
    lines.extend([
        "",
        "## Interpretation boundary",
        "",
        "Promotion requires the prompt repair to remove order-induced wrong accepted actions without sacrificing the useful frozen-order completion region. The same opened bank is a repair diagnostic only; no transfer claim follows.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "seal", "run", "seal-outputs", "score"))
    parser.add_argument("--condition", choices=CONDITIONS)
    parser.add_argument("--base-url")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "seal":
        seal_inputs()
    elif args.command == "run":
        if not args.condition or not args.base_url:
            raise SystemExit("run requires --condition and --base-url")
        run_small(args.condition, args.base_url)
    elif args.command == "seal-outputs":
        seal_outputs()
    else:
        score()


if __name__ == "__main__":
    main()
