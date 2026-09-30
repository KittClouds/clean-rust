"""Vault Phase 1, M5: the journaled v4 activation (amendment v4 section 6), scripted.

  python tools/activate.py check                                   closure conditions (read-only)
  python tools/activate.py rehearse <work> --live-copy            real-clock rehearsal on a current live copy
  python tools/activate.py live --rehearsal-report <report.json>   one-way step; report must match tool and live head

Procedure (the same in rehearsal and live):
 1. stop the daemon; back up the store (a byte copy); export-v1 and Python's independent_verify
    of that final v1 history (archived: the rollback window's last proof);
 2. start; register the closure decision and the backup manifest;
 3. stop; kammi-verify at rest (head H);
 4. start; register the verification (its registration follows H directly); activate;
 5. check: vocabulary v4 active, kammi-verify PASS, flight gate OPEN.
Live mode then seeds Frozen Fabrique (tools/seeds/frozen-fabrique-e4-0.kammi) as Chief Kammi.

`live` requires factual rollback, monitoring, and Library checks to pass. The program owner's
recorded instruction supersedes the former October 6 floor; no clock override is used. The decision
artifact records measured monitoring gaps and accepted fix-forward/rollback risks.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PY = HERE.parent / "kammi-ledger"
PYENV = PY / ".kammi-dev/cleanroom-env/Scripts/python.exe"
sys.path.insert(0, str(HERE / "tools"))
import rust_service as svc  # noqa: E402
from http_differential import free_port  # noqa: E402

NATIVE = str(PY / "vendor/runtime-v1/native")
MONITOR_PERIOD = timedelta(minutes=30)
MONITOR_STALE_AFTER = timedelta(minutes=45)
LIVE_HEALTH_TIMEOUT_SECONDS = 300
LIVE_HEALTH_POLL_SECONDS = 1
AMENDMENT_SCHEMA = "KAMMI_V4_EARLY_ACTIVATION_AMENDMENT_V1"
CLOSURE_SCHEMA = "KAMMI_ROLLBACK_WINDOW_CLOSURE_V2"


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


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def wait_for_stable_live_health(timeout_seconds=LIVE_HEALTH_TIMEOUT_SECONDS,
                                poll_seconds=LIVE_HEALTH_POLL_SECONDS, status_reader=None):
    """Wait for two consecutive healthy snapshots; never turn a missing lag into zero."""
    read_status = status_reader or svc.status
    deadline = time.monotonic() + timeout_seconds
    consecutive = 0
    last = None
    last_error = None
    while True:
        try:
            last = read_status()
            last_error = None
            if last.get("flight_gate") == "OPEN" and last.get("projection_lag") == 0:
                consecutive += 1
                if consecutive == 2:
                    return last
            else:
                consecutive = 0
        except Exception as error:  # transient startup/API failures remain fail-closed at timeout
            last_error = f"{type(error).__name__}: {error}"
            consecutive = 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("live Library did not report two consecutive OPEN/lag-zero health snapshots "
                               f"within {timeout_seconds}s; last_status={last!r}; last_error={last_error!r}")
        time.sleep(min(poll_seconds, remaining))


def validate_rehearsal_report(path: Path, activation_tool_sha256: str, source_head: str):
    """Require the exact passing rehearsal and unchanged journal head before irreversible activation."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"cannot read activation rehearsal report {path}: {error}") from error
    if report.get("schema") != "KAMMI_ACTIVATION_REHEARSAL_V1" or report.get("status") != "PASS":
        raise RuntimeError(f"activation requires a PASS live-copy rehearsal report: {path}")
    if report.get("activation_tool_sha256") != activation_tool_sha256:
        raise RuntimeError("activation tool changed after rehearsal; run a fresh live-copy rehearsal")
    if report.get("source_head") != source_head:
        raise RuntimeError("live journal head changed after rehearsal; run a fresh live-copy rehearsal")
    return report


def hash_tree(root: Path):
    """Hash every file by content and derive a path/size/hash inventory root."""
    entries = []
    total = 0
    # Sort the serialized, case-sensitive POSIX paths, not Windows Path objects (whose ordering
    # can differ from the bytewise order enforced by the Rust verifier).
    files = sorted(((path.relative_to(root).as_posix(), path)
                    for path in root.rglob("*") if path.is_file()), key=lambda pair: pair[0])
    for rel, path in files:
        h = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                h.update(chunk)
                size += len(chunk)
        entries.append({"path": rel, "bytes": size, "sha256": h.hexdigest()})
        total += size
    encoded = "".join(f"{row['path']}\0{row['bytes']}\0{row['sha256']}\n" for row in entries).encode()
    return {"root": str(root), "file_count": len(entries), "total_bytes": total,
            "inventory_sha256": digest_bytes(encoded), "files": entries}


