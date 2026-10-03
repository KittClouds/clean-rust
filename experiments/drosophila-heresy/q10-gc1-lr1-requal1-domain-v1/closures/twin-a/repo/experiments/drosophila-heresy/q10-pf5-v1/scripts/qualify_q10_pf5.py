"""Read-only lineage and search-contract qualification for Q10-PF5.

This module validates the frozen Q10-RMT parent and exposes small contract
primitives used by the PF5 runner. It does not run a repair or write a receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PROTOCOL = "Q10-PF5"
RMT_PROTOCOL = "Q10-RMT"
CHOICES = (0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16)
PREFIX_LENGTHS = (1, 2, 4, 8, 16)
EXACT_PRODUCT_LIMIT = 4_096
BEAM_WIDTH = 32
EXPLOIT_WIDTH = 24
EXPLORE_WIDTH = 8
MAX_ROUNDS = 8
MAX_NODES_PER_GROUP = 8_192


class QualificationError(RuntimeError):
    """A fail-closed contract or lineage violation."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def from_bits(raw: int) -> float:
    return struct.unpack("<f", struct.pack("<I", raw & 0xFFFF_FFFF))[0]


def nextafter32(value: float, upward: bool) -> float:
    """Return the adjacent finite binary32 value, preserving signed zero."""
    raw = bits(value)
    require(not math.isnan(value), "NaN cannot be a prefix endpoint")
    if raw == 0x0000_0000 and not upward:
        return from_bits(0x8000_0001)
    if raw == 0x8000_0000 and upward:
        return from_bits(0x0000_0001)
    if raw == 0x7F80_0000 and upward:
        return value
    if raw == 0xFF80_0000 and not upward:
        return value
    if raw & 0x8000_0000:
        raw += -1 if upward else 1
    else:
        raw += 1 if upward else -1
    return from_bits(raw)


def prefix_value(value: float, choice: int) -> float:
    """Apply exactly one ordered nextafter32 prefix to a cloned scalar."""
    require(choice in CHOICES, f"illegal prefix choice: {choice}")
    result = value
    for _ in range(abs(choice)):
        result = nextafter32(result, choice > 0)
    return result


def canonical_zero(raw: int) -> int:
    return 0x8000_0000 if (raw & 0x7FFF_FFFF) == 0 else raw


def ordered_bits(raw: int) -> int:
    raw = canonical_zero(raw)
    magnitude = raw & 0x7FFF_FFFF
    return 0x8000_0000 - magnitude if raw & 0x8000_0000 else 0x8000_0000 + raw


def ulp_distance(left: float, right: float) -> int:
    return abs(ordered_bits(bits(left)) - ordered_bits(bits(right)))


@dataclass(frozen=True)
class Objective:
    mismatch_rows: int
    total_ulp_distance: int
    residual_l2: float
    maximum_absolute_residual: float
    stable_prefix_tuple: tuple[int, ...] = ()

    def key(self) -> tuple[Any, ...]:
        require(math.isfinite(self.residual_l2), "non-finite residual L2")
        require(math.isfinite(self.maximum_absolute_residual), "non-finite residual")
        return (
            self.mismatch_rows,
            self.total_ulp_distance,
            self.residual_l2,
            self.maximum_absolute_residual,
            self.stable_prefix_tuple,
        )


@dataclass(frozen=True)
class GeometryDebt:
    axis: float
    norm: float
    cue_linear: float

    def within(self, guard: "GeometryDebt") -> bool:
        return (
            abs(self.axis) <= guard.axis
            and abs(self.norm) <= guard.norm
            and abs(self.cue_linear) <= guard.cue_linear
        )


@dataclass(frozen=True)
class BeamState:
    prefix_tuple: tuple[int, ...]
    objective: Objective
    debt: GeometryDebt
    threshold_class: str = "unknown"
    coverage_signature: tuple[int, ...] = ()


@dataclass(frozen=True)
class ReplayPlan:
    mode: str
    coverage: str
    cartesian_product: int


