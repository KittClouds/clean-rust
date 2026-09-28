from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
RUN_ID = "e012-20260926-frame-decomposition-01"
RUN = ROOT / "artifacts/runs" / RUN_ID
INPUT = RUN / "inputs"
V5 = ROOT / "inputs/e009-v5"
LOCK_PATH = RUN / "frozen-input-lock.json"
SEAL_PATH = RUN / "pre-model-seal.json"
NORMALIZATION = "percent-0-100-to-milli-x10-v1+line-endings-lf-v1"
MAX_TOKENS = 1024


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite output: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_frozen_inputs() -> tuple[dict, dict]:
    if not LOCK_PATH.is_file() or not SEAL_PATH.is_file():
        raise SystemExit("E012 inputs have not been frozen and sealed before model contact")
    lock = read_json(LOCK_PATH)
    seal = read_json(SEAL_PATH)
    if lock.get("state") != "FROZEN_BEFORE_MODEL_CONTACT" or lock.get("run_id") != RUN_ID:
        raise SystemExit("E012 frozen input lock is invalid")
    if seal.get("state") != "SEALED_BEFORE_MODEL_CONTACT":
        raise SystemExit("E012 pre-model seal is invalid")
    if seal.get("frozen_input_lock_sha256") != sha256(LOCK_PATH.read_bytes()):
        raise SystemExit("E012 pre-model seal does not bind the frozen input lock")
    for item in lock["local_files"]:
        path = ROOT / item["path"]
        if not path.is_file() or sha256(path.read_bytes()) != item["sha256"]:
            raise SystemExit(f"frozen input hash mismatch: {item['path']}")
    for item in lock["evaluation_files"]:
        path = ROOT / item["path"]
        if not path.is_file() or sha256(path.read_bytes()) != item["sha256"]:
            raise SystemExit(f"frozen evaluation artifact hash mismatch: {item['path']}")
    for item in lock["external_files"]:
        path = Path(item["path"])
        if not path.is_file():
            raise SystemExit(f"frozen external file is missing: {item['name']}")
        if item.get("reverified_by_start_script") is not True:
            if item["sha256"] and file_sha256(path) != item["sha256"]:
                raise SystemExit(f"frozen external file hash mismatch: {item['name']}")
    for item in lock["source_trees"]:
        path = ROOT / item["path"]
        digest, count, total = tree_digest(path)
        if (digest, count, total) != (item["sha256"], item["file_count"], item["bytes"]):
            raise SystemExit(f"frozen source tree changed: {item['path']}")
    return lock, seal


