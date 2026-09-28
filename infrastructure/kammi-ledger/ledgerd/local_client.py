"""External local worker: HTTP custody, fenced process tree, file-backed outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .client import KammiClient
from .processes import terminate_tree
from .windows_job import attach_kill_on_close


def file_id(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def safe_environment() -> dict[str, str]:
    # This is credential minimization for trusted code, not a sandbox.
    secret_prefixes = ("KAMMI_", "AWS_", "AZURE_", "GCP_", "GOOGLE_APPLICATION_", "OPENAI_")
    secret_names = {"HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"}
    return {key: value for key, value in os.environ.items()
            if key.upper() not in secret_names and not key.upper().startswith(secret_prefixes)}


def run(request_path: Path, receipt_root: Path) -> dict:
    body = json.loads(request_path.read_bytes())
    fields = {"actor_id", "run_id", "stage_id", "authorization_id", "lease_id",
              "resource_id", "fencing_token", "attempt_id", "request_id"}
    if set(body) != fields:
        raise ValueError("local runner request fields differ from v1")
    token_file = os.environ.get("KAMMI_ACTOR_TOKEN_FILE")
    if not token_file:
        raise ValueError("KAMMI_ACTOR_TOKEN_FILE is required")
    client = KammiClient(os.environ.get("KAMMI_URL", "http://127.0.0.1:8765"),
                         Path(token_file).read_text().strip())
    scope = {key: body[key] for key in fields if key not in {"attempt_id", "request_id"}}
    resolved = client.call("POST", "/v1/local/resolve", scope)
    spec = resolved["execution_spec"]
    if not resolved["valid"]:
        raise ValueError("local execution was not authorized")
    output_root = Path(spec["output_root"])
    if output_root.exists():
        raise ValueError("fresh local output root already exists")
    receipt_root.mkdir(parents=True, exist_ok=False)
    # The supervisor enters its own kill-on-close Job before creating a model
    # process. If the supervisor dies, the OS kills its child process tree.
    job = attach_kill_on_close()
    _ = job  # Retain the private OS handle for the lifetime of this process.
    prefix = body["request_id"]
    client.call("POST", "/v1/attempts/start", {"attempt_id": body["attempt_id"],
        "actor_id": body["actor_id"], "run_id": body["run_id"],
        "stage_id": body["stage_id"], "authorization_id": body["authorization_id"],
        "request_id": prefix + ":attempt-start"})
    stdout_path, stderr_path = receipt_root / "stdout.log", receipt_root / "stderr.log"
    deadline = time.monotonic() + spec["timeout_seconds"]
    last_renew = time.monotonic()
    process = None
    result: dict = {"schema": "KAMMI_LOCAL_EXECUTION_RESULT_V1", "status": "STOPPED",
                    "attempt_id": body["attempt_id"], "run_id": body["run_id"],
                    "stage_id": body["stage_id"], "authorization_id": body["authorization_id"],
                    "lease_id": body["lease_id"], "fencing_token": body["fencing_token"],
                    "library_acceptance": resolved["library_acceptance"],
                    "output_root": str(output_root), "outputs": {}}
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            client.call("POST", "/v1/local/validate", scope)
            process = subprocess.Popen(spec["command"], cwd=spec["cwd"],
                                       env=safe_environment(), stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, shell=False)
            result["pid_diagnostic_only"] = process.pid
            contact = client.call("POST", "/v1/local/contact", {**scope,
                "attempt_id": body["attempt_id"], "request_id": prefix + ":possible-model-contact"})
            result["model_launch_contact_event"] = contact["event_id"]
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("local process exceeded frozen timeout")
                client.call("POST", "/v1/local/validate", scope)
                if time.monotonic() - last_renew >= 60:
                    client.call("POST", f"/v1/leases/{body['lease_id']}/renew", {
                        "actor_id": body["actor_id"], "fencing_token": body["fencing_token"],
                        "ttl_seconds": 1800,
                        "request_id": prefix + ":renew:" + str(int(time.monotonic() // 60))})
                    last_renew = time.monotonic()
                time.sleep(spec["poll_seconds"])
            result["exit_code"] = process.returncode
            client.call("POST", "/v1/local/validate", scope)
            if process.returncode != 0:
                raise RuntimeError("local process exited nonzero")
            if not output_root.is_dir():
                raise ValueError("local runner did not create its declared output root")
            for name in spec["expected_outputs"]:
                path = output_root.joinpath(*name.split("/"))
                if not path.is_file() or path.is_symlink():
                    raise ValueError("declared local output is missing or is a link: " + name)
                size = path.stat().st_size
                if size > spec["max_output_bytes"]:
                    raise ValueError("local output exceeds frozen cap: " + name)
                identity = file_id(path)
                imported = client.call("POST", "/v1/local/import-output", {**scope,
                    "relative_path": name, "expected_sha256": identity,
                    "kind": "local-execution-output", "request_id": prefix + ":output:" + name.replace("/", ":")},
                    timeout_seconds=3600)
                if imported["artifact_id"] != identity:
                    raise ValueError("server import identity differs from local output")
                result["outputs"][name] = {**imported, "bytes": size}
            result["status"] = "OUTPUTS_REGISTERED"
    except BaseException as exc:
        if process is not None and process.poll() is None:
            terminate_tree(process)
        result["stop_reason"] = type(exc).__name__ + ": " + str(exc)
    finally:
        result["stdout"] = {"path": str(stdout_path), "sha256": file_id(stdout_path)}
        result["stderr"] = {"path": str(stderr_path), "sha256": file_id(stderr_path)}
        (receipt_root / "RESULT.json").write_text(json.dumps(result, indent=2))
        try:
            finish = client.call("POST", "/v1/local/finish", {
                "actor_id": body["actor_id"], "attempt_id": body["attempt_id"],
                "result": result, "request_id": prefix + ":finish"})
            (receipt_root / "FINISH.json").write_text(json.dumps(finish, indent=2))
        except Exception as exc:
            (receipt_root / "FINISH-ERROR.txt").write_text(type(exc).__name__ + ": " + str(exc))
            result["status"] = "STOPPED"
        try:
            release = client.call("POST", f"/v1/leases/{body['lease_id']}/release", {
                "actor_id": body["actor_id"], "fencing_token": body["fencing_token"],
                "request_id": prefix + ":lease-release"})
            (receipt_root / "RELEASE.json").write_text(json.dumps(release, indent=2))
        except Exception as exc:
            (receipt_root / "RELEASE-ERROR.txt").write_text(type(exc).__name__ + ": " + str(exc))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.request, args.receipt_root)
    print(json.dumps(result))
    return 0 if result["status"] == "OUTPUTS_REGISTERED" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