def report_files():
    out = []
    for path in sorted((svc.OPS / "releases").glob("*/release-report.json")):
        try:
            raw = path.read_bytes()
            report = json.loads(raw)
        except (OSError, ValueError):
            out.append({"path": str(path), "readable": False})
            continue
        steps = report.get("steps", [])
        failed = report.get("status") == "FAIL"
        recovery = {s.get("step"): s for s in steps if isinstance(s, dict)}
        recovered = (failed and "FAILED" in recovery
                     and recovery.get("re-accepted previous release", {}).get("acceptance_identity")
                     and recovery.get("previous release serving", {}).get("flight") == "OPEN")
        out.append({"path": str(path), "sha256": digest_bytes(raw), "status": report.get("status"),
                    "failed_probe": recovery.get("FAILED", {}).get("error"),
                    "fallback_recovered": bool(recovered),
                    "last_flight": recovery.get("previous release serving", {}).get("flight")})
    return out


def windows_task_audit():
    """Read the actual Task Scheduler/service startup state; do not assume operational limits."""
    tasks_run = subprocess.run(["schtasks", "/Query", "/V", "/FO", "CSV"], capture_output=True, text=True)
    if tasks_run.returncode != 0:
        return {"ok": False, "error": tasks_run.stderr[-600:]}
    tasks = list(csv.DictReader(io.StringIO(tasks_run.stdout)))
    monitor_task = next((row for row in tasks if row.get("TaskName", "").endswith("\\KammiLibraryMonitor")), None)
    backup_tasks = [row for row in tasks if "kammi" in (row.get("TaskName", "") + row.get("Task To Run", "")).lower()
                    and any(term in (row.get("TaskName", "") + row.get("Task To Run", "")).lower()
                            for term in ("backup", "export-v1"))]
    def launches_daemon(command):
        command = command.lower()
        return bool(re.search(r"rust_service\.py[\"']?\s+[\"']?start\b", command)
                    or "kammi-ledgerd.exe" in command)

    startup_tasks = [row for row in tasks if row.get("Scheduled Task State") == "Enabled"
                     and launches_daemon(row.get("Task To Run", ""))]
    ps = ("$services=Get-CimInstance Win32_Service | Where-Object {$_.PathName -match 'kammi-ledgerd'} | "
          "Select-Object Name,StartMode,State,PathName; "
          "$startup=Get-CimInstance Win32_StartupCommand | Where-Object {$_.Command -match 'kammi-ledgerd|rust_service.py'} | "
          "Select-Object Name,Command,Location; "
          "[pscustomobject]@{services=@($services);startup=@($startup)} | ConvertTo-Json -Compress -Depth 4")
    boot_run = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    boot_records = None
    if boot_run.returncode == 0:
        try:
            boot_records = json.loads(boot_run.stdout or "{}")
        except ValueError:
            pass
    monitor_enabled = bool(monitor_task and monitor_task.get("Scheduled Task State") == "Enabled"
                           and monitor_task.get("Status") == "Ready")
    repeat = monitor_task.get("Repeat: Every", "") if monitor_task else ""
    monitor_period_30m = repeat == "0 Hour(s), 30 Minute(s)"
    services = boot_records.get("services") if boot_records else None
    services = services if isinstance(services, list) else ([services] if services else [])
    startup_entries = boot_records.get("startup") if boot_records else None
    startup_entries = startup_entries if isinstance(startup_entries, list) else ([startup_entries] if startup_entries else [])
    automatic_service = any(str(row.get("StartMode", "")).lower() in {"auto", "automatic"}
                            for row in services if isinstance(row, dict))
    startup_daemon_entry = any(launches_daemon(row.get("Command", ""))
                               for row in startup_entries if isinstance(row, dict))
    return {
        "ok": monitor_enabled and monitor_period_30m and boot_records is not None,
        "monitor_task": {k: monitor_task.get(k) for k in ("TaskName", "Status", "Logon Mode", "Task To Run",
                         "Scheduled Task State", "Repeat: Every", "Last Result")} if monitor_task else None,
        "backup_tasks": [{"TaskName": r.get("TaskName"), "Task To Run": r.get("Task To Run")} for r in backup_tasks],
        "startup_tasks": [{"TaskName": r.get("TaskName"), "Task To Run": r.get("Task To Run")} for r in startup_tasks],
        "startup_services": services,
        "startup_entries": startup_entries,
        "monitor_enabled": monitor_enabled, "monitor_period_30m": monitor_period_30m,
        "monitor_requires_interactive_logon": bool(monitor_task and monitor_task.get("Logon Mode") == "Interactive only"),
        "scheduled_backup_configured": bool(backup_tasks),
        "daemon_autostart_configured": bool(startup_tasks or automatic_service or startup_daemon_entry),
    }


