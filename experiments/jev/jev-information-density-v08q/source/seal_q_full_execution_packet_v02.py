"""Bind the explicit Q full-run authorization to sealed code and parents."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
PACKET = RUN / "q-full-execution-packet-v02.json"
SEAL = RUN / "q-full-execution-packet-seal-v02.json"
PANEL_SEAL = PANEL / "seals/q-panel-phase-terminal-seal-v01.json"
INSTRUMENT = RUN / "instrument/q-execution-instrument-seal-v02.json"
IMPLEMENTATIONS = (
    "experiments/jev-information-density-v08q/source/run_q_training_v02.py",
    "experiments/jev-information-density-v08q/source/evaluate_q_panel_v02.py",
    "experiments/jev-information-density-v08q/source/analyze_q_results_v02.py",
    "experiments/jev-information-density-v08q/source/verify_q_full_execution_v02.py",
    "experiments/jev-information-density-v08q/source/q_analysis_rules_v02.py",
    "experiments/jev-information-density-v08q/source/q_weighted_objective_v02.py",
    "experiments/jev-information-density-v08q/source/seal_q_execution_instrument_v02.py",
    "experiments/jev-information-density-v08q/source/seal_q_full_execution_packet_v02.py",
    "experiments/jev-information-density-v08q/tests/test_q_rules_v02.py",
    "experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py",
    "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py",
    "experiments/jev-frozen-readout-v01/probe.py",
    "experiments/jev-frozen-scaling-v05/train_v05.py",
)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def entries_root(entries: list[dict[str, Any]]) -> str:
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(entries, key=lambda x: x["path"]))
    return hashlib.sha256(payload.encode()).hexdigest()


def write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    if PACKET.exists() or SEAL.exists() or (RUN / "training").exists() or (RUN / "evaluation").exists():
        raise RuntimeError("Q full execution packet is one-use; packet or execution output already exists")
    panel_seal = read_json(PANEL_SEAL)
    if panel_seal.get("root_sha256") != "1b99d39ab6bfed8173a5410f6c8ae0df442aae03038e31bab46b779bd1e039a6":
        raise RuntimeError("Q panel root is not the sealed passing panel")
    if sha(PANEL_SEAL) != "161511e6617ee012b3051590b4a9ce747f79a85228c02649e61ca8a10d080ad6":
        raise RuntimeError("Q panel terminal seal file changed")
    instrument = read_json(INSTRUMENT)
    if instrument.get("status") != "Q_EXECUTION_INSTRUMENTS_SEALED_PRE_HEAD_INITIALIZATION":
        raise RuntimeError("Q execution instruments are not sealed before initialization")
    if entries_root(instrument["entries"]) != instrument["root_sha256"]:
        raise RuntimeError("Q execution instrument root mismatch")
    for row in instrument["entries"]:
        path = Path(row["path"])
        if not path.is_file() or path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise RuntimeError(f"Q execution instrument source changed: {path}")
    source_lock_path = Q / "contracts/q-source-lock-v02.json"
    source_lock = read_json(source_lock_path)
    schedule_path = RUN / "schedule/fixed-schedule.jsonl"
    schedule_seal = read_json(RUN / "schedule/schedule-seal.json")
    if sha(schedule_path) != schedule_seal["schedule_sha256"] or schedule_seal["schedule_sha256"] != "af6688bd983cb01d113a4122938d71ab217143b7d17a43c25f376e04cf573662":
        raise RuntimeError("Q schedule seal mismatch")
    bindings = []
    for relative in IMPLEMENTATIONS:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        bindings.append({"path": relative.replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha(path)})
    packet_root = entries_root(bindings)
    authorization_text = (
        "Authorize the complete frozen JEV v0.8Q execution: verify the sealed panel; materialize the 12-run schedule and paired common initializations; "
        "verify that SHAM-LOW differs only by the 0.5 auxiliary loss multiplier; train all 12 runs to step 120; save checkpoints only at 40, 80, 100, and 120; "
        "seal all checkpoints and telemetry before opening the fresh panel once; emit all 408,000 predictions; run the frozen response-vector, bootstrap, "
        "same-seed labels, family and four-cell analysis; independently verify; seal and stop. No additional seeds, checkpoints, doses, extensions, or tuning."
    )
    packet = {
        "schema": "jev-v08q-full-execution-packet-v02",
        "identity": "JEV-V08Q-SINGLE-DOSE-GAIN-FULL-EXECUTION-V02",
        "authorization": {
            "phase": "Q_FULL_FROZEN_RUN_EVALUATION_AND_ANALYSIS",
            "explicit_user_authorization": True,
            "source": "current user instruction authorizing the complete Q execution packet after the passing fresh-panel seal",
            "statement": authorization_text,
            "statement_sha256": hashlib.sha256(authorization_text.encode()).hexdigest(),
        },
        "parents": {
            "run_contract_sha256": "5f6cd42b6de058a4fcdcbeb70b1939dbe944a6c973ee704a93148f9bea71d1ae",
            "analysis_contract_sha256": "b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc",
            "addendum_sha256": "363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3",
            "source_lock_sha256": sha(source_lock_path),
            "source_lock_root_sha256": source_lock["root_sha256"],
            "panel_root_sha256": panel_seal["root_sha256"],
            "panel_terminal_seal_sha256": sha(PANEL_SEAL),
            "schedule_sha256": sha(schedule_path),
            "schedule_seal_sha256": sha(RUN / "schedule/schedule-seal.json"),
            "execution_instrument_seal_sha256": sha(INSTRUMENT),
            "execution_instrument_root_sha256": instrument["root_sha256"],
        },
        "run_contract_sha256": "5f6cd42b6de058a4fcdcbeb70b1939dbe944a6c973ee704a93148f9bea71d1ae",
        "analysis_contract_sha256": "b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc",
        "addendum_sha256": "363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3",
        "panel_root_sha256": panel_seal["root_sha256"],
        "run": {
            "seeds": [2540205348, 2603246505, 3565067208],
            "arms": ["B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW"],
            "optimizer_steps_per_run": 120,
            "checkpoint_steps": [40, 80, 100, 120],
            "trained_runs": 12,
            "trained_checkpoints": 48,
            "shared_seed_initial_templates": 3,
            "prediction_rows": 408000,
            "panel_open_count": 1,
            "checkpoint_selection": False,
            "panel_feedback_during_training": False,
        },
        "implementation_bindings": bindings,
        "packet_root_sha256": packet_root,
        "failure_policy": "preserve partial one-use outputs and stop; no restart, replacement, or automatic retry",
        "prohibited": ["additional seeds", "extra checkpoints", "dose changes", "training extensions", "checkpoint selection", "panel replacement", "evaluation feedback", "hyperparameter or metric changes"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    RUN.mkdir(parents=True, exist_ok=True)
    write_exclusive(PACKET, packet)
    seal = {
        "schema": "jev-v08q-full-execution-packet-seal-v02",
        "status": "Q_FULL_EXECUTION_PACKET_SEALED_PRE_INITIALIZATION",
        "packet_sha256": sha(PACKET),
        "packet_root_sha256": packet_root,
        "implementation_count": len(bindings),
        "authorization_phase": packet["authorization"]["phase"],
        "panel_root_sha256": panel_seal["root_sha256"],
        "training_started": False,
        "panel_opened": False,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_exclusive(SEAL, seal)
    print(json.dumps({"status": seal["status"], "packet_sha256": seal["packet_sha256"], "packet_root_sha256": packet_root, "implementation_count": len(bindings), "training_started": False, "panel_opened": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
