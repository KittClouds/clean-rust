"""Create the terminal Q-R2 result root after independent replay passes."""

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
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
EXP = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
TRAIN = RUN / "training-v01"
PANEL = RUN / "panel-v01"
EVAL = RUN / "evaluation-v01"
OUTPUT = RUN / "provenance/q-r2-completion-seal-v01.json"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load completion verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to replace Q-R2 completion seal: {OUTPUT}")
    verifier = load_module(EXP / "source/verify_q_r2_results_v01.py", "jev_q_r2_completion_verifier")
    replay = verifier.verify()
    need = lambda ok, message: (_ for _ in ()).throw(RuntimeError(message)) if not ok else None
    paths = [
        EXP / "seals/q-r2-phase-packet-seal-v01.json",
        EXP / "contracts/q-r2-run-contract-v01.json",
        EXP / "contracts/q-r2-analysis-contract-v01.json",
        EXP / "contracts/q-r2-panel-contract-v01.json",
        RUN / "provenance/q-r2-instrument-package-seal-v01.json",
        PANEL / "seals/q-r2-panel-construction-seal-v01.json",
        PANEL / "seals/q-r2-feature-cache-seal-v01.json",
        PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json",
        TRAIN / "schedule/schedule-seal.json",
        TRAIN / "common-prefix-seal-v01.json",
        TRAIN / "checkpoint-hash-tree.json",
        TRAIN / "training-seal-manifest.json",
        EVAL / "panel-opening-receipt-v01.json",
        EVAL / "raw-prediction-hash-tree-v01.json",
        EVAL / "inference-receipt-v01.json",
        EVAL / "q-r2-analysis-seal-v01.json",
        EVAL / "independent-replay-verification-v01.json",
    ]
    paths.extend(EVAL / name for name in (
        "raw-predictions-v01.jsonl", "neighborhood-metrics-v01.jsonl", "shared-neighborhood-bootstrap-plan-v01.npy",
        "shared-moderator-seed-resample-plan-v01.npy", "q-r2-analysis-v01.json", "q-r2-results-v01.md"))
    for path in paths:
        need(path.is_file(), f"required terminal Q-R2 artifact missing: {path}")
    entries = [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)} for path in paths]
    need(len({row["path"] for row in entries}) == len(entries), "duplicate artifact in terminal seal")
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(entries, key=lambda row: row["path"]))
    root = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    receipt = {"status": "Q_R2_COMPLETE_RESULT_SEALED", "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
        "disposition": "POST_REGISTERED_PAIRED_LATE_INTERVENTION_RESULT",
        "authorization_packet_sha256": "3f6367cb5bf03400923913fffb9acc5cc21ffa32ffdaee807615725ff7f2c209",
        "contract_bundle_root_sha256": "6b3b826fd3c861e1aa9114371f9db68c704fb9c5ad85e5c8c60a93afba527275",
        "independent_replay_status": replay["status"], "independent_replay_receipt_sha256": sha(EVAL / "independent-replay-verification-v01.json"),
        "artifact_root_sha256": root, "artifact_count": len(entries), "artifacts": entries,
        "panel_open_count": 1, "training_runs": 24, "late_continuations": 48,
        "evaluation_cells": 120, "raw_prediction_rows": 960_000,
        "step120_primary": True, "step100_descriptive": True,
        "seed_population_inference": False, "controller_fitting": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat()}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, OUTPUT)
    print(json.dumps({"status": receipt["status"], "artifact_root_sha256": root,
                      "completion_seal_sha256": sha(OUTPUT), "artifact_count": len(entries)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