def monitoring_audit(raw: bytes, at=None, reports=None):
    """Measure actual cadence, gaps, freshness, warnings, and unexplained closed samples."""
    at = at or now()
    rows, malformed = [], []
    for line_no, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            stamp = datetime.fromisoformat(row["utc"]).astimezone(timezone.utc)
            rows.append((stamp, row))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            malformed.append(line_no)
    ordered = all(rows[i - 1][0] < rows[i][0] for i in range(1, len(rows)))
    gaps = []
    max_gap = timedelta(0)
    for (left_at, left), (right_at, right) in zip(rows, rows[1:]):
        span = right_at - left_at
        max_gap = max(max_gap, span)
        if span > MONITOR_PERIOD + timedelta(minutes=15):
            gaps.append({"from": left_at.isoformat(), "to": right_at.isoformat(),
                         "seconds": int(span.total_seconds()), "samples": [left.get("journal_events"), right.get("journal_events")]})
    releases = reports if reports is not None else report_files()
    intervals = []
    for report in releases:
        report_path = Path(report.get("path", ""))
        if not report_path.exists():
            continue
        try:
            value = json.loads(report_path.read_text(encoding="utf-8"))
            start = datetime.strptime(value["downtime_started"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            end = datetime.strptime(value["downtime_ended"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            intervals.append((start, end))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    unexplained_closed = []
    warnings = 0
    for stamp, row in rows:
        warnings += int(row.get("warning") is not False)
        if row.get("flight_gate") != "OPEN" and not any(a <= stamp <= b for a, b in intervals):
            unexplained_closed.append(stamp.isoformat())
    last = rows[-1][0] if rows else None
    age = at - last if last else None
    latest_row = rows[-1][1] if rows else {}
    task_audit = windows_task_audit()
    return {
        "schema": "KAMMI_ACTIVATION_MONITORING_AUDIT_V1",
        "snapshot_sha256": digest_bytes(raw),
        "sample_count": len(rows), "malformed_lines": malformed, "strictly_ordered": ordered,
        "gap_count": len(gaps), "gaps": gaps, "max_gap_seconds": int(max_gap.total_seconds()),
        "warning_count": warnings, "unexplained_closed_samples": unexplained_closed,
        "latest_sample_utc": last.isoformat() if last else None,
        "latest_age_seconds": int(age.total_seconds()) if age is not None else None,
        "latest_sample_fresh": bool(age is not None and timedelta(0) <= age <= MONITOR_STALE_AFTER),
        "latest_flight_gate": latest_row.get("flight_gate"),
        "latest_projection_lag": latest_row.get("projection_lag"),
        "windows_task_audit": task_audit,
        "scheduled_backup_configured": task_audit.get("scheduled_backup_configured"),
        "monitor_requires_interactive_logon": task_audit.get("monitor_requires_interactive_logon"),
        "daemon_autostart_configured": task_audit.get("daemon_autostart_configured"),
        "ok": bool(rows) and not malformed and ordered and warnings == 0 and not unexplained_closed
              and age is not None and timedelta(0) <= age <= MONITOR_STALE_AFTER
              and latest_row.get("flight_gate") == "OPEN" and latest_row.get("projection_lag") == 0
              and task_audit.get("ok") is True,
    }


def rollback_audit():
    """Check the actual frozen Python rollback material and the recorded fallback execution."""
    reports = report_files()
    backup_root = svc.OPS / "backups" / "v1-pre-cutover-20260928"
    backup = hash_tree(backup_root) if backup_root.is_dir() else {"file_count": 0, "total_bytes": 0}
    backup.pop("files", None)
    py_ok = PY.is_dir() and PYENV.is_file() and (svc.OPS / "ROLLBACK.md").is_file()
    python_verify = {"status": "NOT_RUN"}
    if py_ok and backup.get("file_count", 0):
        env = {**os.environ, "PATH": NATIVE + os.pathsep + os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
        code = ("import sys,json;sys.path.insert(0,'.');from scripts.independent_verify import verify_store;"
                "from pathlib import Path;print(json.dumps(verify_store(Path(sys.argv[1]))))")
        checked = subprocess.run([str(PYENV), "-c", code, str(backup_root)], cwd=PY, capture_output=True,
                                 text=True, env=env, timeout=900)
        if checked.returncode == 0:
            try:
                result = json.loads(checked.stdout)
                python_verify = {"status": result.get("status"), "journal_head": result.get("journal_head")}
            except ValueError:
                python_verify = {"status": "INVALID_OUTPUT"}
        else:
            python_verify = {"status": "FAIL", "returncode": checked.returncode, "stderr_tail": checked.stderr[-600:]}
    failed = [r for r in reports if r.get("status") == "FAIL"]
    reports_valid = bool(reports) and all(r.get("status") in {"PASS", "FAIL"} and r.get("sha256") for r in reports)
    fallback_proven = bool(failed) and all(r.get("fallback_recovered") for r in failed)
    return {
        "schema": "KAMMI_ROLLBACK_EVIDENCE_AUDIT_V1",
        "python_tree_present": py_ok, "legacy_backup": backup,
        "python_verification": python_verify, "release_reports": reports,
        "release_report_count": len(reports), "release_reports_valid": reports_valid,
        "failed_release_count": len(failed), "all_failed_releases_recovered": fallback_proven,
        "rollback_available": py_ok and backup.get("file_count", 0) > 0 and python_verify.get("status") == "PASS",
        "previous_release_rollback_proven": fallback_proven,
    }


def owner_closure_acknowledges(decision: dict | None) -> bool:
    """Whether an explicit owner CLOSE decision accepts the immediate, fix-forward route."""
    if not isinstance(decision, dict):
        return False
    risk = decision.get("risk_acceptance")
    required = (
        "early_activation", "known_monitoring_gaps", "known_rollback_evidence", "fix_forward",
        "rollback_to_python_ends", "backup_policy_reviewed", "monitoring_policy_reviewed",
        "restart_policy_reviewed", "source_publicity_reviewed",
    )
    return (
        decision.get("schema") == CLOSURE_SCHEMA
        and decision.get("decision") == "CLOSE"
        and decision.get("decision_authority") == "PROGRAM_OWNER"
        and bool(decision.get("decision_record"))
        and isinstance(risk, dict)
        and all(risk.get(field) is True for field in required)
    )


def monitoring_gate(monitoring: dict, decision: dict | None) -> dict:
    """Keep live health strict; allow only explicitly accepted historical/operational gaps."""
    task = monitoring.get("windows_task_audit") or {}
    risk = (decision or {}).get("risk_acceptance") or {}
    owner_valid = owner_closure_acknowledges(decision)
    history_deviations = []
    if monitoring.get("gap_count", 0):
        history_deviations.append(f"monitor_gaps:{monitoring['gap_count']}")
    if monitoring.get("unexplained_closed_samples"):
        history_deviations.append(
            f"unexplained_closed_samples:{len(monitoring['unexplained_closed_samples'])}"
        )
    if task.get("scheduled_backup_configured") is False:
        history_deviations.append("scheduled_backup_not_configured")
    if task.get("monitor_requires_interactive_logon") is True:
        history_deviations.append("monitor_requires_interactive_logon")
    if task.get("daemon_autostart_configured") is False:
        history_deviations.append("daemon_autostart_not_configured")

    current_health = (
        monitoring.get("sample_count", 0) > 0
        and not monitoring.get("malformed_lines")
        and monitoring.get("strictly_ordered") is True
        and monitoring.get("warning_count") == 0
        and monitoring.get("latest_sample_fresh") is True
        and monitoring.get("latest_flight_gate") == "OPEN"
        and monitoring.get("latest_projection_lag") == 0
        and task.get("ok") is True
        and task.get("monitor_enabled") is True
        and task.get("monitor_period_30m") is True
    )
    required_acceptances = []
    if monitoring.get("gap_count", 0) or monitoring.get("unexplained_closed_samples"):
        required_acceptances.extend(("known_monitoring_gaps", "monitoring_policy_reviewed"))
    if task.get("scheduled_backup_configured") is False:
        required_acceptances.append("backup_policy_reviewed")
    if task.get("monitor_requires_interactive_logon") is True:
        required_acceptances.append("monitoring_policy_reviewed")
    if task.get("daemon_autostart_configured") is False:
        required_acceptances.append("restart_policy_reviewed")
    missing_acceptance = [field for field in dict.fromkeys(required_acceptances) if risk.get(field) is not True]
    accepted = owner_valid and not missing_acceptance
    return {
        "ok": current_health and (not history_deviations or accepted),
        "current_health_ok": current_health,
        "strict_monitoring_ok": monitoring.get("ok") is True,
        "owner_closure_valid": owner_valid,
        "history_deviations": history_deviations,
        "missing_owner_acceptances": missing_acceptance,
        "snapshot_sha256": monitoring.get("snapshot_sha256"),
        "accepted_deviations": history_deviations if accepted else [],
    }


def check(owner_decision: dict | None = None):
    """Live factual preflight; historic deviations require explicit owner risk acceptance."""
    monitor_path = svc.OPS / "monitor.jsonl"
    monitor_raw = monitor_path.read_bytes() if monitor_path.is_file() else b""
    monitoring = monitoring_audit(monitor_raw)
    rollback = rollback_audit()
    library = {"ok": False, "error": "unavailable"}
    try:
        url = f"http://127.0.0.1:{svc.PORT}"
        _, status = call(url, "GET", "/v1/status", svc.admin_token())
        _, workspace = call(url, "GET", "/v2/workspaces", svc.admin_token())
        library = {
            "ok": status.get("flight_gate") == "OPEN" and not status.get("active_lease_resources")
                  and status.get("panel_exposures") == 0 and status.get("projection_lag") == 0
                  and workspace.get("vocabulary_v4") is False,
            "flight_gate": status.get("flight_gate"), "journal_head": status.get("journal_head"),
            "active_lease_resources": status.get("active_lease_resources"),
            "panel_exposures": status.get("panel_exposures"), "projection_lag": status.get("projection_lag"),
            "vocabulary_v4": workspace.get("vocabulary_v4"),
        }
    except Exception as error:  # pylint: disable=broad-except
        library = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    rollback["ok"] = (rollback["rollback_available"] and rollback["previous_release_rollback_proven"]
                       and rollback["release_reports_valid"])
    monitor_gate = monitoring_gate(monitoring, owner_decision)
    report = {
        "evaluated_at": now().isoformat(),
        "1_monitoring": monitoring,
        "monitoring_activation_gate": monitor_gate,
        "2_rollback_evidence": rollback,
        "3_library_quiescence": library,
        "decision_required": {
            "schema": CLOSURE_SCHEMA, "owner_must_acknowledge_early_activation": True,
            "owner_must_acknowledge_monitor_gaps": monitoring["gap_count"] > 0,
            "owner_must_acknowledge_rollback_history": rollback["failed_release_count"] > 0,
            "fix_forward_after_activation": True,
        },
    }
    report["ok"] = monitor_gate["ok"] and rollback["ok"] and library["ok"]
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


def procedure(daemon: Daemon, work: Path, decision: dict, report: dict, rollback: dict,
              expected_source_head: str | None = None):
    def step(name, **fields):
        report["steps"].append({"step": name, "utc": now().isoformat(), **fields})
        print(f"-- {name} {json.dumps(fields)[:320]}", flush=True)

    env = {**os.environ, "PATH": NATIVE + os.pathsep + os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    daemon.stop()
    backup_root = work / "backup-pre-activation"
    shutil.copytree(daemon.store, backup_root, ignore=shutil.ignore_patterns("projection", "projection-*", "locks"))
    backup_inventory = hash_tree(backup_root)
    backup_inventory["schema"] = "KAMMI_BACKUP_INVENTORY_V1"
    (work / "backup-inventory.json").write_text(json.dumps(backup_inventory, indent=1), encoding="utf-8")
    backup_check = subprocess.run([str(daemon.bin / "kammi-verify.exe"), str(backup_root)], capture_output=True, text=True)
    backup_verified = json.loads(backup_check.stdout) if backup_check.returncode == 0 else {"status": "FAIL", "error": backup_check.stderr[-800:]}
    assert backup_verified.get("status") == "PASS", backup_verified
    if expected_source_head is not None and backup_verified.get("journal_head") != expected_source_head:
        raise RuntimeError("live journal head changed after successful rehearsal; no v4 event was written: "
                           f"expected={expected_source_head} actual={backup_verified.get('journal_head')}")

    export = work / "final-export-v1"
    exported = subprocess.run([str(daemon.bin / "kammi-migrate.exe"), "export-v1", "--v2", str(backup_root), "--out", str(export)], capture_output=True, text=True, env=env)
    assert exported.returncode == 0, exported.stderr
    py = subprocess.run([str(PYENV), "-c", "import sys,json;sys.path.insert(0,'.');from scripts.independent_verify import verify_store;"
                         "from pathlib import Path;print(json.dumps(verify_store(Path(sys.argv[1]))))", str(export)], cwd=PY,
                        capture_output=True, text=True, env=env, timeout=900)
    final_v1 = json.loads(py.stdout) if py.returncode == 0 else {"status": "FAIL", "error": py.stderr[-800:]}
    assert final_v1.get("status") == "PASS", final_v1
    assert final_v1.get("journal_head") == backup_verified.get("journal_head"), {"backup": backup_verified, "v1": final_v1}
    (work / "final-v1-independent-verify.json").write_text(json.dumps(final_v1, indent=1), encoding="utf-8")
    step("backup inventory and independent rollback verification", backup=str(backup_root), files=backup_inventory["file_count"],
         inventory_sha256=backup_inventory["inventory_sha256"], backup_head=backup_verified["journal_head"], python_verify=final_v1["status"])

    daemon.start()

    def register_raw(raw, kind, request):
        status, body = call(daemon.url, "POST", "/v1/artifacts/base64", daemon.admin,
                           {"bytes_base64": base64.b64encode(raw).decode(), "kind": kind,
                            "actor": "chief-kammi", "request_id": request})
        assert status == 200, body
        return body["artifact_id"]

    def register_json(obj, kind, request):
        return register_raw(json.dumps(obj, indent=1).encode(), kind, request)

    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    effective_at = decision["effective_at"]
    # Audit the fresh, truthful sample before writing any activation evidence into the journal.
    if daemon.live:
        wait_for_stable_live_health()
        svc.monitor()
    monitor_raw = (svc.OPS / "monitor.jsonl").read_bytes()
    monitor = monitoring_audit(monitor_raw, at=now())
    monitor_gate = monitoring_gate(monitor, decision)
    if not monitor_gate["ok"]:
        raise RuntimeError("monitoring preflight changed or current health failed before evidence registration: "
                           + json.dumps({"audit": monitor, "activation_gate": monitor_gate}))

    activation_source = Path(__file__).read_bytes()
    activation_tool_sha256 = digest_bytes(activation_source)
    activation_source_path = work / "activation-tool.py"
    activation_source_path.write_bytes(activation_source)
    activation_tool_artifact = register_raw(activation_source, "activation-procedure-source",
                                            f"v4-activation-tool-{stamp}")
    amendment = register_json({"schema": AMENDMENT_SCHEMA, "decision_authority": "PROGRAM_OWNER",
                               "effective_at": effective_at, "removes_fixed_floor": True,
                               "amendment": "v4.1 immediate activation under recorded owner instruction",
                               "supersedes": "2026-10-06T00:00:00Z",
                               "activation_tool_artifact": activation_tool_artifact,
                               "activation_tool_sha256": activation_tool_sha256},
                              "protocol-amendment", f"v4-amendment-{stamp}")
    # Register the exact monitor history audited above.
    monitoring_artifact = register_raw(monitor_raw, "activation-monitor-history", f"v4-monitor-{stamp}")
    rollback_id = register_json(rollback, "rollback-evidence-audit", f"v4-rollback-audit-{stamp}")
    inventory_id = register_raw((work / "backup-inventory.json").read_bytes(),
                                "pre-activation-backup-inventory", f"v4-backup-inventory-{stamp}")
    backup_manifest = {
        "schema": "KAMMI_PRE_ACTIVATION_BACKUP_V2", "location": str(backup_root),
        "source_head": backup_verified["journal_head"], "file_count": backup_inventory["file_count"],
        "total_bytes": backup_inventory["total_bytes"], "inventory_sha256": backup_inventory["inventory_sha256"],
        "inventory_artifact": inventory_id,
        "inventory_artifact_path": str(work / "backup-inventory.json"),
        "kammi_verify": backup_verified, "python_export_verify": final_v1,
    }
    backup_id = register_json(backup_manifest, "pre-activation-backup", f"v4-backup-{stamp}")
    owner_decision = {
        **decision, "schema": CLOSURE_SCHEMA, "decision": "CLOSE", "decision_authority": "PROGRAM_OWNER",
        "amendment_artifact": amendment, "monitoring_snapshot_artifact": monitoring_artifact,
        "rollback_evidence_artifact": rollback_id,
        "monitoring_audit": {
            "snapshot_artifact": monitoring_artifact, "snapshot_sha256": monitor["snapshot_sha256"],
            "sample_count": monitor["sample_count"], "gap_count": monitor["gap_count"],
            "max_gap_seconds": monitor["max_gap_seconds"], "warning_count": monitor["warning_count"],
            "latest_sample_utc": monitor["latest_sample_utc"], "latest_sample_fresh": monitor["latest_sample_fresh"],
            "malformed_lines": monitor["malformed_lines"], "strictly_ordered": monitor["strictly_ordered"],
            "unexplained_closed_samples": monitor["unexplained_closed_samples"], "gaps": monitor["gaps"],
            "latest_flight_gate": monitor["latest_flight_gate"],
            "latest_projection_lag": monitor["latest_projection_lag"],
            "strict_monitoring_ok": monitor["ok"],
            "owner_accepted_deviations": monitor_gate["accepted_deviations"],
            "scheduled_backup_configured": monitor["scheduled_backup_configured"],
            "monitor_requires_interactive_logon": monitor["monitor_requires_interactive_logon"],
            "daemon_autostart_configured": monitor["daemon_autostart_configured"],
        },
        "operational_limits": {
            "scheduled_backup_configured": monitor["scheduled_backup_configured"],
            "monitor_requires_interactive_logon": monitor["monitor_requires_interactive_logon"],
            "daemon_autostart_configured": monitor["daemon_autostart_configured"],
            "source_publicity": "Public GitHub branch as reported in the current system guide; access status not independently queried.",
        },
        "rollback_summary": {"rollback_available": rollback["rollback_available"],
                             "previous_release_rollback_proven": rollback["previous_release_rollback_proven"],
                             "failed_release_count": rollback["failed_release_count"]},
    }
    closure = register_json(owner_decision, "rollback-window-closure", f"v4-closure-{stamp}")
    (work / "program-owner-closure-decision.json").write_text(json.dumps(owner_decision, indent=1), encoding="utf-8")
    (work / "monitoring-audit.json").write_text(json.dumps(monitor, indent=1), encoding="utf-8")
    (work / "rollback-evidence-audit.json").write_text(json.dumps(rollback, indent=1), encoding="utf-8")
    step("registered activation source, owner amendment, closure, monitoring snapshot, rollback audit, and backup manifest",
         activation_tool=activation_tool_artifact, activation_tool_sha256=activation_tool_sha256,
         amendment=amendment, closure_decision=closure, monitoring_snapshot=monitoring_artifact,
         rollback_evidence=rollback_id, backup=backup_id, actual_monitor_gaps=monitor["gap_count"])

    daemon.stop()
    v = subprocess.run([str(daemon.bin / "kammi-verify.exe"), str(daemon.store)], capture_output=True, text=True)
    if v.returncode != 0:
        raise RuntimeError("kammi-verify exited nonzero: " + v.stderr[-800:])
    verified = json.loads(v.stdout)
    assert verified["status"] == "PASS", verified.get("errors")
    step("kammi-verify at exact pre-activation head", journal_head=verified["journal_head"], events=verified["journal_events"])
    daemon.start()
    verification = register_json(verified, "independent-verification", f"v4-verification-{stamp}")
    payload = {"vocabulary": "v4", "effective_at": effective_at, "amendment": amendment,
               "closure_decision": closure, "verification": verification, "backup": backup_id,
               "monitoring_snapshot": monitoring_artifact, "rollback_evidence": rollback_id,
               "request_id": f"v4-activate-{stamp}", "actor": "chief-kammi"}
    status, body = call(daemon.url, "POST", "/v2/vocabulary/activate", daemon.admin, payload)
    step("activation", status=status, body=body)
    assert status == 200, body
    daemon.stop()
    after_run = subprocess.run([str(daemon.bin / "kammi-verify.exe"), str(daemon.store)], capture_output=True, text=True)
    assert after_run.returncode == 0, after_run.stderr
    after = json.loads(after_run.stdout)
    assert after["status"] == "PASS", after.get("errors")
    daemon.start()
    listed = call(daemon.url, "GET", "/v2/workspaces", daemon.admin)[1]
    flight = call(daemon.url, "GET", "/v1/status", daemon.admin)[1]["flight_gate"]
    step("after activation", vocabulary_v4=listed.get("vocabulary_v4"), kammi_verify=after["status"], flight=flight)
    report["gates"] = {"backup_verified": backup_verified["status"] == "PASS",
                       "legacy_rollback_verified": final_v1["status"] == "PASS",
                       "pre_activation_head_verified": verified["status"] == "PASS",
                       "activated": listed.get("vocabulary_v4") is True,
                       "kammi_verify_after": after["status"] == "PASS", "flight_open": flight == "OPEN"}
    report["flight_after_activation"] = flight


def rehearse(work: Path, live_copy: bool):
    if work.exists():
        raise SystemExit(f"refusing to overwrite existing rehearsal directory: {work}")
    if not live_copy:
        raise SystemExit("rehearsal requires --live-copy and the real Library clock")
    work.mkdir(parents=True)
    info, _ = svc.release()
    bin_dir = svc.OPS / info["bin_dir"]
    copy = work / "store"
    # Stop only the supervised live service while taking a consistent current copy.
    live_daemon = Daemon(svc.STORE, True, None, svc.admin_token(), bin_dir)
    live_daemon.stop()
    try:
        shutil.copytree(svc.STORE, copy, ignore=shutil.ignore_patterns("projection", "projection-*", "locks"))
    finally:
        live_daemon.start()
    admin = base64.urlsafe_b64encode(os.urandom(24)).decode()
    daemon = Daemon(copy, False, None, admin, bin_dir)
    effective_at = now().isoformat(timespec="milliseconds").replace("+00:00", "Z")
    decision = {"schema": CLOSURE_SCHEMA, "decision": "CLOSE", "decision_authority": "PROGRAM_OWNER",
                "decision_record": "Program owner authorized immediate activation; rehearsal only, no live journal write.",
                "effective_at": effective_at, "rehearsal": True,
                "risk_acceptance": {"early_activation": True, "known_monitoring_gaps": True,
                                    "known_rollback_evidence": True, "fix_forward": True,
                                    "rollback_to_python_ends": True, "backup_policy_reviewed": True,
                                    "monitoring_policy_reviewed": True, "restart_policy_reviewed": True,
                                    "source_publicity_reviewed": True}}
    # Refresh only the monitor file before auditing. The operation appends a truthful live sample;
    # it does not mutate the Library journal.
    wait_for_stable_live_health()
    svc.monitor()
    preflight = check(decision)
    if not preflight["ok"]:
        raise SystemExit("live preflight not ready for current-copy rehearsal: " + json.dumps(preflight, indent=1))
    daemon.start()
    try:
        live_copy_status = call(daemon.url, "GET", "/v1/status", daemon.admin)[1]
        source_head = live_copy_status["journal_head"]
        activation_tool_sha256 = digest_bytes(Path(__file__).read_bytes())
        report = {"schema": "KAMMI_ACTIVATION_REHEARSAL_V1", "copy_of": "current live store",
                  "source_release": info["commit"], "source_head": source_head,
                  "activation_tool_sha256": activation_tool_sha256, "clock": "real", "steps": []}
        # The rehearsal also proves the copy's actors can seed Frozen Fabrique afterwards.
        procedure(daemon, work, decision, report, preflight["2_rollback_evidence"], source_head)
        with tempfile.TemporaryDirectory(prefix="kammi-v4-rehearsal-") as secret_dir:
            secret_root = Path(secret_dir)
            admin_file = secret_root / "admin.secret"
            admin_file.write_text(admin)
            seed = subprocess.run([sys.executable, str(HERE / "tools/run_seed.py"), str(HERE / "tools/seeds/frozen-fabrique-e4-0.kammi"), "--url", daemon.url,
                                   "--admin-token-file", str(admin_file), "--secrets", str(secret_root)],
                                  capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "KAMMI_BIN_DIR": str(bin_dir)})
        report["gates"]["seed"] = seed.returncode == 0
        report["seed"] = (seed.stdout[-600:] if seed.returncode == 0 else seed.stderr[-800:])
    finally:
        daemon.stop()
    report["status"] = "PASS" if report.get("gates") and all(report["gates"].values()) else "FAIL"
    (work / "activation-rehearsal.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({"status": report["status"], "gates": report.get("gates")}, indent=1))


def live(decision_file: Path | None, rehearsal_report: Path | None):
    effective_at = now().isoformat(timespec="milliseconds").replace("+00:00", "Z")
    decision = {
        "schema": CLOSURE_SCHEMA, "decision": "CLOSE", "decision_authority": "PROGRAM_OWNER",
        "effective_at": effective_at,
        "decision_record": "Program owner superseded the October 6 waiting floor and authorized immediate activation.",
        "risk_acceptance": {"early_activation": True, "known_monitoring_gaps": True,
                            "known_rollback_evidence": True, "fix_forward": True,
                            "rollback_to_python_ends": True, "backup_policy_reviewed": True,
                            "monitoring_policy_reviewed": True, "restart_policy_reviewed": True,
                            "source_publicity_reviewed": True},
    }
    if decision_file:
        supplied = json.loads(decision_file.read_text(encoding="utf-8"))
        if supplied.get("decision") != "CLOSE" or supplied.get("decision_authority") != "PROGRAM_OWNER":
            raise SystemExit("decision file must record the program owner's CLOSE decision")
        decision.update(supplied)
        decision["effective_at"] = effective_at
    if rehearsal_report is None:
        raise SystemExit("live activation requires --rehearsal-report from a passing current live-copy rehearsal")
    activation_tool_sha256 = digest_bytes(Path(__file__).read_bytes())
    live_health = wait_for_stable_live_health()
    validate_rehearsal_report(rehearsal_report, activation_tool_sha256, live_health["journal_head"])
    # This is a real, truthful sample; historic gaps remain visible in the subsequent audit.
    svc.monitor()
    conditions = check(decision)
    if not conditions["ok"]:
        raise SystemExit("closure conditions not met: " + json.dumps(conditions, indent=1))
    info, _ = svc.release()
    work = svc.OPS / "activation" / now().strftime("%Y%m%dT%H%M%SZ")
    work.mkdir(parents=True, exist_ok=False)
    daemon = Daemon(svc.STORE, True, None, svc.admin_token(), svc.OPS / info["bin_dir"])
    report = {"schema": "KAMMI_ACTIVATION_V2", "conditions": conditions, "steps": [],
              "source_head": live_health["journal_head"], "activation_tool_sha256": activation_tool_sha256,
              "rehearsal_report": str(rehearsal_report.resolve())}
    (work / "program-owner-closure-decision-input.json").write_text(json.dumps(decision, indent=1), encoding="utf-8")
    try:
        procedure(daemon, work, decision, report, conditions["2_rollback_evidence"],
                  live_health["journal_head"])
    except BaseException:
        # A failed pre-activation check must not leave the live Library stopped.
        daemon.start()
        raise
    seed_result = {"status": "NOT_RUN"}
    if all(report["gates"].values()):
        with tempfile.TemporaryDirectory(prefix="kammi-v4-live-seed-") as secret_dir:
            secret_root = Path(secret_dir)
            admin_file = secret_root / "admin.secret"
            admin_file.write_text(daemon.admin)
            seeded = subprocess.run([sys.executable, str(HERE / "tools/run_seed.py"), str(HERE / "tools/seeds/frozen-fabrique-e4-0.kammi"), "--url", daemon.url,
                                     "--admin-token-file", str(admin_file), "--secrets", str(secret_root)],
                                    capture_output=True, text=True,
                                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "KAMMI_BIN_DIR": str(daemon.bin)})
        seed_result = {"status": "PASS" if seeded.returncode == 0 else "FAIL",
                       "stdout": seeded.stdout[-1200:], "stderr": seeded.stderr[-1200:]}
        report["gates"]["frozen_fabrique_seeded"] = seeded.returncode == 0
    report["frozen_fabrique_seed"] = seed_result
    report["status"] = "ACTIVATED" if report["gates"] and all(report["gates"].values()) else "PARTIAL"
    (work / "activation.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({"status": "ACTIVATED" if all(report["gates"].values()) else "CHECK", "gates": report["gates"], "record": str(work)}, indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("check", "rehearse", "live"))
    parser.add_argument("work", nargs="?", type=Path)
    parser.add_argument("--live-copy", action="store_true", help="copy the current live store (brief stop); required for a real-clock rehearsal")
    parser.add_argument("--decision-file", type=Path, help="optional owner decision document; the direct instruction in the current task is otherwise recorded")
    parser.add_argument("--rehearsal-report", type=Path,
                        help="required for live: PASS report from a rehearsal of this tool and the unchanged current journal head")
    args = parser.parse_args()
    if args.operation == "check":
        print(json.dumps(check(), indent=1))
    elif args.operation == "rehearse":
        rehearse(args.work.resolve(), args.live_copy)
    else:
        live(args.decision_file, args.rehearsal_report)
