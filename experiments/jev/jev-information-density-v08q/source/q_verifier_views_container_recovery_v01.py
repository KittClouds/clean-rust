"""Repair the verifier's per-neighborhood accumulator container at runtime."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
EVAL = RUN / "evaluation-continuation-v01"
PACKET = RUN / "q-full-execution-packet-v05.json"
PACKET_SEAL = RUN / "q-full-execution-packet-seal-v05.json"
TRAIN_SEAL = RUN / "training/training-seal-manifest.json"
VERIFY_SOURCE = Q / "source/verify_q_full_execution_v05.py"
VERIFY_RECEIPT = RUN / "q-evaluation-recovery-independent-verification-v01.json"
RECOVERY_RECEIPT = RUN / "q-verifier-container-recovery-v01.json"
EXPECTED_PACKET = "bd263ce025146b9c57c8eebabd46336c28d6367078d153ec145b68ca7e9c177c"
EXPECTED_VERIFIER = "ccb63ac920e7ff0fcd19192fff580339e36adbf926ef3b40988428156d598d29"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        stream.flush()


def need(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_verifier() -> Any:
    spec = importlib.util.spec_from_file_location("q_verify_frozen_v05_container_recovery", VERIFY_SOURCE)
    need(spec is not None and spec.loader is not None, "cannot import sealed Q verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.EVAL = EVAL
    module.RECEIPT = VERIFY_RECEIPT
    return module


def corrected_prediction_matrix(module: Any) -> dict[str, Any]:
    tree = module.read_json(EVAL / "raw-prediction-hash-tree-v01.json")
    pred = EVAL / "raw-predictions-v01.jsonl"
    module.need(module.sha(pred) == tree["raw_predictions"]["sha256"]
                and tree["prediction_rows"] == 408_000 and tree["cell_count"] == 51,
                "Q raw prediction root/count mismatch")
    opening = module.read_json(EVAL / "panel-opening-receipt-v01.json")
    module.need(opening.get("opening_count") == 1
                and opening.get("panel_root_sha256") == module.PANEL_ROOT
                and opening.get("training_seal_sha256") == module.sha(module.TRAIN / "training-seal-manifest.json")
                and opening.get("execution_packet_sha256") == module.sha(module.PACKET),
                "Q panel opening receipt mismatch")
    counts: dict[str, int] = {}
    current = None
    per_cell = 0
    # Frozen verifier used a set here but consumes a neighborhood->view mapping.
    views: dict[str, set[str]] = {}
    nids: set[str] = set()
    total = 0
    with pred.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            cell = (int(row["seed"]), str(row["arm"]), int(row["global_step"]))
            if current is None:
                current = cell
            if cell != current:
                module.need(per_cell == 8_000 and len(nids) == 2_000
                            and all(value == {"anchor", "fact_flip", "sham", "matched_neutral"}
                                    for value in views.values()),
                            f"Q prediction cell malformed: {current}")
                counts[f"{current[0]}/{current[1]}/{current[2]}"] = per_cell
                current = cell
                per_cell = 0
                views = {}
                nids = set()
            neighborhood = str(row["neighborhood_id"])
            views.setdefault(neighborhood, set()).add(str(row["view"]))
            nids.add(neighborhood)
            per_cell += 1
            total += 1
        if current is not None:
            module.need(per_cell == 8_000 and len(nids) == 2_000
                        and all(value == {"anchor", "fact_flip", "sham", "matched_neutral"}
                                for value in views.values()),
                        f"Q final prediction cell malformed: {current}")
            counts[f"{current[0]}/{current[1]}/{current[2]}"] = per_cell
    expected = [f"{seed}/{arm}/{step}" for seed, arm, step in module.expected_cells()]
    module.need(list(counts) == expected and total == 408_000,
                "Q prediction cell order or total mismatch")
    module.need(tree.get("execution_packet_sha256") == module.sha(PACKET),
                "Q prediction tree execution packet mismatch")
    return {"prediction_sha256": module.sha(pred), "prediction_rows": total,
            "cell_count": len(counts), "panel_open_count": 1}


def verify() -> None:
    need(sha(PACKET) == EXPECTED_PACKET and sha(VERIFY_SOURCE) == EXPECTED_VERIFIER,
         "sealed Q packet/verifier identity mismatch")
    need(not VERIFY_RECEIPT.exists() and not RECOVERY_RECEIPT.exists(),
         "Q independent verifier already has a terminal receipt")
    failed = read_json(EVAL / "analysis-failure-receipt-v01.json")
    need(failed.get("stage") == "prediction_seal_preflight"
         and failed.get("exception") == "Q frozen metric implementation hash mismatch",
         "unexpected analysis failure provenance")
    module = load_verifier()
    module.verify_prediction_matrix = lambda: corrected_prediction_matrix(module)
    status = int(module.main())
    need(status == 0, f"sealed Q independent verifier failed: status {status}")
    result = read_json(VERIFY_RECEIPT)
    write_json(RECOVERY_RECEIPT, {
        "status": "Q_INDEPENDENT_VERIFICATION_COMPLETED_WITH_CONTAINER_TYPE_FIX",
        "verifier_sha256": EXPECTED_VERIFIER,
        "adapter_sha256": sha(Path(__file__).resolve()),
        "independent_verification_receipt_sha256": sha(VERIFY_RECEIPT),
        "independent_verification_status": result.get("status"),
        "analysis_failure_receipt_preserved": True,
        "corrected_bug": "Initialize neighborhood-to-view accumulator as dict, matching its setdefault use.",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    print(json.dumps(result, indent=2), flush=True)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "verify":
        raise SystemExit("usage: q_verifier_views_container_recovery_v01.py verify")
    verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
