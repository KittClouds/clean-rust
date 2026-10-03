from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any

from s04_common_v02 import (
    BINDING,
    CLASS_NAMES,
    CONTRACT,
    PROJECT,
    RUN,
    S01_2_CORPUS,
    S01_3_TEST_EVENTS,
    VARIANT_ORDER,
    FailClosed,
    iter_jsonl,
    read_json,
    sha_file,
    test_bucket,
    verify_parents,
    verify_protocol_bundle,
    write_json,
)


def _variant_fields(event: dict[str, Any], quartet: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event["event_id"],
        "variant_id": event["variant_id"],
        "changed_factor": event["changed_factor"],
        "context_term_id": event["context_term_id"],
        "context_term": event["context_term"],
        "entity_term_id": event["entity_term_id"],
        "entity_term": event["entity_term"],
        "context_term_split": event["context_term_split"],
        "entity_term_split": event["entity_term_split"],
        "observation_template_id": event["observation_template_id"],
        "query_template_id": event["query_template_id"],
        "candidate_identity_order": event["candidate_identity_order"],
        "candidate_text_order": event["candidate_text_order"],
        "observation_text": event["observation_text"],
        "query_text": event["query_text"],
        "target_candidate_identity": event["target_candidate_identity"],
        "exact_target": event["exact_target"],
        "query_semantics": event["query_semantics"],
        "relation_id": quartet["relation_id"],
        "state_id": quartet["state_id"],
        "input_sha256": event["input_sha256"],
    }


def _assert_edge(base: dict[str, Any], variant: dict[str, Any], variant_id: str) -> None:
    if variant_id == "C":
        if (variant["context_term_id"] == base["context_term_id"] or
                variant["context_term"] == base["context_term"] or
                variant["entity_term_id"] != base["entity_term_id"] or
                variant["entity_term"] != base["entity_term"] or
                variant["observation_text"] == base["observation_text"] or
                variant["query_text"] == base["query_text"] or
                variant["observation_template_id"] != base["observation_template_id"]):
            raise FailClosed("S01 C edge does not isolate the declared context alias")
    elif variant_id == "E":
        if (variant["entity_term_id"] == base["entity_term_id"] or
                variant["entity_term"] == base["entity_term"] or
                variant["context_term_id"] != base["context_term_id"] or
                variant["context_term"] != base["context_term"] or
                variant["observation_text"] == base["observation_text"] or
                variant["query_text"] == base["query_text"] or
                variant["observation_template_id"] != base["observation_template_id"]):
            raise FailClosed("S01 E edge does not isolate the declared entity alias")
    elif variant_id == "P":
        if (variant["entity_term_id"] != base["entity_term_id"] or
                variant["context_term_id"] != base["context_term_id"] or
                variant["entity_term"] != base["entity_term"] or
                variant["context_term"] != base["context_term"] or
                variant["observation_text"] == base["observation_text"] or
                variant["query_text"] != base["query_text"] or
                variant["observation_template_id"] != (base["observation_template_id"] + 4) % 8):
            raise FailClosed("S01 P edge does not isolate the declared observation paraphrase")
    else:
        raise FailClosed(f"Unexpected S01 variant: {variant_id}")
    for key in (
        "context_term_split", "entity_term_split", "query_template_id",
        "candidate_identity_order", "candidate_text_order",
        "target_candidate_identity", "exact_target", "query_semantics",
        "relation_id", "state_id",
    ):
        if variant[key] != base[key]:
            raise FailClosed(f"S01 {variant_id} edge changed invariant {key}")


