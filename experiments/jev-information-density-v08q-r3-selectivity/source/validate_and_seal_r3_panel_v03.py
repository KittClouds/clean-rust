"""Validate R3 panel construction and seal inference/target joins separately."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v03")
PANEL = RUN / "panel-v03"
EXCLUSION_DIR = RUN / "identity-exclusions-v02"
EXCLUSIONS = EXCLUSION_DIR / "field-exclusion-domain-hashes.json"
EXCLUSION_RECEIPT = EXCLUSION_DIR / "exclusion-receipt.json"
EXCLUSION_ROOT = EXCLUSION_DIR / "root-seal.json"
EXPECTED_EXCLUSION_SHA = "e206a995582cd47a50f5b6c6411f8660fafd985ab80a1620f4db4caed0066ac3"
EXPECTED_EXCLUSION_ROOT = "89dab4a60209a7f5a11205926ed4839377923d534f1275d69e53c90bd5e32f47"
PARTITION = "eval_v08q_r3_confirmatory_v03"
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
FIELDS = ("world_id", "root_id", "episode_id", "full_rendered_input_hash", "selector_input_hash")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl_new(path: Path, values: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def need(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def argmax_first(values: list[float]) -> int:
    return max(range(len(values)), key=lambda index: (values[index], -index))


def domain_digest(field: str, value: str) -> str:
    return sha_bytes(f"jev-v08q-exclusion-v01:{field}:{value}".encode("utf-8"))


def verify_exclusion_root() -> tuple[dict[str, Any], dict[str, set[str]]]:
    need(sha_file(EXCLUSIONS) == EXPECTED_EXCLUSION_SHA, "R3 exclusion payload hash mismatch")
    payload, receipt, root = read_json(EXCLUSIONS), read_json(EXCLUSION_RECEIPT), read_json(EXCLUSION_ROOT)
    need(payload["schema"] == "jev-v08q-r3-field-exclusion-domain-hash-sets-v02", "R3 exclusion schema mismatch")
    need(receipt["payload_sha256"] == EXPECTED_EXCLUSION_SHA, "R3 exclusion receipt binding mismatch")
    entries = (EXCLUSIONS, EXCLUSION_RECEIPT)
    body = "".join(f"{path.name}\t{path.stat().st_size}\t{sha_file(path)}\n" for path in entries)
    computed = sha_bytes(body.encode("utf-8"))
    need(root["entry_count"] == 2 and root["entries_root_sha256"] == computed == EXPECTED_EXCLUSION_ROOT,
         "R3 exclusion root mismatch")
    fields = {field: set(payload["fields"][field]) for field in FIELDS}
    need(all(fields[field] and len(fields[field]) == len(payload["fields"][field]) for field in FIELDS),
         "R3 exclusion digest set empty or duplicated")
    need(all(len(value) == 64 for values in fields.values() for value in values), "malformed exclusion digest")
    e1 = set(payload["e1_neighborhood_hashes"])
    need(len(e1) == 2_000 and all(len(value) == 64 for value in e1), "E1 ID denylist invalid")
    return payload, fields


def main() -> int:
    panel_path = PANEL / "r3-panel-views.jsonl"
    candidate_path = PANEL / "candidate-texts.jsonl"
    admission_path = PANEL / "candidate-admission-receipts.jsonl"
    generation_path = PANEL / "panel-generation-receipt.json"
    for path in (panel_path, candidate_path, admission_path, generation_path):
        need(path.is_file(), f"generated panel artifact missing: {path.name}")
    need(not (PANEL / "seals" / "r3-panel-seal-v01.json").exists(), "panel already has a seal; refusing mutation")
    payload, external = verify_exclusion_root()
    receipt = read_json(generation_path)
    need(receipt.get("status") == "R3_V03_CONFIRMATORY_PANEL_GENERATED_FIELDWISE_ADMISSION_PASS", "panel generation not PASS")
    need(receipt.get("partition") == PARTITION and receipt.get("field_exclusion_sha256") == EXPECTED_EXCLUSION_SHA,
         "panel generator identity/exclusion binding mismatch")
    need(receipt.get("neighborhoods") == 2_000 and receipt.get("view_rows") == 4_000, "panel generator count mismatch")
    need(receipt.get("head_loaded") is False and receipt.get("features_extracted") is False
         and receipt.get("training") is False and receipt.get("evaluation") is False,
         "panel generator crossed model boundary")

    candidates = read_jsonl(candidate_path)
    need(len(candidates) == 16, "candidate catalog count mismatch")
    candidate_ids: dict[str, list[str]] = {}
    for family in FAMILIES:
        rows = [row for row in candidates if row.get("family_slug") == family]
        rows.sort(key=lambda row: row["candidate_order"])
        need(len(rows) == 4 and [row["candidate_order"] for row in rows] == list(range(4)),
             f"candidate semantic basis incomplete: {family}")
        for row in rows:
            need(sha_bytes(row["text"].encode("utf-8")) == row["text_sha256"], "candidate text hash mismatch")
        candidate_ids[family] = [row["candidate_semantic_id"] for row in rows]
        need(len(set(candidate_ids[family])) == 4, f"candidate IDs duplicate: {family}")

    rows = read_jsonl(panel_path)
    admission = read_jsonl(admission_path)
    need(len(rows) == 4_000, "panel row count mismatch")
    need(len(admission) <= 4 * 800 and len(admission) >= 2_000, "candidate admission record count out of bounds")
    need(receipt.get("candidate_stream_rows") == len(admission), "candidate stream receipt row count mismatch")
    stream_cursor = 0
    for family_index, family in enumerate(FAMILIES):
        family_rows = [row for row in admission if row.get("family_slug") == family]
        local_ordinals = [int(row["candidate_ordinal"]) for row in family_rows]
        need(local_ordinals == list(range(len(family_rows))), f"candidate stream ordinal gap/reordering: {family}")
        need(all(int(row.get("family_candidate_ordinal", -1)) == int(row["candidate_ordinal"])
            and int(row.get("stream_ordinal", -1)) == family_index * 800 + int(row["candidate_ordinal"])
            for row in family_rows), f"candidate stream ordinal binding mismatch: {family}")
        stream_cursor += len(family_rows)
    need(stream_cursor == len(admission), "unknown family in admission stream")
    need(sum(bool(row["accepted"]) for row in admission) == 2_000, "online accepted count mismatch")
    need(sum(row.get("status") == "rejected_identity_collision" for row in admission)
        == receipt["candidate_rejections"], "online collision rejection count mismatch")
    need(sum(row.get("status") == "skipped_direction_quota_full" for row in admission)
        == receipt.get("candidate_quota_skips"), "online quota skip count mismatch")
    need(all(row.get("status") in ("admitted", "rejected_identity_collision", "skipped_direction_quota_full")
        for row in admission), "unknown candidate admission status")
    need(all(bool(row.get("evaluated_candidate")) == (row["status"] != "skipped_direction_quota_full")
        for row in admission), "candidate evaluated-status mismatch")

    groups: dict[str, list[dict[str, Any]]] = {}
    field_values: dict[str, dict[str, str]] = {field: {} for field in FIELDS}
    internal_unique: dict[str, set[str]] = {field: set() for field in FIELDS}
    family_direction: dict[tuple[str, str], set[str]] = {}
    target_records: list[dict[str, Any]] = []
    feature_text_records: list[dict[str, Any]] = []
    inference_records: list[dict[str, Any]] = []
    rendered: set[str] = set()
    e1_ids = set(payload["e1_neighborhood_hashes"])
    world_owner: dict[str, str] = {}
    root_owner: dict[str, str] = {}
    for row_index, row in enumerate(rows):
        need(row.get("family_slug") in FAMILIES and row.get("direction") in ("high_to_low", "low_to_high"),
             "unknown panel family/direction")
        need(row.get("view") in ("anchor", "fact"), "unknown panel view")
        family = row["family_slug"]
        ids = row["candidate_semantic_ids"]
        need(ids == candidate_ids[family], "candidate semantic order differs from sealed candidate catalog")
        old_slot, new_slot = (0, 1) if row["direction"] == "high_to_low" else (1, 0)
        need(row["old_semantic_id"] == ids[old_slot] and row["new_semantic_id"] == ids[new_slot],
             "semantic roles do not follow the declared polarity transition")
        need(sha_bytes(row["text"].encode("utf-8")) == row["full_rendered_input_hash"], "model-visible text hash mismatch")
        need(row["full_rendered_input_hash"] not in rendered, "duplicate model-visible row inside R3 panel")
        rendered.add(row["full_rendered_input_hash"])
        target = row["target"]
        need(len(target) == 4 and all(math.isfinite(float(value)) for value in target), "invalid panel target vector")
        need(abs(sum(float(value) for value in target) - 1.0) <= 1e-10, "panel target does not sum to one")
        expected_winner = old_slot if row["view"] == "anchor" else new_slot
        need(argmax_first([float(value) for value in target]) == expected_winner,
             "exact generator target violates semantic role")

        identity_key = row["neighborhood_id"]
        groups.setdefault(identity_key, []).append(row)
        family_direction.setdefault((family, row["direction"]), set()).add(identity_key)
        for field in FIELDS:
            value = str(row[field])
            digest = domain_digest(field, value)
            need(digest not in external[field], f"panel identity collision with sealed exclusion set: {field}")
            if field in ("world_id", "root_id"):
                previous = field_values[field].setdefault(identity_key, value)
                need(previous == value, f"within-neighborhood {field} changed across views")
                owners = world_owner if field == "world_id" else root_owner
                owner = owners.setdefault(value, identity_key)
                need(owner == identity_key, f"internal cross-neighborhood {field} collision")
            else:
                need(value not in internal_unique[field], f"internal R3 duplicate {field}")
                internal_unique[field].add(value)
        need(sha_bytes(identity_key.encode("utf-8")) not in e1_ids,
             "E1 neighborhood ID collision")
        inference_records.append({
            "row_index": row_index,
            "neighborhood_id": identity_key,
            "family_slug": family,
            "direction": row["direction"],
            "view": row["view"],
            "old_semantic_id": row["old_semantic_id"],
            "new_semantic_id": row["new_semantic_id"],
            "candidate_semantic_ids": ids,
            "world_id": row["world_id"], "root_id": row["root_id"], "episode_id": row["episode_id"],
            "selector_input_hash": row["selector_input_hash"],
            "full_rendered_input_hash": row["full_rendered_input_hash"],
        })
        feature_text_records.append({"row_index": row_index,
            "full_rendered_input_hash": row["full_rendered_input_hash"], "text": row["text"]})
        target_records.append({"row_index": row_index, "neighborhood_id": identity_key,
            "family_slug": family, "direction": row["direction"], "view": row["view"],
            "candidate_semantic_ids": ids, "target": target})

    need(len(groups) == 2_000 and len(rendered) == 4_000, "neighborhood/rendered identity cardinality mismatch")
    for neighborhood, group in groups.items():
        need(len(group) == 2 and {row["view"] for row in group} == {"anchor", "fact"},
             f"anchor/fact pair invalid: {neighborhood}")
        anchor = next(row for row in group if row["view"] == "anchor")
        fact = next(row for row in group if row["view"] == "fact")
        need(anchor["family_slug"] == fact["family_slug"] and anchor["direction"] == fact["direction"],
             "paired views disagree on family/direction")
        need(anchor["candidate_semantic_ids"] == fact["candidate_semantic_ids"], "paired candidate order changed")
        need(anchor["old_semantic_id"] == fact["old_semantic_id"] and anchor["new_semantic_id"] == fact["new_semantic_id"],
             "paired semantic role identity changed")
        need(anchor["world_id"] == fact["world_id"] and anchor["root_id"] == fact["root_id"],
             "paired view world/root identity mismatch")
    for family in FAMILIES:
        for direction in ("high_to_low", "low_to_high"):
            need(len(family_direction.get((family, direction), set())) == 250,
                 f"family/polarity neighborhood allocation mismatch: {family}/{direction}")

    inference_path = PANEL / "r3-panel-inference-manifest.jsonl"
    feature_text_path = PANEL / "r3-panel-texts-target-free-v01.jsonl"
    targets_path = PANEL / "r3-panel-targets-v01.jsonl"
    report_path = PANEL / "panel-validation-report.json"
    write_jsonl_new(inference_path, inference_records)
    write_jsonl_new(feature_text_path, feature_text_records)
    write_jsonl_new(targets_path, target_records)
    report = {
        "status": "R3_V03_PANEL_VALIDATION_PASS",
        "panel_generation_receipt_sha256": sha_file(generation_path),
        "exclusion_payload_sha256": EXPECTED_EXCLUSION_SHA,
        "exclusion_root_sha256": EXPECTED_EXCLUSION_ROOT,
        "neighborhoods": len(groups), "view_rows": len(rows), "candidate_texts": len(candidates),
        "family_direction_neighborhood_counts": {f"{family}/{direction}": len(family_direction[(family, direction)])
            for family in FAMILIES for direction in ("high_to_low", "low_to_high")},
        "unique_model_visible_rows": len(rendered),
        "fieldwise_external_collision_counts": {field: 0 for field in FIELDS},
        "e1_neighborhood_id_collisions": 0,
        "all_anchor_targets_select_old_role": True,
        "all_fact_targets_select_new_role": True,
        "target_access": "construction-only exact generative targets; no head, prediction, or metric was read",
        "head_loaded": False, "feature_extraction": False, "training": False, "inference": False,
    }
    write_json(report_path, report)
    seal_dir = PANEL / "seals"
    seal_dir.mkdir(exist_ok=False)
    entries = [
        "candidate-texts.jsonl", "candidate-admission-receipts.jsonl", "panel-generation-receipt.json",
        "r3-panel-views.jsonl", "r3-panel-inference-manifest.jsonl", "r3-panel-texts-target-free-v01.jsonl",
        "r3-panel-targets-v01.jsonl",
        "panel-validation-report.json",
    ]
    entry_rows = [{"path": name, "bytes": (PANEL / name).stat().st_size, "sha256": sha_file(PANEL / name)}
                  for name in entries]
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in sorted(entry_rows, key=lambda item: item["path"]))
    seal = {
        "schema": "jev-r3-panel-seal-v01", "status": "R3_V03_PANEL_SEALED_FEATURE_EXTRACTION_PENDING",
        "identity": "JEV-V08Q-R3-SELECTIVITY-V03-PANEL", "entries": entry_rows,
        "entry_count": len(entry_rows), "entries_root_sha256": sha_bytes(body.encode("utf-8")),
        "inference_manifest_sha256": sha_file(inference_path), "target_join_sha256": sha_file(targets_path),
        "target_free_texts_sha256": sha_file(feature_text_path),
        "exclusion_payload_sha256": EXPECTED_EXCLUSION_SHA, "exclusion_root_sha256": EXPECTED_EXCLUSION_ROOT,
        "head_initialization": False, "feature_extraction": False, "training": False,
        "head_inference": False, "treatment_metrics": False,
    }
    seal_path = seal_dir / "r3-panel-seal-v01.json"
    write_json(seal_path, seal)
    print(json.dumps({"status": report["status"], "panel_seal_sha256": sha_file(seal_path),
        "panel_root_sha256": seal["entries_root_sha256"], "neighborhoods": len(groups),
        "rows": len(rows), "rejected_candidates": receipt["candidate_rejections"],
        "fieldwise_collisions": 0, "targets_read_for_construction_validation": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
