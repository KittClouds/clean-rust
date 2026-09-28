"""Verify V02 salt-0 trace scores against the earlier complete score run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LOGIT_TOLERANCE = 1e-4


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
        if sha256_file(Path(row["trace_file"])) != row["trace_sha256"]:
            raise ValueError(f"source trace hash mismatch: {row['trace_file']}")
        sidecar = read_json(path)
        if sidecar.get("trace_id") != row["trace_id"]:
            raise ValueError(f"trace identity mismatch: {path}")
        if row["trace_id"] in indexed:
            raise ValueError(f"duplicate trace ID: {row['trace_id']}")
        indexed[row["trace_id"]] = (sidecar, row["selector_sha256"])
    if len(indexed) != int(receipt.get("trace_count", -1)):
        raise ValueError("receipt trace count does not match its sidecar index")
    return indexed


def compare_scores(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    if reference["scoring_semantics"] != candidate["scoring_semantics"]:
        raise ValueError("scoring semantics differ")
    max_abs_logit_difference = 0.0
    changed_logit_count = 0
    for field in ("ranking_scores_initial", "ranking_scores_events"):
        left, right = reference[field], candidate[field]
        if len(left) != len(right):
            raise ValueError(f"score vector length differs: {field}")
        for a, b in zip(left, right, strict=True):
            difference = abs(float(a) - float(b))
            max_abs_logit_difference = max(max_abs_logit_difference, difference)
            changed_logit_count += int(difference != 0.0)
    for field in ("probabilities_initial", "probabilities_events"):
        if reference[field] != candidate[field]:
            raise ValueError(f"calibrated probability vector differs: {field}")
    if max_abs_logit_difference > LOGIT_TOLERANCE:
        raise ValueError(f"raw ranking logit drift exceeds {LOGIT_TOLERANCE}: {max_abs_logit_difference}")
    left_scores = reference["ranking_scores_initial"] + reference["ranking_scores_events"]
    right_scores = candidate["ranking_scores_initial"] + candidate["ranking_scores_events"]
    left_best = max(range(len(left_scores)), key=left_scores.__getitem__)
    right_best = max(range(len(right_scores)), key=right_scores.__getitem__)
    return {
        "max_abs_logit_difference": max_abs_logit_difference,
        "changed_logit_count": changed_logit_count,
        "global_argmax_changed": left_best != right_best,
        "reference_argmax_index": left_best,
        "candidate_argmax_index": right_best,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v259", type=Path, required=True)
    parser.add_argument("--v261", type=Path, required=True)
    parser.add_argument("--v262", type=Path, required=True)
    parser.add_argument("--analysis-readback", type=Path, required=True)
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

    v262_comparisons = {}
    for trace_id, (sidecar, _) in v262.items():
        previous = v259[trace_id][0]
        v262_comparisons[trace_id] = compare_scores(previous, sidecar)

    analysis = read_json(args.analysis_readback)
    if analysis.get("schema") != "R1_QTERMINAL_V05_V02_TRACE_SELECTION_ANALYSIS_V01":
        raise ValueError("V260 selector readback has an unexpected schema")
    analysis_by_trace = {str(row["trace_id"]): row for row in analysis.get("traces", [])}
    changed_argmax = [trace_id for trace_id, row in v262_comparisons.items() if row["global_argmax_changed"]]
    if any(trace_id not in analysis_by_trace for trace_id in changed_argmax):
        raise ValueError("V260 readback does not cover every changed global argmax")
    if any(analysis_by_trace[trace_id]["oracle_reachable"] for trace_id in changed_argmax):
        raise ValueError("a changed global argmax occurred on a trace with a reached solution")
    if any(analysis_by_trace[trace_id]["v02_selected_valid"] for trace_id in changed_argmax):
        raise ValueError("V260 selected-valid readback is inconsistent for a changed unreachable trace")

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
    v261_comparisons = {trace_id: compare_scores(v259[trace_id][0], sidecar) for trace_id, sidecar in partial.items()}
    if any(row["global_argmax_changed"] for row in v261_comparisons.values()):
        raise ValueError("V261 partial scores changed a global argmax")
    scorer_path = Path(__file__).with_name("score_traces_v05_v02.py")
    if sha256_file(scorer_path) != v262_receipt.get("scorer_source_sha256"):
        raise ValueError("V262 receipt does not pin the current corrected scorer")

    args.output.mkdir(parents=True)
    result = {
        "schema": "R1_QTERMINAL_V05_V02_SCORE_SMOKE_READBACK_V01",
        "status": "SCORE_SMOKE_READBACK_PASS_WITH_BOUNDED_FP32_DRIFT",
        "v259_receipt_sha256": sha256_file(v259_receipt_path),
        "v261_failure_receipt_sha256": sha256_file(args.v261 / "failed-attempt-receipt.json"),
        "v261_source_snapshot_sha256": v261_failure["source_snapshot_sha256"],
        "v262_receipt_sha256": sha256_file(v262_receipt_path),
        "v262_scorer_source_sha256": v262_receipt["scorer_source_sha256"],
        "v262_trace_count": len(v262),
        "v262_probabilities_bitwise_equal_v259": True,
        "v262_logit_max_abs_difference_v259": max(row["max_abs_logit_difference"] for row in v262_comparisons.values()),
        "v262_logits_within_abs_tolerance": LOGIT_TOLERANCE,
        "v262_global_argmax_changes": len(changed_argmax),
        "changed_argmax_traces_all_unreachable_in_v260": True,
        "v261_partial_sidecars_equal_v259": len(partial),
        "v261_global_argmax_changes": 0,
        "read_existing_v260_outcomes_only": True,
        "read_qualification_labels": False,
    }
    path = args.output / "score-smoke-readback-v01.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{result['status']}: v262={len(v262)} argmax_changes={len(changed_argmax)} v261_partial={len(partial)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
