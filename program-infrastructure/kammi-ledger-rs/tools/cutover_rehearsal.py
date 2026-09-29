"""Phase 4C + 4D: cutover and rollback rehearsal on a copy of the live store.

  python tools/cutover_rehearsal.py <work dir> --evidence <dir of Phase 3/4 reports> [--output report.json]

4C  copy live (read-only) -> Python serves the copy -> gentle traffic -> FENCE (stop Python)
    -> settle -> Python independent_verify (full) -> import -> kammi-migrate verify (every
    object hashed) -> backup/restore round trip -> Rust full-hash replay
    (KAMMI_OBJECT_VERIFY=full) -> independent verification for the audit -> Rust
    LibraryAcceptanceV2 -> Rust serves on the SAME port with acceptance mode OFF -> probes
    (Python CLI, SDK, MCP, Rust SDK, ordinary /v1/authorize, memory written under Python).
4D  real Rust writes (custody, lease, bge memory + search, vault) -> FENCE Rust -> export-v1
    -> unmodified Python independent_verify + Ledger replay (memory included) -> Python
    re-accepted through its own accept_library -> Python serves on the SAME port -> reads the
    Rust-written custody, memory and vault state -> Python writes and authorizes.

Acceptance mode is OFF throughout: the flight gates are real.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from http_differential import PY, TARGET, Side, free_port  # noqa: E402

sys.path.insert(0, str(PY))
from ledgerd.client import KammiClient  # noqa: E402

LIVE = PY / ".kammi-dev/operational/store"
CACHE = PY / "vendor/runtime-v1/embedding-cache"
SDK_SMOKE = Path(os.environ.get("KAMMI_SDK_TARGET", "D:/codex-runs/jev-v08q-r3-rust-target/kammi-ledger-target")) / "release" / "kammi-client-smoke.exe"
ENV = {**os.environ, "PATH": str(PY / "vendor/runtime-v1/native") + os.pathsep + os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
ADMIN = "cleanroom-admin"

# Gate -> evidence report files (names inside the evidence directory).
EVIDENCE = {
    "artifact_tamper": ["workspace-tests.txt"],
    "journal_tamper": ["workspace-tests.txt"],
    "db_deletion_rebuild": ["supervision.json", "memory-differential.json"],
    "crash_recovery": ["workspace-tests.txt", "http-differential.json", "stress.json"],
    "windows_durability_characterization": ["stress.json", "workspace-tests.txt"],
    "backup_restore": ["backup-restore.json", "http-differential.json"],
    "single_writer_fencing": ["workspace-tests.txt", "clients.json"],
    "actor_authorization": ["http-differential.json"],
    "policy_engine": ["http-differential.json"],
    "exposure_enforcement": ["http-differential.json"],
    "resource_leases": ["stress.json", "clients.json", "http-differential.json"],
    "stale_fencing_rejection": ["stress.json", "clients.json", "http-differential.json"],
    "adapter_registry": ["http-differential.json"],
    "failure_history_queries": ["http-differential.json", "shadow.json"],
    "contact_evidence_scope": ["http-differential.json", "shadow.json"],
    "remote_execution": ["http-differential.json"],
    "remote_tamper_replay": ["http-differential.json"],
    "memory_plane": ["memory-differential.json", "clients.json"],
    "fts_retrieval": ["memory-differential.json"],
    "vector_retrieval": ["memory-differential.json"],
    "graph_retrieval": ["memory-differential.json"],
    "memory_custody_trace": ["memory-differential.json", "clients.json"],
    "mcp_interface": ["clients.json"],
    "python_sdk": ["clients.json"],
    "rust_sdk": ["clients.json"],
    "e4_legacy_reconstruction": ["http-differential.json", "shadow.json"],
    "cleanroom_replay": ["http-differential.json"],
    "phoenix_vault": ["http-differential.json"],
    "v1_import_parity": ["shadow.json"],
    "shadow_zero_diff": ["shadow.json"],
    "projector_isolation": ["supervision.json", "stress.json"],
    "export_v1_rollback": ["http-differential.json"],
}


def v1_heads(store: Path):
    import struct
    out = {}
    for name, rel in (("main", "journal/events.log"), ("memory", "memory/journal/events.log")):
        path, head, count = store / rel, "sha256:" + "0" * 64, 0
        if path.exists():
            data, off = path.read_bytes(), 0
            while off + 4 <= len(data):
                length = struct.unpack(">I", data[off:off + 4])[0]
                if off + 4 + length + 32 > len(data):
                    break
                head = "sha256:" + hashlib.sha256(b"kammi-event-v1\0" + data[off + 4:off + 4 + length]).hexdigest()
                count += 1
                off += 4 + length + 32
        out[name] = {"events": count, "head": head}
    return out


def daemon(name, store, command, env, cwd, port):
    side = Side(name, store, command, env, cwd)
    side.port, side.url = port, f"http://127.0.0.1:{port}"
    side.env["KAMMI_PORT"] = str(port)
    side.env["KAMMI_ACCEPTANCE_MODE"] = "0"  # real flight gates
    side.startup_timeout = 1800
    return side


def run(cmd, **kw):
    started = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, env=ENV, **kw)
    return result, round(time.time() - started, 2)


def step(report, name):
    report["steps"].append({"step": name, "started": datetime.now(timezone.utc).isoformat()})
    print(f"-- {name}", flush=True)
    return time.time()


def done(report, started, **fields):
    report["steps"][-1].update(seconds=round(time.time() - started, 2), **fields)


def probe_authorize(client_admin, url, prefix, lab):
    token = prefix + "-agent-credential"
    actor, run_id, stage = prefix + "-agent", prefix + ".run", prefix.upper().replace("-", "_") + "_STAGE"
    client_admin.call("POST", "/v1/actors", {"actor_id": actor, "kind": "agent", "lab": lab,
                      "credential_sha256": hashlib.sha256(token.encode()).hexdigest(), "request_id": prefix + "-actor"})
    client_admin.create_run(run_id, lab, "admin", prefix + "-run")
    policy = client_admin.call("POST", "/v1/policies", {"policy": {"schema": "KAMMI_POLICY_V1", "stage_id": stage, "version": "v1",
                               "requires": {"actor": "AUTHORIZED"}, "forbids": {}}, "request_id": prefix + "-policy"})
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    client_admin.call("POST", "/v1/grants", {"grant_id": prefix + "-grant", "actor_id": actor, "action": "authorize_stage", "run_id": run_id,
                      "stage_id": stage, "policy_hash": policy["policy_hash"], "expires_utc": expiry, "request_id": prefix + "-grant"})
    receipt = KammiClient(url, token).call("POST", "/v1/authorize", {"actor_id": actor, "run_id": run_id, "stage_id": stage,
                                           "expires_utc": expiry, "request_id": prefix + "-authorize"})
    return receipt["receipt"]["decision"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("--live", type=Path, default=LIVE)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    port = free_port()
    report = {"schema": "KAMMI_CUTOVER_ROLLBACK_REHEARSAL_V1", "port": port, "steps": [], "gates": {}}
    py_store, v2 = work / "python-store", work / "rust-store"
    agent_token = "rehearsal-agent-credential"
    sides = []

    def save():
        if args.output:
            args.output.write_text(json.dumps(report, indent=2, default=str))

    try:
        t = step(report, "copy live store (read-only)")
        for part in ("objects", "journal", "memory"):
            if (args.live / part).exists():
                shutil.copytree(args.live / part, py_store / part, ignore=shutil.ignore_patterns("*.tmp"))
        done(report, t, heads=v1_heads(py_store))

        t = step(report, "Python serves the copy; gentle traffic")
        python = daemon("python", py_store, [sys.executable, "-m", "ledgerd.api"], {"KAMMI_EMBEDDING_CACHE": str(CACHE)}, PY, port)
        sides.append(python)
        startup = python.start()
        admin = KammiClient(python.url, ADMIN)
        admin.call("POST", "/v1/actors", {"actor_id": "rehearsal-agent", "kind": "agent", "lab": "rehearsal",
                   "credential_sha256": hashlib.sha256(agent_token.encode()).hexdigest(), "request_id": "rehearsal-agent"})
        evidence = admin.call("POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(b"rehearsal evidence under Python").decode(),
                              "kind": "evidence", "actor": "admin", "request_id": "rehearsal-python-artifact"})["artifact_id"]
        agent = KammiClient(python.url, agent_token)
        py_memory = agent.memory_record({"kind": "OBSERVED", "scope": "rehearsal", "text": "Recorded under Python before the cutover rehearsal",
                                         "actor_id": "rehearsal-agent", "custody_refs": [evidence], "request_id": "rehearsal-python-memory"})["memory_id"]
        python_status = admin.status()
        done(report, t, python_startup_seconds=round(startup, 1), python_head=python_status["journal_head"], python_flight=python_status["flight_gate"])

        t = step(report, "FENCE: stop Python; settle")
        python.stop()
        fenced = v1_heads(py_store)
        done(report, t, fenced=fenced)

        t = step(report, "Python independent_verify (full, pre-import)")
        verify, secs = run([sys.executable, "-c", "import sys,json;sys.path.insert(0,sys.argv[1]);from scripts.independent_verify import verify_store;"
                            "from pathlib import Path;print(json.dumps(verify_store(Path(sys.argv[2]))))", str(PY), str(py_store)], cwd=PY)
        pre = json.loads(verify.stdout) if verify.returncode == 0 else {"status": "FAIL", "error": verify.stderr[-400:]}
        done(report, t, status=pre.get("status"), journal_head=pre.get("journal_head"), verify_seconds=secs)

        t = step(report, "import -> Rust v2; deep verify")
        imported, secs = run([str(TARGET / "kammi-migrate.exe"), "import", "--v1", str(py_store), "--v2", str(v2)])
        deep, deep_secs = run([str(TARGET / "kammi-migrate.exe"), "verify", "--v2", str(v2)])
        line = imported.stdout.strip().splitlines()[-1] if imported.returncode == 0 else ""
        c1 = (imported.returncode == 0 and deep.returncode == 0 and line.split()[1] == fenced["main"]["head"]
              and line.split("memory ")[1].split()[0] == fenced["memory"]["head"] and pre.get("journal_head") == fenced["main"]["head"])
        done(report, t, import_report=line, import_seconds=secs, deep_verify_seconds=deep_secs, heads_equal=c1)

        t = step(report, "backup/restore round trip (export-v1 -> import)")
        backup, restored = work / "backup-v1", work / "restored-v2"
        run([str(TARGET / "kammi-migrate.exe"), "export-v1", "--v2", str(v2), "--out", str(backup)])
        run([str(TARGET / "kammi-migrate.exe"), "import", "--v1", str(backup), "--v2", str(restored)])
        compare, _ = run([str(TARGET / "kammi-migrate.exe"), "compare", "--v1", str(py_store), "--v1", str(backup)])
        a, _ = run([str(TARGET / "kammi-state-dump.exe"), str(v2)])
        b, _ = run([str(TARGET / "kammi-state-dump.exe"), str(restored)])
        backup_ok = compare.returncode == 0 and a.returncode == 0 and a.stdout == b.stdout
        (args.evidence / "backup-restore.json").write_text(json.dumps({"schema": "KAMMI_RUST_BACKUP_RESTORE_V1",
            "status": "PASS" if backup_ok else "FAIL", "backup_byte_identical_to_python_store": compare.returncode == 0,
            "compare": compare.stdout.strip()[:300], "restored_state_identical": a.stdout == b.stdout}))
        done(report, t, byte_identical=compare.returncode == 0, restored_state_identical=a.stdout == b.stdout)

        t = step(report, "Rust full-hash replay (KAMMI_OBJECT_VERIFY=full)")
        checkpoint = v2 / "checkpoints" / "object-verification-v1.json"
        if checkpoint.exists():
            checkpoint.unlink()
        full = subprocess.run([str(TARGET / "kammi-state-dump.exe"), str(v2)], capture_output=True, text=True, env={**ENV, "KAMMI_OBJECT_VERIFY": "full"})
        c2 = full.returncode == 0 and deep.returncode == 0 and not checkpoint.exists()
        done(report, t, full_replay=full.returncode == 0, checkpoint_untouched=not checkpoint.exists())

        t = step(report, "independent verification for the audit (Python over export of the Rust store)")
        audit, secs = run([sys.executable, "-c", "import sys,json;sys.path.insert(0,sys.argv[1]);from scripts.independent_verify import verify_store;"
                           "from pathlib import Path;print(json.dumps(verify_store(Path(sys.argv[2]))))", str(PY), str(backup)], cwd=PY)
        (args.evidence / "independent-verify.json").write_text(audit.stdout if audit.returncode == 0 else json.dumps({"status": "FAIL"}))
        done(report, t, status=json.loads(audit.stdout).get("status") if audit.returncode == 0 else "FAIL", seconds_verify=secs)

        t = step(report, "Rust LibraryAcceptanceV2")
        (args.evidence / "evidence-map.json").write_text(json.dumps({"gates": EVIDENCE, "independent_verification": "independent-verify.json"}, indent=1))
        accepted, secs = run([str(TARGET / "kammi-ledgerd.exe"), "accept", "--store", str(v2), "--evidence-map", str(args.evidence / "evidence-map.json"),
                              "--request-id", "rust-acceptance-rehearsal"])
        acceptance = json.loads(accepted.stdout) if accepted.returncode == 0 else {"status": "FAIL", "error": accepted.stderr[-800:]}
        c3 = acceptance.get("status") == "PASS"
        done(report, t, acceptance={k: acceptance.get(k) for k in ("status", "acceptance_identity", "evidence_files", "flight_state", "error")})

        t = step(report, "SWITCH: Rust serves on the same port; probes")
        rust = daemon("rust", v2, [str(TARGET / "kammi-ledgerd.exe")], {"KAMMI_EMBEDDER": "bge"}, HERE, port)
        sides.append(rust)
        rust_start = rust.start()
        admin = KammiClient(rust.url, ADMIN)
        agent = KammiClient(rust.url, agent_token)
        status = admin.status()
        env = {**ENV, "KAMMI_URL": rust.url, "KAMMI_TOKEN": ADMIN}
        cli = subprocess.run([sys.executable, "-m", "ledgerd.cli", "status"], env=env, cwd=PY, capture_output=True, text=True)
        sdk = subprocess.run([str(SDK_SMOKE)], env=env, capture_output=True, text=True) if SDK_SMOKE.exists() else None
        mcp_messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "memory_get",
                         "arguments": {"memory_id": py_memory, "actor_id": "rehearsal-agent"}}}]
        mcp = subprocess.run([sys.executable, "-m", "ledgerd.mcp"], input="".join(json.dumps(m) + "\n" for m in mcp_messages),
                             env={**env, "KAMMI_TOKEN": agent_token}, cwd=PY, capture_output=True, text=True)
        mcp_replies = [json.loads(l) for l in mcp.stdout.splitlines()] if mcp.returncode == 0 else []
        trace = agent.memory_trace(py_memory, "rehearsal-agent")
        search = agent.memory_search({"query": "cutover rehearsal", "scope": "rehearsal", "actor_id": "rehearsal-agent", "mode": "hybrid",
                                      "request_id": "rehearsal-rust-search-python-memory"})
        decision = probe_authorize(admin, rust.url, "rust-probe", "rehearsal")
        probes = {
            "flight_open": status["flight_gate"] == "OPEN",
            "head_continues_fenced_history": status["journal_events"] > fenced["main"]["events"],
            "python_cli": cli.returncode == 0 and json.loads(cli.stdout)["flight_gate"] == "OPEN",
            "rust_sdk": sdk is not None and sdk.returncode == 0 and json.loads(sdk.stdout)["flight_gate"] == "OPEN",
            "mcp": len(mcp_replies) == 2 and not mcp_replies[-1]["result"].get("isError", False),
            "python_memory_traced": all(r["verified"] for r in trace["references"]),
            "python_memory_found": py_memory in [r["memory"]["memory_id"] for r in search["results"]],
            "authorize": decision == "AUTHORIZED",
        }
        c4 = all(probes.values())
        done(report, t, rust_startup_seconds=round(rust_start, 1), probes=probes)

        t = step(report, "4D: real Rust writes")
        artifact = admin.call("POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(b"written by Rust during its tenure").decode(),
                              "kind": "evidence", "actor": "admin", "request_id": "rust-tenure-artifact"})["artifact_id"]
        policy = admin.call("POST", "/v1/policies", {"policy": {"schema": "KAMMI_POLICY_V1", "stage_id": "TENURE", "version": "v1",
                            "requires": {"actor": "AUTHORIZED"}, "forbids": {}}, "request_id": "tenure-policy"})
        admin.create_run("rehearsal.tenure", "rehearsal", "admin", "tenure-run")
        admin.call("POST", "/v1/grants", {"grant_id": "tenure-lease", "actor_id": "rehearsal-agent", "action": "acquire_lease",
                   "run_id": "rehearsal.tenure", "stage_id": "TENURE", "policy_hash": policy["policy_hash"],
                   "expires_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), "request_id": "tenure-grant"})
        admin.call("POST", "/v1/resources", {"resource_id": "gpu.rehearsal", "kind": "GPU", "host": "local", "constraints": {}, "request_id": "tenure-resource"})
        lease = agent.acquire_lease({"resource_id": "gpu.rehearsal", "run_id": "rehearsal.tenure", "stage_id": "TENURE", "actor_id": "rehearsal-agent",
                                     "purpose": "tenure", "ttl_seconds": 60, "request_id": "tenure-lease"})["receipt"]
        agent.call("POST", f"/v1/leases/{lease['lease_id']}/release", {"actor_id": "rehearsal-agent", "fencing_token": lease["fencing_token"],
                   "request_id": "tenure-release"})
        rust_memory = agent.memory_record({"kind": "OBSERVED", "scope": "rehearsal", "text": "Recorded by the Rust Library during its tenure",
                                           "actor_id": "rehearsal-agent", "custody_refs": [artifact], "request_id": "rust-tenure-memory"})["memory_id"]
        agent.memory_search({"query": "Rust tenure", "scope": "rehearsal", "actor_id": "rehearsal-agent", "mode": "hybrid", "request_id": "rust-tenure-search"})
        phoenix_token = "rehearsal-phoenix-credential"
        admin.call("POST", "/v1/actors", {"actor_id": "rehearsal-phoenix", "kind": "service", "lab": "rehearsal",
                   "credential_sha256": hashlib.sha256(phoenix_token.encode()).hexdigest(), "request_id": "rehearsal-phoenix"})
        phoenix = KammiClient(rust.url, phoenix_token)
        phoenix.call("POST", "/v1/vaults", {"vault_id": "rehearsal-vault", "actor_id": "rehearsal-phoenix", "request_id": "tenure-vault"})
        phoenix.call("POST", "/v1/vaults/source", {"vault_id": "rehearsal-vault", "source_id": "notes.md", "base_revision": 0,
                     "content_base64": base64.b64encode(b"# Written under Rust\n").decode(), "actor_id": "rehearsal-phoenix", "request_id": "tenure-source"})
        rust_final = admin.status()
        # The projector bulk-loaded the imported history, then took these writes incrementally:
        # once caught up, a deep verify against the journal proves no row was duplicated or lost.
        deadline = time.time() + 300
        while time.time() < deadline:
            s = admin.status()
            if s.get("projection_lag") == 0 and s["projection"].get("memory_lag") == 0:
                break
            time.sleep(0.5)
        d1 = bool(artifact and lease["decision"] == "GRANTED" and rust_memory)
        done(report, t, writes=["artifact", "lease grant+release", "bge memory + search", "vault + source"], rust_head=rust_final["journal_head"])

        t = step(report, "FENCE Rust; export-v1")
        rust.stop()
        projection, _ = run([str(TARGET / "kammi-projector.exe"), "verify", "--deep", "--store", str(v2),
                             "--db", str(v2 / "projection" / "custody.lbdb")])
        projection_ok = '"verified":true' in projection.stdout
        d1 = d1 and projection_ok
        report["steps"][-2]["projection_deep_verify_after_bulk_then_incremental"] = projection.stdout.strip()[:300] or projection.stderr.strip()[-300:]
        rollback = work / "rollback-v1"
        exported, secs = run([str(TARGET / "kammi-migrate.exe"), "export-v1", "--v2", str(v2), "--out", str(rollback)])
        d2 = exported.returncode == 0 and v1_heads(rollback)["main"]["head"] == rust_final["journal_head"]
        done(report, t, export_seconds=secs, head_equal=d2)

        t = step(report, "Python accepts Rust history (independent_verify + Ledger replay, memory included)")
        verify, _ = run([sys.executable, "-c", "import sys,json;sys.path.insert(0,sys.argv[1]);from scripts.independent_verify import verify_store;"
                         "from pathlib import Path;print(json.dumps(verify_store(Path(sys.argv[2]))))", str(PY), str(rollback)], cwd=PY)
        replay, _ = run([sys.executable, "-c", "import sys,json;sys.path.insert(0,sys.argv[1]);from pathlib import Path;from ledgerd.core import Ledger;"
                         "l=Ledger(Path(sys.argv[2]),embedding_cache=Path(sys.argv[3]));print(json.dumps({'head':l.journal.head,'memories':len(l.memory.records)}));l.close()",
                         str(PY), str(rollback), str(CACHE)], cwd=PY)
        verified = json.loads(verify.stdout) if verify.returncode == 0 else {}
        replayed = json.loads(replay.stdout) if replay.returncode == 0 else {}
        d3 = verified.get("status") == "PASS" and verified.get("journal_head") == rust_final["journal_head"] and replayed.get("head") == rust_final["journal_head"]
        done(report, t, verify=verified.get("status"), replay=replayed, errors=(verify.stderr[-300:] + replay.stderr[-300:]) if not d3 else "")

        t = step(report, "Python re-accepted (its own accept_library)")
        reaccept, _ = run([sys.executable, str(HERE / "tools/py_reaccept.py"), str(rollback), "python-reacceptance-rehearsal"], cwd=PY)
        reaccepted = json.loads(reaccept.stdout) if reaccept.returncode == 0 else {"status": "FAIL", "error": reaccept.stderr[-500:]}
        d4 = reaccepted.get("status") == "PASS"
        done(report, t, reacceptance={k: reaccepted.get(k) for k in ("status", "flight_state", "error")})

        t = step(report, "SWITCH BACK: Python serves on the same port; reads Rust-written state; writes")
        python2 = daemon("python-rollback", rollback, [sys.executable, "-m", "ledgerd.api"], {"KAMMI_EMBEDDING_CACHE": str(CACHE)}, PY, port)
        sides.append(python2)
        back_start = python2.start()
        admin = KammiClient(python2.url, ADMIN)
        agent = KammiClient(python2.url, agent_token)
        status = admin.status()
        memory = agent.call("GET", f"/v1/memory/{rust_memory}?actor_id=rehearsal-agent")
        trace = agent.memory_trace(rust_memory, "rehearsal-agent")
        vault = KammiClient(python2.url, phoenix_token).call("GET", "/v1/vaults/rehearsal-vault?actor_id=rehearsal-phoenix")
        written = admin.call("POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(b"written by Python after rollback").decode(),
                             "kind": "evidence", "actor": "admin", "request_id": "python-after-rollback"})
        decision = probe_authorize(admin, python2.url, "python-probe", "rehearsal")
        back = {
            "flight_open": status["flight_gate"] == "OPEN",
            "rust_memory_readable": memory["memory_id"] == rust_memory,
            "rust_memory_trace_verified": all(r["verified"] for r in trace["references"]),
            "rust_vault_readable": "notes.md" in json.dumps(vault),
            "python_write": bool(written.get("event_id")),
            "authorize": decision == "AUTHORIZED",
        }
        d5 = all(back.values())
        done(report, t, python_startup_seconds=round(back_start, 1), probes=back)
        python2.stop()
        report["gates"] = {"C1": c1, "C2": c2, "C3": c3, "C4": c4, "D1": d1, "D2": d2, "D3": d3, "D4": d4, "D5": d5}
    except Exception as exc:  # noqa: BLE001
        import traceback
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["trace"] = traceback.format_exc()[-2000:]
    finally:
        for side in sides:
            side.stop()
            for log in side.logs:
                log.close()
    report["status"] = "PASS" if report["gates"] and all(report["gates"].values()) and "error" not in report else "FAIL"
    save()
    print(json.dumps({"status": report["status"], "gates": report["gates"], "error": report.get("error")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
