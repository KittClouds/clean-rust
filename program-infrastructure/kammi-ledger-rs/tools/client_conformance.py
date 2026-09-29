"""External clients against the Rust daemon (evidence for mcp_interface, python_sdk, rust_sdk).

Port of kammi-ledger/tests/test_external_clients.py::ExternalClientTests with the daemon
swapped for kammi-ledgerd. Every client is the unmodified Python-tree client talking HTTP:
the Python CLI, a Phoenix fixture process using ledgerd.client, the MCP server
(ledgerd.mcp), and the Rust SDK smoke binary (kammi-ledger/sdk/rust).

  python tools/client_conformance.py <work dir> [--output report.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PY = HERE.parent / "kammi-ledger"
sys.path.insert(0, str(PY))
from ledgerd.client import KammiClient  # noqa: E402

sys.path.insert(0, str(HERE / "tools"))
from http_differential import free_port  # noqa: E402

TARGET = Path(os.environ.get("CARGO_TARGET_DIR", "G:/kammi-ledger-rs-target")) / "release"
SDK_SMOKE = Path(os.environ.get("KAMMI_SDK_TARGET", "D:/codex-runs/jev-v08q-r3-rust-target/kammi-ledger-target")) / "release" / "kammi-client-smoke.exe"


def kill_tree(process):
    if process.poll() is None:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
    process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.work.resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    store = root / "store"
    subprocess.run([str(TARGET / "kammi-migrate.exe"), "import", "--v1", str(PY / ".kammi-dev/e4-import"), "--v2", str(store)],
                   check=True, stdout=subprocess.DEVNULL)
    port = free_port()
    env = {**os.environ, "KAMMI_ROOT": str(store), "KAMMI_TOKEN": "acceptance-admin-credential", "KAMMI_PORT": str(port),
           "KAMMI_URL": f"http://127.0.0.1:{port}", "KAMMI_EMBEDDER": "bge", "PYTHONDONTWRITEBYTECODE": "1"}
    checks = {}
    log = (root / "daemon.log").open("w")
    process = subprocess.Popen([str(TARGET / "kammi-ledgerd.exe")], env=env, stdout=log, stderr=log)
    client = KammiClient(env["KAMMI_URL"], env["KAMMI_TOKEN"])
    try:
        for _ in range(600):
            if process.poll() is not None:
                raise RuntimeError((root / "daemon.log").read_text())
            try:
                client.status()
                break
            except Exception:
                time.sleep(0.05)
        source = root / "source.txt"
        source.write_text("Phoenix external-harness source fixture")
        artifact = client.register_file(source, "source", "admin", "external-source")
        with ThreadPoolExecutor(max_workers=8) as pool:
            duplicates = list(pool.map(lambda _: client.register_file(source, "source", "admin", "external-source"), range(24)))
        checks["python_sdk_concurrent_idempotent_register"] = all(receipt == artifact for receipt in duplicates)
        client.create_run("acceptance.phoenix", "phoenix", "admin", "external-run")
        client.call("POST", "/v1/facts", {"fact": {"run_id": "acceptance.phoenix", "kind": "ATTEMPT", "subject": "fixture", "object": "fixture",
                    "value": "PASS", "evidence_artifact": artifact["artifact_id"], "scope": "EXTERNAL_CLIENT_FIXTURE"},
                    "actor": "admin", "request_id": "external-fact"})
        actor_token = "acceptance-phoenix-agent-credential"
        client.call("POST", "/v1/actors", {"actor_id": "phoenix-agent", "kind": "agent", "lab": "phoenix",
                    "credential_sha256": hashlib.sha256(actor_token.encode()).hexdigest(), "request_id": "external-actor"})
        cli = subprocess.run([sys.executable, "-m", "ledgerd.cli", "status"], env=env, cwd=PY, capture_output=True, timeout=30)
        checks["python_cli_status"] = cli.returncode == 0 and json.loads(cli.stdout)["flight_gate"] == "CLOSED_PENDING_ACCEPTANCE"
        actor_env = {**env, "KAMMI_TOKEN": actor_token}
        fixture = (
            "import json,sys;from ledgerd.client import KammiClient;"
            "c=KammiClient.from_environment();"
            "r=c.memory_record({'kind':'OBSERVED','scope':'phoenix','text':'External Phoenix fixture works through HTTP',"
            "'actor_id':'phoenix-agent','custody_refs':[sys.argv[1]],'request_id':'phoenix-memory'});"
            "s=c.memory_search({'query':'Phoenix','scope':'phoenix','actor_id':'phoenix-agent','mode':'hybrid','request_id':'phoenix-search'});"
            "t=c.memory_trace(r['memory_id'],'phoenix-agent');"
            "print(json.dumps({'record':r,'search':s,'trace':t}))"
        )
        result = subprocess.run([sys.executable, "-c", fixture, artifact["artifact_id"]], env=actor_env, cwd=PY, capture_output=True, timeout=120)
        evidence = json.loads(result.stdout) if result.returncode == 0 else {}
        checks["phoenix_process_memory_via_sdk"] = bool(evidence) and evidence["trace"]["references"][0]["verified"] and bool(evidence["search"]["results"])
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "memory_record", "arguments": {"body": {
                "kind": "OBSERVED", "scope": "phoenix", "text": "MCP external fixture traced custody", "actor_id": "phoenix-agent",
                "custody_refs": [artifact["artifact_id"]], "request_id": "mcp-record"}}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "memory_search", "arguments": {"body": {
                "query": "MCP external fixture", "scope": "phoenix", "actor_id": "phoenix-agent", "mode": "hybrid", "request_id": "mcp-search"}}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memory_trace", "arguments": {
                "memory_id": evidence.get("record", {}).get("memory_id", ""), "actor_id": "phoenix-agent"}}},
        ]
        mcp = subprocess.run([sys.executable, "-m", "ledgerd.mcp"], input="".join(json.dumps(m) + "\n" for m in messages),
                             env=actor_env, cwd=PY, capture_output=True, text=True, timeout=120)
        replies = [json.loads(line) for line in mcp.stdout.splitlines()] if mcp.returncode == 0 else []
        checks["mcp_server"] = (len(replies) == 5 and all(not r["result"].get("isError", False) for r in replies)
                                and replies[-1]["result"]["structuredContent"]["references"][0]["verified"])
        if SDK_SMOKE.exists():
            rust = subprocess.run([str(SDK_SMOKE)], env=env, capture_output=True, timeout=30)
            rust_memory = subprocess.run([str(SDK_SMOKE)], env={**actor_env, "KAMMI_SMOKE_ACTOR": "phoenix-agent", "KAMMI_SMOKE_SCOPE": "phoenix",
                                         "KAMMI_SMOKE_EVIDENCE": artifact["artifact_id"]}, capture_output=True, timeout=120)
            checks["rust_sdk_status"] = rust.returncode == 0 and json.loads(rust.stdout)["flight_gate"] == "CLOSED_PENDING_ACCEPTANCE"
            checks["rust_sdk_memory"] = rust_memory.returncode == 0 and json.loads(rust_memory.stdout)["status"] == "PASS"
        else:
            checks["rust_sdk_status"] = checks["rust_sdk_memory"] = False
        policy = client.call("POST", "/v1/policies", {"policy": {"schema": "KAMMI_POLICY_V1", "stage_id": "COLLISION", "version": "v1",
                             "requires": {"actor": "AUTHORIZED"}, "forbids": {}}, "request_id": "collision-policy"})
        client.call("POST", "/v1/resources", {"resource_id": "gpu.fixture", "kind": "GPU", "host": "local", "constraints": {}, "request_id": "collision-resource"})
        other_token = "acceptance-other-agent-credential"
        client.call("POST", "/v1/actors", {"actor_id": "other-agent", "kind": "agent", "lab": "phoenix",
                    "credential_sha256": hashlib.sha256(other_token.encode()).hexdigest(), "request_id": "other-actor"})
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        for actor in ("phoenix-agent", "other-agent"):
            client.call("POST", "/v1/grants", {"grant_id": "collision-" + actor, "actor_id": actor, "action": "acquire_lease",
                        "run_id": "acceptance.phoenix", "stage_id": "COLLISION", "policy_hash": policy["policy_hash"], "expires_utc": expiry,
                        "request_id": "collision-grant-" + actor})
        command = ("import json,sys,time;from ledgerd.client import KammiClient;c=KammiClient.from_environment();"
                   "r=c.acquire_lease(json.loads(sys.argv[1]));print(json.dumps(r),flush=True);time.sleep(30)")
        children = []
        try:
            for actor, credential in (("phoenix-agent", actor_token), ("other-agent", other_token)):
                body = {"resource_id": "gpu.fixture", "run_id": "acceptance.phoenix", "stage_id": "COLLISION", "actor_id": actor,
                        "purpose": "collision", "ttl_seconds": 1, "request_id": "collision-client-" + actor}
                children.append(subprocess.Popen([sys.executable, "-c", command, json.dumps(body)], env={**env, "KAMMI_TOKEN": credential},
                                                 cwd=PY, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            receipts = [json.loads(child.stdout.readline()) for child in children]
            winners = [r["receipt"] for r in receipts if r["receipt"]["decision"] == "GRANTED"]
            checks["lease_collision_single_winner"] = len(winners) == 1
            old = winners[0]
        finally:
            for child in children:
                kill_tree(child)
                child.communicate(timeout=10)
        time.sleep(1.1)
        scoped = KammiClient(env["KAMMI_URL"], actor_token)
        replacement = scoped.acquire_lease({"resource_id": "gpu.fixture", "run_id": "acceptance.phoenix", "stage_id": "COLLISION",
                                            "actor_id": "phoenix-agent", "purpose": "replacement", "ttl_seconds": 10,
                                            "request_id": "collision-replacement"})["receipt"]
        old_client = KammiClient(env["KAMMI_URL"], actor_token if old["actor_id"] == "phoenix-agent" else other_token)
        stale = old_client.call("POST", f"/v1/leases/{old['lease_id']}/validate", {"actor_id": old["actor_id"], "run_id": old["run_id"],
                                "resource_id": old["resource_id"], "fencing_token": old["fencing_token"]})
        checks["expired_lease_replaced_and_stale_fence_invalid"] = (replacement["decision"] == "GRANTED"
                                                                    and replacement["fencing_token"] > old["fencing_token"] and not stale["valid"])
        head = client.status()["journal_head"]
        kill_tree(process)
    finally:
        kill_tree(process)
        log.close()
    # Recovery sees exactly the committed custody head after a process kill.
    reopened = subprocess.run([str(TARGET / "kammi-migrate.exe"), "verify", "--v2", str(store)], capture_output=True, text=True)
    dump = subprocess.run([str(TARGET / "kammi-state-dump.exe"), str(store)], capture_output=True, text=True)
    recovered_head = json.loads(dump.stdout)["status"]["journal_head"] if dump.returncode == 0 else None
    checks["kill_recovery_exact_head"] = reopened.returncode == 0 and recovered_head == head
    report = {"schema": "KAMMI_RUST_EXTERNAL_CLIENTS_V1", "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
              "daemon": "kammi-ledgerd", "clients": ["ledgerd.cli", "ledgerd.client (Phoenix fixture process)", "ledgerd.mcp", "kammi-client-smoke (sdk/rust)"]}
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text)
    print(text)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
