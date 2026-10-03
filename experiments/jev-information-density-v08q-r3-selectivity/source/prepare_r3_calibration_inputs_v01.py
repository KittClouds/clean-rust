"""Validate the fresh calibration panel and build balanced R3 training sidecars."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02")
PANEL = RUN / "calibration-panel-v02"
OUT = RUN / "calibration-inputs-v03"
BASE = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01")
Q_PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\panel-v01")

EXPECTED = {
    "run_contract": "52d093a00076700ed24bfe0e2cc33ada73dfc07d073b39cbdbe52103aef525e6",
    "panel_contract": "a835b3d2934265b8f64ebd287e4dbf48f80ffe9bbbfcc1d6ed2650da69f63153",
    "primary": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
    "sham": "9dd346766856f56006be326c171e664dcbab23983cdd7501f480b6fabb6ff895",
    "scope": "aa8cba58f4a8ec46ed6ec8eaf0bfbe992b03b9fa58f815b4259d9fdfe2b009f3",
    "exclusions": "47155233c933f28f6b122b6350cc7c11e6e77e71c13883f9958c203be8bb0f19",
    "q2_identity_rows": "f05b8e65ef867a361f7cd531f1512f0934e01dae88e8385545467e9ac70914c1",
    "q2_panel_seal": "a674c43526f1623f8e201e3ac3b1b92f365ee275a3878b805b81ac6d173c77bf",
    "state_features": "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6",
    "candidate_features": "3bb3036f455a83409361eb3e4150833bd8b255a2a783ec1218b00b12315c0590",
    "candidate_catalog": "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e",
}
FAMILY_ORDER = [
    "chemical_concentration",
    "dosage_safety",
    "flow_management",
    "humidity_control",
    "inventory_control",
    "liquid_level",
    "load_management",
    "power_quality",
    "pressure_control",
    "rotational_speed",
    "thermal_control",
    "torque_control",
]
EVAL_FAMILIES = [
    "exposure_control",
    "respiratory_monitoring",
    "salinity_control",
    "vibration_monitoring",
]


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def verify_file(path: Path, expected: str, label: str) -> None:
    require(path.is_file(), f"missing bound source: {label}")
    require(sha_file(path) == expected, f"bound source hash mismatch: {label}")


def argmax_first(values: list[float]) -> int:
    return max(range(len(values)), key=lambda index: (values[index], -index))


def domain_digest(field: str, value: str) -> str:
    return sha_bytes(f"jev-v08q-exclusion-v01:{field}:{value}".encode("utf-8"))


def verify_calibration_panel() -> dict[str, Any]:
    view_path = PANEL / "calibration-panel-views.jsonl"
    candidate_path = PANEL / "candidate-texts.jsonl"
    require(view_path.is_file() and candidate_path.is_file(), "calibration panel generator output absent")
    rows = read_jsonl(view_path)
    candidates = read_jsonl(candidate_path)
    require(len(rows) == 4_000 and len(candidates) == 16, "calibration panel cardinality mismatch")
    require([row["family_slug"] for row in candidates[::4]] == EVAL_FAMILIES,
            "candidate family order mismatch")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    family_direction: Counter[tuple[str, str]] = Counter()
    all_hashes: set[str] = set()
    for row in rows:
        actual_hash = sha_bytes(row["text"].encode("utf-8"))
        require(actual_hash == row["full_rendered_input_hash"], "panel text hash mismatch")
        require(actual_hash not in all_hashes, "duplicate model-visible row within calibration panel")
        all_hashes.add(actual_hash)
        family_direction[(row["family_slug"], row["direction"])] += 1
        require(row["family_slug"] in EVAL_FAMILIES, "unexpected panel family")
        require(row["direction"] in {"high_to_low", "low_to_high"}, "unexpected polarity")
        groups[row["neighborhood_id"]].append(row)

    require(len(groups) == 2_000, "calibration neighborhood count mismatch")
    require(all(len(group) == 2 for group in groups.values()), "each calibration neighborhood needs anchor/fact")
    for family in EVAL_FAMILIES:
        require(family_direction[(family, "high_to_low")] == 500, f"high-to-low row balance failed: {family}")
        require(family_direction[(family, "low_to_high")] == 500, f"low-to-high row balance failed: {family}")
    for group in groups.values():
        by_view = {row["view"]: row for row in group}
        require(set(by_view) == {"anchor", "fact"}, "view identity mismatch")
        anchor, fact = by_view["anchor"], by_view["fact"]
        require(anchor["direction"] == fact["direction"], "paired views disagree on direction")
        require(anchor["old_semantic_id"] == fact["old_semantic_id"]
                and anchor["new_semantic_id"] == fact["new_semantic_id"], "paired semantic roles disagree")
        old_index = anchor["candidate_semantic_ids"].index(anchor["old_semantic_id"])
        new_index = fact["candidate_semantic_ids"].index(fact["new_semantic_id"])
        require(argmax_first(anchor["target"]) == old_index, "anchor exact target violates old role")
        require(argmax_first(fact["target"]) == new_index, "fact exact target violates new role")

    exclusions_path = Q_PANEL / "exclusions/five-field-exclusion-sets.json"
    identities_path = Q_PANEL / "panel/panel-occurrence-identities.jsonl"
    seal_path = Q_PANEL / "seals/q-r2-panel-construction-seal-v01.json"
    verify_file(exclusions_path, EXPECTED["exclusions"], "sealed five-field exclusion set")
    verify_file(identities_path, EXPECTED["q2_identity_rows"], "Q-R2 occurrence identity rows")
    verify_file(seal_path, EXPECTED["q2_panel_seal"], "Q-R2 panel construction seal")
    seal = read_json(seal_path)
    entry = next((e for e in seal["entries"] if e["path"] == "panel/panel-occurrence-identities.jsonl"), None)
    require(entry is not None and entry["sha256"] == EXPECTED["q2_identity_rows"],
            "Q-R2 seal does not bind the authorized identity manifest")

    exclusions = read_json(exclusions_path)
    old_text_digests = set(exclusions["training"]["full_rendered_input_hash"])
    old_text_digests.update(exclusions["prior_panel"]["full_rendered_input_hash"])
    old_rows = read_jsonl(identities_path)
    require(len(old_rows) == 22_000, "Q-R2 identity source row count mismatch")
    q2_text_hashes = {row["full_rendered_input_hash"] for row in old_rows}
    training_scope_path = BASE / "shared-feature-cache/training-only-feature-scope.jsonl"
    verify_file(training_scope_path, EXPECTED["scope"], "training feature-scope manifest")
    training_text_hashes = {row["input_sha256"] for row in read_jsonl(training_scope_path)}

    prior_collision = 0
    training_collision = 0
    q2_collision = 0
    for row in rows:
        raw_hash = row["full_rendered_input_hash"]
        collision_digest = domain_digest("full_rendered_input_hash", raw_hash)
        prior_collision += collision_digest in old_text_digests
        training_collision += raw_hash in training_text_hashes or collision_digest in old_text_digests
        q2_collision += raw_hash in q2_text_hashes
    require(prior_collision == 0 and training_collision == 0 and q2_collision == 0,
            "fresh calibration panel collides with training/prior model-visible inputs")

    return {
        "status": "R3_CALIBRATION_PANEL_POLARITY_AND_FRESHNESS_PASS",
        "neighborhoods": len(groups),
        "view_rows": len(rows),
        "candidate_texts": len(candidates),
        "family_direction_counts": {
            f"{family}/{direction}": family_direction[(family, direction)]
            for family in EVAL_FAMILIES
            for direction in ("high_to_low", "low_to_high")
        },
        "unique_model_visible_hashes": len(all_hashes),
        "training_scope_rows": len(training_text_hashes),
        "prior_exclusion_source_sha256": EXPECTED["exclusions"],
        "q2_identity_source_sha256": EXPECTED["q2_identity_rows"],
        "collision_counts": {
            "training_and_prior_exclusion_set": prior_collision,
            "training_feature_scope": training_collision,
            "Q_R2_panel": q2_collision,
        },
        "target_use": "construction validation only; no head outputs or treatment metrics",
    }


def build_balanced_training_sidecars() -> dict[str, Any]:
    primary_path = BASE / "phase-b-v03-inputs/common-primary-occurrence-manifest.jsonl"
    sham_path = BASE / "phase-b-v03-inputs/head-input-manifest-B-SHAM.jsonl"
    scope_path = BASE / "shared-feature-cache/training-only-feature-scope.jsonl"
    catalog_path = BASE / "phase-b-v03-inputs/candidate-catalog.json"
    verify_file(primary_path, EXPECTED["primary"], "training primary occurrences")
    verify_file(sham_path, EXPECTED["sham"], "training SHAM event stream")
    verify_file(scope_path, EXPECTED["scope"], "training-only feature scope")
    verify_file(catalog_path, EXPECTED["candidate_catalog"], "training candidate catalog")

    primary_source = read_jsonl(primary_path)
    sham_source = read_jsonl(sham_path)
    scope = read_jsonl(scope_path)
    catalog = read_json(catalog_path)
    require(len(primary_source) == 10_000 and len(sham_source) == 15_000 and len(scope) == 55_000,
            "bound training source row count mismatch")
    scope_by_episode = {row["episode_id"]: row for row in scope}
    require(len(scope_by_episode) == len(scope), "duplicate training episode identity")
    event_by_episode = {row["source_episode_id"]: row for row in sham_source}
    require(len(event_by_episode) == 15_000, "duplicate training event identity")
    catalog_ids = [str(row["candidate_semantic_id"]) for row in catalog["rows"]]
    require(len(catalog_ids) == 48 and len(set(catalog_ids)) == 48 and catalog.get("feature_dimension") == 2048,
            "training candidate catalog schema mismatch")
    catalog_index = {semantic_id: index for index, semantic_id in enumerate(catalog_ids)}

    pairs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in primary_source:
        pairs[row["neighborhood_id"]][row["role"]] = row
    require(len(pairs) == 5_000 and all(set(v) == {"anchor", "fact_flip"} for v in pairs.values()),
            "training neighborhoods are not exact anchor/fact pairs")

    by_family: dict[str, list[str]] = defaultdict(list)
    for neighborhood, pair in pairs.items():
        ids = pair["anchor"]["candidate_semantic_ids"]
        family = ids[0].split("::", 1)[0]
        require(ids == pair["fact_flip"]["candidate_semantic_ids"], "candidate order changed within training pair")
        by_family[family].append(neighborhood)
    require(set(by_family) == set(FAMILY_ORDER), "training family set mismatch")

    # Pseudorandomly spread the two orientations within family while keeping
    # exactly 2,500 groups in each direction and family imbalance at most one.
    sorted_families = sorted(by_family)
    odd_families = [family for family in sorted_families if len(by_family[family]) % 2]
    high_extra = set(odd_families[: len(odd_families) // 2])
    direction_by_neighborhood: dict[str, str] = {}
    family_counts: dict[str, dict[str, int]] = {}
    for family in sorted_families:
        keys = sorted(
            by_family[family],
            key=lambda neighborhood: sha_bytes(f"r3-train-direction-v01/{family}/{neighborhood}".encode()),
        )
        high_n = (len(keys) + 1) // 2 if family in high_extra else len(keys) // 2
        for index, neighborhood in enumerate(keys):
            direction_by_neighborhood[neighborhood] = "high_to_low" if index < high_n else "low_to_high"
        family_counts[family] = {
            "high_to_low": high_n,
            "low_to_high": len(keys) - high_n,
            "groups": len(keys),
        }

    primary_rows: list[dict[str, Any]] = []
    auxiliary_rows: list[dict[str, Any]] = []
    reverse_texts: list[dict[str, Any]] = []
    extra_index = len(scope)
    for neighborhood in sorted(pairs):
        pair = pairs[neighborhood]
        family = pair["anchor"]["candidate_semantic_ids"][0].split("::", 1)[0]
        direction = direction_by_neighborhood[neighborhood]
        high = pair["anchor"]
        low = pair["fact_flip"]
        if direction == "high_to_low":
            anchor_source, fact_source = high, low
            old_index, new_index = 0, 1
            auxiliary_source = event_by_episode[neighborhood + "-sham"]
            aux_feature_index = int(auxiliary_source["feature_scope_index"])
            aux_target = list(auxiliary_source["target"])
            aux_source_id = auxiliary_source["source_episode_id"]
            aux_hash = scope_by_episode[aux_source_id]["input_sha256"]
        else:
            anchor_source, fact_source = low, high
            old_index, new_index = 1, 0
            low_row = scope_by_episode[low["episode_id"]]
            source_text = low_row["text"]
            marker = "Independent panel marker: +."
            require(source_text.count(marker) == 1, "low-pole training row cannot be sham-edited uniquely")
            low_sham_text = source_text.replace(marker, "Independent panel marker: -.", 1)
            aux_feature_index = extra_index
            extra_index += 1
            aux_target = list(event_by_episode[low["episode_id"]]["target"])
            aux_source_id = f"r3-low-sham:{low['episode_id']}"
            aux_hash = sha_bytes(low_sham_text.encode("utf-8"))
            reverse_texts.append({
                "feature_scope_index": aux_feature_index,
                "neighborhood_id": neighborhood,
                "family_slug": family,
                "source_anchor_episode_id": low["episode_id"],
                "text": low_sham_text,
                "input_sha256": aux_hash,
            })

        candidate_ids = list(anchor_source["candidate_semantic_ids"])
        require(candidate_ids == list(fact_source["candidate_semantic_ids"]), "paired candidate order mismatch")
        require(all(candidate_id in catalog_index for candidate_id in candidate_ids),
                "training candidate identity absent from sealed 48-row catalog")
        global_candidate_indices = [catalog_index[candidate_id] for candidate_id in candidate_ids]
        old_id, new_id = candidate_ids[old_index], candidate_ids[new_index]
        for role, source, expected_winner in (
            ("anchor", anchor_source, old_index),
            ("fact_flip", fact_source, new_index),
        ):
            event = event_by_episode[source["episode_id"]]
            target = list(event["target"])
            require(argmax_first(target) == expected_winner, "training target violates prospective semantic role")
            idx = len(primary_rows)
            primary_rows.append({
                "occurrence_index": idx,
                "group_id": f"{neighborhood}::{role}",
                "neighborhood_id": neighborhood,
                "family_slug": family,
                "direction": direction,
                "role": role,
                "episode_id": source["episode_id"],
                "source_episode_id": source["episode_id"],
                "feature_scope_index": int(source["feature_scope_index"]),
                "input_sha256": source["input_sha256"],
                "old_semantic_id": old_id,
                "new_semantic_id": new_id,
                "candidate_semantic_ids": candidate_ids,
                "candidate_indices": global_candidate_indices,
                "target": target,
                "target_hash": source["target_hash"],
                "kind": "choice",
                "probability_source": "exact_generative_posterior",
            })

        anchor_target = list(event_by_episode[anchor_source["episode_id"]]["target"])
        require(aux_target == anchor_target, "orientation-specific SHAM target differs from its anchor")
        auxiliary_rows.append({
            "event_index": len(auxiliary_rows),
            "group_id": f"{neighborhood}::anchor",
            "neighborhood_id": neighborhood,
            "family_slug": family,
            "direction": direction,
            "source_episode_id": aux_source_id,
            "feature_scope_index": aux_feature_index,
            "input_sha256": aux_hash,
            "old_semantic_id": old_id,
            "new_semantic_id": new_id,
            "candidate_semantic_ids": candidate_ids,
            "candidate_indices": global_candidate_indices,
            "target": aux_target,
            "target_hash": sha_bytes(json.dumps(aux_target, separators=(",", ":")).encode()),
            "kind": "choice",
            "probability_source": "exact_generative_posterior",
            "event_kind": "auxiliary",
            "loss_weight": 1.0,
        })

    require(len(primary_rows) == 10_000 and len(auxiliary_rows) == 5_000,
            "balanced training stream count mismatch")
    require(len(reverse_texts) == 2_500 and extra_index == len(scope) + 2_500,
            "low-pole SHAM materialization count mismatch")
    total_high = sum(row["high_to_low"] for row in family_counts.values())
    total_low = sum(row["low_to_high"] for row in family_counts.values())
    require(total_high == total_low == 2_500, "training polarity is not exactly balanced overall")
    for family, counts in family_counts.items():
        require(abs(counts["high_to_low"] - counts["low_to_high"]) <= 1,
                f"per-family training polarity imbalance exceeds one: {family}")
    write_jsonl(OUT / "balanced-primary-occurrences.jsonl", primary_rows)
    write_jsonl(OUT / "balanced-sham-events.jsonl", auxiliary_rows)
    write_jsonl(OUT / "reverse-sham-texts.jsonl", reverse_texts)
    return {
        "primary_rows": len(primary_rows),
        "paired_neighborhoods": len(pairs),
        "auxiliary_sham_rows": len(auxiliary_rows),
        "reverse_sham_feature_rows": len(reverse_texts),
        "family_direction_counts": family_counts,
        "overall_direction_counts": {"high_to_low": total_high, "low_to_high": total_low},
        "low_sham_target_source": "exact low-pole anchor target; nuisance marker toggled; validated by exact solver for all families/profiles",
    }


def main() -> int:
    require(not OUT.exists(), f"refusing pre-existing calibration inputs: {OUT}")
    run_contract = ROOT / "experiments/jev-information-density-v08q-r2-late-branch/contracts/q-r2-run-contract-v01.json"
    panel_contract = ROOT / "experiments/jev-information-density-v08q-r2-late-branch/contracts/q-r2-panel-contract-v01.json"
    verify_file(run_contract, EXPECTED["run_contract"], "bound training recipe")
    verify_file(panel_contract, EXPECTED["panel_contract"], "bound measurement interface")
    OUT.mkdir(parents=True, exist_ok=False)
    panel_report = verify_calibration_panel()
    training_report = build_balanced_training_sidecars()
    receipt = {
        "status": "R3_PRETREATMENT_INPUTS_VALIDATED",
        "identity": "JEV-V08Q-R3-SELECTIVITY-PRETREATMENT-CALIBRATION-V01",
        "calibration_histories_enter_confirmatory_cohort": False,
        "calibration_panel_enters_confirmatory_panel": False,
        "panel": panel_report,
        "balanced_training": training_report,
        "prohibited_operations": {
            "half_weight_branch": False,
            "treatment_metrics": False,
            "confirmatory_panel": False,
            "controller_fit": False,
        },
    }
    write_json(OUT / "pretraining-input-validation-receipt.json", receipt)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
