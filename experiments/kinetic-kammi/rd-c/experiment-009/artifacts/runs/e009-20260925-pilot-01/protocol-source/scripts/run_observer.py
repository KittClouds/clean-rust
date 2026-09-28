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
RUN = ROOT / "artifacts" / "runs" / "e009-20260925-pilot-01"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--task-ids", nargs="*")
    args = parser.parse_args()

    host = urllib.parse.urlparse(args.base_url).hostname
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("observer endpoint must be loopback")
    output_dir = RUN / args.stage
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
            "max_tokens": 128,
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
            "role": args.bundle_id,
            "model": args.model,
            "bundle_id": args.bundle_id,
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
