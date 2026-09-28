"""Real independent clients die, expire, resume stale, under competing load."""
import gc
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import threading
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ledgerd.client import KammiClient
from ledgerd.core import Ledger
from ledgerd.executor import run_fenced, StaleLease
from ledgerd.identity import canonical
from scripts.independent_verify import verify_store

HERE = Path(__file__).resolve().parents[1]


def terminate(process):
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            process.kill()
    process.wait(timeout=15)


def run_collision(root: Path, rounds=8):
    root.mkdir(parents=True)
    with socket.socket() as socket_:
        socket_.bind(("127.0.0.1", 0))
        port = socket_.getsockname()[1]
    env = {**os.environ, "KAMMI_ROOT": str(root / "store"), "KAMMI_TOKEN": "fixture-admin",
           "KAMMI_PORT": str(port), "KAMMI_URL": f"http://127.0.0.1:{port}"}
    log = (root / "daemon.log").open("w")
    daemon = subprocess.Popen([sys.executable, "-m", "ledgerd.api"], cwd=HERE, env=env, stdout=log, stderr=log)
    client = KammiClient(env["KAMMI_URL"], env["KAMMI_TOKEN"])
    receipts = []
    try:
        for _ in range(200):
            try:
                client.status()
                break
            except Exception:
                if daemon.poll() is not None:
                    raise RuntimeError("daemon failed: " + (root / "daemon.log").read_text())
                time.sleep(.05)
        else:
            raise RuntimeError("daemon readiness timeout")
        client.create_run("acceptance.collision", "library", "admin", "run")
        policy = client.call("POST", "/v1/policies", {"policy": {"schema": "KAMMI_POLICY_V1",
            "stage_id": "COLLISION", "version": "v1", "requires": {"actor": "AUTHORIZED"}, "forbids": {}}, "request_id": "policy"})
        client.call("POST", "/v1/resources", {"resource_id": "gpu.logical", "kind": "GPU",
             "host": "local", "constraints": {}, "request_id": "resource"})
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        tokens = {}
        for i in range(4):
            actor, token = "agent-" + str(i), "fixture-agent-secret-" + str(i)
            tokens[actor] = token
            client.call("POST", "/v1/actors", {"actor_id": actor, "kind": "agent", "lab": "library",
                "credential_sha256": hashlib.sha256(token.encode()).hexdigest(), "request_id": "actor-" + str(i)})
            client.call("POST", "/v1/grants", {"grant_id": "grant-" + str(i), "actor_id": actor,
                "action": "acquire_lease", "run_id": "acceptance.collision", "stage_id": "COLLISION",
                "policy_hash": policy["policy_hash"], "expires_utc": expiry, "request_id": "grant-" + str(i)})
        command = ("import json,sys,time;from ledgerd.client import KammiClient;"
                   "c=KammiClient.from_environment();r=c.acquire_lease(json.loads(sys.argv[1]));"
                   "print(json.dumps(r),flush=True);time.sleep(60)")
        for round_ in range(rounds):
            children = []
            try:
                for actor, token in tokens.items():
                    body = {"resource_id": "gpu.logical", "run_id": "acceptance.collision", "stage_id": "COLLISION",
                            "actor_id": actor, "purpose": "collision", "ttl_seconds": 2,
                            "request_id": f"round-{round_}-{actor}"}
                    children.append(subprocess.Popen([sys.executable, "-c", command, json.dumps(body)],
                        cwd=HERE, env={**env, "KAMMI_TOKEN": token}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
                results = [json.loads(child.stdout.readline())["receipt"] for child in children]
                winners = [r for r in results if r["decision"] == "GRANTED"]
                assert len(winners) == 1
                old = winners[0]
            finally:
                for child in children:
                    terminate(child)
                    child.communicate(timeout=10)
            # Real wall clock, no injected timestamp or synthetic expiry.
            time.sleep(2.05)
            actor = old["actor_id"]
            scoped = KammiClient(env["KAMMI_URL"], tokens[actor])
            replacement = scoped.acquire_lease({"resource_id": "gpu.logical", "run_id": "acceptance.collision",
                "stage_id": "COLLISION", "actor_id": actor, "purpose": "replacement", "ttl_seconds": 30,
                "request_id": "replacement-" + str(round_)})["receipt"]
            assert replacement["decision"] == "GRANTED" and replacement["fencing_token"] > old["fencing_token"]
            # A fresh process resumes the killed client's old credentials/fence.
            stale_body = {"actor_id": actor, "run_id": "acceptance.collision", "resource_id": "gpu.logical",
                          "fencing_token": old["fencing_token"]}
            stale_code = ("import json,sys;from ledgerd.client import KammiClient;"
                          "c=KammiClient.from_environment();print(json.dumps(c.call('POST',sys.argv[1],json.loads(sys.argv[2]))))")
            stale = subprocess.run([sys.executable, "-c", stale_code, f"/v1/leases/{old['lease_id']}/validate", json.dumps(stale_body)],
                cwd=HERE, env={**env, "KAMMI_TOKEN": tokens[actor]}, capture_output=True, timeout=20)
            assert stale.returncode == 0 and json.loads(stale.stdout)["valid"] is False
            try:
                # The executor's authority adapter queries the daemon. It does
                # not independently reproduce lease/policy decisions.
                authority = SimpleNamespace(lock=threading.RLock(), leases=SimpleNamespace(
                    valid=lambda *_: scoped.call("POST", f"/v1/leases/{old['lease_id']}/validate", stale_body)["valid"]))
                run_fenced(authority, lease_id=old["lease_id"], resource_id="gpu.logical",
                    fencing_token=old["fencing_token"], actor_id=actor, run_id="acceptance.collision",
                    argv=[sys.executable, "-c", "raise SystemExit(0)"], cwd=root)
            except StaleLease:
                pass
            else:
                raise AssertionError("stale lease executed a command")
            scoped.call("POST", f"/v1/leases/{replacement['lease_id']}/release", {"actor_id": actor,
                "fencing_token": replacement["fencing_token"], "request_id": "release-" + str(round_)})
            receipts.append({"round": round_, "independent_contenders": 4, "granted": 1, "denied": 3,
                "winning_process_killed": True, "real_expiry": True, "stale_resumed_process_rejected": True,
                "stale_executor_rejected": True, "old_fence": old["fencing_token"], "new_fence": replacement["fencing_token"]})
            print(json.dumps(receipts[-1]), flush=True)
    finally:
        terminate(daemon)
        log.close()
    recovered = Ledger(root / "store")
    try:
        audit = verify_store(recovered.root)
        assert recovered.journal.head == recovered.graph.position()[1]
        return {"schema": "KAMMI_LEASE_COLLISION_V1", "status": "PASS", "rounds": receipts,
                "independent_audit": audit, "fixture_store": str(recovered.root),
                "scope": "Logical GPU leases and CPU commands; no physical CUDA allocation or scientific observer contact."}
    finally:
        recovered.close()
        gc.collect()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_bytes(canonical(run_collision(args.root)))
