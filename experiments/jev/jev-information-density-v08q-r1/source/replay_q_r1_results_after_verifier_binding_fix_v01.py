"""Compatibility adapter for the sealed Q-R1 independent replay verifier.

The verifier builds a neighborhood -> family lookup, then passes it to a
function that requires complete per-neighborhood panel bindings. This adapter
bridges those two already-sealed data shapes without changing replay logic.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
R1 = ROOT / "experiments/jev-information-density-v08q-r1"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r1\training-v01")
OUTPUT = RUN / "evaluation-v01"
PACKAGE = RUN / "instrument-v01"
MANIFEST = PACKAGE / "instrument-manifest-v01.json"
MANIFEST_SHA = "b578ca06df76e0b3346cf00f9f4b96d0735d1b117907bc6db8d65d6ac12e8f20"
VERIFIER = R1 / "source/verify_q_r1_results_v01.py"
PANEL_ROOT = "f90fc1de0ce1e728e4b6c72cbc58756e2278c5932adb77dcf33f2b9dff2b6f53"
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01")
ADAPTER_PREFLIGHT = OUTPUT / "independent-replay-adapter-preflight-v01.json"
ADAPTER_RECEIPT = OUTPUT / "independent-verification-receipt-v01.json"
VERIFIER_FAILURE = OUTPUT / "independent-verifier-failure-receipt-v01.json"


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
    require(sha(MANIFEST) == MANIFEST_SHA, "pre-run instrument manifest identity changed")
    verifier = load(VERIFIER, "q_r1_frozen_independent_result_verifier")
    package = verifier.verify_instrument_package()
    require(package["manifest_sha256"] == MANIFEST_SHA, "instrument package verification failed")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = next((row for row in manifest["entries"]
                  if row["path"] == str(VERIFIER.resolve())), None)
    require(entry is not None and sha(VERIFIER) == entry["sha256"],
            "independent verifier differs from its sealed instrument identity")

    # This is a downstream verification stage: panel truth and predictions are
    # already authorized for the one opening and are not fed into training.
    panel_truth = verifier.load_panel_truth()
    panel_ids = {str(row["neighborhood_id"])
                 for row in verifier.jsonl(PANEL / "panel/panel-neighborhoods.jsonl")}
    require(len(panel_truth) == 2_000 and len(panel_ids) == 2_000 and set(panel_truth) == panel_ids,
            "panel truth binding cardinality/identity mismatch")
    for neighborhood_id, binding in panel_truth.items():
        require(set(binding) == {"family_id", "episodes", "candidate_ids", "old_candidate_id",
                                 "new_candidate_id", "targets"},
                f"panel binding schema mismatch: {neighborhood_id}")
        require(set(binding["episodes"]) == set(verifier.VIEWS)
                and set(binding["targets"]) == set(verifier.VIEWS),
                f"panel view binding incomplete: {neighborhood_id}")

    original_replay = verifier.replay_cell

    def replay_with_complete_panel(seed: int, arm: str, step: int, prediction_stream: Any,
                                   metric_stream: Any, family_lookup: dict[str, str]):
        require(set(family_lookup) == set(panel_truth), "family lookup and full panel identities differ")
        require(all(family_lookup[nid] == panel_truth[nid]["family_id"] for nid in panel_truth),
                "family lookup disagrees with sealed panel truth")
        return original_replay(seed, arm, step, prediction_stream, metric_stream, panel_truth)

    verifier.replay_cell = replay_with_complete_panel
    require(not ADAPTER_PREFLIGHT.exists() and not ADAPTER_RECEIPT.exists(),
            "independent replay adapter output already exists")
    preflight = {
        "status": "Q_R1_INDEPENDENT_REPLAY_SCHEMA_ADAPTER_PREFLIGHT_PASS",
        "scope": "runtime argument-shape correction only; frozen verifier replay logic unchanged",
        "verifier_path": str(VERIFIER.resolve()),
        "verifier_sha256": sha(VERIFIER),
        "instrument_manifest_sha256": sha(MANIFEST),
        "panel_root_sha256": PANEL_ROOT,
        "panel_neighborhood_count": len(panel_truth),
        "full_binding_fields": ["family_id", "episodes", "candidate_ids", "old_candidate_id",
                                "new_candidate_id", "targets"],
        "family_lookup_verified_against_full_bindings": True,
        "predictions_replayed_before_adapter_preflight": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    ADAPTER_PREFLIGHT.write_text(json.dumps(preflight, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": preflight["status"],
                      "preflight_sha256": sha(ADAPTER_PREFLIGHT)}, indent=2), flush=True)
    try:
        result = verifier.main()
        require(result == 0, f"frozen verifier returned nonzero status {result}")
        receipt = {
            "status": "Q_R1_INDEPENDENT_RESULT_REPLAY_PASS",
            "verifier_sha256": sha(VERIFIER),
            "adapter_sha256": sha(Path(__file__).resolve()),
            "adapter_preflight_sha256": sha(ADAPTER_PREFLIGHT),
            "instrument_manifest_sha256": sha(MANIFEST),
            "panel_root_sha256": PANEL_ROOT,
            "panel_open_count": 1,
            "raw_prediction_sha256": sha(OUTPUT / "raw-predictions-v01.jsonl"),
            "analysis_seal_sha256": sha(OUTPUT / "q-r1-analysis-seal-v01.json"),
            "analysis_failure_receipt_preserved": (OUTPUT / "analysis-failure-receipt-v01.json").is_file(),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        ADAPTER_RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": receipt["status"],
                          "verification_receipt_sha256": sha(ADAPTER_RECEIPT)}, indent=2), flush=True)
        return 0
    except BaseException as exc:
        if not VERIFIER_FAILURE.exists():
            VERIFIER_FAILURE.write_text(json.dumps({
                "status": "Q_R1_INDEPENDENT_VERIFIER_ADAPTER_FAILED_CLOSED",
                "exception_type": type(exc).__name__, "exception": str(exc),
                "verifier_sha256": sha(VERIFIER), "adapter_sha256": sha(Path(__file__).resolve()),
                "panel_root_sha256": PANEL_ROOT, "panel_open_count": 1,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            }, indent=2) + "\n", encoding="utf-8")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
