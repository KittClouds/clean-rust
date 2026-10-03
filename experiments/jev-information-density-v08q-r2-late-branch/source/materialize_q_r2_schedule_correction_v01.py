"""Versioned field-path correction for the frozen Q-R2 schedule materializer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
SOURCE = EXP / "source/materialize_q_r2_schedule_v01.py"
OUT = RUN / "training-v01/schedule"
FAILURE = RUN / "provenance/q-r2-schedule-materializer-v01-failed-attempt.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_source() -> Any:
    spec = importlib.util.spec_from_file_location("jev_q_r2_original_schedule_source", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load original Q-R2 schedule implementation")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("xb") as destination:
        destination.write(data)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, path)


def main() -> int:
    source = load_source()
    require = source.require
    require(not OUT.exists(), f"refusing pre-existing schedule output: {OUT}")
    instrument_path = RUN / "provenance/q-r2-instrument-package-seal-v01.json"
    instrument = json.loads(instrument_path.read_text(encoding="utf-8"))
    source_entry = next((row for row in instrument.get("entries", [])
                         if row["path"].endswith("materialize_q_r2_schedule_v01.py")), None)
    require(source_entry is not None and sha(SOURCE) == source_entry["sha256"],
            "bound original schedule source changed")
    require(sha(source.CONTRACT) == source.EXPECTED["contract"]
            and sha(source.SOURCE_LOCK) == source.EXPECTED["source_lock"]
            and sha(source.PRIMARY) == source.EXPECTED["primary"], "Q-R2 schedule authority changed")
    packet = json.loads(source.PACKET.read_text(encoding="utf-8"))
    require(sha(source.PACKET) == source.EXPECTED["packet"]
            and packet.get("status") == "SEALED_AUTHORIZED_FOR_PHASE_EXECUTION",
            "Q-R2 schedule packet identity/status mismatch")
    contract = json.loads(source.CONTRACT.read_text(encoding="utf-8"))
    seeds = contract["paired_seed_design"]["seed_derivation"]["seeds"]
    require(len(seeds) == 24 and len(set(seeds)) == 24, "Q-R2 contract seed list invalid")
    failure = {"status": "Q_R2_SCHEDULE_MATERIALIZER_V01_FAILED_BEFORE_OUTPUT",
        "failure": "KeyError: 'seeds' at paired_seed_design.seeds; authoritative list is nested at paired_seed_design.seed_derivation.seeds",
        "source_sha256": sha(SOURCE), "output_directory_created": False,
        "correction_wrapper_preflight_failure": "KeyError: wrapper referenced EXPECTED['algorithm_source']; v01 intentionally binds its source through the sealed instrument inventory",
        "head_initialized": False, "training": False, "panel_opened": False, "evaluation": False,
        "preserved_at_utc": datetime.now(timezone.utc).isoformat()}
    require(not FAILURE.exists(), "refusing to replace schedule materializer failure receipt")
    atomic_write(FAILURE, json.dumps(failure, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")
    failure_sha = sha(FAILURE)

    primary = source.read_jsonl(source.PRIMARY)
    schedule = [row for seed in seeds for row in source.schedule_for_seed(primary, seed)]
    source.validate(primary, schedule, seeds)
    replay = [row for seed in seeds for row in source.schedule_for_seed(primary, seed)]
    encoded = b"".join(source.canonical(row) for row in schedule)
    require(encoded == b"".join(source.canonical(row) for row in replay),
            "corrected schedule failed deterministic replay")
    OUT.mkdir(parents=True, exist_ok=False)
    schedule_path = OUT / "fixed-schedule.jsonl"
    atomic_write(schedule_path, encoded)
    branch_order = {str(seed): (["LATE_SHAM_1X", "LATE_SHAM_HALF"] if i % 2 == 0
                                else ["LATE_SHAM_HALF", "LATE_SHAM_1X"])
                    for i, seed in enumerate(seeds)}
    correction_sha = sha(Path(__file__).resolve())
    manifest = {"status": "Q_R2_SCHEDULE_MATERIALIZED_PRE_INITIALIZATION",
        "schedule_sha256": sha(schedule_path), "schedule_rows": len(schedule), "seeds": seeds,
        "common_history_steps": [1, 80], "continuation_steps": [81, 120],
        "branch_order_by_seed": branch_order, "steps_per_epoch": 40, "total_steps": 120,
        "checkpoints": [80, 100, 120], "common_prefixes": 24, "continuations": 48,
        "run_contract_sha256": source.EXPECTED["contract"],
        "analysis_contract_sha256": source.EXPECTED["analysis"],
        "primary_manifest_sha256": source.EXPECTED["primary"],
        "algorithm_source_sha256": correction_sha,
        "source_correction": {"identity": "Q-R2-SCHEDULE-SEED-FIELD-PATH-CORRECTION-V01",
            "original_materializer_sha256": sha(SOURCE), "failure_receipt_sha256": failure_sha,
            "corrected_json_pointer": "/paired_seed_design/seed_derivation/seeds",
            "training_or_model_contact": False},
        "head_initialized": False, "training": False, "panel_opened": False, "evaluation": False}
    manifest_path = OUT / "fixed-schedule-manifest.json"
    atomic_write(manifest_path, source.canonical(manifest))
    seal = {"status": "Q_R2_SCHEDULE_SEALED_PRE_INITIALIZATION",
        "schedule_sha256": sha(schedule_path), "manifest_sha256": sha(manifest_path),
        "rows": len(schedule), "seed_count": len(seeds), "continuations": 48,
        "algorithm_source_sha256": correction_sha, "failure_receipt_sha256": failure_sha,
        "head_initialized": False, "training": False, "panel_read": False}
    atomic_write(OUT / "schedule-seal.json", source.canonical(seal))
    print(json.dumps(seal, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
