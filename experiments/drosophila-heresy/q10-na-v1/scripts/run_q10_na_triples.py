"""Exact triple replay for the Q10-NA rows with complete pair-negative domains."""
from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import run_q10_na_pairs as pairs


TRIPLE_LIMIT_TOTAL = 50_000_000


def run_target(target: dict[str, Any], state: dict[str, Any], coordinates: set[int]) -> dict[str, Any]:
    row = int(target["row"])
    target_value = pairs.na.from_bits(int(target["target_bits"]))
    baseline_ulp = int(target["baseline_ulp_distance"])
    ordered = sorted(coordinates)
    domains = {coordinate: pairs.legal_choices(state, coordinate) for coordinate in ordered}
    triple_domain = sum(
        len(domains[left]) * len(domains[middle]) * len(domains[right])
        for left_index, left in enumerate(ordered)
        for middle_index, middle in enumerate(ordered[left_index + 1 :], start=left_index + 1)
        for right in ordered[middle_index + 1 :]
    )
    if triple_domain == 0:
        return {
            "target": [target["endpoint"], target["set_index"], row],
            "support_size": len(ordered),
            "triple_domain": 0,
            "triple_replays": 0,
            "triple_domain_complete": True,
            "classification": "no-effect-within-complete-domain",
            "improving_triple_count": 0,
            "best": None,
        }

    best: dict[str, Any] | None = None
    replays = 0
    improving = 0
    for left_index, left in enumerate(ordered):
        for middle_index, middle in enumerate(ordered[left_index + 1 :], start=left_index + 1):
            for right in ordered[middle_index + 1 :]:
                for choices in itertools.product(domains[left], domains[middle], domains[right]):
                    assignments = ((left, choices[0]), (middle, choices[1]), (right, choices[2]))
                    actual = pairs.row_value_assignments(state, row, assignments)
                    distance = pairs.ulp_distance(actual, target_value)
                    replays += 1
                    if distance < baseline_ulp:
                        improving += 1
                        candidate = pairs.candidate_weights(state, assignments)
                        record = {
                            "coordinates": [left, middle, right],
                            "choices": list(choices),
                            "observed_bits": pairs.na.bits(actual),
                            "target_bits": int(target["target_bits"]),
                            "baseline_ulp": baseline_ulp,
                            "candidate_ulp": distance,
                            "geometry": pairs.geometry_signature(candidate, state["fixture"]),
                        }
                        if best is None or (distance, tuple(record["coordinates"]), tuple(record["choices"])) < (
                            best["candidate_ulp"], tuple(best["coordinates"]), tuple(best["choices"])
                        ):
                            best = record
    return {
        "target": [target["endpoint"], target["set_index"], row],
        "support_size": len(ordered),
        "triple_domain": triple_domain,
        "triple_replays": replays,
        "triple_domain_complete": replays == triple_domain,
        "classification": "triple" if improving else "no-effect-within-complete-domain",
        "improving_triple_count": improving,
        "best": best,
    }


def main() -> int:
    root = pairs.na.protocol_root()
    pair_receipt = pairs.na.load_json(root / "qualification" / "pair-full.json")
    if pair_receipt.get("stage") != "PAIR_REPLAY_FULL" or pair_receipt.get("triple_replay_executed"):
        raise RuntimeError("complete pair receipt is required before triples")
    contract, targets, states, raw_coordinates = pairs.prepare()
    by_key = {(item["endpoint"], item["set_index"], item["row"]): item for item in targets}
    selected = [
        by_key[tuple(record["target"])]
        for record in pair_receipt["records"]
        if record["classification"] == "no-effect-within-complete-domain"
    ]
    projected = json.loads((root / "qualification" / "preflight.json").read_text(encoding="utf-8"))
    projected_by_key = {
        (item["endpoint"], item["set_index"], item["row"]): item
        for item in projected["cost_projection"]["per_target"]
    }
    total_projected = sum(projected_by_key[(item["endpoint"], item["set_index"], item["row"])]["exact_triple_candidates"] for item in selected)
    if total_projected > TRIPLE_LIMIT_TOTAL:
        raise RuntimeError(f"pair-negative triple domain exceeds budget: {total_projected}")

    records: list[dict[str, Any]] = []
    for item in selected:
        key = (item["endpoint"], item["set_index"])
        support = raw_coordinates[(item["endpoint"], item["set_index"], item["row"])]
        records.append(run_target(item, states[key], support))
    receipt = {
        "protocol": "Q10-NA",
        "stage": "TRIPLE_REPLAY_PAIR_NEGATIVE_TAIL",
        "engineering_only": True,
        "contract_plan_sha256": contract["plan_sha256"],
        "pair_negative_rows": len(selected),
        "target_rows_replayed": len(records),
        "projected_triple_domain": total_projected,
        "triple_replays": sum(record["triple_replays"] for record in records),
        "scientific_seed_bundles_used": 0,
        "behavioral_inference": False,
        "canonical_repair_applied": False,
        "dh08b_authorized": False,
        "pair_replay_executed": True,
        "triple_replay_executed": True,
        "records": records,
    }
    output = root / "qualification" / "triple-full.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "targets": len(records), "triple_replays": receipt["triple_replays"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
