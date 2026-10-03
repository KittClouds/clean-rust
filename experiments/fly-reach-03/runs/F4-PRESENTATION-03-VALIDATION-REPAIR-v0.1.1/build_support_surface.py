"""Target-only support accounting for the sealed native collection.

This stage opens only inclusion probability and target polarity after the raw
collection tree has passed the independent key/hash audit. It does not read
reference values, native deltas, predictor features, logits, or model outputs.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import struct
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[4]
STUDY = REPO / "experiments" / "fly-reach-03"
BRANCH = STUDY / "f4-presentation-03"
RUN_ID = "F4-PRESENTATION-03-ENG1"
RUN = STUDY / "runs" / RUN_ID
TASK = RUN / "task-bank"
COLLECTION = RUN / "native-collection"
REPAIR = Path(__file__).resolve().parent
BLOCKS = tuple(range(309000, 309012))
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
SIDES = ("L", "R")
INPUT_MAGIC = b"FLYREACH3SYMINP\0"
TRUTH_MAGIC = b"FLYREACH3SYMTRU\0"
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
HEADER = 32
TRIALS_PER_BLOCK = 8192
COORDINATES_PER_CELL = 64


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, value: object) -> str:
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha_bytes(raw)


def write_csv_new(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())
    return sha_file(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def weight_summary(values: Iterable[float]) -> dict[str, float | int | None]:
    weights = [float(value) for value in values]
    if not weights:
        return {"count": 0, "min_q": None, "max_q": None, "mean_q": None, "sum_q": 0.0, "ess": 0.0}
    total = math.fsum(weights)
    squares = math.fsum(value * value for value in weights)
    return {
        "count": len(weights),
        "min_q": min(weights),
        "max_q": max(weights),
        "mean_q": total / len(weights),
        "sum_q": total,
        "ess": total * total / squares if squares > 0.0 else 0.0,
    }


def bits_for(assignment: list[int]) -> str:
    selected = set(int(value) for value in assignment)
    return "".join("1" if cue in selected else "0" for cue in range(4))


def main() -> None:
    validation_path = REPAIR / "COLLECTION-VALIDATION-RECEIPT-v0.1.1.json"
    seal_path = REPAIR / "RAW-COLLECTION-TREE-SEAL-v0.1.1.json"
    amendment_path = REPAIR / "VALIDATION-REPAIR-AMENDMENT-v0.1.1.json"
    validation = read_json(validation_path)
    seal = read_json(seal_path)
    amendment = read_json(amendment_path)
    if validation.get("status") != "PASS" or validation.get("truth_values_opened") is not False:
        raise RuntimeError("collection validation is not a closed-truth PASS")
    if seal.get("status") != "PASS" or validation.get("raw_collection_tree_seal_sha256") != sha_file(seal_path):
        raise RuntimeError("raw collection seal mismatch")
    if amendment.get("status") != "VERSIONED_READ_ONLY_VALIDATION_CONTINUATION":
        raise RuntimeError("validation repair amendment mismatch")
    sealed_files = {row["name"]: row for row in seal["files"]}
    for name in ("RAW-PREDICTORS.bin", "RAW-SCORING-TRUTH.bin", "NATIVE-COLLECTION-RECEIPT.json"):
        path = COLLECTION / name
        expected = sealed_files.get(name)
        if expected is None or path.stat().st_size != int(expected["bytes"]) or sha_file(path) != expected["sha256"]:
            raise RuntimeError(f"collection artifact drift before support opening: {name}")

    support_amendment = {
        "schema": "F4-PRESENTATION-03-support-accounting-amendment-v0.1.1",
        "status": "FROZEN_PRE_FIT_SUPPORT_AND_WEIGHT_DIAGNOSTICS",
        "validation_repair_identity": REPAIR.name,
        "scope": [
            "emit all 216 substrate-side-block support cells, including zero-row cells",
            "evaluate assignment polarity support across each assignment's two blocks",
            "evaluate all 12 leave-one-block-out training partitions",
            "report raw q=1/p diagnostics with no trim, cap, normalization, or winsorization",
        ],
        "support_rule": "all six assignments must each contain both target polarities across their two blocks; otherwise the equal-weight assignment aggregate is null",
        "eligible_count_rule": "the frozen collector did not persist exact pre-modulus eligible denominators; retain null exact counts and report sampled counts plus sum(q) estimate without replay",
        "weight_diagnostic_fields": ["min_q", "max_q", "mean_q", "sum_q", "ess=(sum_q)^2/sum(q^2)"],
        "support_script_sha256": sha_file(Path(__file__)),
        "collection_validation_receipt_sha256": sha_file(validation_path),
        "raw_collection_tree_seal_sha256": sha_file(seal_path),
        "task_bank_manifest_sha256": sha_file(TASK / "TASK-BANK-MANIFEST.json"),
        "training_payload_sha256": sha_file(TASK / "training.json"),
        "raw_predictor_sha256": sha_file(COLLECTION / "RAW-PREDICTORS.bin"),
        "raw_truth_sha256": sha_file(COLLECTION / "RAW-SCORING-TRUTH.bin"),
        "analysis_prohibited_until_support_receipt": True,
    }
    amendment_path = REPAIR / "SUPPORT-ACCOUNTING-AMENDMENT-v0.1.1.json"
    amendment_sha = write_new(amendment_path, support_amendment)

    task_manifest = read_json(TASK / "TASK-BANK-MANIFEST.json")
    seed_manifest = read_json(TASK / "TASK-SEED-MANIFEST.json")
    assignment_by_block = {int(row["block_id"]): int(row["assignment_index"]) for row in task_manifest["blocks"]}
    if set(assignment_by_block) != set(BLOCKS) or any(list(assignment_by_block.values()).count(i) != 2 for i in range(6)):
        raise RuntimeError("support task assignment map is not exactly two blocks per assignment")
    assignment_defs = [list(map(int, row)) for row in task_manifest["assignments"]]
    if len(assignment_defs) != 6:
        raise RuntimeError("expected six frozen balanced assignments")
    seeds = {int(row["block_id"]): row for row in seed_manifest["blocks"]}
    seed_domains = {
        "assignment_mapping_domain_hex": seed_manifest["assignment_mapping_domain_hex"],
        "task_pattern_domain_hex": seed_manifest["task_pattern_domain_hex"],
        "simulator_domain_hex": seed_manifest["simulator_domain_hex"],
        "schedule_domain_hex": seed_manifest["schedule_domain_hex"],
    }
    graph_manifest = read_json(STUDY / "manifests" / "QUALIFICATION-MANIFEST.json")
    cell_meta = {(str(cell["substrate"]), str(cell["side"])): cell for cell in graph_manifest["cells"]}
    if set(cell_meta) != {(s, d) for s in SUBSTRATES for d in SIDES}:
        raise RuntimeError("frozen cell metadata grid mismatch")

    # Reconstruct predictor identities only. The collection seal already binds
    # features; this pass maps sampled keys to the required 216 actual cells.
    predictor_path = COLLECTION / "RAW-PREDICTORS.bin"
    truth_path = COLLECTION / "RAW-SCORING-TRUTH.bin"
    cell_rows: dict[tuple[str, str, int], dict[str, Any]] = {}
    for substrate in SUBSTRATES:
        for side in SIDES:
            for block in BLOCKS:
                assignment = assignment_by_block[block]
                cell_rows[(substrate, side, block)] = {
                    "substrate": substrate,
                    "side": side,
                    "block_id": block,
                    "assignment_index": assignment,
                    "assignment_bits": bits_for(assignment_defs[assignment]),
                    "positive_cues": ",".join(map(str, assignment_defs[assignment])),
                    "generated_trials": 0,
                    "candidate_coordinate_trial_pairs": 0,
                    "eligible_rows_exact": None,
                    "eligible_population_rows_ht_estimate": 0.0,
                    "sampled_rows": 0,
                    "target_positive_rows": 0,
                    "target_negative_rows": 0,
                    "q_values": [],
                    "processed_trials_verified": False,
                    "task_pattern_seed_sha256": seeds[block]["task_seed_sha256"],
                    "simulator_seed_sha256": seeds[block]["simulator_seed_sha256"],
                    "schedule_seed_sha256": seeds[block]["schedule_seed_sha256"],
                }
    row_keys: list[bytes] = []
    with predictor_path.open("rb") as stream:
        header = stream.read(HEADER)
        if len(header) != HEADER or header[:16] != INPUT_MAGIC:
            raise RuntimeError("predictor header changed after collection seal")
        version, width, count = struct.unpack_from("<IIQ", header, 16)
        if (version, width) != (1, INPUT_WIDTH) or count != int(validation["sampled_row_count"]):
            raise RuntimeError("predictor row dimensions changed after seal")
        for index in range(count):
            record = stream.read(INPUT_WIDTH)
            if len(record) != INPUT_WIDTH:
                raise RuntimeError(f"truncated predictor row {index}")
            key = record[:18]
            sub_id, side_id = key[0], key[1]
            if sub_id >= len(SUBSTRATES) or side_id >= len(SIDES):
                raise RuntimeError(f"bad cell identity at row {index}")
            block, trial, coordinate = struct.unpack_from("<QII", key, 2)
            if block not in BLOCKS:
                raise RuntimeError(f"bad block identity at row {index}")
            cell_key = (SUBSTRATES[sub_id], SIDES[side_id], block)
            if coordinate not in set(map(int, cell_meta[(cell_key[0], cell_key[1])]["coordinates"])):
                raise RuntimeError(f"coordinate outside frozen cell set at row {index}")
            if trial >= TRIALS_PER_BLOCK:
                raise RuntimeError(f"trial outside frozen task schedule at row {index}")
            row_keys.append(key)
            cell_rows[cell_key]["sampled_rows"] += 1

    # Open only p and Y. Reference, native delta, preweight, and feature payload
    # values are skipped and are not used by this support gate.
    row_records: list[tuple[tuple[str, str, int], int, float]] = []
    with truth_path.open("rb") as stream:
        header = stream.read(HEADER)
        if len(header) != HEADER or header[:16] != TRUTH_MAGIC:
            raise RuntimeError("truth header changed after collection seal")
        version, width, count = struct.unpack_from("<IIQ", header, 16)
        if (version, width) != (1, TRUTH_WIDTH) or count != len(row_keys):
            raise RuntimeError("truth dimensions changed after collection seal")
        for index, expected_key in enumerate(row_keys):
            key = stream.read(18)
            if key != expected_key:
                raise RuntimeError(f"truth/predictor key mismatch during support accounting at {index}")
            p_raw = stream.read(8)
            y_raw = stream.read(1)
            if len(p_raw) != 8 or len(y_raw) != 1:
                raise RuntimeError(f"truncated truth support fields at {index}")
            p = struct.unpack("<d", p_raw)[0]
            y = struct.unpack("b", y_raw)[0]
            if not math.isfinite(p) or p <= 0.0 or p > 1.0 or y not in (-1, 1):
                raise RuntimeError(f"invalid p/Y support values at row {index}")
            q = 1.0 / p
            sub_id, side_id = key[0], key[1]
            block = struct.unpack_from("<Q", key, 2)[0]
            cell_key = (SUBSTRATES[sub_id], SIDES[side_id], block)
            cell = cell_rows[cell_key]
            expected_p = float(cell_meta[(cell["substrate"], cell["side"])]["inclusion_probability"])
            if p != expected_p:
                raise RuntimeError(f"stored inclusion probability differs from frozen cell metadata: {cell['substrate']}:{cell['side']}")
            cell["q_values"].append(q)
            row_records.append((cell_key, y, q))
            if y == 1:
                cell["target_positive_rows"] += 1
            else:
                cell["target_negative_rows"] += 1
            # Skip native proposed delta, preweight, and reference fields.
            stream.seek(TRUTH_WIDTH - 27, os.SEEK_CUR)
        if stream.tell() != HEADER + count * TRUTH_WIDTH:
            raise RuntimeError("support reader ended at wrong truth offset")

    native = read_json(COLLECTION / "NATIVE-COLLECTION-RECEIPT.json")
    native_map = {(str(row["substrate"]), str(row["side"]), int(row["block_id"])): row for row in native["streams"]}
    task_blocks = {int(row["block_id"]): row for row in task_manifest["blocks"]}
    csv_fields = [
        "cell_id", "substrate", "side", "block_id", "assignment_index", "assignment_bits", "positive_cues",
        "generated_trials", "processed_trials", "candidate_coordinate_trial_pairs", "eligibility_rule",
        "eligible_rows_exact", "eligible_population_rows_ht_estimate", "sampled_rows",
        "target_positive_rows", "target_negative_rows", "class_complete", "native_stream_status",
        "inclusion_probability_p", "min_q", "max_q", "mean_q", "sum_q", "ess",
        "task_pattern_seed_sha256", "simulator_seed_sha256", "schedule_seed_sha256",
        "assignment_mapping_domain_hex", "task_pattern_domain_hex", "simulator_domain_hex", "schedule_domain_hex",
    ]
    cell_csv_rows: list[dict[str, Any]] = []
    cell_weights: dict[str, Any] = {}
    by_block: dict[int, list[tuple[int, float]]] = defaultdict(list)
    by_assignment: dict[int, list[tuple[int, float]]] = defaultdict(list)
    per_cell_records: dict[tuple[str, str, int], list[tuple[int, float]]] = defaultdict(list)
    all_rows: list[tuple[int, float]] = []
    for cell_key, target, qvalue in row_records:
        block = cell_key[2]
        assignment = assignment_by_block[block]
        item = (target, qvalue)
        per_cell_records[cell_key].append(item)
        by_block[block].append(item)
        by_assignment[assignment].append(item)
        all_rows.append(item)
    for key in [(s, d, b) for s in SUBSTRATES for d in SIDES for b in BLOCKS]:
        cell = cell_rows[key]
        block = cell["block_id"]
        assignment = cell["assignment_index"]
        task = task_blocks[block]
        schedule_rows = task.get("trial_count")
        if schedule_rows != TRIALS_PER_BLOCK:
            raise RuntimeError(f"task schedule length mismatch for block {block}")
        cell["generated_trials"] = int(schedule_rows)
        cell["processed_trials_verified"] = native_map[key].get("status") == "PASS" and native_map[key].get("rows") == cell["sampled_rows"]
        if not cell["processed_trials_verified"]:
            raise RuntimeError(f"native stream receipt mismatch for cell {key}")
        cell["candidate_coordinate_trial_pairs"] = TRIALS_PER_BLOCK * COORDINATES_PER_CELL
        # The native collector did not serialize the pre-modulus eligible
        # denominator. Preserve null instead of fabricating an exact count.
        p = float(cell_meta[(cell["substrate"], cell["side"])]["inclusion_probability"])
        qd = weight_summary(cell["q_values"])
        cell["eligible_population_rows_ht_estimate"] = qd["sum_q"]
        cell_id = f"{cell['substrate']}:{cell['side']}:{block}"
        cell_weights[cell_id] = _scoped_weight_summary(per_cell_records[key])
        cell_csv_rows.append({
            "cell_id": cell_id,
            "substrate": cell["substrate"],
            "side": cell["side"],
            "block_id": block,
            "assignment_index": assignment,
            "assignment_bits": cell["assignment_bits"],
            "positive_cues": cell["positive_cues"],
            "generated_trials": cell["generated_trials"],
            "processed_trials": cell["generated_trials"],
            "candidate_coordinate_trial_pairs": cell["candidate_coordinate_trial_pairs"],
            "eligibility_rule": "reference target Y in {-1,+1} and abs(native proposed delta)>EPS before deterministic row-modulus sampling",
            "eligible_rows_exact": "",
            "eligible_population_rows_ht_estimate": f"{cell['eligible_population_rows_ht_estimate']:.12g}",
            "sampled_rows": cell["sampled_rows"],
            "target_positive_rows": cell["target_positive_rows"],
            "target_negative_rows": cell["target_negative_rows"],
            "class_complete": cell["target_positive_rows"] > 0 and cell["target_negative_rows"] > 0,
            "native_stream_status": native_map[key]["status"],
            "inclusion_probability_p": f"{p:.17g}",
            "min_q": "" if qd["min_q"] is None else f"{qd['min_q']:.12g}",
            "max_q": "" if qd["max_q"] is None else f"{qd['max_q']:.12g}",
            "mean_q": "" if qd["mean_q"] is None else f"{qd['mean_q']:.12g}",
            "sum_q": f"{qd['sum_q']:.12g}",
            "ess": f"{qd['ess']:.12g}",
            "task_pattern_seed_sha256": cell["task_pattern_seed_sha256"],
            "simulator_seed_sha256": cell["simulator_seed_sha256"],
            "schedule_seed_sha256": cell["schedule_seed_sha256"],
            **seed_domains,
        })

    # Assignment support is determined on the two blocks together, pooled over
    # the frozen substrate-side panel, then class balanced and equally weighted.
    assignment_support: list[dict[str, Any]] = []
    assignment_weights: dict[str, Any] = {}
    for assignment in range(6):
        blocks = [block for block in BLOCKS if assignment_by_block[block] == assignment]
        values = by_assignment[assignment]
        positives = sum(target == 1 for target, _ in values)
        negatives = sum(target == -1 for target, _ in values)
        assignment_support.append({
            "assignment_index": assignment,
            "assignment_bits": bits_for(assignment_defs[assignment]),
            "positive_cues": assignment_defs[assignment],
            "blocks": blocks,
            "sampled_rows": len(values),
            "target_positive_rows": positives,
            "target_negative_rows": negatives,
            "evaluable": positives > 0 and negatives > 0,
        })
        assignment_weights[str(assignment)] = _scoped_weight_summary(values)

    block_support = []
    block_weights: dict[str, Any] = {}
    for block in BLOCKS:
        values = by_block[block]
        positives = sum(target == 1 for target, _ in values)
        negatives = sum(target == -1 for target, _ in values)
        block_support.append({
            "block_id": block,
            "assignment_index": assignment_by_block[block],
            "assignment_bits": bits_for(assignment_defs[assignment_by_block[block]]),
            "sampled_rows": len(values),
            "target_positive_rows": positives,
            "target_negative_rows": negatives,
            "evaluable": positives > 0 and negatives > 0,
        })
        block_weights[str(block)] = _scoped_weight_summary(values)

    training_rows = []
    for heldout in BLOCKS:
        values = [item for block in BLOCKS if block != heldout for item in by_block[block]]
        positives = sum(target == 1 for target, _ in values)
        negatives = sum(target == -1 for target, _ in values)
        training_rows.append({
            "heldout_block": heldout,
            "heldout_assignment_index": assignment_by_block[heldout],
            "training_rows": len(values),
            "training_positive_rows": positives,
            "training_negative_rows": negatives,
            "valid_two_class_training_support": positives > 0 and negatives > 0,
        })

    all_six_evaluable = all(row["evaluable"] for row in assignment_support)
    all_training_valid = all(row["valid_two_class_training_support"] for row in training_rows)
    if len(cell_csv_rows) != 216 or sum(row["sampled_rows"] for row in cell_csv_rows) != len(row_keys):
        raise RuntimeError("support cell table cardinality reconciliation failed")
    fields = csv_fields
    cell_csv_sha = write_csv_new(REPAIR / "CELL-SUPPORT-SURFACE-v0.1.1.csv", fields, cell_csv_rows)
    training_csv_sha = write_csv_new(REPAIR / "TRAINING-SUPPORT-SURFACE-v0.1.1.csv", list(training_rows[0]), training_rows)
    assignment_csv_sha = write_csv_new(REPAIR / "ASSIGNMENT-SUPPORT-v0.1.1.csv", list(assignment_support[0]), assignment_support)
    cell_meta_out = {
        "schema": "F4-PRESENTATION-03-cell-weight-diagnostics-v1",
        "cell_scopes": cell_weights,
        "assignment_scopes": assignment_weights,
        "block_scopes": block_weights,
        "pooled_scope": _scoped_weight_summary(all_rows),
        "diagnostic_fields": ["min_q", "max_q", "mean_q", "sum_q", "ess"],
        "weight_rule": "q=1/p; untrimmed, uncapped, unnormalized, unwinsorized",
    }
    weights_sha = write_new(REPAIR / "RAW-WEIGHT-DIAGNOSTICS-v0.1.1.json", cell_meta_out)
    report = {
        "schema": "F4-PRESENTATION-03-support-accounting-receipt-v0.1.1",
        "status": "PASS",
        "parent_run_id": RUN_ID,
        "validation_repair_identity": REPAIR.name,
        "support_accounting_amendment_sha256": amendment_sha,
        "collection_validation_sha256": sha_file(validation_path),
        "raw_collection_tree_seal_sha256": sha_file(seal_path),
        "support_surface_sha256": cell_csv_sha,
        "assignment_support_sha256": assignment_csv_sha,
        "training_support_sha256": training_csv_sha,
        "raw_weight_diagnostics_sha256": weights_sha,
        "native_collection_unchanged": all(sha_file(COLLECTION / row["name"]) == row["sha256"] for row in sealed_files.values()),
        "truth_fields_opened": ["inclusion_probability_p", "target_polarity_Y"],
        "truth_fields_not_opened": ["native_delta", "preweight", "reference_value"],
        "cell_count": len(cell_csv_rows),
        "sampled_row_count": len(row_keys),
        "generated_trials_per_cell": TRIALS_PER_BLOCK,
        "candidate_coordinate_trial_pairs_per_cell": TRIALS_PER_BLOCK * COORDINATES_PER_CELL,
        "exact_pre_sampling_eligible_counts_recorded_by_frozen_collector": False,
        "pre_sampling_eligible_count_policy": "exact count is null; report the observed sampled-eligible count and separately the untrimmed sum(q) population estimate; no replay or recollection",
        "assignment_support": assignment_support,
        "assignment_evaluable_count": sum(bool(row["evaluable"]) for row in assignment_support),
        "required_evaluable_assignments": 6,
        "primary_equal_weight_assignment_aggregate_evaluable": all_six_evaluable,
        "primary_support_disposition": "EVALUABLE" if all_six_evaluable else "NOT_EVALUABLE_SUPPORT",
        "training_support": training_rows,
        "all_training_folds_two_class_valid": all_training_valid,
        "fits_authorized_by_support_gate": all_training_valid,
        "fits_executed": False,
        "comparative_outcomes_emitted": False,
    }
    write_new(REPAIR / "SUPPORT-ACCOUNTING-RECEIPT-v0.1.1.json", report)
    print(json.dumps({
        "status": "PASS",
        "sampled_rows": len(row_keys),
        "evaluable_assignments": report["assignment_evaluable_count"],
        "primary_disposition": report["primary_support_disposition"],
        "training_folds_valid": all_training_valid,
        "fits_authorized_by_support_gate": all_training_valid,
        "truth_fields_opened": report["truth_fields_opened"],
    }, sort_keys=True))


def _scoped_weight_summary(values: Iterable[tuple[int, float]]) -> dict[str, Any]:
    rows = list(values)
    all_q = weight_summary(q for _, q in rows)
    positive_q = weight_summary(q for y, q in rows if y == 1)
    negative_q = weight_summary(q for y, q in rows if y == -1)
    return {"all_rows": all_q, "target_positive": positive_q, "target_negative": negative_q}


if __name__ == "__main__":
    main()
