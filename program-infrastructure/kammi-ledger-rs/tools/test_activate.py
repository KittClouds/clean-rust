"""Unit checks for factual activation preflight accounting."""

import json
import unittest
import csv
import io
import subprocess
from datetime import datetime, timezone
from unittest.mock import patch

import activate


class MonitoringAuditTests(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 9, 29, 17, 0, tzinfo=timezone.utc)
        self.task = {
            "ok": True,
            "monitor_enabled": True,
            "monitor_period_30m": True,
            "scheduled_backup_configured": False,
            "monitor_requires_interactive_logon": True,
            "daemon_autostart_configured": False,
        }

    def audit(self, rows):
        raw = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
        with patch.object(activate, "windows_task_audit", return_value=self.task):
            return activate.monitoring_audit(raw, at=self.at, reports=[])

    @staticmethod
    def owner_decision():
        return {
            "schema": activate.CLOSURE_SCHEMA,
            "decision": "CLOSE",
            "decision_authority": "PROGRAM_OWNER",
            "decision_record": "Immediate activation and known operational risks accepted.",
            "risk_acceptance": {
                "early_activation": True,
                "known_monitoring_gaps": True,
                "known_rollback_evidence": True,
                "fix_forward": True,
                "rollback_to_python_ends": True,
                "backup_policy_reviewed": True,
                "monitoring_policy_reviewed": True,
                "restart_policy_reviewed": True,
                "source_publicity_reviewed": True,
            },
        }

    @staticmethod
    def row(utc, **extra):
        return {"utc": utc, "flight_gate": "OPEN", "projection_lag": 0,
                "warning": False, **extra}

    def test_reports_real_gap_count_and_maximum(self):
        audit = self.audit([
            self.row("2026-09-29T16:00:00+00:00"),
            self.row("2026-09-29T17:00:00+00:00"),
        ])
        self.assertEqual(audit["gap_count"], 1)
        self.assertEqual(audit["max_gap_seconds"], 3600)
        self.assertTrue(audit["ok"])

    def test_warning_and_unexplained_closed_sample_fail_preflight(self):
        warning = self.row("2026-09-29T16:30:00+00:00", warning=True)
        closed = self.row("2026-09-29T17:00:00+00:00", flight_gate="CLOSED")
        audit = self.audit([warning, closed])
        self.assertEqual(audit["warning_count"], 1)
        self.assertEqual(len(audit["unexplained_closed_samples"]), 1)
        self.assertFalse(audit["ok"])

    def test_owner_can_accept_historical_gaps_but_not_bad_current_health(self):
        audit = self.audit([
            self.row("2026-09-29T15:00:00+00:00"),
            self.row("2026-09-29T16:00:00+00:00", flight_gate="CLOSED_PENDING_ACCEPTANCE"),
            self.row("2026-09-29T17:00:00+00:00"),
        ])
        self.assertEqual(audit["gap_count"], 2)
        self.assertEqual(len(audit["unexplained_closed_samples"]), 1)
        self.assertFalse(activate.monitoring_gate(audit, None)["ok"])

        gate = activate.monitoring_gate(audit, self.owner_decision())
        self.assertTrue(gate["ok"])
        self.assertFalse(gate["strict_monitoring_ok"])
        self.assertEqual(gate["snapshot_sha256"], audit["snapshot_sha256"])
        self.assertIn("monitor_gaps:2", gate["accepted_deviations"])
        self.assertIn("unexplained_closed_samples:1", gate["accepted_deviations"])

    def test_owner_ack_does_not_override_bad_latest_status_or_warning(self):
        for rows in (
            [self.row("2026-09-29T16:30:00+00:00"),
             self.row("2026-09-29T17:00:00+00:00", flight_gate="CLOSED")],
            [self.row("2026-09-29T17:00:00+00:00", warning=True)],
        ):
            with self.subTest(rows=rows):
                audit = self.audit(rows)
                self.assertFalse(activate.monitoring_gate(audit, self.owner_decision())["ok"])

    def test_owner_cannot_accept_malformed_monitor_history(self):
        raw = b'{"utc":"broken"}\n' + json.dumps(self.row("2026-09-29T17:00:00+00:00")).encode() + b"\n"
        with patch.object(activate, "windows_task_audit", return_value=self.task):
            audit = activate.monitoring_audit(raw, at=self.at, reports=[])
        self.assertEqual(audit["malformed_lines"], [1])
        self.assertFalse(activate.monitoring_gate(audit, self.owner_decision())["ok"])

    def test_owner_decision_must_be_explicit_and_accept_all_risks(self):
        decision = self.owner_decision()
        self.assertTrue(activate.owner_closure_acknowledges(decision))
        decision["risk_acceptance"]["fix_forward"] = False
        self.assertFalse(activate.owner_closure_acknowledges(decision))

    def test_out_of_order_history_fails_preflight(self):
        audit = self.audit([
            self.row("2026-09-29T16:30:00+00:00"),
            self.row("2026-09-29T16:00:00+00:00"),
        ])
        self.assertFalse(audit["strictly_ordered"])
        self.assertFalse(audit["ok"])

    def test_monitor_only_scheduled_task_is_not_daemon_autostart(self):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["TaskName", "Status", "Logon Mode", "Task To Run",
                                                     "Scheduled Task State", "Repeat: Every", "Last Result"])
        writer.writeheader()
        writer.writerow({"TaskName": "\\KammiLibraryMonitor", "Status": "Ready",
                         "Logon Mode": "Interactive only",
                         "Task To Run": 'pythonw.exe rust_service.py" monitor"',
                         "Scheduled Task State": "Enabled", "Repeat: Every": "0 Hour(s), 30 Minute(s)",
                         "Last Result": "0"})
        responses = [
            subprocess.CompletedProcess([], 0, stdout=output.getvalue(), stderr=""),
            subprocess.CompletedProcess([], 0, stdout=json.dumps({"services": [], "startup": []}), stderr=""),
        ]
        with patch.object(activate.subprocess, "run", side_effect=responses):
            audit = activate.windows_task_audit()
        self.assertTrue(audit["monitor_enabled"])
        self.assertTrue(audit["monitor_period_30m"])
        self.assertFalse(audit["daemon_autostart_configured"])

    def test_enabled_daemon_start_task_is_detected(self):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["TaskName", "Status", "Logon Mode", "Task To Run",
                                                     "Scheduled Task State", "Repeat: Every", "Last Result"])
        writer.writeheader()
        writer.writerow({"TaskName": "\\KammiStart", "Status": "Ready", "Logon Mode": "Interactive only",
                         "Task To Run": 'python.exe rust_service.py" start"',
                         "Scheduled Task State": "Enabled", "Repeat: Every": "", "Last Result": "0"})
        responses = [
            subprocess.CompletedProcess([], 0, stdout=output.getvalue(), stderr=""),
            subprocess.CompletedProcess([], 0, stdout=json.dumps({"services": [], "startup": []}), stderr=""),
        ]
        with patch.object(activate.subprocess, "run", side_effect=responses):
            audit = activate.windows_task_audit()
        self.assertTrue(audit["daemon_autostart_configured"])


if __name__ == "__main__":
    unittest.main()
