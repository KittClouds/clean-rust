from __future__ import annotations

import importlib.util
from pathlib import Path


STUDY = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY / "source-recovery/tools/src01_boundary_audit.py"
SPEC = importlib.util.spec_from_file_location("src01_boundary_audit", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_admitted_online_captures_pass_boundary_and_causal_audit() -> None:
    root = STUDY / "source-recovery"
    m1 = MODULE.audit_capture(root / "OBS_OPEN_SRC01_US30_M1_ONLINE_run1.tsv", "PERIOD_M1")
    m5 = MODULE.audit_capture(root / "OBS_OPEN_SRC01_US30_M5_ONLINE_run1.tsv", "PERIOD_M5")
    assert m1["status"] == "PASS"
    assert m5["status"] == "PASS"
    assert m1["causal_commit_bar_open"] == "09:36"
    assert m5["causal_commit_bar_open"] == "09:40"
    m5_not_applicable = {row["boundary"] for row in m5["boundary_matrix"] if row["status"] == "NOT_APPLICABLE_TIMEFRAME_BOUNDARY"}
    assert m5_not_applicable == {"09:29", "09:34", "09:39"}
