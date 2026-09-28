"""Fresh authority bytes, distinct HTTP daemon, complete workflow and crash."""
import base64
import gc
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ledgerd.backup import backup, restore
from ledgerd.client import KammiClient
from ledgerd.core import Ledger
from ledgerd.identity import canonical, strict_json
from ledgerd.remote import public_bytes
from ledgerd.worker import execute_bundle
from scripts.independent_verify import verify_store
from scripts.projection_compare import snapshot
from scripts.lease_collision import terminate

HERE = Path(__file__).resolve().parents[1]


def run_http_cleanroom(root):
    root.mkdir(parents=True)
    store = root / "store"
    for path in ("objects/sha256", "journal"):
        shutil.copytree(HERE / ".kammi-dev/e4-import" / path, store / path)
    key_path = root / "daemon-signing-secret"
    key_path.write_bytes(os.urandom(32))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "KAMMI_ROOT": str(store), "KAMMI_PORT": str(port),
           "KAMMI_TOKEN": "cleanroom-admin", "KAMMI_SIGNING_KEY_FILE": str(key_path),
           "KAMMI_EMBEDDING_CACHE": str(HERE / "vendor/runtime-v1/embedding-cache"),
           "KAMMI_ACCEPTANCE_MODE": "1"}
    url = f"http://127.0.0.1:{port}"
    admin, agent, worker = (KammiClient(url, token) for token in ("cleanroom-admin", "cleanroom-agent", "cleanroom-worker"))
    logs = []
    daemon = None
    def start(extra=None):
        log = (root / f"daemon-{len(logs)}.log").open("w")
        logs.append(log)
        process = subprocess.Popen([sys.executable, "-m", "ledgerd.api"], cwd=HERE,
            env={**env, **(extra or {})}, stdout=log, stderr=log)
        for _ in range(600):
            if process.poll() is not None:
                raise RuntimeError("cleanroom daemon failed: " + Path(log.name).read_text())
            try:
                admin.status()
                return process
            except Exception:
                time.sleep(.05)
        terminate(process)
        raise RuntimeError("cleanroom daemon startup timed out")
    def put(raw, kind, request):
        return admin.call("POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(raw).decode(),
            "kind": kind, "actor": "auditor", "request_id": request})["artifact_id"]
    run, stage = "acceptance.http-cleanroom", "HTTP_REPLAY"
    scope = {"run_id": run, "stage_id": stage, "actor_id": "agent"}
    try:
        daemon = start()
        history_run = "E4-0-legacy-history-complete-v1"
        history = admin.call("GET", f"/v1/runs/{history_run}/history")
        summary = admin.history_summary(history_run)
        assert len(history["facts"]) == 557 and len(summary["stopped_attempts"]) == 29
        imported = json.loads((HERE / "acceptance/e4-0/history-import-v3.json").read_text())
        assert admin.lineage(imported["source_merkle_root"])["entry_count"] == 493
        for actor, kind, credential in (("agent", "agent", "cleanroom-agent"), ("worker", "remote_worker", "cleanroom-worker")):
            admin.call("POST", "/v1/actors", {"actor_id": actor, "kind": kind, "lab": "library",
                "credential_sha256": hashlib.sha256(credential.encode()).hexdigest(), "request_id": "actor-" + actor})
        admin.create_run(run, "library", "auditor", "run")
        policy = admin.call("POST", "/v1/policies", {"policy": {"schema": "KAMMI_POLICY_V1", "stage_id": stage,
            "version": "v1", "requires": {"actor": "AUTHORIZED", "scientific_spec": "SEALED",
                "execution_spec": "SEALED", "predecessor_seal": "VERIFIED", "resource.gpu": "LEASED"},
            "forbids": {"truth_label_contact": True}}, "request_id": "policy"})["policy_hash"]
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        for action in ("bind_spec", "authorize_stage", "acquire_lease", "open_panel", "apply_adapter", "execute_bundle"):
            admin.call("POST", "/v1/grants", {"grant_id": action, **scope, "action": action,
                "policy_hash": policy, "expires_utc": expiry, "request_id": "grant-" + action})
        science, execution, environment, input_id = [put(raw, kind, kind) for raw, kind in (
            (b"fresh synthetic scientific specification", "scientific-spec"),
            (b"fresh synthetic execution specification", "execution-spec"),
            (b"synthetic worker environment", "environment-lock"), (b"declared input", "input"))]
        seal = admin.create_seal([science, execution, environment, input_id], [], "auditor", "seal")["root"]
        for kind, identity in (("SCIENTIFIC", science), ("EXECUTION", execution)):
            agent.call("POST", "/v1/specs/bind", {**scope, "spec_kind": kind, "artifact_id": identity,
                "seal_root": seal, "request_id": "bind-" + kind})
        agent.call("POST", f"/v1/seals/{seal}/verify-for-run", {**scope, "request_id": "verify"})
        admin.call("POST", "/v1/resources", {"resource_id": "gpu.fixture", "kind": "GPU", "host": "local", "constraints": {}, "request_id": "resource"})
        lease = agent.acquire_lease({**scope, "resource_id": "gpu.fixture", "purpose": "replay", "ttl_seconds": 600, "request_id": "lease"})["receipt"]
        auth = agent.call("POST", "/v1/acceptance/stages/authorize", {**scope, "expires_utc": expiry, "request_id": "authorize"})
        assert auth["receipt"]["decision"] == "AUTHORIZED"
        authorization = auth["event_id"]
        agent.call("POST", "/v1/attempts/start", {**scope, "attempt_id": "http-attempt", "authorization_id": authorization, "request_id": "attempt"})
        panel_id = put(b"visible synthetic terminal evidence", "panel", "panel-source")
        admin.call("POST", "/v1/panels", {"panel_id": "P", "artifact_id": panel_id, "lab": "library", "request_id": "panel"})
        opened = agent.open_panel("P", {**scope, "purpose": "terminal", "authorization_id": authorization, "request_id": "open"})
        assert base64.b64decode(opened["bytes_base64"]) == b"visible synthetic terminal evidence"
        source = put(canonical({"schema": "evaluation-v1", "evaluation_checkpoint_cells": [1, 2]}), "manifest", "adapter-source")
        admin.call("POST", "/v1/adapters", {"adapter_id": "EVAL_CELLS_RENAME_V1", "request_id": "adapter"})
        derived = agent.call("POST", "/v1/adapters/EVAL_CELLS_RENAME_V1/apply", {**scope,
            "source_artifact_id": source, "authorization_id": authorization, "purpose": "handoff", "request_id": "apply"})["derived_view_id"]
        worker_key = Ed25519PrivateKey.generate()
        admin.call("POST", "/v1/remote/worker-keys", {"worker_actor_id": "worker", "public_key_hex": public_bytes(worker_key).hex(), "request_id": "worker-key"})
        bundle = {"schema": "KAMMI_REMOTE_BUNDLE_V1", "run_id": run, "lab": "library", "stage_id": stage,
            "scientific_spec": science, "execution_spec": execution, "git_commit": "a" * 40, "dirty_tree_policy": "CLEAN_REQUIRED",
            "input_roots": [seal], "input_artifacts": [input_id], "environment_lock": environment,
            "runtime_requirements": {"runtime": "python-fixture"}, "gpu_requirements": {}, "seeds": [7],
            "command": [sys.executable, "-c", "import os,pathlib; (pathlib.Path(os.environ['KAMMI_OUTPUT_DIR'])/'output').write_bytes(b'HTTP replay')"],
            "expected_outputs": ["output"], "authorization_id": authorization, "lease_id": lease["lease_id"],
            "lease_resource_id": "gpu.fixture", "fencing_token": lease["fencing_token"], "worker_actor_id": "worker"}
        envelope = agent.call("POST", "/v1/remote/bundles", {"bundle": bundle, "actor_id": "agent", "request_id": "bundle"})["envelope"]
        bundle_id = envelope["bundle_artifact_id"]
        fetched = worker.call("GET", f"/v1/remote/bundles/{bundle_id}?worker_actor_id=worker")
        worker.call("POST", f"/v1/remote/bundles/{bundle_id}/start", {"worker_actor_id": "worker", "request_id": "worker-start"})
        def valid(i, r, f):
            return agent.call("POST", f"/v1/leases/{i}/validate", {"actor_id": "agent", "run_id": run,
                "resource_id": r, "fencing_token": f})["valid"]
        result = execute_bundle(base64.b64decode(fetched["bundle_base64"]), envelope["signature_hex"],
            bytes.fromhex(envelope["issuer_public_hex"]), {input_id: b"declared input"}, worker_key,
            {"git_commit": "a" * 40, "dirty_tree": False, "runtime": "python-fixture"}, valid)
        encoded = lambda raw: base64.b64encode(raw).decode()
        returned = worker.call("POST", f"/v1/remote/bundles/{bundle_id}/return", {"worker_actor_id": "worker",
            "receipt_base64": encoded(result[0]), "receipt_signature": result[1],
            "outputs_base64": {k: encoded(v) for k, v in result[2].items()}, "stdout_base64": encoded(result[3]),
            "stderr_base64": encoded(result[4]), "request_id": "worker-return"})["receipt"]
        memory_ids = []
        for index, text in enumerate(("Nested schema mismatch required a registered adapter; exact source remained unchanged.",
                                      "Apply a registered schema adapter and trace immutable source identity.")):
            memory_ids.append(agent.memory_record({"kind": "FAILURE_MODE", "scope": "library", "text": text,
                "actor_id": "agent", "custody_refs": [source, derived], "tags": ["e4", "schema"], "request_id": "memory-" + str(index)})["memory_id"])
        for mode in ("fts", "vector", "hybrid", "graph"):
            found = agent.memory_search({"query": "schema mismatch", "scope": "library", "actor_id": "agent",
                "mode": mode, "seed_memory": memory_ids[1] if mode == "graph" else None, "grounded_only": True, "request_id": "search-" + mode})
            assert memory_ids[0] in [r["memory"]["memory_id"] for r in found["results"]]
        trace = agent.memory_trace(memory_ids[0], "agent")
        assert all(r["verified"] for r in trace["references"])
        agent.call("POST", "/v1/attempts/finish", {"attempt_id": "http-attempt", "actor_id": "agent", "outcome": "COMPLETE",
            "evidence_artifact": derived, "reason": "HTTP fixture complete", "request_id": "complete"})
        output_seal = admin.create_seal([derived, *returned["outputs"].values()], [seal], "auditor", "output-seal")["root"]
        agent.call("POST", "/v1/results/declare", {**scope, "authorization_id": authorization, "seal_root": output_seal, "request_id": "result"})
        before_crash = admin.status()["journal_head"]
        terminate(daemon)
        daemon = start({"KAMMI_ACCEPTANCE_FAULTS": "1", "KAMMI_FAULT_POINT": "journal.after_fsync"})
        try:
            put(b"durably committed HTTP operation before controlled crash", "receipt", "controlled-crash")
        except Exception:
            pass
        daemon.wait(timeout=20)
        assert daemon.returncode == 91
        committed = verify_store(store)
        assert committed["journal_head"] != before_crash
        daemon = start()
        assert admin.status()["journal_head"] == committed["journal_head"]
        # The client cannot know the prior request committed. Retrying the exact
        # key/bytes repairs the response without appending a duplicate event.
        put(b"durably committed HTTP operation before controlled crash", "receipt", "controlled-crash")
        assert admin.status()["journal_head"] == committed["journal_head"]
        assert agent.memory_trace(memory_ids[0], "agent")["references"] == trace["references"]
        terminate(daemon)
        ledger = Ledger(store, embedding_cache=HERE / "vendor/runtime-v1/embedding-cache")
        try:
            rows = snapshot(ledger)
            backup(ledger, root / "backup")
        finally:
            ledger.close()
            gc.collect()
        restore(root / "backup", root / "restored")
        restored = Ledger(root / "restored", embedding_cache=HERE / "vendor/runtime-v1/embedding-cache")
        try:
            assert snapshot(restored) == rows and verify_store(restored.root) == committed
        finally:
            restored.close()
            gc.collect()
        env["KAMMI_ROOT"] = str(root / "restored")
        daemon = start()
        agent.call("POST", f"/v1/leases/{lease['lease_id']}/release", {"actor_id": "agent", "fencing_token": lease["fencing_token"], "request_id": "release"})
        replacement = agent.acquire_lease({**scope, "resource_id": "gpu.fixture", "purpose": "replacement", "ttl_seconds": 60, "request_id": "replacement"})["receipt"]
        assert replacement["fencing_token"] > lease["fencing_token"] and not valid(lease["lease_id"], "gpu.fixture", lease["fencing_token"])
        try:
            agent.open_panel("P", {**scope, "purpose": "terminal", "authorization_id": "sha256:" + "0" * 64, "request_id": "denied"})
        except RuntimeError as exc:
            assert "403" in str(exc)
        else:
            raise AssertionError("unauthorized terminal panel opened")
        terminate(daemon)
        return {"schema": "KAMMI_HTTP_CLEANROOM_V1", "status": "PASS", "distinct_daemon_process": True,
            "authority_only_start": True, "restored_exact_heads": True, "restored_exact_projection": True,
            "controlled_crash_exit": 91, "independent_audit": committed, "remote_receipt": returned,
            "memory_trace": trace, "history_summary": summary, "fixture_store": str(root / "restored"),
            "steps": ["e4_rebuild", "history_queries", "run", "specs", "authorization", "fenced_lease", "guarded_exposure",
                "adapter", "bundle", "worker", "remote_return", "memory", "fts", "vector", "graph", "trace",
                "result", "http_daemon_crash", "restart", "backup", "rebuild", "exact_heads", "stale_fence", "unauthorized_panel"]}
    finally:
        if daemon is not None:
            terminate(daemon)
        for log in logs:
            log.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_bytes(canonical(run_http_cleanroom(args.root)))
