from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
INPUT = RUN / "evaluation-v02"
OUTPUT = RUN / "evaluation-v03"
PACKET = RUN / "q-analysis-correction-packet-v01.json"
SEAL = RUN / "q-analysis-correction-seal-v01.json"
RECORD = Q / "contracts/q-analysis-metric-source-correction-v01.json"
METRIC = ROOT / "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py"
EXPECTED_RAW = "d4bc4fce5fd1c51815ac214b794e3b5d5c51f549d80ad7e1362ec5c04abc976e"
EXPECTED_TREE = "9a558752afd107487bf9f3b1dbf7bceebf927c51892a55b1289d447eabbc1d5b"
EXPECTED_FAILURE = "a818e245788050e5dfc9a5da590c31c60e18d505494900eb0543520dd0fd8a58"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_new(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    if PACKET.exists() or SEAL.exists() or OUTPUT.exists():
        raise RuntimeError("analysis correction artifacts/output already exist; refusing overwrite")
    raw = INPUT / "raw-predictions-v01.jsonl"
    tree = INPUT / "raw-prediction-hash-tree-v01.json"
    failure = INPUT / "analysis-failure-receipt-v01.json"
    if sha(raw) != EXPECTED_RAW or sha(tree) != EXPECTED_TREE or sha(failure) != EXPECTED_FAILURE:
        raise RuntimeError("frozen prediction or failed-preflight parent identity mismatch")
    if (INPUT / "neighborhood-metrics-v01.jsonl").exists():
        raise RuntimeError("v06 unexpectedly emitted metrics; correction precondition fails")
    if sha(METRIC) != "dbde07fe1ec009f2bca7f1f22ad913a2a79f4f8dfb8120a1f31ebf37d5f59b70":
        raise RuntimeError("frozen neighborhood-metric implementation identity mismatch")
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    if record.get("failed_preflight_receipt_sha256") != EXPECTED_FAILURE or record.get("repair", {}).get("raw_prediction_sha256") != EXPECTED_RAW:
        raise RuntimeError("correction record parent identity mismatch")

    relative_paths = [
        "experiments/jev-information-density-v08q/contracts/q-analysis-metric-source-correction-v01.json",
        "experiments/jev-information-density-v08q/source/analyze_q_results_v07.py",
        "experiments/jev-information-density-v08q/source/verify_q_full_execution_v07.py",
        "experiments/jev-information-density-v08q/source/seal_q_analysis_correction_v01.py",
        "experiments/jev-information-density-v08q/tests/test_q_analysis_metric_source_correction_v01.py",
    ]
    bindings = []
    for relative in sorted(relative_paths):
        path = ROOT / relative
        bindings.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha(path)})
    root = hashlib.sha256("".join(f"{x['path']}\t{x['bytes']}\t{x['sha256']}\n" for x in bindings).encode()).hexdigest()
    packet = {
        "schema": "jev-v08q-analysis-metric-source-correction-v01",
        "identity": "JEV-V08Q-ANALYSIS-METRIC-SOURCE-CORRECTION-V01",
        "status": "SEALED_CORRECTED_ANALYSIS_READY",
        "parent_execution_packet_sha256": sha(RUN / "q-full-execution-packet-v05.json"),
        "parent_evaluation_correction_packet_sha256": sha(RUN / "q-evaluation-correction-packet-v01.json"),
        "training_seal_sha256": sha(RUN / "training/training-seal-manifest.json"),
        "analysis_contract_sha256": "b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc",
        "execution_addendum_sha256": "363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3",
        "correction_record_sha256": sha(RECORD),
        "failed_analysis_preflight_sha256": sha(failure),
        "prior_v06_analyzer_sha256": sha(Q / "source/analyze_q_results_v06.py"),
        "raw_prediction_sha256": sha(raw),
        "raw_prediction_hash_tree_sha256": sha(tree),
        "metric_implementation_sha256": sha(METRIC),
        "analysis_implementation_sha256": sha(Q / "source/analyze_q_results_v07.py"),
        "verifier_implementation_sha256": sha(Q / "source/verify_q_full_execution_v07.py"),
        "output_directory": "evaluation-v03",
        "metric_logic_changed": False,
        "prediction_matrix_changed": False,
        "training_or_checkpoint_changed": False,
        "implementation_bindings": bindings,
        "correction_root_sha256": root,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_new(PACKET, packet)
    seal = {
        "status": "Q_ANALYSIS_CORRECTION_PACKET_SEALED",
        "packet_sha256": sha(PACKET),
        "root_sha256": root,
        "output_count": len(bindings),
        "outputs": bindings,
        "builder_sha256": sha(Path(__file__).resolve()),
        "raw_prediction_sha256": sha(raw),
        "raw_prediction_hash_tree_sha256": sha(tree),
    }
    write_new(SEAL, seal)
    print(json.dumps({"packet_sha256": sha(PACKET), "correction_root_sha256": root, "seal_sha256": sha(SEAL), "bound_files": len(bindings)}, indent=2))


if __name__ == "__main__":
    main()
