"""Derive compatible S-replacement pair opportunities with geometry screening."""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

PROTOCOL = "REQUAL1-SREPLACE-PAIR-DOMAIN"
IDENTITY = "q10-gc1-lr1-requal1-sreplace-pair-domain-v1"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
CANDIDATE_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-candidates-v1"
CANDIDATE_EXECUTION = CANDIDATE_ROOT / "execution.json"
DOMAIN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_ROOT = DOMAIN_ROOT / "closures/twin-a"
CLOSURE_REPO = CLOSURE_ROOT / "repo"
PF5_SCRIPTS = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/scripts"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
PALETTE = CLOSURE_REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl"
BUILDER_ROOT = DOMAIN_ROOT / "scripts"
REF_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
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
SCREEN_MARGIN = 1.0e-12


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def object_hash(value: Any) -> str:
    return digest_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    require(not tmp.exists(), f"orphan temporary output exists: {tmp}")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)


def case_slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def load_modules() -> tuple[Any, Any]:
    sys.path.insert(0, str(PF5_SCRIPTS))
    pf = importlib.import_module("run_q10_pf5")
    sys.path.insert(0, str(BUILDER_ROOT))
    builder = importlib.import_module("build_domain_closure")
    require(Path(pf.__file__).resolve() == (PF5_SCRIPTS / "run_q10_pf5.py").resolve(), "wrong PF5 module loaded")
    return pf, builder


def bits_hash(values: tuple[int, ...]) -> str:
    return digest_bytes(b"".join(int(value).to_bytes(4, "little", signed=False) for value in values))


def mapping_bits(pf: Any, state: Any, mapping: list[list[int]]) -> tuple[int, ...]:
    bits = list(int(value) for value in state.baseline_weight_bits)
    seen = set()
    for coordinate, choice in mapping:
        coordinate, choice = int(coordinate), int(choice)
        require(coordinate not in seen, f"duplicate reference mapping coordinate: {coordinate}")
        seen.add(coordinate)
        raw = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        require(raw is not None, f"illegal reference mapping prefix: {coordinate} {choice}")
        bits[coordinate] = int(raw)
    return tuple(bits)


def verify_reference(pf: Any, state: Any, result: dict[str, Any], pf5_contract: dict[str, Any]) -> tuple[tuple[int, ...], tuple[float, ...], dict[str, Any]]:
    mapping = result["best_search"]["canonical_mapping"]
    bits = mapping_bits(pf, state, mapping)
    weights = tuple(pf.from_bits(raw) for raw in bits)
    readout = tuple(pf.readout_bits(state.rows, weights))
    geometry = pf.geometry_metrics(state.rows, weights, state.base_weights, state.target_weights, state.axis)
    require(bits_hash(bits) == str(result["best_search"]["weight_state_sha256"]).upper(), f"S bytes drift: {state.key}")
    require(bits_hash(readout) == str(result["best_search"]["readout_sha256"]).upper(), f"S readout drift: {state.key}")
    require(not pf.final_geometry_pass(geometry, pf5_contract), f"S unexpectedly valid: {state.key}")
    return bits, weights, geometry


def compact_candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {"group": int(row["group"]), "from": str(row["from"]), "to": str(row["to"]), "canonical_mapping": row["canonical_mapping"], "eligibility_reason": str(row["eligibility_reason"]), "singleton_score": row["score"], "singleton_final_geometry_pass": bool(row["final_geometry_pass"]), "singleton_weight_state_sha256": str(row["weight_state_sha256"]).upper(), "singleton_readout_sha256": str(row["readout_sha256"]).upper()}


