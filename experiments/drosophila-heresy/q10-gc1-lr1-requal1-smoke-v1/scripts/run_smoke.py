"""Run one exact singleton smoke replay per current REQUAL1 context."""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

PROTOCOL = "REQUAL1-SMOKE"
IDENTITY = "q10-gc1-lr1-requal1-smoke-v1"
ROOT = Path(__file__).resolve().parents[1]
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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def bits_hash(values: tuple[int, ...] | list[int]) -> str:
    return digest_bytes(b"".join(int(value).to_bytes(4, "little", signed=False) for value in values))


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite smoke receipt: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    domain_execution_path = DOMAIN_ROOT / "execution.json"
    domain_execution = json.loads(domain_execution_path.read_text(encoding="utf-8"))
    require(domain_execution["status"] == "DOMAIN_READY_FOR_SMOKE", "domain gate is not ready for smoke")
    closure_repo = Path(domain_execution["closures"]["twin-a"]["repo"])
    require(closure_repo.is_dir(), "sealed domain closure twin is missing")
    sys.path.insert(0, str(DOMAIN_ROOT / "scripts"))
    domain_builder = importlib.import_module("build_domain_closure")
    pf = domain_builder.import_pf5(closure_repo)
    _, data = domain_builder.fresh_lineage(closure_repo, pf)
    palette_path = closure_repo / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl"
    palette_rows = [json.loads(line) for line in palette_path.read_text(encoding="utf-8").splitlines() if line]
    by_key_group = {(str(item["identity"][0]), int(item["identity"][1]), int(item["identity"][2])): item for item in palette_rows}
    states = {state.key: state for state in data["states"]}
    receipts = []
    for key in KEYS:
        groups = data["groups"][key]
        require(groups, f"no reconstructed group for smoke context: {key}")
        group = groups[0]
        item = by_key_group[(key[0], key[1], group.group_index)]
        candidate_id = str(item["role_selection"]["best_D"])
        candidates = {str(candidate["candidate_identity"]): candidate for candidate in item["palette"]}
        candidate = candidates.get(candidate_id)
        require(candidate is not None and candidate_id != str(item["baseline"]["candidate_identity"]), f"smoke candidate is missing/nonzero: {key}")
        state = states[key]
        mapping = {int(coordinate): int(choice) for coordinate, choice in candidate["canonical_mapping"]}
        require(tuple(sorted(mapping)) == group.coordinates, f"smoke canonical coordinate drift: {key}")
        weight_bits = list(state.baseline_weight_bits)
        for coordinate, choice in mapping.items():
            if choice == 0:
                continue
            replacement = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
            require(replacement is not None, f"smoke illegal prefix: {key} coordinate={coordinate}")
            weight_bits[coordinate] = replacement
        weight_hash = bits_hash(weight_bits)
        require(weight_hash == str(candidate["committed_f32_weight_state_sha256"]).upper(), f"smoke candidate byte drift: {key}")
        weights = tuple(pf.from_bits(value) for value in weight_bits)
        readout = tuple(pf.readout_bits(state.rows, weights))
        readout_hash = bits_hash(readout)
        require(readout_hash == str(candidate["exact_readout_sha256"]).upper(), f"smoke sequential replay drift: {key}")
        mismatch = sum(actual != target for actual, target in zip(readout, state.target_readout_bits))
        total_ulp = sum(pf.ulp_distance(pf.from_bits(actual), pf.from_bits(target)) for actual, target in zip(readout, state.target_readout_bits))
        geometry = pf.geometry_metrics(state.rows, weights, state.base_weights, state.target_weights, state.axis)
        final_pass = bool(pf.final_geometry_pass(geometry, {"geometry": json.loads((closure_repo / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json").read_text(encoding="utf-8"))["geometry"]}))
        receipts.append({"key": [key[0], key[1]], "group_index": group.group_index, "candidate_identity": candidate_id, "weight_state_sha256": weight_hash, "readout_sha256": readout_hash, "mismatch_count": mismatch, "total_ulp_distance": total_ulp, "geometry": geometry, "final_geometry_pass": final_pass})
    execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SMOKE_PASS", "engineering_only": True, "domain_execution_sha256": digest(domain_execution_path), "domain_identity": domain_execution["identity"], "closure_twin": "twin-a", "counts": {"contexts": len(receipts), "exact_replays": len(receipts)}, "receipts": receipts, "singleton_campaign_opened": False, "pair_replay_executed": False, "scientific_promotion": False}
    write_new(ROOT / "execution.json", execution)
    print(json.dumps(execution, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
