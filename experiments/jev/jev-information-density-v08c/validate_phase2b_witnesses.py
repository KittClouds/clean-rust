"""Independent audit of v0.8C identity witnesses and frozen selector objectives.

This verifier intentionally does not import the v0.8 selector, v0.8B bank
builder, or v0.8C feasibility/optimizer modules. It streams the pinned metadata
source twice, reconstructs the family holdout and selector arithmetic, and
emits a metadata-only receipt outside the repository.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
V08_DIR = REPO / "experiments" / "jev-information-density-v08"
V08B_DIR = REPO / "experiments" / "jev-information-density-v08b"

FAMILY_AXES = (
    "world_or_topology_family",
    "ontology_family",
    "schema_composition_family",
    "candidate_set_construction_family",
    "definition_template_family",
    "intervention_family",
)
COVERAGE_AXES = (
    "semantic_novelty",
    "local_discrimination",
    "probability_geometry",
    "structural_coverage",
    "redundancy",
)
GROUP_FIELDS = {
    "group_id", "episode_id", "root_id", "valid", "family_ids", "strata",
    "coverage_features", "overlap_keys", "split_family_bundle_id",
    "posterior_entropy_nats",
}
HOLDOUT_SALT = "jev-idv08-family-bundle-holdout-sha256-v1"
HOLDOUT_FRACTION = 0.20
V08_RANDOM_SEED = "jev-idv08-r100-sha256-v1"
V08_CURATED_SEED = "jev-idv08-c100-sha256-v3-static-frequency-coverage"
GROUP_LIMIT = 100_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_digest(seed: str, key: str) -> bytes:
    return hashlib.sha256(f"{seed}|{key}".encode("utf-8")).digest()


def is_held_out(bundle_id: str) -> bool:
    digest = hashlib.sha256(
        f"{HOLDOUT_SALT}|family_bundle|{bundle_id}".encode("utf-8")
    ).digest()
    threshold = int(HOLDOUT_FRACTION * (1 << 256))
    return int.from_bytes(digest, "big") < threshold


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


def input_and_gold(overlap_keys: list[str], where: str) -> tuple[str, str]:
    inputs = [key.removeprefix("model_input:") for key in overlap_keys if key.startswith("model_input:")]
    golds = [key.removeprefix("gold_target:") for key in overlap_keys if key.startswith("gold_target:")]
    if len(inputs) != 1 or len(golds) != 1:
        raise ValueError(f"expected one model_input and gold_target key at {where}")
    return inputs[0], golds[0]


def read_manifest(path: Path, expected_count: int | None = None) -> tuple[dict[str, str], str]:
    entries: dict[str, str] = {}
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            digest.update(raw)
            if not raw.strip():
                continue
            row = json.loads(raw)
            group_id = row.get("group_id")
            episode_id = row.get("episode_id")
            if not isinstance(group_id, str) or not group_id:
                raise ValueError(f"missing group_id at {path}:{line_no}")
            if not isinstance(episode_id, str) or not episode_id:
                raise ValueError(f"missing episode_id at {path}:{line_no}")
            if group_id in entries:
                raise ValueError(f"duplicate group_id at {path}:{line_no}: {group_id}")
            entries[group_id] = episode_id
    if expected_count is not None and len(entries) != expected_count:
        raise ValueError(f"{path} has {len(entries)} groups, expected {expected_count}")
    return entries, digest.hexdigest()


def validate_row_shape(row: dict[str, Any], line_no: int) -> None:
    if set(row) != GROUP_FIELDS:
        missing = sorted(GROUP_FIELDS - set(row))
        extra = sorted(set(row) - GROUP_FIELDS)
        raise ValueError(f"group schema mismatch at line {line_no}: missing={missing}; extra={extra}")
    families = row["family_ids"]
    if not isinstance(families, dict) or set(families) != set(FAMILY_AXES):
        raise ValueError(f"family axes mismatch at line {line_no}")
    if any(families[axis] in (None, "", "none", "unknown") for axis in FAMILY_AXES):
        raise ValueError(f"empty family identity at line {line_no}")
    strata = row["strata"]
    if not isinstance(strata, dict):
        raise ValueError(f"invalid strata at line {line_no}")
    coverage = row["coverage_features"]
    if not isinstance(coverage, dict):
        raise ValueError(f"invalid coverage features at line {line_no}")
    for axis in COVERAGE_AXES:
        if not isinstance(coverage.get(axis), list) or not coverage[axis]:
            raise ValueError(f"missing {axis} coverage at line {line_no}")
    if not isinstance(row["overlap_keys"], list):
        raise ValueError(f"invalid overlap keys at line {line_no}")


def normalized_features(row: dict[str, Any], input_id: str) -> tuple[tuple[str, ...], ...]:
    result = [tuple(sorted({str(value) for value in row["coverage_features"][axis]})) for axis in COVERAGE_AXES]
    redundancy_index = COVERAGE_AXES.index("redundancy")
    result[redundancy_index] = tuple(sorted(set(result[redundancy_index]) | {f"input:{input_id}"}))
    return tuple(result)


def cell_for(row: dict[str, Any], thresholds: list[float]) -> tuple[str, ...]:
    entropy = float(row["posterior_entropy_nats"])
    q = bisect.bisect_right(thresholds, entropy) + 1
    strata = row.get("strata", {})
    world = row["world_family"] if "world_family" in row else strata["world_family"]
    query = row["query_view_type"] if "query_view_type" in row else strata["query_view_type"]
    cardinality = row["candidate_cardinality_bin"] if "candidate_cardinality_bin" in row else strata["candidate_cardinality_bin"]
    return (
        str(world),
        str(row["split_family_bundle_id"]),
        str(query),
        str(cardinality),
        f"q{q}",
        entropy_band(entropy),
    )


def coverage_score(features: tuple[tuple[str, ...], ...], counts: list[Counter[str]]) -> float:
    axis_scores = [
        sum(1.0 / math.sqrt(counts[index][feature]) for feature in values) / len(values)
        for index, values in enumerate(features)
        if values
    ]
    return sum(axis_scores) / len(axis_scores)


def histogram(counts: Counter[Any]) -> Counter[int]:
    return Counter(counts.values())


def tv(left: Counter[Any], right: Counter[Any]) -> float:
    n_left, n_right = sum(left.values()), sum(right.values())
    if not n_left or not n_right:
        return 0.0 if n_left == n_right == 0 else 1.0
    return 0.5 * sum(
        abs(left.get(key, 0) / n_left - right.get(key, 0) / n_right)
        for key in set(left) | set(right)
    )


def outward_interval(reference: int) -> tuple[int, int]:
    return math.floor(reference * 0.98), math.ceil(reference * 1.02)


def json_counter(counter: Counter[Any]) -> dict[str, int]:
    return {json.dumps(key, ensure_ascii=False, separators=(",", ":")) if isinstance(key, tuple) else str(key): value
            for key, value in sorted(counter.items(), key=lambda item: repr(item[0]))}


def summarize_profile(rows: list[dict[str, Any]], thresholds: list[float]) -> dict[str, Any]:
    profile: dict[str, Counter[Any]] = {
        name: Counter() for name in ("cells", "inputs", "roots", "topology", "interventions", "views", "cardinality", "bundles", "entropy_bands")
    }
    for row in rows:
        cell = cell_for(row, thresholds)
        profile["cells"][cell] += 1
        profile["inputs"][row["input_id"]] += 1
        profile["roots"][row["root_id"]] += 1
        profile["views"][cell[2]] += 1
        profile["cardinality"][cell[3]] += 1
        profile["bundles"][cell[1]] += 1
        profile["entropy_bands"][cell[5]] += 1
        profile["topology"].update(
            value.removeprefix("topology:")
            for value in row["coverage_features"]["structural_coverage"]
            if value.startswith("topology:")
        )
        profile["interventions"][row["intervention_family"]] += 1
    input_hist, root_hist = histogram(profile["inputs"]), histogram(profile["roots"])
    return {
        "group_count": sum(profile["cells"].values()),
        "unique_model_inputs": len(profile["inputs"]),
        "unique_roots": len(profile["roots"]),
        "joint_cell_count": len(profile["cells"]),
        "query_views": json_counter(profile["views"]),
        "candidate_cardinality": json_counter(profile["cardinality"]),
        "family_bundles": json_counter(profile["bundles"]),
        "entropy_bands": json_counter(profile["entropy_bands"]),
        "joint_cells": json_counter(profile["cells"]),
        "input_multiplicity_histogram": json_counter(input_hist),
        "root_multiplicity_histogram": json_counter(root_hist),
        "topology": json_counter(profile["topology"]),
        "interventions": json_counter(profile["interventions"]),
        "self_profile_checks": {
            "group_count_100k": sum(profile["cells"].values()) == GROUP_LIMIT,
            "unique_input_relative_error": 0.0,
            "input_multiplicity_tv": 0.0,
            "unique_root_relative_error": 0.0,
            "root_multiplicity_tv": 0.0,
            "topology_tv": 0.0,
            "intervention_tv": 0.0,
            "joint_cells_exact_by_identity": True,
        },
    }


def training_quintile_thresholds(values: list[float]) -> list[float]:
    values.sort()
    if not values:
        raise ValueError("empty training entropy population")
    return [values[min(len(values) - 1, math.floor(len(values) * q / 5))] for q in range(1, 5)]


def original_r100_selection(
    strata_rows: dict[str, list[tuple[bytes, str]]], total: int
) -> set[str]:
    quotas = {key: (len(rows) * GROUP_LIMIT) // total for key, rows in strata_rows.items()}
    remaining = GROUP_LIMIT - sum(quotas.values())
    remainder_order = sorted(
        strata_rows,
        key=lambda key: (-(len(strata_rows[key]) * GROUP_LIMIT % total), key),
    )
    for key in remainder_order[:remaining]:
        quotas[key] += 1
    selected: set[str] = set()
    for key, rows in strata_rows.items():
        rows.sort(key=lambda item: (item[0], item[1]))
        selected.update(group_id for _digest, group_id in rows[:quotas[key]])
    return selected


def rank_objective(
    items: list[tuple[Any, ...]],
    mode: str,
    selected_ids: dict[str, set[str]],
    quotas: dict[str, Counter[tuple[str, ...]]],
) -> dict[str, Any]:
    total = len(items)
    if mode == "curated":
        items.sort(key=lambda item: (-item[0], item[1], item[2]))
        get_id_cell = lambda item: (item[2], item[3])
    else:
        items.sort(key=lambda item: (item[0], item[1]))
        get_id_cell = lambda item: (item[1], item[2])
    sums = {name: 0 for name in selected_ids}
    upper = {name: 0 for name in selected_ids}
    seen = {name: Counter() for name in selected_ids}
    for rank, item in enumerate(items):
        group_id, cell = get_id_cell(item)
        priority = total - rank
        for name, ids in selected_ids.items():
            if group_id in ids:
                sums[name] += priority
            remaining = quotas[name].get(cell, 0)
            if seen[name][cell] < remaining:
                upper[name] += priority
                seen[name][cell] += 1
    return {
        "policy": mode,
        "eligible_group_count": total,
        "selected_priority_sums": sums,
        "cell_relaxed_valid_upper_bounds": upper,
        "headroom_from_identity_witness": {
            name: max(0, upper[name] - sums[name]) for name in selected_ids
        },
        "upper_bound_scope": "top priority ranks per exact joint cell; ignores all other constraints, therefore valid but potentially loose",
    }


class PeakMemory:
    """Best-effort RSS sampling without adding a nonstandard dependency."""

    def __init__(self) -> None:
        self.peak = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _rss(self) -> int:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            try:
                import psutil
                return int(psutil.Process(os.getpid()).memory_info().peak_wset)
            except Exception:
                pass

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            handle = kernel32.GetCurrentProcess()
            ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            return int(counters.PeakWorkingSetSize if ok else 0)
        try:
            import resource
            value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return int(value * (1024 if value < 10**9 else 1))
        except Exception:
            return 0

    def _sample(self) -> None:
        while not self._stop.wait(0.5):
            self.peak = max(self.peak, self._rss())

    def __enter__(self) -> "PeakMemory":
        self.peak = self._rss()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        self.peak = max(self.peak, self._rss())


def run(args: argparse.Namespace) -> dict[str, Any]:
    phase2_path = HERE / "v08c-phase2-contract.json"
    phase2 = json.loads(phase2_path.read_text(encoding="utf-8"))
    pins = phase2["inputs"]
    pinned_files = {
        "v08_contract_sha256": V08_DIR / "v08-contract.json",
        "v08_selector_sha256": V08_DIR / "select_banks.py",
        "v08b_contract_sha256": V08B_DIR / "v08b-contract.json",
        "phase1_solver_sha256": HERE / "solve_feasibility.py",
        "phase2_solver_sha256": HERE / "optimize_matched_banks.py",
    }
    for pin_name, path in pinned_files.items():
        observed = sha256_file(path)
        if observed != pins[pin_name]:
            raise ValueError(f"pinned source mismatch for {pin_name}: {observed} != {pins[pin_name]}")
    if sha256_file(HERE / "v08c-contract.json") != phase2["phase1_contract_sha256"]:
        raise ValueError("Phase 1 contract hash mismatch")
    preflight_receipt = Path(r"D:\codex-runs\jev-information-density-v08c\preflight-v03\preflight.json")
    if sha256_file(preflight_receipt) != pins["phase1_receipt_sha256"]:
        raise ValueError("Phase 1 preflight receipt hash mismatch")
    paths = {
        "group_records": args.groups,
        "r100_manifest": args.r100,
        "c100_manifest": args.c100,
        "eval_manifest": args.eval,
    }
    manifest_info: dict[str, dict[str, Any]] = {}
    manifests: dict[str, dict[str, str]] = {}
    for name in ("r100_manifest", "c100_manifest", "eval_manifest"):
        expected = pins[name + "_sha256"]
        entries, observed = read_manifest(paths[name], GROUP_LIMIT if name != "eval_manifest" else None)
        if observed != expected:
            raise ValueError(f"pinned hash mismatch for {name}: {observed} != {expected}")
        manifests[name] = entries
        manifest_info[name] = {"path": str(paths[name]), "sha256": observed, "group_count": len(entries)}
    r_entries, c_entries, e_entries = (manifests[key] for key in ("r100_manifest", "c100_manifest", "eval_manifest"))
    r_ids, c_ids, e_ids = set(r_entries), set(c_entries), set(e_entries)
    if len(e_ids) != 83_328:
        raise ValueError(f"NewTight-Eval count is {len(e_ids)}, expected 83,328")

    profiles_rows: dict[str, list[dict[str, Any]]] = {"R100": [], "C100": []}
    witness_names: dict[str, set[str]] = defaultdict(set)
    for name, ids in (("R100", r_ids), ("C100", c_ids)):
        for group_id in ids:
            witness_names[group_id].add(name)

    feature_counts = [Counter() for _ in COVERAGE_AXES]
    training_entropies: list[float] = []
    seen_ids: set[str] = set()
    found_eval: set[str] = set()
    found_witness: Counter[str] = Counter()
    input_gold: dict[str, str] = {}
    eligible_count = valid_count = heldout_count = 0
    raw_digest = hashlib.sha256()
    phase_times: dict[str, float] = {}

    started = time.perf_counter()
    with PeakMemory() as memory:
        with paths["group_records"].open("rb") as stream:
            for line_no, raw in enumerate(stream, 1):
                raw_digest.update(raw)
                if not raw.strip():
                    continue
                row = json.loads(raw)
                validate_row_shape(row, line_no)
                group_id = str(row["group_id"])
                if not group_id or group_id in seen_ids:
                    raise ValueError(f"empty or duplicate group_id at source line {line_no}")
                seen_ids.add(group_id)
                if row["valid"] is not True:
                    continue
                valid_count += 1
                bundle = str(row["split_family_bundle_id"])
                held_out = is_held_out(bundle)
                if held_out:
                    heldout_count += 1
                    if group_id in e_ids:
                        found_eval.add(group_id)
                    if group_id in witness_names:
                        raise ValueError(f"training witness is held out: {group_id}")
                    continue
                eligible_count += 1
                if group_id in e_ids:
                    raise ValueError(f"NewTight-Eval group is not held out: {group_id}")
                entropy = float(row["posterior_entropy_nats"])
                if not math.isfinite(entropy) or entropy < 0:
                    raise ValueError(f"invalid posterior entropy at source line {line_no}")
                training_entropies.append(entropy)
                input_id, gold_id = input_and_gold(row["overlap_keys"], f"source line {line_no}")
                old_gold = input_gold.setdefault(input_id, gold_id)
                if old_gold != gold_id:
                    raise ValueError(f"conflicting gold for model input {input_id}")
                features = normalized_features(row, input_id)
                for axis_index, values in enumerate(features):
                    feature_counts[axis_index].update(values)
                if group_id in witness_names:
                    expected_episode = r_entries.get(group_id, c_entries.get(group_id))
                    if str(row["episode_id"]) != expected_episode:
                        raise ValueError(f"episode mismatch for witness group {group_id}")
                    family_ids = row["family_ids"]
                    record = {
                        "group_id": group_id,
                        "episode_id": str(row["episode_id"]),
                        "root_id": str(row["root_id"]),
                        "input_id": input_id,
                        "gold_id": gold_id,
                        "split_family_bundle_id": bundle,
                        "world_family": str(row["strata"]["world_family"]),
                        "query_view_type": str(row["strata"]["query_view_type"]),
                        "candidate_cardinality_bin": str(row["strata"]["candidate_cardinality_bin"]),
                        "posterior_entropy_nats": entropy,
                        "family_ids": family_ids,
                        "coverage_features": row["coverage_features"],
                        "features_normalized": features,
                        "intervention_family": str(family_ids["intervention_family"]),
                    }
                    for name in witness_names[group_id]:
                        profiles_rows[name].append(record)
                        found_witness[name] += 1

        phase_times["source_stream_and_witness_membership_seconds"] = time.perf_counter() - started
        observed_groups_hash = raw_digest.hexdigest()
        if observed_groups_hash != pins["group_records_sha256"]:
            raise ValueError(f"pinned group-record hash mismatch: {observed_groups_hash}")
        if eligible_count != 416_672 or heldout_count != 83_328:
            raise ValueError(f"holdout reconstruction mismatch: eligible={eligible_count}, heldout={heldout_count}")
        if found_eval != e_ids:
            raise ValueError(f"evaluation membership mismatch: found={len(found_eval)} manifest={len(e_ids)}")
        if found_witness != Counter({"R100": GROUP_LIMIT, "C100": GROUP_LIMIT}):
            raise ValueError(f"witness eligible membership incomplete: {dict(found_witness)}")

        phase_start = time.perf_counter()
        thresholds = training_quintile_thresholds(training_entropies)
        profile_results = {
            name: summarize_profile(rows, thresholds)
            for name, rows in profiles_rows.items()
        }
        # After the training-only entropy thresholds are fixed, the second
        # source pass checks input-to-cell consistency over the whole eligible
        # universe, not only over the two witnesses.
        input_cell: dict[str, tuple[str, ...]] = {}
        cell_conflicts = 0
        phase_times["training_thresholds_and_witness_profiles_seconds"] = time.perf_counter() - phase_start

        # Counter over exact joint cells, using the independently reconstructed
        # training-only quintiles.
        quotas = {
            name: Counter(cell_for(row, thresholds) for row in profiles_rows[name])
            for name in ("R100", "C100")
        }
        selected_policy_ids = {"R100": r_ids, "C100": c_ids}

        phase_start = time.perf_counter()
        original_c100_items: list[tuple[float, bytes, str]] = []
        phase2_curated_items: list[tuple[float, bytes, str, tuple[str, ...]]] = []
        phase2_random_items: list[tuple[bytes, str, tuple[str, ...]]] = []
        r100_strata: dict[str, list[tuple[bytes, str]]] = defaultdict(list)
        second_digest = hashlib.sha256()
        with paths["group_records"].open("rb") as stream:
            for line_no, raw in enumerate(stream, 1):
                second_digest.update(raw)
                if not raw.strip():
                    continue
                row = json.loads(raw)
                if row["valid"] is not True or is_held_out(str(row["split_family_bundle_id"])):
                    continue
                group_id = str(row["group_id"])
                input_id, _gold_id = input_and_gold(row["overlap_keys"], f"second pass line {line_no}")
                features = normalized_features(row, input_id)
                score = coverage_score(features, feature_counts)
                cell = cell_for(row, thresholds)
                previous_cell = input_cell.setdefault(input_id, cell)
                if previous_cell != cell:
                    cell_conflicts += 1
                original_c100_items.append((score, stable_digest(V08_CURATED_SEED, group_id), group_id))
                phase2_curated_items.append((score, stable_digest(phase2["objective"]["curated_seed"], group_id), group_id, cell))
                phase2_random_items.append((stable_digest(phase2["objective"]["random_seed"], group_id), group_id, cell))
                strata = row["strata"]
                q = bisect.bisect_right(thresholds, float(row["posterior_entropy_nats"])) + 1
                original_stratum = json.dumps(
                    [str(strata["world_family"]), str(strata["query_view_type"]),
                     str(strata["candidate_cardinality_bin"]), f"q{q}"],
                    ensure_ascii=False, separators=(",", ":"),
                )
                r100_strata[original_stratum].append((stable_digest(V08_RANDOM_SEED, group_id), group_id))
        observed_second_hash = second_digest.hexdigest()
        if observed_second_hash != observed_groups_hash:
            raise ValueError("group-record source changed between validator passes")
        if cell_conflicts:
            raise ValueError(f"model-input signatures cross joint cells: {cell_conflicts}")
        phase_times["objective_feature_scoring_and_indexing_seconds"] = time.perf_counter() - phase_start

        phase_start = time.perf_counter()
        original_c100_items.sort(key=lambda item: (-item[0], item[1], item[2]))
        expected_c100 = {group_id for _score, _digest, group_id in original_c100_items[:GROUP_LIMIT]}
        expected_r100 = original_r100_selection(r100_strata, eligible_count)
        original_objective_reproduction = {
            "C100": {
                "selector": "v0.8 static global feature-rarity top-100k",
                "exact_manifest_match": expected_c100 == c_ids,
                "symmetric_difference_count": len(expected_c100 ^ c_ids),
            },
            "R100": {
                "selector": "v0.8 proportional-largest-remainder stratified SHA256 priority",
                "exact_manifest_match": expected_r100 == r_ids,
                "symmetric_difference_count": len(expected_r100 ^ r_ids),
            },
        }
        phase_times["original_selector_reproduction_seconds"] = time.perf_counter() - phase_start
        if not all(row["exact_manifest_match"] for row in original_objective_reproduction.values()):
            raise ValueError(f"reference selector reproduction failed: {original_objective_reproduction}")

        phase_start = time.perf_counter()
        objective_ranks = {
            "curated": rank_objective(phase2_curated_items, "curated", selected_policy_ids, quotas),
            "seeded_random_priority": rank_objective(phase2_random_items, "random", selected_policy_ids, quotas),
        }
        phase_times["phase2_objective_ranking_and_bounds_seconds"] = time.perf_counter() - phase_start

    if memory.peak <= 0:
        peak_memory = {"peak_working_set_bytes": None, "measurement": "unavailable"}
    else:
        peak_memory = {"peak_working_set_bytes": memory.peak, "measurement": "OS peak working set sampled"}

    phase2_contract_hash = sha256_file(phase2_path)
    source_hashes = {
        "v08_contract": sha256_file(V08_DIR / "v08-contract.json"),
        "v08_selector": sha256_file(V08_DIR / "select_banks.py"),
        "v08b_contract": sha256_file(V08B_DIR / "v08b-contract.json"),
        "v08b_builder": sha256_file(V08B_DIR / "build_factorial_banks.py"),
        "phase1_contract": sha256_file(HERE / "v08c-contract.json"),
        "phase1_solver": sha256_file(HERE / "solve_feasibility.py"),
        "phase2_contract": phase2_contract_hash,
        "phase2_optimizer": sha256_file(HERE / "optimize_matched_banks.py"),
        "independent_validator": sha256_file(Path(__file__).resolve()),
    }
    report = {
        "receipt": "jev-information-density-v08c-phase2b-witness-validation/v1",
        "result": "PASS_PROFILE_WITNESSES_ONLY",
        "scope": {
            "model_contact": False,
            "phoenix_access": False,
            "banks_materialized": False,
            "prior_artifacts_modified": False,
        },
        "source_hashes": source_hashes,
        "manifest_hashes": manifest_info,
        "reconstructed_population": {
            "all_unique_group_ids": len(seen_ids),
            "valid_groups": valid_count,
            "eligible_training_groups": eligible_count,
            "heldout_evaluation_groups": heldout_count,
            "training_only_entropy_quintile_thresholds_nats": thresholds,
            "input_gold_conflicts": 0,
            "model_input_signatures_crossing_cells_in_eligible_universe": cell_conflicts,
            "r100_c100_overlap_groups": len(r_ids & c_ids),
        },
        "identity_witnesses": {
            name: {
                "status": "PROFILE_FEASIBLE",
                "profile_feasible": True,
                "counterfactual_feasible": False,
                "separated": False,
                "eligible_membership_count": found_witness[name],
                "eval_overlap_count": len((r_ids if name == "R100" else c_ids) & e_ids),
                "profile": profile_results[name],
                "meaning": "Identity witness proves only the frozen profile non-empty; it is not a distinct candidate counterfactual.",
            }
            for name in ("R100", "C100")
        },
        "original_selector_objective_reproduction": original_objective_reproduction,
        "phase2_identity_objective_receipts": objective_ranks,
        "construction_status": {
            "CM100": "NOT_CONSTRUCTED",
            "RM100": "NOT_CONSTRUCTED",
            "global_optimality_required": phase2["objective"]["objective_optimality_required"],
            "identity_witnesses_are_incumbents_for_full_counterfactual_problem": False,
            "reason": "The Phase 2B non-identity rule excludes identity as a counterfactual incumbent; it remains a profile-feasibility witness and initialization source only.",
        },
        "timing_seconds": phase_times,
        "memory": peak_memory,
        "limitations": [
            "No CM100/RM100 candidate was searched or emitted.",
            "The valid per-cell objective bound ignores input/root/marginal constraints and may be loose.",
            "Positive objective separation is not evidence of a material downstream model effect.",
        ],
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--groups", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\full-universe-500k-v08\group-records.jsonl"))
    parser.add_argument("--r100", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12\new-tight-r100-group-ids.jsonl"))
    parser.add_argument("--c100", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12\new-tight-c100-group-ids.jsonl"))
    parser.add_argument("--eval", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12\new-tight-eval-group-ids.jsonl"))
    parser.add_argument("--out", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08c\phase2b-v01\witness-validation.json"))
    args = parser.parse_args()
    report = run(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.out)
    print(json.dumps({
        "result": report["result"],
        "output": str(args.out),
        "timing_seconds": report["timing_seconds"],
        "memory": report["memory"],
        "selector_reproduction": report["original_selector_objective_reproduction"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
