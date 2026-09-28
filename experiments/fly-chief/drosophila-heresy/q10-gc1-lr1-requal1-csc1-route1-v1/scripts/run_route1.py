from __future__ import annotations

import hashlib
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PROTOCOL = "Q10-CSC1-ROUTE1"
IDENTITY = ROOT.name
UPAIR = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-upair1-v1"
DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-upair1-domain-v1"
PF5_CONTRACT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1/closures/twin-a/repo/experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
CONTEXTS = (
    "seed9731-L-tau16__set2",
    "seed9731-L-tau4__set3",
    "seed9731-R-tau16__set1",
    "seed9731-R-tau16__set3",
    "seed9731-R-tau4__set0",
    "seed9731-R-tau4__set1",
    "seed9731-R-tau4__set2",
    "seed9731-R-tau4__set3",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def score_key(score: dict[str, Any]) -> tuple[Any, ...]:
    return (int(score["mismatch_count"]), int(score["total_ulp_distance"]), float(score["residual_l2"]), float(score["maximum_absolute_residual"]))


def action_id(side: dict[str, Any]) -> str:
    return f"{int(side['group'])}:{str(side['to'])}"


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


def geometry_key(prediction: dict[str, Any], gates: dict[str, Any]) -> tuple[Any, ...]:
    geometry = prediction["predictions"]["structural"]["geometry"]
    ratios = (
        float(geometry["axis_normalized_error"]) / float(gates["axis_normalized_abs"]),
        float(geometry["norm_normalized_error"]) / float(gates["norm_normalized_abs"]),
        float(geometry["cue_linear_normalized_error"]) / float(gates["cue_linear_normalized_abs"]),
    )
    valid = bool(prediction["predictions"]["structural"]["final_geometry_pass"])
    return (0 if valid else 1, max(ratios), sum(max(0.0, value - 1.0) for value in ratios), hash_key(str(prediction["sample_pair_index"])))


def readout_key(partner: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(score_key(partner["score"]))


def load_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    upair_execution = json.loads((UPAIR / "execution.json").read_text(encoding="utf-8"))
    domain_execution = json.loads((DOMAIN / "execution.json").read_text(encoding="utf-8"))
    gates = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))["geometry"]["final_da2_gates"]
    require(upair_execution["status"] == "UPAIR1_COMPLETE", "UPAIR1 is not complete")
    require(int(upair_execution["counts"]["pair_records"]) == 17712, "UPAIR1 cardinality drift")
    require(domain_execution["status"] == "UPAIR1_DOMAIN_COMPLETE", "UPAIR1 domain drift")
    return upair_execution, domain_execution, gates


def load_observations() -> list[dict[str, Any]]:
    directed: list[dict[str, Any]] = []
    for context in CONTEXTS:
        path = UPAIR / "shards" / f"{context}.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            for source_side, partner_side in (("a", "b"), ("b", "a")):
                source = record[source_side]
                partner = record[partner_side]
                directed.append({
                    "context": context,
                    "sample_pair_index": int(record["sample_pair_index"]),
                    "source": action_id(source),
                    "partner": action_id(partner),
                    "source_side": source_side,
                    "partner_side": partner_side,
                    "partner_record": partner,
                    "prediction": record["predictions"],
                    "actual": record["ab"],
                    "outcome": record["outcome"],
                })
    return directed


