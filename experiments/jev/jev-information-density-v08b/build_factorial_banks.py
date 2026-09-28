"""Build CM100/RM100 ID manifests under the frozen v0.8B matching rules."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V08_DIR = HERE.parent / "jev-information-density-v08"
sys.path.insert(0, str(V08_DIR))
import select_banks as v08  # noqa: E402


CM_SEED = "jev-idv08b-cm100-sha256-v1-profile-constrained-curation"
RM_SEED = "jev-idv08b-rm100-sha256-v1-profile-constrained-random"
TARGET_GROUPS = 100_000
TV_LIMIT = 0.02
RELATIVE_LIMIT = 0.02


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line).get("group_id")
            if not isinstance(value, str) or not value or value in ids:
                raise ValueError(f"invalid or duplicate group ID at {path}:{line_number}")
            ids.add(value)
    return ids


def model_input_id(group: v08.Group) -> str:
    values = [
        key.removeprefix("model_input:")
        for key in group.overlap_keys
        if key.startswith("model_input:")
    ]
    if len(values) != 1:
        raise ValueError(f"group {group.group_id} needs exactly one model_input digest")
    return values[0]


def entropy_band(value: float) -> str:
    if value < 0.20:
        return "very_low"
    if value < 0.55:
        return "low"
    if value < 0.95:
        return "medium"
    if value < 1.30:
        return "high"
    return "very_high"


def joint_cell(group: v08.Group) -> tuple[str, ...]:
    world, query, cardinality, quintile = group.strata
    bundle = group.split_family_bundle_id
    band = entropy_band(group.posterior_entropy_nats)
    return world, bundle, query, cardinality, quintile, band


def stable_digest(seed: str, key: str) -> bytes:
    return hashlib.sha256(f"{seed}|{key}".encode("utf-8")).digest()


def feature_counts(groups: list[v08.Group]) -> list[Counter[str]]:
    return [
        Counter(feature for group in groups for feature in group.features[axis])
        for axis in range(len(v08.COVERAGE_AXES))
    ]


def group_coverage_score(group: v08.Group, counts: list[Counter[str]]) -> float:
    axis_scores = [
        sum(1.0 / math.sqrt(counts[axis][feature]) for feature in features) / len(features)
        for axis, features in enumerate(group.features)
        if features
    ]
    return sum(axis_scores) / len(axis_scores)


def histogram(values: Counter[str]) -> Counter[int]:
    return Counter(values.values())


def tv_distance(left: Counter[Any], right: Counter[Any]) -> float:
    left_total = sum(left.values())
    right_total = sum(right.values())
    if not left_total or not right_total:
        return 0.0 if not left_total and not right_total else 1.0
    categories = set(left) | set(right)
    return 0.5 * sum(
        abs(left.get(key, 0) / left_total - right.get(key, 0) / right_total)
        for key in categories
    )


def within_relative_limit(actual: int, target: int) -> bool:
    return target > 0 and abs(actual - target) / target <= RELATIVE_LIMIT


def ranked_window(items: list[Any], required: int, attempt_index: int) -> list[Any]:
    """Select the next deterministic, overlapping window of a ranked candidate list."""
    if required < 0 or required > len(items):
        raise ValueError("ranked window request exceeds candidate count")
    if required == 0:
        return []
    last_start = len(items) - required
    start = min(attempt_index * required, last_start)
    return items[start : start + required]


def choose_cell(
    cell: tuple[str, ...],
    candidates: dict[str, list[v08.Group]],
    demand_histogram: Counter[int],
    mode: str,
    seed: str,
    scores: dict[str, float],
    attempt_index: int = 0,
) -> dict[str, int]:
    """Choose input signatures and exact multiplicities, best-fit by capacity."""
    remaining = set(candidates)
    selected: dict[str, int] = {}
    cell_key = json.dumps(cell, separators=(",", ":"))
    for multiplicity, required_inputs in sorted(demand_histogram.items(), reverse=True):
        eligible = [
            input_id for input_id in remaining
            if len(candidates[input_id]) >= multiplicity
        ]
        if len(eligible) < required_inputs:
            raise ValueError(
                f"cell {cell_key} needs {required_inputs} inputs with capacity {multiplicity}; "
                f"found {len(eligible)}"
            )

        def input_key(input_id: str) -> tuple[Any, ...]:
            rows = candidates[input_id]
            if mode == "random":
                tie = stable_digest(seed, f"{cell_key}|input|{input_id}")
                return len(rows), tie, input_id
            top_scores = sorted((scores[row.group_id] for row in rows), reverse=True)[:multiplicity]
            mean_score = sum(top_scores) / multiplicity
            tie = stable_digest(seed, f"{cell_key}|input|{input_id}")
            return len(rows), -mean_score, tie, input_id

        ranked = sorted(eligible, key=input_key)
        chosen_inputs = ranked_window(ranked, required_inputs, attempt_index)
        for input_id in chosen_inputs:
            selected[input_id] = multiplicity
            remaining.remove(input_id)
    return selected


class Dinic:
    """Compact-in-purpose integer max-flow for the layered input-root graph."""

    def __init__(self, node_count: int) -> None:
        self.adj: list[list[int]] = [[] for _ in range(node_count)]
        self.to: list[int] = []
        self.capacity: list[int] = []

    def add_edge(self, source: int, target: int, capacity: int) -> int:
        forward = len(self.to)
        self.to.extend((target, source))
        self.capacity.extend((capacity, 0))
        self.adj[source].append(forward)
        self.adj[target].append(forward + 1)
        return forward

    def max_flow(self, source: int, sink: int, limit: int) -> int:
        from collections import deque

        total = 0
        size = len(self.adj)
        while total < limit:
            level = [-1] * size
            level[source] = 0
            queue = deque([source])
            while queue:
                node = queue.popleft()
                for edge in self.adj[node]:
                    target = self.to[edge]
                    if self.capacity[edge] > 0 and level[target] < 0:
                        level[target] = level[node] + 1
                        queue.append(target)
            if level[sink] < 0:
                break
            next_edge = [0] * size

            def push(node: int, amount: int) -> int:
                if node == sink:
                    return amount
                while next_edge[node] < len(self.adj[node]):
                    edge = self.adj[node][next_edge[node]]
                    target = self.to[edge]
                    if self.capacity[edge] > 0 and level[target] == level[node] + 1:
                        sent = push(target, min(amount, self.capacity[edge]))
                        if sent:
                            self.capacity[edge] -= sent
                            self.capacity[edge ^ 1] += sent
                            return sent
                    next_edge[node] += 1
                return 0

            while total < limit:
                sent = push(source, limit - total)
                if not sent:
                    break
                total += sent
        return total


class MatchingFlowIncomplete(ValueError):
    def __init__(self, achieved: int, target: int) -> None:
        super().__init__(f"input-root b-matching flow was {achieved}/{target}")
        self.achieved = achieved
        self.target = target


def choose_root_demands(
    root_rows: dict[str, list[v08.Group]],
    demand_histogram: Counter[int],
    mode: str,
    seed: str,
    scores: dict[str, float],
    attempt_index: int = 0,
) -> dict[str, int]:
    remaining = set(root_rows)
    selected: dict[str, int] = {}
    for multiplicity, required_roots in sorted(demand_histogram.items(), reverse=True):
        eligible = [root for root in remaining if len(root_rows[root]) >= multiplicity]
        if len(eligible) < required_roots:
            raise ValueError(
                f"root profile needs {required_roots} roots with capacity {multiplicity}; "
                f"found {len(eligible)} among selected-input candidates"
            )

        def root_key(root: str) -> tuple[Any, ...]:
            rows = root_rows[root]
            if mode == "random":
                return len(rows), stable_digest(seed, f"root|{root}"), root
            top_scores = sorted((scores[row.group_id] for row in rows), reverse=True)[:multiplicity]
            return len(rows), -sum(top_scores) / multiplicity, stable_digest(seed, f"root|{root}"), root

        ranked = sorted(eligible, key=root_key)
        for root in ranked_window(ranked, required_roots, attempt_index):
            selected[root] = multiplicity
            remaining.remove(root)
    return selected


def assign_groups_by_flow(
    input_demands: dict[tuple[tuple[str, ...], str], int],
    groups_by_cell_input: dict[tuple[str, ...], dict[str, list[v08.Group]]],
    root_demands: dict[str, int],
    mode: str,
    seed: str,
    scores: dict[str, float],
    attempt_index: int = 0,
) -> tuple[list[v08.Group], dict[str, int]]:
    input_keys = sorted(input_demands)
    roots = sorted(root_demands)
    if sum(input_demands.values()) != sum(root_demands.values()):
        raise ValueError("input and root degree totals differ")
    source = 0
    input_start = 1
    root_start = input_start + len(input_keys)
    sink = root_start + len(roots)
    flow = Dinic(sink + 1)
    input_index = {key: input_start + index for index, key in enumerate(input_keys)}
    root_index = {root: root_start + index for index, root in enumerate(roots)}
    root_set = set(roots)
    pair_edges: list[tuple[int, int, list[v08.Group]]] = []

    for key in input_keys:
        cell, input_id = key
        left = input_index[key]
        flow.add_edge(source, left, input_demands[key])
        rows_by_root: dict[str, list[v08.Group]] = defaultdict(list)
        for row in groups_by_cell_input[cell][input_id]:
            if row.root_id in root_set:
                rows_by_root[row.root_id].append(row)
        for root, rows in sorted(rows_by_root.items()):
            edge = flow.add_edge(left, root_index[root], len(rows))
            pair_edges.append((edge, len(rows), rows))

    for root, demand in root_demands.items():
        flow.add_edge(root_index[root], sink, demand)
    target_flow = sum(input_demands.values())
    achieved = flow.max_flow(source, sink, target_flow)
    if achieved != target_flow:
        raise MatchingFlowIncomplete(achieved, target_flow)

    selected: list[v08.Group] = []
    used_pairs = 0
    attempt_seed = f"{seed}|attempt:{attempt_index:02d}"
    for edge, initial_capacity, rows in pair_edges:
        count = initial_capacity - flow.capacity[edge]
        if not count:
            continue
        used_pairs += 1
        if mode == "random":
            ordered = sorted(
                rows,
                key=lambda row: (stable_digest(attempt_seed, f"group|{row.group_id}"), row.group_id),
            )
        else:
            ordered = sorted(
                rows,
                key=lambda row: (
                    -scores[row.group_id],
                    stable_digest(attempt_seed, f"group|{row.group_id}"),
                    row.group_id,
                ),
            )
        selected.extend(ordered[:count])
    return selected, {
        "target_flow": target_flow,
        "achieved_flow": achieved,
        "input_cell_nodes": len(input_keys),
        "root_nodes": len(roots),
        "candidate_input_root_pairs": len(pair_edges),
        "used_input_root_pairs": used_pairs,
    }


def profile(groups: list[v08.Group]) -> dict[str, Any]:
    inputs: Counter[str] = Counter()
    roots: Counter[str] = Counter()
    cells: Counter[tuple[str, ...]] = Counter()
    views: Counter[str] = Counter()
    cardinality: Counter[str] = Counter()
    bundles: Counter[str] = Counter()
    entropy_bands: Counter[str] = Counter()
    topology: Counter[str] = Counter()
    interventions: Counter[str] = Counter()
    for group in groups:
        input_id = model_input_id(group)
        inputs[input_id] += 1
        roots[group.root_id] += 1
        cells[joint_cell(group)] += 1
        views[group.strata[1]] += 1
        cardinality[group.strata[2]] += 1
        bundles[group.split_family_bundle_id] += 1
        entropy_bands[entropy_band(group.posterior_entropy_nats)] += 1
        for value in group.features[3]:
            if value.startswith("topology:"):
                topology[value.removeprefix("topology:")] += 1
        family_map = dict(group.families)
        interventions[family_map["intervention_family"]] += 1
    return {
        "group_count": len(groups),
        "inputs": inputs,
        "roots": roots,
        "cells": cells,
        "query_views": views,
        "cardinality": cardinality,
        "bundles": bundles,
        "entropy_bands": entropy_bands,
        "topology": topology,
        "interventions": interventions,
    }


def compare(reference: dict[str, Any], selected: dict[str, Any]) -> dict[str, Any]:
    ref_input_hist = histogram(reference["inputs"])
    sel_input_hist = histogram(selected["inputs"])
    ref_root_hist = histogram(reference["roots"])
    sel_root_hist = histogram(selected["roots"])
    return {
        "group_count_exact": selected["group_count"] == TARGET_GROUPS,
        "joint_cells_exact": selected["cells"] == reference["cells"],
        "query_views_exact": selected["query_views"] == reference["query_views"],
        "cardinality_exact": selected["cardinality"] == reference["cardinality"],
        "family_bundles_exact": selected["bundles"] == reference["bundles"],
        "gold_entropy_bands_exact": selected["entropy_bands"] == reference["entropy_bands"],
        "unique_inputs": {
            "reference": len(reference["inputs"]),
            "selected": len(selected["inputs"]),
            "relative_error": abs(len(selected["inputs"]) - len(reference["inputs"])) / len(reference["inputs"]),
            "pass_2pct": within_relative_limit(len(selected["inputs"]), len(reference["inputs"])),
        },
        "input_occurrence_histogram": {
            "reference": {str(k): v for k, v in sorted(ref_input_hist.items())},
            "selected": {str(k): v for k, v in sorted(sel_input_hist.items())},
            "tv": tv_distance(ref_input_hist, sel_input_hist),
            "pass_0_02": ref_input_hist == sel_input_hist or tv_distance(ref_input_hist, sel_input_hist) <= TV_LIMIT,
        },
        "unique_roots": {
            "reference": len(reference["roots"]),
            "selected": len(selected["roots"]),
            "relative_error": abs(len(selected["roots"]) - len(reference["roots"])) / len(reference["roots"]),
            "pass_2pct": within_relative_limit(len(selected["roots"]), len(reference["roots"])),
        },
        "root_occurrence_histogram": {
            "reference": {str(k): v for k, v in sorted(ref_root_hist.items())},
            "selected": {str(k): v for k, v in sorted(sel_root_hist.items())},
            "tv": tv_distance(ref_root_hist, sel_root_hist),
            "pass_0_02": tv_distance(ref_root_hist, sel_root_hist) <= TV_LIMIT,
        },
        "topology_marginal": {
            "reference": dict(sorted(reference["topology"].items())),
            "selected": dict(sorted(selected["topology"].items())),
            "tv": tv_distance(reference["topology"], selected["topology"]),
            "pass_0_02": tv_distance(reference["topology"], selected["topology"]) <= TV_LIMIT,
        },
        "intervention_marginal": {
            "reference": dict(sorted(reference["interventions"].items())),
            "selected": dict(sorted(selected["interventions"].items())),
            "tv": tv_distance(reference["interventions"], selected["interventions"]),
            "pass_0_02": tv_distance(reference["interventions"], selected["interventions"]) <= TV_LIMIT,
        },
    }


def write_ids(path: Path, groups: list[v08.Group]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for group in sorted(groups, key=lambda item: item.group_id):
            stream.write(json.dumps({"group_id": group.group_id, "episode_id": group.episode_id}, separators=(",", ":")))
            stream.write("\n")


def all_pass(report: dict[str, Any]) -> bool:
    exact = (
        "group_count_exact",
        "joint_cells_exact",
        "query_views_exact",
        "cardinality_exact",
        "family_bundles_exact",
        "gold_entropy_bands_exact",
    )
    bounded = {
        "unique_inputs": "pass_2pct",
        "input_occurrence_histogram": "pass_0_02",
        "unique_roots": "pass_2pct",
        "root_occurrence_histogram": "pass_0_02",
        "topology_marginal": "pass_0_02",
        "intervention_marginal": "pass_0_02",
    }
    return all(report[key] for key in exact) and all(
        report[key][field] for key, field in bounded.items()
    )


def failed_constraint_names(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for key in (
        "group_count_exact",
        "joint_cells_exact",
        "query_views_exact",
        "cardinality_exact",
        "family_bundles_exact",
        "gold_entropy_bands_exact",
    ):
        if not report[key]:
            failures.append(key)
    for key, field in (
        ("unique_inputs", "pass_2pct"),
        ("input_occurrence_histogram", "pass_0_02"),
        ("unique_roots", "pass_2pct"),
        ("root_occurrence_histogram", "pass_0_02"),
        ("topology_marginal", "pass_0_02"),
        ("intervention_marginal", "pass_0_02"),
    ):
        if not report[key][field]:
            failures.append(f"{key}.{field}")
    return failures


def compact_comparison(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "all_frozen_constraints_pass": all_pass(report),
        "failed_constraints": failed_constraint_names(report),
        "group_count": report["group_count_exact"],
        "joint_cells": report["joint_cells_exact"],
        "unique_input_count": report["unique_inputs"]["selected"],
        "unique_input_relative_error": report["unique_inputs"]["relative_error"],
        "input_multiplicity_tv": report["input_occurrence_histogram"]["tv"],
        "unique_root_count": report["unique_roots"]["selected"],
        "unique_root_relative_error": report["unique_roots"]["relative_error"],
        "root_multiplicity_tv": report["root_occurrence_histogram"]["tv"],
        "topology_tv": report["topology_marginal"]["tv"],
        "intervention_tv": report["intervention_marginal"]["tv"],
    }


def failure_category(error: ValueError) -> str:
    message = str(error)
    if "inputs with capacity" in message:
        return "input_profile_capacity_short"
    if "roots with capacity" in message:
        return "root_profile_capacity_short"
    if "b-matching flow was" in message:
        return "input_root_b_matching_incomplete"
    if "degree totals differ" in message:
        return "input_root_degree_total_mismatch"
    return "candidate_construction_error"


def build(args: argparse.Namespace) -> dict[str, Any]:
    contract_path = HERE / "v08b-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    expected = contract["inherited_v08"]
    v08_contract_path = V08_DIR / "v08-contract.json"
    v08_selector_path = V08_DIR / "select_banks.py"
    if sha256_file(v08_contract_path) != expected["contract_sha256"]:
        raise ValueError("frozen v0.8 contract hash mismatch")
    if sha256_file(v08_selector_path) != expected["selector_source_sha256"]:
        raise ValueError("frozen v0.8 selector source hash mismatch")
    actual_hashes = {
        "group_records_sha256": sha256_file(args.group_records),
        "r100_manifest_sha256": sha256_file(args.r100),
        "c100_manifest_sha256": sha256_file(args.c100),
        "eval_manifest_sha256": sha256_file(args.eval),
    }
    for key, value in actual_hashes.items():
        if expected.get(key) != value:
            raise ValueError(f"frozen v0.8 input hash mismatch for {key}")

    r_ids, c_ids, eval_ids = read_ids(args.r100), read_ids(args.c100), read_ids(args.eval)
    all_groups = v08.read_group_records(args.group_records)
    train_groups, eval_pairs, _split = v08.split_families(all_groups)
    derived_eval_ids = {group.group_id for group, _axes in eval_pairs}
    if derived_eval_ids != eval_ids:
        raise ValueError("NewTight-Eval identity differs from the frozen family split")
    train_groups = v08.assign_training_entropy_quintiles(train_groups)
    train_ids = {group.group_id for group in train_groups}
    if r_ids - train_ids or c_ids - train_ids:
        raise ValueError("an existing R100/C100 group is outside the eligible training pool")

    reference_ids = {"R100": r_ids, "C100": c_ids}
    references = {
        name: [group for group in train_groups if group.group_id in ids]
        for name, ids in reference_ids.items()
    }
    if any(len(groups) != TARGET_GROUPS for groups in references.values()):
        raise ValueError("existing R100/C100 reference manifest does not contain exactly 100k groups")
    reference_profiles = {name: profile(groups) for name, groups in references.items()}

    groups_by_cell_input: dict[tuple[str, ...], dict[str, list[v08.Group]]] = defaultdict(lambda: defaultdict(list))
    for group in train_groups:
        groups_by_cell_input[joint_cell(group)][model_input_id(group)].append(group)
    input_cells: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for cell, input_map in groups_by_cell_input.items():
        for input_id in input_map:
            input_cells[input_id].add(cell)
    cross_cell_inputs = sum(len(cells) > 1 for cells in input_cells.values())
    if cross_cell_inputs:
        raise ValueError(f"model-input signatures span {cross_cell_inputs} joint cells; per-cell multiplicity matching is invalid")

    scores_count = feature_counts(train_groups)
    scores = {group.group_id: group_coverage_score(group, scores_count) for group in train_groups}
    outputs: dict[str, list[v08.Group]] = {}
    comparisons: dict[str, Any] = {}
    construction_map = {"CM100": ("R100", "curated", CM_SEED), "RM100": ("C100", "random", RM_SEED)}
    max_attempts = int(contract["policy"]["bounded_deterministic_attempts_per_bank"])

    for output_name, (reference_name, mode, seed) in construction_map.items():
        target = reference_profiles[reference_name]
        target_by_cell_input: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
        for group in references[reference_name]:
            target_by_cell_input[joint_cell(group)][model_input_id(group)] += 1
        target_root_histogram = histogram(target["roots"])
        attempt_receipts: list[dict[str, Any]] = []
        accepted: tuple[list[v08.Group], dict[str, int], dict[str, Any], int] | None = None

        for attempt_index in range(max_attempts):
            try:
                input_demands: dict[tuple[tuple[str, ...], str], int] = {}
                for cell, input_counts in sorted(target_by_cell_input.items()):
                    chosen = choose_cell(
                        cell,
                        groups_by_cell_input[cell],
                        histogram(input_counts),
                        mode,
                        seed,
                        scores,
                        attempt_index,
                    )
                    for input_id, multiplicity in chosen.items():
                        input_demands[(cell, input_id)] = multiplicity

                root_rows: dict[str, list[v08.Group]] = defaultdict(list)
                for cell, input_id in input_demands:
                    for row in groups_by_cell_input[cell][input_id]:
                        root_rows[row.root_id].append(row)
                root_demands = choose_root_demands(
                    root_rows,
                    target_root_histogram,
                    mode,
                    seed,
                    scores,
                    attempt_index,
                )
                selected, flow_report = assign_groups_by_flow(
                    input_demands,
                    groups_by_cell_input,
                    root_demands,
                    mode,
                    seed,
                    scores,
                    attempt_index,
                )
                comparison = compare(target, profile(selected))
                compact = compact_comparison(comparison)
                attempt_receipts.append({
                    "attempt_index": attempt_index,
                    "status": "PASS" if compact["all_frozen_constraints_pass"] else "CONSTRAINT_MISMATCH",
                    "flow": flow_report,
                    "comparison": compact,
                })
                if compact["all_frozen_constraints_pass"]:
                    accepted = (selected, flow_report, comparison, attempt_index)
                    break
            except ValueError as error:
                receipt: dict[str, Any] = {
                    "attempt_index": attempt_index,
                    "status": "INFEASIBLE",
                    "failure_class": failure_category(error),
                }
                if isinstance(error, MatchingFlowIncomplete):
                    receipt["flow"] = {
                        "target_flow": error.target,
                        "achieved_flow": error.achieved,
                        "unmatched_units": error.target - error.achieved,
                        "complete": False,
                    }
                attempt_receipts.append(receipt)

        if accepted is not None:
            selected, flow_report, comparison, accepted_attempt = accepted
            outputs[output_name] = selected
            comparisons[output_name] = {
                "composition_target": reference_name,
                "selection_mode": mode,
                "seed": seed,
                "accepted_attempt": accepted_attempt,
                "attempt_limit": max_attempts,
                "attempts": attempt_receipts,
                "root_profile_flow": flow_report,
                "comparison": comparison,
                "all_frozen_constraints_pass": True,
            }
        else:
            comparisons[output_name] = {
                "composition_target": reference_name,
                "selection_mode": mode,
                "seed": seed,
                "accepted_attempt": None,
                "attempt_limit": max_attempts,
                "attempts": attempt_receipts,
                "all_frozen_constraints_pass": False,
            }

    overall_pass = all(row["all_frozen_constraints_pass"] for row in comparisons.values())
    report: dict[str, Any] = {
        "contract": contract["contract"],
        "contract_sha256": sha256_file(contract_path),
        "selector_source_sha256": sha256_file(Path(__file__)),
        "group_records_sha256": actual_hashes["group_records_sha256"],
        "r100_manifest_sha256": actual_hashes["r100_manifest_sha256"],
        "c100_manifest_sha256": actual_hashes["c100_manifest_sha256"],
        "eval_manifest_sha256": actual_hashes["eval_manifest_sha256"],
        "eligible_pool_group_count": len(train_groups),
        "cross_joint_cell_input_signatures": cross_cell_inputs,
        "banks": comparisons,
        "factorial_matching_status": "PASS" if overall_pass else "FAIL_CLOSED",
        "protected_text_or_model_outputs_read": False,
        "phoenix_in_scope": False,
        "training_banks_materialized": False,
        "model_contact_authorized": False,
        "new_bank_ids_emitted": False,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    if overall_pass:
        write_ids(args.out / "cm100-group-ids.jsonl", outputs["CM100"])
        write_ids(args.out / "rm100-group-ids.jsonl", outputs["RM100"])
        report["new_bank_ids_emitted"] = True
        report["new_bank_manifest_sha256"] = {
            "CM100": sha256_file(args.out / "cm100-group-ids.jsonl"),
            "RM100": sha256_file(args.out / "rm100-group-ids.jsonl"),
        }
    report_path = args.out / "factorial-bank-audit.json"
    if report_path.exists():
        raise FileExistsError(f"refusing to overwrite report: {report_path}")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group-records", type=Path, required=True)
    parser.add_argument("--r100", type=Path, required=True)
    parser.add_argument("--c100", type=Path, required=True)
    parser.add_argument("--eval", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite or reuse output directory: {args.out}")
    report = build(args)
    print(json.dumps({
        "factorial_matching_status": report["factorial_matching_status"],
        "new_bank_ids_emitted": report["new_bank_ids_emitted"],
        "model_contact_authorized": False,
    }))


if __name__ == "__main__":
    main()
