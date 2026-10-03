from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
UVD0 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-uvd0-v1"
PROTOCOL = "Q10-CSC1-UPAIR1-DOMAIN"
IDENTITY = ROOT.name
PARTNERS_PER_ACTION = 8

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


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def action_key(action: dict[str, Any]) -> str:
    return f"{int(action['group'])}:{str(action['to'])}"


def pair_key(context: str, row: dict[str, Any]) -> str:
    return f"{context}|{int(row['a']['group'])}:{row['a']['to']}|{int(row['b']['group'])}:{row['b']['to']}"


def rank_key(context: str, row: dict[str, Any]) -> str:
    return digest_bytes(pair_key(context, row).encode("utf-8"))


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(not (ROOT / "CONTRACT.json").exists(), "domain contract already exists")
    require(not (ROOT / "execution.json").exists(), "domain execution already exists")
    plan = ROOT / "PLAN.md"
    runner = Path(__file__)
    uvd0_contract_path = UVD0 / "CONTRACT.json"
    uvd0_execution_path = UVD0 / "execution.json"
    require(uvd0_contract_path.is_file() and uvd0_execution_path.is_file(), "UVD0 parent missing")
    uvd0_contract = json.loads(uvd0_contract_path.read_text(encoding="utf-8"))
    uvd0_execution = json.loads(uvd0_execution_path.read_text(encoding="utf-8"))
    require(uvd0_contract["status"] == "SEALED_PREMEASUREMENT", "UVD0 contract is not sealed")
    require(uvd0_execution["status"] == "UVD0_COMPLETE", "UVD0 execution is incomplete")
    require(int(uvd0_execution["counts"]["structurally_eligible_pairs"]) == 840704, "UVD0 census cardinality drift")

    bindings = []
    for label, path in (
        ("upair1_plan", plan),
        ("upair1_runner", runner),
        ("uvd0_contract", uvd0_contract_path),
        ("uvd0_execution", uvd0_execution_path),
    ):
        bindings.append({"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)})
    for slug in CONTEXTS:
        path = UVD0 / "shards" / f"{slug}.jsonl"
        require(path.is_file(), f"missing UVD0 shard: {slug}")
        bindings.append({"label": f"uvd0_shard:{slug}", "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)})

    contract = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": "SEALED_PREMEASUREMENT",
        "parent_bindings": bindings,
        "parent_protocol": "Q10-CSC1-UVD0",
        "parent_census_pairs": 840704,
        "partner_selection": {
            "partners_per_action": PARTNERS_PER_ACTION,
            "hash": "SHA256(UTF8(context|a_group:a_to|b_group:b_to))",
            "selection": "lowest hash-ranked eligible partners per action, union across actions",
            "retention_order": "original UVD0 shard order",
        },
        "pair_outcomes_consulted": False,
        "pair_replay_performed": False,
        "scientific_promotion": False,
        "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "shards/*.jsonl"],
    }
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": "PREEXECUTION_SEALED",
        "contract_sha256": digest(ROOT / "CONTRACT.json"),
        "pair_outcomes_consulted": False,
        "pair_replay_performed": False,
    })

    shard_meta = []
    total_parent = 0
    total_sample = 0
    coverage_min = None
    coverage_max = None
    for slug in CONTEXTS:
        source = UVD0 / "shards" / f"{slug}.jsonl"
        rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line]
        total_parent += len(rows)
        ranked: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for position, row in enumerate(rows):
            require(str(row["case"]) == slug, f"context drift in UVD0 row {slug} {position}")
            for side in ("a", "b"):
                action = row[side]
                key = action_key(action)
                ranked[key].append((rank_key(slug, row), position))
        selected_positions: set[int] = set()
        for key, entries in sorted(ranked.items()):
            entries.sort(key=lambda item: (item[0], item[1]))
            require(len(entries) >= PARTNERS_PER_ACTION, f"insufficient structural partners for {slug} {key}")
            selected_positions.update(position for _, position in entries[:PARTNERS_PER_ACTION])
        selected = [rows[position] for position in sorted(selected_positions)]
        output_rows = []
        coverage: dict[str, int] = defaultdict(int)
        for sample_index, row in enumerate(selected):
            record = {
                "sample_pair_index": sample_index,
                "source_uvd0_pair_index": int(row["pair_index"]),
                "case": slug,
                "a": row["a"],
                "b": row["b"],
            }
            output_rows.append(record)
            coverage[action_key(row["a"])] += 1
            coverage[action_key(row["b"])] += 1
        require(len(coverage) == len(ranked), f"action coverage cardinality drift in {slug}")
        require(min(coverage.values()) >= PARTNERS_PER_ACTION, f"action coverage below frozen cap in {slug}")
        cmin, cmax = min(coverage.values()), max(coverage.values())
        coverage_min = cmin if coverage_min is None else min(coverage_min, cmin)
        coverage_max = cmax if coverage_max is None else max(coverage_max, cmax)
        output = ROOT / "shards" / f"{slug}.jsonl"
        payload = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in output_rows).encode("utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        require(not output.exists(), f"refusing to overwrite sealed output: {output}")
        output.write_bytes(payload)
        shard_meta.append({
            "context": slug,
            "parent_pairs": len(rows),
            "sample_pairs": len(output_rows),
            "actions": len(ranked),
            "min_action_coverage": cmin,
            "max_action_coverage": cmax,
            "domain_sha256": digest(output),
            "coverage_sha256": digest_bytes(canonical(dict(sorted(coverage.items())))),
        })
        total_sample += len(output_rows)

    ordered_domain = "".join(str(item["domain_sha256"]) for item in shard_meta).encode("ascii")
    execution = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": "UPAIR1_DOMAIN_COMPLETE",
        "engineering_only": True,
        "scientific_promotion": False,
        "pair_outcomes_consulted": False,
        "pair_replay_performed": False,
        "counts": {"contexts": len(shard_meta), "parent_census_pairs": total_parent, "sample_pairs": total_sample, "actions": sum(int(item["actions"]) for item in shard_meta)},
        "coverage": {"partners_per_action_required": PARTNERS_PER_ACTION, "min_observed": coverage_min, "max_observed": coverage_max},
        "contexts": shard_meta,
        "ordered_domain_sha256": digest_bytes(ordered_domain),
        "parent_uvd0_execution_sha256": digest(uvd0_execution_path),
        "parent_uvd0_contract_sha256": digest(uvd0_contract_path),
    }
    write_new(ROOT / "execution.json", execution)
    write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "pair_outcomes_consulted": False, "pair_replay_performed": False, "execution_sha256": digest(ROOT / "execution.json")})
    print(json.dumps(execution, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