def rank_observations(observations: list[dict[str, Any]], method: str, gates: dict[str, Any]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[Any, ...]:
        if method == "random":
            return (hash_key(f"random|{item['context']}|{item['source']}|{item['partner']}"),)
        if method == "readout":
            return (*readout_key(item["partner_record"]), hash_key(f"readout|{item['context']}|{item['source']}|{item['partner']}"))
        if method == "geometry":
            return geometry_key(item, gates)
        predicted_valid = bool(item["prediction"]["structural"]["final_geometry_pass"])
        return (0 if predicted_valid else 1, *readout_key(item["partner_record"]), *geometry_key(item, gates), hash_key(f"two_stage|{item['context']}|{item['source']}|{item['partner']}"))

    return sorted(observations, key=key)


def pool_metrics(items: list[dict[str, Any]], method: str, gates: dict[str, Any]) -> dict[str, Any]:
    ranked = rank_observations(items, method, gates)
    successes = [index + 1 for index, item in enumerate(ranked) if item["outcome"] in {"VALID_ADVANTAGE_PRESERVED", "EXACT_ALTERNATIVE"}]
    first = successes[0] if successes else None
    n = len(ranked)
    predicted_valid_count = sum(bool(item["prediction"]["structural"]["final_geometry_pass"]) for item in ranked)
    actual_valid_count = sum(bool(item["actual"]["final_geometry_pass"]) for item in ranked)
    return {
        "n": n,
        "success_count": len(successes),
        "first_success_rank": first,
        "reciprocal_rank": 0.0 if first is None else 1.0 / first,
        "stopping_cost": n if first is None else first,
        "hit_at_1": bool(first is not None and first <= 1),
        "hit_at_5": bool(first is not None and first <= 5),
        "hit_at_10": bool(first is not None and first <= 10),
        "predicted_valid_count": predicted_valid_count,
        "actual_valid_count": actual_valid_count,
        "predicted_valid_before_first_success": sum(not bool(item["prediction"]["structural"]["final_geometry_pass"]) for item in ranked[: (first - 1 if first is not None else n)]),
        "ranked_partner_ids": [item["partner"] for item in ranked],
    }


def aggregate(pool_rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    n = len(pool_rows)
    success_pools = [item for item in pool_rows if item["success_count"] > 0]
    return {
        "method": method,
        "source_pools": n,
        "pools_with_success": len(success_pools),
        "pools_without_success": n - len(success_pools),
        "hit_at_1": sum(item["hit_at_1"] for item in pool_rows) / n if n else None,
        "hit_at_5": sum(item["hit_at_5"] for item in pool_rows) / n if n else None,
        "hit_at_10": sum(item["hit_at_10"] for item in pool_rows) / n if n else None,
        "mean_reciprocal_rank": sum(item["reciprocal_rank"] for item in pool_rows) / n if n else None,
        "mean_stopping_cost": sum(item["stopping_cost"] for item in pool_rows) / n if n else None,
        "mean_first_success_rank_conditional": sum(item["first_success_rank"] for item in success_pools) / len(success_pools) if success_pools else None,
        "mean_predicted_valid_count": sum(item["predicted_valid_count"] for item in pool_rows) / n if n else None,
        "mean_actual_valid_count": sum(item["actual_valid_count"] for item in pool_rows) / n if n else None,
        "exhaustive_evaluations": sum(item["n"] for item in pool_rows),
        "evaluations_saved": sum(item["n"] - item["stopping_cost"] for item in pool_rows),
    }


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(not (ROOT / "execution.json").exists(), "ROUTE1 execution already exists")
    upair_execution, domain_execution, gates = load_inputs()
    bindings = []
    for label, path in (("route1_plan", ROOT / "PLAN.md"), ("route1_runner", Path(__file__)), ("upair_execution", UPAIR / "execution.json"), ("upair_contract", UPAIR / "CONTRACT.json"), ("upair_domain_execution", DOMAIN / "execution.json"), ("upair_domain_contract", DOMAIN / "CONTRACT.json"), ("pf5_contract", PF5_CONTRACT)):
        require(path.is_file(), f"missing ROUTE1 input: {path}")
        bindings.append({"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)})
    contract = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "methods": ["random", "readout", "geometry", "geometry_then_readout"], "primary_success": "actual final-valid pair strictly better than fresh V", "replay_performed": False, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "source-records.jsonl", "REPORT.json"]}
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json"), "replay_performed": False, "outcomes_read_only": True})
    directed = load_observations()
    pools: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in directed:
        pools[(item["context"], item["source"])].append(item)
    require(len(pools) == 3696, f"directed source pool cardinality drift: {len(pools)}")
    methods = ("random", "readout", "geometry", "geometry_then_readout")
    records = []
    for (context, source), items in sorted(pools.items()):
        row = {"context": context, "source": source, "candidate_count": len(items), "actual_success_count": sum(item["outcome"] in {"VALID_ADVANTAGE_PRESERVED", "EXACT_ALTERNATIVE"} for item in items), "methods": {method: pool_metrics(items, method, gates) for method in methods}}
        records.append(row)
    source_bytes = "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in records).encode("utf-8")
    require(not (ROOT / "source-records.jsonl").exists(), "source records already exist")
    (ROOT / "source-records.jsonl").write_bytes(source_bytes)
    aggregates = {method: aggregate([row["methods"][method] for row in records], method) for method in methods}
    mixed_contexts = sum(0 < int(item["valid"]) < int(item["records"]) for item in upair_execution["contexts"])
    report = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "ROUTE1_COMPLETE", "engineering_only": True, "scientific_promotion": False, "replay_performed": False, "outcomes_read_only": True, "counts": {"directed_observations": len(directed), "source_pools": len(records), "successful_directed_observations": sum(row["actual_success_count"] for row in records), "contexts": len(CONTEXTS)}, "methods": aggregates, "diagnosticity": {"mixed_validity_contexts": mixed_contexts, "sample_domain_pairs": int(upair_execution["counts"]["pair_records"]), "domain_outcomes": {"valid": int(upair_execution["counts"]["valid"]), "better_than_V": int(upair_execution["counts"]["better_than_V"]), "exact_alternative": int(upair_execution["counts"]["exact_alternative"])}, "validity_not_saturated": True}, "parent_sha256": {"upair_execution": digest(UPAIR / "execution.json"), "upair_contract": digest(UPAIR / "CONTRACT.json"), "domain_execution": digest(DOMAIN / "execution.json"), "source_records": digest(ROOT / "source-records.jsonl")}}
    write_new(ROOT / "REPORT.json", report)
    write_new(ROOT / "execution.json", report)
    write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "ROUTE1_COMPLETE", "engineering_only": True, "scientific_promotion": False, "replay_performed": False, "execution_sha256": digest(ROOT / "execution.json")})
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
