"""Verify the explicit source/runtime inventory for the authorized Q-R2 run."""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
SEAL = RUN / "provenance/q-r2-instrument-package-seal-v01.json"

REPO_FILES = (
    "experiments/jev-information-density-v08q-r2-late-branch/contracts/q-r2-analysis-contract-v01.json",
    "experiments/jev-information-density-v08q-r2-late-branch/contracts/q-r2-panel-contract-v01.json",
    "experiments/jev-information-density-v08q-r2-late-branch/contracts/q-r2-run-contract-v01.json",
    "experiments/jev-information-density-v08q-r2-late-branch/seals/q-r2-phase-packet-seal-v01.json",
    "experiments/jev-information-density-v08q-r2-late-branch/generator/Cargo.toml",
    "experiments/jev-information-density-v08q-r2-late-branch/generator/Cargo.lock",
    "experiments/jev-information-density-v08q-r2-late-branch/generator/src/main.rs",
    "experiments/jev-information-density-v08n/generator/src/main.rs",
    "experiments/jev-information-density-v08n/generator/src/generator.rs",
    "experiments/jev-information-density-v08n/generator/src/families.rs",
    "experiments/jev-decision-world-v01/Cargo.toml",
    "experiments/jev-decision-world-v01/Cargo.lock",
    "experiments/jev-decision-world-v01/src/exact.rs",
    "experiments/jev-decision-world-v01/src/lib.rs",
    "experiments/jev-decision-world-v01/src/generate.rs",
    "experiments/jev-decision-world-v01/src/families.rs",
    "experiments/jev-decision-world-v01/src/types.rs",
    "experiments/jev-decision-world-v01/src/validate.rs",
    "experiments/jev-frozen-readout-v01/probe.py",
    "experiments/jev-frozen-scaling-v05/train_v05.py",
    "experiments/jev-information-density-v08q/source/q_weighted_objective_v02.py",
    "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py",
    "experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py",
    "experiments/jev-information-density-v08p-r2/runner/r2_panel_target_join.py",
    "experiments/jev-lfm-variable-v07/extract_lfm.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/analyze_q_r2_results_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/evaluate_q_r2_panel_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/extract_q_r2_panel_features_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/join_q_r2_exact_world_targets_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/match_q_r2_panel_radius_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/materialize_q_r2_schedule_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/run_q_r2_training_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/seal_q_r2_feature_cache_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/seal_q_r2_panel_construction_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/seal_q_r2_panel_inputs_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/verify_q_r2_exact_world_targets_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/verify_q_r2_panel_construction_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/verify_q_r2_instrument_package_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/seal_q_r2_instrument_package_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/verify_q_r2_results_v01.py",
    "experiments/jev-information-density-v08q-r2-late-branch/source/seal_q_r2_completion_v01.py",
)
BUILD_FILES = (
    Path(r"D:\cargo-targets\jev-q-r2-late-branch-v01\release\jev-information-density-v08q-r2-panel-generator.exe"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def entry_root(entries: list[dict[str, Any]]) -> str:
    payload = "".join(
        f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
        for row in sorted(entries, key=lambda row: row["path"])
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify() -> dict[str, Any]:
    if not SEAL.is_file():
        raise RuntimeError("Q-R2 instrument package seal is missing")
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    if seal.get("status") != "Q_R2_INSTRUMENT_PACKAGE_SEALED":
        raise RuntimeError("Q-R2 instrument package is not sealed")
    expected: dict[str, Path] = {path: ROOT / path for path in REPO_FILES}
    expected.update({path.as_posix(): path for path in BUILD_FILES})
    rows = seal.get("entries", [])
    if len(rows) != len(expected) or {row.get("path") for row in rows} != set(expected):
        raise RuntimeError("Q-R2 instrument package file set mismatch")
    for row in rows:
        path = expected[row["path"]]
        if not path.is_file() or path.stat().st_size != row.get("bytes") or sha256(path) != row.get("sha256"):
            raise RuntimeError(f"Q-R2 instrument source changed: {row['path']}")
    root = entry_root(rows)
    if root != seal.get("entries_root_sha256"):
        raise RuntimeError("Q-R2 instrument package root mismatch")
    return {"seal_sha256": sha256(SEAL), "entries_root_sha256": root,
            "entry_count": len(rows), "status": seal["status"]}


def main() -> int:
    result = verify()
    result["python"] = platform.python_version()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
