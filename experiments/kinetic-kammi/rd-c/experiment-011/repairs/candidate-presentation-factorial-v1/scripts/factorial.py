from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011\repairs\candidate-presentation-factorial-v1")
PARENT = Path(r"C:\rd-c\experiment-011")
PARENT_RUN = PARENT / "artifacts/runs/e011-20260925-causal-evidence-01"
R1_RUN = PARENT / "repairs/candidate-canonicalization-v1/artifacts/runs/e011-r1-20260925-candidate-canonicalization-01"
RUN_ID = "e011-r2-20260925-presentation-factorial-01"
RUN = ROOT / "artifacts/runs" / RUN_ID
CONDITIONS = ("ids-only", "order-only")
ROLES = ("small", "large")
MIN_APP = 850
MAX_ABST = 150


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
        raise RuntimeError(f"refusing to overwrite factorial input: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def build_conditions(base_frames: dict[str, dict], combined_frames: dict[str, dict]) -> dict[str, list[dict]]:
    ids_only: list[dict] = []
    order_only: list[dict] = []
    for task_id, base in base_frames.items():
        combined = combined_frames[task_id]
        base_by_patch = {item["patch_sha256"]: item for item in base["action_options"]}
        combined_by_patch = {item["patch_sha256"]: item for item in combined["action_options"]}
        if base_by_patch.keys() != combined_by_patch.keys():
            raise RuntimeError(f"candidate set changed in E011 combined permutation: {task_id}")

        ids_frame = copy.deepcopy(base)
        for option in ids_frame["action_options"]:
            option["action"]["id"] = combined_by_patch[option["patch_sha256"]]["action"]["id"]
        ids_only.append(ids_frame)

        order_frame = copy.deepcopy(base)
        order_frame["action_options"] = []
        for combined_option in combined["action_options"]:
            option = copy.deepcopy(base_by_patch[combined_option["patch_sha256"]])
            order_frame["action_options"].append(option)
        order_only.append(order_frame)

        if [item["patch_sha256"] for item in ids_frame["action_options"]] != [
            item["patch_sha256"] for item in base["action_options"]
        ]:
            raise RuntimeError(f"IDs-only treatment changed candidate order: {task_id}")
        if [item["patch_sha256"] for item in order_frame["action_options"]] != [
            item["patch_sha256"] for item in combined["action_options"]
        ]:
            raise RuntimeError(f"order-only treatment did not reuse E011 shuffled order: {task_id}")
        if any(
            option["action"]["id"] != base_by_patch[option["patch_sha256"]]["action"]["id"]
            for option in order_frame["action_options"]
        ):
            raise RuntimeError(f"order-only treatment changed original action IDs: {task_id}")
    return {"ids-only": ids_only, "order-only": order_only}


def prepare() -> None:
    if RUN.exists() and any(RUN.iterdir()):
        raise SystemExit(f"refusing to overwrite nonempty factorial run: {RUN}")
    RUN.mkdir(parents=True, exist_ok=True)
    copies = {
        PARENT / "inputs/e010-heldout-frame-lock.json": ROOT / "inputs/e010-heldout-frame-lock.json",
        PARENT / "inputs/e010-heldout-sealed-labels.json": ROOT / "inputs/e010-heldout-sealed-labels.json",
        PARENT / "inputs/e010-frozen-input-lock.json": ROOT / "inputs/e010-frozen-input-lock.json",
        PARENT / "inputs/e009-v5-bundle-lock.json": ROOT / "inputs/e009-v5-bundle-lock.json",
        PARENT / "inputs/system-observer-v2.txt": ROOT / "inputs/system-observer-v2.txt",
        PARENT / "inputs/observer-output.v2.json": ROOT / "inputs/observer-output.v2.json",
        PARENT / "inputs/chat-template-small.jinja": ROOT / "inputs/chat-template-small.jinja",
        PARENT / "inputs/chat-template-large.jinja": ROOT / "inputs/chat-template-large.jinja",
    }
    for source, destination in copies.items():
        copy_once(source, destination)

    source_lock = read_json(ROOT / "inputs/e010-heldout-frame-lock.json")
    combined_lock = read_json(PARENT_RUN / "frame-lock-candidate-permuted.json")
    base_frames = {entry["frame"]["task_id"]: entry["frame"] for entry in source_lock["frames"]}
    combined_frames = {entry["pair_task_id"]: entry["frame"] for entry in combined_lock["frames"]}
    if len(base_frames) != 16 or base_frames.keys() != combined_frames.keys():
        raise RuntimeError("E010 baseline and E011 combined-permutation frames do not pair")
    treatments = build_conditions(base_frames, combined_frames)
    frame_hashes = {}
    for condition, frames in treatments.items():
        entries = [
            {
                "task_id": frame["task_id"],
                "pair_task_id": task_id,
                "frame_sha256": sha256(canonical(frame)),
                "frame": frame,
            }
            for task_id, frame in zip(base_frames, frames, strict=True)
        ]
        path = RUN / f"frame-lock-{condition}.json"
        write_json(path, {"schema_version": 1, "condition": condition, "frames": entries})
        frame_hashes[condition] = sha256(path.read_bytes())

    parent_hashes = {
        "e011_pre_model_seal_sha256": sha256((PARENT_RUN / "pre-model-seal.json").read_bytes()),
        "e011_output_seal_sha256": sha256((PARENT_RUN / "postrun-output-seal.json").read_bytes()),
        "e011_score_sha256": sha256((PARENT_RUN / "score-e011.json").read_bytes()),
        "e011_candidate_permuted_frame_sha256": sha256((PARENT_RUN / "frame-lock-candidate-permuted.json").read_bytes()),
        "r1_score_sha256": sha256((R1_RUN / "repair-score.json").read_bytes()),
        "r1_output_seal_sha256": sha256((R1_RUN / "postrun-output-seal.json").read_bytes()),
    }
    inputs = {
        path.relative_to(ROOT).as_posix(): sha256(path.read_bytes())
        for path in sorted((ROOT / "inputs").rglob("*"))
        if path.is_file()
    }
    inputs["spec.md"] = sha256((ROOT / "spec.md").read_bytes())
    inputs["scripts/factorial.py"] = sha256(Path(__file__).read_bytes())
    lock = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_MODEL_CONTACT",
        "run_id": RUN_ID,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "same-bank input-factor autopsy; no fitting or promotion",
        "labels": "E010 already-opened labels reused for diagnostic only",
        "observer_bundles": {
            "small": "minicpm5-2b-q8-local-v5",
            "large": "ternary-bonsai-2-27b-ptq1-local-v5",
            "adapter": "none; original E009 v5 action wire contract",
            "thresholds": {"minimum_applicability_milli": MIN_APP, "maximum_abstention_milli": MAX_ABST},
        },
        "conditions": list(CONDITIONS),
        "routing": "small first; large on small rejection or abstention",
        "parent_e011_hashes": parent_hashes,
        "sha256": {"inputs": inputs, "condition_frame_locks": frame_hashes},
    }
    write_json(RUN / "pre-model-input-lock.json", lock)
    print(json.dumps({"run_id": RUN_ID, "state": lock["state"], "tasks_per_condition": 16, "conditions": frame_hashes}, indent=2))


