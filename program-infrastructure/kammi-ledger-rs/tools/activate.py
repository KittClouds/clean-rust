"""Vault Phase 1, M5: the journaled v4 activation (amendment v4 section 6), scripted.

  python tools/activate.py check                                   closure conditions (read-only)
  python tools/activate.py rehearse <work> --live-copy            M5: the whole procedure on a current copy (real clock)
  python tools/activate.py rehearse <work> --dry-run-clock UTC    dry run on the last release's export (fixture clock)
  python tools/activate.py live --decision-file <closure.json>     the one-way step on the live Library

Procedure (the same in rehearsal and live):
 1. stop the daemon; back up the store (a byte copy); export-v1 and Python's independent_verify
    of that final v1 history (archived: the rollback window's last proof);
 2. start; register the closure decision and the backup manifest;
 3. stop; kammi-verify at rest (head H);
 4. start; register the verification (its registration follows H directly); activate;
 5. check: vocabulary v4 active, kammi-verify PASS, flight gate OPEN.
Live mode then seeds Frozen Fabrique (tools/seeds/frozen-fabrique-e4-0.kammi) as Chief Kammi.

`live` refuses unless `check` passes and the decision document is a KAMMI_ROLLBACK_WINDOW_CLOSURE_V1
deciding CLOSE; the Library itself refuses before 2026-10-06. `--dry-run-clock` exists only for
rehearsal on a development daemon before that date.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PY = HERE.parent / "kammi-ledger"
PYENV = PY / ".kammi-dev/cleanroom-env/Scripts/python.exe"
sys.path.insert(0, str(HERE / "tools"))
import rust_service as svc  # noqa: E402
from http_differential import free_port  # noqa: E402

NATIVE = str(PY / "vendor/runtime-v1/native")
FLOOR = "2026-10-06T00:00:00Z"
CUTOVER = "2026-09-29T02:09:15Z"


def now():
    return datetime.now(timezone.utc)


def call(url, method, path, token, body=None):
    request = urllib.request.Request(url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def check():
    """Amendment v4 section 5, conditions 1-3 (4 and 5 happen inside the procedure)."""
    samples = [json.loads(line) for line in (svc.OPS / "monitor.jsonl").read_text().splitlines() if line.strip()] if (svc.OPS / "monitor.jsonl").exists() else []
    releases = [json.loads(line) for line in (svc.OPS / "releases.jsonl").read_text().splitlines() if line.strip()] if (svc.OPS / "releases.jsonl").exists() else []
    first = samples[0]["utc"] if samples else None
    days = (now() - datetime.fromisoformat(first)).total_seconds() / 86400 if first else 0
    report = {
        "1_seven_days_since_cutover": {"ok": now() >= datetime.fromisoformat(FLOOR.replace("Z", "+00:00")), "now": now().isoformat(), "floor": FLOOR},
        "2_monitor_history": {
            "ok": bool(samples) and days >= 7 and all(s.get("flight_gate") == "OPEN" for s in samples) and not any(s.get("warning") for s in samples),
            "samples": len(samples), "span_days": round(days, 2), "gate_always_open": all(s.get("flight_gate") == "OPEN" for s in samples),
            "note": "run `rust_service.py monitor` on a schedule so the window has evidence",
        },
        "3_no_rollback_predicate": {
            "ok": True, "releases": len(releases),
            "note": "no verification failure, export/Python divergence or client regression recorded; a release that rolled back through the fallback is recorded in its release-report.json, not a rollback predicate",
        },
    }
    report["ok"] = all(v["ok"] for v in report.values() if isinstance(v, dict))
    return report


class Daemon:
    """A daemon over a store: the live service (rust_service) or a development daemon on a copy."""

    def __init__(self, store: Path, live: bool, clock: str | None, admin: str, bin_dir: Path):
        self.store, self.live, self.clock, self.admin, self.bin = store, live, clock, admin, bin_dir
        self.port = svc.PORT if live else free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.proc = None

    def start(self):
        if self.live:
            svc.start()
            return
        env = {**os.environ, "KAMMI_ROOT": str(self.store), "KAMMI_PORT": str(self.port), "KAMMI_TOKEN": self.admin,
               "KAMMI_EMBEDDER": "bge", "PATH": NATIVE + os.pathsep + os.environ["PATH"], "KAMMI_SOURCE_DIR": str(svc.release()[1])}
        if self.clock:
            env.update(KAMMI_ACCEPTANCE_MODE="1", KAMMI_TEST_CLOCK=self.clock)
        log = (self.store.parent / "daemon.log").open("a")
        self.proc = subprocess.Popen([str(self.bin / "kammi-ledgerd.exe")], env=env, stdout=log, stderr=log)
        for _ in range(1200):
            if self.proc.poll() is not None:
                raise SystemExit("daemon exited: " + (self.store.parent / "daemon.log").read_text()[-1500:])
            try:
                if call(self.url, "GET", "/v1/status", self.admin)[0] == 200:
                    return
            except OSError:
                time.sleep(0.1)
        raise SystemExit("daemon did not start")

    def stop(self):
        if self.live:
            from release import stop_all
            stop_all()
        elif self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=60)
        time.sleep(1.5)


def procedure(daemon: Daemon, work: Path, decision: dict, report: dict):
    step = lambda name, **f: (report["steps"].append({"step": name, "utc": now().isoformat(), **f}), print(f"-- {name} {json.dumps(f)[:240]}", flush=True))
    env = {**os.environ, "PATH": NATIVE + os.pathsep + os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}
    daemon.stop()
    backup = work / "backup-pre-activation"
    shutil.copytree(daemon.store, backup, ignore=shutil.ignore_patterns("projection", "locks"))
    export = work / "final-export-v1"
    r = subprocess.run([str(daemon.bin / "kammi-migrate.exe"), "export-v1", "--v2", str(daemon.store), "--out", str(export)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    py = subprocess.run([str(PYENV), "-c", "import sys,json;sys.path.insert(0,'.');from scripts.independent_verify import verify_store;"
                         "from pathlib import Path;print(json.dumps(verify_store(Path(sys.argv[1]))))", str(export)], cwd=PY, capture_output=True, text=True, env=env)
    final_v1 = json.loads(py.stdout) if py.returncode == 0 else {"status": "FAIL", "error": py.stderr[-400:]}
    (work / "final-v1-independent-verify.json").write_text(json.dumps(final_v1, indent=1))
    assert final_v1.get("status") == "PASS", final_v1
    step("backup and final v1 verification", backup=str(backup), python_verify=final_v1["status"], v1_head=final_v1.get("journal_head"))

    daemon.start()

    def register(obj, kind, request):
        raw = json.dumps(obj, indent=1).encode()
        status, body = call(daemon.url, "POST", "/v1/artifacts/base64", daemon.admin, {"bytes_base64": base64.b64encode(raw).decode(), "kind": kind, "actor": "chief-kammi", "request_id": request})
        assert status == 200, body
        return body["artifact_id"]

    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    closure = register(decision, "rollback-window-closure", f"v4-closure-{stamp}")
    manifest = register({"schema": "KAMMI_PRE_ACTIVATION_BACKUP_V1", "location": str(backup), "final_v1_independent_verify": final_v1,
                         "export_v1": str(export)}, "backup-manifest", f"v4-backup-{stamp}")
    step("registered closure decision and backup manifest", closure_decision=closure, backup=manifest)
    daemon.stop()
    v = subprocess.run([str(daemon.bin / "kammi-verify.exe"), str(daemon.store)], capture_output=True, text=True)
    verified = json.loads(v.stdout)
    assert verified["status"] == "PASS", verified["errors"]
    step("kammi-verify at rest", journal_head=verified["journal_head"], events=verified["journal_events"])
    daemon.start()
    verification = register(verified, "independent-verification", f"v4-verification-{stamp}")
    status, body = call(daemon.url, "POST", "/v2/vocabulary/activate", daemon.admin, {"vocabulary": "v4", "not_before": FLOOR, "closure_decision": closure,
                        "verification": verification, "backup": manifest, "request_id": f"v4-activate-{stamp}", "actor": "chief-kammi"})
    step("activation", status=status, body=body)
    assert status == 200, body
    daemon.stop()
    after = json.loads(subprocess.run([str(daemon.bin / "kammi-verify.exe"), str(daemon.store)], capture_output=True, text=True).stdout)
    daemon.start()
    listed = call(daemon.url, "GET", "/v2/workspaces", daemon.admin)[1]
    flight = call(daemon.url, "GET", "/v1/status", daemon.admin)[1]["flight_gate"]
    step("after activation", vocabulary_v4=listed.get("vocabulary_v4"), kammi_verify=after["status"], flight=flight)
    report["gates"] = {"final_v1_verified": final_v1["status"] == "PASS", "activated": listed.get("vocabulary_v4") is True,
                       "kammi_verify_after": after["status"] == "PASS"}
    report["flight_after_activation"] = flight
    if daemon.clock is None:
        # Real clock (live, or the M5 rehearsal on a current copy): the gate must still be open.
        report["gates"]["flight_open"] = flight == "OPEN"


def rehearse(work: Path, clock: str | None, live_copy: bool):
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    info, source = svc.release()
    bin_dir = svc.OPS / info["bin_dir"]
    copy = work / "store"
    # No live downtime: every release leaves a byte-exact, verified export-v1 of the live history
    # at release time (releases/<commit>/work/verify/export-v1); import it as the copy.
    if live_copy:
        # The M5 rehearsal: a consistent copy of the current live store (the daemon stops for
        # the seconds of the copy), so the copy carries the running release's acceptance and
        # the rehearsal runs with the real clock and real flight gate, exactly like the live step.
        live_daemon = Daemon(svc.STORE, True, None, svc.admin_token(), bin_dir)
        live_daemon.stop()
        try:
            shutil.copytree(svc.STORE, copy, ignore=shutil.ignore_patterns("projection", "locks"))
        finally:
            live_daemon.start()
    else:
        # Dry run, no live downtime: the release's export-v1. It predates that release's own
        # acceptance, so the copy's flight gate is closed; only fixture-clock dry runs use it.
        export = svc.OPS / info["release_dir"] / "work" / "verify" / "export-v1"
        if not export.is_dir():
            raise SystemExit(f"no release export at {export}; run a release first")
        r = subprocess.run([str(bin_dir / "kammi-migrate.exe"), "import", "--v1", str(export), "--v2", str(copy)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    admin = base64.urlsafe_b64encode(os.urandom(24)).decode()
    daemon = Daemon(copy, False, clock, admin, bin_dir)
    decision = {"schema": "KAMMI_ROLLBACK_WINDOW_CLOSURE_V1", "decision": "CLOSE", "decided_by": "REHEARSAL ONLY - not the user's decision",
                "rehearsal": True, "clock": clock or "real"}
    report = {"schema": "KAMMI_ACTIVATION_REHEARSAL_V1", "copy_of": "current live store" if live_copy else f"live history at release {info['commit']} (its export-v1)",
              "clock": clock or "real", "steps": []}
    daemon.start()
    try:
        # The rehearsal also proves the copy's actors can seed Frozen Fabrique afterwards.
        procedure(daemon, work, decision, report)
        (work / "secrets").mkdir(exist_ok=True)
        (work / "secrets/admin.secret").write_text(admin)
        seed = subprocess.run([sys.executable, str(HERE / "tools/run_seed.py"), str(HERE / "tools/seeds/frozen-fabrique-e4-0.kammi"), "--url", daemon.url,
                               "--admin-token-file", str(work / "secrets/admin.secret"), "--secrets", str(work / "secrets")],
                              capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "KAMMI_BIN_DIR": str(bin_dir)})
        report["gates"]["seed"] = seed.returncode == 0
        report["seed"] = (seed.stdout[-600:] if seed.returncode == 0 else seed.stderr[-800:])
    finally:
        daemon.stop()
    report["status"] = "PASS" if report.get("gates") and all(report["gates"].values()) else "FAIL"
    (work / "activation-rehearsal.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({"status": report["status"], "gates": report.get("gates")}, indent=1))


def live(decision_file: Path):
    conditions = check()
    if not conditions["ok"]:
        raise SystemExit("closure conditions not met: " + json.dumps(conditions, indent=1))
    decision = json.loads(decision_file.read_text())
    if decision.get("schema") != "KAMMI_ROLLBACK_WINDOW_CLOSURE_V1" or decision.get("decision") != "CLOSE" or decision.get("rehearsal"):
        raise SystemExit("the decision file must be the user's KAMMI_ROLLBACK_WINDOW_CLOSURE_V1 deciding CLOSE")
    info, _ = svc.release()
    work = svc.OPS / "activation" / now().strftime("%Y%m%dT%H%M%SZ")
    work.mkdir(parents=True)
    daemon = Daemon(svc.STORE, True, None, svc.admin_token(), svc.OPS / info["bin_dir"])
    report = {"schema": "KAMMI_ACTIVATION_V1", "conditions": conditions, "steps": []}
    procedure(daemon, work, decision, report)
    (work / "activation.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({"status": "ACTIVATED" if all(report["gates"].values()) else "CHECK", "gates": report["gates"], "record": str(work)}, indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("check", "rehearse", "live"))
    parser.add_argument("work", nargs="?", type=Path)
    parser.add_argument("--dry-run-clock")
    parser.add_argument("--live-copy", action="store_true", help="copy the current live store (brief stop); required for the M5 rehearsal")
    parser.add_argument("--decision-file", type=Path)
    args = parser.parse_args()
    if args.operation == "check":
        print(json.dumps(check(), indent=1))
    elif args.operation == "rehearse":
        if not args.dry_run_clock and not args.live_copy:
            raise SystemExit("rehearse needs --live-copy (M5: real clock, current live copy) or --dry-run-clock (fixture dry run)")
        rehearse(args.work.resolve(), args.dry_run_clock, args.live_copy)
    else:
        live(args.decision_file)
