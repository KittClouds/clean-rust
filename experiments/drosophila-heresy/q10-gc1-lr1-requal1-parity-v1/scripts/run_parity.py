"""Independent parity audit for a fixed sample of fresh singleton shards."""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any

PROTOCOL = "REQUAL1-PARITY"
IDENTITY = "q10-gc1-lr1-requal1-parity-v1"
ROOT = Path(__file__).resolve().parents[1]
SINGLES_ROOT = ROOT.parent / "q10-gc1-lr1-requal1-singles-v1"
DOMAIN_ROOT = ROOT.parent / "q10-gc1-lr1-requal1-domain-r2-v1"
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
POSITIONS = (0, 1, 7, 8, 64, 127, 255, -1)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def bits_hash(values: list[int] | tuple[int, ...]) -> str:
    return digest_bytes(b"".join(int(value).to_bytes(4, "little", signed=False) for value in values))


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite parity receipt: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def to_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def from_bits(value: int) -> float:
    return struct.unpack("<f", struct.pack("<I", value))[0]


def next_bits(raw: int, choice: int) -> int | None:
    candidate = (int(raw) + (1 if choice > 0 else -1) * abs(int(choice))) & 0xFFFF_FFFF
    value = from_bits(candidate)
    if not math.isfinite(value) or not (0.0 < value < 2.0):
        return None
    if candidate < to_bits(0.0) + 16 or candidate > to_bits(2.0) - 16:
        return None
    return candidate


def replay(rows: list[list[int]], weights: list[float]) -> tuple[int, ...]:
    output = []
    for row in rows:
        value = from_bits(0x80000000)
        for coordinate in row:
            value = f32(value + weights[coordinate])
        output.append(to_bits(value))
    return tuple(output)


def ordered(bits: int) -> int:
    return (~bits & 0xFFFF_FFFF) if bits & 0x80000000 else (bits ^ 0x80000000)


def ulp_distance(left: float, right: float) -> int:
    return abs(ordered(to_bits(left)) - ordered(to_bits(right)))


def norm(values: list[float]) -> float:
    return math.sqrt(math.fsum(value * value for value in values))


def geometry(rows: list[list[int]], weights: list[float], base: list[float], target: list[float], axis: list[float]) -> dict[str, float]:
    displacement = [value - initial for value, initial in zip(weights, base)]
    target_displacement = [value - initial for value, initial in zip(target, base)]
    target_axis = math.fsum(value * coefficient for value, coefficient in zip(target_displacement, axis))
    final_axis = math.fsum(value * coefficient for value, coefficient in zip(displacement, axis))
    target_norm = norm(target_displacement)
    final_norm = norm(displacement)
    true_drive = [math.fsum(target_displacement[index] for index in row) for row in rows]
    final_drive = [math.fsum(displacement[index] for index in row) for row in rows]
    cue_error = norm([a - b for a, b in zip(final_drive, true_drive)])
    cue_scale = max(norm(true_drive), 1.0e-12)
    return {"axis_absolute_error": abs(final_axis - target_axis), "axis_normalized_error": abs(final_axis - target_axis) / max(abs(target_axis), 1.0e-12), "norm_absolute_error": abs(final_norm - target_norm), "norm_normalized_error": abs(final_norm - target_norm) / max(target_norm, 1.0e-12), "cue_linear_absolute_error": cue_error, "cue_linear_normalized_error": cue_error / cue_scale, "final_axis": final_axis, "target_axis": target_axis, "final_norm": final_norm, "target_norm": target_norm}


