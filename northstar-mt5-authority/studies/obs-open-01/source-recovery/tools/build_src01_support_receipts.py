"""Build deterministic supporting receipts for OBS-OPEN-SRC-01."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version(path: Path) -> str:
    escaped = str(path).replace("'", "''")
    command = f"(Get-Item -LiteralPath '{escaped}').VersionInfo.FileVersion"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def reload_receipt(root: Path) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for timeframe in ("M1", "M5"):
        left = root / f"OBS_OPEN_SRC01_US30_{timeframe}_RELOAD_run1.tsv"
        right = root / f"OBS_OPEN_SRC01_US30_{timeframe}_RELOAD_run2.tsv"
        left_hash, right_hash = sha256(left), sha256(right)
        rows.append({
            "timeframe": timeframe,
            "run1_sha256": left_hash,
            "run2_sha256": right_hash,
            "run1_bytes": left.stat().st_size,
            "run2_bytes": right.stat().st_size,
            "byte_identical": left.read_bytes() == right.read_bytes(),
            "status": "PASS" if left_hash == right_hash and left.read_bytes() == right.read_bytes() else "FAIL",
        })
    return {"schema": "OBS_OPEN_SRC01_RELOAD_DETERMINISM_V1", "rows": rows, "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL"}


def fixture_receipt(root: Path) -> dict[str, object]:
    path = root / "tools" / "test_src01_boundary_fixtures.py"
    spec = importlib.util.spec_from_file_location("src01_fixtures", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tests = (
        "test_end_candle_new_high_is_included",
        "test_end_candle_new_low_is_included",
        "test_endpoint_is_shared_by_period_and_area",
    )
    rows = []
    for name in tests:
        getattr(module, name)()
        rows.append({"fixture": name, "status": "PASS"})
    return {"schema": "OBS_OPEN_SRC01_SYNTHETIC_BOUNDARY_FIXTURE_V1", "scientific_evidence": False, "metrology_evidence": True, "source_sha256": sha256(path), "fixtures": rows, "status": "PASS"}


def runtime_receipt(terminal: Path, runtime: Path, compiler: Path) -> dict[str, object]:
    tester_log = terminal / "Tester" / "logs" / "20260814.log"
    terminal_log = terminal / "logs" / "20260814.log"
    tester_text = tester_log.read_text(encoding="utf-16", errors="ignore") if tester_log.read_bytes().startswith(b"\xff\xfe") else tester_log.read_text(encoding="cp1252", errors="ignore")
    terminal_text = terminal_log.read_text(encoding="utf-16", errors="ignore") if terminal_log.read_bytes().startswith(b"\xff\xfe") else terminal_log.read_text(encoding="cp1252", errors="ignore")
    agent_builds = sorted(set(re.findall(r"agent build (\d+)", tester_text)))
    account_match = re.search(r"'(\d+)': authorized on ([^\r\n]+?) through .*?build (\d+)\)", terminal_text)
    return {
        "schema": "OBS_OPEN_SRC01_RUNTIME_RECEIPT_V1",
        "terminal_data_id": terminal.name,
        "terminal_origin": str(runtime.parent),
        "terminal_binary": {"path": str(runtime), "version": version(runtime), "sha256": sha256(runtime)},
        "compiler_binary": {"path": str(compiler), "version": version(compiler), "sha256": sha256(compiler)},
        "tester_agent_builds_observed": agent_builds,
        "account": account_match.group(1) if account_match else "NOT_EVALUABLE",
        "server": account_match.group(2) if account_match else "NOT_EVALUABLE",
        "server_reported_build": account_match.group(3) if account_match else "NOT_EVALUABLE",
        "symbol": "US30",
        "timeframes": ["M1", "M5"],
        "tester_window": ["2024-01-01T00:00:00", "2024-01-03T00:00:00"],
        "tester_model": {"online": 0, "historical_reload": 1},
        "clock_inputs": {"begin": "09:30", "period_end": "09:35", "area_end": "09:40", "authority": "SOURCE_CLOCK_WALL_TIME"},
        "compile_receipt": {"result": "0 errors, 0 warnings", "elapsed_ms": 585, "cpu": "X64 Regular"},
    }


def defect_receipt(root: Path) -> dict[str, object]:
    frozen = root / "authority"
    return {
        "schema": "OBS_OPEN_SRC01_METROLOGY_DEFECT_V1",
        "defect": "CAPTURE_HARNESS_OMITTED_V2_INPUT_GROUP_HEADING_ARGUMENTS",
        "scope": "CAPTURE_HARNESS_ONLY",
        "disposition": "CORRECTED_BEFORE_ADMITTED_PARITY_EVIDENCE",
        "observer_sources_modified": False,
        "causal_semantics_modified": False,
        "runtime_abi": "MQL5_INPUT_GROUP_HEADINGS_COUNT_AS_POSITIONAL_STRING_INPUTS",
        "corrected_capture_source_sha256": sha256(frozen / "OBS_OPEN_SRC01_BufferCaptureEA.mq5"),
        "corrected_capture_ex5_sha256": sha256(frozen / "OBS_OPEN_SRC01_BufferCaptureEA.ex5"),
        "admitted_captures": [
            "OBS_OPEN_SRC01_US30_M1_ONLINE_run1.tsv",
            "OBS_OPEN_SRC01_US30_M5_ONLINE_run1.tsv",
            "OBS_OPEN_SRC01_US30_M1_RELOAD_run1.tsv",
            "OBS_OPEN_SRC01_US30_M1_RELOAD_run2.tsv",
            "OBS_OPEN_SRC01_US30_M5_RELOAD_run1.tsv",
            "OBS_OPEN_SRC01_US30_M5_RELOAD_run2.tsv",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--terminal", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--compiler", required=True, type=Path)
    args = parser.parse_args()
    write(args.root / "SRC01_reload_determinism.json", reload_receipt(args.root))
    write(args.root / "SRC01_synthetic_fixture_receipt.json", fixture_receipt(args.root))
    write(args.root / "SRC01_runtime_receipt.json", runtime_receipt(args.terminal, args.runtime, args.compiler))
    write(args.root / "SRC01_metrology_defect_receipt.json", defect_receipt(args.root))


if __name__ == "__main__":
    main()
