from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from s05_common import (
    AUTHORIZATION_PATH,
    CONTRACT_PATH,
    FAS00_EVENTS,
    FAS00_RUN,
    RUN,
    S01_TEST_EVENTS,
    S04_ELIGIBILITY,
    S02_FINAL_CACHE,
    S02_FINAL_PREDICTIONS,
    S02_MEAN_PREDICTIONS,
    FailClosed,
    S01_TEST_ROWS,
    test_bucket,
    iter_jsonl,
    read_json,
    sha_file,
    verify_parents,
    verify_protocol_bundle,
    write_json,
)


def _read_prediction_rows(path, expected_slice_names: set[str]) -> dict[str, dict[str, Any]]:
    by_event: dict[str, dict[str, Any]] = {}
    slice_events: dict[str, set[str]] = defaultdict(set)
    for _, row in iter_jsonl(path):
        event_id = row["event_id"]
        if row.get("slice") not in expected_slice_names or event_id in slice_events[row["slice"]]:
            raise FailClosed(f"Unexpected or duplicate sealed S02 prediction row in {path.name}")
        slice_events[row["slice"]].add(event_id)
        normalized = {
            "event_id": event_id,
            "row_index": int(row["row_index"]),
            "label": int(row["label"]),
            "prediction": int(row["prediction"]),
            "world_seed": int(row["world_seed"]),
            "slices": [row["slice"]],
        }
        if event_id in by_event:
            old = by_event[event_id]
            for key in ("row_index", "label", "prediction", "world_seed"):
                if old[key] != normalized[key]:
                    raise FailClosed(f"Conflicting repeated S02 diagonal prediction for {event_id}")
            old["slices"].append(row["slice"])
        else:
            by_event[event_id] = normalized
    expected_counts = {"test_context_term_3": 412, "test_entity_term_7": 212}
    if {key: len(value) for key, value in slice_events.items()} != expected_counts:
        raise FailClosed("Sealed S02 diagonal predictions do not reproduce contracted slice counts")
    return by_event


