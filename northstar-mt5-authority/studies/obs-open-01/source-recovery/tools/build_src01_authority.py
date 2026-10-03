"""Build the deterministic SRC-01 source/compiler/configuration manifest.

This tool records external authority by content hash. It never copies large
terminal data into the repository and never reads confirmation observations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TERMINAL = Path(
    r"C:\Users\shuga\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
)
DEFAULT_COMPILER = Path(r"C:\Program Files\MetaTrader 5\metaeditor64.exe")
DEFAULT_RUNTIME = Path(r"C:\Program Files\MetaTrader 5\terminal64.exe")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def file_record(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        return {"label": label, "status": "NOT_FOUND", "path": str(path)}
    return {
        "label": label,
        "status": "PRESENT",
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def config_record(path: Path) -> dict[str, object]:
    return file_record(path, f"config:{path.name}")


def build(terminal: Path, compiler: Path, runtime: Path) -> dict[str, object]:
    ind = terminal / "MQL5" / "Indicators"
    exp = terminal / "MQL5" / "Experts" / "Research"
    cfg = ROOT / "studies" / "obs-open-01" / "source-recovery" / "config"
    recovery = ROOT / "studies" / "obs-open-01" / "source-recovery"
    frozen = recovery / "authority"
    files = [
        file_record(ind / "BreakOut.mq5", "original_source"),
        file_record(ind / "BreakOut2.mq5", "translated_source"),
        file_record(ind / "OpeningRangeGrammar_v2_00_LegacyStateMachine.mq5", "v2_source"),
        file_record(exp / "OBS_OPEN_SRC01_BufferCaptureEA.mq5", "capture_source"),
        file_record(ind / "BreakOut.ex5", "original_ex5"),
        file_record(ind / "BreakOut2.ex5", "translated_ex5"),
        file_record(ind / "OpeningRangeGrammar_v2_00_LegacyStateMachine.ex5", "v2_ex5"),
        file_record(exp / "OBS_OPEN_SRC01_BufferCaptureEA.ex5", "capture_ex5"),
        file_record(compiler, "compiler"),
        file_record(runtime, "runtime"),
        file_record(recovery / "compile-capture-grouped-abi.log", "compiler_receipt"),
        file_record(recovery / "SRC01_protocol.md", "metrology_protocol"),
    ]
    files.extend(config_record(cfg / name) for name in sorted(os.listdir(cfg)))
    files.extend(
        file_record(frozen / name, f"frozen_authority:{name}")
        for name in sorted(os.listdir(frozen))
    )
    files.extend(
        file_record(recovery / "tools" / name, f"metrology_tool:{name}")
        for name in sorted(os.listdir(recovery / "tools"))
    )
    snapshot_sources = {
        "BreakOut.mq5": ind / "BreakOut.mq5",
        "BreakOut2.mq5": ind / "BreakOut2.mq5",
        "OpeningRangeGrammar_v2_00_LegacyStateMachine.mq5": ind / "OpeningRangeGrammar_v2_00_LegacyStateMachine.mq5",
        "BreakOut.ex5": ind / "BreakOut.ex5",
        "BreakOut2.ex5": ind / "BreakOut2.ex5",
        "OpeningRangeGrammar_v2_00_LegacyStateMachine.ex5": ind / "OpeningRangeGrammar_v2_00_LegacyStateMachine.ex5",
        "OBS_OPEN_SRC01_BufferCaptureEA.mq5": exp / "OBS_OPEN_SRC01_BufferCaptureEA.mq5",
        "OBS_OPEN_SRC01_BufferCaptureEA.ex5": exp / "OBS_OPEN_SRC01_BufferCaptureEA.ex5",
    }
    snapshot_parity = []
    for name, live in snapshot_sources.items():
        retained = frozen / name
        live_hash = sha256(live) if live.is_file() else None
        retained_hash = sha256(retained) if retained.is_file() else None
        snapshot_parity.append({
            "name": name,
            "live_sha256": live_hash,
            "retained_sha256": retained_hash,
            "status": "PASS" if live_hash is not None and live_hash == retained_hash else "FAIL",
        })
    manifest = {
        "schema": "OBS_OPEN_SRC01_AUTHORITY_V1",
        "generation": "LEGACY_BREAKOUT_OBSERVER_V1",
        "parent_generations": ["RECONSTRUCTED_OBSERVER_V1"],
        "confirmation_state": "FROZEN_UNOPENED",
        "confirmation_sessions": 69,
        "clock": {
            "civil_zone": "America/New_York",
            "begin": "09:30",
            "period_end": "09:35",
            "area_end": "09:40",
            "status": "SOURCE_CLOCK_INPUTS_FROZEN",
            "timestamp_semantics": "SOURCE_CLOCK_WALL_TIME",
            "new_york_clock_transport": "NOT_EVALUATED_BY_SRC01",
        },
        "timeframes": ["M1", "M5"],
        "boundary_minutes": ["09:29", "09:30", "09:34", "09:35", "09:39", "09:40"],
        "legacy_buffers": {"original": [0, 1, 2, 3], "translated": [0, 1, 2, 3], "v2_compatibility": [17, 18, 19, 20]},
        "causal_buffers": {"lifecycle": 4, "geometry_known": 25, "interaction_eligible": 8, "location": 9, "grammar_event": 10},
        "source_authority": files,
        "retained_snapshot_parity": {
            "rows": snapshot_parity,
            "status": "PASS" if all(row["status"] == "PASS" for row in snapshot_parity) else "FAIL",
        },
        "synthetic_fixture": file_record(
            ROOT / "studies" / "obs-open-01" / "source-recovery" / "tools" / "test_src01_boundary_fixtures.py",
            "controlled_late_endpoint_fixture",
        ),
        "capture_contract": {
            "online": "CURRENT_OPEN|COMPLETED_BAR|CURRENT_TICK",
            "reload": "HISTORICAL_RELOAD",
            "cell_key": ["capture_mode", "event_kind", "symbol", "timeframe", "bar_open", "shift"],
            "missing_value": "NA",
            "parity": "exact canonical cell equality",
            "v2_runtime_abi": "GROUP_HEADINGS_ARE_POSITIONAL_STRING_INPUTS",
        },
    }
    encoded = json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True).encode()
    manifest["logical_manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal", type=Path, default=DEFAULT_TERMINAL)
    parser.add_argument("--compiler", type=Path, default=DEFAULT_COMPILER)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--output", type=Path, default=ROOT / "studies/obs-open-01/source-recovery/SRC01_authority_manifest.json")
    args = parser.parse_args()
    manifest = build(args.terminal, args.compiler, args.runtime)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