def make_candidate(pf: Any, state: Any, s_weights: tuple[float, ...], q_s: tuple[float, ...], s_cue_sq: float, row: dict[str, Any], palette_item: dict[str, Any]) -> dict[str, Any]:
    candidate = next((item for item in palette_item["palette"] if str(item["candidate_identity"]) == str(row["to"])), None)
    require(candidate is not None, f"candidate missing from palette: {row['to']}")
    delta = {}
    for coordinate, choice, committed in candidate["committed_f32_mapping"]:
        coordinate, choice, committed = int(coordinate), int(choice), int(committed)
        expected = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        require(expected is not None and int(expected) == committed, f"candidate committed byte drift: {row['group']} {coordinate}")
        delta[coordinate] = pf.from_bits(committed) - s_weights[coordinate]
    drow: dict[int, float] = {}
    for coordinate, value in delta.items():
        for row_index, count in state.support_counts[coordinate]:
            drow[int(row_index)] = drow.get(int(row_index), 0.0) + value * count
    return {"row": row, "group": int(row["group"]), "coordinates": set(delta), "delta": delta, "d_axis": math.fsum(delta[i] * state.axis[i] for i in delta), "d_norm": math.fsum((s_weights[i] - state.base_weights[i] + delta[i]) ** 2 - (s_weights[i] - state.base_weights[i]) ** 2 for i in delta), "drow": drow, "base_dot": math.fsum(q_s[index] * value for index, value in drow.items()), "self_sq": math.fsum(value * value for value in drow.values()), "s_cue_sq": s_cue_sq}


def screen_pair(state: Any, s_geometry: dict[str, Any], left: dict[str, Any], right: dict[str, Any], pf5_contract: dict[str, Any]) -> bool:
    axis = float(s_geometry["final_axis"]) + left["d_axis"] + right["d_axis"]
    norm = math.sqrt(max(float(s_geometry["final_norm"]) ** 2 + left["d_norm"] + right["d_norm"], 0.0))
    cross = math.fsum(left["drow"].get(index, 0.0) * value for index, value in right["drow"].items())
    cue_sq = left["s_cue_sq"] + 2.0 * left["base_dot"] + left["self_sq"] + 2.0 * right["base_dot"] + right["self_sq"] + 2.0 * cross
    cue = math.sqrt(max(cue_sq, 0.0))
    gates = pf5_contract["geometry"]["final_da2_gates"]
    axis_error = abs(axis - float(s_geometry["target_axis"])) / max(abs(float(s_geometry["target_axis"])), 1.0e-12)
    norm_error = abs(norm - float(s_geometry["target_norm"])) / max(float(s_geometry["target_norm"]), 1.0e-12)
    cue_error = cue / max(float(state.cue_scale), 1.0e-12)
    return axis_error <= float(gates["axis_normalized_abs"]) + SCREEN_MARGIN and norm_error <= float(gates["norm_normalized_abs"]) + SCREEN_MARGIN and cue_error <= float(gates["cue_linear_normalized_abs"]) + SCREEN_MARGIN