def build_design() -> tuple[dict[str, Any], dict[str, Any]]:
    test_by_quartet: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(dict)
    seen_test_rows: set[int] = set()
    seen_feature_rows: set[int] = set()
    seen_events: set[str] = set()
    test_event_count = 0
    for row in iter_jsonl(S01_3_TEST_EVENTS):
        qid, variant_id, event_id = row["quartet_id"], row["variant_id"], row["event_id"]
        if test_bucket(qid) != 0:
            raise FailClosed(f"S01-3 test manifest contains a non-test quartet: {qid}")
        if variant_id in test_by_quartet[qid] or event_id in seen_events:
            raise FailClosed("Duplicate event or variant in the sealed S01-3 test manifest")
        test_row = int(row["test_row"])
        feature_row = int(row["feature_row_index"])
        if test_row in seen_test_rows or feature_row in seen_feature_rows:
            raise FailClosed("Duplicate test-row or feature-row index in S01-3 test manifest")
        seen_test_rows.add(test_row)
        seen_feature_rows.add(feature_row)
        seen_events.add(event_id)
        test_by_quartet[qid][variant_id] = row
        test_event_count += 1
    if test_event_count != 21_272 or seen_test_rows != set(range(test_event_count)):
        raise FailClosed("S01-3 test-event manifest count or row order differs from its frozen contract")
    for qid, variants in test_by_quartet.items():
        if set(variants) != set(VARIANT_ORDER):
            raise FailClosed(f"S01-3 test split did not keep all quartet siblings together: {qid}")

    selected: list[dict[str, Any]] = []
    corpus_quartets = 0
    seen_test_quartets: set[str] = set()
    selected_qids: set[str] = set()
    state_labels: dict[int, str] | None = None
    relation_state_counts: collections.Counter[tuple[int, int]] = collections.Counter()
    factor_counts: collections.Counter[str] = collections.Counter()
    for quartet in iter_jsonl(S01_2_CORPUS):
        qid = quartet["quartet_id"]
        if qid not in test_by_quartet:
            continue
        if qid in seen_test_quartets:
            raise FailClosed(f"Duplicate quartet identity in S01-2 corpus: {qid}")
        seen_test_quartets.add(qid)
        if quartet["track_id"] != "FACTORIAL_BALANCED":
            continue
        corpus_quartets += 1
        variant_map = {variant["variant_id"]: variant for variant in quartet["variants"]}
        if set(variant_map) != set(VARIANT_ORDER):
            raise FailClosed(f"Quartet does not contain exactly A/C/E/P: {qid}")
        base = _variant_fields(variant_map["A"], quartet)
        if (base["changed_factor"] != "NONE" or
                variant_map["C"]["changed_factor"] != "CONTEXT" or
                variant_map["E"]["changed_factor"] != "ENTITY" or
                variant_map["P"]["changed_factor"] != "OBSERVATION_TEMPLATE"):
            raise FailClosed(f"Quartet factor labels violate the S01 protocol: {qid}")
        for variant_id in ("C", "E", "P"):
            _assert_edge(base, _variant_fields(variant_map[variant_id], quartet), variant_id)

        candidate_semantics = quartet["latent_world"]["candidate_semantics"]
        state_by_identity = {int(item["candidate_identity"]): int(item["state_id"]) for item in candidate_semantics}
        labels = {int(item["state_id"]): str(item["surface"]) for item in candidate_semantics}
        if state_by_identity != {0: 0, 1: 1, 2: 2} or set(labels) != {0, 1, 2}:
            raise FailClosed(f"Unexpected candidate-identity/state mapping in {qid}")
        if int(quartet["target_candidate_identity"]) != int(quartet["state_id"]):
            raise FailClosed(f"S01 target candidate does not map to the declared state in {qid}")
        expected_target_position = quartet["candidate_identity_order"].index(int(quartet["target_candidate_identity"]))
        if int(quartet["exact_target"]) != expected_target_position:
            raise FailClosed(f"S01 exact-target class is not the candidate slot in {qid}")
        if state_labels is None:
            state_labels = labels
        elif state_labels != labels:
            raise FailClosed("Invented state surfaces are not invariant across the sealed S01 corpus")

        event_refs = []
        for variant_id in VARIANT_ORDER:
            variant = _variant_fields(variant_map[variant_id], quartet)
            test_meta = test_by_quartet[qid][variant_id]
            if test_meta["event_id"] != variant["event_id"]:
                raise FailClosed(f"S01 test manifest event identity mismatch: {qid}/{variant_id}")
            for key in (
                "exact_target", "context_term_id", "entity_term_id",
                "context_term_split", "entity_term_split", "observation_template_id",
                "query_template_id", "relation_id", "state_id",
            ):
                if test_meta[key] != variant[key]:
                    raise FailClosed(f"S01 test manifest {key} mismatch: {qid}/{variant_id}")
            event_refs.append({
                "variant_id": variant_id,
                "event_id": variant["event_id"],
                "feature_row_index": int(test_meta["feature_row_index"]),
                "test_row": int(test_meta["test_row"]),
                "exact_target_candidate_position": int(variant["exact_target"]),
            })
            factor_counts[variant_id] += 1
        relation_state_counts[(int(quartet["relation_id"]), int(quartet["state_id"]))] += 1
        selected_qids.add(qid)
        selected.append({
            "quartet_id": qid,
            "track_id": quartet["track_id"],
            "context_term_split": quartet["context_term_split"],
            "entity_term_split": quartet["entity_term_split"],
            "context_pair_id": int(quartet["context_pair_id"]),
            "entity_pair_id": int(quartet["entity_pair_id"]),
            "context_term_id_A": int(variant_map["A"]["context_term_id"]),
            "context_term_id_C": int(variant_map["C"]["context_term_id"]),
            "context_term_A": variant_map["A"]["context_term"],
            "context_term_C": variant_map["C"]["context_term"],
            "entity_term_id_A": int(variant_map["A"]["entity_term_id"]),
            "entity_term_id_E": int(variant_map["E"]["entity_term_id"]),
            "entity_term_A": variant_map["A"]["entity_term"],
            "entity_term_E": variant_map["E"]["entity_term"],
            "world_family_id": int(quartet["world_family_id"]),
            "relation_id": int(quartet["relation_id"]),
            "state_id": int(quartet["state_id"]),
            "observation_template_id": int(quartet["observation_template_id"]),
            "observation_template_id_P": int(variant_map["P"]["observation_template_id"]),
            "query_template_id": int(quartet["query_template_id"]),
            "candidate_identity_order": quartet["candidate_identity_order"],
            "candidate_semantics": candidate_semantics,
            "target_candidate_identity": int(quartet["target_candidate_identity"]),
            "target_state_id": int(quartet["state_id"]),
            "variants": event_refs,
        })

    if (corpus_quartets != len(selected) or not selected or
            seen_test_quartets != set(test_by_quartet)):
        raise FailClosed("No complete factorial test quartets were found in the sealed corpus")

    eligibility = {
        "disposition_id": "FAS_S04_DESIGN_ELIGIBILITY_V01",
        "status": "PASS",
        "test_manifest_rows_all_tracks": test_event_count,
        "selected_factorial_test_quartets": len(selected),
        "selected_factorial_test_events": len(selected) * 4,
        "complete_A_C_E_P_quartets": len(selected),
        "variant_counts": dict(factor_counts),
        "relation_state_quartet_counts": [
            {"relation_id": relation, "state_id": state, "quartets": count}
            for (relation, state), count in sorted(relation_state_counts.items())
        ],
        "semantic_state_surfaces_by_id": {str(key): value for key, value in sorted((state_labels or {}).items())},
        "estimand_eligibility": {
            "C_context_alias_delta": "ELIGIBLE",
            "E_entity_alias_delta": "ELIGIBLE",
            "P_observation_paraphrase_delta": "ELIGIBLE",
            "CE_joint_alias_interaction": "NOT_ESTIMABLE_NO_CE_VARIANT_IN_SEALED_QUARTET",
            "R_relation_intervention": "NOT_ESTIMATED_NOT_A_WITHIN_QUARTET_VARIANT",
            "S_state_intervention": "NOT_ESTIMATED_NOT_A_WITHIN_QUARTET_VARIANT",
        },
        "selected_quartets": selected,
        "model_contact": False,
        "feature_payloads_read": False,
    }
    receipt = {
        "receipt_id": "FAS_S04_DESIGN_AUDIT_V01",
        "status": "PASS",
        "protocol_root_sha256": verify_protocol_bundle()["root_sha256"],
        "runner_correction_root_sha256": verify_protocol_bundle()["runner_correction_root_sha256"],
        "parents": verify_parents(),
        "corpus_sha256": sha_file(S01_2_CORPUS),
        "test_events_sha256": sha_file(S01_3_TEST_EVENTS),
        "selected_quartets": len(selected),
        "selected_events": len(selected) * 4,
        "metadata_only": True,
        "feature_payloads_read": False,
        "LFM_loaded": False,
        "probe_parameters_read": False,
    }
    return eligibility, receipt


