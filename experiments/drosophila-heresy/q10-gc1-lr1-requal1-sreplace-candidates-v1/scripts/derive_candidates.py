"""Derive the complete fresh S-replacement pair-eligible candidate library."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROTOCOL = "REQUAL1-SREPLACE-CANDIDATES"
IDENTITY = "q10-gc1-lr1-requal1-sreplace-candidates-v1"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PARENT_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-singles-v1"
PARENT_EXECUTION = PARENT_ROOT / "execution.json"
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


def case_slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def source_manifest() -> dict[str, Any]:
    paths = [ROOT / "PLAN.md", ROOT / "CONTRACT.json", Path(__file__), PARENT_EXECUTION, PARENT_ROOT / "ROOT_MANIFEST.json", PARENT_ROOT / "PLAN.md", PARENT_ROOT / "CONTRACT.json", PARENT_ROOT / "scripts/run_sreplace_singles.py"]
    entries = []
    for key in KEYS:
        paths.append(PARENT_ROOT / "shards" / f"{case_slug(key)}.jsonl")
    for path in paths:
        require(path.is_file(), f"missing candidate-library input: {path}")
        entries.append({"path": path.relative_to(REPO).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size})
    return {"protocol": PROTOCOL, "identity": IDENTITY, "entries": entries, "manifest_sha256": object_hash(entries)}


def main() -> int:
    require(not (ROOT / "execution.json").exists(), "candidate execution already exists")
    contract = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "candidate contract identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "candidate PLAN drift")
    require(contract["runner_sha256"] == digest(Path(__file__)), "candidate runner drift")
    parent = json.loads(PARENT_EXECUTION.read_text(encoding="utf-8"))
    require(parent["status"] == "SREPLACE_SINGLETONS_COMPLETE", "singleton parent is not complete")
    require(parent["counts"]["nonzero_singletons"] == 3696, "singleton parent count drift")
    for item in contract["parent_bindings"]:
        path = REPO / Path(item["path"])
        require(path.is_file() and digest(path) == str(item["sha256"]).upper(), f"parent drift: {item['label']}")
    eligible_shards: dict[str, list[dict[str, Any]]] = {}
    context_meta = []
    for key in KEYS:
        slug = case_slug(key)
        path = PARENT_ROOT / "shards" / f"{slug}.jsonl"
        require(digest(path) == str(parent["shard_hashes"][slug]).upper(), f"singleton shard drift: {key}")
        rows = json.loads(path.read_text(encoding="utf-8"))
        eligible = []
        reasons = {"VALID_ANY_SCORE": 0, "READOUT_BETTER_THAN_V": 0, "VALID_AND_READOUT_BETTER_THAN_V": 0}
        for row in rows:
            if int(row["replacement_changed_coordinate_count"]) == 0:
                continue
            valid = bool(row["final_geometry_pass"])
            better = bool(tuple(row["score_key"]) < tuple(row["historical_valid_score_key"]))
            if not (valid or better):
                continue
            if valid and better:
                reason = "VALID_AND_READOUT_BETTER_THAN_V"
            elif valid:
                reason = "VALID_ANY_SCORE"
            else:
                reason = "READOUT_BETTER_THAN_V"
            item = dict(row)
            item["eligibility_reason"] = reason
            item["application_base"] = "fresh_S"
            item["candidate_library_identity"] = IDENTITY
            eligible.append(item)
            reasons[reason] += 1
        require(len({(int(row["group"]), str(row["to"])) for row in eligible}) == len(eligible), f"duplicate eligible candidate: {key}")
        eligible_shards[slug] = eligible
        context_meta.append({"context": [key[0], key[1]], "input_singletons": len(rows), "eligible_candidates": len(eligible), "rejected_nonidentity": len(rows) - sum(int(row["replacement_changed_coordinate_count"]) == 0 for row in rows) - len(eligible), "identity_replacements_excluded": sum(int(row["replacement_changed_coordinate_count"]) == 0 for row in rows), "eligibility_reasons": reasons, "shard_content_sha256": object_hash(eligible)})
    shard_hashes = {}
    for slug in sorted(eligible_shards):
        path = ROOT / "shards" / f"{slug}.jsonl"
        write_new(path, eligible_shards[slug])
        shard_hashes[slug] = digest(path)
    total = sum(len(rows) for rows in eligible_shards.values())
    execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SREPLACE_CANDIDATES_COMPLETE", "engineering_only": True, "scientific_promotion": False, "pair_replay_executed": False, "historical_lr1_results_used_as_evidence": False, "parent_singletons_execution_sha256": digest(PARENT_EXECUTION), "source_manifest_sha256": source_manifest()["manifest_sha256"], "counts": {"contexts": 8, "input_singletons": 3696, "eligible_candidates": total}, "contexts": context_meta, "shard_hashes": shard_hashes, "eligibility": "nonidentity and (final_geometry_pass or score_key strictly better than fresh V score key)"}
    write_new(ROOT / "execution.json", execution)
    write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "pair_replay_executed": False, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
    print(json.dumps(execution, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
