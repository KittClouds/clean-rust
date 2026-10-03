"""Find a metadata-only common-support profile and learner-visible witness pair."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V08C_DIR = ROOT / "experiments/jev-information-density-v08c"
sys.path.insert(0, str(V08C_DIR))
import phase2c_training_signatures as signature_ops  # noqa: E402

CONTRACT_PATH = HERE / "v08d-contract.json"
FREEZE_PATH = Path(r"D:\codex-runs\jev-information-density-v08d\common-support-v01\freeze-receipt.json")
RUN_DIR = FREEZE_PATH.parent
TARGET = 100_000
SUPPORT_MULTIPLIER = 4
INVARIANCE_MAX_PAIRS = 16
FAMILY_AXES = (
    "world_or_topology_family",
    "ontology_family",
    "schema_composition_family",
    "candidate_set_construction_family",
    "definition_template_family",
    "intervention_family",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_freeze() -> dict[str, Any]:
    contract = read_json(CONTRACT_PATH)
    receipt = read_json(FREEZE_PATH)
    if contract.get("status") != "frozen_before_support_construction":
        raise ValueError("v0.8D contract is not frozen")
    if receipt.get("status") != "SEALED_BEFORE_V08D_SUPPORT_CONSTRUCTION":
        raise ValueError("v0.8D freeze receipt status mismatch")
    if receipt.get("contract_sha256") != sha256_file(CONTRACT_PATH):
        raise ValueError("v0.8D contract hash mismatch")
    for relative, expected in receipt["repository_sources"].items():
        if sha256_file(ROOT / relative) != expected:
            raise ValueError(f"frozen v0.8D source changed: {relative}")
    for name, item in receipt["external_inputs"].items():
        if sha256_file(Path(item["path"])) != item["sha256"]:
            raise ValueError(f"frozen v0.8D input changed: {name}")
    verify_source_authority(contract)
    return contract


def verify_source_authority(contract: dict[str, Any]) -> None:
    """Recheck the pinned eligibility, firewall, and signature lineage receipts."""
    inputs = contract["inputs"]
    generation = read_json(Path(inputs["generation_receipt"]["path"]))
    if (generation.get("atomic_group_count"), generation.get("model_contact_authorized"),
            generation.get("phoenix_in_scope")) != (500_000, False, False):
        raise ValueError("generation receipt does not match the frozen metadata-only source scope")

    preselection = read_json(Path(inputs["preselection_audit"]["path"]))
    source_overlap = read_json(Path(inputs["source_overlap_report"]["path"]))
    consistency = read_json(Path(inputs["input_target_consistency"]["path"]))
    signatures = read_json(Path(inputs["training_equivalence_audit"]["path"]))
    parent_path = Path(contract["parent"]["v08c_integrity_receipt"]["path"])
    parent = read_json(parent_path)

    group_hash = inputs["group_records"]["sha256"]
    if preselection.get("status") != "ready_for_selection":
        raise ValueError("upstream v0.8 preselection is not ready")
    if (preselection.get("group_records_sha256") != group_hash
            or preselection.get("raw_valid_group_count") != 500_000
            or preselection.get("eligible_training_group_count") != 416_672
            or preselection.get("new_tight_eval_group_count") != 83_328
            or preselection.get("legacy_firewall_collision_group_count") != 0):
        raise ValueError("upstream preselection audit does not certify this clean eligible universe")
    if (preselection.get("contract_sha256") != sha256_file(ROOT / "experiments/jev-information-density-v08/v08-contract.json")
            or source_overlap.get("selector_source_sha256") != sha256_file(ROOT / "experiments/jev-information-density-v08/select_banks.py")
            or preselection.get("model_outputs_or_features_read") is not False
            or preselection.get("protected_text_exported") is not False):
        raise ValueError("upstream eligibility/firewall provenance differs from its frozen source")
    if (source_overlap.get("collision_group_count") != 0
            or source_overlap.get("group_records_sha256") != group_hash
            or source_overlap.get("model_outputs_or_features_read") is not False
            or source_overlap.get("protected_text_exported") is not False):
        raise ValueError("upstream source-overlap report is not a zero-collision audit of the pinned universe")
    consistency_detail = consistency.get("input_target_consistency", {})
    if (consistency.get("status") != "PASS"
            or consistency.get("group_records_sha256") != group_hash
            or consistency.get("canonical_group_count") != 500_000
            or consistency.get("metadata_group_count") != 500_000
            or consistency.get("unmatched_metadata_group_count") != 0
            or consistency.get("missing_metadata_group_count") != 0
            or consistency_detail.get("groups") != 500_000
            or consistency_detail.get("conflicting_inputs") != 0
            or preselection.get("input_target_consistency", {}).get("status") != "PASS"):
        raise ValueError("pinned input/target consistency receipt does not pass")
    if (signatures.get("status") != "PASS_METADATA_SIGNATURES_RECONSTRUCTED"
            or signatures.get("source_hashes", {}).get("group_records_sha256") != group_hash
            or signatures.get("source_row_counts", {}).get("eligible_closed_v05_training_groups") != 416_672
            or signatures.get("source_row_counts", {}).get("held_out_closed_v05_groups") != 83_328):
        raise ValueError("training-signature index lineage does not match the pinned eligible universe")
    if (parent.get("status") != "SEALED_BOUNDED_SEARCH_OUTCOME"
            or parent.get("scope", {}).get("model_or_tokenizer_access") is not False
            or parent.get("scope", {}).get("phoenix_access") is not False):
        raise ValueError("v0.8C parent receipt is not the expected sealed, no-model outcome")
    if sha256_file(parent_path) != contract["parent"]["v08c_integrity_receipt"]["sha256"]:
        raise ValueError("pinned v0.8C parent receipt hash mismatch")


@dataclass(frozen=True, slots=True)
class Item:
    group_id: str
    episode_id: str
    stratum_id: str
    joint_cell: tuple[str, ...]
    topology: tuple[str, ...]
    intervention: str
    input_state: str
    input_selector: str
    root_id: str
    family_items: tuple[tuple[str, str], ...]
    kind: str
    view: str
    candidate_count: int
    open_world: bool
    probability_source: str
    state_input_sha256: str
    candidate_ordered_sha256: str
    candidate_set_sha256: str
    target_ordered_sha256: str
    supervised_signature_sha256: str
    ordered_signature_sha256: str
    invariant_key: str
    perturbation_class: str | None

    def signature_row(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "state_input_sha256": self.state_input_sha256,
            "candidate_ordered_sha256": self.candidate_ordered_sha256,
            "candidate_set_sha256": self.candidate_set_sha256,
            "target_ordered_sha256": self.target_ordered_sha256,
            "supervised_signature_sha256": self.supervised_signature_sha256,
            "ordered_signature_sha256": self.ordered_signature_sha256,
            "invariant_key": self.invariant_key,
            "perturbation_class": self.perturbation_class,
            "kind": self.kind,
            "view": self.view,
            "open_world": self.open_world,
            "probability_source": self.probability_source,
        }


def item_from_row(row: tuple[Any, ...]) -> Item:
    (
        group_id, episode_id, root_id, cell_json, input_selector, input_state,
        topology_json, family_json, adapter_kind, view, open_world,
        probability_source, candidate_count, state_input, candidate_ordered,
        candidate_set, target_ordered, supervised, ordered, invariant_key,
        perturbation_class,
    ) = row
    joint_cell = tuple(str(value) for value in json.loads(cell_json))
    coverage = json.loads(topology_json)
    structural = coverage.get("structural_coverage", []) if isinstance(coverage, dict) else []
    topology = tuple(sorted(
        str(value).removeprefix("topology:")
        for value in structural
        if str(value).startswith("topology:")
    ))
    families = json.loads(family_json)
    if len(joint_cell) != 6:
        raise ValueError(f"expected six joint-cell fields for {group_id}")
    missing_family_axes = set(FAMILY_AXES) - set(families)
    if missing_family_axes:
        raise ValueError(f"missing family axes for {group_id}: {sorted(missing_family_axes)}")
    if not topology:
        raise ValueError(f"coverage metadata has no topology feature for {group_id}")
    family_items = tuple(sorted((str(key), str(value)) for key, value in families.items()))
    stratum = [
        list(joint_cell), list(topology), str(families["intervention_family"]),
    ]
    return Item(
        group_id=str(group_id),
        episode_id=str(episode_id),
        stratum_id=canonical_json(stratum),
        joint_cell=joint_cell,
        topology=topology,
        intervention=str(families["intervention_family"]),
        input_state=str(input_state),
        input_selector=str(input_selector),
        root_id=str(root_id),
        family_items=family_items,
        kind=str(adapter_kind),
        view=str(view),
        candidate_count=int(candidate_count),
        open_world=bool(open_world),
        probability_source=str(probability_source),
        state_input_sha256=str(state_input),
        candidate_ordered_sha256=str(candidate_ordered),
        candidate_set_sha256=str(candidate_set),
        target_ordered_sha256=str(target_ordered),
        supervised_signature_sha256=str(supervised),
        ordered_signature_sha256=str(ordered),
        invariant_key=str(invariant_key),
        perturbation_class=None if perturbation_class is None else str(perturbation_class),
    )


def allocate_quotas(capacities: dict[str, int], target: int, multiplier: int) -> dict[str, int]:
    eligible = {key: value for key, value in capacities.items() if value >= multiplier}
    upper = {key: value // multiplier for key, value in eligible.items()}
    if len(eligible) > target:
        raise ValueError(f"{len(eligible)} admitted strata exceed the target's one-per-stratum lower bound")
    if sum(upper.values()) < target:
        raise ValueError(f"fourfold replay capacity {sum(upper.values())} is below target {target}")
    quota = {key: 1 for key in eligible}
    remaining = target - len(quota)
    while remaining:
        active = [key for key in eligible if quota[key] < upper[key]]
        if not active:
            raise AssertionError("quota water filling exhausted capacity before target")
        total_weight = sum(eligible[key] for key in active)
        proposals: list[tuple[int, float, str]] = []
        for key in active:
            ideal = remaining * eligible[key] / total_weight
            whole = min(upper[key] - quota[key], int(ideal))
            proposals.append((whole, ideal - int(ideal), key))
        assigned = 0
        for whole, _remainder, key in proposals:
            if whole:
                quota[key] += whole
                assigned += whole
        remaining -= assigned
        if remaining == 0:
            break
        active = [key for key in eligible if quota[key] < upper[key]]
        if not active:
            raise AssertionError("quota water filling reached a closed set")
        weights = sum(eligible[key] for key in active)
        ranked = sorted(
            active,
            key=lambda key: (
                -(remaining * eligible[key] / weights % 1.0),
                digest_text(key),
                key,
            ),
        )
        one_pass = min(remaining, len(ranked))
        for key in ranked[:one_pass]:
            quota[key] += 1
        remaining -= one_pass
    if sum(quota.values()) != target or any(quota[key] > upper[key] for key in quota):
        raise AssertionError("quota allocation failed its exact total or replay cap")
    return quota


def histogram(counter: Counter[str]) -> Counter[int]:
    return Counter(counter.values())


def tv_distance(left: Counter[Any], right: Counter[Any]) -> float:
    left_total, right_total = sum(left.values()), sum(right.values())
    if left_total == 0 or right_total == 0:
        return 0.0 if left_total == right_total else 1.0
    return 0.5 * sum(
        abs(left.get(key, 0) / left_total - right.get(key, 0) / right_total)
        for key in left.keys() | right.keys()
    )


def profile(items: list[Item]) -> dict[str, Any]:
    cells = Counter(item.stratum_id for item in items)
    state_inputs = Counter(item.input_state for item in items)
    selector_inputs = Counter(item.input_selector for item in items)
    roots = Counter(item.root_id for item in items)
    families = {axis: Counter(dict(item.family_items)[axis] for item in items) for axis in FAMILY_AXES}
    topology = Counter(value for item in items for value in item.topology)
    interventions = Counter(item.intervention for item in items)
    return {
        "group_count": len(items),
        "strata": cells,
        "state_input_counts": state_inputs,
        "selector_input_counts": selector_inputs,
        "root_counts": roots,
        "family_counts": families,
        "topology_counts": topology,
        "intervention_counts": interventions,
        "kind_counts": Counter(item.kind for item in items),
        "view_counts": Counter(item.view for item in items),
        "candidate_count_counts": Counter(str(item.candidate_count) for item in items),
        "open_world_counts": Counter(str(item.open_world).lower() for item in items),
        "probability_source_counts": Counter(item.probability_source for item in items),
    }


def profile_check(reference: dict[str, Any], selected: dict[str, Any], tolerances: dict[str, Any]) -> dict[str, Any]:
    comparisons: dict[str, Any] = {
        "group_count_exact": selected["group_count"] == TARGET,
        "stratum_counts_exact": selected["strata"] == reference["strata"],
    }
    for name, counter_name in (("state_input", "state_input_counts"), ("selector_input", "selector_input_counts"), ("root", "root_counts")):
        ref_count = len(reference[counter_name])
        selected_count = len(selected[counter_name])
        relative = abs(selected_count - ref_count) / max(1, ref_count)
        tv = tv_distance(histogram(reference[counter_name]), histogram(selected[counter_name]))
        comparisons[name] = {
            "reference_unique": ref_count,
            "selected_unique": selected_count,
            "relative_error": relative,
            "occurrence_histogram_tv": tv,
            "unique_pass": relative <= tolerances["unique_relative_error_max"] + 1e-12,
            "histogram_pass": tv <= tolerances["occurrence_histogram_tv_max"] + 1e-12,
        }
    marginals = {
        **{f"family:{axis}": (reference["family_counts"][axis], selected["family_counts"][axis]) for axis in FAMILY_AXES},
        "kind": (reference["kind_counts"], selected["kind_counts"]),
        "view": (reference["view_counts"], selected["view_counts"]),
        "candidate_count": (reference["candidate_count_counts"], selected["candidate_count_counts"]),
        "open_world": (reference["open_world_counts"], selected["open_world_counts"]),
        "probability_source": (reference["probability_source_counts"], selected["probability_source_counts"]),
    }
    comparisons["marginal_tv"] = {
        name: {
            "tv": tv_distance(left, right),
            "pass": tv_distance(left, right) <= tolerances["marginal_tv_max"] + 1e-12,
        }
        for name, (left, right) in marginals.items()
    }
    comparisons["all_pass"] = (
        comparisons["group_count_exact"]
        and comparisons["stratum_counts_exact"]
        and all(comparisons[key]["unique_pass"] and comparisons[key]["histogram_pass"]
                for key in ("state_input", "selector_input", "root"))
        and all(item["pass"] for item in comparisons["marginal_tv"].values())
    )
    return comparisons


def core_categories(items: list[Item]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for item in items:
        names = (
            "world_family", "family_bundle", "query_view", "candidate_cardinality_bin",
            "entropy_quintile", "entropy_band",
        )
        for name, value in zip(names, item.joint_cell):
            result[name].add(value)
        result["topology"].update(item.topology)
        result["intervention_family"].add(item.intervention)
    return result


def full_profile_coverage(all_items: list[Item], support_items: list[Item], selected: list[Item], min_population: int) -> dict[str, Any]:
    all_core = core_categories(all_items)
    support_core = core_categories(support_items)
    selected_core = core_categories(selected)
    core_missing_support = {axis: sorted(values - support_core.get(axis, set())) for axis, values in all_core.items()}
    core_missing_selected = {axis: sorted(values - selected_core.get(axis, set())) for axis, values in all_core.items()}
    family_all = {axis: Counter(dict(item.family_items)[axis] for item in all_items) for axis in FAMILY_AXES}
    family_support = {axis: Counter(dict(item.family_items)[axis] for item in support_items) for axis in FAMILY_AXES}
    family_selected = {axis: Counter(dict(item.family_items)[axis] for item in selected) for axis in FAMILY_AXES}
    family_missing: dict[str, list[str]] = {}
    family_missing_support: dict[str, list[str]] = {}
    family_missing_selected: dict[str, list[str]] = {}
    for axis in FAMILY_AXES:
        required = {key for key, count in family_all[axis].items() if count >= min_population}
        family_missing_support[axis] = sorted(required - set(family_support[axis]))
        family_missing_selected[axis] = sorted(required - set(family_selected[axis]))
        family_missing[axis] = sorted(set(family_missing_support[axis]) | set(family_missing_selected[axis]))
    return {
        "core_categories_total": {axis: len(values) for axis, values in all_core.items()},
        "core_categories_in_support": {axis: len(support_core.get(axis, set())) for axis in all_core},
        "core_categories_in_anchor": {axis: len(selected_core.get(axis, set())) for axis in all_core},
        "core_missing_from_support": core_missing_support,
        "core_missing_from_anchor": core_missing_selected,
        "family_axis_category_counts": {axis: len(values) for axis, values in family_all.items()},
        "family_categories_missing_from_support": family_missing_support,
        "family_categories_missing_from_anchor": family_missing_selected,
        "family_categories_missing_at_min_population": family_missing,
        "all_core_categories_retained": not any(core_missing_support.values()) and not any(core_missing_selected.values()),
        "family_min_population_categories_retained": not any(family_missing.values()),
    }


def exact_training_distance(left: list[Item], right: list[Item]) -> dict[str, Any]:
    left_rows = [item.signature_row() for item in left]
    right_rows = [item.signature_row() for item in right]
    left_final, left_pairs = signature_ops.attach_invariance_context(
        left_rows, max_pairs=INVARIANCE_MAX_PAIRS
    )
    right_final, right_pairs = signature_ops.attach_invariance_context(
        right_rows, max_pairs=INVARIANCE_MAX_PAIRS
    )
    supervised = signature_ops.multiset_distance(
        (item.supervised_signature_sha256 for item in left),
        (item.supervised_signature_sha256 for item in right),
    )
    training = signature_ops.multiset_distance(left_final.values(), right_final.values())
    return {
        "supervised_signature_distance": supervised,
        "exact_training_signature_distance": training,
        "left_selected_invariance_pairs": len(left_pairs),
        "right_selected_invariance_pairs": len(right_pairs),
        "invariance_pair_cap": INVARIANCE_MAX_PAIRS,
        "left_training_multiset_sha256": signature_ops.digest(sorted(left_final.values())),
        "right_training_multiset_sha256": signature_ops.digest(sorted(right_final.values())),
    }


def write_manifest(path: Path, items: list[Item]) -> str:
    digest = hashlib.sha256()
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for item in sorted(items, key=lambda value: value.group_id):
            line = json.dumps({"group_id": item.group_id, "episode_id": item.episode_id}, separators=(",", ":")) + "\n"
            stream.write(line)
            digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def write_json(path: Path, body: dict[str, Any]) -> str:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
    return sha256_file(path)


def main() -> int:
    contract = verify_freeze()
    for output_name, filename in contract["outputs"].items():
        if output_name != "freeze_receipt" and (RUN_DIR / filename).exists():
            raise FileExistsError(f"refusing to overwrite v0.8D output: {RUN_DIR / filename}")
    input_cfg = contract["inputs"]
    db_path = Path(input_cfg["training_signature_index"]["path"])
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True)
    try:
        total_rows = connection.execute("SELECT COUNT(*) FROM training_groups").fetchone()[0]
        eligible_rows = connection.execute("SELECT COUNT(*) FROM training_groups WHERE held_out=0").fetchone()[0]
        held_rows = connection.execute("SELECT COUNT(*) FROM training_groups WHERE held_out=1").fetchone()[0]
        if (total_rows, eligible_rows, held_rows) != (416_672, 416_672, 0):
            raise ValueError(f"source population mismatch: {(total_rows, eligible_rows, held_rows)}")
        held_manifest: set[str] = set()
        with Path(input_cfg["heldout_manifest"]["path"]).open("r", encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    held_manifest.add(str(json.loads(line)["group_id"]))
        if len(held_manifest) != 83_328:
            raise ValueError(f"held-out manifest population mismatch: {len(held_manifest)}")

        query = """SELECT group_id, episode_id, root_id, joint_cell_json,
            selector_model_input_sha256, state_input_sha256, coverage_features_json,
            family_ids_json, adapter_kind, view, open_world, probability_source,
            candidate_count, state_input_sha256, candidate_ordered_sha256,
            candidate_set_sha256, target_ordered_sha256, supervised_signature_sha256,
            ordered_signature_sha256, invariant_key_sha256, perturbation_class
            FROM training_groups WHERE held_out=0 ORDER BY group_id"""
        all_items: list[Item] = []
        groups_by_stratum: dict[str, list[Item]] = defaultdict(list)
        eval_intersection_count = 0
        for row in connection.execute(query):
            item = item_from_row(row)
            if item.group_id in held_manifest:
                eval_intersection_count += 1
            all_items.append(item)
            groups_by_stratum[item.stratum_id].append(item)
    finally:
        connection.close()
    if eval_intersection_count:
        raise ValueError(f"training-only signature index intersects NewTight-Eval: {eval_intersection_count}")

    capacities = {key: len(values) for key, values in groups_by_stratum.items()}
    admitted = {key: value for key, value in capacities.items() if value >= SUPPORT_MULTIPLIER}
    fourfold_capacity = sum(value // SUPPORT_MULTIPLIER for value in admitted.values())
    quota: dict[str, int] = {}
    quota_error: str | None = None
    if fourfold_capacity >= TARGET and len(admitted) <= TARGET:
        quota = allocate_quotas(capacities, TARGET, SUPPORT_MULTIPLIER)
    else:
        quota_error = (
            f"admitted_strata={len(admitted)}; fourfold_capacity={fourfold_capacity}; "
            f"target={TARGET}"
        )
    support_items = [item for key, values in groups_by_stratum.items() if key in admitted for item in values]
    core_support = core_categories(support_items)
    core_all = core_categories(all_items)
    missing_core = {axis: sorted(values - core_support.get(axis, set())) for axis, values in core_all.items()}
    support_capacity_pass = bool(quota) and fourfold_capacity >= TARGET
    core_coverage_pass = not any(missing_core.values())
    if not core_coverage_pass:
        quota_error = (quota_error + "; " if quota_error else "") + "fourfold admission drops required core categories"

    attempts: list[dict[str, Any]] = []
    profile_valid: list[tuple[float, int, list[Item], list[Item], dict[str, Any], dict[str, Any]]] = []
    tolerance = contract["design"]["profile_constraints"]
    for attempt in range(int(contract["design"]["witness_attempts"]) if support_capacity_pass and core_coverage_pass else 0):
        seed = f"{contract['design']['witness_seed_prefix']}{attempt:02d}"
        left: list[Item] = []
        right: list[Item] = []
        for key in sorted(quota):
            ranked = sorted(
                groups_by_stratum[key],
                key=lambda item: (hashlib.sha256(f"{seed}|{item.group_id}".encode("utf-8")).digest(), item.group_id),
            )
            count = quota[key]
            left.extend(ranked[:count])
            right.extend(ranked[count : 2 * count])
        left_profile = profile(left)
        right_profile = profile(right)
        comparison = profile_check(left_profile, right_profile, {
            "unique_relative_error_max": tolerance["unique_relative_error_max"],
            "occurrence_histogram_tv_max": tolerance["occurrence_histogram_tv_max"],
            "marginal_tv_max": tolerance["marginal_tv_max"],
        })
        coverage_a = full_profile_coverage(all_items, support_items, left, int(contract["design"]["required_family_category_min_population"]))
        coverage_b = full_profile_coverage(all_items, support_items, right, int(contract["design"]["required_family_category_min_population"]))
        coverage_pass = all(
            coverage["all_core_categories_retained"] and coverage["family_min_population_categories_retained"]
            for coverage in (coverage_a, coverage_b)
        )
        if not coverage_pass:
            comparison["all_pass"] = False
            comparison["coverage_fail"] = True
        exact = exact_training_distance(left, right) if comparison["all_pass"] else None
        attempts.append({
            "attempt": attempt,
            "seed": seed,
            "profile_pass": bool(comparison["all_pass"]),
            "profile": comparison,
            "coverage_pass": coverage_pass,
            "coverage_a": coverage_a,
            "coverage_b": coverage_b,
            "D_supervised": None if exact is None else exact["supervised_signature_distance"],
            "D_train": None if exact is None else exact["exact_training_signature_distance"],
        })
        if exact is not None:
            profile_valid.append((exact["exact_training_signature_distance"], attempt, left, right, comparison, exact))

    profile_valid.sort(key=lambda item: (-item[0], item[1]))
    best = profile_valid[0] if profile_valid else None
    training_gate = best is not None and best[0] >= float(contract["design"]["exact_training_distance_gate"])
    if not support_capacity_pass:
        status = "SUPPORT_CAPACITY_FAIL"
    elif not core_coverage_pass:
        status = "CORE_COVERAGE_FAIL"
    elif best is None:
        status = "PROFILE_WITNESS_FAIL"
    elif not training_gate:
        status = "TREATMENT_CAPACITY_UNPROVEN"
    else:
        status = "CAPACITY_WITNESS_PASS"

    if quota:
        quota_distribution = Counter(quota.values())
        ratios = sorted(capacities[key] / quota[key] for key in quota)
    else:
        quota_distribution = Counter()
        ratios = []
    support_census = {
        "protocol": contract["protocol"],
        "status": status if status in {"SUPPORT_CAPACITY_FAIL", "CORE_COVERAGE_FAIL"} else "SUPPORT_CAPACITY_PASS",
        "fourfold_quota_capacity_pass": support_capacity_pass,
        "core_coverage_pass": core_coverage_pass,
        "admission_error": quota_error,
        "source_population": {
            "full_universe_groups_from_generation_receipt": 500_000,
            "training_signature_index_groups": total_rows,
            "eligible_training_index_rows": eligible_rows,
            "held_out_rows_in_training_index": held_rows,
            "heldout_manifest_groups": len(held_manifest),
            "training_eval_intersection": eval_intersection_count,
        },
        "S_star": {
            "support_group_count": len(support_items),
            "support_stratum_count": len(admitted),
            "excluded_low_capacity_strata": len(capacities) - len(admitted),
            "excluded_low_capacity_groups": sum(value for value in capacities.values() if value < SUPPORT_MULTIPLIER),
            "fourfold_quota_capacity": fourfold_capacity,
            "capacity_to_quota_ratio_min": min(ratios) if ratios else None,
            "capacity_to_quota_ratio_median": ratios[len(ratios) // 2] if ratios else None,
            "quota_count_distribution": {str(key): value for key, value in sorted(quota_distribution.items())},
            "core_categories_in_all_eligible": {axis: len(values) for axis, values in core_all.items()},
            "core_categories_in_S_star": {axis: len(values) for axis, values in core_support.items()},
            "core_categories_missing_from_S_star": missing_core,
            "all_core_categories_retained": not any(missing_core.values()),
        },
        "metadata_only": True,
        "model_contact": False,
        "phoenix_access": False,
    }
    support_path = RUN_DIR / contract["outputs"]["support_census"]
    support_hash = write_json(support_path, support_census)

    anchor_profile = None if best is None else profile(best[2])
    pstar_body: dict[str, Any] = {
        "protocol": contract["protocol"],
        "status": "PROFILE_FROZEN_BY_CAPACITY_WITNESS" if training_gate else (
            "PROFILE_NOT_FROZEN_TREATMENT_CAPACITY_UNPROVEN" if best else "PROFILE_NOT_FROZEN"
        ),
        "group_count": TARGET,
        "stratum_counts": [{"stratum": json.loads(key), "capacity": capacities[key], "quota": quota[key], "replay_ratio": capacities[key] / quota[key]} for key in sorted(quota)],
        "quota_rule": contract["design"]["quota_rule"],
        "input_root_anchor": None if anchor_profile is None else {
            name: {
                "state_inputs": dict(sorted(anchor_profile["state_input_counts"].items())),
                "selector_inputs": dict(sorted(anchor_profile["selector_input_counts"].items())),
                "roots": dict(sorted(anchor_profile["root_counts"].items())),
            },
            "anchor_witness_seed": f"{contract['design']['witness_seed_prefix']}{best[1]:02d}",
        },
        "support_census_sha256": support_hash,
        "profile_uses_model_outcomes": False,
    }
    pstar_path = RUN_DIR / contract["outputs"]["pstar_profile"]
    pstar_hash = write_json(pstar_path, pstar_body)

    manifest_hashes: dict[str, str] = {}
    if best is not None:
        left_path = RUN_DIR / contract["outputs"]["witness_a_manifest"]
        right_path = RUN_DIR / contract["outputs"]["witness_b_manifest"]
        manifest_hashes = {
            "A": write_manifest(left_path, best[2]),
            "B": write_manifest(right_path, best[3]),
        }
    witness_report = {
        "protocol": contract["protocol"],
        "status": status,
        "profile_valid_attempts": len(profile_valid),
        "attempts": attempts,
        "winner": None if best is None else {
            "attempt": best[1],
            "seed": f"{contract['design']['witness_seed_prefix']}{best[1]:02d}",
            "D_train": best[0],
            "D_train_gate": float(contract["design"]["exact_training_distance_gate"]),
            "training_distance": best[5],
            "profile": best[4],
            "manifest_sha256": manifest_hashes,
            "manifest_role": "capacity witnesses only; not R100*/C100* training arms",
        },
        "max_attainable_claim": "best witness among the 32 frozen attempts only; not a global maximum",
        "admission_error": quota_error,
        "policy_arms_constructed": False,
        "model_contact_authorized": False,
        "training_materialized": False,
        "phoenix_access": False,
    }
    witness_path = RUN_DIR / contract["outputs"]["witness_report"]
    witness_hash = write_json(witness_path, witness_report)
    integrity = {
        "protocol": contract["protocol"],
        "status": "SEALED_V08D_SUPPORT_CAPACITY_RESULT",
        "freeze_receipt_sha256": sha256_file(FREEZE_PATH),
        "contract_sha256": sha256_file(CONTRACT_PATH),
        "inputs": {name: item["sha256"] for name, item in contract["inputs"].items()},
        "outputs": {
            "support_census_sha256": support_hash,
            "pstar_profile_sha256": pstar_hash,
            "capacity_witness_report_sha256": witness_hash,
            "witness_a_manifest_sha256": manifest_hashes.get("A"),
            "witness_b_manifest_sha256": manifest_hashes.get("B"),
        },
        "result_status": status,
        "model_contact": False,
        "training_materialized": False,
        "phoenix_access": False,
    }
    integrity_path = RUN_DIR / contract["outputs"]["integrity_receipt"]
    write_json(integrity_path, integrity)
    print(json.dumps({
        "status": status,
        "support_groups": len(support_items),
        "strata": len(quota),
        "fourfold_capacity": support_census["S_star"]["fourfold_quota_capacity"],
        "profile_valid_attempts": len(profile_valid),
        "best_D_train": None if best is None else best[0],
        "D_train_gate": contract["design"]["exact_training_distance_gate"],
        "model_contact": False,
        "integrity_receipt": str(integrity_path),
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