def main() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    protocol = verify_protocol_bundle()
    eligibility, receipt = build_design()
    write_json(RUN / "design-eligibility-v01.json", eligibility)
    receipt["eligibility_sha256"] = sha_file(RUN / "design-eligibility-v01.json")
    receipt["protocol_root_sha256"] = protocol["root_sha256"]
    write_json(RUN / "design-audit-receipt-v01.json", receipt)
    preflight = {
        "receipt_id": "FAS_S04_PREFLIGHT_V01",
        "status": "PASS",
        "protocol_root_sha256": protocol["root_sha256"],
        "runner_correction_root_sha256": protocol["runner_correction_root_sha256"],
        "eligibility_sha256": sha_file(RUN / "design-eligibility-v01.json"),
        "design_audit_receipt_sha256": sha_file(RUN / "design-audit-receipt-v01.json"),
        "parents": receipt["parents"],
        "selected_quartets": eligibility["selected_factorial_test_quartets"],
        "selected_events": eligibility["selected_factorial_test_events"],
        "S04_DESIGN_AUDIT_PASS": True,
        "S04_MARGIN_ANALYSIS_COMPLETE": False,
        "S04_MODEL_CONTACT": False,
        "S04_PROBE_FITTING": False,
        "FAS00_PHASE4_AUTHORIZED": False,
        "SAE_ANALYSIS_AUTHORIZED": False,
    }
    write_json(RUN / "preflight-receipt-v01.json", preflight)
    print(f"S04_DESIGN_AUDIT_PASS quartets={eligibility['selected_factorial_test_quartets']} events={eligibility['selected_factorial_test_events']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"S04_FAIL_CLOSED: {type(exc).__name__}: {exc}")
        raise
