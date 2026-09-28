"""Derive a fresh S-replacement shortlist and pair domain without replay."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROTOCOL = "REQUAL1-SREPLACE-DOMAIN"
IDENTITY = "q10-gc1-lr1-requal1-sreplace-domain-v1"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
SREPLACE_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-singles-v1"
SINGLES_EXECUTION = SREPLACE_ROOT / "execution.json"
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


def object_hash(value: Any) -> str:
    return digest_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    require(not tmp.exists(), f"orphan temporary output exists: {tmp}")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)


def score_key(row: dict[str, Any]) -> tuple[Any, ...]:
    score = row["score"]
    return (int(score["mismatch_count"]), int(score["total_ulp_distance"]), float(score["residual_l2"]), float(score["maximum_absolute_residual"]))


def candidate_key(row: dict[str, Any]) -> tuple[int, str]:
    return int(row["group"]), str(row["to"])


def unique_append(out: list[dict[str, Any]], seen: set[tuple[int, str]], row: dict[str, Any], lane: str) -> None:
    key = candidate_key(row)
    if key in seen:
        return
    seen.add(key)
    item = dict(row)
    item["selector_lane"] = lane
    item["shortlist_rank"] = len(out)
    out.append(item)


def select(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    eligible = [row for row in rows if int(row["replacement_changed_coordinate_count"]) > 0]
    require(len(eligible) >= 32, "fewer than 32 nonidentity singleton candidates")
    seen: set[tuple[int, str]] = set()
    selected: list[dict[str, Any]] = []
    geometry = sorted(eligible, key=lambda row: (float(row["max_ratio"]), float(row["excess"]), score_key(row), int(row["damaged"]), int(row["group"]), str(row["to"])))
    for row in geometry[:16]:
        unique_append(selected, seen, row, "GEOMETRY")
    collateral = sorted((row for row in eligible if candidate_key(row) not in seen), key=lambda row: (int(row["damaged"]), score_key(row), float(row["excess"]), int(row["group"]), str(row["to"])))
    for row in collateral[:8]:
        unique_append(selected, seen, row, "COLLATERAL")
    buckets: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for row in eligible:
        if candidate_key(row) not in seen:
            buckets.setdefault(tuple(int(value) for value in row["bucket"]), []).append(row)
    for values in buckets.values():
        values.sort(key=lambda row: (int(row["group"]), str(row["to"])))
    bucket_order = sorted(buckets)
    offset = 0
    while len(selected) < 32 and offset < max((len(value) for value in buckets.values()), default=0):
        progressed = False
        for bucket in bucket_order:
            values = buckets[bucket]
            if offset < len(values):
                unique_append(selected, seen, values[offset], "BUCKET")
                progressed = True
                if len(selected) >= 32:
                    break
        if not progressed:
            break
        offset += 1
    require(len(selected) == 32, f"shortlist cardinality drift: {len(selected)}")
    for rank, row in enumerate(selected):
        row["shortlist_rank"] = rank
    provenance = {
        "eligible_nonidentity": len(eligible),
        "excluded_identity_replacements": len(rows) - len(eligible),
        "slots": {"geometry": 16, "collateral": 8, "bucket_fill": 8},
        "score_definition": ["mismatch_count", "total_ulp_distance", "residual_l2", "maximum_absolute_residual"],
        "geometry_key": ["max_ratio_asc", "excess_asc", "score_asc", "damaged_asc", "group_asc", "candidate_id_asc"],
        "collateral_key": ["damaged_asc", "score_asc", "excess_asc", "group_asc", "candidate_id_asc"],
        "bucket_key": ["group", "sign_d_axis", "sign_opp"],
        "pair_rule": "all unordered selected pairs with distinct group IDs",
        "historical_lr1_selector_used": False,
    }
    return selected, provenance


def compact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "group": int(row["group"]),
        "from": str(row["from"]),
        "to": str(row["to"]),
        "canonical_mapping": row["canonical_mapping"],
        "source_singleton_row": {
            "weight_state_sha256": str(row["source_singleton_weight_state_sha256"]).upper(),
            "readout_sha256": str(row["source_singleton_readout_sha256"]).upper(),
        },
        "singleton_score": row["score"],
        "singleton_geometry": row["geometry"],
        "singleton_final_geometry_pass": bool(row["final_geometry_pass"]),
        "strictly_better_than_V": bool(row["strictly_better_than_V"]),
        "d_axis": float(row["d_axis"]),
        "opp": float(row["opp"]),
        "bucket": [int(value) for value in row["bucket"]],
        "selector_lane": str(row["selector_lane"]),
        "shortlist_rank": int(row["shortlist_rank"]),
    }


def main() -> int:
    require(not (ROOT / "execution.json").exists(), "domain execution already exists")
    contract = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "domain contract identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "domain PLAN drift")
    require(contract["runner_sha256"] == digest(Path(__file__)), "domain runner drift")
    parent = json.loads(SINGLES_EXECUTION.read_text(encoding="utf-8"))
    require(parent["status"] == "SREPLACE_SINGLETONS_COMPLETE", "singleton parent is not complete")
    require(parent["counts"]["nonzero_singletons"] == 3696, "singleton parent cardinality drift")
    for item in contract["parent_bindings"]:
        path = REPO / Path(item["path"])
        require(path.is_file() and digest(path) == str(item["sha256"]).upper(), f"parent drift: {item['label']}")
    all_rows: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for key in KEYS:
        slug = f"{key[0].removesuffix('.json')}__set{key[1]}"
        path = SREPLACE_ROOT / "shards" / f"{slug}.jsonl"
        require(digest(path) == str(parent["shard_hashes"][slug]).upper(), f"singleton shard drift: {key}")
        rows = json.loads(path.read_text(encoding="utf-8"))
        require(all(str(row["endpoint"]) == key[0] and int(row["set_index"]) == key[1] for row in rows), f"singleton context drift: {key}")
        require(len(rows) > 0, f"empty singleton context: {key}")
        all_rows[key] = rows
    shortlists: dict[str, list[dict[str, Any]]] = {}
    pairs: dict[str, list[dict[str, Any]]] = {}
    context_meta = []
    for key in KEYS:
        slug = f"{key[0].removesuffix('.json')}__set{key[1]}"
        selected, provenance = select(all_rows[key])
        short = [compact(row) for row in selected]
        pair_rows = []
        for i, left in enumerate(short):
            for j in range(i + 1, len(short)):
                right = short[j]
                if int(left["group"]) == int(right["group"]):
                    continue
                pair_rows.append({"pair_index": len(pair_rows), "a": left, "b": right, "case": [key[0], key[1]], "semantics": "simultaneous replacement of groups A and B in fresh S"})
        shortlists[slug] = short
        pairs[slug] = pair_rows
        context_meta.append({"context": [key[0], key[1]], "singleton_records": len(all_rows[key]), "shortlist_records": len(short), "pair_records": len(pair_rows), "provenance": provenance, "shortlist_sha256": object_hash(short), "pair_domain_sha256": object_hash(pair_rows)})
    short_root = ROOT / "shortlists"
    pair_root = ROOT / "pair-domains"
    short_hashes = {}
    pair_hashes = {}
    for slug in sorted(shortlists):
        write_path = short_root / f"{slug}.json"
        pair_path = pair_root / f"{slug}.json"
        require(not write_path.exists() and not pair_path.exists(), "domain output exists")
        write_path.parent.mkdir(parents=True, exist_ok=True)
        pair_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(json.dumps(shortlists[slug], indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        pair_path.write_text(json.dumps(pairs[slug], indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        short_hashes[slug] = digest(write_path)
        pair_hashes[slug] = digest(pair_path)
    total_pairs = sum(len(value) for value in pairs.values())
    execution = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": "SREPLACE_DOMAIN_COMPLETE",
        "engineering_only": True,
        "scientific_promotion": False,
        "pair_replay_executed": False,
        "historical_lr1_results_used_as_evidence": False,
        "parent_singletons_execution_sha256": digest(SINGLES_EXECUTION),
        "counts": {"contexts": 8, "singleton_records": 3696, "shortlist_records": 256, "pair_records": total_pairs},
        "contexts": context_meta,
        "shortlist_hashes": short_hashes,
        "pair_domain_hashes": pair_hashes,
        "selector": {"identity_replacements_excluded": True, "shortlist_size": 32, "geometry_slots": 16, "collateral_slots": 8, "bucket_slots": 8, "pair_rule": "unordered distinct-group pairs"},
    }
    write_new(ROOT / "execution.json", execution)
    write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "pair_replay_executed": False, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
    print(json.dumps(execution, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
