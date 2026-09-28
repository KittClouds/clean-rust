from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=("small", "large"))
    parser.add_argument("--stage", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--bundle-lock", required=True)
    parser.add_argument("--frame-lock", required=True)
    parser.add_argument("--frozen-lock", required=True)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    run_path = ROOT / "artifacts" / "runs" / args.run_id
    frozen_path = resolve_path(args.frozen_lock)
    frozen = read_json(frozen_path)
    if frozen.get("state") != "FROZEN_BEFORE_MODEL_CONTACT":
        raise SystemExit("input lock is not frozen for model contact")
    if frozen.get("run_id") != args.run_id:
        raise SystemExit("input lock run ID does not match request")

    frame_lock_path = resolve_path(args.frame_lock)
    frame_hash = sha256(frame_lock_path.read_bytes())
    expected_frame_hash = frozen.get("sha256", {}).get("dev_frame_lock" if args.stage.startswith("dev-") else "heldout_frame_lock")
    if frame_hash != expected_frame_hash:
        raise SystemExit("selected frame lock does not match frozen hash")

    prompt_path = ROOT / "prompts" / "system-observer-v2.txt"
    schema_path = ROOT / "schemas" / "observer-output.v2.json"
    prompt = prompt_path.read_text(encoding="utf-8")
    schema = read_json(schema_path)
    prompt_hash = sha256(prompt_path.read_bytes())
    schema_hash = sha256(schema_path.read_bytes())
    expected_hashes = frozen.get("sha256", {})
    if prompt_hash != expected_hashes.get("system_prompt") or schema_hash != expected_hashes.get("output_schema"):
        raise SystemExit("prompt or output schema differs from frozen input lock")

    bundle_path = resolve_path(args.bundle_lock)
    bundle_lock_bytes = bundle_path.read_bytes()
    bundle_lock = json.loads(bundle_lock_bytes)
    bundle_item = next(
        (item for item in bundle_lock.get("bundles", []) if item["manifest"]["bundle_id"] == args.bundle_id),
        None,
    )
    if bundle_item is None:
        raise SystemExit("requested bundle ID is absent from the supplied lock")
    manifest = bundle_item["manifest"]
    expected_model = next(
        (item for item in frozen.get("models", []) if item.get("role") == args.role and item.get("bundle_id") == args.bundle_id),
        None,
    )
    if expected_model is None:
        raise SystemExit("bundle is not authorized by this frozen input lock")
    if expected_model.get("server_alias") != args.model:
        raise SystemExit("requested server alias is not authorized by the frozen bundle record")
    if (
        expected_model.get("bundle_blake3") != bundle_item.get("blake3")
        or expected_model.get("bundle_lock_sha256") != sha256(bundle_lock_bytes)
        or expected_model.get("bundle_lock_path") != str(bundle_path.relative_to(ROOT)).replace("\\", "/")
    ):
        raise SystemExit("bundle digest or lock path differs from frozen input lock")
    if (
        manifest.get("reasoning_mode") != "off"
        or manifest.get("maximum_output_tokens") != args.max_tokens
        or manifest.get("system_prompt_sha256") != prompt_hash
        or manifest.get("output_schema_sha256") != schema_hash
        or manifest.get("output_schema") != "rdc-coding-observer-output.v2"
        or manifest.get("normalization_contract") != "percent-0-100-to-milli-x10-v1+line-endings-lf-v1"
    ):
        raise SystemExit("bundle does not bind the expected corrected observer settings")

    template_path = ROOT / expected_model["chat_template_path"]
    if sha256(template_path.read_bytes()) != manifest.get("chat_template_sha256"):
        raise SystemExit("captured chat template differs from bundle identity")

    server_role_path = run_path / args.role / "server-process.json"
    server_lock = read_json(server_role_path)
    runtime_args = server_lock.get("runtime_args", [])
    if (
        server_lock.get("reasoning_mode") != "off"
        or "--reasoning" not in runtime_args
        or runtime_args[runtime_args.index("--reasoning") + 1 : runtime_args.index("--reasoning") + 2] != ["off"]
        or server_lock.get("alias") != args.model
        or server_lock.get("base_url", "").rstrip("/") != args.base_url.rstrip("/")
    ):
        raise SystemExit("running observer service does not match the frozen reasoning-off runtime")

    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("observer endpoint must be loopback")

    frames = read_json(frame_lock_path)["frames"]
    output_dir = run_path / args.stage
    output_dir.mkdir(parents=True, exist_ok=False)
    for locked in frames:
        frame = locked["frame"]
        payload = {
            "model": args.model,
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
                "json_schema": {"name": "rdc_coding_observer_output_v1", "strict": True, "schema": schema},
            },
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        record: dict = {
            "schema_version": 1,
            "run_id": args.run_id,
            "stage": args.stage,
            "role": args.role,
            "bundle_id": args.bundle_id,
            "bundle_blake3": bundle_item["blake3"],
            "bundle_lock_sha256": sha256(bundle_lock_bytes),
            "frozen_input_lock_sha256": sha256(frozen_path.read_bytes()),
            "frame_lock_sha256": frame_hash,
            "frame_blake3": locked["blake3"],
            "task_id": frame["task_id"],
            "server_alias": args.model,
            "server_process_id": server_lock["process_id"],
            "server_runtime_args": runtime_args,
            "reasoning_mode": server_lock["reasoning_mode"],
            "chat_template_sha256": manifest["chat_template_sha256"],
            "maximum_output_tokens": args.max_tokens,
            "system_prompt_sha256": prompt_hash,
            "output_schema_sha256": schema_hash,
            "normalization_contract": manifest["normalization_contract"],
            "thresholds": {
                "minimum_applicability_milli": manifest["minimum_applicability_milli"],
                "maximum_abstention_milli": manifest["maximum_abstention_milli"],
            },
            "model": args.model,
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
                choice = choices[0] if choices else {}
                record["finish_reason"] = choice.get("finish_reason")
        except urllib.error.HTTPError as error:
            record["http_status"] = error.code
            record["error_body"] = error.read().decode("utf-8", errors="replace")
            record["normalized_output"] = None
            record["normalization_error"] = "http-error"
        except Exception as error:  # preserve an endpoint failure as one observation
            record["error"] = f"{type(error).__name__}: {error}"
            record["normalized_output"] = None
            record["normalization_error"] = "request-error"
        record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        result_path = output_dir / f"{frame['task_id']}.json"
        result_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{args.stage} {frame['task_id']} {record.get('http_status', 'ERROR')} {record['elapsed_ms']} ms")


if __name__ == "__main__":
    main()
