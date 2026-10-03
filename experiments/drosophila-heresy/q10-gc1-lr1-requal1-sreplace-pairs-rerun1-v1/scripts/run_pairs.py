"""Exact sequential-f32 replay of the fresh screened S-replacement pairs."""
from __future__ import annotations

import concurrent.futures
import hashlib
import importlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

PROTOCOL = "REQUAL1-SREPLACE-PAIRS-RERUN1"
IDENTITY = "q10-gc1-lr1-requal1-sreplace-pairs-rerun1-v1"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PAIR_DOMAIN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pair-domain-v1"
PAIR_EXECUTION = PAIR_DOMAIN_ROOT / "execution.json"
CANDIDATE_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-candidates-v1"
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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def bits_hash(values: tuple[int, ...]) -> str:
    return digest_bytes(b"".join(int(value).to_bytes(4, "little", signed=False) for value in values))


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


def score_dict(pf: Any, actual: tuple[int, ...], target: tuple[int, ...]) -> dict[str, Any]:
    residuals = [pf.from_bits(a) - pf.from_bits(t) for a, t in zip(actual, target)]
    return {"mismatch_count": sum(a != t for a, t in zip(actual, target)), "total_ulp_distance": sum(pf.ulp_distance(pf.from_bits(a), pf.from_bits(t)) for a, t in zip(actual, target)), "residual_l2": math.sqrt(math.fsum(value * value for value in residuals)), "maximum_absolute_residual": max((abs(value) for value in residuals), default=0.0)}


def score_key(score: dict[str, Any]) -> tuple[Any, ...]:
    return (int(score["mismatch_count"]), int(score["total_ulp_distance"]), float(score["residual_l2"]), float(score["maximum_absolute_residual"]))


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


def replay(pf: Any, state: Any, bits: tuple[int, ...], pf5_contract: dict[str, Any]) -> dict[str, Any]:
    weights = tuple(pf.from_bits(raw) for raw in bits)
    readout = tuple(int(value) for value in pf.readout_bits(state.rows, weights))
    geometry = pf.geometry_metrics(state.rows, weights, state.base_weights, state.target_weights, state.axis)
    return {"bits": bits, "weights": weights, "readout": readout, "weight_state_sha256": bits_hash(bits), "readout_sha256": bits_hash(readout), "score": score_dict(pf, readout, state.target_readout_bits), "geometry": geometry, "final_geometry_pass": bool(pf.final_geometry_pass(geometry, pf5_contract))}


def verify_s(pf: Any, state: Any, ref_result: dict[str, Any], pf5_contract: dict[str, Any]) -> dict[str, Any]:
    bits = mapping_bits(pf, state, ref_result["best_search"]["canonical_mapping"])
    result = replay(pf, state, bits, pf5_contract)
    expected = ref_result["best_search"]
    require(result["weight_state_sha256"] == str(expected["weight_state_sha256"]).upper(), f"S weight drift: {state.key}")
    require(result["readout_sha256"] == str(expected["readout_sha256"]).upper(), f"S readout drift: {state.key}")
    require(result["score"] == expected["score"] and result["geometry"] == expected["geometry"], f"S receipt drift: {state.key}")
    require(not result["final_geometry_pass"], f"S unexpectedly valid: {state.key}")
    return result


def apply_candidate(pf: Any, state: Any, s_bits: tuple[int, ...], palette_item: dict[str, Any], candidate_id: str) -> tuple[int, ...]:
    candidate = next((item for item in palette_item["palette"] if str(item["candidate_identity"]) == candidate_id), None)
    require(candidate is not None, f"pair candidate missing from palette: {candidate_id}")
    bits = list(s_bits)
    seen = set()
    for coordinate, choice, committed in candidate["committed_f32_mapping"]:
        coordinate, choice, committed = int(coordinate), int(choice), int(committed)
        require(coordinate not in seen, f"duplicate candidate coordinate: {coordinate}")
        seen.add(coordinate)
        expected = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
        require(expected is not None and int(expected) == committed, f"pair candidate byte drift: {candidate_id} {coordinate}")
        bits[coordinate] = committed
    return tuple(bits)


def fixed_damaged(base: tuple[int, ...], actual: tuple[int, ...], target: tuple[int, ...]) -> tuple[int, int]:
    fixed = sum(a != t and b == t for a, b, t in zip(base, actual, target))
    damaged = sum(a == t and b != t for a, b, t in zip(base, actual, target))
    return fixed, damaged


