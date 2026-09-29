"""Deterministic activation records for isolated integration-test stores only."""
from __future__ import annotations

import hashlib
import json


def register_v4_records(register, *, prefix: str, effective_at: str, source_head: str):
    """Register the same evidence shapes required by live activation on a disposable store."""
    amendment = register({
        "schema": "KAMMI_V4_EARLY_ACTIVATION_AMENDMENT_V1",
        "decision_authority": "PROGRAM_OWNER",
        "effective_at": effective_at,
        "removes_fixed_floor": True,
        "fixture": True,
    }, "protocol-amendment", f"{prefix}-amendment")

    sample = {"utc": effective_at, "flight_gate": "OPEN", "projection_lag": 0, "warning": False}
    snapshot = register(sample, "activation-monitor-history", f"{prefix}-monitor")
    snapshot_bytes = json.dumps(sample).encode()
    rollback = register({
        "schema": "KAMMI_ROLLBACK_EVIDENCE_AUDIT_V1",
        "rollback_available": True,
        "previous_release_rollback_proven": True,
        "python_verification": {"status": "PASS"},
        "release_reports_valid": True,
        "fixture": True,
    }, "rollback-evidence-audit", f"{prefix}-rollback")

    content_hash = hashlib.sha256(b"x").hexdigest()
    inventory_bytes = b"fixture.bin" + bytes([0]) + b"1" + bytes([0]) + content_hash.encode() + b"\n"
    inventory_hash = hashlib.sha256(inventory_bytes).hexdigest()
    inventory_artifact = register({
        "schema": "KAMMI_BACKUP_INVENTORY_V1",
        "inventory_sha256": inventory_hash,
        "file_count": 1,
        "total_bytes": 1,
        "files": [{"path": "fixture.bin", "bytes": 1, "sha256": content_hash}],
    }, "pre-activation-backup-inventory", f"{prefix}-inventory")
    backup = register({
        "schema": "KAMMI_PRE_ACTIVATION_BACKUP_V2",
        "source_head": source_head,
        "file_count": 1,
        "total_bytes": 1,
        "inventory_sha256": inventory_hash,
        "inventory_artifact": inventory_artifact,
        "kammi_verify": {"status": "PASS", "journal_head": source_head},
        "python_export_verify": {"status": "PASS", "journal_head": source_head},
        "fixture": True,
    }, "pre-activation-backup", f"{prefix}-backup")

    closure = register({
        "schema": "KAMMI_ROLLBACK_WINDOW_CLOSURE_V2",
        "decision": "CLOSE",
        "decision_authority": "PROGRAM_OWNER",
        "effective_at": effective_at,
        "amendment_artifact": amendment,
        "monitoring_snapshot_artifact": snapshot,
        "rollback_evidence_artifact": rollback,
        "monitoring_audit": {
            "snapshot_artifact": snapshot,
            "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
            "sample_count": 1,
            "gap_count": 0,
            "max_gap_seconds": 0,
            "warning_count": 0,
            "latest_sample_utc": effective_at,
            "latest_sample_fresh": True,
            "scheduled_backup_configured": False,
            "monitor_requires_interactive_logon": True,
            "daemon_autostart_configured": False,
        },
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
        "fixture": True,
    }, "rollback-window-closure", f"{prefix}-closure")

    return {
        "vocabulary": "v4",
        "effective_at": effective_at,
        "amendment": amendment,
        "closure_decision": closure,
        "backup": backup,
        "monitoring_snapshot": snapshot,
        "rollback_evidence": rollback,
    }
