"""Independent, metadata-safe audit for the fresh v0.8I Phase-A banks."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ARM_SIZE = 100_000
FAMILY_FIELDS = (
    "candidate_set_construction_family",
    "definition_template_family",
    "intervention_family",
    "ontology_family",
    "schema_composition_family",
    "world_or_topology_family",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_no}") from exc


def indexed_texts(path: Path) -> list[str]:
    result: list[str] = []
    for expected, row in enumerate(rows(path)):
        if row.get("index") != expected or not isinstance(row.get("text"), str):
            raise ValueError(f"invalid indexed text table {path}:{expected + 1}")
        result.append(row["text"])
    return result


def multiplicity_histogram(counts: Counter[Any]) -> Counter[int]:
    return Counter(counts.values())


def audit_bank(path: Path, states: list[str], candidates: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ids": {},
        "episodes": set(),
        "training_signatures": Counter(),
        "selector_signatures": Counter(),
        "state_occurrences": Counter(),
        "root_occurrences": Counter(),
        "views": Counter(),
        "cardinality": Counter(),
        "families": {name: Counter() for name in FAMILY_FIELDS},
    }
    count = 0
    for row in rows(path):
        count += 1
        group_id = str(row.get("group_id", ""))
        if not group_id or group_id in result["ids"]:
            raise ValueError(f"empty/duplicate group ID in {path}: {group_id!r}")
        if row.get("split") != "train":
            raise ValueError(f"non-training row in Phase-A bank: {group_id}")
        state = states[int(row["state_idx"])]
        candidate_ids = list(row["candidate_semantic_ids"])
        candidate_surfaces = [
            candidates[int(index)]
            for index in row["candidate_indices"]["name_definition"]
        ]
        if len(candidate_ids) != len(candidate_surfaces):
            raise ValueError(f"candidate surface/ID count mismatch: {group_id}")
        pairs = list(zip(candidate_ids, candidate_surfaces))
        selector_payload = [
            state,
            pairs,
            row["kind"],
            row["view"],
            bool(row["open_world"]),
        ]
        training_payload = [
            state,
            pairs,
            row["kind"],
            row["view"],
            list(row["gold"]),
            bool(row["open_world"]),
            row["probability_source"],
            row["authority"],
            "L3_source_typed",
            1.0,
        ]
        result["ids"][group_id] = {
            "row_digest": digest(row),
            "episode_id": str(row["episode_id"]),
        }
        result["episodes"].add(str(row["episode_id"]))
        result["training_signatures"][digest(training_payload)] += 1
        result["selector_signatures"][digest(selector_payload)] += 1
        result["state_occurrences"][state] += 1
        result["root_occurrences"][str(row["root_id"])] += 1
        result["views"][str(row["view"])] += 1
        result["cardinality"][str(row["candidate_cardinality"])] += 1
        for field in FAMILY_FIELDS:
            result["families"][field][str(row["family_ids"][field])] += 1
    if count != ARM_SIZE:
        raise ValueError(f"{path} has {count} rows, expected {ARM_SIZE}")
    result["count"] = count
    result["state_multiplicity"] = multiplicity_histogram(result["state_occurrences"])
    result["selector_multiplicity"] = multiplicity_histogram(result["selector_signatures"])
    result["root_multiplicity"] = multiplicity_histogram(result["root_occurrences"])
    result["unique_states"] = len(result["state_occurrences"])
    return result


def counter_equal(left: Counter[Any], right: Counter[Any]) -> bool:
    return left == right


def validate_contrast_triplet(
    certificate: dict[str, Any], episodes: dict[str, dict[str, Any]]
) -> None:
    ids = certificate["episode_ids"]
    base, flip, sham = (episodes[str(ids[role])] for role in ("anchor", "fact_flip", "sham"))
    for role, episode in (("anchor", base), ("fact_flip", flip), ("sham", sham)):
        episode_id = str(ids[role])
        require = lambda condition, message: (_ for _ in ()).throw(ValueError(message)) if not condition else None
        require(episode.get("episode_id") == episode_id, f"contrast episode identity mismatch: {episode_id}")
        require(episode.get("contract") == "jev-like-decision-dataset/v1", f"wrong contrast contract: {episode_id}")
        require(episode.get("identity", {}).get("episode_id") == episode_id, f"canonical identity mismatch: {episode_id}")
        require(episode["identity"].get("world_family_id") == certificate["world_family_id"], f"contrast family mismatch: {episode_id}")
        require(episode["identity"].get("world_instance_id") == base["identity"].get("world_instance_id"), f"contrast world mismatch: {episode_id}")
        require(episode.get("runtime_schema") == base.get("runtime_schema"), f"contrast schema drift: {episode_id}")
        require(episode.get("queries") == base.get("queries"), f"contrast query drift: {episode_id}")
        require(len(episode.get("queries", [])) == 1 and len(episode.get("gold_targets", [])) == 1, f"contrast query count mismatch: {episode_id}")

    base_text = base["state"]["observable"]["content"]
    flip_text = flip["state"]["observable"]["content"]
    sham_text = sham["state"]["observable"]["content"]
    require(len(base_text) == len(flip_text) == len(sham_text), "contrast surface lengths differ")
    changed = lambda left, right: [i for i, (a, b) in enumerate(zip(left, right)) if a != b]
    flip_chars, sham_chars = changed(base_text, flip_text), changed(base_text, sham_text)
    require(len(flip_chars) == len(sham_chars) == 1 and flip_chars != sham_chars, "contrast edits are not distinct single-character changes")
    flip_byte = len(base_text[:flip_chars[0]].encode("utf-8"))
    sham_byte = len(base_text[:sham_chars[0]].encode("utf-8"))
    for edge, position, altered, before, after in (
        ("fact_flip", flip_byte, flip_text, base_text, flip_text),
        ("sham", sham_byte, sham_text, base_text, sham_text),
    ):
        before_bytes, after_bytes = before.encode("utf-8"), after.encode("utf-8")
        require(before_bytes[position:position + 1] == b"+" and after_bytes[position:position + 1] == b"-", f"contrast edit is not + to -: {edge}")
        span = certificate["changed_surface_spans"][edge]
        require(span["before"] == [position, position + 1] and span["after"] == [position, position + 1], f"contrast span mismatch: {edge}")

    targets = [episode["gold_targets"][0] for episode in (base, flip, sham)]
    distributions = [
        [float(item["probability"]) for item in target["target"]["distribution"]]
        for target in targets
    ]
    certified = [certificate["exact_target_before"], certificate["exact_target_after"], certificate["exact_sham_target"]]
    for actual, expected in zip(distributions, certified):
        if len(actual) != len(expected) or any(abs(a - float(b)) > 1e-12 for a, b in zip(actual, expected)):
            raise ValueError("contrast posterior differs from certificate")
    require(all(target["probability_source"]["probability_source"] == "exact_generative_posterior" for target in targets), "contrast lacks exact-posterior authority")
    require(all(abs(sum(values) - 1.0) <= 1e-12 for values in distributions), "contrast posterior is not normalized")
    require(all(abs(a - b) <= 1e-12 for a, b in zip(distributions[0], distributions[2])), "sham changed exact posterior")
    tops = [max(range(len(values)), key=values.__getitem__) for values in distributions]
    require(tops == [0, 1, 0], "contrast top candidate does not flip only on relevant evidence")
    for target, expected in zip(targets, (certificate["expected_label_before"], certificate["expected_label_after"], certificate["sham_label_after"])):
        require(target["target"]["selected_candidate_semantic_id"].endswith("::" + str(expected)), "contrast selected label differs from certificate")
    require(certificate["affected_query_ids"] == ["q_choice"], "contrast affected-query certificate drifted")
    require(certificate["sham_affected_query_ids"] == [], "sham affected-query certificate drifted")
    require(certificate["sham_unaffected_query_ids"] == ["q_choice"], "sham locality certificate drifted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    materialized = args.run / "materialized"
    training_inputs = args.run / "training-inputs"
    contract_hash = sha256_file(args.contract)
    contract = read_json(args.contract)
    generator = read_json(args.run / "generator-receipt.json")
    scope = read_json(training_inputs / "scope-receipt.json")
    bank_receipt = read_json(materialized / "phase-a-bank-receipt.json")
    integrity = read_json(materialized / "phase-a-integrity-receipt.json")

    require = lambda condition, message: (_ for _ in ()).throw(ValueError(message)) if not condition else None
    require(contract.get("run_identity") == "phase-a-v02-clean", "wrong contract identity")
    require(generator.get("protocol_contract_sha256") == contract_hash, "generator contract hash mismatch")
    require(scope.get("protocol_contract_sha256") == contract_hash, "scope contract hash mismatch")
    require(bank_receipt.get("status") == "PHASE_A_BANKS_BUILT_NO_MODEL_CONTACT", "bank receipt is not a no-model Phase-A pass")
    require(integrity.get("status") == "PASS_NO_MODEL_CONTACT", "integrity receipt is not PASS")
    require(generator.get("train_pairs") == 12_000 and generator.get("eval_pairs") == 2_000, "generator pair counts drifted")
    require(scope.get("source_scope") == "training_only" and scope.get("source_bank") == "R100-star", "wrong training scope")
    require(scope.get("source_row_count") == ARM_SIZE, "scope source count drifted")
    for key in ("contains_eval_ids", "contains_eval_family_ids", "contains_eval_text"):
        require(scope.get(key) is False, f"scope does not certify {key}=false")
    protected = scope["protected_identity_audit"]
    zero_fields = (
        "source_group_id_overlap", "source_episode_id_overlap", "source_root_id_overlap",
        "source_exact_state_text_hash_overlap", "source_schema_surface_hash_overlap",
        "source_model_input_hash_overlap", "source_group_hash_overlap", "source_episode_hash_overlap",
    )
    for key in zero_fields:
        require(protected.get(key) == 0, f"protected overlap is nonzero: {key}")
    require(all(value == 0 for value in protected["source_family_id_overlap_by_field"].values()), "protected family overlap")
    scan = scope["canonical_scan"]
    require(scan.get("protected_eval_episode_bodies_parsed") == 0, "protected eval bodies were parsed")
    require(scan.get("nonselected_record_bodies_json_decoded") == 0, "nonselected archive bodies were decoded")
    require(scan.get("eval_text_materialized") is False, "eval text was materialized")
    require(integrity.get("model_contact") is False and integrity.get("phase_b_authorization") is False, "model/Phase-B boundary crossed")
    require(integrity.get("protected_eval_bodies_opened") is False, "integrity claims protected eval was opened")
    require(integrity.get("generated_eval_bodies_opened") is False, "integrity claims generated eval was opened")

    train_families = set(generator["train_family_ids"])
    eval_families = set(generator["eval_family_ids"])
    train_templates = set(generator["train_template_ids"])
    eval_templates = set(generator["eval_template_ids"])
    train_episode_ids = set(generator["train_episode_ids"])
    eval_episode_ids = set(generator["eval_episode_ids"])
    require(not train_families & eval_families, "train/eval family overlap")
    require(not train_templates & eval_templates, "train/eval template overlap")
    require(not train_episode_ids & eval_episode_ids, "train/eval episode overlap")

    for name, metadata in bank_receipt["files"].items():
        path = materialized / name
        require(sha256_file(path) == metadata, f"bank receipt file hash mismatch: {name}")
        integrity_item = integrity["verified_files"].get(name)
        require(integrity_item and integrity_item.get("verified") is True, f"integrity receipt lacks {name}")

    states = indexed_texts(materialized / "state-inputs.jsonl")
    candidates = indexed_texts(materialized / "candidate-inputs-name_definition.jsonl")
    s = audit_bank(materialized / "S100-groups.jsonl", states, candidates)
    f = audit_bank(materialized / "F100-groups.jsonl", states, candidates)
    signature_l1 = sum(
        abs(s["training_signatures"].get(key, 0) - f["training_signatures"].get(key, 0))
        for key in s["training_signatures"].keys() | f["training_signatures"].keys()
    )
    distance = signature_l1 / (2 * ARM_SIZE)
    require(s["unique_states"] == f["unique_states"], "unique state count differs")
    profile_equal = {
        "family_marginals": all(counter_equal(s["families"][key], f["families"][key]) for key in FAMILY_FIELDS),
        "root_counts": counter_equal(s["root_occurrences"], f["root_occurrences"]),
        "view_counts": counter_equal(s["views"], f["views"]),
        "candidate_cardinality": counter_equal(s["cardinality"], f["cardinality"]),
        "root_multiplicity": counter_equal(s["root_multiplicity"], f["root_multiplicity"]),
        "state_multiplicity": counter_equal(s["state_multiplicity"], f["state_multiplicity"]),
        "selector_input_multiplicity": counter_equal(s["selector_multiplicity"], f["selector_multiplicity"]),
    }
    require(all(profile_equal.values()), "independent bank profile mismatch")

    certs = list(rows(materialized / "selected-train-contrast-certificates.jsonl"))
    require(len(certs) == 5_000, "selected contrast count drifted")
    wanted_episode_ids = {
        str(episode_id)
        for cert in certs
        for episode_id in cert["episode_ids"].values()
    }
    selected_episodes: dict[str, dict[str, Any]] = {}
    train_canonical = args.run / "train-canonical-episodes.jsonl"
    for episode in rows(train_canonical):
        episode_id = str(episode.get("episode_id", ""))
        if episode_id in wanted_episode_ids:
            if episode_id in selected_episodes:
                raise ValueError(f"duplicate selected train episode: {episode_id}")
            selected_episodes[episode_id] = episode
    require(set(selected_episodes) == wanted_episode_ids, "selected train canonical episode coverage mismatch")
    for cert in certs:
        validate_contrast_triplet(cert, selected_episodes)
    s_custom_episodes = {str(cert["episode_ids"][role]) for cert in certs for role in ("anchor", "sham")}
    f_custom_episodes = {str(cert["episode_ids"][role]) for cert in certs for role in ("anchor", "fact_flip")}
    selected_train_episodes = s_custom_episodes | f_custom_episodes
    require(selected_train_episodes <= train_episode_ids, "selected contrast episode is outside train partition")
    require(not selected_train_episodes & eval_episode_ids, "selected contrast overlaps eval episode IDs")

    s_ids, f_ids = set(s["ids"]), set(f["ids"])
    common_ids = s_ids & f_ids
    require(s_ids == f_ids and len(common_ids) == ARM_SIZE, "aligned group-slot IDs differ")
    row_content_changes = {
        group_id for group_id in common_ids
        if s["ids"][group_id]["row_digest"] != f["ids"][group_id]["row_digest"]
    }
    require(len(row_content_changes) == 5_000, "changed sibling-slot count differs")
    common_skeleton_ids = {
        group_id for group_id in common_ids
        if s["ids"][group_id]["episode_id"] not in selected_train_episodes
    }
    require(len(common_skeleton_ids) == 90_000, "common skeleton group count differs")
    common_rows_equal = all(s["ids"][key]["row_digest"] == f["ids"][key]["row_digest"] for key in common_skeleton_ids)
    require(common_rows_equal, "common skeleton row contents differ")
    s_custom_rows = sum(value["episode_id"] in s_custom_episodes for value in s["ids"].values())
    f_custom_rows = sum(value["episode_id"] in f_custom_episodes for value in f["ids"].values())
    require(s_custom_rows == 10_000 and f_custom_rows == 10_000, "custom occurrence count differs")
    s_episode_only = s["episodes"] - f["episodes"]
    f_episode_only = f["episodes"] - s["episodes"]
    require(len(s_episode_only) == 5_000 and len(f_episode_only) == 5_000, "arm-specific episode turnover differs")
    require(not (s["episodes"] | f["episodes"]) & eval_episode_ids, "bank episode overlaps generated eval IDs")

    expected_distance = bank_receipt["banks"]["exact_training_signature_distance"]["D_train"]
    require(abs(distance - expected_distance) < 1e-12, "independent D_train differs from bank receipt")
    require(abs(distance - 0.05) < 1e-12, "D_train differs from frozen target")
    require(bank_receipt["banks"]["common_skeleton_groups"] == 90_000, "receipt common skeleton drifted")
    require(bank_receipt["banks"]["groups_per_arm"] == ARM_SIZE, "receipt bank size drifted")

    result = {
        "audit": "independent-phase-a-v02-bank-and-boundary-audit",
        "status": "PASS_NO_MODEL_CONTACT",
        "run_identity": "phase-a-v02-clean",
        "contract_sha256": contract_hash,
        "independent_bank_recomputation": {
            "S100_groups": s["count"], "F100_groups": f["count"],
            "S100_unique_signatures": len(s["training_signatures"]),
            "F100_unique_signatures": len(f["training_signatures"]),
            "signature_l1": signature_l1, "D_train": distance,
            "common_group_id_count": len(common_ids),
            "common_skeleton_count": len(common_skeleton_ids),
            "common_skeleton_rows_equal": common_rows_equal,
            "aligned_group_slot_ids": ARM_SIZE,
            "content_changed_slots": len(row_content_changes),
            "custom_occurrences_each": {"S100": s_custom_rows, "F100": f_custom_rows},
            "arm_specific_episode_ids_each": 5_000,
            "unique_states_each": s["unique_states"],
            "profile_equal": profile_equal,
        },
        "independent_contrast_semantics": {
            "selected_pairs": len(certs),
            "selected_train_episodes_validated": len(selected_episodes),
            "relevant_fact_flip_changes_winner": True,
            "sham_preserves_exact_posterior_and_winner": True,
            "eval_episode_bodies_opened": False,
        },
        "family_partition": {
            "train_families": len(train_families), "eval_families": len(eval_families),
            "train_templates": len(train_templates), "eval_templates": len(eval_templates),
            "train_episodes": len(train_episode_ids), "eval_episodes": len(eval_episode_ids),
            "all_disjoint": True,
        },
        "protected_boundary": {
            "scope_status": scope["status"],
            "all_overlap_counters_zero": True,
            "eval_episode_bodies_parsed": scan["protected_eval_episode_bodies_parsed"],
            "nonselected_bodies_decoded": scan["nonselected_record_bodies_json_decoded"],
            "eval_text_materialized": scan["eval_text_materialized"],
            "assembler_generated_eval_bodies_opened": integrity["generated_eval_bodies_opened"],
            "model_contact": False, "phoenix_access": False, "phase_b_authorized": False,
        },
    }
    output = materialized / "phase-a-v02-independent-audit.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"status": result["status"], "D_train": distance, "output": str(output)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
