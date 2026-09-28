"""Bounded, metadata-only repair of the v0.8D common-support witness.

This tool imports the sealed v0.8D implementation only to reconstruct its
frozen support, quota, profile, and witness semantics. It writes all new
artifacts to the v0.8E external run directory and never accesses model assets,
features, Phoenix, or protected text.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
V08D_DIR = ROOT / "experiments/jev-information-density-v08d"
V08E_RUN = Path(r"D:\codex-runs\jev-information-density-v08e\state-exposure-v01")
V03_RUN = Path(r"D:\codex-runs\jev-information-density-v08d\common-support-v03")
DB_PATH = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\training-signatures.sqlite")
SEED = "jev-idv08d-capacity-witness-sha256-v1-01"
TARGET = 100_000
TV_LIMIT = 0.02

sys.path.insert(0, str(V08D_DIR))
import discover_v08d_common_support as core  # noqa: E402
import execute_v08d_runner_v03 as v03  # noqa: E402


SELECT = """SELECT group_id, episode_id, root_id, joint_cell_json,
 selector_model_input_sha256, state_input_sha256, coverage_features_json,
 family_ids_json, adapter_kind, view, open_world, probability_source,
 candidate_count, state_input_sha256, candidate_ordered_sha256,
 candidate_set_sha256, target_ordered_sha256, supervised_signature_sha256,
 ordered_signature_sha256, invariant_key_sha256, perturbation_class
 FROM training_groups WHERE held_out=0 ORDER BY group_id"""


def require_v03_integrity() -> dict[str, Any]:
    """Verify all upstream v0.8D hashes before reading its indexed metadata."""
    contract = v03.verify_v03_receipt()
    receipt = core.read_json(V03_RUN / "integrity-receipt.json")
    if receipt.get("status") != "SEALED_V08D_SUPPORT_CAPACITY_RESULT":
        raise ValueError("v0.8D v03 result is not sealed")
    if receipt.get("result_status") != "PROFILE_WITNESS_FAIL":
        raise ValueError("v0.8D v03 result status changed")
    if receipt.get("model_contact") is not False or receipt.get("phoenix_access") is not False:
        raise ValueError("v0.8D receipt violates metadata-only boundary")
    return contract


def load_items(contract: dict[str, Any]) -> tuple[list[core.Item], dict[str, list[core.Item]]]:
    db = Path(contract["inputs"]["training_signature_index"]["path"])
    uri = f"file:{db.as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        counts = connection.execute(
            "SELECT COUNT(*), SUM(CASE WHEN held_out=0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN held_out=1 THEN 1 ELSE 0 END) FROM training_groups"
        ).fetchone()
        if counts != (416_672, 416_672, 0):
            raise ValueError(f"training index population mismatch: {counts}")
        all_items: list[core.Item] = []
        by_stratum: dict[str, list[core.Item]] = collections.defaultdict(list)
        for row in connection.execute(SELECT):
            item = core.item_from_row(row)
            all_items.append(item)
            by_stratum[item.stratum_id].append(item)
    finally:
        connection.close()
    return all_items, by_stratum


def build_witness(
    by_stratum: dict[str, list[core.Item]],
    quota: dict[str, int],
    seed: str = SEED,
) -> tuple[list[core.Item], list[core.Item], dict[str, list[core.Item]]]:
    left: list[core.Item] = []
    right: list[core.Item] = []
    selected: dict[str, list[core.Item]] = {}
    for key in sorted(quota):
        ranked = sorted(
            by_stratum[key],
            key=lambda item: (
                hashlib.sha256(f"{seed}|{item.group_id}".encode("utf-8")).digest(),
                item.group_id,
            ),
        )
        q = quota[key]
        a, b = ranked[:q], ranked[q : 2 * q]
        if len(a) != q or len(b) != q:
            raise ValueError(f"witness reconstruction shortfall in stratum {key}")
        left.extend(a)
        right.extend(b)
        selected[key] = ranked[2 * q :]
    return left, right, selected


def histogram_tv(left: collections.Counter[int], right: collections.Counter[int]) -> float:
    return core.tv_distance(left, right)


def state_diagnostics(
    all_items: list[core.Item], left: list[core.Item], right: list[core.Item]
) -> dict[str, Any]:
    state_all = collections.Counter(x.input_state for x in all_items)
    state_a = collections.Counter(x.input_state for x in left)
    state_b = collections.Counter(x.input_state for x in right)
    hist_a, hist_b = core.histogram(state_a), core.histogram(state_b)
    buckets = sorted(set(hist_a) | set(hist_b))
    bucket_rows = []
    for lo, hi, name in ((1, 1, "1"), (2, 2, "2"), (3, 3, "3"), (4, 5, "4-5"),
                         (6, 8, "6-8"), (9, 16, "9-16"), (17, 1_000_000_000, "17+")):
        bucket_rows.append({
            "state_multiplicity": name,
            "state_signatures_A": sum(hist_a.get(k, 0) for k in range(lo, hi + 1)),
            "state_signatures_B": sum(hist_b.get(k, 0) for k in range(lo, hi + 1)),
        })
    strata_by_state: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for item in all_items:
        strata_by_state[item.input_state][item.stratum_id] += 1
    selected_strata_a: dict[str, set[str]] = collections.defaultdict(set)
    selected_strata_b: dict[str, set[str]] = collections.defaultdict(set)
    for item in left:
        selected_strata_a[item.input_state].add(item.stratum_id)
    for item in right:
        selected_strata_b[item.input_state].add(item.stratum_id)
    imbalanced = []
    for state in set(state_a) | set(state_b):
        ca, cb = state_a.get(state, 0), state_b.get(state, 0)
        if ca == cb:
            continue
        imbalanced.append({
            "state_signature": state,
            "count_A": ca,
            "count_B": cb,
            "difference_A_minus_B": ca - cb,
            "eligible_groups_in_support": state_all.get(state, 0),
            "eligible_alternative_strata": len(strata_by_state[state]),
            "selected_strata_A": len(selected_strata_a[state]),
            "selected_strata_B": len(selected_strata_b[state]),
        })
    imbalanced.sort(key=lambda x: (-abs(x["difference_A_minus_B"]), x["state_signature"]))
    return {
        "state_signature_definition": "SHA256 of shared state/context text before query- and candidate-specific material",
        "state_signature_count_A": len(state_a),
        "state_signature_count_B": len(state_b),
        "state_multiplicity_histogram_A": {str(k): hist_a[k] for k in sorted(hist_a)},
        "state_multiplicity_histogram_B": {str(k): hist_b[k] for k in sorted(hist_b)},
        "state_multiplicity_bins": bucket_rows,
        "state_occurrence_histogram_tv": histogram_tv(hist_a, hist_b),
        "state_count_difference": {
            "exactly_equal_signatures": sum(state_a.get(s, 0) == state_b.get(s, 0) for s in set(state_a) | set(state_b)),
            "nonzero_difference_signatures": len(imbalanced),
            "sum_absolute_count_difference": sum(abs(state_a.get(s, 0) - state_b.get(s, 0)) for s in set(state_a) | set(state_b)),
        },
        "largest_state_imbalances": imbalanced[:100],
    }


def counters_for(items: list[core.Item]) -> dict[str, Any]:
    return core.profile(items)


def report_initial(contract: dict[str, Any], out_dir: Path) -> tuple[list[core.Item], list[core.Item], list[core.Item], dict[str, Any]]:
    all_items, by_stratum = load_items(contract)
    capacities = {key: len(rows) for key, rows in by_stratum.items()}
    quota = core.allocate_quotas(capacities, TARGET, 4)
    left, right, unselected = build_witness(by_stratum, quota)
    left_profile, right_profile = counters_for(left), counters_for(right)
    tolerances = contract["design"]["profile_constraints"]
    check = core.profile_check(left_profile, right_profile, {
        "unique_relative_error_max": tolerances["unique_input_relative_error_max"],
        "occurrence_histogram_tv_max": tolerances["input_occurrence_histogram_tv_max"],
        "marginal_tv_max": tolerances["extra_family_axis_tv_max"],
    })
    attempt = next(
        row for row in core.read_json(V03_RUN / "capacity-witness-report.json")["attempts"]
        if row["seed"] == SEED
    )
    reconstructed_state = check["state_input"]["occurrence_histogram_tv"]
    recorded_state = attempt["profile"]["state_input"]["occurrence_histogram_tv"]
    if not math.isclose(reconstructed_state, recorded_state, rel_tol=0.0, abs_tol=1e-15):
        raise ValueError(f"seed reconstruction mismatch: {reconstructed_state} != {recorded_state}")
    diagnostics = state_diagnostics(all_items, left, right)
    diag = {
        "status": "RECONSTRUCTED_V08D_ATTEMPT_01",
        "source_integrity_verified": True,
        "attempt_seed": SEED,
        "target_groups_per_arm": TARGET,
        "selected_A": len(left),
        "selected_B": len(right),
        "strata": len(quota),
        "profile_check": {
            "all_pass": check["all_pass"],
            "state_input": check["state_input"],
            "selector_input": check["selector_input"],
            "root": check["root"],
            "marginal_tv": check["marginal_tv"],
            "stratum_counts_exact": check["stratum_counts_exact"],
        },
        "recorded_attempt_profile_equal": True,
        "signature_terminology": {
            "state_signature": "shared state/context digest; state_input_sha256",
            "selector_input_signature": "full model-visible selector input digest; selector_model_input_sha256",
            "training_signature": "loss-relevant supervised signature; not reconstructed in this state-profile audit",
        },
        "state_diagnostics": diagnostics,
        "scope": {"model_contact": False, "feature_extraction": False, "phoenix_access": False},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "state-occurrence-diagnostics.json"
    path.write_text(json.dumps(diag, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return all_items, left, right, {"quota": quota, "unselected": unselected, "profile": check, "report": diag}


def _shift_histogram(hist: collections.Counter[int], old: int, new: int) -> None:
    if old > 0:
        hist[old] -= 1
        if hist[old] <= 0:
            del hist[old]
    if new > 0:
        hist[new] += 1


def predicted_state_tv(
    counts_a: collections.Counter[str],
    counts_b: collections.Counter[str],
    hist_a: collections.Counter[int],
    hist_b: collections.Counter[int],
    exchanges: list[tuple[core.Item, core.Item]],
) -> float:
    """Return exact state-multiplicity TV after A/B cross-arm exchanges."""
    if any(a.input_state == b.input_state for a, b in exchanges):
        return histogram_tv(hist_a, hist_b)
    delta_a: collections.Counter[str] = collections.Counter()
    delta_b: collections.Counter[str] = collections.Counter()
    for a, b in exchanges:
        delta_a[a.input_state] -= 1
        delta_a[b.input_state] += 1
        delta_b[a.input_state] += 1
        delta_b[b.input_state] -= 1
    next_a, next_b = hist_a.copy(), hist_b.copy()
    for state, delta in delta_a.items():
        _shift_histogram(next_a, counts_a.get(state, 0), counts_a.get(state, 0) + delta)
    for state, delta in delta_b.items():
        _shift_histogram(next_b, counts_b.get(state, 0), counts_b.get(state, 0) + delta)
    return histogram_tv(next_a, next_b)


def profile_other_than_state_pass(check: dict[str, Any]) -> bool:
    return (
        check["group_count_exact"]
        and check["stratum_counts_exact"]
        and check["state_input"]["unique_pass"]
        and all(
            check[name]["unique_pass"] and check[name]["histogram_pass"]
            for name in ("selector_input", "root")
        )
        and all(row["pass"] for row in check["marginal_tv"].values())
    )


def state_maps(
    left: list[core.Item], right: list[core.Item]
) -> tuple[
    collections.Counter[str], collections.Counter[str],
    dict[str, dict[str, list[core.Item]]], dict[str, dict[str, list[core.Item]]],
    collections.Counter[int], collections.Counter[int],
]:
    counts_a = collections.Counter(item.input_state for item in left)
    counts_b = collections.Counter(item.input_state for item in right)
    by_stratum_a: dict[str, dict[str, list[core.Item]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    by_stratum_b: dict[str, dict[str, list[core.Item]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    for item in left:
        by_stratum_a[item.stratum_id][item.input_state].append(item)
    for item in right:
        by_stratum_b[item.stratum_id][item.input_state].append(item)
    return counts_a, counts_b, by_stratum_a, by_stratum_b, core.histogram(counts_a), core.histogram(counts_b)


def ranked_state_exchanges(
    left: list[core.Item],
    right: list[core.Item],
    max_candidates: int = 300,
    states_per_side: int = 16,
    rows_per_state: int = 2,
) -> tuple[list[tuple[float, str, core.Item, core.Item]], dict[str, Any]]:
    """Find deterministic same-stratum swaps most likely to reduce state TV."""
    counts_a, counts_b, by_a, by_b, hist_a, hist_b = state_maps(left, right)
    current_tv = histogram_tv(hist_a, hist_b)
    differences = {s: counts_a.get(s, 0) - counts_b.get(s, 0) for s in counts_a.keys() | counts_b.keys()}
    tie_seed = "jev-v08e-state-repair-candidates-v1"
    candidates: list[tuple[float, str, core.Item, core.Item]] = []
    seen: set[tuple[str, str]] = set()
    possible_state_pairs = 0
    for stratum in sorted(by_a.keys() & by_b.keys()):
        over = sorted(
            (s for s in by_a[stratum] if differences.get(s, 0) > 0),
            key=lambda s: (-differences[s], s),
        )[:states_per_side]
        under = sorted(
            (s for s in by_b[stratum] if differences.get(s, 0) < 0),
            key=lambda s: (differences[s], s),
        )[:states_per_side]
        possible_state_pairs += len(over) * len(under)
        for state_a in over:
            rows_a = sorted(
                by_a[stratum][state_a],
                key=lambda item: (core.digest_text(f"{tie_seed}|A|{item.group_id}"), item.group_id),
            )[:rows_per_state]
            for state_b in under:
                rows_b = sorted(
                    by_b[stratum][state_b],
                    key=lambda item: (core.digest_text(f"{tie_seed}|B|{item.group_id}"), item.group_id),
                )[:rows_per_state]
                for item_a in rows_a:
                    for item_b in rows_b:
                        pair_key = (item_a.group_id, item_b.group_id)
                        if pair_key in seen:
                            continue
                        seen.add(pair_key)
                        trial = predicted_state_tv(
                            counts_a, counts_b, hist_a, hist_b, [(item_a, item_b)]
                        )
                        if trial < current_tv - 1e-15:
                            tie = core.digest_text(f"{tie_seed}|{item_a.group_id}|{item_b.group_id}")
                            candidates.append((trial, tie, item_a, item_b))
    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates[:max_candidates], {
        "current_state_tv": current_tv,
        "candidate_state_pair_count": possible_state_pairs,
        "candidate_group_exchange_count": len(seen),
        "state_improving_exchange_count": len(candidates),
        "retained_exchange_count": min(max_candidates, len(candidates)),
    }


def atomic_write(path: Path, text: str) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    temp.replace(path)


def save_checkpoint(
    out_dir: Path, left: list[core.Item], right: list[core.Item], metrics: dict[str, Any]
) -> None:
    for name, items in (("best-witness-a-ids.jsonl", left), ("best-witness-b-ids.jsonl", right)):
        body = "".join(
            json.dumps({"group_id": item.group_id, "episode_id": item.episode_id}, separators=(",", ":")) + "\n"
            for item in sorted(items, key=lambda item: item.group_id)
        )
        atomic_write(out_dir / name, body)
    atomic_write(out_dir / "best-witness-metrics.json", json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")


def log_event(path: Path, event: dict[str, Any], console: bool = False) -> None:
    event = {"time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
    if console:
        print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)


def apply_exchanges(
    left: list[core.Item], right: list[core.Item], exchanges: list[tuple[core.Item, core.Item]]
) -> tuple[list[tuple[int, int, core.Item, core.Item]], bool]:
    index_a = {item.group_id: idx for idx, item in enumerate(left)}
    index_b = {item.group_id: idx for idx, item in enumerate(right)}
    seen: set[str] = set()
    operations: list[tuple[int, int, core.Item, core.Item]] = []
    for item_a, item_b in exchanges:
        if item_a.group_id in seen or item_b.group_id in seen:
            return [], False
        seen.add(item_a.group_id)
        seen.add(item_b.group_id)
        ia, ib = index_a[item_a.group_id], index_b[item_b.group_id]
        if left[ia].stratum_id != right[ib].stratum_id:
            return [], False
        operations.append((ia, ib, left[ia], right[ib]))
    for ia, ib, old_a, old_b in operations:
        left[ia], right[ib] = old_b, old_a
    return operations, True


def revert_exchanges(
    left: list[core.Item], right: list[core.Item], operations: list[tuple[int, int, core.Item, core.Item]]
) -> None:
    for ia, ib, old_a, old_b in operations:
        left[ia], right[ib] = old_a, old_b


def independently_validate(
    contract: dict[str, Any],
    all_items: list[core.Item],
    left: list[core.Item],
    right: list[core.Item],
) -> dict[str, Any]:
    """Re-read selected IDs from SQLite and recompute all promotion metrics."""
    connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro&immutable=1", uri=True)
    try:
        held = {
            str(json.loads(line)["group_id"])
            for line in Path(contract["inputs"]["heldout_manifest"]["path"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        selected_ids = {item.group_id for item in left} | {item.group_id for item in right}
        if len(selected_ids) != len(left) + len(right):
            raise ValueError("candidate arms overlap or contain duplicate IDs")
        if selected_ids & held:
            raise ValueError("candidate intersects NewTight-Eval held-out manifest")
        from_db: dict[str, core.Item] = {}
        ids = sorted(selected_ids)
        for start in range(0, len(ids), 800):
            batch = ids[start : start + 800]
            placeholders = ",".join("?" for _ in batch)
            query = SELECT.replace(" FROM training_groups WHERE held_out=0 ORDER BY group_id", f" FROM training_groups WHERE held_out=0 AND group_id IN ({placeholders})")
            for row in connection.execute(query, batch):
                item = core.item_from_row(row)
                from_db[item.group_id] = item
    finally:
        connection.close()
    if len(from_db) != len(selected_ids):
        raise ValueError(f"independent source lookup missing {len(selected_ids) - len(from_db)} selected IDs")
    a = [from_db[item.group_id] for item in left]
    b = [from_db[item.group_id] for item in right]
    design = contract["design"]
    tolerances = design["profile_constraints"]
    checked = core.profile_check(core.profile(a), core.profile(b), {
        "unique_relative_error_max": tolerances["unique_input_relative_error_max"],
        "occurrence_histogram_tv_max": tolerances["input_occurrence_histogram_tv_max"],
        "marginal_tv_max": tolerances["extra_family_axis_tv_max"],
    })
    cover_a = core.full_profile_coverage(all_items, all_items, a, design["required_family_category_min_population"])
    cover_b = core.full_profile_coverage(all_items, all_items, b, design["required_family_category_min_population"])
    coverage_pass = all(x["all_core_categories_retained"] and x["family_min_population_categories_retained"] for x in (cover_a, cover_b))
    exact = core.exact_training_distance(a, b) if checked["all_pass"] and coverage_pass else None
    return {
        "status": "PASS" if checked["all_pass"] and coverage_pass else "FAIL",
        "source_rows_reloaded": len(from_db),
        "selected_groups_per_arm": [len(a), len(b)],
        "heldout_intersection_count": 0,
        "profile": checked,
        "coverage_pass": coverage_pass,
        "coverage_A": cover_a,
        "coverage_B": cover_b,
        "D_train": None if exact is None else exact["exact_training_signature_distance"],
        "training_distance": exact,
        "model_contact": False,
        "phoenix_access": False,
    }


def run_repair(
    contract: dict[str, Any],
    all_items: list[core.Item],
    left: list[core.Item],
    right: list[core.Item],
    out_dir: Path,
    minutes: float,
    max_profile_checks: int,
) -> dict[str, Any]:
    events = out_dir / "search-events.jsonl"
    start = time.monotonic()
    deadline = start + minutes * 60
    checks = accepts = 0
    phase_counts = collections.Counter()
    best_a, best_b = list(left), list(right)
    tol = contract["design"]["profile_constraints"]
    check_tolerances = {
        "unique_relative_error_max": tol["unique_input_relative_error_max"],
        "occurrence_histogram_tv_max": tol["input_occurrence_histogram_tv_max"],
        "marginal_tv_max": tol["extra_family_axis_tv_max"],
    }

    def current_measure() -> tuple[float, dict[str, Any]]:
        p_a, p_b = core.profile(left), core.profile(right)
        chk = core.profile_check(p_a, p_b, check_tolerances)
        state_tv = chk["state_input"]["occurrence_histogram_tv"]
        return state_tv, chk

    current_tv, current_check = current_measure()
    metrics = {"elapsed_seconds": 0, "state_tv": current_tv, "profile": current_check, "accepted_exchanges": 0}
    save_checkpoint(out_dir, left, right, metrics)
    log_event(events, {"event": "search_start", "state_tv": current_tv, "state_tv_limit": TV_LIMIT,
                       "max_minutes": minutes, "max_profile_checks": max_profile_checks}, True)
    last_checkpoint = start
    last_console = start
    status = "LOCAL_NEIGHBORHOOD_STALLED"

    while time.monotonic() < deadline and checks < max_profile_checks:
        if current_tv <= TV_LIMIT + 1e-12:
            status = "STATE_TV_GATE_REACHED"
            break
        candidates, scan = ranked_state_exchanges(left, right)
        phase_counts["candidate_group_exchanges"] += scan["candidate_group_exchange_count"]
        log_event(events, {"event": "candidate_scan", "accepted_exchanges": accepts,
                           "state_tv": current_tv, **scan}, False)
        accepted = False
        for trial_tv, _tie, item_a, item_b in candidates:
            if checks >= max_profile_checks or time.monotonic() >= deadline:
                break
            if trial_tv >= current_tv - 1e-15:
                continue
            ops, ok = apply_exchanges(left, right, [(item_a, item_b)])
            if not ok:
                continue
            checks += 1
            chk = core.profile_check(core.profile(left), core.profile(right), check_tolerances)
            coverage_ok = False
            if profile_other_than_state_pass(chk):
                coverage = [
                    core.full_profile_coverage(all_items, all_items, bank, int(contract["design"]["required_family_category_min_population"]))
                    for bank in (left, right)
                ]
                coverage_ok = all(x["all_core_categories_retained"] and x["family_min_population_categories_retained"] for x in coverage)
            if profile_other_than_state_pass(chk) and coverage_ok and chk["state_input"]["occurrence_histogram_tv"] < current_tv - 1e-15:
                accepts += 1
                phase_counts["single_swaps_accepted"] += 1
                current_tv, current_check = chk["state_input"]["occurrence_histogram_tv"], chk
                accepted = True
                log_event(events, {"event": "accepted_single_swap", "checks": checks, "accepted_exchanges": accepts,
                                   "state_tv": current_tv, "delta_tv": current_tv - metrics["state_tv"],
                                   "group_A_out": item_a.group_id, "group_B_out": item_b.group_id,
                                   "state_A_out": item_a.input_state, "state_B_out": item_b.input_state}, True)
                break
            revert_exchanges(left, right, ops)
            phase_counts["single_swaps_rejected_profile_or_coverage"] += 1
            if checks % 25 == 0:
                log_event(events, {"event": "search_progress", "checks": checks, "accepted_exchanges": accepts,
                                   "state_tv": current_tv, "candidate_count": len(candidates)}, True)
        if accepted:
            now = time.monotonic()
            metrics = {"elapsed_seconds": now - start, "state_tv": current_tv,
                       "profile": current_check, "accepted_exchanges": accepts,
                       "profile_checks": checks}
            if accepts % 5 == 0 or now - last_checkpoint >= 60:
                save_checkpoint(out_dir, left, right, metrics)
                last_checkpoint = now
            if now - last_console >= 30:
                log_event(events, {"event": "heartbeat", **metrics}, True)
                last_console = now
            continue

        # Bounded two-exchange cycles can repair selector/root histogram
        # drift that prevents either single exchange from being accepted.
        pool = candidates[:28]
        counts_a, counts_b, _, _, hist_a, hist_b = state_maps(left, right)
        pair_moves: list[tuple[float, str, tuple[core.Item, core.Item], tuple[core.Item, core.Item]]] = []
        for i, first in enumerate(pool):
            for second in pool[i + 1 :]:
                exch1, exch2 = (first[2], first[3]), (second[2], second[3])
                ids = {exch1[0].group_id, exch1[1].group_id, exch2[0].group_id, exch2[1].group_id}
                if len(ids) != 4:
                    continue
                trial = predicted_state_tv(counts_a, counts_b, hist_a, hist_b, [exch1, exch2])
                if trial < current_tv - 1e-15:
                    pair_moves.append((trial, first[1] + second[1], exch1, exch2))
        pair_moves.sort(key=lambda row: (row[0], row[1]))
        phase_counts["two_exchange_candidate_count"] += len(pair_moves)
        for _trial_tv, _tie, exch1, exch2 in pair_moves[: min(80, max_profile_checks - checks)]:
            if checks >= max_profile_checks or time.monotonic() >= deadline:
                break
            ops, ok = apply_exchanges(left, right, [exch1, exch2])
            if not ok:
                continue
            checks += 1
            chk = core.profile_check(core.profile(left), core.profile(right), check_tolerances)
            coverage_ok = False
            if profile_other_than_state_pass(chk):
                coverage = [
                    core.full_profile_coverage(all_items, all_items, bank, int(contract["design"]["required_family_category_min_population"]))
                    for bank in (left, right)
                ]
                coverage_ok = all(x["all_core_categories_retained"] and x["family_min_population_categories_retained"] for x in coverage)
            if profile_other_than_state_pass(chk) and coverage_ok and chk["state_input"]["occurrence_histogram_tv"] < current_tv - 1e-15:
                accepts += 2
                phase_counts["two_exchange_cycles_accepted"] += 1
                current_tv, current_check = chk["state_input"]["occurrence_histogram_tv"], chk
                accepted = True
                log_event(events, {"event": "accepted_two_exchange_cycle", "checks": checks,
                                   "accepted_exchanges": accepts, "state_tv": current_tv,
                                   "exchanges": [[exch1[0].group_id, exch1[1].group_id], [exch2[0].group_id, exch2[1].group_id]]}, True)
                break
            revert_exchanges(left, right, ops)
            phase_counts["two_exchange_cycles_rejected_profile_or_coverage"] += 1
        if accepted:
            now = time.monotonic()
            metrics = {"elapsed_seconds": now - start, "state_tv": current_tv,
                       "profile": current_check, "accepted_exchanges": accepts,
                       "profile_checks": checks}
            save_checkpoint(out_dir, left, right, metrics)
            last_checkpoint = now
            continue
        status = "LOCAL_NEIGHBORHOOD_STALLED"
        break

    if current_tv <= TV_LIMIT + 1e-12:
        status = "STATE_TV_GATE_REACHED"
    elif checks >= max_profile_checks:
        status = "WITNESS_SEARCH_BOUNDED_UNKNOWN"
    elif time.monotonic() >= deadline:
        status = "WITNESS_SEARCH_BOUNDED_UNKNOWN"
    elif status != "LOCAL_NEIGHBORHOOD_STALLED":
        status = "WITNESS_SEARCH_BOUNDED_UNKNOWN"

    metrics = {"elapsed_seconds": time.monotonic() - start, "status": status,
               "bounded_stop_reason": ("profile_check_budget" if checks >= max_profile_checks else
                                       "time_budget" if time.monotonic() >= deadline else
                                       "local_neighborhood_stalled"),
               "state_tv": current_tv, "state_tv_start": 0.027559110973668696,
               "improvement": 0.027559110973668696 - current_tv,
               "profile": current_check, "accepted_exchanges": accepts,
               "profile_checks": checks, "search_method_counts": dict(phase_counts),
               "state_tv_limit": TV_LIMIT, "model_contact": False, "phoenix_access": False}
    save_checkpoint(out_dir, left, right, metrics)
    validation = None
    if status == "STATE_TV_GATE_REACHED":
        validation = independently_validate(contract, all_items, left, right)
        metrics["independent_validation"] = validation
        if validation["status"] == "PASS":
            metrics["status"] = "PSTAR_PROFILE_VALIDATED"
        else:
            metrics["status"] = "INDEPENDENT_VALIDATION_FAILED"
        save_checkpoint(out_dir, left, right, metrics)
    atomic_write(out_dir / "repair-result.json", json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    log_event(events, {"event": "search_end", "status": metrics["status"],
                       "state_tv": current_tv, "profile_checks": checks,
                       "accepted_exchanges": accepts, "elapsed_seconds": metrics["elapsed_seconds"]}, True)
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=V08E_RUN)
    parser.add_argument("--minutes", type=float, default=25.0)
    parser.add_argument("--max-profile-checks", type=int, default=300)
    args = parser.parse_args()
    contract = require_v03_integrity()
    if args.run_dir.exists():
        raise FileExistsError(f"refusing to reuse v0.8E run directory: {args.run_dir}")
    all_items, left, right, built = report_initial(contract, args.run_dir)
    summary = run_repair(contract, all_items, left, right, args.run_dir, args.minutes, args.max_profile_checks)
    summary = {"run_directory": str(args.run_dir), "seed": SEED, **summary}
    print(json.dumps(summary, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
