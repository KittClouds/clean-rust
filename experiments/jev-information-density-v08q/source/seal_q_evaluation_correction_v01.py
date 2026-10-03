from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
PACKET = RUN / "q-full-execution-packet-v05.json"
PACKET_SHA = "bd263ce025146b9c57c8eebabd46336c28d6367078d153ec145b68ca7e9c177c"
TERMINAL_PANEL_ROOT = "1b99d39ab6bfed8173a5410f6c8ae0df442aae03038e31bab46b779bd1e039a6"
FEATURE_CACHE_ROOT = "57d9ebaea0bd6fa39d388cd7a3429c08eb349b929bd261eead33d6c9a51ea861"


def sha(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def binding(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    digest, size = sha(path)
    return {"path": relative, "bytes": size, "sha256": digest}


def entries_root(entries: list[dict[str, Any]]) -> str:
    payload = "".join(
        f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
        for row in sorted(entries, key=lambda row: row["path"])
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_new(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    correction_path = RUN / "q-evaluation-correction-packet-v01.json"
    seal_path = RUN / "q-evaluation-correction-seal-v01.json"
    if correction_path.exists() or seal_path.exists():
        raise SystemExit("Q evaluation correction artifacts exist; refusing overwrite")
    if (RUN / "evaluation-v02").exists():
        raise RuntimeError("corrected evaluation output already exists")
    if sha(PACKET)[0] != PACKET_SHA:
        raise RuntimeError("original frozen execution packet changed")

    failed = RUN / "evaluation/evaluation-failure-receipt-v01.json"
    opening = RUN / "evaluation/panel-opening-receipt-v01.json"
    failure = read_json(failed)
    opening_receipt = read_json(opening)
    if failure.get("panel_opened") is not True or failure.get("exception") != "Q feature receipt parent mismatch":
        raise RuntimeError("unexpected prior evaluation attempt; stop for review")
    if any((RUN / "evaluation" / name).exists() for name in ("raw-predictions-v01.jsonl", "raw-prediction-hash-tree-v01.json", "inference-receipt-v01.json")):
        raise RuntimeError("prior attempt emitted evaluation outputs; correction cannot proceed")
    if opening_receipt.get("panel_root_sha256") != TERMINAL_PANEL_ROOT:
        raise RuntimeError("prior opening receipt panel root mismatch")

    feature_receipt = read_json(PANEL / "features/q-feature-extraction-receipt.json")
    feature_seal = read_json(PANEL / "seals/q-feature-cache-seal-v01.json")
    construction_path = PANEL / "seals/q-panel-construction-seal-v01.json"
    construction_sha = sha(construction_path)[0]
    receipt_sha = sha(PANEL / "features/q-feature-extraction-receipt.json")[0]
    if feature_receipt.get("panel_root_sha256") != feature_seal.get("panel_construction_root_sha256"):
        raise RuntimeError("feature receipt does not bind to its construction root")
    if feature_receipt.get("panel_seal_sha256") != feature_seal.get("panel_seal_sha256") or feature_seal.get("panel_seal_sha256") != construction_sha:
        raise RuntimeError("feature receipt/construction seal mismatch")
    if feature_seal.get("root_sha256") != FEATURE_CACHE_ROOT or feature_seal.get("feature_receipt_sha256") != receipt_sha:
        raise RuntimeError("feature-cache sub-seal mismatch")
    terminal = read_json(PANEL / "seals/q-panel-phase-terminal-seal-v01.json")
    if terminal.get("root_sha256") != TERMINAL_PANEL_ROOT:
        raise RuntimeError("terminal panel root mismatch")
    train_seal_path = RUN / "training/training-seal-manifest.json"
    train_seal = read_json(train_seal_path)
    if train_seal.get("status") != "Q_ALL_12_RUNS_COMPLETE_SEALED_UNEVALUATED":
        raise RuntimeError("Q training is not completely sealed")

    relative_paths = (
        "experiments/jev-information-density-v08q/contracts/q-evaluation-metadata-correction-v01.json",
        "experiments/jev-information-density-v08q/source/evaluate_q_panel_v06.py",
        "experiments/jev-information-density-v08q/source/analyze_q_results_v06.py",
        "experiments/jev-information-density-v08q/source/verify_q_full_execution_v06.py",
        "experiments/jev-information-density-v08q/tests/test_q_evaluation_metadata_binding_v01.py",
    )
    implementation = sorted((binding(path) for path in relative_paths), key=lambda row: row["path"])
    root = entries_root(implementation)
    correction = {
        "schema": "jev-v08q-evaluation-metadata-correction-v01",
        "identity": "JEV-V08Q-EVALUATION-METADATA-CORRECTION-V01",
        "status": "FROZEN_METADATA_ONLY_CORRECTION_BEFORE_PREDICTIONS",
        "original_execution_packet_sha256": PACKET_SHA,
        "training_seal_sha256": sha(train_seal_path)[0],
        "failed_preflight_receipt_sha256": sha(failed)[0],
        "prior_panel_opening_receipt_sha256": sha(opening)[0],
        "parent_panel_terminal_root_sha256": TERMINAL_PANEL_ROOT,
        "feature_construction_root_sha256": feature_seal["panel_construction_root_sha256"],
        "feature_cache_root_sha256": FEATURE_CACHE_ROOT,
        "correction_record_sha256": implementation[0]["sha256"],
        "correction_root_sha256": root,
        "implementation_bindings": implementation,
        "access_history": {
            "prior_metadata_preflight_attempts": 1,
            "prior_attempt_read_panel_metadata_and_features": True,
            "prior_attempt_emitted_predictions": False,
            "prior_attempt_emitted_metrics": False,
            "corrected_scored_evaluation_passes": 1,
            "same_panel_identity_and_contents": True,
            "panel_replacement_or_rematching": False,
        },
        "scientific_contract_changed": False,
        "feature_cache_or_training_changed": False,
    }
    write_new(correction_path, correction)
    seal = {
        "schema": "jev-v08q-evaluation-correction-seal-v01",
        "status": "Q_METADATA_CORRECTION_IMPLEMENTATION_SEALED_BEFORE_SCORED_EVALUATION",
        "packet_sha256": sha(correction_path)[0],
        "root_sha256": root,
        "entries": implementation,
        "prior_failed_attempt_receipt_sha256": sha(failed)[0],
    }
    write_new(seal_path, seal)
    print(json.dumps({"status": seal["status"], "packet_sha256": seal["packet_sha256"], "correction_root_sha256": root}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
