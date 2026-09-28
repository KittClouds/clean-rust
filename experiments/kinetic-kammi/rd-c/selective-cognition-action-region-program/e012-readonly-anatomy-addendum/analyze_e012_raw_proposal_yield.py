#!/usr/bin/env python3
"""Read-only recount of E012 raw small proposals; writes only its output file."""
from __future__ import annotations
import hashlib, json
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program")
RUN = ROOT / "experiment-012" / "artifacts" / "runs" / "e012-20260926-frame-decomposition-01"
OUT = ROOT / "e012-readonly-anatomy-addendum" / "E012-RAW-PROPOSAL-YIELD-v1.0.json"

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def bucket():
    return {"tasks": 0, "null": 0, "correct": 0, "wrong": 0,
            "accepted": 0, "accepted_correct": 0, "accepted_wrong": 0}

def main() -> None:
    labels_path = RUN / "vault" / "evaluation-labels.json"
    lock_path = RUN / "frozen-input-lock.json"
    report_path = RUN / "reports" / "full-frame-baseline-report.json"
    labels = json.loads(labels_path.read_text(encoding="utf-8"))["tasks"]
    by_sample = {row["sample_id"]: row for row in labels}
    files = sorted((RUN / "vault" / "authorization-inputs").glob("small_only--*.json"))
    if len(files) != 48 or len(by_sample) != 48:
        raise SystemExit(f"expected 48 E012 tasks; got inputs={len(files)} labels={len(by_sample)}")
    counts = {"all": bucket(), "empty_valid_set": bucket(), "nonempty_valid_set": bucket()}
    ordinal = defaultdict(lambda: {"accepted": 0, "correct": 0, "wrong": 0})
    file_hashes = []
    for path in files:
        sample_id = path.stem[len("small_only--"):]
        row = by_sample.get(sample_id)
        if row is None:
            raise SystemExit(f"missing sealed label for {sample_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        out = data["observer_output"]
        choice = out.get("action_choice")
        accepted = (choice is not None and
                    out["applicability_milli"] >= data["thresholds"]["minimum_applicability_milli"] and
                    out["abstention_milli"] <= data["thresholds"]["maximum_abstention_milli"])
        key = "empty_valid_set" if not row["expected_valid_action_ids"] else "nonempty_valid_set"
        for name in ("all", key):
            dest = counts[name]
            dest["tasks"] += 1
            if choice is None:
                dest["null"] += 1
                continue
            correct = choice in row["expected_valid_action_ids"]
            dest["correct" if correct else "wrong"] += 1
            if accepted:
                dest["accepted"] += 1
                dest["accepted_correct" if correct else "accepted_wrong"] += 1
        if choice is not None and accepted:
            ordinal_row = next((o for o in data["ordered_options"] if o["action"]["id"] == choice), None)
            if ordinal_row is None:
                raise SystemExit(f"proposal not in bound presentation for {sample_id}")
            pos = ordinal[str(ordinal_row["producer_ordinal"])]
            pos["accepted"] += 1
            pos["correct" if choice in row["expected_valid_action_ids"] else "wrong"] += 1
        file_hashes.append({"name": path.name, "sha256": sha256(path)})
    proposal_total = counts["all"]["correct"] + counts["all"]["wrong"]
    result = {
        "schema_version": 1,
        "artifact_id": "E012-RAW-PROPOSAL-YIELD-v1.0",
        "state": "READ_ONLY_DESCRIPTIVE_RECOUNT",
        "source_run_id": "e012-20260926-frame-decomposition-01",
        "model_contact": False,
        "fitting_or_threshold_search": False,
        "source_run_modified": False,
        "source_sha256": {
            "frozen_input_lock": sha256(lock_path),
            "baseline_report": sha256(report_path),
            "evaluation_labels": sha256(labels_path),
        },
        "small_authorization_input_files": file_hashes,
        "counts": counts,
        "raw_proposal_precision": {
            "numerator": counts["all"]["correct"],
            "denominator": proposal_total,
            "rate": counts["all"]["correct"] / proposal_total if proposal_total else None,
        },
        "accepted_action_producer_ordinal": dict(sorted(ordinal.items(), key=lambda item: int(item[0]))),
        "interpretation": [
            "A null raw action choice is a no-proposal outcome, not a wrong proposal.",
            "Every non-null proposal on an empty valid set is wrong by construction.",
            "These are retrospective descriptive counts; no threshold, subgroup, or signal was fitted.",
        ],
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "counts": counts,
                      "raw_proposal_precision": result["raw_proposal_precision"],
                      "accepted_action_producer_ordinal": result["accepted_action_producer_ordinal"]}, indent=2))

if __name__ == "__main__":
    main()
