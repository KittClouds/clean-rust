"""Derive the fresh current-lineage RIS1 pair opportunity domain.

This file is intentionally a domain builder, not a pair replay runner. It
reconstructs current singleton receipts and the current PAR8 reference state,
then writes an immutable shortlist and pair-domain manifest.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any

PROTOCOL = "REQUAL1-RIS1-DOMAIN"
IDENTITY = "q10-gc1-lr1-requal1-ris1-domain-v2"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
DOMAIN_ROOT = ROOT.parent / "q10-gc1-lr1-requal1-domain-r2-v1"
SINGLES_ROOT = ROOT.parent / "q10-gc1-lr1-requal1-singles-v1"
PARITY_ROOT = ROOT.parent / "q10-gc1-lr1-requal1-parity-v1"
PAR8_REL = "experiments/drosophila-heresy/q10-gc1-par8-v1/qualification/execution.json"
KEYS = (
    ("seed9731-L-tau16.json", 2),
    ("seed9731-L-tau4.json", 3),
    ("seed9731-R-tau16.json", 1),
    ("seed9731-R-tau16.json", 3),
    ("seed9731-R-tau4.json", 0),
    ("seed9731-R-tau4.json", 1),
    ("seed9731-R-tau4.json", 2),
    ("seed9731-R-tau4.json", 3),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def object_hash(value: Any) -> str:
    return digest_bytes(canonical(value))


def bits_hash(values: list[int] | tuple[int, ...]) -> str:
    return digest_bytes(b"".join(int(value).to_bytes(4, "little", signed=False) for value in values))


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def score_key(score: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(score["mismatch_count"]),
        int(score["total_ulp_distance"]),
        float(score["residual_l2"]),
        float(score["maximum_absolute_residual"]),
    )


def sign(value: float) -> int:
    return -1 if value < 0.0 else (1 if value > 0.0 else 0)


def replay_bits(pf: Any, rows: tuple[tuple[int, ...], ...], weight_bits: list[int]) -> tuple[int, ...]:
    weights = tuple(pf.from_bits(value) for value in weight_bits)
    return tuple(int(value) for value in pf.readout_bits(rows, weights))


def drive_vector(pf: Any, state: Any, weight_bits: list[int]) -> tuple[float, ...]:
    weights = tuple(pf.from_bits(value) for value in weight_bits)
    displacement = tuple(value - initial for value, initial in zip(weights, state.base_weights))
    return tuple(math.fsum(displacement[i] for i in row) for row in state.rows)


def normalized_axis(geometry: dict[str, Any]) -> float:
    target = float(geometry["target_axis"])
    return (float(geometry["final_axis"]) - target) / max(abs(target), 1.0e-12)


def apply_mapping(pf: Any, state: Any, mapping: list[list[int]]) -> list[int]:
    raw = [int(value) for value in state.baseline_weight_bits]
    for coordinate, choice in mapping:
        coordinate = int(coordinate)
        choice = int(choice)
        if choice == 0:
            continue
        replacement = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        require(replacement is not None, f"current PAR8 mapping has illegal prefix {coordinate} {choice}")
        raw[coordinate] = int(replacement)
    return raw


def current_par8_reference(pf: Any, states: dict[tuple[str, int], Any], par8: dict[str, Any], pf5_contract: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for item in par8["endpoint_set_results"]:
        key = (str(item["endpoint"]), int(item["set_index"]))
        if key not in states:
            continue
        state = states[key]
        mapping = [[int(pair[0]), int(pair[1])] for pair in item["best_search"]["canonical_mapping"]]
        raw = apply_mapping(pf, state, mapping)
        readout = replay_bits(pf, state.rows, raw)
        geometry = pf.geometry_metrics(state.rows, tuple(pf.from_bits(value) for value in raw), state.base_weights, state.target_weights, state.axis)
        target = tuple(int(value) for value in state.target_readout_bits)
        residuals = [pf.from_bits(actual) - pf.from_bits(expected) for actual, expected in zip(readout, target)]
        score = {
            "mismatch_count": sum(actual != expected for actual, expected in zip(readout, target)),
            "total_ulp_distance": sum(pf.ulp_distance(pf.from_bits(actual), pf.from_bits(expected)) for actual, expected in zip(readout, target)),
            "residual_l2": math.sqrt(math.fsum(value * value for value in residuals)),
            "maximum_absolute_residual": max((abs(value) for value in residuals), default=0.0),
        }
        drive = drive_vector(pf, state, raw)
        target_drive = tuple(float(value) for value in state.target_drive)
        result[key] = {
            "canonical_mapping": mapping,
            "weight_state_sha256": bits_hash(raw),
            "readout_sha256": bits_hash(readout),
            "score": score,
            "geometry": geometry,
            "final_geometry_pass": bool(pf.final_geometry_pass(geometry, pf5_contract)),
            "axis_error_signed": normalized_axis(geometry),
            "linear_error": [float(actual - expected) for actual, expected in zip(drive, target_drive)],
        }
    require(set(result) == set(states), "current PAR8 reference coverage drift")
    return result


def enrich_singletons(pf: Any, data: dict[str, Any], rows_by_key: dict[tuple[str, int], list[dict[str, Any]]], references: dict[tuple[str, int], dict[str, Any]], pf5_contract: dict[str, Any]) -> dict[tuple[str, int], list[dict[str, Any]]]:
    gates = pf5_contract["geometry"]["final_da2_gates"]
    states = {state.key: state for state in data["states"]}
    enriched: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for key, rows in rows_by_key.items():
        state = states[key]
        base_readout = tuple(int(value) for value in state.baseline_readout_bits)
        target_readout = tuple(int(value) for value in state.target_readout_bits)
        reference = references[key]
        ref_axis = float(reference["axis_error_signed"])
        ref_linear = tuple(float(value) for value in reference["linear_error"])
        seen: set[tuple[int, str]] = set()
        output: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            group_key = (int(row["group"]), str(row["to"]))
            require(group_key not in seen, f"duplicate singleton identity: {key} {group_key}")
            seen.add(group_key)
            mapping = [[int(pair[0]), int(pair[1])] for pair in row["canonical_mapping"]]
            raw = apply_mapping(pf, state, mapping)
            readout = replay_bits(pf, state.rows, raw)
            require(bits_hash(raw) == str(row["weight_state_sha256"]).upper(), f"singleton weight drift: {key} {index}")
            require(bits_hash(readout) == str(row["readout_sha256"]).upper(), f"singleton readout drift: {key} {index}")
            geometry = pf.geometry_metrics(state.rows, tuple(pf.from_bits(value) for value in raw), state.base_weights, state.target_weights, state.axis)
            require(geometry == row["geometry"], f"singleton geometry drift: {key} {index}")
            residuals = [pf.from_bits(actual) - pf.from_bits(expected) for actual, expected in zip(readout, target_readout)]
            score = {
                "mismatch_count": sum(actual != expected for actual, expected in zip(readout, target_readout)),
                "total_ulp_distance": sum(pf.ulp_distance(pf.from_bits(actual), pf.from_bits(expected)) for actual, expected in zip(readout, target_readout)),
                "residual_l2": math.sqrt(math.fsum(value * value for value in residuals)),
                "maximum_absolute_residual": max((abs(value) for value in residuals), default=0.0),
            }
            require(score == row["score"], f"singleton score drift: {key} {index}")
            damaged = sum(1 for base, target, actual in zip(base_readout, target_readout, readout) if base == target and actual != target)
            fixed = sum(1 for base, target, actual in zip(base_readout, target_readout, readout) if base != target and actual == target)
            max_ratio = max(
                float(geometry["axis_normalized_error"]) / float(gates["axis_normalized_abs"]),
                float(geometry["norm_normalized_error"]) / float(gates["norm_normalized_abs"]),
                float(geometry["cue_linear_normalized_error"]) / float(gates["cue_linear_normalized_abs"]),
            )
            excess = sum(max(0.0, ratio - 1.0) for ratio in (
                float(geometry["axis_normalized_error"]) / float(gates["axis_normalized_abs"]),
                float(geometry["norm_normalized_error"]) / float(gates["norm_normalized_abs"]),
                float(geometry["cue_linear_normalized_error"]) / float(gates["cue_linear_normalized_abs"]),
            ))
            linear = drive_vector(pf, state, raw)
            target_drive = tuple(float(value) for value in state.target_drive)
            linear_error = tuple(actual - expected for actual, expected in zip(linear, target_drive))
            d_axis = normalized_axis(geometry) - ref_axis
            d_linear = tuple(actual - expected for actual, expected in zip(linear_error, ref_linear))
            opp = -math.fsum(actual * expected for actual, expected in zip(d_linear, ref_linear))
            enriched_row = dict(row)
            enriched_row.update({
                "singleton_index": index,
                "damaged": int(damaged),
                "fixed": int(fixed),
                "max_ratio": float(max_ratio),
                "excess": float(excess),
                "d_axis": float(d_axis),
                "opp": float(opp),
                "bucket": [int(row["group"]), sign(d_axis), sign(opp)],
                "current_reference_axis_error": ref_axis,
                "current_reference_weight_state_sha256": reference["weight_state_sha256"],
            })
            output.append(enriched_row)
        require(len(output) == 8 * len(data["groups"][key]), f"singleton context cardinality drift: {key}")
        enriched[key] = output
    return enriched


def shortlist_legacy_shape(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_geo = sorted(rows, key=lambda item: (item["max_ratio"], item["excess"], score_key(item["score"])))
    selected: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for item in by_geo[:16]:
        identity = (int(item["group"]), str(item["to"]))
        if identity not in seen:
            seen.add(identity)
            selected.append(item)
    by_collateral = sorted(
        [item for item in rows if (int(item["group"]), str(item["to"])) not in seen],
        key=lambda item: (int(item["damaged"]), score_key(item["score"]), item["excess"]),
    )
    for item in by_collateral[:8]:
        identity = (int(item["group"]), str(item["to"]))
        if identity not in seen:
            seen.add(identity)
            selected.append(item)
    buckets: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for item in rows:
        identity = (int(item["group"]), str(item["to"]))
        if identity in seen:
            continue
        bucket = tuple(int(value) for value in item["bucket"])
        buckets.setdefault(bucket, []).append(item)
    for values in buckets.values():
        values.sort(key=lambda item: (int(item["group"]), str(item["to"])))
    bucket_order = sorted(buckets)
    offset = 0
    while len(selected) < 32 and buckets:
        progressed = False
        for bucket in bucket_order:
            values = buckets.get(bucket, [])
            if offset < len(values):
                item = values[offset]
                identity = (int(item["group"]), str(item["to"]))
                if identity not in seen:
                    seen.add(identity)
                    selected.append(item)
                    progressed = True
                if len(selected) >= 32:
                    break
        offset += 1
        if not progressed:
            break
    require(len(selected) <= 32, "shortlist exceeded frozen limit")
    return selected, {"selected_count": len(selected), "geometry_slots": 16, "collateral_slots": 8, "fill": "round-robin (group, axis-sign, opposition-sign), canonical ties"}


def derive_pairs(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for left_index in range(len(selected)):
        for right_index in range(left_index + 1, len(selected)):
            left = selected[left_index]
            right = selected[right_index]
            if int(left["group"]) == int(right["group"]):
                continue
            pairs.append({
                "pair_index": len(pairs),
                "a": {"singleton_index": int(left["singleton_index"]), "group": int(left["group"]), "to": str(left["to"])},
                "b": {"singleton_index": int(right["singleton_index"]), "group": int(right["group"]), "to": str(right["to"])},
            })
    return pairs


def load_singletons() -> dict[tuple[str, int], list[dict[str, Any]]]:
    output: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for endpoint, set_index in KEYS:
        slug = f"{endpoint.removesuffix('.json')}__set{set_index}"
        path = SINGLES_ROOT / "shards" / f"{slug}.jsonl"
        require(path.is_file(), f"missing fresh singleton shard: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        require(isinstance(value, list), f"singleton shard is not an array: {path}")
        output[(endpoint, set_index)] = value
    return output


def main() -> int:
    require(not (ROOT / "execution.json").exists(), "RIS1 domain identity already has an execution receipt")
    domain_execution = json.loads((DOMAIN_ROOT / "execution.json").read_text(encoding="utf-8"))
    singles_execution = json.loads((SINGLES_ROOT / "execution.json").read_text(encoding="utf-8"))
    parity_execution = json.loads((PARITY_ROOT / "execution.json").read_text(encoding="utf-8"))
    require(domain_execution["status"] == "DOMAIN_READY_FOR_SMOKE", "fresh domain gate is not passing")
    require(singles_execution["status"] == "SINGLES_COMPLETE", "fresh singleton gate is not passing")
    require(parity_execution["status"] == "PARITY_PASS", "fresh parity gate is not passing")
    closure_repo = Path(domain_execution["closures"]["twin-a"]["repo"])
    sys.path.insert(0, str(closure_repo / "experiments/drosophila-heresy/q10-pf5-v1/scripts"))
    pf = importlib.import_module("run_q10_pf5")
    sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1/scripts"))
    builder = importlib.import_module("build_domain_closure")
    _, data = builder.fresh_lineage(closure_repo, pf)
    states = {state.key: state for state in data["states"]}
    pf5_contract = json.loads((closure_repo / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json").read_text(encoding="utf-8"))
    par8 = json.loads((closure_repo / PAR8_REL).read_text(encoding="utf-8"))
    parent_hashes = {
        "domain_execution_sha256": digest(DOMAIN_ROOT / "execution.json"),
        "singles_execution_sha256": digest(SINGLES_ROOT / "execution.json"),
        "parity_execution_sha256": digest(PARITY_ROOT / "execution.json"),
        "closure_twin_a_derived_sha256": digest(DOMAIN_ROOT / "closures/twin-a/DERIVED.json"),
        "closure_twin_a_manifest_sha256": digest(DOMAIN_ROOT / "closures/twin-a/MANIFEST.json"),
        "current_par8_execution_sha256": digest(closure_repo / PAR8_REL),
    }
    rows_by_key = load_singletons()
    references = current_par8_reference(pf, states, par8, pf5_contract)
    enriched = enrich_singletons(pf, data, rows_by_key, references, pf5_contract)
    shortlist_records: list[dict[str, Any]] = []
    pair_records: list[dict[str, Any]] = []
    context_summaries: list[dict[str, Any]] = []
    for key in KEYS:
        selected, selector = shortlist_legacy_shape(enriched[key])
        for rank, item in enumerate(selected):
            shortlist_records.append({
                "context": [key[0], key[1]],
                "rank": rank,
                "group": int(item["group"]),
                "to": str(item["to"]),
                "singleton_index": int(item["singleton_index"]),
                "score": item["score"],
                "geometry": item["geometry"],
                "final_geometry_pass": bool(item["final_geometry_pass"]),
                "damaged": int(item["damaged"]),
                "fixed": int(item["fixed"]),
                "max_ratio": float(item["max_ratio"]),
                "excess": float(item["excess"]),
                "d_axis": float(item["d_axis"]),
                "opp": float(item["opp"]),
                "bucket": item["bucket"],
                "weight_state_sha256": str(item["weight_state_sha256"]),
                "readout_sha256": str(item["readout_sha256"]),
                "reference_weight_state_sha256": references[key]["weight_state_sha256"],
            })
        pairs = derive_pairs(selected)
        for pair in pairs:
            pair_records.append({"context": [key[0], key[1]], **pair})
        context_summaries.append({
            "context": [key[0], key[1]],
            "singleton_count": len(enriched[key]),
            "shortlist_count": len(selected),
            "cross_group_pair_count": len(pairs),
            "shortlist_groups": sorted({int(item["group"]) for item in selected}),
            "reference": references[key],
            "selector": selector,
        })
    require(len(shortlist_records) > 0, "fresh selector produced no records")
    require(len(pair_records) > 0, "fresh pair domain is empty")
    write_new(ROOT / "shortlist.json", shortlist_records)
    pair_lines = "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in pair_records)
    pair_path = ROOT / "pairs-domain.jsonl"
    require(not pair_path.exists(), f"refusing to overwrite pair domain: {pair_path}")
    pair_path.write_text(pair_lines, encoding="utf-8", newline="\n")
    manifest = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "contexts": [[key[0], key[1]] for key in KEYS],
        "ordered_shortlist_sha256": object_hash(shortlist_records),
        "ordered_pair_domain_sha256": digest(pair_path),
        "pair_domain_count": len(pair_records),
        "shortlist_count": len(shortlist_records),
        "historical_counts_not_imported": True,
        "pair_replay_executed": False,
    }
    write_new(ROOT / "DOMAIN_MANIFEST.json", manifest)
    execution = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": "RIS1_DOMAIN_READY_FOR_REPLAY",
        "engineering_only": True,
        "scientific_promotion": False,
        "behavioral_probe": False,
        "pair_replay_executed": False,
        "parent_hashes": parent_hashes,
        "domain_parents": {
            "domain": domain_execution["identity"],
            "singles": singles_execution["identity"],
            "parity": parity_execution["identity"],
            "closure": "twin-a",
        },
        "counts": {
            "contexts": len(KEYS),
            "singleton_records_revalidated": sum(len(rows) for rows in enriched.values()),
            "shortlist_records": len(shortlist_records),
            "pair_domain_records": len(pair_records),
        },
        "context_summaries": context_summaries,
        "hashes": manifest,
        "selector": json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))["selector"],
    }
    write_new(ROOT / "execution.json", execution)
    print(json.dumps(execution, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