def tree_digest(root: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    total = 0
    for path in files:
        rel = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(rel)
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
        total += len(data)
    return digest.hexdigest(), len(files), total


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


def build_payload(model_id: str, prompt: str, schema: dict, frame: dict) -> dict:
    return {
        "model": model_id,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(frame, ensure_ascii=False, separators=(",", ":"))},
        ],
        "temperature": 0,
        "top_p": 1,
        "seed": 0,
        "max_tokens": MAX_TOKENS,
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=("small", "large"))
    parser.add_argument("--base-url")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    lock, _seal = verify_frozen_inputs()
    lock_hash = sha256(LOCK_PATH.read_bytes())

    model_lock = read_json(V5 / "e010-frozen-input-lock.json")
    model = next(row for row in model_lock["models"] if row["role"] == args.role)
    bundle_lock_path = V5 / "e009-v5-bundle-lock.json"
    bundle_lock = read_json(bundle_lock_path)
    bundle = next(
        row for row in bundle_lock["bundles"]
        if row["manifest"]["bundle_id"] == model["bundle_id"]
    )
    manifest = bundle["manifest"]
    prompt_path = V5 / "system-observer-v2.txt"
    schema_path = V5 / "observer-output.v2.json"
    template_path = V5 / f"chat-template-{args.role}.jinja"
    prompt = prompt_path.read_text(encoding="utf-8")
    schema = read_json(schema_path)
    if bundle["blake3"] != model["bundle_blake3"]:
        raise SystemExit("v5 bundle identity differs from the frozen lock")
    if manifest["maximum_output_tokens"] != MAX_TOKENS or manifest["reasoning_mode"] != "off":
        raise SystemExit("v5 observer settings differ from the frozen contract")
    if manifest["normalization_contract"] != NORMALIZATION:
        raise SystemExit("unknown v5 output normalization contract")
    for field, path in (
        ("system_prompt_sha256", prompt_path),
        ("output_schema_sha256", schema_path),
        ("chat_template_sha256", template_path),
    ):
        if sha256(path.read_bytes()) != manifest[field]:
            raise SystemExit(f"v5 {field} mismatch")

    frames = read_json(INPUT / "full-frame-lock.json")
    if frames.get("run_id") != RUN_ID or len(frames["frames"]) != 48:
        raise SystemExit("frozen full-frame bank is missing or has the wrong size")
    bindings = read_json(INPUT / "presentation-bindings.json")
    binding_by_sample = {row["sample_id"]: row for row in bindings["bindings"]}
    if len(binding_by_sample) != len(frames["frames"]):
        raise SystemExit("presentation binding cardinality mismatch")

    if args.dry_run:
        manifest_rows = []
        for entry in frames["frames"]:
            if sha256(canonical(entry["frame"])) != entry["frame_sha256"]:
                raise SystemExit(f"frame lock digest mismatch: {entry['sample_id']}")
            payload = build_payload(model["server_alias"], prompt, schema, entry["frame"])
            body = canonical(payload)
            manifest_rows.append({
                "sample_id": entry["sample_id"],
                "task_id": entry["task_id"],
                "frame_sha256": entry["frame_sha256"],
                "request_sha256": sha256(body),
                "request_bytes": len(body),
                "presentation_binding_matches": (
                    binding_by_sample[entry["sample_id"]]["frame_sha256"] == entry["frame_sha256"]
                    and binding_by_sample[entry["sample_id"]]["task_id"] == entry["task_id"]
                ),
            })
        out = RUN / "preflight" / f"request-dry-run-{args.role}.json"
        write_new(out, {
            "state": "DRY_RUN_NO_MODEL_CONTACT",
            "run_id": RUN_ID,
            "role": args.role,
            "frozen_input_lock_sha256": lock_hash,
            "bundle_id": model["bundle_id"],
            "frame_count": len(manifest_rows),
            "all_presentation_bindings_match": all(row["presentation_binding_matches"] for row in manifest_rows),
            "requests": manifest_rows,
        })
        print(f"{args.role}: validated {len(manifest_rows)} frozen requests without model contact")
        return

    if not args.base_url:
        raise SystemExit("--base-url is required unless --dry-run is set")
    gate_path = RUN / "preflight/model-contact-gate.json"
    gate = read_json(gate_path)
    if (
        gate.get("state") != "MODEL_CONTACT_GATE_PASS"
        or gate.get("run_id") != RUN_ID
        or gate.get("model_contact_authorized") is not True
        or gate.get("frozen_input_lock_sha256") != lock_hash
        or gate.get("model_requests_started") is not False
    ):
        raise SystemExit("E012 model-contact gate is missing or does not bind the frozen inputs")
    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("observer endpoint must be loopback")
    server_path = RUN / "services" / args.role / "server-process.json"
    server = read_json(server_path)
    expected_alias = model["server_alias"]
    if (
        server.get("reasoning_mode") != "off"
        or server.get("alias") != expected_alias
        or server.get("base_url", "").rstrip("/") != args.base_url.rstrip("/")
        or server.get("runtime_sha256") != model["runtime_sha256"]
        or server.get("model_sha256") != model["model_sha256"]
    ):
        raise SystemExit("running service differs from frozen E009 v5 identity")
    runtime_args = server.get("runtime_args", [])
    if "--reasoning" not in runtime_args:
        raise SystemExit("observer service lacks an explicit reasoning-mode argument")
    index = runtime_args.index("--reasoning")
    if runtime_args[index + 1:index + 2] != ["off"]:
        raise SystemExit("observer service is not running with reasoning disabled")
    if server.get("process_id") is None:
        raise SystemExit("observer server process identity is missing")

    output_dir = RUN / "outputs" / args.role
    output_dir.mkdir(parents=True, exist_ok=False)
    frozen_hash = lock_hash
    for entry in frames["frames"]:
        if sha256(canonical(entry["frame"])) != entry["frame_sha256"]:
            raise SystemExit(f"frame lock digest mismatch: {entry['sample_id']}")
        payload = build_payload(model["server_alias"], prompt, schema, entry["frame"])
        body = canonical(payload)
        record: dict = {
            "schema_version": 1,
            "run_id": RUN_ID,
            "role": args.role,
            "sample_id": entry["sample_id"],
            "task_id": entry["task_id"],
            "bundle_id": model["bundle_id"],
            "bundle_blake3": model["bundle_blake3"],
            "frozen_input_lock_sha256": frozen_hash,
            "model_contact_gate_sha256": sha256(gate_path.read_bytes()),
            "frame_lock_sha256": lock["run_artifacts"]["full_frame_lock_sha256"],
            "frame_sha256": entry["frame_sha256"],
            "server_alias": model["server_alias"],
            "server_process_id": server["process_id"],
            "runtime_sha256": server["runtime_sha256"],
            "model_sha256": server["model_sha256"],
            "reasoning_mode": "off",
            "maximum_output_tokens": MAX_TOKENS,
            "chat_template_sha256": manifest["chat_template_sha256"],
            "system_prompt_sha256": sha256(prompt_path.read_bytes()),
            "output_schema_sha256": sha256(schema_path.read_bytes()),
            "normalization_contract": NORMALIZATION,
            "thresholds": model["thresholds"],
            "request_sha256": sha256(body),
            "request_bytes": len(body),
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
                record["normalized_output"], record["normalization_error"] = normalize_output(record["output"])
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
        target = output_dir / f"{entry['sample_id']}.json"
        write_new(target, record)
        print(f"{args.role} {entry['sample_id']} {record.get('http_status', 'ERROR')} {record['elapsed_ms']} ms")


if __name__ == "__main__":
    main()
