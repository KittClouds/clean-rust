"""Materialize complete signed constraint state records for VMAT1."""
from __future__ import annotations

import concurrent.futures
import hashlib
import importlib
import json
import math
import os
import struct
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

PROTOCOL = "Q10-CSC1-VMAT1"
IDENTITY = "q10-gc1-lr1-requal1-csc1-vmat1-v2"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
DOMAIN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_REPO = DOMAIN_ROOT / "closures/twin-a/repo"
PAIR_DOMAIN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pair-domain-v1"
PAIR_RUN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-v1"
REF_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
PF5_ROOT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1"
PAIR_KEYS = (
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


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    require(not temp.exists(), f"orphan temporary output exists: {temp}")
    temp.write_bytes(payload)
    temp.replace(path)


def write_json_atomic(path: Path, value: Any) -> None:
    write_atomic(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def bits_bytes(values: tuple[int, ...] | list[int]) -> bytes:
    out = bytearray()
    for value in values:
        out.extend(struct.pack("<I", int(value)))
    return bytes(out)


def f64_bytes(values: tuple[float, ...] | list[float]) -> bytes:
    out = bytearray()
    for value in values:
        out.extend(struct.pack("<d", float(value)))
    return bytes(out)


def bits_hash(values: tuple[int, ...] | list[int]) -> str:
    return digest_bytes(bits_bytes(values))


def score_key(score: dict[str, Any]) -> tuple[Any, ...]:
    return (int(score["mismatch_count"]), int(score["total_ulp_distance"]), float(score["residual_l2"]), float(score["maximum_absolute_residual"]))


def load_modules() -> tuple[Any, Any, Any]:
    sys.path.insert(0, str(PAIR_RUN_ROOT / "scripts"))
    pair = importlib.import_module("run_pairs")
    pf, builder = pair.load_modules()
    require(Path(pair.__file__).resolve() == (PAIR_RUN_ROOT / "scripts/run_pairs.py").resolve(), "wrong pair runtime loaded")
    require(Path(pf.__file__).resolve() == (PF5_ROOT / "scripts/run_q10_pf5.py").resolve(), "wrong PF5 runtime loaded")
    require(Path(builder.__file__).resolve() == (DOMAIN_ROOT / "scripts/build_domain_closure.py").resolve(), "wrong domain builder loaded")
    return pair, pf, builder


def load_domain_rows(key: tuple[str, int]) -> list[dict[str, Any]]:
    return load_json(PAIR_DOMAIN_ROOT / "shards" / f"{slug(key)}.jsonl")


def load_run_rows(key: tuple[str, int]) -> dict[int, dict[str, Any]]:
    rows = load_json(PAIR_RUN_ROOT / "shards" / f"{slug(key)}.jsonl")
    return {int(row["pair_index"]): row for row in rows}


def apply_mapping(pair: Any, pf: Any, state: Any, source_bits: tuple[int, ...], mapping: list[list[int]]) -> tuple[int, ...]:
    bits = list(source_bits)
    seen: set[int] = set()
    for coordinate, choice in mapping:
        coordinate, choice = int(coordinate), int(choice)
        require(coordinate not in seen, f"duplicate mapping coordinate: {coordinate}")
        seen.add(coordinate)
        raw = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        require(raw is not None, f"illegal prefix in mapping: coordinate={coordinate} choice={choice}")
        bits[coordinate] = int(raw)
    return tuple(bits)


def replay(pair: Any, pf: Any, state: Any, bits: tuple[int, ...], contract: dict[str, Any]) -> dict[str, Any]:
    weights = tuple(pf.from_bits(raw) for raw in bits)
    readout = tuple(int(value) for value in pf.readout_bits(state.rows, weights))
    geometry = pf.geometry_metrics(state.rows, weights, state.base_weights, state.target_weights, state.axis)
    return {
        "bits": bits,
        "weights": weights,
        "readout": readout,
        "weight_state_sha256": bits_hash(bits),
        "readout_sha256": bits_hash(readout),
        "score": pair.score_dict(pf, readout, state.target_readout_bits),
        "geometry": geometry,
        "final_geometry_pass": bool(pf.final_geometry_pass(geometry, contract)),
    }


def signed_vectors(pf: Any, state: Any, result: dict[str, Any], tolerances: dict[str, Any]) -> dict[str, Any]:
    geometry = result["geometry"]
    weights = result["weights"]
    base = state.base_weights
    final_drive = tuple(math.fsum(weights[i] - base[i] for i in row) for row in state.rows)
    target_drive = tuple(float(value) for value in state.target_drive)
    linear_residual = tuple(a - b for a, b in zip(final_drive, target_drive))
    axis_residual = float(geometry["final_axis"] - geometry["target_axis"])
    norm_residual = float(geometry["final_norm"] - geometry["target_norm"])
    axis_scale = max(abs(float(geometry["target_axis"])), 1.0e-12)
    norm_scale = max(float(geometry["target_norm"]), 1.0e-12)
    linear_scale = max(math.sqrt(math.fsum(value * value for value in target_drive)), 1.0e-12)
    axis_norm = axis_residual / axis_scale
    norm_norm = norm_residual / norm_scale
    linear_norm = tuple(value / linear_scale for value in linear_residual)
    gate = tuple([
        axis_norm / float(tolerances["axis_normalized_abs"]),
        norm_norm / float(tolerances["norm_normalized_abs"]),
        *[value / float(tolerances["cue_linear_normalized_abs"]) for value in linear_norm],
    ])
    raw = (axis_residual, norm_residual, *linear_residual)
    normalized = (axis_norm, norm_norm, *linear_norm)
    return {
        "axis_value": float(geometry["final_axis"]),
        "axis_target": float(geometry["target_axis"]),
        "axis_residual": axis_residual,
        "norm_value": float(geometry["final_norm"]),
        "norm_target": float(geometry["target_norm"]),
        "norm_residual": norm_residual,
        "linear_drive": final_drive,
        "target_drive": target_drive,
        "linear_residual": linear_residual,
        "raw": raw,
        "normalized": normalized,
        "gate_normalized": gate,
        "scales": {"axis": axis_scale, "norm": norm_scale, "linear_drive": linear_scale},
    }


def state_payload(pair: Any, pf: Any, state: Any, bits: tuple[int, ...], mapping: list[list[int]], role: str, contract: dict[str, Any], tolerances: dict[str, Any]) -> dict[str, Any]:
    result = replay(pair, pf, state, bits, contract)
    vectors = signed_vectors(pf, state, result, tolerances)
    return {"role": role, "mapping": sorted([[int(a), int(b)] for a, b in mapping]), "result": result, "vectors": vectors}


class Sidecars:
    def __init__(self, root: Path, row_count: int) -> None:
        self.root = root
        self.row_count = row_count
        self.buffers = {name: bytearray() for name in ("weights", "readout", "linear-drive", "linear-residual", "constraint-raw", "constraint-gate")}
        self.records: dict[str, dict[str, Any]] = {}

    def add(self, payload: dict[str, Any]) -> str:
        result = payload["result"]
        key = str(result["weight_state_sha256"]).upper()
        if key in self.records:
            require(self.records[key]["readout_sha256"] == result["readout_sha256"], "weight hash maps to inconsistent readout")
            return key
        vectors = payload["vectors"]
        arrays = {
            "weights": bits_bytes(result["bits"]),
            "readout": bits_bytes(result["readout"]),
            "linear-drive": f64_bytes(vectors["linear_drive"]),
            "linear-residual": f64_bytes(vectors["linear_residual"]),
            "constraint-raw": f64_bytes(vectors["raw"]),
            "constraint-gate": f64_bytes(vectors["gate_normalized"]),
        }
        offsets = {name: len(buffer) for name, buffer in self.buffers.items()}
        for name, data in arrays.items():
            self.buffers[name].extend(data)
        self.records[key] = {
            "state_ref": key,
            "role_first_seen": payload["role"],
            "mapping": payload["mapping"],
            "weight_state_sha256": key,
            "readout_sha256": result["readout_sha256"],
            "score": result["score"],
            "geometry": result["geometry"],
            "final_geometry_pass": result["final_geometry_pass"],
            "vectors": {k: v for k, v in vectors.items() if k not in {"linear_drive", "target_drive", "linear_residual", "raw", "normalized", "gate_normalized"}},
            "offset_bytes": offsets,
            "byte_lengths": {name: len(data) for name, data in arrays.items()},
            "element_counts": {"weights": len(result["bits"]), "readout": len(result["readout"]), "linear_drive": len(vectors["linear_drive"]), "linear_residual": len(vectors["linear_residual"]), "constraint_raw": len(vectors["raw"]), "constraint_gate": len(vectors["gate_normalized"])},
        }
        return key

    def finalize(self) -> dict[str, str]:
        self.root.mkdir(parents=True, exist_ok=True)
        names = {"weights": "weights.u32bin", "readout": "readout.u32bin", "linear-drive": "linear-drive.f64bin", "linear-residual": "linear-residual.f64bin", "constraint-raw": "constraint-raw.f64bin", "constraint-gate": "constraint-gate.f64bin"}
        hashes = {}
        for name, filename in names.items():
            path = self.root / filename
            write_atomic(path, bytes(self.buffers[name]))
            hashes[filename] = digest(path)
        index = self.root / "state-index.jsonl"
        write_atomic(index, "".join(json.dumps(self.records[key], sort_keys=True) + "\n" for key in sorted(self.records)).encode("utf-8"))
        hashes[index.name] = digest(index)
        return hashes


def verify_expected(pair: Any, pf: Any, actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    require(actual["weight_state_sha256"] == str(expected["weight_state_sha256"]).upper(), f"{label} weight hash drift")
    require(actual["readout_sha256"] == str(expected["readout_sha256"]).upper(), f"{label} readout hash drift")
    require(actual["score"] == expected["score"], f"{label} score drift")
    require(actual["geometry"] == expected["geometry"], f"{label} geometry drift")
    require(bool(actual["final_geometry_pass"]) == bool(expected["final_geometry_pass"]), f"{label} final gate drift")


def run_context(args: tuple[str, int, str]) -> dict[str, Any]:
    endpoint, set_index, root_text = args
    pair, pf, builder = load_modules()
    _, data = builder.fresh_lineage(CLOSURE_REPO, pf)
    key = (endpoint, int(set_index))
    state = next(item for item in data["states"] if item.key == key)
    pf5_contract = load_json(PF5_ROOT / "CONTRACT.json")
    tolerance_schema = load_json(ROOT / "tolerance-schema.json")["tolerance"]
    ref_execution = load_json(REF_ROOT / "execution.json")
    ref = next(item for item in ref_execution["results"] if item["endpoint"] == endpoint and int(item["set_index"]) == int(set_index))
    domain_rows = load_domain_rows(key)
    run_rows = load_run_rows(key)
    require(len(domain_rows) == len(run_rows), f"domain/run row count drift: {key}")
    s_bits = apply_mapping(pair, pf, state, tuple(state.baseline_weight_bits), ref["best_search"]["canonical_mapping"])
    s = state_payload(pair, pf, state, s_bits, ref["best_search"]["canonical_mapping"], "S", pf5_contract, tolerance_schema)
    verify_expected(pair, pf, s["result"], run_rows[0]["s"] if domain_rows else ref["best_search"], "S")
    sidecars = Sidecars(ROOT / "sidecars" / slug(key), len(state.rows))
    records: list[dict[str, Any]] = []
    for domain_row in domain_rows:
        index = int(domain_row["pair_index"])
        expected = run_rows[index]
        a_map = domain_row["a_mapping"]
        b_map = domain_row["b_mapping"]
        a_bits = apply_mapping(pair, pf, state, s_bits, a_map)
        b_bits = apply_mapping(pair, pf, state, s_bits, b_map)
        coordinates_a = {int(item[0]) for item in a_map}
        coordinates_b = {int(item[0]) for item in b_map}
        require(coordinates_a.isdisjoint(coordinates_b), f"pair coordinate overlap: {key} {index}")
        ab_bits = apply_mapping(pair, pf, state, a_bits, b_map)
        a = state_payload(pair, pf, state, a_bits, a_map, "A", pf5_contract, tolerance_schema)
        b = state_payload(pair, pf, state, b_bits, b_map, "B", pf5_contract, tolerance_schema)
        ab_map = sorted(a_map + b_map)
        ab = state_payload(pair, pf, state, ab_bits, ab_map, "AB", pf5_contract, tolerance_schema)
        verify_expected(pair, pf, a["result"], expected["a"], f"A {index}")
        verify_expected(pair, pf, b["result"], expected["b"], f"B {index}")
        verify_expected(pair, pf, ab["result"], expected["ab"], f"AB {index}")
        require(s["result"]["weight_state_sha256"] == expected["s"]["weight_state_sha256"], f"S hash drift at pair {index}")
        fixed = sum(a != t and b != t for a, b, t in zip(s["result"]["readout"], ab["result"]["readout"], state.target_readout_bits))
        damaged = sum(a == t and b != t for a, b, t in zip(s["result"]["readout"], ab["result"]["readout"], state.target_readout_bits))
        require(fixed == int(expected["fixed"]) and damaged == int(expected["damaged"]), f"fixed/damaged drift at pair {index}")
        refs = {role: sidecars.add(payload) for role, payload in (("S", s), ("A", a), ("B", b), ("AB", ab))}
        records.append({"pair_index": index, "context": [endpoint, int(set_index)], "application_base": "fresh_S", "state_refs": refs, "mappings": {"S": s["mapping"], "A": a["mapping"], "B": b["mapping"], "AB": ab["mapping"]}, "scores": {role: payload["result"]["score"] for role, payload in (("S", s), ("A", a), ("B", b), ("AB", ab))}, "final_geometry_pass": {role: bool(payload["result"]["final_geometry_pass"]) for role, payload in (("S", s), ("A", a), ("B", b), ("AB", ab))}, "outcome": expected["outcome"], "target_equal": bool(expected["target_equal"]), "fixed": fixed, "damaged": damaged})
    sidecar_hashes = sidecars.finalize()
    shard = ROOT / "shards" / f"{slug(key)}.jsonl"
    write_atomic(shard, "".join(json.dumps(row, sort_keys=True) + "\n" for row in records).encode("utf-8"))
    return {"context": [endpoint, int(set_index)], "records": len(records), "state_records": len(sidecars.records), "shard": shard.name, "shard_sha256": digest(shard), "sidecar_hashes": sidecar_hashes}


def preflight(contract: dict[str, Any]) -> list[dict[str, Any]]:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "VMAT1 contract identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "PLAN drift")
    require(contract["runner_sha256"] == digest(Path(__file__)), "runner drift")
    require(contract["domain_manifest_sha256"] == digest(ROOT / "domain-manifest.json"), "domain manifest drift")
    require(contract["tolerance_schema_sha256"] == digest(ROOT / "tolerance-schema.json"), "tolerance schema drift")
    ordered_pairs = load_json(ROOT / "domain-manifest.json").get("ordered_pairs", [])
    require(all(isinstance(item, dict) for item in ordered_pairs), "malformed domain record")
    for item in contract["parent_bindings"]:
        path = REPO / Path(item["path"])
        require(path.is_file() and digest(path) == str(item["sha256"]).upper(), f"parent drift: {item['label']}")
    manifest = load_json(ROOT / "domain-manifest.json")
    require(int(manifest["count"]) == 4999 and len(manifest["ordered_pairs"]) == 4999, "domain count drift")
    require(not (ROOT / "execution.json").exists(), "VMAT1 execution already exists")
    require(not list(ROOT.rglob("*.tmp")), "orphan VMAT1 temporary output exists")
    require(not (ROOT / "scripts" / "__pycache__").exists(), "unexpected VMAT1 scripts pycache")
    return manifest["ordered_pairs"]


def main() -> int:
    contract = load_json(ROOT / "CONTRACT.json")
    try:
        domain = preflight(contract)
        args = [(str(key[0]), int(key[1]), str(CLOSURE_REPO)) for key in PAIR_KEYS]
        results: list[dict[str, Any]] = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(run_context, arg) for arg in args]
            for future in futures:
                result = future.result()
                results.append(result)
                print(json.dumps({"context": result["context"], "records": result["records"], "state_records": result["state_records"]}, sort_keys=True), flush=True)
        results.sort(key=lambda item: (item["context"][0], item["context"][1]))
        require(sum(int(item["records"]) for item in results) == 4999, "VMAT1 record count drift")
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "CSC1_VMAT1_COMPLETE", "engineering_only": True, "scientific_promotion": False, "behavioral_probe": False, "pair_domain_frozen": True, "routing_conclusion": False, "counts": {"contexts": 8, "pair_records": 4999, "states_per_pair": 4, "unique_state_records": sum(int(item["state_records"]) for item in results)}, "domain_manifest_sha256": digest(ROOT / "domain-manifest.json"), "contract_sha256": digest(ROOT / "CONTRACT.json"), "results": results, "execution_hygiene": {"python_flag_B": True, "PYTHONDONTWRITEBYTECODE": os.environ.get("PYTHONDONTWRITEBYTECODE"), "unexpected_path_policy": "FAIL_PROMOTION", "write_allowlist": contract["write_allowlist"]}}
        write_json_atomic(ROOT / "execution.json", execution)
        write_json_atomic(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_CSC1_VMAT1", "engineering_only": True, "scientific_promotion": False, "error_type": type(exc).__name__, "error": str(exc)}
        if not (ROOT / "execution.json").exists():
            write_json_atomic(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
