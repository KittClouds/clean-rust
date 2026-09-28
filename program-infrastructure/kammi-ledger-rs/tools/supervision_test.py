"""Phase 3 supervision gates against the real daemon + projector (G1-G4, G13, G14).

  python tools/supervision_test.py <work dir> [--output report.json]

G1  projector runs as a supervised child: /v1/status.projection.process RUNNING with a pid
G13 every memory search sees the caller's own just-committed record (read-your-writes)
G3  status carries projection position, lag and health; lag reaches 0 when idle
G2  kill the projector mid-traffic: custody writes keep committing, searches answer 503 at
    worst, the supervisor restarts it with a new pid, it catches up to lag 0
G4  corrupt the projection while the daemon is down: restart quarantines, rebuilds, records
    last_quarantine, and custody writes are accepted during the rebuild
G14 kill the projector at projection.mid_transaction (statement path), resume, verify --deep
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
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from http_differential import PY, TARGET, Side  # noqa: E402


def wait(predicate, timeout, what):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {what}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    (work / "rust").mkdir(parents=True)
    store = work / "rust" / "store"
    subprocess.run([str(TARGET / "kammi-migrate.exe"), "import", "--v1", str(PY / ".kammi-dev/e4-import"), "--v2", str(store)],
                   check=True, stdout=subprocess.DEVNULL)
    key = work / "signing"
    key.write_bytes(hashlib.sha256(b"supervision").digest())
    rust = Side("rust", store, [str(TARGET / "kammi-ledgerd.exe")],
                {"KAMMI_SIGNING_KEY_FILE": str(key), "KAMMI_EMBEDDER": "bge"}, HERE)
    agent = "supervision-agent"
    gates, evidence = {}, {}
    counter = iter(range(1, 10**6))

    def status():
        return rust.call("status", "GET", "/v1/status", record=False)[0]

    def put():
        n = next(counter)
        body = {"bytes_base64": base64.b64encode(f"custody write {n}".encode()).decode(), "kind": "note", "actor": "auditor", "request_id": f"w-{n}"}
        return rust.raw("POST", "/v1/artifacts/base64", body, token="cleanroom-admin")[0]

    def record(n, text):
        body = {"kind": "INTERPRETIVE", "scope": "library", "text": text, "actor_id": "agent", "tags": ["supervision"], "request_id": f"m-{n}"}
        return rust.call(f"record-{n}", "POST", "/v1/memory", body, token=agent, record=False)[0]["memory_id"]

    def search(n, query):
        body = {"query": query, "scope": "library", "actor_id": "agent", "mode": "hybrid", "limit": 10, "request_id": f"s-{n}"}
        status_code, (raw, _) = rust.raw("POST", "/v1/memory/search", body, token=agent)
        return status_code, (json.loads(raw) if raw else None)

    try:
        rust.start()
        rust.call("actor", "POST", "/v1/actors", {"actor_id": "agent", "kind": "agent", "lab": "library",
                  "credential_sha256": hashlib.sha256(agent.encode()).hexdigest(), "request_id": "actor"}, record=False)
        block = wait(lambda: (s := status().get("projection")) and s.get("pid") and s["process"] == "RUNNING" and s, 60, "projector RUNNING")
        gates["G1"] = True
        evidence["G1"] = {"process": block["process"], "pid": block["pid"]}

        # G13: read-your-writes on every search.
        seen = 0
        for n in range(12):
            text = f"supervision probe {n} unique token zq{n}x about projector recovery"
            memory_id = record(n, text)
            code, body = search(n, f"zq{n}x projector recovery")
            if code == 200 and memory_id in [r["memory"]["memory_id"] for r in body["results"]]:
                seen += 1
        gates["G13"] = seen == 12
        evidence["G13"] = {"searches": 12, "saw_own_write": seen}

        # G3: lag visible and closes.
        idle = wait(lambda: (s := status()) and s["projection_lag"] == 0 and s["projection"]["memory_lag"] == 0 and s, 60, "lag 0")
        keys = ["process", "pid", "restarts", "projection_seq", "projection_head", "lag", "memory_seq", "memory_lag", "journal_head", "last_verify", "last_quarantine"]
        gates["G3"] = all(k in idle["projection"] for k in keys) and idle["projection_seq"] == idle["journal_events"]
        evidence["G3"] = {k: idle["projection"][k] for k in keys if k != "projection_head"}

        # G2: kill the projector during traffic.
        old_pid, old_restarts = idle["projection"]["pid"], idle["projection"]["restarts"]
        subprocess.run(["taskkill", "/F", "/PID", str(old_pid)], capture_output=True)
        write_codes, search_codes = [], []
        for n in range(100, 140):
            write_codes.append(put())
            if n % 5 == 0:
                search_codes.append(search(n, "projector recovery")[0])
        restarted = wait(lambda: (s := status()["projection"]) and s["pid"] not in (None, old_pid) and s["process"] == "RUNNING" and s, 90, "projector restart")
        caught = wait(lambda: (s := status()) and s["projection_lag"] == 0 and s, 90, "catch-up after restart")
        after_code, after = search(999, "zq3x projector recovery")
        # An intact projection resumes from its stored position; a kill that tore Ladybug's WAL
        # (which cannot be repaired safely) is quarantined and bulk-rebuilt. Either way authority
        # never stalls and the projection converges.
        recovery = caught["projection"].get("last_quarantine")
        gates["G2"] = (all(c == 200 for c in write_codes) and set(search_codes) <= {200, 503}
                       and restarted["restarts"] > old_restarts and after_code == 200 and caught["projection_lag"] == 0)
        evidence["G2"] = {"writes_during_outage": len(write_codes), "write_statuses": sorted(set(write_codes)), "search_statuses": sorted(set(search_codes)),
                          "old_pid": old_pid, "new_pid": restarted["pid"], "restarts": restarted["restarts"], "last_exit": restarted["last_exit"],
                          "lag_after": caught["projection_lag"], "search_after_restart": after_code,
                          "recovery": recovery or "clean resume (no quarantine)"}

        # G4: corrupt the projection while the daemon is down.
        rust.stop()
        db = store / "projection" / "custody.lbdb"
        wait(lambda: not (store / "projection" / "custody.lbdb.lock").exists() or _unlocked(store / "projection" / "custody.lbdb.lock"), 30, "projector exit")
        size = db.stat().st_size
        with open(db, "r+b") as handle:  # scribble over a wide band of pages: content or structure breaks
            for offset in range(size // 3, size // 3 * 2, 4096 * 7):
                handle.seek(offset + 256)
                handle.write(b"\xde\xad\xbe\xef" * 256)
        rust.start()
        codes_during = [put() for _ in range(20)]
        healed = wait(lambda: (s := status()["projection"]) and s.get("last_quarantine") and s["process"] == "RUNNING" and s.get("lag") == 0 and s, 180,
                      "quarantine + rebuild")
        gates["G4"] = all(c == 200 for c in codes_during) and bool(healed["last_quarantine"])
        evidence["G4"] = {"writes_during_rebuild": len(codes_during), "statuses": sorted(set(codes_during)),
                          "last_quarantine": healed["last_quarantine"], "last_verify": healed["last_verify"],
                          "quarantined_files": sorted(p.name for p in (store / "projection" / "quarantine").iterdir())}
        final_status = status()
        rust.stop()

        # Deep verification of the healed live projection, offline.
        env = {**os.environ, "PATH": str(PY / "vendor/runtime-v1/native") + os.pathsep + os.environ["PATH"]}
        healed_verify = subprocess.run([str(TARGET / "kammi-projector.exe"), "verify", "--deep", "--store", str(store), "--db", str(db)],
                                       capture_output=True, text=True, env=env)
        evidence["G4"]["healed_verify"] = healed_verify.stdout.strip()[:300] or healed_verify.stderr.strip()[:300]
        gates["G4"] = gates["G4"] and '"verified":true' in healed_verify.stdout

        # G14: kill at projection.mid_transaction on the statement path, resume, verify.
        g14 = work / "g14.lbdb"
        crash = subprocess.run([str(TARGET / "kammi-projector.exe"), "project", "--store", str(store), "--db", str(g14)],
                               capture_output=True, text=True,
                               env={**env, "KAMMI_ACCEPTANCE_FAULTS": "1", "KAMMI_FAULT_POINT": "projection.mid_transaction", "KAMMI_FAULT_HIT": "700"})
        resume = subprocess.run([str(TARGET / "kammi-projector.exe"), "project", "--store", str(store), "--db", str(g14)], capture_output=True, text=True, env=env)
        check = subprocess.run([str(TARGET / "kammi-projector.exe"), "verify", "--deep", "--store", str(store), "--db", str(g14)], capture_output=True, text=True, env=env)
        resumed = json.loads(resume.stdout) if resume.returncode == 0 else {}
        gates["G14"] = crash.returncode == 91 and resume.returncode == 0 and '"verified":true' in check.stdout and resumed.get("seq") == final_status["journal_events"]
        evidence["G14"] = {"crash_exit": crash.returncode, "resumed_projected": resumed.get("projected"), "seq": resumed.get("seq"),
                           "journal_events": final_status["journal_events"], "verify": check.stdout.strip()[:300] or check.stderr.strip()[:300]}
    finally:
        rust.stop()
        for log in rust.logs:
            log.close()
    report = {"schema": "KAMMI_SUPERVISION_GATES_V1", "status": "PASS" if gates and all(gates.values()) else "FAIL", "gates": gates, "evidence": evidence}
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        args.output.write_text(text)
    print(text)
    return 0 if report["status"] == "PASS" else 1


def _unlocked(lock: Path) -> bool:
    try:
        import msvcrt
        with open(lock, "r+b") as handle:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(main())
