from __future__ import annotations

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

PROTOCOL = "Q10-CSC1-VMAT1-FINALIZER"
IDENTITY = "q10-gc1-lr1-requal1-csc1-vmat1-finalizer-v1"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
VMAT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-vmat1-v6"
DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pair-domain-v1"
PAIR_RUN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-v1"
REF = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
DOMAIN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE = DOMAIN_ROOT / "closures/twin-a/repo"
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


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def bits_hash(values: tuple[int, ...]) -> str:
    out = bytearray()
    for value in values:
        out.extend(struct.pack("<I", int(value)))
    return digest_bytes(bytes(out))


def score(pair: Any, pf: Any, actual: tuple[int, ...], target: tuple[int, ...]) -> dict[str, Any]:
    return pair.score_dict(pf, actual, target)


def replay(pair: Any, pf: Any, state: Any, bits: tuple[int, ...], contract: dict[str, Any]) -> dict[str, Any]:
    weights = tuple(pf.from_bits(raw) for raw in bits)
    readout = tuple(int(value) for value in pf.readout_bits(state.rows, weights))
    geometry = pf.geometry_metrics(state.rows, weights, state.base_weights, state.target_weights, state.axis)
    return {"bits": bits, "readout": readout, "weights": weights, "weight_state_sha256": bits_hash(bits), "readout_sha256": bits_hash(readout), "score": score(pair, pf, readout, state.target_readout_bits), "geometry": geometry, "final_geometry_pass": bool(pf.final_geometry_pass(geometry, contract))}


def apply(pf: Any, state: Any, source: tuple[int, ...], mapping: list[list[int]]) -> tuple[int, ...]:
    bits = list(source)
    seen: set[int] = set()
    for coordinate, choice in mapping:
        coordinate, choice = int(coordinate), int(choice)
        require(coordinate not in seen, "duplicate sampled mapping coordinate")
        seen.add(coordinate)
        raw = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        require(raw is not None, "sampled mapping contains illegal prefix")
        bits[coordinate] = int(raw)
    return tuple(bits)