def stable_token(state: BeamState) -> str:
    payload = json.dumps(
        {
            "prefix": state.prefix_tuple,
            "objective": state.objective.key(),
            "debt": (state.debt.axis, state.debt.norm, state.debt.cue_linear),
            "threshold": state.threshold_class,
            "coverage": state.coverage_signature,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def diversity_signature(state: BeamState) -> tuple[Any, ...]:
    debt_bucket = tuple(round(value, 12) for value in (state.debt.axis, state.debt.norm, state.debt.cue_linear))
    return (state.threshold_class, debt_bucket, state.coverage_signature)


def select_beam(
    states: Iterable[BeamState],
    *,
    exploit_width: int = EXPLOIT_WIDTH,
    explore_width: int = EXPLORE_WIDTH,
) -> tuple[BeamState, ...]:
    """Select fixed exploit and diversity lanes without a monotonicity filter."""
    require(exploit_width >= 0 and explore_width >= 0, "negative beam width")
    candidates = sorted(states, key=lambda item: (item.objective.key(), stable_token(item)))
    exploit = candidates[:exploit_width]
    used = {stable_token(item) for item in exploit}
    remaining = [item for item in candidates if stable_token(item) not in used]
    representatives: dict[tuple[Any, ...], BeamState] = {}
    for item in remaining:
        signature = diversity_signature(item)
        previous = representatives.get(signature)
        if previous is None or (item.objective.key(), stable_token(item)) < (previous.objective.key(), stable_token(previous)):
            representatives[signature] = item
    exploration = sorted(
        representatives.values(),
        key=lambda item: (diversity_signature(item), item.objective.key(), stable_token(item)),
    )[:explore_width]
    used.update(stable_token(item) for item in exploration)
    if len(exploration) < explore_width:
        for item in remaining:
            token = stable_token(item)
            if token not in used:
                exploration.append(item)
                used.add(token)
            if len(exploration) == explore_width:
                break
    return tuple(exploit + exploration)


def replay_plan(domains: Sequence[Sequence[int]], *, product_limit: int = EXACT_PRODUCT_LIMIT, node_limit: int = MAX_NODES_PER_GROUP) -> ReplayPlan:
    cardinality = 1
    for domain in domains:
        require(bool(domain), "empty coordinate domain")
        cardinality *= len(domain)
        if cardinality > node_limit:
            return ReplayPlan("OVERSIZE_UNTESTED", "incomplete", cardinality)
    if cardinality <= product_limit:
        return ReplayPlan("EXACT_ENUMERATION", "complete", cardinality)
    return ReplayPlan("BOUNDED_BEAM", "partial", cardinality)


def no_helpful_row_diagnostic() -> str:
    """The RMT zero-helpful label never becomes an endpoint class alone."""
    return "NO_INDIVIDUAL_HELPFUL_AUTHORITY"


def classify_endpoint(
    *,
    exact_target: bool,
    improved: bool,
    final_geometry_pass: bool,
    coverage_complete: bool,
    bounded_search_exhausted: bool = False,
    oversize: bool = False,
    additive_screen_reject: bool = False,
) -> str:
    if oversize:
        return "OVERSIZE_UNTESTED"
    if additive_screen_reject and coverage_complete:
        return "RELAXATION_OUTSIDE_ADDITIVE_DOMAIN"
    if exact_target and final_geometry_pass:
        return "EXACT_TARGET_REACHED"
    if improved and final_geometry_pass:
        return "PARTIAL_FEASIBILITY_FOUND"
    if bounded_search_exhausted:
        return "INCONCLUSIVE_BOUNDED_SEARCH"
    if coverage_complete:
        return "BLOCKED_WITHIN_DECLARED_DOMAIN"
    if not coverage_complete:
        return "INCONCLUSIVE_BOUNDED_SEARCH"
    raise QualificationError("unreachable endpoint classification")


def _resolve(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def resolve_receipt_path(rmt_root: Path, receipt_root: str, manifest_path: str) -> Path:
    """Resolve a manifest entry below the RMT root without dropping prefixes."""
    root = Path(receipt_root)
    relative = Path(manifest_path)
    require(not relative.is_absolute(), f"absolute receipt manifest path: {manifest_path}")
    require(".." not in relative.parts, f"receipt manifest traversal: {manifest_path}")
    require(relative.parts[: len(root.parts)] == root.parts, f"receipt outside canonical root: {manifest_path}")
    return rmt_root / relative


def _check_hash(path: Path, expected: str, label: str) -> None:
    require(path.is_file(), f"missing {label}: {path}")
    actual = digest(path)
    require(actual == expected.upper(), f"hash mismatch for {label}: {path}")


def _check_forbidden_keys(value: Any, forbidden: set[str], location: str = "receipt") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            require(str(key).lower() not in forbidden, f"forbidden field {key!r} at {location}")
            _check_forbidden_keys(nested, forbidden, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _check_forbidden_keys(nested, forbidden, f"{location}[{index}]")


def audit_parent(protocol_root: Path) -> dict[str, int]:
    contract = load_json(protocol_root / "CONTRACT.json")
    require(contract["protocol"] == PROTOCOL, "Q10-PF5 contract identity mismatch")
    _check_hash(protocol_root / "PLAN.md", contract["plan_sha256"], "Q10-PF5 PLAN.md")

    repo_root = protocol_root.parents[2]
    parent = contract["parent"]
    rmt_root = _resolve(repo_root, parent["rmt_root"])
    for name, filename in (
        ("rmt_result_sha256", "RESULT.md"),
        ("rmt_status_sha256", "STATUS.json"),
        ("rmt_plan_sha256", "PLAN.md"),
        ("rmt_contract_sha256", "CONTRACT.json"),
        ("rmt_config_sha256", "q10-rmt-config.json"),
        ("rmt_preexecution_sha256", "PREEXECUTION.json"),
    ):
        _check_hash(rmt_root / filename, parent[name], f"Q10-RMT {filename}")

    preexecution = load_json(rmt_root / "PREEXECUTION.json")
    require(preexecution["protocol"] == RMT_PROTOCOL, "parent PREEXECUTION protocol mismatch")
    require(preexecution["status"] == "FROZEN_PRE_EXECUTION", "parent PREEXECUTION is not frozen")
    require(preexecution["source_manifest"] == parent["source_manifest"], "parent source manifest drift")
    for entry in parent["source_manifest"]:
        _check_hash(rmt_root / entry["path"], entry["sha256"], f"Q10-RMT source {entry['path']}")

    expected_source_root = _resolve(repo_root, parent["source_input_root"]).resolve()
    actual_source_root = Path(preexecution["input_root"]).resolve()
    require(actual_source_root == expected_source_root, "Q10-RMT input root drift")
    require(preexecution["input_sha256"] == parent["source_input_sha256"], "Q10-RMT source input manifest drift")
    for filename, expected in parent["source_input_sha256"].items():
        _check_hash(expected_source_root / filename, expected, f"Q10-RMT source input {filename}")

    da2_root = Path(preexecution["parent_root"]).resolve()
    da2_results_path = da2_root / "qualification/sample-9731-9732/results.json"
    _check_hash(da2_results_path, parent["da2_results_sha256"], "Q10-DA2 results")
    da2_results = json.loads(da2_results_path.read_text(encoding="utf-8"))
    require(isinstance(da2_results, list) and len(da2_results) == 32, "Q10-DA2 result cardinality mismatch")

    receipt_root = rmt_root / parent["receipt_root"]
    require(receipt_root.is_dir(), f"missing canonical Q10-RMT receipt root: {receipt_root}")
    receipt_paths = [entry["path"] for entry in parent["receipt_manifest"]]
    require(len(receipt_paths) == len(set(receipt_paths)), "duplicate canonical receipt manifest path")
    require(all(entry.startswith(parent["receipt_root"] + "/") for entry in receipt_paths), "receipt escapes canonical root")
    for entry in parent["receipt_manifest"]:
        receipt_path = resolve_receipt_path(rmt_root, parent["receipt_root"], entry["path"])
        _check_hash(receipt_path, entry["sha256"], f"Q10-RMT receipt {entry['path']}")
    actual_receipt_paths = {
        parent["receipt_root"] + "/" + path.relative_to(receipt_root).as_posix()
        for path in receipt_root.rglob("*")
        if path.is_file()
    }
    require(actual_receipt_paths == set(receipt_paths), "canonical receipt root contains an unbound or missing file")

    status = load_json(rmt_root / "STATUS.json")
    require(status["protocol"] == RMT_PROTOCOL, "parent STATUS protocol mismatch")
    require(status["status"] == "Q10_RMT_VALID__TOPOLOGY_MAPPED", "parent STATUS is not valid")
    require(status["receipts"]["execution"] == "qualification/sample-9731-9732/execution.json", "parent STATUS receipt drift")
    execution = load_json(receipt_root / "execution.json")
    summary = load_json(receipt_root / "authority-summary.json")
    invariants = contract["topology_invariants"]
    require(execution["protocol"] == RMT_PROTOCOL, "receipt execution protocol mismatch")
    require(execution["status"] == "Q10_RMT_VALID__TOPOLOGY_MAPPED", "receipt execution status mismatch")
    require(execution["primary_valid_endpoints"] == contract["scope"]["primary_endpoints"], "primary endpoint count mismatch")
    require(execution["excluded_noncontract_endpoints"] == contract["scope"]["excluded_da2_geometry_failures"], "excluded endpoint count mismatch")
    require(execution["mismatch_rows_mapped"] == invariants["mismatch_rows"], "mismatch row count mismatch")
    require(execution["component_records"] == invariants["helpful_components"], "component count mismatch")
    require(execution["local_replay_checks"] == invariants["local_replay_checks"], "replay check count mismatch")
    require(execution["local_replay_passes"] == invariants["local_replay_passes"], "replay pass count mismatch")
    require(execution["repair_applied"] is False, "parent reports a repair")
    require(execution["behavioral_inference"] is False, "parent reports behavioral inference")
    require(execution["scientific_seed_bundles_used"] == 0, "parent reports scientific bundles")
    require(execution["dh08b_authorized"] is False, "parent authorizes DH08B")
    for field, expected in (
        ("endpoint_count", 28),
        ("excluded_noncontract_endpoints", 4),
        ("mismatch_rows_total", invariants["mismatch_rows"]),
        ("one_step_orphan_rows", invariants["one_step_orphan_rows"]),
        ("one_step_fragile_rows", invariants["one_step_fragile_rows"]),
        ("immediate_rows", invariants["k_star_counts"]["1"]),
        ("threshold_gated_rows", sum(invariants["k_star_counts"][str(k)] for k in (2, 4, 8, 16))),
        ("no_local_authority_rows", invariants["k_star_counts"]["none"]),
        ("largest_component_rows", invariants["largest_helpful_component_rows"]),
    ):
        require(summary[field] == expected, f"authority summary mismatch: {field}")

    endpoints = json.loads((receipt_root / "endpoints.json").read_text(encoding="utf-8"))
    excluded = json.loads((receipt_root / "excluded-noncontract.json").read_text(encoding="utf-8"))
    require(len(endpoints) == 28 and len(excluded) == 4, "endpoint receipt cardinality mismatch")
    identities = [(item["source_event"], item["set_index"]) for item in endpoints]
    require(len(identities) == len(set(identities)), "duplicate primary endpoint identity")
    expected_primary = {
        (item["source_event"], item["set_index"])
        for item in da2_results
        if item["status"] == "DA2_GEOMETRY_PASS"
    }
    expected_excluded = {
        (item["source_event"], item["set_index"])
        for item in da2_results
        if item["status"] != "DA2_GEOMETRY_PASS"
    }
    actual_primary = set(identities)
    actual_excluded = {(item["source_event"], item["set_index"]) for item in excluded}
    require(actual_primary == expected_primary, "primary RMT endpoint identities do not match sealed DA2 pass set")
    require(actual_excluded == expected_excluded, "excluded RMT endpoint identities do not match sealed DA2 failure set")
    for shard in execution["shard_receipts"]:
        shard_path = Path(shard["path"])
        lowered = {part.lower() for part in shard_path.parts}
        require(not lowered.intersection({"archived", "failed", "probe"}), "noncanonical shard in merged receipt")
        shard_root = rmt_root / shard_path
        for filename, expected in shard["sha256"].items():
            _check_hash(shard_root / filename, expected, f"Q10-RMT shard {shard['path']}/{filename}")

    forbidden = {field.lower() for field in contract["forbidden_fields"]}
    _check_forbidden_keys(execution, forbidden, "receipt.execution")
    _check_forbidden_keys(summary, forbidden, "receipt.authority-summary")
    return {
        "primary_endpoints": len(endpoints),
        "excluded_endpoints": len(excluded),
        "mismatch_rows": summary["mismatch_rows_total"],
        "components": execution["component_records"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="audit the frozen Q10-PF5 parent without running the qualification")
    parser.add_argument("--protocol-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        counts = audit_parent(args.protocol_root.resolve())
    except (OSError, KeyError, TypeError, ValueError, QualificationError) as error:
        raise SystemExit(f"Q10-PF5 lineage qualification failed: {error}") from error
    print(
        "Q10-PF5 lineage qualification passed: "
        f"endpoints={counts['primary_endpoints']} excluded={counts['excluded_endpoints']} "
        f"rows={counts['mismatch_rows']} components={counts['components']}"
    )
    print("Q10-PF5 scientific run: not executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
