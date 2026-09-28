"""Materialize the fresh REQUAL1 singleton domain in immutable case shards."""
from __future__ import annotations

import concurrent.futures
import hashlib
import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any

PROTOCOL = "REQUAL1-SINGLES"
IDENTITY = "q10-gc1-lr1-requal1-singles-v1"
ROOT = Path(__file__).resolve().parents[1]
DOMAIN_ROOT = ROOT.parent / "q10-gc1-lr1-requal1-domain-r2-v1"
SMOKE_ROOT = ROOT.parent / "q10-gc1-lr1-requal1-smoke-v1"
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


def bits_hash(values: tuple[int, ...] | list[int]) -> str:
    return digest_bytes(b"".join(int(value).to_bytes(4, "little", signed=False) for value in values))


def object_hash(value: Any) -> str:
    return digest_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite singleton artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def case_slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def run_case(args: tuple[str, int, str]) -> tuple[tuple[str, int], list[dict[str, Any]]]:
    endpoint, set_index, closure_text = args
    key = (endpoint, set_index)
    closure = Path(closure_text)
    sys.path.insert(0, str(DOMAIN_ROOT / "scripts"))
    domain_builder = importlib.import_module("build_domain_closure")
    pf = domain_builder.import_pf5(closure)
    _, data = domain_builder.fresh_lineage(closure, pf)
    state = next(item for item in data["states"] if item.key == key)
    groups = data["groups"][key]
    palette_path = closure / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl"
    palette_rows = [json.loads(line) for line in palette_path.read_text(encoding="utf-8").splitlines() if line]
    by_group = {int(item["identity"][2]): item for item in palette_rows if str(item["identity"][0]) == endpoint and int(item["identity"][1]) == set_index}
    pf5_contract = json.loads((closure / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json").read_text(encoding="utf-8"))
    output: list[dict[str, Any]] = []
    for group in groups:
        item = by_group.get(group.group_index)
        require(item is not None, f"missing current palette group: {key} group={group.group_index}")
        baseline_id = str(item["baseline"]["candidate_identity"])
        nonzero = [candidate for candidate in item["palette"] if str(candidate["candidate_identity"]) != baseline_id]
        require(len(nonzero) == 8, f"current nonzero palette count drift: {key} group={group.group_index}")
        for candidate in nonzero:
            mapping = {int(coordinate): int(choice) for coordinate, choice in candidate["canonical_mapping"]}
            require(tuple(sorted(mapping)) == group.coordinates, f"singleton coordinate map drift: {key} group={group.group_index}")
            weight_bits = list(state.baseline_weight_bits)
            for coordinate, choice in mapping.items():
                if choice == 0:
                    continue
                replacement = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
                require(replacement is not None, f"singleton illegal prefix: {key} group={group.group_index}")
                weight_bits[coordinate] = replacement
            weight_hash = bits_hash(weight_bits)
            require(weight_hash == str(candidate["committed_f32_weight_state_sha256"]).upper(), f"singleton byte drift: {key} group={group.group_index}")
            weights = tuple(pf.from_bits(value) for value in weight_bits)
            readout = tuple(pf.readout_bits(state.rows, weights))
            readout_hash = bits_hash(readout)
            require(readout_hash == str(candidate["exact_readout_sha256"]).upper(), f"singleton readout drift: {key} group={group.group_index}")
            residuals = [pf.from_bits(actual) - pf.from_bits(target) for actual, target in zip(readout, state.target_readout_bits)]
            geometry = pf.geometry_metrics(state.rows, weights, state.base_weights, state.target_weights, state.axis)
            output.append({
                "endpoint": endpoint,
                "set_index": set_index,
                "group": group.group_index,
                "from": baseline_id,
                "to": str(candidate["candidate_identity"]),
                "canonical_mapping": [[int(coordinate), int(choice)] for coordinate, choice in sorted(mapping.items())],
                "weight_state_sha256": weight_hash,
                "readout_sha256": readout_hash,
                "score": {"mismatch_count": sum(actual != target for actual, target in zip(readout, state.target_readout_bits)), "total_ulp_distance": sum(pf.ulp_distance(pf.from_bits(actual), pf.from_bits(target)) for actual, target in zip(readout, state.target_readout_bits)), "residual_l2": math.sqrt(math.fsum(value * value for value in residuals)), "maximum_absolute_residual": max((abs(value) for value in residuals), default=0.0)},
                "geometry": geometry,
                "final_geometry_pass": bool(pf.final_geometry_pass(geometry, pf5_contract)),
            })
    require(len(output) == len(groups) * 8, f"singleton shard cardinality drift: {key}")
    return key, output


def main() -> int:
    require(not (ROOT / "execution.json").exists(), "singleton execution already exists")
    domain_execution_path = DOMAIN_ROOT / "execution.json"
    smoke_execution_path = SMOKE_ROOT / "execution.json"
    domain = json.loads(domain_execution_path.read_text(encoding="utf-8"))
    smoke = json.loads(smoke_execution_path.read_text(encoding="utf-8"))
    require(domain["status"] == "DOMAIN_READY_FOR_SMOKE", "domain is not ready")
    require(smoke["status"] == "SMOKE_PASS", "smoke gate is not passing")
    closure = str(domain["closures"]["twin-a"]["repo"])
    shards: dict[str, list[dict[str, Any]]] = {}
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(run_case, (key[0], key[1], closure)) for key in KEYS]
            for future in futures:
                key, rows = future.result()
                name = case_slug(key)
                shards[name] = rows
                write_new(ROOT / "shards" / f"{name}.jsonl", rows)
        ordered = [row for key in KEYS for row in shards[case_slug(key)]]
        require(len(ordered) == 3696, f"singleton total cardinality drift: {len(ordered)}")
        shard_hashes = {name: digest(ROOT / "shards" / f"{name}.jsonl") for name in sorted(shards)}
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SINGLES_COMPLETE", "engineering_only": True, "domain_execution_sha256": digest(domain_execution_path), "smoke_execution_sha256": digest(smoke_execution_path), "closure_twin": "twin-a", "counts": {"contexts": 8, "groups": 462, "nonzero_singletons": len(ordered)}, "shard_hashes": shard_hashes, "valid_geometry_count": sum(bool(row["final_geometry_pass"]) for row in ordered), "invalid_geometry_count": sum(not bool(row["final_geometry_pass"]) for row in ordered), "pair_replay_executed": False, "behavioral_probe": False, "scientific_promotion": False}
    except Exception as exc:
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_SINGLETON_MATERIALIZATION", "engineering_only": True, "error_type": type(exc).__name__, "error": str(exc), "completed_shards": sorted(shards), "pair_replay_executed": False, "behavioral_probe": False, "scientific_promotion": False}
    write_new(ROOT / "execution.json", execution)
    print(json.dumps(execution, indent=2, sort_keys=True))
    return 0 if execution["status"] == "SINGLES_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