def seal_inputs() -> None:
    lock_path = RUN / "pre-model-input-lock.json"
    seal_path = RUN / "pre-model-seal.json"
    if seal_path.exists():
        raise SystemExit("factorial pre-model seal already exists")
    lock = read_json(lock_path)
    if lock.get("state") != "FROZEN_BEFORE_MODEL_CONTACT":
        raise SystemExit("factorial inputs are not frozen")
    if (RUN / "outputs").exists() or any((RUN / role / "server-process.json").exists() for role in ROLES):
        raise SystemExit("model contact began before factorial sealing")
    for relative, expected in lock["sha256"]["inputs"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise RuntimeError(f"factorial input changed: {relative}")
    parents = lock["parent_e011_hashes"]
    parent_paths = {
        "e011_pre_model_seal_sha256": PARENT_RUN / "pre-model-seal.json",
        "e011_output_seal_sha256": PARENT_RUN / "postrun-output-seal.json",
        "e011_score_sha256": PARENT_RUN / "score-e011.json",
        "e011_candidate_permuted_frame_sha256": PARENT_RUN / "frame-lock-candidate-permuted.json",
        "r1_score_sha256": R1_RUN / "repair-score.json",
        "r1_output_seal_sha256": R1_RUN / "postrun-output-seal.json",
    }
    for key, path in parent_paths.items():
        if sha256(path.read_bytes()) != parents[key]:
            raise RuntimeError(f"parent experiment artifact changed: {path}")
    frame_hashes = {}
    for condition in CONDITIONS:
        path = RUN / f"frame-lock-{condition}.json"
        expected = lock["sha256"]["condition_frame_locks"][condition]
        if sha256(path.read_bytes()) != expected:
            raise RuntimeError(f"factorial frame lock changed: {condition}")
        frame_hashes[condition] = expected
    code_paths = (
        ROOT / "spec.md",
        ROOT / "scripts/factorial.py",
        ROOT / "scripts/start_factorial_observer.ps1",
        ROOT / "scripts/stop_factorial_observer.ps1",
    )
    code_hashes = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()) for path in code_paths}
    seal = {
        "schema_version": 1,
        "state": "SEALED_BEFORE_MODEL_CONTACT",
        "run_id": RUN_ID,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input_lock_sha256": sha256(lock_path.read_bytes()),
        "code_sha256": code_hashes,
        "condition_frame_locks_sha256": frame_hashes,
        "model_contact_started": False,
    }
    write_json(seal_path, seal)
    print(json.dumps({"state": seal["state"], "seal_sha256": sha256(seal_path.read_bytes())}, indent=2))


