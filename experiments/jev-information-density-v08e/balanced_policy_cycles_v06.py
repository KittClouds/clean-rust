"""Metadata-only balanced-cycle search for frozen P* selection policies.

The search changes selected training groups only through two-edge cycles. Each
edge is a one-row replacement within an exact P* stratum. The paired state
occupancies are chosen so that the state-multiplicity histogram is preserved
exactly while state identities may change. Every accepted arm remains checked
against the sealed P* profile; this module never accesses model features.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import build_policy_arms as policy
import state_exposure as v08e

ROOT = v08e.ROOT
RUN = Path(r"D:\codex-runs\jev-information-density-v08e")
SEALED = RUN / "sealed-pstar-v01"
REPAIR = RUN / "repair-v01"
DB = Path(r"D:\codex-runs\jev-information-density-v08c\phase2c-v01\training-signatures.sqlite")
OUT = RUN / "policy-mobility-v06-balanced-cycles-v04"
TOP_PER_BUCKET = 8
EDGE_CAP_PER_TRANSITION = 48
CYCLE_CAP = 250_000
BATCH_CYCLES = 256
CHECKPOINT_EVERY = 16
TREATMENT_GATE = 0.10


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_ids(path: Path) -> list[str]:
    return [
        str(json.loads(line)["group_id"])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def hist_after_cycle(
    counts: collections.Counter[str],
    changes: Iterable[tuple[str, int]],
) -> collections.Counter[int]:
    """Compute the positive-count histogram after sparse identity deltas."""
    histogram = v08e.core.histogram(counts)
    combined: collections.Counter[str] = collections.Counter()
    for identity, amount in changes:
        combined[identity] += amount
    for identity, amount in combined.items():
        before = counts.get(identity, 0)
        after = before + amount
        if after < 0:
            raise ValueError("cycle removes more occurrences than currently selected")
        if before:
            histogram[before] -= 1
            if histogram[before] <= 0:
                del histogram[before]
        if after:
            histogram[after] += 1
    return histogram


def state_cycle_is_balanced(
    state_counts: collections.Counter[str],
    outgoing: tuple[Any, Any],
    incoming: tuple[Any, Any],
) -> bool:
    """Check that a two-edge cycle exactly preserves state occupancy histogram."""
    old_a, new_b = outgoing
    old_c, new_d = incoming
    changed_states = [old_a.input_state, new_b.input_state, old_c.input_state, new_d.input_state]
    if len(set(changed_states)) != 4:
        return False
    old_a_count = state_counts.get(old_a.input_state, 0)
    new_b_count = state_counts.get(new_b.input_state, 0)
    old_c_count = state_counts.get(old_c.input_state, 0)
    new_d_count = state_counts.get(new_d.input_state, 0)
    if old_a_count < 1 or old_c_count < 1:
        return False
    if (old_c_count, new_d_count) != (new_b_count + 1, old_a_count - 1):
        return False
    before = v08e.core.histogram(state_counts)
    after = hist_after_cycle(state_counts, (
        (old_a.input_state, -1), (new_b.input_state, 1),
        (old_c.input_state, -1), (new_d.input_state, 1),
    ))
    return before == after


def histogram_tv(reference: collections.Counter[int], selected: collections.Counter[int]) -> float:
    return v08e.core.tv_distance(reference, selected)


def sparse_tv(
    reference: collections.Counter[str],
    selected: collections.Counter[str],
    delta: dict[str, int],
) -> float:
    selected_total = sum(selected.values()) + sum(delta.values())
    reference_total = sum(reference.values())
    if reference_total == 0 or selected_total == 0:
        return 0.0 if reference_total == selected_total else 1.0
    keys = reference.keys() | selected.keys() | delta.keys()
    return 0.5 * sum(
        abs(reference.get(key, 0) / reference_total - (selected.get(key, 0) + delta.get(key, 0)) / selected_total)
        for key in keys
    )


class ProfileTracker:
    """Incremental counters for cheap exact P* checks on sparse cycle changes."""

    def __init__(self, items: list[Any]):
        self.counts: dict[str, Any] = v08e.core.profile(items)
        self.hists = {
            "state_input_counts": v08e.core.histogram(self.counts["state_input_counts"]),
            "selector_input_counts": v08e.core.histogram(self.counts["selector_input_counts"]),
            "root_counts": v08e.core.histogram(self.counts["root_counts"]),
        }
        self._identity_keys = {
            "state_input_counts": "input_state",
            "selector_input_counts": "input_selector",
            "root_counts": "root_id",
        }
        self._reference_hist_cache: dict[int, dict[str, collections.Counter[int]]] = {}

    def _reference_hists(self, reference: dict[str, Any]) -> dict[str, collections.Counter[int]]:
        key = id(reference)
        cached = self._reference_hist_cache.get(key)
        if cached is None:
            cached = {
                counter_name: v08e.core.histogram(reference[counter_name])
                for counter_name in self._identity_keys
            }
            self._reference_hist_cache[key] = cached
        return cached

    @staticmethod
    def _counter_delta(outgoing: list[Any], incoming: list[Any], key_fn) -> dict[str, int]:
        delta: collections.Counter[str] = collections.Counter()
        for item in outgoing:
            delta[str(key_fn(item))] -= 1
        for item in incoming:
            delta[str(key_fn(item))] += 1
        return {key: value for key, value in delta.items() if value}

    @staticmethod
    def _histogram_delta_tv(
        reference_counts: collections.Counter[str],
        reference_hist: collections.Counter[int],
        selected_counts: collections.Counter[str],
        selected_hist: collections.Counter[int],
        delta: dict[str, int],
    ) -> tuple[int, float]:
        unique_count = len(selected_counts)
        next_hist = selected_hist.copy()
        for identity, amount in delta.items():
            before = selected_counts.get(identity, 0)
            after = before + amount
            if after < 0:
                raise ValueError("invalid sparse profile delta")
            if before:
                next_hist[before] -= 1
                if next_hist[before] <= 0:
                    del next_hist[before]
            else:
                unique_count += 1
            if after:
                next_hist[after] += 1
            else:
                unique_count -= 1
        return unique_count, histogram_tv(reference_hist, next_hist)

    def check(
        self,
        outgoing: list[Any],
        incoming: list[Any],
        references: list[dict[str, Any]],
        tolerances: dict[str, float],
        required_families: dict[str, set[str]],
    ) -> tuple[bool, list[dict[str, Any]]]:
        deltas: dict[str, dict[str, int]] = {}
        for counter_name, attr in self._identity_keys.items():
            deltas[counter_name] = self._counter_delta(outgoing, incoming, lambda item, a=attr: getattr(item, a))

        family_deltas: dict[str, dict[str, int]] = {}
        for axis in v08e.core.FAMILY_AXES:
            family_deltas[axis] = self._counter_delta(
                outgoing, incoming, lambda item, a=axis: dict(item.family_items)[a]
            )

        topology_delta: collections.Counter[str] = collections.Counter()
        for item in outgoing:
            topology_delta.subtract(item.topology)
        for item in incoming:
            topology_delta.update(item.topology)
        topology_delta = collections.Counter({key: value for key, value in topology_delta.items() if value})

        categorical_specs = {
            "kind_counts": lambda item: item.kind,
            "view_counts": lambda item: item.view,
            "candidate_count_counts": lambda item: str(item.candidate_count),
            "open_world_counts": lambda item: str(item.open_world).lower(),
            "probability_source_counts": lambda item: item.probability_source,
            "intervention_counts": lambda item: item.intervention,
        }
        cat_deltas = {
            name: self._counter_delta(outgoing, incoming, fn)
            for name, fn in categorical_specs.items()
        }
        max_unique_rel = float(tolerances["unique_relative_error_max"])
        max_hist_tv = float(tolerances["occurrence_histogram_tv_max"])
        max_marginal_tv = float(tolerances["marginal_tv_max"])

        rows: list[dict[str, Any]] = []
        for reference in references:
            reference_hists = self._reference_hists(reference)
            failed = False
            row: dict[str, Any] = {"all_pass": False}
            for label, counter_name in (
                ("state_input", "state_input_counts"),
                ("selector_input", "selector_input_counts"),
                ("root", "root_counts"),
            ):
                base = reference[counter_name]
                selected = self.counts[counter_name]
                unique, tv = self._histogram_delta_tv(
                    base, reference_hists[counter_name], selected, self.hists[counter_name], deltas[counter_name]
                )
                rel = abs(len(base) - unique) / max(1, len(base))
                unique_pass, hist_pass = rel <= max_unique_rel + 1e-12, tv <= max_hist_tv + 1e-12
                row[label] = {"reference_unique": len(base), "selected_unique": unique,
                              "relative_error": rel, "occurrence_histogram_tv": tv,
                              "unique_pass": unique_pass, "histogram_pass": hist_pass}
                failed |= not (unique_pass and hist_pass)

            marginal_rows: dict[str, dict[str, Any]] = {}
            for axis in v08e.core.FAMILY_AXES:
                reference_axis = reference["family_counts"][axis]
                tv = sparse_tv(reference_axis, self.counts["family_counts"][axis], family_deltas[axis])
                marginal_rows[f"family:{axis}"] = {"tv": tv, "pass": tv <= max_marginal_tv + 1e-12}
            tv = sparse_tv(reference["topology_counts"], self.counts["topology_counts"], dict(topology_delta))
            marginal_rows["topology"] = {"tv": tv, "pass": tv <= max_marginal_tv + 1e-12}
            for name, delta in cat_deltas.items():
                tv = sparse_tv(reference[name], self.counts[name], delta)
                marginal_rows[name.removesuffix("_counts")] = {"tv": tv, "pass": tv <= max_marginal_tv + 1e-12}
            row["marginal_tv"] = marginal_rows
            failed |= any(not value["pass"] for value in marginal_rows.values())

            # P* strata are unchanged by construction (every edge stays inside its stratum).
            row["stratum_counts_exact"] = True
            row["group_count_exact"] = self.counts["group_count"] == reference["group_count"]
            failed |= not row["group_count_exact"]
            family_coverage = {}
            for axis, values in required_families.items():
                current = self.counts["family_counts"][axis]
                missing = [value for value in values if current.get(value, 0) + family_deltas[axis].get(value, 0) <= 0]
                family_coverage[axis] = missing
                failed |= bool(missing)
            row["required_family_categories_missing"] = family_coverage
            row["all_pass"] = not failed
            rows.append(row)
        return all(row["all_pass"] for row in rows), rows

    def apply(self, outgoing: list[Any], incoming: list[Any]) -> None:
        for counter_name, attr in self._identity_keys.items():
            counter = self.counts[counter_name]
            hist = self.hists[counter_name]
            delta = self._counter_delta(outgoing, incoming, lambda item, a=attr: getattr(item, a))
            for identity, amount in delta.items():
                before = counter.get(identity, 0)
                after = before + amount
                if before:
                    hist[before] -= 1
                    if hist[before] <= 0:
                        del hist[before]
                if after:
                    hist[after] += 1
                    counter[identity] = after
                else:
                    counter.pop(identity, None)

        for axis in v08e.core.FAMILY_AXES:
            counter = self.counts["family_counts"][axis]
            for item in outgoing:
                counter[dict(item.family_items)[axis]] -= 1
            for item in incoming:
                counter[dict(item.family_items)[axis]] += 1
            for key in [key for key, value in counter.items() if value <= 0]:
                del counter[key]
        for item in outgoing:
            self.counts["topology_counts"].subtract(item.topology)
        for item in incoming:
            self.counts["topology_counts"].update(item.topology)
        for name, fn in {
            "kind_counts": lambda item: item.kind,
            "view_counts": lambda item: item.view,
            "candidate_count_counts": lambda item: str(item.candidate_count),
            "open_world_counts": lambda item: str(item.open_world).lower(),
            "probability_source_counts": lambda item: item.probability_source,
            "intervention_counts": lambda item: item.intervention,
        }.items():
            counter = self.counts[name]
            for item in outgoing:
                counter[str(fn(item))] -= 1
            for item in incoming:
                counter[str(fn(item))] += 1
            for key in [key for key, value in counter.items() if value <= 0]:
                del counter[key]
        for counter_name in ("topology_counts",):
            counter = self.counts[counter_name]
            for key in [key for key, value in counter.items() if value <= 0]:
                del counter[key]

    def profile(self) -> dict[str, Any]:
        return self.counts


@dataclass(frozen=True, slots=True)
class Edge:
    outgoing: Any
    incoming: Any
    outgoing_state_count: int
    incoming_state_count: int
    gain: float
    tie: str


@dataclass(frozen=True, slots=True)
class Cycle:
    first: Edge
    second: Edge
    gain: float
    tie: str


def item_quality(item: Any, score_by_id: dict[str, float], policy_name: str) -> float:
    if policy_name == "curated":
        return score_by_id[item.group_id]
    if policy_name == "random":
        value = int.from_bytes(policy.digest(policy.RANDOM_SEED, item.group_id), "big")
        return 1.0 - value / (1 << 256)
    raise ValueError(f"unsupported frozen policy: {policy_name}")


def training_signature_distance_from_counts(
    reference: collections.Counter[str], selected: collections.Counter[str], delta: dict[str, int] | None = None
) -> float:
    changes = delta or {}
    l1 = sum(abs(reference.get(key, 0) - (selected.get(key, 0) + changes.get(key, 0)))
             for key in reference.keys() | selected.keys() | changes.keys())
    return l1 / (2 * v08e.TARGET)


def build_cycles(
    items: list[Any],
    selected: dict[str, Any],
    state_counts: collections.Counter[str],
    quality_by_id: dict[str, float],
    policy_name: str,
    batch_id: int,
) -> tuple[list[Cycle], dict[str, Any]]:
    """Create deterministic high-policy-gain cycles with exact state-hist balance."""
    selected_by_stratum_count: dict[tuple[str, int], list[Any]] = collections.defaultdict(list)
    incoming_by_stratum_count: dict[tuple[str, int], list[Any]] = collections.defaultdict(list)
    for item in items:
        state_count = state_counts.get(item.input_state, 0)
        key = (item.stratum_id, state_count)
        if item.group_id in selected:
            selected_by_stratum_count[key].append(item)
        else:
            incoming_by_stratum_count[key].append(item)

    edge_buckets: dict[tuple[int, int], list[Edge]] = collections.defaultdict(list)
    transition_buckets = 0
    edge_candidates = 0
    for stratum in sorted({key[0] for key in selected_by_stratum_count}):
        out_levels = sorted(count for cell, count in selected_by_stratum_count if cell == stratum)
        in_levels = sorted(count for cell, count in incoming_by_stratum_count if cell == stratum)
        for a in out_levels:
            outgoing_by_state: dict[str, Any] = {}
            for item in selected_by_stratum_count[(stratum, a)]:
                old = outgoing_by_state.get(item.input_state)
                if old is None or (quality_by_id[item.group_id], item.group_id) < (quality_by_id[old.group_id], old.group_id):
                    outgoing_by_state[item.input_state] = item
            outgoing_rows = sorted(
                outgoing_by_state.values(), key=lambda item: (quality_by_id[item.group_id], item.group_id)
            )[:TOP_PER_BUCKET]
            if not outgoing_rows:
                continue
            for b in in_levels:
                incoming_by_state: dict[str, Any] = {}
                for item in incoming_by_stratum_count[(stratum, b)]:
                    old = incoming_by_state.get(item.input_state)
                    if old is None or (-quality_by_id[item.group_id], item.group_id) < (-quality_by_id[old.group_id], old.group_id):
                        incoming_by_state[item.input_state] = item
                incoming_rows = sorted(
                    incoming_by_state.values(), key=lambda item: (-quality_by_id[item.group_id], item.group_id)
                )[:TOP_PER_BUCKET]
                if not incoming_rows:
                    continue
                transition_buckets += 1
                transition = (a, b)
                for old in outgoing_rows:
                    for new in incoming_rows:
                        if old.input_state == new.input_state:
                            continue
                        gain = quality_by_id[new.group_id] - quality_by_id[old.group_id]
                        if gain <= 0:
                            continue
                        edge_candidates += 1
                        tie = hashlib.sha256(
                            f"jev-v08f-cycle-{policy_name}-{batch_id}|{old.group_id}|{new.group_id}".encode("utf-8")
                        ).hexdigest()
                        bucket = edge_buckets[transition]
                        bucket.append(Edge(old, new, a, b, gain, tie))
                if len(edge_buckets[transition]) > EDGE_CAP_PER_TRANSITION * 2:
                    edge_buckets[transition].sort(key=lambda edge: (-edge.gain, edge.tie))
                    del edge_buckets[transition][EDGE_CAP_PER_TRANSITION:]

    for key in edge_buckets:
        edge_buckets[key].sort(key=lambda edge: (-edge.gain, edge.tie))
        del edge_buckets[key][EDGE_CAP_PER_TRANSITION:]

    cycles: list[Cycle] = []
    pair_types_seen: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for transition in sorted(edge_buckets):
        a, b = transition
        partner_type = (b + 1, a - 1)
        if partner_type not in edge_buckets:
            continue
        type_pair = tuple(sorted((transition, partner_type)))
        if type_pair in pair_types_seen:
            continue
        pair_types_seen.add(type_pair)
        for first in edge_buckets[transition]:
            for second in edge_buckets[partner_type]:
                if len({first.outgoing.group_id, first.incoming.group_id,
                        second.outgoing.group_id, second.incoming.group_id}) != 4:
                    continue
                if len({first.outgoing.input_state, first.incoming.input_state,
                        second.outgoing.input_state, second.incoming.input_state}) != 4:
                    continue
                if first.gain + second.gain <= 0:
                    continue
                tie = hashlib.sha256(f"{first.tie}|{second.tie}".encode("ascii")).hexdigest()
                cycles.append(Cycle(first, second, first.gain + second.gain, tie))
    cycles.sort(key=lambda cycle: (-cycle.gain, cycle.tie))
    if len(cycles) > CYCLE_CAP:
        cycles = cycles[:CYCLE_CAP]
    return cycles, {
        "state_count_levels": len(set(state_counts.values())),
        "transition_buckets": transition_buckets,
        "positive_edges_considered": edge_candidates,
        "transition_types_with_edges": len(edge_buckets),
        "candidate_cycles": len(cycles),
        "cycle_cap": CYCLE_CAP,
        "top_per_bucket": TOP_PER_BUCKET,
        "edge_cap_per_transition": EDGE_CAP_PER_TRANSITION,
    }


def cycle_items(cycle: Cycle) -> tuple[list[Any], list[Any]]:
    return (
        [cycle.first.outgoing, cycle.second.outgoing],
        [cycle.first.incoming, cycle.second.incoming],
    )


def cycle_state_balanced(cycle: Cycle, state_counts: collections.Counter[str]) -> bool:
    return state_cycle_is_balanced(
        state_counts,
        (cycle.first.outgoing, cycle.first.incoming),
        (cycle.second.outgoing, cycle.second.incoming),
    )


def signature_delta(outgoing: list[Any], incoming: list[Any]) -> dict[str, int]:
    delta: collections.Counter[str] = collections.Counter()
    for item in outgoing:
        delta[item.supervised_signature_sha256] -= 1
    for item in incoming:
        delta[item.supervised_signature_sha256] += 1
    return {key: value for key, value in delta.items() if value}


def manifest_body(items: Iterable[Any]) -> str:
    return "".join(
        json.dumps({"group_id": item.group_id, "episode_id": item.episode_id}, separators=(",", ":")) + "\n"
        for item in sorted(items, key=lambda item: item.group_id)
    )


def write_checkpoint(out_dir: Path, arm: str, tracker: ProfileTracker, selected: dict[str, Any], state: dict[str, Any]) -> Path:
    path = out_dir / f"candidate-{arm}-ids.jsonl"
    v08e.atomic_write(path, manifest_body(selected.values()))
    metrics_path = out_dir / f"candidate-{arm}-metrics.json"
    v08e.atomic_write(metrics_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return path


def log_event(path: Path, event: dict[str, Any]) -> None:
    event = {"time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def required_family_categories(items: list[Any], floor: int) -> dict[str, set[str]]:
    all_counts = {
        axis: collections.Counter(dict(item.family_items)[axis] for item in items)
        for axis in v08e.core.FAMILY_AXES
    }
    return {axis: {key for key, count in counts.items() if count >= floor} for axis, counts in all_counts.items()}


def pairwise_state_turnover(left: list[Any], right: list[Any]) -> dict[str, Any]:
    a, b = collections.Counter(item.input_state for item in left), collections.Counter(item.input_state for item in right)
    keys_a, keys_b = set(a), set(b)
    intersection, union = keys_a & keys_b, keys_a | keys_b
    shared_mass_a = sum(a[key] for key in intersection)
    shared_mass_b = sum(b[key] for key in intersection)
    return {
        "unique_states_left": len(keys_a), "unique_states_right": len(keys_b),
        "shared_state_ids": len(intersection), "left_only_state_ids": len(keys_a - keys_b),
        "right_only_state_ids": len(keys_b - keys_a),
        "state_id_jaccard": len(intersection) / len(union) if union else 1.0,
        "left_occurrence_mass_on_shared_states": shared_mass_a / max(1, sum(a.values())),
        "right_occurrence_mass_on_shared_states": shared_mass_b / max(1, sum(b.values())),
        "left_occurrence_mass_on_replaced_states": 1.0 - shared_mass_a / max(1, sum(a.values())),
        "right_occurrence_mass_on_replaced_states": 1.0 - shared_mass_b / max(1, sum(b.values())),
    }


def optimize_arm(
    *,
    arm_name: str,
    policy_name: str,
    all_items: list[Any],
    anchor_items: list[Any],
    objective_baseline_items: list[Any] | None,
    reference_profile: dict[str, Any],
    pair_reference_profile: dict[str, Any] | None,
    score_by_id: dict[str, float],
    tolerances: dict[str, float],
    required_families: dict[str, set[str]],
    out_dir: Path,
    minutes: float,
    batch_cycles: int,
    max_batches: int,
) -> tuple[list[Any], dict[str, Any]]:
    selected = {item.group_id: item for item in anchor_items}
    tracker = ProfileTracker(anchor_items)
    state_counts: collections.Counter[str] = collections.Counter(item.input_state for item in anchor_items)
    signature_counts: collections.Counter[str] = collections.Counter(item.supervised_signature_sha256 for item in anchor_items)
    anchor_signature_counts = signature_counts.copy()
    quality = {item.group_id: item_quality(item, score_by_id, policy_name) for item in all_items}
    search_start_quality = sum(quality[item.group_id] for item in anchor_items) / len(anchor_items)
    baseline_items = anchor_items if objective_baseline_items is None else objective_baseline_items
    baseline_quality = sum(quality[item.group_id] for item in baseline_items) / len(baseline_items)
    current_quality_sum = sum(quality[item.group_id] for item in anchor_items)
    start = time.monotonic()
    deadline = start + minutes * 60.0
    events = out_dir / "optimizer-events.jsonl"
    accepted_cycles = 0
    checks = 0
    batch_summaries = []
    status = "SEARCH_BOUNDED_UNKNOWN"
    for batch_id in range(max_batches):
        if time.monotonic() >= deadline:
            break
        log_event(events, {"event": "batch_start", "arm": arm_name, "batch": batch_id,
                           "accepted_cycles_total": accepted_cycles,
                           "elapsed_seconds": time.monotonic() - start})
        print(json.dumps({"event": "batch_start", "arm": arm_name, "batch": batch_id,
                          "accepted_cycles_total": accepted_cycles}, separators=(",", ":")), flush=True)
        cycles, census = build_cycles(all_items, selected, state_counts, quality, policy_name, batch_id)
        if not cycles:
            status = "NO_BALANCED_POLICY_CYCLES_FOUND"
            log_event(events, {"event": "no_cycles", "arm": arm_name, "batch": batch_id, **census})
            break
        used_states: set[str] = set()
        used_groups: set[str] = set()
        batch_accepted = 0
        batch_rejected = 0
        batch_best_gain = 0.0
        for cycle in cycles:
            if batch_accepted >= batch_cycles or time.monotonic() >= deadline:
                break
            outgoing, incoming = cycle_items(cycle)
            state_ids = {
                item.input_state for item in outgoing + incoming
            }
            group_ids = {item.group_id for item in outgoing + incoming}
            if len(state_ids) != 4 or len(group_ids) != 4:
                continue
            if state_ids & used_states or group_ids & used_groups:
                continue
            if any(item.group_id not in selected for item in outgoing):
                continue
            if any(item.group_id in selected for item in incoming):
                continue
            if (state_counts.get(cycle.first.outgoing.input_state, 0) != cycle.first.outgoing_state_count
                    or state_counts.get(cycle.first.incoming.input_state, 0) != cycle.first.incoming_state_count
                    or state_counts.get(cycle.second.outgoing.input_state, 0) != cycle.second.outgoing_state_count
                    or state_counts.get(cycle.second.incoming.input_state, 0) != cycle.second.incoming_state_count):
                continue
            if not cycle_state_balanced(cycle, state_counts):
                continue
            sig_delta = signature_delta(outgoing, incoming)
            if not sig_delta:
                continue
            checks += 1
            references = [reference_profile]
            if pair_reference_profile is not None:
                references.append(pair_reference_profile)
            passes, comparison_rows = tracker.check(outgoing, incoming, references, tolerances, required_families)
            if not passes:
                batch_rejected += 1
                continue

            next_quality = current_quality_sum + cycle.gain
            if next_quality <= current_quality_sum + 1e-15:
                continue
            for item in outgoing:
                selected.pop(item.group_id)
                state_counts[item.input_state] -= 1
                signature_counts[item.supervised_signature_sha256] -= 1
                if state_counts[item.input_state] == 0:
                    del state_counts[item.input_state]
                if signature_counts[item.supervised_signature_sha256] == 0:
                    del signature_counts[item.supervised_signature_sha256]
            for item in incoming:
                selected[item.group_id] = item
                state_counts[item.input_state] += 1
                signature_counts[item.supervised_signature_sha256] += 1
            tracker.apply(outgoing, incoming)
            current_quality_sum = next_quality
            accepted_cycles += 1
            batch_accepted += 1
            batch_best_gain = max(batch_best_gain, cycle.gain)
            used_states.update(state_ids)
            used_groups.update(group_ids)
            current_d_supervised = training_signature_distance_from_counts(anchor_signature_counts, signature_counts)
            if accepted_cycles % CHECKPOINT_EVERY == 0:
                metrics = {
                    "arm": arm_name, "policy": policy_name, "accepted_cycles": accepted_cycles,
                    "accepted_row_replacements": 4 * accepted_cycles,
                    "objective_mean": next_quality / v08e.TARGET,
                    "objective_mean_at_anchor": baseline_quality,
                    "objective_mean_at_search_start": search_start_quality,
                    "objective_gain_per_group": (next_quality / v08e.TARGET) - baseline_quality,
                    "D_supervised_from_search_start": current_d_supervised,
                    "state_histogram_exact_to_anchor": tracker.hists["state_input_counts"] == v08e.core.histogram(reference_profile["state_input_counts"]),
                    "elapsed_seconds": time.monotonic() - start,
                    "model_contact": False, "feature_extraction": False, "phoenix_access": False,
                }
                checkpoint = write_checkpoint(out_dir, arm_name, tracker, selected, metrics)
                log_event(events, {"event": "checkpoint", "arm": arm_name,
                                   "manifest_sha256": sha256(checkpoint), **metrics})
            if next_quality / v08e.TARGET > baseline_quality + 1e-15:
                status = "POLICY_OBJECTIVE_IMPROVED"
        elapsed = time.monotonic() - start
        current_quality = current_quality_sum / v08e.TARGET
        d_supervised = training_signature_distance_from_counts(anchor_signature_counts, signature_counts)
        batch_summary = {
            "batch": batch_id, "elapsed_seconds": elapsed, "candidate_cycles": census["candidate_cycles"],
            "profile_checks_total": checks, "accepted_cycles_total": accepted_cycles,
            "accepted_cycles_batch": batch_accepted, "profile_rejections_batch": batch_rejected,
            "batch_best_policy_gain": batch_best_gain, "objective_mean": current_quality,
            "objective_gain_per_group": current_quality - baseline_quality,
            "D_supervised_from_search_start": d_supervised,
            "state_occurrence_histogram_tv_to_anchor": v08e.core.tv_distance(
                v08e.core.histogram(reference_profile["state_input_counts"]),
                tracker.hists["state_input_counts"],
            ),
            "selector_occurrence_histogram_tv_to_anchor": v08e.core.tv_distance(
                v08e.core.histogram(reference_profile["selector_input_counts"]),
                tracker.hists["selector_input_counts"],
            ),
            "root_occurrence_histogram_tv_to_anchor": v08e.core.tv_distance(
                v08e.core.histogram(reference_profile["root_counts"]),
                tracker.hists["root_counts"],
            ),
            "cycle_census": census,
        }
        batch_summaries.append(batch_summary)
        log_event(events, {"event": "batch_end", "arm": arm_name, **batch_summary})
        checkpoint_state = {
            "arm": arm_name, "policy": policy_name, "accepted_cycles": accepted_cycles,
            "accepted_row_replacements": 4 * accepted_cycles,
            "objective_mean": current_quality, "objective_mean_at_anchor": baseline_quality,
            "objective_mean_at_search_start": search_start_quality,
            "objective_gain_per_group": current_quality - baseline_quality,
            "D_supervised_from_search_start": d_supervised,
            "state_histogram_exact_to_anchor": tracker.hists["state_input_counts"] == v08e.core.histogram(reference_profile["state_input_counts"]),
            "elapsed_seconds": elapsed, "last_batch": batch_summary,
            "model_contact": False, "feature_extraction": False, "phoenix_access": False,
        }
        checkpoint = write_checkpoint(out_dir, arm_name, tracker, selected, checkpoint_state)
        if batch_accepted == 0:
            status = "PROFILE_VALID_POLICY_NEIGHBORHOOD_STALLED"
            break
    if time.monotonic() >= deadline:
        status = "SEARCH_BOUNDED_UNKNOWN"

    result_items = list(selected.values())
    result_profile = v08e.core.profile(result_items)
    refs = [reference_profile]
    if pair_reference_profile is not None:
        refs.append(pair_reference_profile)
    final_checks = [v08e.core.profile_check(ref, result_profile, tolerances) for ref in refs]
    current_quality = current_quality_sum / v08e.TARGET
    signature_distance = v08e.core.signature_ops.multiset_distance(
        anchor_signature_counts.elements(), signature_counts.elements()
    ) if hasattr(v08e.core, "signature_ops") else training_signature_distance_from_counts(anchor_signature_counts, signature_counts)
    report = {
        "status": status,
        "arm": arm_name,
        "policy": policy_name,
        "policy_semantics": (
            "frozen v0.8 global rarity-weighted equal-axis curation score, maximized"
            if policy_name == "curated" else
            "frozen v0.8 SHA-256 random priority, minimized (reported as 1-priority quality)"
        ),
        "objective_mean_at_anchor": baseline_quality,
        "objective_mean_at_search_start": search_start_quality,
        "objective_mean_final": current_quality,
        "objective_gain_per_group": current_quality - baseline_quality,
        "objective_direction_pass": current_quality > baseline_quality,
        "accepted_cycles": accepted_cycles,
        "accepted_row_replacements": 4 * accepted_cycles,
        "profile_checks": checks,
        "elapsed_seconds": time.monotonic() - start,
        "D_supervised_from_search_start": signature_distance,
        "profile_checks_final": final_checks,
        "profile_pass_final": all(row["all_pass"] for row in final_checks),
        "batch_summaries": batch_summaries,
        "bounded_optimality": "not claimed; deterministic restricted cycle neighborhood with capped per-transition edge pools",
        "model_contact": False, "feature_extraction": False, "phoenix_access": False,
    }
    write_checkpoint(out_dir, arm_name, tracker, selected, report)
    return result_items, report


def load_inputs() -> tuple[dict[str, Any], dict[str, Any], list[Any], list[Any], dict[str, float], dict[str, float]]:
    contract = v08e.require_v03_integrity()
    receipt_path = SEALED / "integrity-receipt.json"
    profile_path = SEALED / "pstar-profile.json"
    receipt = policy.read_json(receipt_path)
    if receipt.get("status") != "SEALED_PSTAR_PROFILE_AND_CAPACITY_WITNESS":
        raise ValueError("P* profile receipt is not sealed")
    if sha256(profile_path) != receipt.get("sealed_profile_sha256"):
        raise ValueError("sealed P* profile hash mismatch")
    profile_body = policy.read_json(profile_path)
    if profile_body.get("status") != "PSTAR_PROFILE_FROZEN":
        raise ValueError("P* profile status mismatch")
    items, _by_stratum, _quota, feature_counts, features_by_id = policy.selection_features_and_pool(
        contract, profile_body["stratum_counts"]
    )
    scores = {item.group_id: policy.curation_score(features_by_id[item.group_id], feature_counts) for item in items}
    by_id = {item.group_id: item for item in items}
    ids = read_ids(REPAIR / "best-witness-a-ids.jsonl")
    if len(ids) != v08e.TARGET or len(set(ids)) != v08e.TARGET or not set(ids) <= set(by_id):
        raise ValueError("P* anchor A is malformed or no longer in eligible support")
    anchor = [by_id[identity] for identity in ids]
    anchor_profile = policy.thaw_profile(profile_body["anchor_profile"])
    limits = contract["design"]["profile_constraints"]
    tolerances = {
        "unique_relative_error_max": limits["unique_input_relative_error_max"],
        "occurrence_histogram_tv_max": limits["input_occurrence_histogram_tv_max"],
        "marginal_tv_max": limits["extra_family_axis_tv_max"],
    }
    return contract, profile_body, items, anchor, scores, tolerances


def load_seed_arm(path: Path, by_id: dict[str, Any], label: str) -> list[Any]:
    ids = read_ids(path)
    if len(ids) != v08e.TARGET or len(set(ids)) != v08e.TARGET:
        raise ValueError(f"{label} seed must contain exactly {v08e.TARGET} unique IDs")
    missing = set(ids) - set(by_id)
    if missing:
        raise ValueError(f"{label} seed has {len(missing)} IDs outside current eligible support")
    return [by_id[identity] for identity in ids]


def independent_validation(
    contract: dict[str, Any],
    all_items: list[Any],
    anchor: list[Any],
    random_items: list[Any],
    curated_items: list[Any],
    tolerances: dict[str, float],
) -> dict[str, Any]:
    random_ids = [item.group_id for item in random_items]
    curated_ids = [item.group_id for item in curated_items]
    reloaded_r = policy.independent_reload(random_ids)
    reloaded_c = policy.independent_reload(curated_ids)
    profile_anchor = v08e.core.profile(anchor)
    profile_r, profile_c = v08e.core.profile(reloaded_r), v08e.core.profile(reloaded_c)
    checks = {
        "R_vs_Pstar": v08e.core.profile_check(profile_anchor, profile_r, tolerances),
        "C_vs_Pstar": v08e.core.profile_check(profile_anchor, profile_c, tolerances),
        "R_vs_C": v08e.core.profile_check(profile_r, profile_c, tolerances),
    }
    floor = int(contract["design"]["required_family_category_min_population"])
    coverages = [
        v08e.core.full_profile_coverage(all_items, all_items, bank, floor)
        for bank in (reloaded_r, reloaded_c)
    ]
    held_ids = {
        str(json.loads(line)["group_id"])
        for line in Path(contract["inputs"]["heldout_manifest"]["path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    held_overlap = (set(random_ids) | set(curated_ids)) & held_ids
    distance = v08e.core.exact_training_distance(reloaded_r, reloaded_c)
    return {
        "status": "PASS" if all(row["all_pass"] for row in checks.values())
        and all(value["all_core_categories_retained"] and value["family_min_population_categories_retained"] for value in coverages)
        and not held_overlap and distance["exact_training_signature_distance"] >= TREATMENT_GATE else "FAIL",
        "selected_group_counts": [len(reloaded_r), len(reloaded_c)],
        "selected_group_ids_unique": len(set(random_ids)) == len(random_ids) and len(set(curated_ids)) == len(curated_ids),
        "cross_arm_group_id_overlap": len(set(random_ids) & set(curated_ids)),
        "heldout_group_id_overlap": len(held_overlap),
        "profile_checks": checks,
        "coverage": coverages,
        "training_distance": distance,
        "state_turnover": pairwise_state_turnover(reloaded_r, reloaded_c),
        "reloaded_from_source_index": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes-per-arm", type=float, default=12.0)
    parser.add_argument("--batch-cycles", type=int, default=BATCH_CYCLES)
    parser.add_argument("--max-batches", type=int, default=12)
    parser.add_argument("--run-dir", type=Path, default=OUT)
    parser.add_argument("--curated-seed", type=Path)
    parser.add_argument("--random-seed", type=Path)
    args = parser.parse_args()
    if args.run_dir.exists():
        raise FileExistsError(f"refusing to reuse balanced-cycle output: {args.run_dir}")
    if (args.curated_seed is None) != (args.random_seed is None):
        raise ValueError("provide both --curated-seed and --random-seed, or neither")
    contract, profile_body, all_items, anchor, scores, tolerances = load_inputs()
    args.run_dir.mkdir(parents=True, exist_ok=False)
    anchor_profile = policy.thaw_profile(profile_body["anchor_profile"])
    by_id = {item.group_id: item for item in all_items}
    if args.curated_seed is None:
        curated_seed = random_seed = anchor
        random_seed_profile = None
        seed_sources: dict[str, Any] = {"mode": "Pstar_anchor"}
    else:
        curated_seed = load_seed_arm(args.curated_seed, by_id, "curated")
        random_seed = load_seed_arm(args.random_seed, by_id, "random")
        # Rebuild seed records from the immutable source index before allowing
        # them to become search incumbents.
        curated_seed = policy.independent_reload([item.group_id for item in curated_seed])
        random_seed = policy.independent_reload([item.group_id for item in random_seed])
        seed_checks = {
            "C_vs_Pstar": v08e.core.profile_check(anchor_profile, v08e.core.profile(curated_seed), tolerances),
            "R_vs_Pstar": v08e.core.profile_check(anchor_profile, v08e.core.profile(random_seed), tolerances),
            "C_vs_R": v08e.core.profile_check(v08e.core.profile(curated_seed), v08e.core.profile(random_seed), tolerances),
        }
        if not all(row["all_pass"] for row in seed_checks.values()):
            raise ValueError(f"seed candidates failed independent P* profile validation: {seed_checks}")
        random_seed_profile = v08e.core.profile(random_seed)
        seed_sources = {
            "mode": "independently_reloaded_v02_candidates",
            "curated": {"path": str(args.curated_seed), "sha256": sha256(args.curated_seed)},
            "random": {"path": str(args.random_seed), "sha256": sha256(args.random_seed)},
            "profile_checks": seed_checks,
        }
    family_floor = int(contract["design"]["required_family_category_min_population"])
    required_families = required_family_categories(all_items, family_floor)
    anchor_check = v08e.core.profile_check(anchor_profile, v08e.core.profile(anchor), tolerances)
    if not anchor_check["all_pass"]:
        raise ValueError("independently reconstructed anchor A no longer passes P*")
    log_event(args.run_dir / "optimizer-events.jsonl", {
        "event": "run_start", "Pstar_profile_sha256": sha256(SEALED / "pstar-profile.json"),
        "eligible_groups": len(all_items), "anchor_groups": len(anchor),
        "strata": len(profile_body["stratum_counts"]), "state_exposure_matches_histogram_not_identity": True,
        "curated_search_pair_reference": random_seed_profile is not None,
        "seed_sources": seed_sources,
        "model_contact": False, "feature_extraction": False, "training": False, "phoenix_access": False,
    })
    anchor_checkpoint = {
        "status": "VALID_PSTAR_ANCHOR_BEFORE_SEARCH",
        "accepted_cycles": 0,
        "objective_direction_pass": False,
        "D_supervised_from_anchor": 0.0,
        "profile_pass": True,
        "model_contact": False,
        "feature_extraction": False,
        "phoenix_access": False,
    }
    for arm, seed in (("C100-star", curated_seed), ("R100-star", random_seed)):
        initial_state = dict(anchor_checkpoint)
        initial_state["seed_group_count"] = len(seed)
        initial_state["seed_profile_pass"] = v08e.core.profile_check(
            anchor_profile, v08e.core.profile(seed), tolerances
        )["all_pass"]
        write_checkpoint(args.run_dir, arm, ProfileTracker(seed),
                         {item.group_id: item for item in seed}, initial_state)

    curated, curated_report = optimize_arm(
        arm_name="C100-star", policy_name="curated", all_items=all_items, anchor_items=curated_seed,
        objective_baseline_items=anchor,
        reference_profile=anchor_profile, pair_reference_profile=random_seed_profile, score_by_id=scores,
        tolerances=tolerances, required_families=required_families, out_dir=args.run_dir,
        minutes=args.minutes_per_arm, batch_cycles=args.batch_cycles, max_batches=args.max_batches,
    )
    curated_profile = v08e.core.profile(curated)
    random_items, random_report = optimize_arm(
        arm_name="R100-star", policy_name="random", all_items=all_items, anchor_items=random_seed,
        objective_baseline_items=anchor,
        reference_profile=anchor_profile, pair_reference_profile=curated_profile, score_by_id=scores,
        tolerances=tolerances, required_families=required_families, out_dir=args.run_dir,
        minutes=args.minutes_per_arm, batch_cycles=args.batch_cycles, max_batches=args.max_batches,
    )
    validation = independent_validation(contract, all_items, anchor, random_items, curated, tolerances)
    random_obj_pass = random_report["objective_direction_pass"]
    curated_obj_pass = curated_report["objective_direction_pass"]
    ready = (
        validation["status"] == "PASS" and random_obj_pass and curated_obj_pass
        and validation["training_distance"]["exact_training_signature_distance"] >= TREATMENT_GATE
    )
    result = {
        "protocol": "jev-information-density-v0.8f-policy-mobility-balanced-cycles",
        "status": "POLICY_ARMS_READY_MODEL_CONTACT_NOT_AUTHORIZED" if ready else "BOUNDED_POLICY_SEARCH_NOT_READY",
        "semantic_contract": {
            "Pstar_profile_sha256": sha256(SEALED / "pstar-profile.json"),
            "state_exposure_semantics": "match the distribution of selected state multiplicities and unique-state tolerance; state identities may differ and are treatment telemetry",
            "Pstar_changed": False, "curation_objective_changed": False,
            "random_priority_changed": False, "target_group_count": v08e.TARGET,
            "D_train_gate": TREATMENT_GATE,
            "curated_search_preserves_random_seed_profile": random_seed_profile is not None,
        },
        "search_seed_sources": seed_sources,
        "curated_arm_search": curated_report,
        "random_arm_search": random_report,
        "independent_validation": validation,
        "model_contact_authorized": False,
        "feature_extraction": False, "training": False, "phoenix_access": False,
    }
    result_path = args.run_dir / "balanced-cycle-search.json"
    v08e.atomic_write(result_path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    receipt = {
        "status": result["status"],
        "Pstar_profile_sha256": sha256(SEALED / "pstar-profile.json"),
        "source_hashes": {
            "cycle_search": sha256(Path(__file__)),
            "policy_builder": sha256(Path(policy.__file__)),
            "sealed_profile": sha256(SEALED / "pstar-profile.json"),
            "sealed_receipt": sha256(SEALED / "integrity-receipt.json"),
            "source_db": sha256(DB),
        },
        "result_sha256": sha256(result_path),
        "candidate_manifests": {
            name: {"path": str(args.run_dir / f"candidate-{name}-ids.jsonl"),
                   "sha256": sha256(args.run_dir / f"candidate-{name}-ids.jsonl")}
            for name in ("C100-star", "R100-star")
        },
        "authorization": {"model_contact": False, "feature_extraction": False, "training": False, "phoenix_access": False},
    }
    v08e.atomic_write(args.run_dir / "integrity-receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "status": result["status"],
        "curated_gain": curated_report["objective_gain_per_group"],
        "random_gain": random_report["objective_gain_per_group"],
        "D_train": validation["training_distance"]["exact_training_signature_distance"],
        "state_jaccard": validation["state_turnover"]["state_id_jaccard"],
        "run_directory": str(args.run_dir),
    }, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