def main() -> int:
    require(not (ROOT / "execution.json").exists(), "parity execution already exists")
    singles_execution = json.loads((SINGLES_ROOT / "execution.json").read_text(encoding="utf-8"))
    domain_execution = json.loads((DOMAIN_ROOT / "execution.json").read_text(encoding="utf-8"))
    require(singles_execution["status"] == "SINGLES_COMPLETE", "singleton campaign is not complete")
    require(domain_execution["status"] == "DOMAIN_READY_FOR_SMOKE", "domain gate is not ready")
    closure = Path(domain_execution["closures"]["twin-a"]["repo"])
    source_root = closure / "experiments/drosophila-heresy/q10-distributed-additive-v1/qualification/sample-9731-9732"
    da2 = json.loads((closure / "experiments/drosophila-heresy/q10-da2-geometry-v1/qualification/sample-9731-9732/results.json").read_text(encoding="utf-8"))
    da2_lookup = {(item["source_event"], int(item["set_index"])): item for item in da2}
    sampled = []
    checks = []
    for key in KEYS:
        shard = ROOT.parent / "q10-gc1-lr1-requal1-singles-v1/shards" / f"{key[0].removesuffix('.json')}__set{key[1]}.jsonl"
        rows = json.loads(shard.read_text(encoding="utf-8"))
        selected = []
        for position in POSITIONS:
            index = position if position >= 0 else len(rows) + position
            if 0 <= index < len(rows) and index not in selected:
                selected.append(index)
        for index in selected:
            record = rows[index]
            event = json.loads((source_root / key[0]).read_text(encoding="utf-8"))
            fixture = event["fixture"]
            operator = fixture["operator"]
            source_set = event["sets"][key[1]]
            da2_item = da2_lookup[key]
            initial_bits = [int(value) for value in fixture["initial_weight_bits"]]
            baseline_bits = initial_bits[:]
            for coordinate, choice in sorted((int(c), int(s)) for c, s in da2_item["selected_steps"].items()):
                replacement = next_bits(initial_bits[coordinate], choice)
                require(replacement is not None, f"parity baseline prefix illegal: {key}")
                baseline_bits[coordinate] = replacement
            mapping = {int(coordinate): int(choice) for coordinate, choice in record["canonical_mapping"]}
            candidate_bits = baseline_bits[:]
            for coordinate, choice in mapping.items():
                replacement = next_bits(baseline_bits[coordinate], choice) if choice else baseline_bits[coordinate]
                require(replacement is not None, f"parity singleton prefix illegal: {key}")
                candidate_bits[coordinate] = replacement
            require(bits_hash(candidate_bits) == record["weight_state_sha256"], f"parity weight hash mismatch: {key} index={index}")
            weights = [from_bits(value) for value in candidate_bits]
            readout = replay([[int(c) for c in row] for row in operator["rows"]], weights)
            require(bits_hash(readout) == record["readout_sha256"], f"parity readout hash mismatch: {key} index={index}")
            target_bits = tuple(int(value) for value in fixture["target_readout_bits"])
            errors = [from_bits(actual) - from_bits(target) for actual, target in zip(readout, target_bits)]
            score = {"mismatch_count": sum(actual != target for actual, target in zip(readout, target_bits)), "total_ulp_distance": sum(ulp_distance(from_bits(actual), from_bits(target)) for actual, target in zip(readout, target_bits)), "residual_l2": math.sqrt(math.fsum(value * value for value in errors)), "maximum_absolute_residual": max((abs(value) for value in errors), default=0.0)}
            require(score == record["score"], f"parity score mismatch: {key} index={index}")
            geo = geometry([[int(c) for c in row] for row in operator["rows"]], weights, [from_bits(int(value)) for value in fixture["snapshot_base_bits"]], [from_bits(int(value)) for value in fixture["target_weight_bits"]], [float(value) for value in fixture["acquisition_axis"]])
            for name, value in geo.items():
                require(abs(value - float(record["geometry"][name])) <= 1.0e-12, f"parity geometry mismatch: {key} index={index} field={name}")
            sampled.append({"key": [key[0], key[1]], "shard_index": index, "group": record["group"], "to": record["to"]})
            checks.append({"key": [key[0], key[1]], "index": index, "weight_hash": record["weight_state_sha256"], "readout_hash": record["readout_sha256"], "score_match": True, "geometry_match": True})
    execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PARITY_PASS", "engineering_only": True, "singleton_execution_sha256": digest(SINGLES_ROOT / "execution.json"), "domain_execution_sha256": digest(DOMAIN_ROOT / "execution.json"), "sample_positions": list(POSITIONS), "counts": {"sampled_records": len(checks), "contexts": len(KEYS)}, "sample_manifest_sha256": digest_bytes(json.dumps(sampled, sort_keys=True, separators=(",", ":")).encode("utf-8")), "checks": checks, "pair_replay_executed": False, "scientific_promotion": False}
    write_new(ROOT / "execution.json", execution)
    print(json.dumps(execution, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
