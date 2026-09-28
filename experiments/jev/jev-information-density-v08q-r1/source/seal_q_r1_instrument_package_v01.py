"""Seal exact Q-R1 execution sources before any paired head initialization."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
R1 = ROOT / "experiments/jev-information-density-v08q-r1"
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r1\training-v01")
PANEL_SEAL = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01\seals\q-r1-panel-input-terminal-seal-v01.json")
OUTPUT = RUN / "instrument-v01"
RUN_SHA = "e5fb3bd147bd5866849266937dc5b060abd8047c13faf2dea48908af518c1317"
ANALYSIS_SHA = "98d5f781d8f98a9a2e6f3737ddbcb2765bbb1f174c25a01292db1e3e5cc4e81b"
PANEL_ROOT = "f90fc1de0ce1e728e4b6c72cbc58756e2278c5932adb77dcf33f2b9dff2b6f53"
PANEL_SEAL_SHA = "064c1bef2dfe160396641be74e3a4419f16f0ead28cb0ab4b6978151d587dfe8"
PACKET_ROOT = "dfc1f1c9d1e59a1a9abd930f437f3227261e9fa91f85a70ff3ed4c849e6833c0"
PACKET_SHA = "80090a8011455395134f5ba8e0ef2a4eef33d4a78ccc795a137b9d7dc0bed7a4"
SCHEDULE_SHA = "f33b943e0fda2a065639d29786b8407b712b042d1acacbd85cd5b174d3ffd71c"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def need(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def expected_paths() -> list[Path]:
    return [
        R1 / "contracts/q-r1-run-contract-v01.json",
        R1 / "contracts/q-r1-analysis-contract-v01.json",
        R1 / "contracts/q-r1-panel-contract-v01.json",
        R1 / "seals/q-r1-packet-seal-and-authorization-v01.json",
        R1 / "source/run_q_r1_training_v01.py",
        R1 / "source/evaluate_q_r1_panel_v01.py",
        R1 / "source/analyze_q_r1_results_v01.py",
        R1 / "source/verify_q_r1_results_v01.py",
        R1 / "source/verify_q_r1_instrument_package_v01.py",
        R1 / "source/seal_q_r1_instrument_package_v01.py",
        R1 / "source/materialize_q_r1_schedule_v01.py",
        R1 / "source/verify_q_r1_schedule_v01.py",
        Q / "contracts/q-source-lock-v02.json",
        Q / "source/q_weighted_objective_v02.py",
        Q / "source/q_analysis_rules_v02.py",
        ROOT / "experiments/jev-frozen-readout-v01/probe.py",
        ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py",
        ROOT / "experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py",
        ROOT / "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py",
        RUN / "schedule/fixed-schedule.jsonl",
        RUN / "schedule/fixed-schedule-manifest.json",
        RUN / "schedule/schedule-seal.json",
        RUN / "schedule/independent-verification-v01.json",
        PANEL_SEAL,
    ]


def digest_entries(entries: list[dict[str, Any]]) -> str:
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
                   for row in sorted(entries, key=lambda item: item["path"]))
    return hashlib.sha256(body.encode()).hexdigest()


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    need(not OUTPUT.exists(), "instrument package already exists; never overwrite")
    need(not (RUN / "training").exists(), "head initialization/training namespace already exists")
    packet = R1 / "seals/q-r1-packet-seal-and-authorization-v01.json"
    schedule = RUN / "schedule/fixed-schedule.jsonl"
    panel = json.loads(PANEL_SEAL.read_text(encoding="utf-8"))
    need(sha(packet) == PACKET_SHA and sha(schedule) == SCHEDULE_SHA and sha(PANEL_SEAL) == PANEL_SEAL_SHA
         and panel.get("root_sha256") == PANEL_ROOT and panel.get("status") == "Q_R1_PANEL_FEATURE_CACHE_RADIUS_AND_TARGETS_SEALED_TRAINING_PENDING",
         "sealed packet, schedule, or panel prerequisite mismatch")
    paths = sorted((path.resolve() for path in expected_paths()), key=str)
    entries = []
    for path in paths:
        need(path.is_file(), f"instrument allowlist input missing: {path}")
        entries.append({"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)})
    root = digest_entries(entries)
    manifest = {
        "identity": "JEV-V08Q-R1-PRETRAIN-INSTRUMENT-PACKAGE-V01",
        "status": "SEALED_BEFORE_HEAD_INITIALIZATION",
        "run_contract_sha256": RUN_SHA, "analysis_contract_sha256": ANALYSIS_SHA,
        "packet_sha256": PACKET_SHA, "packet_bundle_root_sha256": PACKET_ROOT,
        "panel_input_root_sha256": PANEL_ROOT, "schedule_sha256": SCHEDULE_SHA,
        "entries_root_sha256": root, "entry_count": len(entries), "entries": entries,
        "execution_state": {"head_initialization": False, "training": False,
                            "panel_opened": False, "inference": False},
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = OUTPUT / "instrument-manifest-v01.json"
    write_new(manifest_path, manifest)
    seal = {
        "status": "Q_R1_PRETRAIN_INSTRUMENT_PACKAGE_SEALED",
        "identity": manifest["identity"], "manifest_sha256": sha(manifest_path),
        "entries_root_sha256": root, "entry_count": len(entries),
        "head_initialization": False, "training": False, "panel_opened": False,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    seal_path = OUTPUT / "instrument-seal-v01.json"
    write_new(seal_path, seal)
    print(json.dumps({**seal, "seal_sha256": sha(seal_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