def verify_run() -> tuple[dict, dict]:
    lock_path = RUN / "pre-model-input-lock.json"
    seal_path = RUN / "pre-model-seal.json"
    lock = read_json(lock_path)
    seal = read_json(seal_path)
    if (
        lock.get("state") != "FROZEN_BEFORE_MODEL_CONTACT"
        or seal.get("state") != "SEALED_BEFORE_MODEL_CONTACT"
        or seal.get("input_lock_sha256") != sha256(lock_path.read_bytes())
    ):
        raise SystemExit("factorial input lock/seal mismatch")
    for relative, expected in seal["code_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise SystemExit(f"factorial code hash mismatch: {relative}")
    for relative, expected in lock["sha256"]["inputs"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise SystemExit(f"factorial input hash mismatch: {relative}")
    parent_paths = {
        "e011_pre_model_seal_sha256": PARENT_RUN / "pre-model-seal.json",
        "e011_output_seal_sha256": PARENT_RUN / "postrun-output-seal.json",
        "e011_score_sha256": PARENT_RUN / "score-e011.json",
        "e011_candidate_permuted_frame_sha256": PARENT_RUN / "frame-lock-candidate-permuted.json",
        "r1_score_sha256": R1_RUN / "repair-score.json",
        "r1_output_seal_sha256": R1_RUN / "postrun-output-seal.json",
    }
    for key, path in parent_paths.items():
        if not path.is_file() or sha256(path.read_bytes()) != lock["parent_e011_hashes"][key]:
            raise SystemExit(f"parent artifact hash mismatch: {key}")
    for condition, expected in seal["condition_frame_locks_sha256"].items():
        path = RUN / f"frame-lock-{condition}.json"
        if sha256(path.read_bytes()) != expected:
            raise SystemExit(f"factorial frame lock mismatch: {condition}")
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


def run_observer(role: str, condition: str, base_url: str, max_tokens: int = 1024) -> None:
    lock, _ = verify_run()
    parsed = urllib.parse.urlparse(base_url)
    if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("factorial observer endpoint must be loopback")
    server = read_json(RUN / role / "server-process.json")
    alias = "e009-small-v5" if role == "small" else "e009-large-v5"
    expected_port = 18489 if role == "small" else 18490
    if server.get("alias") != alias or server.get("base_url") != base_url or server.get("reasoning_mode") != "off":
        raise SystemExit("factorial server does not match the frozen observer identity")
    if urllib.parse.urlparse(base_url).port != expected_port:
        raise SystemExit("factorial observer is running on an unexpected port")

    model_lock = read_json(ROOT / "inputs/e010-frozen-input-lock.json")
    model = next(item for item in model_lock["models"] if item["role"] == role)
    bundle_lock = read_json(ROOT / "inputs/e009-v5-bundle-lock.json")
    bundle = next(item for item in bundle_lock["bundles"] if item["manifest"]["bundle_id"] == model["bundle_id"])
    manifest = bundle["manifest"]
    prompt_path = ROOT / "inputs/system-observer-v2.txt"
    schema_path = ROOT / "inputs/observer-output.v2.json"
    template_path = ROOT / f"inputs/chat-template-{role}.jinja"
    prompt = prompt_path.read_text(encoding="utf-8")
    schema = read_json(schema_path)
    if sha256(prompt_path.read_bytes()) != manifest["system_prompt_sha256"]:
        raise SystemExit("factorial prompt differs from E009 v5")
    if sha256(schema_path.read_bytes()) != manifest["output_schema_sha256"]:
        raise SystemExit("factorial output schema differs from E009 v5")
    if sha256(template_path.read_bytes()) != manifest["chat_template_sha256"]:
        raise SystemExit("factorial chat template differs from E009 v5")
    if (
        server.get("model_sha256") != model["model_sha256"]
        or server.get("runtime_sha256") != model["runtime_sha256"]
        or manifest["maximum_output_tokens"] != max_tokens
    ):
        raise SystemExit("factorial model identity differs from frozen v5")
    runtime_args = server.get("runtime_args", [])
    if "--reasoning" not in runtime_args or runtime_args[runtime_args.index("--reasoning") + 1 :][:1] != ["off"]:
        raise SystemExit("factorial model reasoning must be off")

    frame_lock_path = RUN / f"frame-lock-{condition}.json"
    frame_lock = read_json(frame_lock_path)
    out_dir = RUN / "outputs" / role / condition
    out_dir.mkdir(parents=True, exist_ok=False)
    for entry in frame_lock["frames"]:
        frame = entry["frame"]
        if sha256(canonical(frame)) != entry["frame_sha256"]:
            raise SystemExit(f"factorial frame hash mismatch: {entry['task_id']}")
        payload = {
            "model": alias,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(frame, ensure_ascii=False, separators=(",", ":"))},
            ],
            "temperature": 0,
            "top_p": 1,
            "seed": 0,
            "max_tokens": max_tokens,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "rdc_coding_observer_output_v1", "strict": True, "schema": schema},
            },
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        record: dict = {
            "schema_version": 1,
            "run_id": RUN_ID,
            "condition": condition,
            "role": role,
            "bundle_id": model["bundle_id"],
            "server_alias": alias,
            "server_process_id": server["process_id"],
            "model_sha256": server["model_sha256"],
            "runtime_sha256": server["runtime_sha256"],
            "reasoning_mode": "off",
            "input_lock_sha256": sha256((RUN / "pre-model-input-lock.json").read_bytes()),
            "pre_model_seal_sha256": sha256((RUN / "pre-model-seal.json").read_bytes()),
            "frame_lock_sha256": lock["sha256"]["condition_frame_locks"][condition],
            "frame_sha256": entry["frame_sha256"],
            "task_id": entry["task_id"],
            "request_sha256": sha256(body),
            "request": payload,
            "normalization_contract": manifest["normalization_contract"],
            "thresholds": {"minimum_applicability_milli": MIN_APP, "maximum_abstention_milli": MAX_ABST},
        }
        request = urllib.request.Request(
            base_url.rstrip("/") + "/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                body_response = response.read()
                record["http_status"] = response.status
                response_json = json.loads(body_response)
                record["response"] = response_json
                choices = response_json.get("choices", [])
                content = choices[0].get("message", {}).get("content") if choices else None
                record["content"] = content
                try:
                    record["output"] = json.loads(content) if isinstance(content, str) else None
                except json.JSONDecodeError:
                    record["output"] = None
                record["normalized_output"], record["normalization_error"] = normalize(record["output"])
                record["usage"] = response_json.get("usage", {})
                record["finish_reason"] = choices[0].get("finish_reason") if choices else None
        except urllib.error.HTTPError as error:
            record["http_status"] = error.code
            record["error_body"] = error.read().decode("utf-8", errors="replace")
            record["normalized_output"] = None
            record["normalization_error"] = "http-error"
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
            record["normalized_output"] = None
            record["normalization_error"] = "request-error"
        record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        (out_dir / f"{entry['pair_task_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{role}/{condition} {entry['task_id']} {record.get('http_status', 'ERROR')} {record['elapsed_ms']} ms")


def seal_outputs() -> None:
    _, preseal = verify_run()
    path = RUN / "postrun-output-seal.json"
    if path.exists():
        raise SystemExit("factorial outputs already sealed")
    trees = {}
    for role in ROLES:
        trees[role] = {}
        for condition in CONDITIONS:
            directory = RUN / "outputs" / role / condition
            records = sorted(directory.glob("*.json"))
            if len(records) != 16:
                raise RuntimeError(f"{role}/{condition} expected 16 outputs, found {len(records)}")
            http_ok = normalized = 0
            for record_path in records:
                record = read_json(record_path)
                http_ok += int(record.get("http_status") == 200)
                normalized += int(isinstance(record.get("normalized_output"), dict))
            trees[role][condition] = {
                "record_count": 16,
                "http_success_count": http_ok,
                "normalized_output_count": normalized,
                "tree_sha256": tree_hash(directory),
            }
    output_seal = {
        "schema_version": 1,
        "state": "OUTPUTS_SEALED_BEFORE_SCORING",
        "run_id": RUN_ID,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "pre_model_seal_sha256": sha256((RUN / "pre-model-seal.json").read_bytes()),
        "trees": trees,
    }
    write_json(path, output_seal)
    print(json.dumps(output_seal, indent=2))


def view(record: dict, frame: dict, labels: dict) -> dict:
    output = record.get("normalized_output")
    if not isinstance(output, dict):
        return {"accepted": False, "correct": False, "raw_correct": False, "patch": None, "reason": "invalid-output"}
    choice = output.get("action_choice")
    option = next(
        (item for item in frame["action_options"] if type(choice) is int and item["action"]["id"] == choice),
        None,
    )
    patch = option["patch_sha256"] if option else None
    raw_correct = bool(
        patch and labels["actions_by_patch_sha256"].get(patch, {}).get("expected_task_completion", False)
    )
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
    accepted = reason == "accepted"
    return {
        "accepted": accepted,
        "correct": bool(accepted and raw_correct),
        "raw_correct": raw_correct,
        "patch": patch,
        "reason": reason,
        "elapsed_ms": float(record.get("elapsed_ms", 0.0)),
        "tokens": int(record.get("usage", {}).get("prompt_tokens", 0) or 0)
        + int(record.get("usage", {}).get("completion_tokens", 0) or 0),
    }


def score() -> None:
    lock, preseal = verify_run()
    output_seal = read_json(RUN / "postrun-output-seal.json")
    if (
        output_seal.get("state") != "OUTPUTS_SEALED_BEFORE_SCORING"
        or output_seal.get("pre_model_seal_sha256") != sha256((RUN / "pre-model-seal.json").read_bytes())
    ):
        raise SystemExit("factorial output seal mismatch")
    for role in ROLES:
        for condition in CONDITIONS:
            directory = RUN / "outputs" / role / condition
            seal = output_seal["trees"][role][condition]
            if tree_hash(directory) != seal["tree_sha256"]:
                raise RuntimeError(f"sealed factorial output tree changed: {role}/{condition}")

    base_lock = read_json(ROOT / "inputs/e010-heldout-frame-lock.json")
    base_frames = {item["frame"]["task_id"]: item["frame"] for item in base_lock["frames"]}
    labels = read_json(ROOT / "inputs/e010-heldout-sealed-labels.json")["tasks"]
    repos: dict[str, list[str]] = defaultdict(list)
    for task_id, frame in base_frames.items():
        repos[frame["repository_id"]].append(task_id)
    result = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "scored_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "same-bank factorial diagnosis; shadow-only",
        "thresholds": {"minimum_applicability_milli": MIN_APP, "maximum_abstention_milli": MAX_ABST},
        "conditions": {},
    }
    for condition in CONDITIONS:
        frame_lock = read_json(RUN / f"frame-lock-{condition}.json")
        transformed = {row["pair_task_id"]: row["frame"] for row in frame_lock["frames"]}
        by_role = {}
        for role in ROLES:
            by_role[role] = {}
            for task_id in base_frames:
                record = read_json(RUN / "outputs" / role / condition / f"{task_id}.json")
                if record.get("http_status") != 200:
                    raise RuntimeError(f"observer call failed: {role}/{condition}/{task_id}")
                by_role[role][task_id] = view(record, transformed[task_id], labels[task_id])

        rows = []
        for repository, task_ids in sorted(repos.items()):
            small = [by_role["small"][task] for task in task_ids]
            large = [by_role["large"][task] for task in task_ids]
            hybrid = [
                by_role["small"][task] if by_role["small"][task]["accepted"] else by_role["large"][task]
                for task in task_ids
            ]
            rows.append(
                {
                    "repository": repository,
                    "tasks": len(task_ids),
                    "small": {
                        "coverage": sum(item["accepted"] for item in small),
                        "direct_correct": sum(item["correct"] for item in small),
                        "wrong_accepted": sum(item["accepted"] and not item["raw_correct"] for item in small),
                        "proposal_reasons": dict(Counter(item["reason"] for item in small)),
                        "tokens": sum(item["tokens"] for item in small),
                        "observer_ms": round(sum(item["elapsed_ms"] for item in small), 3),
                    },
                    "large": {
                        "coverage": sum(item["accepted"] for item in large),
                        "direct_correct": sum(item["correct"] for item in large),
                        "wrong_accepted": sum(item["accepted"] and not item["raw_correct"] for item in large),
                        "tokens": sum(item["tokens"] for item in large),
                        "observer_ms": round(sum(item["elapsed_ms"] for item in large), 3),
                    },
                    "hybrid": {
                        "completions": sum(item["correct"] for item in hybrid),
                        "wrong_accepted": sum(item["accepted"] and not item["raw_correct"] for item in hybrid),
                        "large_calls": sum(not by_role["small"][task]["accepted"] for task in task_ids),
                        "large_calls_avoided": sum(by_role["small"][task]["accepted"] for task in task_ids),
                        "tokens": sum(
                            by_role["small"][task]["tokens"]
                            + (by_role["large"][task]["tokens"] if not by_role["small"][task]["accepted"] else 0)
                            for task in task_ids
                        ),
                        "observer_ms": round(sum(
                            by_role["small"][task]["elapsed_ms"]
                            + (by_role["large"][task]["elapsed_ms"] if not by_role["small"][task]["accepted"] else 0.0)
                            for task in task_ids
                        ), 3),
                    },
                    "always_large_completions": sum(item["correct"] for item in large),
                }
            )
        result["conditions"][condition] = rows

    parent = read_json(PARENT_RUN / "score-e011.json")
    combined = {row["repository"]: row for row in parent["conditions"]["candidate-permuted"] if row["repository"] != "POOLED_DESCRIPTIVE"}
    baseline = {row["repository"]: row for row in parent["conditions"]["full-frame"] if row["repository"] != "POOLED_DESCRIPTIVE"}
    canonical = {row["repository"]: row for row in read_json(R1_RUN / "repair-score.json")["repositories"]}
    result["prior_comparison"] = {
        repository: {
            "full_frame": {
                "hybrid": baseline[repository]["shadow_counterfactual_switchboard"]["hybrid_completions"],
                "small_wrong": baseline[repository]["small"]["wrong_accepted"],
            },
            "combined_permutation": {
                "hybrid": combined[repository]["shadow_counterfactual_switchboard"]["hybrid_completions"],
                "small_wrong": combined[repository]["small"]["wrong_accepted"],
            },
            "canonicalization_r1": {
                "hybrid": canonical[repository]["hybrid"]["completions"],
                "small_wrong": canonical[repository]["small"]["wrong_accepted"],
            },
        }
        for repository in sorted(repos)
    }
    write_json(RUN / "factorial-score.json", result)
    (RUN / "factorial-report.md").write_text(render_report(result), encoding="utf-8")
    print(json.dumps({"report": str(RUN / "factorial-report.md")}, indent=2))