def _load_original_population() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expected_slices = {"test_context_term_3", "test_entity_term_7"}
    mean_rows = _read_prediction_rows(S02_MEAN_PREDICTIONS, expected_slices)
    final_rows = _read_prediction_rows(S02_FINAL_PREDICTIONS, expected_slices)
    if set(mean_rows) != set(final_rows) or len(mean_rows) != 512:
        raise FailClosed("S02 diagonal predictions differ in event population or union size")
    for event_id, mean in mean_rows.items():
        final = final_rows[event_id]
        for key in ("row_index", "label", "world_seed", "slices"):
            if (sorted(mean[key]) != sorted(final[key]) if key == "slices" else mean[key] != final[key]):
                raise FailClosed(f"S02 diagonal event/label identity mismatch for {event_id}: {key}")

    # Verify the exact event row and target source against the sealed Phase 1 corpus.
    selected: dict[str, dict[str, Any]] = {}
    by_row = {int(value["row_index"]): event_id for event_id, value in mean_rows.items()}
    for row_index, event in iter_jsonl(FAS00_EVENTS):
        if row_index not in by_row:
            continue
        expected_event_id = by_row[row_index]
        if event["event_id"] != expected_event_id:
            raise FailClosed(f"S02 event ID does not match Phase 1 row {row_index}")
        ref = mean_rows[expected_event_id]
        if (int(event["exact_target"]) != ref["label"] or
                int(event["world_seed"]) != ref["world_seed"] or
                int(event["surface_template_id"]) != 5 or
                not 24 <= int(event["world_seed"]) <= 31 or
                event.get("observation_text") is None):
            raise FailClosed(f"S02 evaluation row does not satisfy original test split: {expected_event_id}")
        slices = []
        if int(event["context_term_id"]) == 3:
            slices.append("CONTEXT_TERM_3")
        if int(event["entity_term_id"]) == 7:
            slices.append("ENTITY_TERM_7")
        expected_slice_map = {"test_context_term_3": "CONTEXT_TERM_3", "test_entity_term_7": "ENTITY_TERM_7"}
        if sorted(slices) != sorted(expected_slice_map[name] for name in ref["slices"]):
            raise FailClosed(f"S02 slice membership differs from Phase 1 metadata: {expected_event_id}")
        selected[expected_event_id] = {
            **ref,
            "context_term_id": int(event["context_term_id"]),
            "entity_term_id": int(event["entity_term_id"]),
            "surface_template_id": int(event["surface_template_id"]),
            "task_structure": event["task_structure"],
            "world_family": event["world_family"],
            "feedback_condition": event["feedback_condition"],
            "exact_target": int(event["exact_target"]),
            "mean_feature_row": row_index * 2,
            "final_feature_row": row_index,
            "row_index": row_index,
        }
    if set(selected) != set(mean_rows):
        raise FailClosed("Not every S02 diagonal event maps to a Phase 1 row")

    # Audit all selected source feature row receipts and output row receipts.
    wanted_full = {row["mean_feature_row"]: row for row in selected.values()}
    seen_full: set[int] = set()
    for _, row in iter_jsonl(FAS00_RUN / "phase2a-v01" / "feature-cache-v01" / "feature-rows-v01.jsonl"):
        source_row = int(row["row_index"])
        if source_row in wanted_full:
            expected = wanted_full[source_row]
            if row.get("event_id") != expected["event_id"] or row.get("input_view") != "FULL":
                raise FailClosed(f"FAS-00 FULL feature row receipt mismatch at {source_row}")
            seen_full.add(source_row)
    if seen_full != set(wanted_full):
        raise FailClosed("S02 selected FULL feature rows are not all present in the sealed cache receipt")

    final_manifest = S02_FINAL_CACHE / "final-position-rows-v01.jsonl"
    wanted_final = {row["final_feature_row"]: row for row in selected.values()}
    seen_final: set[int] = set()
    for _, row in iter_jsonl(final_manifest):
        index = int(row.get("output_row_index", -1))
        if index in wanted_final:
            expected = wanted_final[index]
            if (row.get("event_id") != expected["event_id"] or
                    int(row.get("source_full_row_index", -1)) != index * 2):
                raise FailClosed(f"S02 final-position row receipt mismatch at {index}")
            seen_final.add(index)
    if seen_final != set(wanted_final):
        raise FailClosed("S02 selected final-position rows are not all present in the sealed cache receipt")

    slices = {
        "UNION": sorted(selected),
        "CONTEXT_TERM_3": sorted(event_id for event_id, row in selected.items() if "CONTEXT_TERM_3" in row["slices"]),
        "ENTITY_TERM_7": sorted(event_id for event_id, row in selected.items() if "ENTITY_TERM_7" in row["slices"]),
    }
    if {name: len(ids) for name, ids in slices.items()} != {"UNION": 512, "CONTEXT_TERM_3": 412, "ENTITY_TERM_7": 212}:
        raise FailClosed("Original corpus S05 population counts differ from the sealed contract")
    return [{**selected[event_id], "event_id": event_id} for event_id in slices["UNION"]], slices


