from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011\repairs\candidate-canonicalization-v1")
RUN_ID = "e011-r1-20260925-candidate-canonicalization-01"
RUN = ROOT / "artifacts/runs" / RUN_ID


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


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


def verify_seal() -> tuple[dict, dict]:
    lock_path = RUN / "pre-model-input-lock.json"
    seal_path = RUN / "pre-model-seal.json"
    lock = read_json(lock_path)
    seal = read_json(seal_path)
    if (
        lock.get("state") != "FROZEN_BEFORE_MODEL_CONTACT"
        or seal.get("state") != "SEALED_BEFORE_MODEL_CONTACT"
        or seal.get("run_id") != RUN_ID
        or seal.get("input_lock_sha256") != sha256(lock_path.read_bytes())
    ):
        raise SystemExit("repair pre-model lock/seal mismatch")
    for relative, expected in seal["code_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise SystemExit(f"repair code hash mismatch: {relative}")
    if sha256((RUN / "canonical-frame-lock.json").read_bytes()) != seal["canonical_frame_lock_sha256"]:
        raise SystemExit("canonical frame lock differs from repair seal")
    return lock, seal


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=("small", "large"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    lock, seal = verify_seal()
    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("repair observer endpoint must be loopback")

    server = read_json(RUN / args.role / "server-process.json")
    alias = "e009-small-v5" if args.role == "small" else "e009-large-v5"
    if server.get("alias") != alias or server.get("reasoning_mode") != "off" or server.get("base_url") != args.base_url:
        raise SystemExit("repair server process differs from the frozen v5 observer")
    model_lock = read_json(ROOT / "inputs/e010-frozen-input-lock.json")
    model = next(item for item in model_lock["models"] if item["role"] == args.role)
    identities = read_json(ROOT / "observer-adapter-identities.json")
    bundle_id = identities[f"{args.role}_bundle_id"]

    prompt_path = ROOT / "inputs/system-observer-v2.txt"
    schema_path = ROOT / "inputs/observer-output.v2.json"
    prompt = prompt_path.read_text(encoding="utf-8")
    schema = read_json(schema_path)
    bundle_lock = read_json(ROOT / "inputs/e009-v5-bundle-lock.json")
    bundle = next(item for item in bundle_lock["bundles"] if item["manifest"]["bundle_id"] == model["bundle_id"])
    manifest = bundle["manifest"]
    if manifest["maximum_output_tokens"] != args.max_tokens or manifest["reasoning_mode"] != "off":
        raise SystemExit("base model bundle changed from E009 v5")
    if sha256(prompt_path.read_bytes()) != manifest["system_prompt_sha256"]:
        raise SystemExit("frozen prompt hash mismatch")
    if sha256(schema_path.read_bytes()) != manifest["output_schema_sha256"]:
        raise SystemExit("frozen output schema hash mismatch")
    if server.get("model_sha256") != model["model_sha256"] or server.get("runtime_sha256") != model["runtime_sha256"]:
        raise SystemExit("repair observer weights/runtime differ from E009 v5")
    template = ROOT / f"inputs/chat-template-{args.role}.jinja"
    if sha256(template.read_bytes()) != manifest["chat_template_sha256"]:
        raise SystemExit("captured chat template hash mismatch")

    frame_lock_path = RUN / "canonical-frame-lock.json"
    frame_lock = read_json(frame_lock_path)
    output_dir = RUN / "outputs" / args.role
    output_dir.mkdir(parents=True, exist_ok=False)
    for entry in frame_lock["frames"]:
        frame = entry["frame"]
        if sha256(canonical(frame)) != entry["frame_sha256"]:
            raise SystemExit(f"canonical frame digest mismatch: {entry['task_id']}")
        payload = {
            "model": alias,
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
        receipt = entry["receipt_full_frame"]
        by_id = {row["canonical_action_id"]: row for row in receipt}
        record: dict = {
            "schema_version": 1,
            "run_id": RUN_ID,
            "role": args.role,
            "bundle_id": bundle_id,
            "base_weight_bundle_id": model["bundle_id"],
            "input_adapter_id": "candidate-canonicalization-v1",
            "pre_model_seal_sha256": sha256((RUN / "pre-model-seal.json").read_bytes()),
            "frame_lock_sha256": lock["sha256"]["canonical_frame_lock"],
            "frame_sha256": entry["frame_sha256"],
            "task_id": entry["task_id"],
            "server_alias": alias,
            "server_process_id": server["process_id"],
            "model_sha256": server["model_sha256"],
            "runtime_sha256": server["runtime_sha256"],
            "reasoning_mode": "off",
            "maximum_output_tokens": args.max_tokens,
            "system_prompt_sha256": sha256(prompt_path.read_bytes()),
            "output_schema_sha256": sha256(schema_path.read_bytes()),
            "normalization_contract": manifest["normalization_contract"],
            "thresholds": {"minimum_applicability_milli": 850, "maximum_abstention_milli": 150},
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
                response_json = json.loads(response.read())
                record["http_status"] = response.status
                record["response"] = response_json
                choices = response_json.get("choices", [])
                content = choices[0].get("message", {}).get("content") if choices else None
                record["content"] = content
                try:
                    record["output"] = json.loads(content) if isinstance(content, str) else None
                except json.JSONDecodeError:
                    record["output"] = None
                normalized, error = normalize_output(record["output"])
                record["normalized_output"] = normalized
                record["normalization_error"] = error
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

        output = record.get("normalized_output")
        choice = output.get("action_choice") if isinstance(output, dict) else None
        mapping = by_id.get(choice) if type(choice) is int else None
        record["canonical_action_choice"] = choice
        record["mapped_original_action_id"] = mapping["original_action_id"] if mapping else None
        record["selected_patch_sha256"] = mapping["patch_sha256"] if mapping else None
        record["mapping_status"] = "mapped" if mapping else ("abstain" if choice is None else "unknown-canonical-id")
        record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        (output_dir / f"{entry['task_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{args.role} canonical {entry['task_id']} {record.get('http_status', 'ERROR')} {record['elapsed_ms']} ms")


if __name__ == "__main__":
    main()
