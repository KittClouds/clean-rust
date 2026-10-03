"""Outcome-blind binding adapter for the sealed Q-R1 analyzer.

The analyzer's metric hash constant names the evaluation metric hash, while its
metric_path names the analysis metric module. Resolve that mismatch from the
already sealed pre-run instrument manifest; do not edit the frozen analyzer.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
R1 = ROOT / "experiments/jev-information-density-v08q-r1"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r1\training-v01")
OUTPUT = RUN / "evaluation-v01"
PACKAGE = RUN / "instrument-v01"
MANIFEST = PACKAGE / "instrument-manifest-v01.json"
PACKAGE_SEAL = PACKAGE / "instrument-seal-v01.json"
ANALYZER = R1 / "source/analyze_q_r1_results_v01.py"
ANALYZER_SHA = "a90a55f075b0da272d1351b10ee93f0f89cd279c402b75a71d7dd636362cf04f"
MANIFEST_SHA = "b578ca06df76e0b3346cf00f9f4b96d0735d1b117907bc6db8d65d6ac12e8f20"
PACKAGE_SEAL_SHA = "2cdcde6326bbf485c75d05ea3f0ad9c24dabc93937a56be93a14ad2fea033a23"
ANALYSIS_METRIC = ROOT / "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py"
EVAL_METRIC = ROOT / "experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py"
GATE = ROOT / "experiments/jev-information-density-v08q/source/q_analysis_rules_v02.py"
EXPECTED_ANALYSIS_METRIC_SHA = "dbde07fe1ec009f2bca7f1f22ad913a2a79f4f8dfb8120a1f31ebf37d5f59b70"
EXPECTED_EVAL_METRIC_SHA = "fa22bc8febff89d2b635091c6cb40be6f3beba4549c4a135d16e213f6fd3dda4"
EXPECTED_GATE_SHA = "4ba7a48438a35f00154e5eefcc76906122080944ff32575a4a26a5b1d29f91b3"
RECEIPT = OUTPUT / "analysis-binding-correction-receipt-v01.json"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    require(sha(ANALYZER) == ANALYZER_SHA, "sealed analyzer source identity changed")
    require(sha(MANIFEST) == MANIFEST_SHA and sha(PACKAGE_SEAL) == PACKAGE_SEAL_SHA,
            "sealed instrument package identity changed")

    verifier = load(R1 / "source/verify_q_r1_instrument_package_v01.py",
                    "q_r1_analysis_binding_instrument_verifier")
    package_receipt = verifier.verify()
    require(package_receipt["manifest_sha256"] == MANIFEST_SHA
            and package_receipt["seal_sha256"] == PACKAGE_SEAL_SHA,
            "instrument package verification receipt differs")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = {row["path"]: row for row in manifest["entries"]}

    def bound(path: Path, expected: str) -> str:
        row = rows.get(str(path.resolve()))
        require(row is not None, f"path not present in sealed instrument manifest: {path}")
        require(row["sha256"] == expected and sha(path) == expected,
                f"sealed implementation mismatch: {path}")
        return row["sha256"]

    analysis_metric_sha = bound(ANALYSIS_METRIC, EXPECTED_ANALYSIS_METRIC_SHA)
    eval_metric_sha = bound(EVAL_METRIC, EXPECTED_EVAL_METRIC_SHA)
    gate_sha = bound(GATE, EXPECTED_GATE_SHA)

    analyzer = load(ANALYZER, "q_r1_frozen_analyzer_with_manifest_bound_metric_sha")
    require(analyzer.METRIC_SHA == eval_metric_sha,
            "analyzer's incorrect constant no longer matches the diagnosed binding defect")
    require(analyzer.GATE_SHA == gate_sha,
            "analyzer gate binding differs from the sealed gate implementation")

    expected_outputs = (
        "neighborhood-metrics-v01.jsonl", "shared-bootstrap-plan-v01.npz",
        "q-r1-results-v01.json", "q-r1-results-v01.md", "q-r1-analysis-seal-v01.json",
    )
    existing = [name for name in expected_outputs if (OUTPUT / name).exists()]
    require(not existing, f"analysis outputs already exist; refusing overwrite: {existing}")
    require(not RECEIPT.exists(), "binding correction receipt already exists")

    failure_path = OUTPUT / "analysis-failure-receipt-v01.json"
    failure_sha = sha(failure_path) if failure_path.is_file() else None
    receipt = {
        "status": "Q_R1_ANALYSIS_HASH_BINDING_CORRECTION_VERIFIED",
        "scope": "runtime binding only; frozen analyzer and analysis contract unchanged",
        "analyzer_path": str(ANALYZER.resolve()),
        "analyzer_sha256": sha(ANALYZER),
        "instrument_manifest_sha256": sha(MANIFEST),
        "instrument_seal_sha256": sha(PACKAGE_SEAL),
        "analysis_metric_path": str(ANALYSIS_METRIC.resolve()),
        "analysis_metric_sha256_from_sealed_manifest": analysis_metric_sha,
        "evaluation_metric_path": str(EVAL_METRIC.resolve()),
        "evaluation_metric_sha256": eval_metric_sha,
        "analyzer_original_metric_constant": analyzer.METRIC_SHA,
        "analyzer_original_metric_path_resolves_to": str(ANALYSIS_METRIC.resolve()),
        "runtime_metric_constant_bound_from_manifest": analysis_metric_sha,
        "seed_gate_path": str(GATE.resolve()),
        "seed_gate_sha256": gate_sha,
        "prior_analyzer_failure_receipt_sha256": failure_sha,
        "analysis_outputs_present_before_run": False,
        "predictions_or_metrics_inspected_for_binding": False,
        "panel_open_count": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    analyzer.METRIC_SHA = analysis_metric_sha
    print(json.dumps({"status": receipt["status"],
                      "analysis_metric_sha256": analysis_metric_sha,
                      "receipt_sha256": sha(RECEIPT)}, indent=2), flush=True)
    return analyzer.main()


if __name__ == "__main__":
    raise SystemExit(main())
