#!/usr/bin/env python3
"""Independent count/hash/receipt audit. Does not calculate arm comparisons."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUN = ROOT / "experiments" / "fly-drop-00" / "artifacts" / "run-FLY-DROP-00-RUN1"


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb", buffering=0) as f:
        while chunk := f.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value):
    data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as f:
        f.write(data); f.flush()
        import os
        os.fsync(f.fileno())


def main():
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RUN
    contract_path = run / "run-contract.json"
    contract = load(contract_path)
    failures = []
    if sha_file(contract_path) != (run / "run-contract.sha256").read_text().split()[0]:
        failures.append("run contract sidecar mismatch")
    if contract.get("run_id") != "FLY-DROP-00-RUN1" or contract.get("seal_sha256") != "9dc9235c1b5ebf8c8a426f793100f9081cd1242523c27bab00331c2921e85918":
        failures.append("run identity or seal reference mismatch")
    seal_path = ROOT / "experiments" / "fly-drop-00" / "PRETRAINING-SEAL.json"
    if sha_file(seal_path) != contract.get("seal_sha256"):
        failures.append("pretraining seal changed")
    seal_sidecar = (ROOT / "experiments" / "fly-drop-00" / "PRETRAINING-SEAL.sha256").read_text().split()[0]
    if seal_sidecar != contract.get("seal_sha256"):
        failures.append("pretraining seal sidecar mismatch")
    manifest_path = run / "execution-manifest.json"
    if sha_file(manifest_path) != contract.get("execution_manifest_sha256"):
        failures.append("execution manifest hash mismatch")
    manifest = load(manifest_path)
    expected = {f["fit_id"]: f for f in manifest["fits"]}
    fit_rows = manifest["fits"]
    if len(expected) != 656 or len(fit_rows) != 656 or len(manifest["operators"]) != 41 or len(manifest["teacher_worlds"]) != 4:
        failures.append("frozen matrix dimensions mismatch")
    operator_ids = {o["operator_id"] for o in manifest["operators"]}
    teacher_seeds = {int(t["seed"]) for t in manifest["teacher_worlds"]}
    learner_seeds = {int(f["learner_seed"]) for f in fit_rows}
    if operator_ids != {f["operator_id"] for f in fit_rows} or teacher_seeds != {6101, 6102, 6103, 6104} or learner_seeds != {7101, 7102, 7103, 7104}:
        failures.append("Cartesian factor levels differ from the sealed design")
    expected_grid = {(op, teacher, learner) for op in operator_ids for teacher in teacher_seeds for learner in learner_seeds}
    observed_grid = {(f["operator_id"], int(f["teacher_seed"]), int(f["learner_seed"])) for f in fit_rows}
    if observed_grid != expected_grid:
        failures.append("manifest has duplicate or missing Cartesian cells")
    if int(contract.get("total_optimizer_steps", -1)) != 839680:
        failures.append("declared optimizer step count mismatch")

    for section in ("sealed_files", "run_files"):
        for rec in contract[section]:
            p = Path(rec["path"])
            if not p.is_absolute(): p = ROOT / p
            try:
                if sha_file(p) != rec["sha256"]:
                    failures.append(f"{section} hash mismatch: {p}")
            except OSError as e:
                failures.append(f"{section} unavailable: {p}: {e}")

    receipts_dir = run / "collection" / "fit-receipts"
    receipts_by_fit = defaultdict(list)
    interrupted_receipts = []
    for path in receipts_dir.glob("*.json") if receipts_dir.exists() else []:
        try:
            rec = load(path)
            receipts_by_fit[rec["fit_id"]].append((path, rec))
        except Exception as e:
            marker = ".attempt-"
            fit_id, _, tail = path.name.partition(marker)
            try: attempt = int(tail[:4])
            except ValueError: attempt = -1
            interrupted_receipts.append({"path": path.name, "fit_id": fit_id, "attempt": attempt, "parse_error": str(e)})
    observed_ids = set(receipts_by_fit)
    if observed_ids != set(expected):
        failures.append(f"fit receipt universe mismatch: expected {len(expected)}, got {len(observed_ids)}")

    selected = {}
    numerical_fits = []
    for fit_id, fit in expected.items():
        entries = receipts_by_fit.get(fit_id, [])
        if not entries: continue
        entries.sort(key=lambda row: int(row[1].get("attempt", 0)))
        path, rec = entries[-1]
        selected[fit_id] = rec
        for damaged in [x for x in interrupted_receipts if x["fit_id"] == fit_id]:
            if damaged["attempt"] < int(rec.get("attempt", 0)):
                continue
            failures.append(f"unreadable receipt has no later successful rerun: {damaged['path']}")
        for candidate_path, candidate in entries:
            if candidate.get("run_id") != contract["run_id"] or candidate.get("fit_id") != fit_id:
                failures.append(f"receipt identity mismatch: {candidate_path.name}")
            if candidate.get("optimizer_updates") != 1280 or candidate.get("epochs_completed") != 20:
                failures.append(f"fit update count mismatch: {candidate_path.name}")
            if len(candidate.get("epoch_train_loss", [])) != 20:
                failures.append(f"epoch trajectory length mismatch: {candidate_path.name}")
        if rec.get("status") not in ("complete", "numerical_failure"):
            failures.append(f"latest attempt lacks terminal receipt: {path.name}")
        if rec.get("operator_id") != fit["operator_id"] or rec.get("operator_sha256") != fit["operator_sha256"]:
            failures.append(f"operator receipt mismatch: {path.name}")
        if rec.get("initial_parameters_sha256") != fit["initial_parameters"]["sha256"] or rec.get("minibatch_order_sha256") != fit["minibatch_order"]["sha256"]:
            failures.append(f"paired plan hash mismatch: {path.name}")
        if rec.get("paired_initialization_fingerprint") != fit["paired_initialization_fingerprint"] or rec.get("paired_order_fingerprint") != fit["paired_order_fingerprint"]:
            failures.append(f"paired fingerprint mismatch: {path.name}")
        if rec.get("input_hashes") != fit["input_hashes"]:
            failures.append(f"input hash mapping mismatch: {path.name}")
        if rec.get("terminal_eval_update_count") != 1280 or rec.get("terminal_eval_passes") != 1:
            failures.append(f"terminal evaluation boundary mismatch: {path.name}")
        if rec.get("status") == "numerical_failure": numerical_fits.append(fit_id)
        if rec.get("status") == "complete" and (rec.get("heldout_bce") is None or rec.get("heldout_accuracy") is None):
            failures.append(f"finite fit lacks terminal outcome fields: {path.name}")
        start = run / "collection" / "attempts" / f"{fit_id}.attempt-{int(rec.get('attempt', 0)):04}.start.json"
        end = run / "collection" / "attempts" / f"{fit_id}.attempt-{int(rec.get('attempt', 0)):04}.end.json"
        try:
            start_record, end_record = load(start), load(end)
            if end_record.get("receipt_sha256") != sha_file(path): failures.append(f"attempt-end receipt hash mismatch: {path.name}")
            if start_record.get("fit_id") != fit_id or end_record.get("fit_id") != fit_id: failures.append(f"attempt boundary identity mismatch: {fit_id}")
        except Exception as e:
            failures.append(f"attempt boundaries missing for {fit_id}: {e}")

    if len(selected) == 656:
        pair_fingerprints = defaultdict(set)
        observed_cells = set()
        for fit_id, fit in expected.items():
            receipt = selected.get(fit_id)
            if receipt is None: continue
            cell = (fit["operator_id"], fit["teacher_seed"], fit["learner_seed"])
            observed_cells.add(cell)
            pair_fingerprints[(fit["teacher_seed"], fit["learner_seed"])].add((receipt.get("paired_initialization_fingerprint"), receipt.get("paired_order_fingerprint")))
        if len(observed_cells) != 656: failures.append("duplicate or missing Cartesian fit cells")
        if len(pair_fingerprints) != 16 or any(len(v) != 1 for v in pair_fingerprints.values()):
            failures.append("paired initialization/order differs within a teacher×learner cell")

    access_dir = run / "collection" / "evaluation-access"
    access_events = []
    if not access_dir.exists():
        failures.append("terminal evaluation access log missing")
    else:
        for event_path in access_dir.glob("*.json"):
            try: access_events.append(load(event_path))
            except Exception as e:
                marker = ".attempt-"
                fit_id, _, tail = event_path.stem.partition(marker)
                try: attempt = int(tail[:4])
                except ValueError: attempt = -1
                current = selected.get(fit_id)
                if current is None or attempt >= int(current.get("attempt", 0)):
                    failures.append(f"unreadable terminal evaluation event without later successful rerun: {event_path.name}: {e}")
                else:
                    interrupted_receipts.append({"path": event_path.name, "fit_id": fit_id, "attempt": attempt, "parse_error": str(e), "kind": "evaluation_event"})
    event_by_attempt = defaultdict(list)
    for event in access_events:
        event_by_attempt[(event.get("fit_id"), event.get("attempt"))].append(event)
        if event.get("access") != "terminal_heldout_evaluation" or event.get("optimizer_updates") != 1280 or event.get("planned_passes") != 1:
            failures.append("nonterminal or repeated evaluation access declaration")
        if event.get("fit_id") not in expected:
            failures.append("evaluation event references an unknown fit")
    for fit_id, rec in selected.items():
        events = event_by_attempt.get((fit_id, rec.get("attempt")), [])
        if len(events) != 1: failures.append(f"terminal evaluation event count is not one for {fit_id}")

    collection = run / "collection"
    for name in ("final-outcomes.csv", "epoch-metrics.csv"):
        if not (collection / name).is_file(): failures.append(f"collection output missing: {name}")
    collection_receipt_path = run / "collection-receipt.json"
    try:
        collection_receipt = load(collection_receipt_path)
        if collection_receipt.get("status") != "COLLECTION_COMPLETE" or collection_receipt.get("completed_fit_receipts") != 656 or collection_receipt.get("total_optimizer_steps") != 839680:
            failures.append("collection receipt does not certify the declared completed matrix")
    except Exception as e:
        failures.append(f"collection receipt missing or malformed: {e}")
    numerical_summary = {"fit_count": len(numerical_fits), "fit_ids": numerical_fits,
                         "infrastructure_failures": len(failures), "scientific_numerical_status": "observed" if numerical_fits else "none"}
    status = "PASS" if not failures and len(selected) == 656 else "FAIL"
    receipt = {"schema": "FLY-DROP-00-integrity-receipt-v1", "run_id": contract["run_id"],
        "status": status, "seal_sha256": contract["seal_sha256"],
        "verified_fit_receipts": len(selected), "expected_fit_receipts": 656,
        "optimizer_updates_per_fit": 1280, "verified_total_optimizer_steps": len(selected) * 1280,
        "verified_terminal_evaluation_events": len(access_events),
        "preserved_interrupted_attempt_artifacts": interrupted_receipts,
        "paired_teacher_learner_cells_verified": 16 if len(selected) == 656 else 0,
        "numerical_status": numerical_summary,
        "evaluation_access_audit_basis": "hash-locked runner code and executable plus per-attempt terminal-only access events at update 1280",
        "frozen_source_hashes_unchanged": not any(f.startswith("sealed_files ") for f in failures),
        "run_code_hashes_unchanged": not any(f.startswith("run_files ") for f in failures),
        "failures": failures}
    if status == "PASS":
        gate_path = run / "integrity-receipt.json"
        if gate_path.exists():
            existing = load(gate_path)
            if existing != receipt: raise RuntimeError("an existing integrity PASS differs; refusing to replace it")
        else:
            write_new(gate_path, receipt)
        digest = sha_file(gate_path)
        sidecar = run / "integrity-receipt.sha256"
        if not sidecar.exists():
            with sidecar.open("x", encoding="ascii") as f:
                f.write(f"{digest}  integrity-receipt.json\n")
    else:
        attempts = run / "integrity-attempts"
        attempts.mkdir(exist_ok=True)
        previous = list(attempts.glob("audit-*.json"))
        index = 1 + max((int(p.stem.split("-")[-1]) for p in previous), default=0)
        attempt_path = attempts / f"audit-{index:04}.json"
        write_new(attempt_path, receipt)
    print(f"Integrity {status}: {len(selected)}/656 fit receipts; {len(failures)} infrastructure failures; {len(numerical_fits)} numerical-failure fits")
    if failures:
        for item in failures[:20]: print(f"integrity issue: {item}")
    if status != "PASS": raise SystemExit(2)


if __name__ == "__main__":
    main()
