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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--run-id", default="e009-20260925-pilot-01")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--bundle-lock", required=True)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--task-ids", nargs="*")
    args = parser.parse_args()
    run_path = ROOT / "artifacts" / "runs" / args.run_id
    frozen = json.loads((run_path / "frozen-input-lock.json").read_text(encoding="utf-8"))
    if frozen.get("state") != "FROZEN_BEFORE_MODEL_CONTACT":
        raise SystemExit("run is not locked for model contact")
    status_path = run_path / "run-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    amendment = status.get("protocol_amendment")
    if (
        status.get("state") not in {
            "AMENDED_CONTINUATION_PENDING_REASONING_OFF_RETRY",
            "AMENDED_CONTINUATION_IN_PROGRESS",
        }
        or amendment != "DECODING_AMENDMENT.md#v3"
        or status.get("original_frozen_output_tokens") != frozen.get("decoding", {}).get("maximum_output_tokens")
        or status.get("amended_output_tokens") != args.max_tokens
        or status.get("amended_reasoning_mode") != "off"
        or args.max_tokens != 1024
        or not status.get("prior_attempts_preserved_and_excluded")
    ):
        raise SystemExit("run status does not authorize the recorded 1024-token reasoning-off continuation")
    expected_inputs = {
        "system_prompt": ROOT / "prompts" / "system-observer-v1.txt",
        "output_schema": ROOT / "schemas" / "observer-output.v1.json",
        "frame_lock": ROOT / "tasks" / "frames" / "frame-lock.json",
    }
    for key, path in expected_inputs.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != frozen["sha256"][key]:
            raise SystemExit(f"locked input hash changed: {key}")
    bundle_lock_path = Path(args.bundle_lock)
    if not bundle_lock_path.is_absolute():
        bundle_lock_path = ROOT / bundle_lock_path
    bundle_lock = json.loads(bundle_lock_path.read_text(encoding="utf-8"))
    bundle = next(
        (item for item in bundle_lock["bundles"] if item["manifest"]["bundle_id"] == args.bundle_id),
        None,
    )
    if bundle is None or bundle["manifest"]["maximum_output_tokens"] != args.max_tokens:
        raise SystemExit("bundle ID or amended output budget does not match")
    original_bundle_path = run_path / "protocol-source" / "models" / "bundle-lock.json"
    if not original_bundle_path.is_file():
        raise SystemExit("original pre-contact bundle manifest is not archived")
    original_bytes = original_bundle_path.read_bytes()
    if hashlib.sha256(original_bytes).hexdigest() != frozen["sha256"]["bundle_lock"]:
        raise SystemExit("archived pre-contact bundle manifest does not match the frozen lock")
    original_lock = json.loads(original_bytes)
    original_bundle = next(
        (item for item in original_lock["bundles"] if item["manifest"]["bundle_id"] == args.bundle_id),
        None,
    )
    if original_bundle is None:
        raise SystemExit("requested bundle ID is absent from the pre-contact manifest")
    original_manifest = dict(original_bundle["manifest"])
    amended_manifest = dict(bundle["manifest"])
    if original_manifest.pop("maximum_output_tokens") != frozen["decoding"]["maximum_output_tokens"]:
        raise SystemExit("pre-contact bundle budget disagrees with the frozen run")
    if amended_manifest.pop("maximum_output_tokens") != args.max_tokens or amended_manifest != original_manifest:
        raise SystemExit("bundle amendment changed fields beyond maximum_output_tokens")
    expected_model = next(
        (item for item in frozen["models"] if item["bundle_id"] == args.bundle_id),
        None,
    )
    if expected_model is None or expected_model["bundle_blake3"] != original_bundle["blake3"]:
        raise SystemExit("requested observer does not match the pre-contact frozen run")
    current_bundle_lock_sha256 = hashlib.sha256(bundle_lock_path.read_bytes()).hexdigest()

    server_role = "small" if args.bundle_id.startswith("minicpm") else "large"
    server_lock_path = run_path / server_role / "server-process.json"
    if not server_lock_path.is_file():
        raise SystemExit(f"missing {server_role} observer process lock")
    server_lock = json.loads(server_lock_path.read_text(encoding="utf-8"))
    runtime_args = server_lock.get("runtime_args", [])
    if (
        server_lock.get("reasoning_mode") != "off"
        or "--reasoning" not in runtime_args
        or runtime_args[runtime_args.index("--reasoning") + 1 : runtime_args.index("--reasoning") + 2] != ["off"]
        or server_lock.get("alias") != args.model
        or server_lock.get("base_url", "").rstrip("/") != args.base_url.rstrip("/")
    ):
        raise SystemExit("observer server lock does not match the amended reasoning-off configuration")

    host = urllib.parse.urlparse(args.base_url).hostname
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("observer endpoint must be loopback")
    output_dir = run_path / args.stage
    output_dir.mkdir(parents=True, exist_ok=False)

    frames = json.loads((ROOT / "tasks" / "frames" / "frame-lock.json").read_text(encoding="utf-8"))["frames"]
    system_prompt = (ROOT / "prompts" / "system-observer-v1.txt").read_text(encoding="utf-8")
    schema = json.loads((ROOT / "schemas" / "observer-output.v1.json").read_text(encoding="utf-8"))

    selected_ids = set(args.task_ids or [])
    selected_frames = [
        locked for locked in frames if not selected_ids or locked["frame"]["task_id"] in selected_ids
    ]
    if selected_ids and {locked["frame"]["task_id"] for locked in selected_frames} != selected_ids:
        raise SystemExit("unknown task ID requested")
    for locked in selected_frames:
        frame = locked["frame"]
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(frame, ensure_ascii=False, separators=(",", ":"))},
        ]
        payload = {
            "model": args.model,
            "messages": messages,
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
            "stage": args.stage,
            "run_id": args.run_id,
            "protocol_amendment_id": amendment,
            "prior_output_budget_tokens": frozen["decoding"]["maximum_output_tokens"],
            "output_budget_tokens": args.max_tokens,
            "original_frozen_bundle_blake3": original_bundle["blake3"],
            "amended_bundle_lock_sha256": current_bundle_lock_sha256,
            "server_reasoning_mode": server_lock["reasoning_mode"],
            "server_process_id": server_lock["process_id"],
            "server_runtime_args": runtime_args,
            "role": args.bundle_id,
            "model": args.model,
            "bundle_id": args.bundle_id,
            "bundle_blake3": bundle["blake3"],
            "task_id": frame["task_id"],
            "frame_blake3": locked["blake3"],
            "request_sha256": hashlib.sha256(body).hexdigest(),
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
                record["usage"] = response_json.get("usage", {})
        except urllib.error.HTTPError as error:
            record["http_status"] = error.code
            record["error_body"] = error.read().decode("utf-8", errors="replace")
        except Exception as error:  # preserve endpoint failure as data; do not retry
            record["error"] = f"{type(error).__name__}: {error}"
        record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        output_path = output_dir / f"{frame['task_id']}.json"
        output_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{args.stage} {frame['task_id']} {record.get('http_status', 'ERROR')} {record['elapsed_ms']} ms")


if __name__ == "__main__":
    main()