def run_context(args: tuple[str, int, str]) -> tuple[tuple[str, int], list[dict[str, Any]]]:
    endpoint, set_index, repo_text = args
    sys.dont_write_bytecode = True
    pf, builder = load_modules()
    _, data = builder.fresh_lineage(Path(repo_text), pf)
    key = (endpoint, set_index)
    state = next(item for item in data["states"] if item.key == key)
    ref = json.loads((REF_ROOT / "execution.json").read_text(encoding="utf-8"))
    ref_result = next(item for item in ref["results"] if item["endpoint"] == endpoint and int(item["set_index"]) == set_index)
    pf5_contract = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))
    s = verify_s(pf, state, ref_result, pf5_contract)
    v_bits = mapping_bits(pf, state, ref_result["best_valid"]["canonical_mapping"])
    v = replay(pf, state, v_bits, pf5_contract)
    require(v["final_geometry_pass"] and v["score"] == ref_result["best_valid"]["score"], f"V receipt drift: {key}")
    domain_shard_hashes = json.loads(PAIR_EXECUTION.read_text(encoding="utf-8"))["shard_hashes"]
    pair_path = PAIR_DOMAIN_ROOT / "shards" / f"{case_slug(key)}.jsonl"
    require(digest(pair_path) == str(domain_shard_hashes[case_slug(key)]).upper(), f"pair-domain shard drift: {key}")
    pair_rows = json.loads(pair_path.read_text(encoding="utf-8"))
    palette = {}
    for line in PALETTE.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        if str(item["identity"][0]) == endpoint and int(item["identity"][1]) == set_index:
            palette[int(item["identity"][2])] = item
    output = []
    target = tuple(state.target_readout_bits)
    for pair in pair_rows:
        left, right = pair["a"], pair["b"]
        require(int(left["group"]) != int(right["group"]), f"same-group pair: {key}")
        a_bits = apply_candidate(pf, state, s["bits"], palette[int(left["group"])], str(left["to"]))
        b_bits = apply_candidate(pf, state, s["bits"], palette[int(right["group"])], str(right["to"]))
        ab_bits = list(s["bits"])
        for candidate in (left, right):
            combined = apply_candidate(pf, state, tuple(ab_bits), palette[int(candidate["group"])], str(candidate["to"]))
            ab_bits = list(combined)
        a = replay(pf, state, a_bits, pf5_contract)
        b = replay(pf, state, b_bits, pf5_contract)
        ab = replay(pf, state, tuple(ab_bits), pf5_contract)
        require(a["weight_state_sha256"] == str(left["singleton_weight_state_sha256"]).upper() and a["readout_sha256"] == str(left["singleton_readout_sha256"]).upper(), f"A singleton control drift: {key} {pair['pair_index']}")
        require(b["weight_state_sha256"] == str(right["singleton_weight_state_sha256"]).upper() and b["readout_sha256"] == str(right["singleton_readout_sha256"]).upper(), f"B singleton control drift: {key} {pair['pair_index']}")
        fixed, damaged = fixed_damaged(s["readout"], ab["readout"], target)
        target_equal = ab["readout"] == target
        outcome = "EXACT_ALTERNATIVE" if target_equal and ab["final_geometry_pass"] and ab["bits"] != v["bits"] and ab["bits"] != s["bits"] else ("VALID_ADVANTAGE_PRESERVED" if ab["final_geometry_pass"] and score_key(ab["score"]) < score_key(v["score"]) and ab["bits"] != s["bits"] else ("VALID_TIE_NON_SUCCESS" if ab["final_geometry_pass"] and score_key(ab["score"]) == score_key(v["score"]) else ("VALID_WORSE_NON_SUCCESS" if ab["final_geometry_pass"] else "INVALID_NON_SUCCESS")))
        output.append({"pair_index": int(pair["pair_index"]), "case": [endpoint, set_index], "application_base": "fresh_S", "a": {"group": int(left["group"]), "to": str(left["to"]), "weight_state_sha256": a["weight_state_sha256"], "readout_sha256": a["readout_sha256"], "score": a["score"], "geometry": a["geometry"], "final_geometry_pass": a["final_geometry_pass"]}, "b": {"group": int(right["group"]), "to": str(right["to"]), "weight_state_sha256": b["weight_state_sha256"], "readout_sha256": b["readout_sha256"], "score": b["score"], "geometry": b["geometry"], "final_geometry_pass": b["final_geometry_pass"]}, "s": {"weight_state_sha256": s["weight_state_sha256"], "readout_sha256": s["readout_sha256"], "score": s["score"], "geometry": s["geometry"], "final_geometry_pass": s["final_geometry_pass"]}, "ab": {"canonical_mapping": sorted(left["canonical_mapping"] + right["canonical_mapping"]), "weight_state_sha256": ab["weight_state_sha256"], "readout_sha256": ab["readout_sha256"], "score": ab["score"], "geometry": ab["geometry"], "final_geometry_pass": ab["final_geometry_pass"]}, "fixed": fixed, "damaged": damaged, "target_equal": target_equal, "outcome": outcome})
    require(len(output) == len(pair_rows), f"pair shard cardinality drift: {key}")
    return key, output


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "Python bytecode generation is enabled")
    require(not (ROOT / "scripts" / "__pycache__").exists(), "unexpected preflight __pycache__")
    require(not (ROOT / "execution.json").exists(), "pair execution already exists")
    contract = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "pair contract identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "pair PLAN drift")
    require(contract["runner_sha256"] == digest(Path(__file__)), "pair runner drift")
    for item in contract["parent_bindings"]:
        path = REPO / Path(item["path"])
        require(path.is_file() and digest(path) == str(item["sha256"]).upper(), f"parent drift: {item['label']}")
    domain = json.loads(PAIR_EXECUTION.read_text(encoding="utf-8"))
    require(domain["status"] == "SREPLACE_PAIR_DOMAIN_COMPLETE", "pair domain is not complete")
    require(int(domain["counts"]["retained_pairs"]) == sum(int(item["retained_pairs"]) for item in domain["contexts"]), "pair domain count drift")
    all_rows: dict[str, list[dict[str, Any]]] = {}
    closure = str(CLOSURE_REPO)
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(run_context, (key[0], key[1], closure)) for key in KEYS]
            for future in futures:
                key, rows = future.result()
                slug = case_slug(key)
                all_rows[slug] = rows
                write_new(ROOT / "shards" / f"{slug}.jsonl", rows)
                print(json.dumps({"context": [key[0], key[1]], "status": "SREPLACE_PAIRS_COMPLETE", "records": len(rows)}, sort_keys=True), flush=True)
        ordered = [row for key in KEYS for row in all_rows[case_slug(key)]]
        require(len(ordered) == int(domain["counts"]["retained_pairs"]), f"pair total cardinality drift: {len(ordered)}")
        shard_hashes = {slug: digest(ROOT / "shards" / f"{slug}.jsonl") for slug in sorted(all_rows)}
        execution_hygiene = {
            "python_flag_B": bool(sys.dont_write_bytecode),
            "PYTHONDONTWRITEBYTECODE": os.environ.get("PYTHONDONTWRITEBYTECODE"),
            "preflight_no_pycache": True,
            "unexpected_path_policy": "FAIL_PROMOTION",
            "write_allowlist": ["shards/*.jsonl", "execution.json", "STATUS.json"],
        }
        execution = {"protocol": PROTOCOL, "execution_hygiene": execution_hygiene, "identity": IDENTITY, "status": "SREPLACE_PAIRS_COMPLETE", "engineering_only": True, "scientific_promotion": False, "behavioral_probe": False, "historical_lr1_results_used_as_evidence": False, "pair_replay_executed": True, "pair_domain_execution_sha256": digest(PAIR_EXECUTION), "reference_execution_sha256": digest(REF_ROOT / "execution.json"), "closure_manifest_sha256": digest(CLOSURE_ROOT / "MANIFEST.json"), "closure_derived_sha256": digest(CLOSURE_ROOT / "DERIVED.json"), "palette_sha256": digest(PALETTE), "pf5_contract_sha256": digest(PF5_CONTRACT), "counts": {"contexts": 8, "pair_records": len(ordered), "exact_alternative": sum(row["outcome"] == "EXACT_ALTERNATIVE" for row in ordered), "valid_advantage_preserved": sum(row["outcome"] == "VALID_ADVANTAGE_PRESERVED" for row in ordered), "valid_any": sum(bool(row["ab"]["final_geometry_pass"]) for row in ordered)}, "shard_hashes": shard_hashes}
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "pair_replay_executed": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_SREPLACE_PAIRS", "engineering_only": True, "scientific_promotion": False, "pair_replay_executed": bool(all_rows), "error_type": type(exc).__name__, "error": str(exc), "completed_shards": sorted(all_rows)}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