def main() -> int:
    require(not (ROOT / "execution.json").exists(), "pair-domain execution already exists")
    contract = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "pair-domain contract identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "pair-domain PLAN drift")
    require(contract["runner_sha256"] == digest(Path(__file__)), "pair-domain runner drift")
    for item in contract["parent_bindings"]:
        path = REPO / Path(item["path"])
        require(path.is_file() and digest(path) == str(item["sha256"]).upper(), f"parent drift: {item['label']}")
    candidate_execution = json.loads(CANDIDATE_EXECUTION.read_text(encoding="utf-8"))
    require(candidate_execution["status"] == "SREPLACE_CANDIDATES_COMPLETE", "candidate parent is not complete")
    eligible_total = int(candidate_execution["counts"]["eligible_candidates"])
    pf, builder = load_modules()
    _, data = builder.fresh_lineage(CLOSURE_REPO, pf)
    states = {state.key: state for state in data["states"]}
    groups = {key: {int(group.group_index): group for group in data["groups"][key]} for key in KEYS}
    ref = json.loads((REF_ROOT / "execution.json").read_text(encoding="utf-8"))
    pf5_contract = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))
    palette_by_context: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}
    for line in PALETTE.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        key = (str(item["identity"][0]), int(item["identity"][1]))
        palette_by_context.setdefault(key, {})[int(item["identity"][2])] = item
    output_shards: dict[str, list[dict[str, Any]]] = {}
    context_meta = []
    for key in KEYS:
        slug = case_slug(key)
        candidate_rows = json.loads((CANDIDATE_ROOT / "shards" / f"{slug}.jsonl").read_text(encoding="utf-8"))
        state = states[key]
        ref_result = next(item for item in ref["results"] if item["endpoint"] == key[0] and int(item["set_index"]) == key[1])
        s_bits, s_weights, s_geometry = verify_reference(pf, state, ref_result, pf5_contract)
        q_s = tuple(math.fsum(s_weights[index] - state.target_weights[index] for index in row) for row in state.rows)
        s_cue_sq = math.fsum(value * value for value in q_s)
        candidates = [make_candidate(pf, state, s_weights, q_s, s_cue_sq, row, palette_by_context[key][int(row["group"])]) for row in candidate_rows]
        pairs: list[dict[str, Any]] = []
        all_pairs = geometry_screened = coordinate_conflicts = full_geometry_rejects = 0
        for i, left in enumerate(candidates):
            for right in candidates[i + 1:]:
                if left["group"] == right["group"]:
                    continue
                all_pairs += 1
                if left["coordinates"] & right["coordinates"]:
                    coordinate_conflicts += 1
                    continue
                if not screen_pair(state, s_geometry, left, right, pf5_contract):
                    continue
                geometry_screened += 1
                bits = list(s_bits)
                for item in (left, right):
                    palette_item = palette_by_context[key][item["group"]]
                    candidate = next(c for c in palette_item["palette"] if str(c["candidate_identity"]) == str(item["row"]["to"]))
                    for coordinate, choice, committed in candidate["committed_f32_mapping"]:
                        bits[int(coordinate)] = int(committed)
                full_geometry = pf.geometry_metrics(state.rows, tuple(pf.from_bits(raw) for raw in bits), state.base_weights, state.target_weights, state.axis)
                if not pf.final_geometry_pass(full_geometry, pf5_contract):
                    full_geometry_rejects += 1
                    continue
                pairs.append({"pair_index": len(pairs), "case": [key[0], key[1]], "application_base": "fresh_S", "a": compact_candidate(left["row"]), "b": compact_candidate(right["row"]), "combined_geometry": full_geometry, "coordinate_overlap": False})
        output_shards[slug] = pairs
        context_meta.append({"context": [key[0], key[1]], "eligible_candidates": len(candidates), "all_compatible_pairs": all_pairs, "coordinate_conflicts": coordinate_conflicts, "geometry_screened_pairs": geometry_screened, "full_geometry_rejects": full_geometry_rejects, "retained_pairs": len(pairs), "pair_domain_sha256": object_hash(pairs)})
    shard_hashes = {}
    for slug in sorted(output_shards):
        path = ROOT / "shards" / f"{slug}.jsonl"
        write_new(path, output_shards[slug])
        shard_hashes[slug] = digest(path)
    total = sum(len(value) for value in output_shards.values())
    execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SREPLACE_PAIR_DOMAIN_COMPLETE", "engineering_only": True, "scientific_promotion": False, "pair_replay_executed": False, "historical_lr1_results_used_as_evidence": False, "candidate_execution_sha256": digest(CANDIDATE_EXECUTION), "reference_execution_sha256": digest(REF_ROOT / "execution.json"), "closure_manifest_sha256": digest(CLOSURE_ROOT / "MANIFEST.json"), "closure_derived_sha256": digest(CLOSURE_ROOT / "DERIVED.json"), "palette_sha256": digest(PALETTE), "pf5_contract_sha256": digest(PF5_CONTRACT), "screen": {"method": "committed-byte geometry with full PF5 geometry verification for retained pairs", "margin": SCREEN_MARGIN, "sequential_readout_replay": False}, "counts": {"contexts": 8, "eligible_candidates": eligible_total, "all_compatible_pairs": sum(item["all_compatible_pairs"] for item in context_meta), "coordinate_conflicts": sum(item["coordinate_conflicts"] for item in context_meta), "geometry_screened_pairs": sum(item["geometry_screened_pairs"] for item in context_meta), "full_geometry_rejects": sum(item["full_geometry_rejects"] for item in context_meta), "retained_pairs": total}, "contexts": context_meta, "shard_hashes": shard_hashes}
    write_new(ROOT / "execution.json", execution)
    write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "pair_replay_executed": False, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
    print(json.dumps(execution, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
