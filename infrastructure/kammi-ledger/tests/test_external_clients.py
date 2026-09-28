"""External harness fixture: HTTP only, no Ladybug imports in clients."""
import gc
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ledgerd.client import KammiClient
from ledgerd.core import Ledger
from scripts.independent_verify import verify_store

HERE = Path(__file__).resolve().parents[1]


def kill_tree(process):
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            process.kill()
    process.wait(timeout=10)


class ExternalClientTests(unittest.TestCase):
    def test_python_cli_mcp_rust_and_phoenix_process(self):
        fixture_parent = HERE / ".kammi-dev/acceptance-fixtures"
        fixture_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="kammi-external-", dir=fixture_parent, delete=False) as directory:
            root = Path(directory)
            self.fixture_root = root
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = {**os.environ, "KAMMI_ROOT": str(root / "store"),
                   "KAMMI_TOKEN": "acceptance-admin-credential", "KAMMI_PORT": str(port),
                   "KAMMI_URL": f"http://127.0.0.1:{port}",
                   "KAMMI_EMBEDDING_CACHE": str(HERE / ".kammi-dev" / "embedding-cache")}
            log = (root / "daemon.log").open("w")
            process = subprocess.Popen([sys.executable, "-m", "ledgerd.api"], env=env,
                                       cwd=HERE, stdout=log, stderr=log)
            client = KammiClient(env["KAMMI_URL"], env["KAMMI_TOKEN"])
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        self.fail((root / "daemon.log").read_text())
                    try:
                        client.status()
                        break
                    except Exception:
                        time.sleep(0.05)
                else:
                    self.fail("daemon did not start")
                source = root / "source.txt"
                source.write_text("Phoenix external-harness source fixture")
                artifact = client.register_file(source, "source", "admin", "external-source")
                with ThreadPoolExecutor(max_workers=8) as pool:
                    duplicates = list(pool.map(lambda _: client.register_file(source, "source", "admin", "external-source"), range(24)))
                self.assertTrue(all(receipt == artifact for receipt in duplicates))
                client.create_run("acceptance.phoenix", "phoenix", "admin", "external-run")
                client.call("POST", "/v1/facts", {
                    "fact": {"run_id": "acceptance.phoenix", "kind": "ATTEMPT",
                             "subject": "fixture", "object": "fixture", "value": "PASS",
                             "evidence_artifact": artifact["artifact_id"], "scope": "EXTERNAL_CLIENT_FIXTURE"},
                    "actor": "admin", "request_id": "external-fact"})
                actor_token = "acceptance-phoenix-agent-credential"
                client.call("POST", "/v1/actors", {
                    "actor_id": "phoenix-agent", "kind": "agent", "lab": "phoenix",
                    "credential_sha256": hashlib.sha256(actor_token.encode()).hexdigest(),
                    "request_id": "external-actor"})
                cli = subprocess.run([sys.executable, "-m", "ledgerd.cli", "status"],
                                     env=env, cwd=HERE, capture_output=True, timeout=20)
                self.assertEqual(cli.returncode, 0, cli.stderr)
                self.assertEqual(json.loads(cli.stdout)["flight_gate"], "CLOSED_PENDING_ACCEPTANCE")
                actor_env = {**env, "KAMMI_TOKEN": actor_token}
                # Phoenix fixture is its own process and depends only on client.py/HTTP.
                fixture = (
                    "import json,sys;from ledgerd.client import KammiClient;"
                    "c=KammiClient.from_environment();"
                    "r=c.memory_record({'kind':'OBSERVED','scope':'phoenix','text':'External Phoenix fixture works through HTTP',"
                    "'actor_id':'phoenix-agent','custody_refs':[sys.argv[1]],'request_id':'phoenix-memory'});"
                    "s=c.memory_search({'query':'Phoenix','scope':'phoenix','actor_id':'phoenix-agent','mode':'hybrid','request_id':'phoenix-search'});"
                    "t=c.memory_trace(r['memory_id'],'phoenix-agent');"
                    "print(json.dumps({'record':r,'search':s,'trace':t}))"
                )
                result = subprocess.run([sys.executable, "-c", fixture, artifact["artifact_id"]],
                                        env=actor_env, cwd=HERE, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                evidence = json.loads(result.stdout)
                self.assertTrue(evidence["trace"]["references"][0]["verified"])
                self.assertTrue(evidence["search"]["results"])
                messages = [
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                        "name": "memory_record", "arguments": {"body": {"kind": "OBSERVED", "scope": "phoenix",
                            "text": "MCP external fixture traced custody", "actor_id": "phoenix-agent",
                            "custody_refs": [artifact["artifact_id"]], "request_id": "mcp-record"}}}},
                    {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
                        "name": "memory_search", "arguments": {"body": {"query": "MCP external fixture",
                            "scope": "phoenix", "actor_id": "phoenix-agent", "mode": "hybrid", "request_id": "mcp-search"}}}},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                        "name": "memory_trace", "arguments": {"memory_id": evidence["record"]["memory_id"], "actor_id": "phoenix-agent"}}},
                ]
                mcp = subprocess.run([sys.executable, "-m", "ledgerd.mcp"],
                                     input="".join(json.dumps(m) + "\n" for m in messages),
                                     env=actor_env, cwd=HERE, capture_output=True, text=True, timeout=20)
                self.assertEqual(mcp.returncode, 0, mcp.stderr)
                replies = [json.loads(line) for line in mcp.stdout.splitlines()]
                self.assertEqual(len(replies), 5)
                self.assertTrue(all(not r["result"].get("isError", False) for r in replies))
                self.assertFalse(replies[-1]["result"]["isError"])
                self.assertTrue(replies[-1]["result"]["structuredContent"]["references"][0]["verified"])
                rust_binary = HERE / ".kammi-dev" / "clients" / "rust" / "kammi-client-smoke.exe"
                self.assertTrue(rust_binary.exists(), "qualify/build the Rust SDK before acceptance")
                rust = subprocess.run([str(rust_binary)], env=env, cwd=HERE,
                                      capture_output=True, timeout=20)
                self.assertEqual(rust.returncode, 0, rust.stderr)
                self.assertEqual(json.loads(rust.stdout)["flight_gate"], "CLOSED_PENDING_ACCEPTANCE")
                rust_memory = subprocess.run([str(rust_binary)], env={**actor_env,
                    "KAMMI_SMOKE_ACTOR": "phoenix-agent", "KAMMI_SMOKE_SCOPE": "phoenix",
                    "KAMMI_SMOKE_EVIDENCE": artifact["artifact_id"]}, cwd=HERE,
                    capture_output=True, timeout=30)
                self.assertEqual(rust_memory.returncode, 0, rust_memory.stderr)
                self.assertEqual(json.loads(rust_memory.stdout)["status"], "PASS")
                policy = client.call("POST", "/v1/policies", {"policy": {
                    "schema": "KAMMI_POLICY_V1", "stage_id": "COLLISION", "version": "v1",
                    "requires": {"actor": "AUTHORIZED"}, "forbids": {}}, "request_id": "collision-policy"})
                client.call("POST", "/v1/resources", {"resource_id": "gpu.fixture", "kind": "GPU", "host": "local",
                                                        "constraints": {}, "request_id": "collision-resource"})
                other_token = "acceptance-other-agent-credential"
                client.call("POST", "/v1/actors", {"actor_id": "other-agent", "kind": "agent", "lab": "phoenix",
                                                    "credential_sha256": hashlib.sha256(other_token.encode()).hexdigest(), "request_id": "other-actor"})
                expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
                for actor in ("phoenix-agent", "other-agent"):
                    client.call("POST", "/v1/grants", {"grant_id": "collision-" + actor, "actor_id": actor,
                        "action": "acquire_lease", "run_id": "acceptance.phoenix", "stage_id": "COLLISION",
                        "policy_hash": policy["policy_hash"], "expires_utc": expiry, "request_id": "collision-grant-" + actor})
                command = "import json,sys,time;from ledgerd.client import KammiClient;c=KammiClient.from_environment();r=c.acquire_lease(json.loads(sys.argv[1]));print(json.dumps(r),flush=True);time.sleep(30)"
                children = []
                try:
                    for actor, credential in (("phoenix-agent", actor_token), ("other-agent", other_token)):
                        body = {"resource_id": "gpu.fixture", "run_id": "acceptance.phoenix", "stage_id": "COLLISION",
                                "actor_id": actor, "purpose": "collision", "ttl_seconds": 1, "request_id": "collision-client-" + actor}
                        children.append(subprocess.Popen([sys.executable, "-c", command, json.dumps(body)],
                                         env={**env, "KAMMI_TOKEN": credential}, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
                    receipts = [json.loads(child.stdout.readline()) for child in children]
                    winners = [r["receipt"] for r in receipts if r["receipt"]["decision"] == "GRANTED"]
                    self.assertEqual(len(winners), 1)
                    old = winners[0]
                finally:
                    for child in children:
                        kill_tree(child)
                        child.communicate(timeout=10)
                time.sleep(1.1)
                scoped = KammiClient(env["KAMMI_URL"], actor_token)
                next_lease = scoped.acquire_lease({"resource_id": "gpu.fixture", "run_id": "acceptance.phoenix", "stage_id": "COLLISION",
                                                  "actor_id": "phoenix-agent", "purpose": "replacement", "ttl_seconds": 10, "request_id": "collision-replacement"})["receipt"]
                self.assertEqual(next_lease["decision"], "GRANTED")
                self.assertGreater(next_lease["fencing_token"], old["fencing_token"])
                old_client = KammiClient(env["KAMMI_URL"], actor_token if old["actor_id"] == "phoenix-agent" else other_token)
                stale = old_client.call("POST", f"/v1/leases/{old['lease_id']}/validate", {
                    "actor_id": old["actor_id"], "run_id": old["run_id"], "resource_id": old["resource_id"], "fencing_token": old["fencing_token"]})
                self.assertFalse(stale["valid"])
                head = client.status()["journal_head"]
                kill_tree(process)
            finally:
                kill_tree(process)
                log.close()
            # Recovery sees exactly the committed custody head after process kill.
            recovered = Ledger(root / "store", embedding_cache=HERE / ".kammi-dev" / "embedding-cache")
            try:
                self.assertEqual(recovered.journal.head, head)
                self.assertEqual(verify_store(recovered.root)["status"], "PASS")
            finally:
                recovered.close()
                gc.collect()