def _load_s01_population() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    eligibility = read_json(S04_ELIGIBILITY)
    if (eligibility.get("status") != "PASS" or
            eligibility.get("selected_factorial_test_quartets") != 4933 or
            eligibility.get("selected_factorial_test_events") != 19732 or
            eligibility.get("feature_payloads_read") is not False):
        raise FailClosed("Sealed S04 population eligibility differs")
    needed: dict[str, dict[str, Any]] = {}
    quartet_rows = []
    for quartet in eligibility["selected_quartets"]:
        qid = quartet["quartet_id"]
        if test_bucket(qid) != 0 or quartet.get("track_id") != "FACTORIAL_BALANCED":
            raise FailClosed(f"S04 selected quartet violates its sealed track/split: {qid}")
        state_map = {int(item["candidate_identity"]): int(item["state_id"])
                     for item in quartet["candidate_semantics"]}
        if set(state_map) != {0, 1, 2} or set(state_map.values()) != {0, 1, 2}:
            raise FailClosed(f"S04 candidate/state mapping is invalid for {qid}")
        row = {
            "quartet_id": qid,
            "target_state_id": int(quartet["target_state_id"]),
            "candidate_identity_order": [int(x) for x in quartet["candidate_identity_order"]],
            "state_by_candidate_identity": state_map,
            "relation_id": int(quartet["relation_id"]),
            "context_term_split": quartet["context_term_split"],
            "entity_term_split": quartet["entity_term_split"],
            "events": [],
        }
        for ref in quartet["variants"]:
            event = {
                "event_id": ref["event_id"],
                "variant_id": ref["variant_id"],
                "test_row": int(ref["test_row"]),
                "feature_row_index": int(ref["feature_row_index"]),
                "target_state_id": int(quartet["target_state_id"]),
                "candidate_identity_order": row["candidate_identity_order"],
                "state_by_candidate_identity": state_map,
                "quartet_id": qid,
                "track_id": "FACTORIAL_BALANCED",
            }
            if event["event_id"] in needed:
                raise FailClosed(f"Duplicate S04 selected event {event['event_id']}")
            needed[event["event_id"]] = event
            row["events"].append(event)
        if {event["variant_id"] for event in row["events"]} != {"A", "C", "E", "P"}:
            raise FailClosed(f"Incomplete S04 quartet {qid}")
        quartet_rows.append(row)
    if len(needed) != 19732 or len(quartet_rows) != 4933:
        raise FailClosed("S04 selected S01 population count differs from sealed contract")

    test_rows: dict[int, dict[str, Any]] = {}
    selected_event_ids = set(needed)
    found_ids: set[str] = set()
    for test_row, item in iter_jsonl(S01_TEST_EVENTS):
        if test_row >= S01_TEST_ROWS:
            raise FailClosed("S01 test event manifest exceeds its sealed row count")
        if item["event_id"] in selected_event_ids:
            event = needed[item["event_id"]]
            if (int(item["test_row"]) != event["test_row"] or test_row != event["test_row"] or
                    int(item["feature_row_index"]) != event["feature_row_index"] or
                    item["quartet_id"] != event["quartet_id"] or
                    item["variant_id"] != event["variant_id"]):
                raise FailClosed(f"S04 selected event does not bind to S01 test metadata: {event['event_id']}")
            found_ids.add(item["event_id"])
            test_rows[event["test_row"]] = item
    if found_ids != selected_event_ids:
        raise FailClosed("S04 selected events are absent from the S01 test manifest")

    flat = []
    for q in quartet_rows:
        for event in q["events"]:
            event["sealed_test_metadata"] = test_rows[event["test_row"]]
            flat.append(event)
    supports = Counter(event["target_state_id"] for event in flat)
    if set(supports) != {0, 1, 2}:
        raise FailClosed("S01 selected population lacks one of the three target states")
    return flat, {"FACTORIAL_TEST": [event["event_id"] for event in flat], "quartets": quartet_rows}


def main() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    protocol = verify_protocol_bundle()
    parents = verify_parents(deep=True)
    original_rows, original_slices = _load_original_population()
    s01_rows, s01_selection = _load_s01_population()
    populations = {
        "population_id": "FAS_S05_EVENT_POPULATIONS_V01",
        "parents": parents,
        "FAS00_ORIGINAL": {
            "rows": original_rows,
            "slices": original_slices,
            "class_order": ["safe", "risky", "idle"],
            "feature_row_mapping": {"mean_full": "2 * row_index", "final_position": "row_index"},
        },
        "S01_CONTROLLED": {
            "rows": s01_rows,
            "quartets": s01_selection["quartets"],
            "slices": {"FACTORIAL_TEST": s01_selection["FACTORIAL_TEST"]},
            "class_order": ["zavik", "nurex", "pavom"],
            "class_ids": [0, 1, 2],
        },
        "model_contact": False,
        "feature_payloads_used_for_selection": False,
        "probe_parameters_used_for_selection": False,
    }
    write_json(RUN / "event-populations-v01.json", populations)
    preflight = {
        "receipt_id": "FAS_S05_PREFLIGHT_V01",
        "status": "PASS",
        "protocol_root_sha256": protocol["root_sha256"],
        "analysis_contract_sha256": sha_file(CONTRACT_PATH),
        "authorization_packet_sha256": sha_file(AUTHORIZATION_PATH),
        "event_populations_sha256": sha_file(RUN / "event-populations-v01.json"),
        "parents": parents,
        "FAS00_ORIGINAL_unique_events": len(original_rows),
        "FAS00_ORIGINAL_slices": {key: len(value) for key, value in original_slices.items()},
        "S01_CONTROLLED_quartets": len(s01_selection["quartets"]),
        "S01_CONTROLLED_events": len(s01_rows),
        "diagonal_replay_required": True,
        "model_contact": False,
        "feature_extraction": False,
        "probe_fitting": False,
        "adaptive_mechanisms": False,
        "SAE_analysis": False,
    }
    write_json(RUN / "preflight-receipt-v01.json", preflight)
    print(f"S05_PREFLIGHT_PASS fas00_union={len(original_rows)} context={len(original_slices['CONTEXT_TERM_3'])} entity={len(original_slices['ENTITY_TERM_7'])} s01_quartets={len(s01_selection['quartets'])} events={len(s01_rows)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"S05_FAIL_CLOSED: {type(exc).__name__}: {exc}")
        raise