def f64_values(path: Path, offset: int, length: int) -> tuple[float, ...]:
    raw = path.read_bytes()[offset:offset + length]
    require(len(raw) == length and length % 8 == 0, f"invalid float64 sidecar slice: {path}")
    return struct.unpack("<" + "d" * (length // 8), raw)


def u32_values(path: Path, offset: int, length: int) -> tuple[int, ...]:
    raw = path.read_bytes()[offset:offset + length]
    require(len(raw) == length and length % 4 == 0, f"invalid uint32 sidecar slice: {path}")
    return struct.unpack("<" + "I" * (length // 4), raw)


def state_vectors(pf: Any, state: Any, result: dict[str, Any], tolerance: dict[str, Any]) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    weights = result["weights"]
    geometry = result["geometry"]
    drive = tuple(math.fsum(weights[i] - state.base_weights[i] for i in row) for row in state.rows)
    target_drive = tuple(float(value) for value in state.target_drive)
    residual = tuple(a - b for a, b in zip(drive, target_drive))
    axis = float(geometry["final_axis"] - geometry["target_axis"])
    norm = float(geometry["final_norm"] - geometry["target_norm"])
    axis_norm = axis / max(abs(float(geometry["target_axis"])), 1.0e-12)
    norm_norm = norm / max(float(geometry["target_norm"]), 1.0e-12)
    scale = max(math.sqrt(math.fsum(value * value for value in target_drive)), 1.0e-12)
    linear_norm = tuple(value / scale for value in residual)
    gate = tuple([axis_norm / tolerance["axis_normalized_abs"], norm_norm / tolerance["norm_normalized_abs"], *[value / tolerance["cue_linear_normalized_abs"] for value in linear_norm]])
    return drive, residual, (axis, norm, *residual), gate


def sample_indices(rows: list[dict[str, Any]]) -> list[int]:
    chosen: set[int] = set()
    for index in (0, len(rows) // 2, len(rows) - 1):
        if 0 <= index < len(rows):
            chosen.add(index)
    for index, row in enumerate(rows):
        if row["outcome"] == "VALID_ADVANTAGE_PRESERVED":
            chosen.add(index)
            break
    return sorted(chosen)


def main() -> int:
    report: dict[str, Any] = {"protocol": PROTOCOL, "identity": IDENTITY, "parent_vmat_identity": load(VMAT / "CONTRACT.json")["identity"], "scientific_promotion": False}
    try:
        contract = load(VMAT / "CONTRACT.json")
        execution = load(VMAT / "execution.json")
        require(execution["status"] == "CSC1_VMAT1_COMPLETE", "VMAT1 is not complete")
        require(execution["counts"]["pair_records"] == 4999, "VMAT1 pair count drift")
        require(digest(VMAT / "execution.json") == load(VMAT / "STATUS.json")["execution_sha256"], "VMAT1 status hash drift")
        for item in contract["parent_bindings"]:
            path = REPO / Path(item["path"])
            require(path.is_file() and digest(path) == item["sha256"], f"VMAT1 parent drift: {item['label']}")
        manifest = load(VMAT / "domain-manifest.json")
        require(manifest["count"] == 4999 and len(manifest["ordered_pairs"]) == 4999, "VMAT1 domain manifest drift")
        require(digest(VMAT / "domain-manifest.json") == contract["domain_manifest_sha256"], "VMAT1 domain hash drift")
        unexpected = []
        for path in VMAT.rglob("*"):
            if path.is_dir():
                continue
            if path.name.endswith(".tmp") or "__pycache__" in path.parts:
                unexpected.append(path.relative_to(VMAT).as_posix())
        require(not unexpected, f"unexpected VMAT1 output paths: {unexpected[:5]}")
        pair, pf, builder = None, None, None
        sys.path.insert(0, str(PAIR_RUN / "scripts"))
        pair = importlib.import_module("run_pairs")
        pf, builder = pair.load_modules()
        _, data = builder.fresh_lineage(CLOSURE, pf)
        states = {state.key: state for state in data["states"]}
        pf5_contract = load(CLOSURE / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json")
        tolerance = load(VMAT / "tolerance-schema.json")["tolerance"]
        by_context = {}
        sampled = []
        total_records = 0
        for key in PAIR_KEYS:
            context_slug = slug(key)
            shard_path = VMAT / "shards" / f"{context_slug}.jsonl"
            records = [json.loads(line) for line in shard_path.read_text(encoding="utf-8").splitlines() if line]
            domain_rows = load(DOMAIN / "shards" / f"{context_slug}.jsonl")
            require(len(records) == len(domain_rows), f"VMAT1 shard/domain count drift: {key}")
            index_path = VMAT / "sidecars" / context_slug / "state-index.jsonl"
            state_index = {row["state_ref"]: row for row in (json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line)}
            side_root = VMAT / "sidecars" / context_slug
            files = {name: side_root / name for name in ("weights.u32bin", "readout.u32bin", "linear-drive.f64bin", "linear-residual.f64bin", "constraint-raw.f64bin", "constraint-gate.f64bin")}
            for path in files.values():
                require(path.is_file(), f"missing sidecar: {path}")
            for ref in state_index.values():
                counts = ref["element_counts"]
                lengths = ref["byte_lengths"]
                require(lengths["weights"] == counts["weights"] * 4 and lengths["readout"] == counts["readout"] * 4, "u32 sidecar length mismatch")
                require(lengths["linear-drive"] == counts["linear_drive"] * 8 and lengths["linear-residual"] == counts["linear_residual"] * 8, "drive sidecar length mismatch")
                require(lengths["constraint-raw"] == counts["constraint_raw"] * 8 and lengths["constraint-gate"] == counts["constraint_gate"] * 8, "constraint sidecar length mismatch")
                for name, path in files.items():
                    offset = int(ref["offset_bytes"][name.removesuffix(".u32bin").removesuffix(".f64bin") if name not in ("weights.u32bin", "readout.u32bin") else name.removesuffix(".u32bin")]) if False else None
                for logical, filename in (("weights", "weights.u32bin"), ("readout", "readout.u32bin"), ("linear-drive", "linear-drive.f64bin"), ("linear-residual", "linear-residual.f64bin"), ("constraint-raw", "constraint-raw.f64bin"), ("constraint-gate", "constraint-gate.f64bin")):
                    offset = int(ref["offset_bytes"][logical])
                    length = int(ref["byte_lengths"][logical])
                    require(offset + length <= files[filename].stat().st_size, f"sidecar offset overflow: {context_slug} {ref['state_ref']}")
            by_context[context_slug] = {"records": len(records), "state_records": len(state_index), "shard_sha256": digest(shard_path), "state_index_sha256": digest(index_path)}
            total_records += len(records)
            for local_index in sample_indices(records):
                sampled.append((key, local_index, records[local_index], domain_rows[local_index], state_index, files, tolerance, pf5_contract, states[key]))
        require(total_records == 4999, f"VMAT1 total records drift: {total_records}")
        ref_execution = load(REF / "execution.json")
        sample_checks = 0
        for key, local_index, record, domain_row, state_index, files, tolerance, pf5_contract, state in sampled:
            ref = next(item for item in ref_execution["results"] if item["endpoint"] == key[0] and int(item["set_index"]) == key[1])
            source = pair.mapping_bits(pf, state, ref["best_search"]["canonical_mapping"])
            maps = {"S": ref["best_search"]["canonical_mapping"], "A": domain_row["a"]["canonical_mapping"], "B": domain_row["b"]["canonical_mapping"], "AB": domain_row["a"]["canonical_mapping"] + domain_row["b"]["canonical_mapping"]}
            bits_by_role = {"S": source, "A": apply(pf, state, source, maps["A"]), "B": apply(pf, state, source, maps["B"]), "AB": apply(pf, state, apply(pf, state, source, maps["A"]), maps["B"])}
            for role, bits in bits_by_role.items():
                actual = replay(pair, pf, state, bits, pf5_contract)
                ref_key = record["state_refs"][role]
                ref_state = state_index[ref_key]
                require(actual["weight_state_sha256"] == ref_state["weight_state_sha256"], f"sample weight mismatch {key} {local_index} {role}")
                require(actual["readout_sha256"] == ref_state["readout_sha256"], f"sample readout mismatch {key} {local_index} {role}")
                require(actual["score"] == ref_state["score"] and actual["geometry"] == ref_state["geometry"], f"sample summary mismatch {key} {local_index} {role}")
                vectors = state_vectors(pf, state, actual, tolerance)
                ref_weights = u32_values(files["weights.u32bin"], int(ref_state["offset_bytes"]["weights"]), int(ref_state["byte_lengths"]["weights"]))
                ref_readout = u32_values(files["readout.u32bin"], int(ref_state["offset_bytes"]["readout"]), int(ref_state["byte_lengths"]["readout"]))
                require(ref_weights == bits and ref_readout == actual["readout"], f"sample sidecar bits mismatch {key} {local_index} {role}")
                require(f64_values(files["linear-drive.f64bin"], int(ref_state["offset_bytes"]["linear-drive"]), int(ref_state["byte_lengths"]["linear-drive"])) == vectors[0], f"sample drive mismatch {key} {local_index} {role}")
                require(f64_values(files["linear-residual.f64bin"], int(ref_state["offset_bytes"]["linear-residual"]), int(ref_state["byte_lengths"]["linear-residual"])) == vectors[1], f"sample residual mismatch {key} {local_index} {role}")
                require(f64_values(files["constraint-raw.f64bin"], int(ref_state["offset_bytes"]["constraint-raw"]), int(ref_state["byte_lengths"]["constraint-raw"])) == vectors[2], f"sample raw vector mismatch {key} {local_index} {role}")
                require(f64_values(files["constraint-gate.f64bin"], int(ref_state["offset_bytes"]["constraint-gate"]), int(ref_state["byte_lengths"]["constraint-gate"])) == vectors[3], f"sample gate vector mismatch {key} {local_index} {role}")
                sample_checks += 1
        report.update({"status": "VMAT1_FINALIZER_PASS", "coverage": {"contexts": 8, "pair_records": total_records, "unique_state_records": sum(item["state_records"] for item in by_context.values()), "sampled_pairs": len(sampled), "sampled_state_checks": sample_checks}, "context_reports": by_context, "unexpected_files": [], "independent_replay_scope": "stratified sample across all contexts and pair outcomes", "routing_conclusion": False})
        (ROOT / "REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        return 0
    except Exception as exc:
        report.update({"status": "VMAT1_FINALIZER_BLOCKED", "error_type": type(exc).__name__, "error": str(exc)})
        (ROOT / "REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
