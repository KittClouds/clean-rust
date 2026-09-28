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
E010 = Path(r"C:\rd-c\experiment-010")
REPAIR = ROOT / "repairs" / "producer-order-v1"
RUN_ID = "e011-producer-order-integration-qual-01"
RUN = REPAIR / "artifacts" / "runs" / RUN_ID


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_output(raw: object) -> tuple[dict | None, str | None]:
    if not isinstance(raw, dict):
        return None, "invalid-output-object"
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
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    frozen_path = RUN / "frozen-input-lock.json"
    prepared_path = RUN / "prepared-frame-lock.json"
    frozen = read_json(frozen_path)
    if frozen.get("state") != "FROZEN_BEFORE_MODEL_CONTACT" or frozen.get("run_id") != RUN_ID:
        raise SystemExit("E011 runtime input lock is not frozen for this run")
    if sha256(prepared_path.read_bytes()) != frozen["sha256"]["prepared_frame_lock"]:
        raise SystemExit("prepared presentation lock changed after freeze")
    prompt_path = Path(frozen["prompt_path"])
    schema_path = Path(frozen["schema_path"])
    if sha256(prompt_path.read_bytes()) != frozen["sha256"]["system_prompt"]:
        raise SystemExit("system prompt changed after freeze")
    if sha256(schema_path.read_bytes()) != frozen["sha256"]["output_schema"]:
        raise SystemExit("observer output schema changed after freeze")
    prompt = prompt_path.read_text(encoding="utf-8")
    schema = read_json(schema_path)
    model_record = next((item for item in frozen["models"] if item["role"] == args.role), None)
    if model_record is None:
        raise SystemExit(f"no frozen {args.role} model record")
    bundle_path = Path(frozen["bundle_lock_path"])
    if sha256(bundle_path.read_bytes()) != frozen["sha256"]["bundle_lock"]:
        raise SystemExit("v5 bundle lock changed after freeze")
    bundle_lock = read_json(bundle_path)
    bundle = next(
        (item for item in bundle_lock["bundles"] if item["manifest"]["bundle_id"] == model_record["bundle_id"]),
        None,
    )
    if bundle is None:
        raise SystemExit("v5 bundle is missing from the frozen bundle lock")
    manifest = bundle["manifest"]
    if bundle.get("blake3") != model_record["bundle_blake3"]:
        raise SystemExit("observer bundle digest differs from the frozen model record")
    if (
        manifest.get("reasoning_mode") != frozen["reasoning_mode"]
        or manifest.get("maximum_output_tokens") != frozen["maximum_output_tokens"]
        or manifest.get("system_prompt_sha256") != frozen["sha256"]["system_prompt"]
        or manifest.get("output_schema_sha256") != frozen["sha256"]["output_schema"]
        or manifest.get("normalization_contract") != frozen["normalization_contract"]
        or manifest.get("minimum_applicability_milli") != frozen["thresholds"]["minimum_applicability_milli"]
        or manifest.get("maximum_abstention_milli") != frozen["thresholds"]["maximum_abstention_milli"]
    ):
        raise SystemExit("v5 bundle does not match the frozen E009 observer contract")
    template_path = E010 / model_record["chat_template_path"]
    if sha256(template_path.read_bytes()) != manifest.get("chat_template_sha256"):
        raise SystemExit("captured chat template differs from the frozen bundle")

    server_path = RUN / args.role / "server-process.json"
    server = read_json(server_path)
    runtime_args = server.get("runtime_args", [])
    base_url = server.get("base_url", "")
    parsed = urllib.parse.urlparse(base_url)
    if (
        server.get("reasoning_mode") != "off"
        or server.get("alias") != model_record["server_alias"]
        or server.get("runtime_sha256") != model_record["runtime_sha256"]
        or server.get("model_sha256") != model_record["model_sha256"]
        or "--reasoning" not in runtime_args
        or runtime_args[runtime_args.index("--reasoning") + 1 : runtime_args.index("--reasoning") + 2] != ["off"]
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
    ):
        raise SystemExit("running observer does not match the frozen v5 runtime identity")

    output_dir = RUN / "observations" / args.role
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"refusing to overwrite {args.role} observer outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared = read_json(prepared_path)["rows"]
    for row in prepared:
        frame = row["observer_frame"]
        presentation = row["presentation"]
        payload = {
            "model": model_record["server_alias"],
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(frame, ensure_ascii=False, separators=(",", ":"))},
            ],
            "temperature": 0,
            "top_p": 1,
            "seed": 0,
            "max_tokens": frozen["maximum_output_tokens"],
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
            "role": args.role,
            "bundle_id": model_record["bundle_id"],
            "task_id": row["task_id"],
            "repository_id": row["repository_id"],
            "frame_blake3": row["frame_blake3"],
            "serialized_frame_sha256": row["serialized_frame_sha256"],
            "normalization_contract": frozen["normalization_contract"],
            "thresholds": frozen["thresholds"],
            "server_alias": server["alias"],
            "server_process_id": server["process_id"],
            "server_runtime_args": runtime_args,
            "reasoning_mode": server["reasoning_mode"],
            "chat_template_sha256": manifest["chat_template_sha256"],
            "maximum_output_tokens": frozen["maximum_output_tokens"],
            "system_prompt_sha256": frozen["sha256"]["system_prompt"],
            "output_schema_sha256": frozen["sha256"]["output_schema"],
            "observer_rpc_request": {
                "request_id_hex": presentation["request_id_hex"],
                "receipt_digest_hex": presentation["receipt_digest_hex"],
                "presentation_receipt_hex": presentation["receipt_hex"],
                "frame_blake3": row["frame_blake3"],
            },
            "request_sha256": sha256(body),
            "request": payload,
        }
        request = urllib.request.Request(
            base_url.rstrip("/") + "/v1/chat/completions",
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
                record["normalized_output"], record["normalization_error"] = normalize_output(record["output"])
                record["usage"] = response_json.get("usage", {})
                choice = choices[0] if choices else {}
                record["finish_reason"] = choice.get("finish_reason")
                # The synchronous caller associates this HTTP response with its request envelope.
                record["observer_rpc_response"] = {
                    "request_id_hex": presentation["request_id_hex"],
                    "receipt_digest_hex": presentation["receipt_digest_hex"],
                    "pairing": "synchronous response to the recorded request ID",
                }
        except urllib.error.HTTPError as error:
            record["http_status"] = error.code
            record["error_body"] = error.read().decode("utf-8", errors="replace")
            record["normalized_output"] = None
            record["normalization_error"] = "http-error"
        except Exception as error:  # preserve endpoint failures as an observation
            record["error"] = f"{type(error).__name__}: {error}"
            record["normalized_output"] = None
            record["normalization_error"] = "request-error"
        record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        result_path = output_dir / f"{row['task_id']}.json"
        result_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{args.role} {row['task_id']} {record.get('http_status', 'ERROR')} {record['elapsed_ms']} ms")


if __name__ == "__main__":
    main()
