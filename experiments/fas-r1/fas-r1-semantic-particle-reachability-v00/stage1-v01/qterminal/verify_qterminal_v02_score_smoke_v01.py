"""Verify V02 salt-0 trace scores against the earlier complete score run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCORE_FIELDS = (
    "scoring_semantics",
    "ranking_scores_initial",
    "probabilities_initial",
    "ranking_scores_events",
    "probabilities_events",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def index_sidecars(root: Path, receipt: dict[str, Any]) -> dict[str, tuple[dict[str, Any], str]]:
    indexed = {}
    for row in receipt.get("sidecars", []):
        path = root / row["selector_file"]
        if sha256_file(path) != row["selector_sha256"]:
            raise ValueError(f"selector sidecar hash mismatch: {path}")
        sidecar = read_json(path)
        if sidecar.get("trace_id") != row["trace_id"]:
            raise ValueError(f"trace identity mismatch: {path}")
        if row["trace_id"] in indexed:
            raise ValueError(f"duplicate trace ID: {row['trace_id']}")
        indexed[row["trace_id"]] = (sidecar, row["selector_sha256"])
    if len(indexed) != int(receipt.get("trace_count", -1)):
        raise ValueError("receipt trace count does not match its sidecar index")
    return indexed


def score_projection(sidecar: dict[str, Any]) -> dict[str, Any]:
    return {field: sidecar[field] for field in SCORE_FIELDS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v259", type=Path, required=True)
    parser.add_argument("--v261", type=Path, required=True)
    parser.add_argument("--v262", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("output directory must be new")

    v259_receipt_path = args.v259 / "trace-scoring-receipt-v05-v02.json"
    v262_receipt_path = args.v262 / "trace-scoring-receipt-v05-v02.json"
    v259_receipt = read_json(v259_receipt_path)
    v262_receipt = read_json(v262_receipt_path)
    if v259_receipt.get("status") != "TRACE_SELECTOR_SCORES_COMPLETE":
        raise ValueError("V259 is not a completed scoring run")
    if v262_receipt.get("status") != "TRACE_SELECTOR_SCORES_COMPLETE":
        raise ValueError("V262 is not a completed scoring run")
    if v262_receipt.get("trace_count") != 240:
        raise ValueError("V262 salt-0 smoke did not score exactly 240 traces")
    v259 = index_sidecars(args.v259, v259_receipt)
    v262 = index_sidecars(args.v262, v262_receipt)
    if not set(v262).issubset(v259):
        raise ValueError("V262 contains traces absent from V259")

    for trace_id, (sidecar, _) in v262.items():
        previous = v259[trace_id][0]
        if score_projection(sidecar) != score_projection(previous):
            raise ValueError(f"V262 scores differ from V259 for trace {trace_id}")

    v261_failure = read_json(args.v261 / "failed-attempt-receipt.json")
    if v261_failure.get("status") != "FAILED_PARTIAL_SIDECAR_WRITE":
        raise ValueError("V261 failure receipt has the wrong status")
    if sha256_file(Path(v261_failure["source_snapshot_path"])) != v261_failure["source_snapshot_sha256"]:
        raise ValueError("V261 scorer source snapshot hash mismatch")
    partial = {}
    for path in args.v261.glob("*.selector.json"):
        sidecar = read_json(path)
        trace_id = str(sidecar["trace_id"])
        if trace_id in partial:
            raise ValueError(f"duplicate V261 partial trace ID: {trace_id}")
        partial[trace_id] = sidecar
    if len(partial) != int(v261_failure.get("partial_sidecar_count", -1)):
        raise ValueError("V261 partial sidecar count differs from its failure receipt")
    if not set(partial).issubset(v259):
        raise ValueError("V261 partial output contains an unknown trace")
    for trace_id, sidecar in partial.items():
        if score_projection(sidecar) != score_projection(v259[trace_id][0]):
            raise ValueError(f"V261 partial score differs from V259 for trace {trace_id}")

    args.output.mkdir(parents=True)
    result = {
        "schema": "R1_QTERMINAL_V05_V02_SCORE_SMOKE_READBACK_V01",
        "status": "SCORE_SMOKE_READBACK_PASS",
        "v259_receipt_sha256": sha256_file(v259_receipt_path),
        "v261_failure_receipt_sha256": sha256_file(args.v261 / "failed-attempt-receipt.json"),
        "v261_source_snapshot_sha256": v261_failure["source_snapshot_sha256"],
        "v262_receipt_sha256": sha256_file(v262_receipt_path),
        "v262_scorer_source_sha256": v262_receipt["scorer_source_sha256"],
        "v262_trace_count": len(v262),
        "v262_scores_equal_v259": True,
        "v261_partial_sidecars_equal_v259": len(partial),
        "read_qualification_labels": False,
    }
    path = args.output / "score-smoke-readback-v01.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{result['status']}: v262={len(v262)} v261_partial={len(partial)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