def render_report(result: dict) -> str:
    lines = [
        "# E011-R2 — Candidate Presentation Factorial",
        "",
        f"- Run: {result['run_id']}",
        "- E009 v5 weights, prompt, output schema, normalization, and thresholds unchanged.",
        "- Same E010 tasks and already-opened labels; shadow-only paired diagnosis.",
        "",
        "## Repository-level results",
        "",
        "| Condition | Repository | Small coverage | Direct precision | Wrong small actions | Hybrid | Always large | Large calls avoided |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition, rows in result["conditions"].items():
        for row in rows:
            small = row["small"]
            direct_precision = (
                "n/a" if small["coverage"] == 0 else
                f"{small['direct_correct']}/{small['coverage']} ({100 * small['direct_correct'] / small['coverage']:.1f}%)"
            )
            lines.append(
                f"| {condition} | {row['repository']} | {small['coverage']}/{row['tasks']} | "
                f"{direct_precision} | {small['wrong_accepted']} | "
                f"{row['hybrid']['completions']}/{row['tasks']} | "
                f"{row['always_large_completions']}/{row['tasks']} | {row['hybrid']['large_calls_avoided']} |"
            )
    lines.extend(["", "## Prior conditions", ""])
    lines.append("| Repository | E010 full hybrid / small errors | E011 combined permutation hybrid / small errors | E011-R1 canonical hybrid / small errors |")
    lines.append("| --- | ---: | ---: | ---: |")
    for repository, row in result["prior_comparison"].items():
        full = row["full_frame"]
        combined = row["combined_permutation"]
        canonical = row["canonicalization_r1"]
        lines.append(
            f"| {repository} | {full['hybrid']}/8 / {full['small_wrong']} | "
            f"{combined['hybrid']}/8 / {combined['small_wrong']} | "
            f"{canonical['hybrid']}/8 / {canonical['small_wrong']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "IDs-only preserves E010 option positions while replacing the numeric IDs with the exact fresh IDs from E011's combined permutation. Order-only uses the exact E011 shuffled positions while restoring original E010 IDs. The paired differences localize presentation sensitivity on this bank. They do not establish broad transfer or internal model mechanism.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "seal", "run", "seal-outputs", "score"))
    parser.add_argument("--role", choices=ROLES)
    parser.add_argument("--condition", choices=CONDITIONS)
    parser.add_argument("--base-url")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "seal":
        seal_inputs()
    elif args.command == "run":
        if not all((args.role, args.condition, args.base_url)):
            raise SystemExit("run requires --role, --condition, and --base-url")
        run_observer(args.role, args.condition, args.base_url)
    elif args.command == "seal-outputs":
        seal_outputs()
    else:
        score()


if __name__ == "__main__":
    main()
