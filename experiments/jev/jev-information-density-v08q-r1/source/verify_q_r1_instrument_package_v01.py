"""Verify the explicit pre-run Q-R1 code/dependency package on exact paths."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
R1 = ROOT / "experiments/jev-information-density-v08q-r1"
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r1\training-v01")
PACKAGE = RUN / "instrument-v01"
MANIFEST = PACKAGE / "instrument-manifest-v01.json"
SEAL = PACKAGE / "instrument-seal-v01.json"
RUN_SHA = "e5fb3bd147bd5866849266937dc5b060abd8047c13faf2dea48908af518c1317"
ANALYSIS_SHA = "98d5f781d8f98a9a2e6f3737ddbcb2765bbb1f174c25a01292db1e3e5cc4e81b"
PANEL_ROOT = "f90fc1de0ce1e728e4b6c72cbc58756e2278c5932adb77dcf33f2b9dff2b6f53"
PANEL_SEAL_SHA = "064c1bef2dfe160396641be74e3a4419f16f0ead28cb0ab4b6978151d587dfe8"
PACKET_ROOT = "dfc1f1c9d1e59a1a9abd930f437f3227261e9fa91f85a70ff3ed4c849e6833c0"


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
        Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01\seals\q-r1-panel-input-terminal-seal-v01.json"),
    ]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest_entries(entries: list[dict[str, Any]]) -> str:
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
                   for row in sorted(entries, key=lambda item: item["path"]))
    return hashlib.sha256(body.encode()).hexdigest()


def verify() -> dict[str, Any]:
    manifest = read_json(MANIFEST)
    seal = read_json(SEAL)
    entries = manifest.get("entries", [])
    expected = sorted(str(path.resolve()) for path in expected_paths())
    actual = [row.get("path") for row in entries]
    need(actual == sorted(expected), "instrument package path set/order differs from explicit allowlist")
    need(manifest.get("run_contract_sha256") == RUN_SHA
         and manifest.get("analysis_contract_sha256") == ANALYSIS_SHA
         and manifest.get("panel_input_root_sha256") == PANEL_ROOT
         and manifest.get("packet_bundle_root_sha256") == PACKET_ROOT,
         "instrument package contract roots differ")
    root = digest_entries(entries)
    need(manifest.get("entries_root_sha256") == root and seal.get("entries_root_sha256") == root
         and seal.get("manifest_sha256") == sha(MANIFEST)
         and seal.get("status") == "Q_R1_PRETRAIN_INSTRUMENT_PACKAGE_SEALED",
         "instrument manifest/seal binding failed")
    frozen = {
        str((R1 / "contracts/q-r1-run-contract-v01.json").resolve()): RUN_SHA,
        str((R1 / "contracts/q-r1-analysis-contract-v01.json").resolve()): ANALYSIS_SHA,
        str((R1 / "seals/q-r1-packet-seal-and-authorization-v01.json").resolve()): "80090a8011455395134f5ba8e0ef2a4eef33d4a78ccc795a137b9d7dc0bed7a4",
        str((RUN / "schedule/fixed-schedule.jsonl").resolve()): "f33b943e0fda2a065639d29786b8407b712b042d1acacbd85cd5b174d3ffd71c",
        str((Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01\seals\q-r1-panel-input-terminal-seal-v01.json")).resolve()): PANEL_SEAL_SHA,
    }
    by_path = {row["path"]: row for row in entries}
    for path, expected_hash in frozen.items():
        need(by_path[path]["sha256"] == expected_hash, f"instrument frozen binding mismatch: {path}")
    for row in entries:
        path = Path(row["path"])
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
             f"instrument package input changed: {path}")
    return {"manifest_sha256": sha(MANIFEST), "seal_sha256": sha(SEAL),
            "entries_root_sha256": root, "entry_count": len(entries), "status": seal["status"]}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
