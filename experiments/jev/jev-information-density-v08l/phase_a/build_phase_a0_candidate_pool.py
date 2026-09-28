"""Build the outcome-blind, training-only v0.8L NOVEL candidate pool."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "experiments/jev-information-density-v08l/phase_a/phase-a-v01-contract.json"
OUT = Path(r"D:\codex-runs\jev-information-density-v08l\phase-a-v01-clean")
F100 = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean\materialized\F100-groups.jsonl")
STATE_INPUTS = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean\materialized\state-inputs.jsonl")
TRIPLETS = Path(r"D:\codex-runs\jev-information-density-v08k\phase-a-v01-clean\inputs\triplets.jsonl")
SHAMS = Path(r"D:\codex-runs\jev-information-density-v08j\phase-a-v01\inputs\sham-views.jsonl")
K_SEAL = Path(r"D:\codex-runs\jev-information-density-v08k\phase-a-v01-clean\seal\k-phase-a-seal-manifest.json")
K_SUMMARY = Path(r"D:\codex-runs\jev-information-density-v08k\phase-b-v01\reports\k-attribution-summary.json")

FAMILY_FIELDS = (
    "world_or_topology_family",
    "ontology_family",
    "schema_composition_family",
    "candidate_set_construction_family",
    "definition_template_family",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def gold_key(row: dict[str, Any]) -> tuple[float, ...]:
    return tuple(round(float(value), 12) for value in row["gold"])


def hard_key(row: dict[str, Any]) -> tuple[Any, ...]:
    families = tuple((field, row["family_ids"].get(field)) for field in FAMILY_FIELDS)
    return (
        row["kind"],
        row["view"],
        int(row["candidate_cardinality"]),
        tuple(row["candidate_semantic_ids"]),
        tuple(row["candidate_indices"]["name_definition"]),
        families,
        row["probability_source"],
        gold_key(row),
    )


def key_text(key: tuple[Any, ...]) -> str:
    return json.dumps(key, ensure_ascii=False, separators=(",", ":"))


def main() -> int:
    contract = read_json(CONTRACT_PATH)
    require(contract["phase_a_identity"] == "phase-a-v01-clean", "L Phase-A identity drift")
    require(read_json(K_SEAL)["status"] == "PHASE_A_COMPLETE_NONPARENTABLE_PHASE_B_UNAUTHORIZED", "K parent is not sealed")
    k_summary = read_json(K_SUMMARY)
    require(k_summary["status"] == "COMPLETE", "K attribution summary is not complete")
    require(k_summary["no_follow_on_authorized"] is True, "K follow-on boundary drift")

    primary = read_jsonl(F100)
    state_rows = read_jsonl(STATE_INPUTS)
    triplets = read_jsonl(TRIPLETS)
    sham_rows = read_jsonl(SHAMS)
    require(len(primary) == 100_000 and len({row["group_id"] for row in primary}) == 100_000, "F100 count/identity drift")
    require(len(state_rows) > 0 and all(row.get("index") == index for index, row in enumerate(state_rows)), "state table is not canonical indexed training data")
    require(len(triplets) == 5_000 and len(sham_rows) == 5_000, "triplet or sham count drift")
    require(all(row.get("split") == "train" for row in primary), "non-training primary row encountered")
    require(all(row.get("split") == "train" for row in sham_rows), "non-training sham row encountered")

    primary_by_id = {row["group_id"]: row for row in primary}
    sham_by_id = {row["group_id"]: row for row in sham_rows}
    state_texts = [row["text"] for row in state_rows]

    anchors: list[dict[str, Any]] = []
    seen_triplets: set[str] = set()
    for item in triplets:
        triplet_id = item["triplet_id"]
        require(triplet_id not in seen_triplets, f"duplicate triplet: {triplet_id}")
        seen_triplets.add(triplet_id)
        anchor = primary_by_id.get(item["anchor_group_id"])
        sham = sham_by_id.get(item["sham_group_id"])
        fact = primary_by_id.get(item["fact_flip_group_id"])
        require(anchor is not None and fact is not None and sham is not None, f"triplet source missing: {triplet_id}")
        require(anchor["contrast_role"] == "anchor", f"anchor role drift: {triplet_id}")
        require(sham["contrast_role"] == "sham", f"sham role drift: {triplet_id}")
        require(anchor["candidate_semantic_ids"] == sham["candidate_semantic_ids"], f"anchor/sham schema drift: {triplet_id}")
        require(gold_key(anchor) == gold_key(sham), f"anchor/sham target drift: {triplet_id}")
        require(max(range(len(anchor["gold"])), key=anchor["gold"].__getitem__) != max(range(len(fact["gold"])), key=fact["gold"].__getitem__), f"fact flip drift: {triplet_id}")
        anchors.append({
            "triplet_id": triplet_id,
            "anchor": anchor,
            "fact": fact,
            "sham": sham,
            "triplet_group_ids": {anchor["group_id"], fact["group_id"], sham["group_id"]},
        })

    candidate_rows = [
        row for row in primary
        if row.get("contrast_role") == "anchor"
        and row.get("split") == "train"
        and row.get("view") == "choice"
        and row.get("kind") == "choice"
        and int(row.get("candidate_cardinality", -1)) == 4
        and row.get("probability_source") == "exact_generative_posterior"
    ]
    require(len(candidate_rows) == 5_000, f"unexpected NOVEL candidate anchor count: {len(candidate_rows)}")
    candidate_by_key: defaultdict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_rows:
        candidate_by_key[hard_key(row)].append(row)

    pool: list[dict[str, Any]] = []
    counts: list[int] = []
    key_counts: Counter[str] = Counter()
    for record in anchors:
        anchor = record["anchor"]
        key = hard_key(anchor)
        key_id = sha256_json(key)
        eligible = []
        for candidate in candidate_by_key[key]:
            if candidate["group_id"] in record["triplet_group_ids"]:
                continue
            if candidate["root_id"] == anchor["root_id"]:
                continue
            candidate_state = state_texts[int(candidate["state_idx"])]
            anchor_state = state_texts[int(anchor["state_idx"])]
            if candidate_state == anchor_state:
                continue
            eligible.append({
                "triplet_id": record["triplet_id"],
                "anchor_group_id": anchor["group_id"],
                "anchor_state_idx": int(anchor["state_idx"]),
                "sham_group_id": record["sham"]["group_id"],
                "sham_state_idx": int(record["sham"]["state_idx"]),
                "candidate_group_id": candidate["group_id"],
                "candidate_state_idx": int(candidate["state_idx"]),
                "candidate_root_id": candidate["root_id"],
                "hard_key_sha256": key_id,
                "target_l1": sum(abs(float(a) - float(b)) for a, b in zip(anchor["gold"], candidate["gold"])),
                "target_exact": gold_key(anchor) == gold_key(candidate),
            })
        counts.append(len(eligible))
        key_counts[key_id] += 1
        pool.extend(eligible)

    require(len(pool) > 0 and min(counts) > 0, f"NOVEL candidate pool is infeasible: min={min(counts)}")
    require(all(row["target_exact"] and row["target_l1"] <= 1e-12 for row in pool), "target exactness drift in candidate pool")
    require(len({row["candidate_group_id"] for row in pool}) == len(candidate_rows), "candidate pool identity drift")

    OUT.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT / "candidate-pool.jsonl", pool)
    source_hashes = {name: sha256_file(path) for name, path in {
        "contract": CONTRACT_PATH,
        "F100": F100,
        "state_inputs": STATE_INPUTS,
        "triplets": TRIPLETS,
        "sham_views": SHAMS,
        "k_seal": K_SEAL,
        "k_summary": K_SUMMARY,
    }.items()}
    summary = {
        "protocol": contract["protocol"],
        "status": "PHASE_A0_CANDIDATE_POOL_READY_NO_MODEL_CONTACT",
        "phase_a_identity": contract["phase_a_identity"],
        "source_scope": "training_only",
        "primary_groups": len(primary),
        "triplets": len(anchors),
        "candidate_anchor_rows": len(candidate_rows),
        "candidate_pool_rows": len(pool),
        "per_anchor_candidate_count": {
            "min": min(counts),
            "median": median(counts),
            "max": max(counts),
            "mean": sum(counts) / len(counts),
        },
        "hard_key_count": len(key_counts),
        "target_matching": "exact within 1e-12 per component",
        "different_root": True,
        "different_state_text": True,
        "candidate_reuse_cap": 1,
        "model_contact": False,
        "feature_extraction": False,
        "training": False,
        "evaluation_bodies_opened": False,
        "phoenix_access": False,
        "source_hashes": source_hashes,
        "candidate_pool_sha256": sha256_file(OUT / "candidate-pool.jsonl"),
    }
    write_json(OUT / "candidate-pool-summary.json", summary)
    write_json(OUT / "candidate-pool-receipt.json", {
        "status": "PASS",
        "protocol": contract["protocol"],
        "contract_sha256": sha256_file(CONTRACT_PATH),
        "summary_sha256": sha256_file(OUT / "candidate-pool-summary.json"),
        "candidate_pool_sha256": summary["candidate_pool_sha256"],
        "selection_objective": "none; eligibility enumeration only",
        "outcome_blind": True,
        "protected_evaluation_bodies_opened": False,
        "model_contact": False,
        "phoenix_access": False,
    })
    print(json.dumps({"status": summary["status"], "candidate_pool_rows": len(pool), "min_per_anchor": min(counts), "max_per_anchor": max(counts)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
