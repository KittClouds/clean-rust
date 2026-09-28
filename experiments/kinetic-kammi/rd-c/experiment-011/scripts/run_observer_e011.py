from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011")
RUN_ID = "e011-20260925-causal-evidence-01"
RUN = ROOT / "artifacts/runs" / RUN_ID
E010_FROZEN = ROOT / "inputs/e010-frozen-input-lock.json"
CONDITIONS = (
    "evidence-masked",
    "evidence-swapped",
    "repository-neutralized",
    "candidate-permuted",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_output(raw: object, contract: str) -> tuple[dict | None, str | None]:
    if not isinstance(raw, dict):
        return None, "invalid-output-object"
    if contract != "percent-0-100-to-milli-x10-v1+line-endings-lf-v1":
        return None, "unknown-normalization-contract"
    choice = raw.get("action_choice")
    app = raw.get("applicability_percent")
    abst = raw.get("abstention_percent")
    if choice is not None and (type(choice) is not int or not 0 <= choice <= 65535):
        return None, "invalid-action-choice"
    if type(app) is not int or type(abst) is not int or not 0 <= app <= 100 or not 0 <= abst <= 100:
        return None, "score-outside-percent-range"
    return {
        "action_choice": choice,
        "applicability_milli": app * 10,
        "abstention_milli": abst * 10,
    }, None


def verify_pre_model_lock(lock: dict) -> None:
    if lock.get("state") != "FROZEN_BEFORE_MODEL_CONTACT" or lock.get("run_id") != RUN_ID:
        raise SystemExit("E011 input lock is missing, unfrozen, or belongs to another run")
    for relative, expected in lock["sha256"]["inputs"].items():
        if relative.startswith("e010-"):
            continue
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise SystemExit(f"frozen input hash mismatch: {relative}")
    if sha256(E010_FROZEN.read_bytes()) != lock["sha256"]["inputs"]["inputs/e010-frozen-input-lock.json"]:
        raise SystemExit("copied E010 lock digest mismatch")
    seal_path = RUN / "pre-model-seal.json"
    seal = read_json(seal_path)
    if (
        seal.get("state") != "SEALED_BEFORE_MODEL_CONTACT"
        or seal.get("run_id") != RUN_ID
        or seal.get("frozen_input_lock_sha256") != sha256((RUN / "frozen-input-lock.json").read_bytes())
    ):
        raise SystemExit("E011 pre-model seal is missing or does not match the frozen lock")
    for relative, expected in seal["code_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise SystemExit(f"frozen E011 code hash mismatch: {relative}")
    for role, expected in seal["e010_baseline_tree_sha256"].items():
        directory = RUN / "full-frame-baseline" / role
        digest = hashlib.sha256()
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        if digest.hexdigest() != expected:
            raise SystemExit(f"copied E010 {role} baseline changed after sealing")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=("small", "large"))
    parser.add_argument("--condition", required=True, choices=CONDITIONS)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    frozen_path = RUN / "frozen-input-lock.json"
    frozen = read_json(frozen_path)
    verify_pre_model_lock(frozen)

    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("observer endpoint must be loopback")
    server = read_json(RUN / args.role / "server-process.json")
    expected_alias = "e009-small-v5" if args.role == "small" else "e009-large-v5"
    if (
        server.get("reasoning_mode") != "off"
        or server.get("alias") != expected_alias
        or server.get("base_url", "").rstrip("/") != args.base_url.rstrip("/")
    ):
        raise SystemExit("running service differs from frozen E009 observer identity")

    e010_frozen = read_json(E010_FROZEN)
    model = next(item for item in e010_frozen["models"] if item["role"] == args.role)
    bundle_lock_path = ROOT / "inputs/e009-v5-bundle-lock.json"
    bundle_lock_bytes = bundle_lock_path.read_bytes()
    bundle_lock = json.loads(bundle_lock_bytes)
    bundle_item = next(
        item for item in bundle_lock["bundles"]
        if item["manifest"]["bundle_id"] == model["bundle_id"]
    )
    manifest = bundle_item["manifest"]
    if (
        sha256(bundle_lock_bytes) != model["bundle_lock_sha256"]
        or bundle_item["blake3"] != model["bundle_blake3"]
        or manifest["bundle_id"] != model["bundle_id"]
        or manifest["reasoning_mode"] != "off"
        or manifest["maximum_output_tokens"] != args.max_tokens
        or manifest["normalization_contract"] != frozen["model_bundles"]["normalization"]
    ):
        raise SystemExit("observer bundle differs from the E009 v5 frozen identity")

    prompt_path = ROOT / "inputs/system-observer-v2.txt"
    schema_path = ROOT / "inputs/observer-output.v2.json"
    prompt = prompt_path.read_text(encoding="utf-8")
    schema = read_json(schema_path)
    prompt_hash = sha256(prompt_path.read_bytes())
    schema_hash = sha256(schema_path.read_bytes())
    if prompt_hash != manifest["system_prompt_sha256"] or schema_hash != manifest["output_schema_sha256"]:
        raise SystemExit("prompt or output schema differs from frozen observer bundle")
    template = ROOT / f"inputs/chat-template-{args.role}.jinja"
    if sha256(template.read_bytes()) != manifest["chat_template_sha256"]:
        raise SystemExit("captured chat template differs from frozen observer bundle")
    if server.get("runtime_sha256") != model["runtime_sha256"] or server.get("model_sha256") != model["model_sha256"]:
        raise SystemExit("running runtime/model hashes differ from frozen model bundle")
    runtime_args = server.get("runtime_args", [])
    if "--reasoning" not in runtime_args:
        raise SystemExit("observer service lacks an explicit reasoning-mode argument")
    if runtime_args[runtime_args.index("--reasoning") + 1 : runtime_args.index("--reasoning") + 2] != ["off"]:
        raise SystemExit("observer service is not running with reasoning disabled")

    frame_lock_path = RUN / f"frame-lock-{args.condition}.json"
    expected_lock_hash = frozen["sha256"]["transformed_frame_locks"][args.condition]
    if sha256(frame_lock_path.read_bytes()) != expected_lock_hash:
        raise SystemExit("transformed frame lock differs from pre-model seal")
    frame_lock = read_json(frame_lock_path)
    output_dir = RUN / "outputs" / args.role / args.condition
    output_dir.mkdir(parents=True, exist_ok=False)

    for entry in frame_lock["frames"]:
        frame = entry["frame"]
        if sha256(canonical(frame)) != entry["frame_sha256"]:
            raise SystemExit(f"frame digest mismatch: {entry['task_id']}")
        payload = {
            "model": model["server_alias"],
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(frame, ensure_ascii=False, separators=(",", ":"))},
            ],
            "temperature": 0,
            "top_p": 1,
            "seed": 0,
            "max_tokens": args.max_tokens,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "rdc_coding_observer_output_v1",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        record: dict = {
            "schema_version": 1,
            "run_id": RUN_ID,
            "condition": args.condition,
            "role": args.role,
            "bundle_id": model["bundle_id"],
            "bundle_blake3": model["bundle_blake3"],
            "frozen_input_lock_sha256": sha256(frozen_path.read_bytes()),
            "frame_lock_sha256": expected_lock_hash,
            "frame_sha256": entry["frame_sha256"],
            "task_id": entry["task_id"],
            "pair_task_id": entry["pair_task_id"],
            "server_alias": model["server_alias"],
            "server_process_id": server["process_id"],
            "runtime_sha256": server["runtime_sha256"],
            "model_sha256": server["model_sha256"],
            "reasoning_mode": "off",
            "chat_template_sha256": manifest["chat_template_sha256"],
            "maximum_output_tokens": args.max_tokens,
            "system_prompt_sha256": prompt_hash,
            "output_schema_sha256": schema_hash,
            "normalization_contract": manifest["normalization_contract"],
            "thresholds": {
                "minimum_applicability_milli": 850,
                "maximum_abstention_milli": 150,
            },
            "request_sha256": sha256(body),
            "request": payload,
        }
        request = urllib.request.Request(
            args.base_url.rstrip("/") + "/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                response_body = response.read()
                record["http_status"] = response.status
                response_json = json.loads(response_body)
                record["response"] = response_json
                choices = response_json.get("choices", [])
                content = choices[0].get("message", {}).get("content") if choices else None
                record["content"] = content
                try:
                    record["output"] = json.loads(content) if isinstance(content, str) else None
                except json.JSONDecodeError:
                    record["output"] = None
                record["normalized_output"], record["normalization_error"] = normalize_output(
                    record["output"], manifest["normalization_contract"]
                )
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
        result_path = output_dir / f"{entry['pair_task_id']}.json"
        result_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{args.role}/{args.condition} {entry['pair_task_id']} {record.get('http_status', 'ERROR')} {record['elapsed_ms']} ms")


if __name__ == "__main__":
    main()
