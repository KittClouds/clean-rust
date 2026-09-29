"""Operate the Rust Library as the local service (after the 4E cutover).

  python tools/rust_service.py install   copy release binaries from $CARGO_TARGET_DIR into the operational dir
  python tools/rust_service.py start     start kammi-ledgerd detached on 8765 (no-op if already serving)
  python tools/rust_service.py status    /v1/status through the admin credential
  python tools/rust_service.py stop      stop the daemon (a hard stop is safe: gate A3)
  python tools/rust_service.py monitor   append event count + daemon/projector RSS to monitor.jsonl

Mirrors `kammi-ledger/scripts/service.py`: same port, same admin and signing secret files
(`kammi-ledger/.kammi-dev/operational/*.secret`), credentials never in argv. The Rust store
and binaries live in `program-infrastructure/kammi-ledger-rs-operational/`, outside both source
trees (each Library hashes its own tree into its flight identity).

The daemon hashes the release's source snapshot (`release.json` -> `source/<commit>`), never
the development tree, so editing the repository cannot close the live flight gate; only a
release (`tools/release.py`) changes what the daemon is bound to.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RS = Path(__file__).resolve().parents[1]
PY = RS.parent / "kammi-ledger"
PY_SERVICE = PY / ".kammi-dev/operational"
OPS = RS.parent / "kammi-ledger-rs-operational"
BIN = OPS / "bin"
STORE = OPS / "store"
PORT = 8765
BINARIES = ("kammi-ledgerd.exe", "kammi-projector.exe", "kammi-migrate.exe", "kammi-state-dump.exe")
# Memory is O(events) until compact state is qualified (PHASE-4-GATES.md, open finding).
RSS_WARN_MB = 1024


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def admin_token() -> str:
    return (PY_SERVICE / "admin.secret").read_text().strip()


def status(port=PORT, timeout=5):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/status", headers={"Authorization": "Bearer " + admin_token()})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def install():
    target = Path(os.environ["CARGO_TARGET_DIR"]) / "release"
    BIN.mkdir(parents=True, exist_ok=True)
    installed = {}
    for name in BINARIES:
        shutil.copy2(target / name, BIN / name)
        if sha256(BIN / name) != sha256(target / name):
            raise RuntimeError(f"copy of {name} differs")
        installed[name] = "sha256:" + sha256(BIN / name)
    (OPS / "binaries.json").write_text(json.dumps(installed, indent=1))
    return installed


def release():
    """The installed release: which source snapshot the daemon hashes (never the dev tree)."""
    info = json.loads((OPS / "release.json").read_text())
    source = OPS / info["source_dir"]
    if not source.is_dir():
        raise RuntimeError(f"release source snapshot missing: {source}")
    return info, source


def environment(port=PORT):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("KAMMI_") or k in {"KAMMI_OBJECT_VERIFY"}}
    env.update(KAMMI_ROOT=str(STORE), KAMMI_PORT=str(port), KAMMI_TOKEN_FILE=str(PY_SERVICE / "admin.secret"),
               KAMMI_SIGNING_KEY_FILE=str(PY_SERVICE / "signing.secret"), KAMMI_EMBEDDER="bge",
               KAMMI_SOURCE_DIR=str(release()[1]), KAMMI_LBUG_NATIVE_DIR=str(PY / "vendor/runtime-v1/native"))
    env["PATH"] = str(PY / "vendor/runtime-v1/native") + os.pathsep + env.get("PATH", "")
    return env


def start(port=PORT):
    try:
        return {"state": "ALREADY_RUNNING", "status": status(port)}
    except OSError:
        pass
    log = (OPS / "daemon.log").open("a")
    log.write(f"--- start {datetime.now(timezone.utc).isoformat()}\n")
    log.flush()
    flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen([str(BIN / "kammi-ledgerd.exe")], cwd=OPS, env=environment(port), stdin=subprocess.DEVNULL,
                               stdout=log, stderr=log, creationflags=flags)
    log.close()
    (OPS / "launch.json").write_text(json.dumps({"pid_diagnostic_only": process.pid, "port": port, "root": str(STORE),
                                                 "binary": str(BIN / "kammi-ledgerd.exe")}))
    for _ in range(1200):
        if process.poll() is not None:
            raise RuntimeError("kammi-ledgerd exited; inspect kammi-ledger-rs-operational/daemon.log")
        try:
            state = status(port)
        except OSError:
            time.sleep(0.1)
            continue
        if state["flight_gate"] != "OPEN":
            raise RuntimeError(f"kammi-ledgerd is running but the flight gate is {state['flight_gate']}")
        return {"state": "RUNNING", "pid": process.pid, "status": state}
    raise RuntimeError("kammi-ledgerd readiness timeout")


def pids():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like '" + str(BIN) + "\\*' } | "
                          "ForEach-Object { '{0} {1} {2}' -f $_.ProcessId, $_.Name, $_.WorkingSetSize }"],
                         capture_output=True, text=True).stdout.split("\n")
    return [(int(p), n, int(w) / 2**20) for p, n, w in (line.split() for line in out if line.strip())]


def stop():
    daemons = [pid for pid, name, _ in pids() if name == "kammi-ledgerd.exe"]
    for pid in daemons:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    return {"stopped": daemons}


def monitor():
    procs = {name: round(mb, 1) for _, name, mb in pids()}
    entry = {"utc": datetime.now(timezone.utc).isoformat(), "daemon_mb": procs.get("kammi-ledgerd.exe"),
             "projector_mb": procs.get("kammi-projector.exe")}
    try:
        s = status()
        entry.update(journal_events=s["journal_events"], journal_head=s["journal_head"], flight_gate=s["flight_gate"],
                     projection_lag=s.get("projection_lag"))
    except OSError as exc:
        entry["error"] = f"not serving: {exc}"
    entry["warning"] = bool(entry.get("daemon_mb") and entry["daemon_mb"] > RSS_WARN_MB)
    with (OPS / "monitor.jsonl").open("a") as log:
        log.write(json.dumps(entry) + "\n")
    return entry


if __name__ == "__main__":
    operation = sys.argv[1] if len(sys.argv) > 1 else "status"
    action = {"install": install, "start": start, "status": status, "stop": stop, "monitor": monitor}[operation]
    print(json.dumps(action(), indent=2))
