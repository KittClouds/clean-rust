#!/usr/bin/env python3
"""Join closed V05 V02 Q scores to post-hoc validity labels for engineering readback."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def trace_parts(path: Path):
    header = footer = None
    events = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            kind, payload = row.get("record"), row.get("payload")
            if kind == "header":
                if header is not None:
                    raise ValueError(f"duplicate header in {path}")
                header = payload
            elif kind == "event":
                if int(payload.get("event_index", -1)) != len(events):
                    raise ValueError(f"noncontiguous event in {path}:{line_number}")
                events.append(payload)
            elif kind == "footer":
                if footer is not None:
                    raise ValueError(f"duplicate footer in {path}")
                footer = payload
            else:
                raise ValueError(f"unknown trace record in {path}:{line_number}")
    if header is None or footer is None or int(footer["ledger"]["expansions"]) != len(events):
        raise ValueError(f"trace is incomplete: {path}")
    return header, events, footer


def selected_valid(scores_initial, scores_events, initial_valid: bool, event_valid: list[bool]) -> bool:
    if len(scores_events) != len(event_valid):
        raise ValueError("selector score count differs from post-hoc event labels")
    best = float("-inf")
    best_valid = False
    for score in scores_initial:
        value = float(score)
        if value > best:
            best, best_valid = value, bool(initial_valid)
    for index, score in enumerate(scores_events):
        value = float(score)
        if value > best:
            best, best_valid = value, bool(event_valid[index])
    return best_valid


def summarize(args) -> dict[str, Any]:
    scoring_receipt = read_json(args.scoring_receipt)
    if scoring_receipt.get("schema") != "R1_QTERMINAL_V05_V02_TRACE_SCORING_RECEIPT_V01" or scoring_receipt.get("status") != "TRACE_SELECTOR_SCORES_COMPLETE":
        raise ValueError("trace-scoring receipt is not complete")
    sidecars = {str(row["trace_file"]): row for row in scoring_receipt.get("sidecars", [])}
    if len(sidecars) != int(scoring_receipt.get("trace_count", -1)):
        raise ValueError("scoring receipt has missing or duplicate trace pins")
    per_arm = defaultdict(lambda: {"traces": 0, "reach_count": 0, "v02_selected_count": 0, "legacy_selected_count": 0})
    per_run_arm = defaultdict(lambda: {"traces": 0, "reach_count": 0, "v02_selected_count": 0})
    row_details = []
    for trace_path_text, sidecar_receipt in sorted(sidecars.items()):
        trace_path = Path(trace_path_text)
        if sha256_file(trace_path) != sidecar_receipt["trace_sha256"]:
            raise ValueError(f"trace changed after Q scoring: {trace_path}")
        selector_path = args.scoring_receipt.parent / sidecar_receipt["selector_file"]
        if sha256_file(selector_path) != sidecar_receipt["selector_sha256"]:
            raise ValueError(f"selector sidecar hash mismatch: {selector_path}")
        trace_id = str(sidecar_receipt["trace_id"])
        header, events, footer = trace_parts(trace_path)
        if str(header["trace_id"]) != trace_id or str(header["task_id"]) != str(sidecar_receipt["task_id"]):
            raise ValueError(f"trace identity mismatch for {trace_path}")
        sidecar = read_json(selector_path)
        if sidecar.get("schema") != "R1_QTERMINAL_V05_V02_TRACE_SCORES_V01" or sidecar.get("trace_id") != trace_id:
            raise ValueError(f"selector sidecar identity mismatch for {trace_path}")
        posthoc_path = trace_path.with_name(trace_path.name.replace(".trace.jsonl", ".posthoc.json"))
        posthoc = read_json(posthoc_path)
        if posthoc.get("trace_id") != trace_id or posthoc.get("task_id") != header["task_id"]:
            raise ValueError(f"post-hoc sidecar identity mismatch for {trace_path}")
        event_labels = posthoc.get("events", [])
        if len(events) != len(event_labels) or len(events) != int(sidecar_receipt["event_count"]):
            raise ValueError(f"trace, post-hoc, and Q-score event counts differ for {trace_path}")
        event_valid = [bool(row["valid"]) for row in event_labels]
        reach = bool(posthoc["initial_valid"]) or any(event_valid)
        v02_selected = selected_valid(
            sidecar["ranking_scores_initial"],
            sidecar["ranking_scores_events"],
            bool(posthoc["initial_valid"]),
            event_valid,
        )
        selected_event = footer.get("selected_event")
        selected_initial = footer.get("selected_initial_particle")
        if selected_event is not None:
            legacy_selected = bool(event_valid[int(selected_event)])
        elif selected_initial is not None:
            legacy_selected = bool(posthoc["initial_valid"])
        else:
            legacy_selected = False
        stem = trace_path.name.removesuffix(".trace.jsonl")
        arm = stem.rsplit("-", 1)[-1]
        run_tag = trace_path.parent.name
        for table, key in ((per_arm, arm), (per_run_arm, f"{run_tag}/{arm}")):
            cell = table[key]
            cell["traces"] += 1
            cell["reach_count"] += int(reach)
            cell["v02_selected_count"] += int(v02_selected)
        per_arm[arm]["legacy_selected_count"] += int(legacy_selected)
        row_details.append({
            "trace_id": trace_id,
            "run": run_tag,
            "task_id": str(header["task_id"]),
            "arm": arm,
            "expansions": len(events),
            "oracle_reachable": reach,
            "v02_selected_valid": v02_selected,
            "legacy_selected_valid": legacy_selected,
            "v02_selection_loss": reach and not v02_selected,
        })

    def rates(table):
        output = {}
        for key, row in sorted(table.items()):
            count = int(row["traces"])
            reach = int(row["reach_count"])
            selected = int(row["v02_selected_count"])
            output[key] = {
                **row,
                "reach_rate": reach / count if count else 0.0,
                "v02_selected_success_rate": selected / count if count else 0.0,
                "selection_loss_count": reach - selected,
                "selection_loss_rate_of_reachable": (reach - selected) / reach if reach else 0.0,
                **({"legacy_selected_success_rate": row["legacy_selected_count"] / count if count else 0.0} if "legacy_selected_count" in row else {}),
            }
        return output

    result = {
        "schema": "R1_QTERMINAL_V05_V02_TRACE_SELECTION_ANALYSIS_V01",
        "status": "ENGINEERING_SELECTOR_READBACK_COMPLETE",
        "scoring_receipt_sha256": sha256_file(args.scoring_receipt),
        "scorer_source_sha256": sha256_file(Path(__file__).with_name("score_traces_v05_v02.py")),
        "analysis_source_sha256": sha256_file(Path(__file__)),
        "trace_count": len(row_details),
        "per_arm": rates(per_arm),
        "per_run_arm": rates(per_run_arm),
        "scoring_costs": {
            "unique_assignments": scoring_receipt["unique_assignments_scored"],
            "forward_batches": scoring_receipt["scoring_forward_batches"],
            "gpu_active_ns": scoring_receipt["scoring_gpu_active_ns"],
            "wall_active_ns": scoring_receipt["scoring_wall_active_ns"],
            "peak_gpu_memory_bytes": scoring_receipt["peak_gpu_memory_bytes"],
        },
        "readout_boundary": "post-hoc labels were joined only after V02 scores were written; this is engineering analysis, not independent confirmation",
        "traces": row_details,
    }
    if args.output.exists():
        raise ValueError(f"refusing to overwrite {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scoring-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args)
    print(f"{result['status']}: traces={result['trace_count']}")
    for arm, row in result["per_arm"].items():
        print(f"{arm}: R={row['reach_count']}/{row['traces']} S_V02={row['v02_selected_count']}/{row['traces']} S_legacy={row['legacy_selected_count']}/{row['traces']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
