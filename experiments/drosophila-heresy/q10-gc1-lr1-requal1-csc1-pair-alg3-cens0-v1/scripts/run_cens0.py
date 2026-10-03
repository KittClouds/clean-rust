from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PROTOCOL = "Q10-ALG3-CENS0"
IDENTITY = ROOT.name
ALG1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
UVD0 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-uvd0-v1"
CONTEXTS = (("seed9731-L-tau16.json", 2), ("seed9731-L-tau4.json", 3), ("seed9731-R-tau16.json", 1), ("seed9731-R-tau16.json", 3), ("seed9731-R-tau4.json", 0), ("seed9731-R-tau4.json", 1), ("seed9731-R-tau4.json", 2), ("seed9731-R-tau4.json", 3))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def action_key(item: dict[str, Any]) -> str:
    return f"{int(item['group'])}:{str(item['to'])}"


def run_context(key: tuple[str, int]) -> dict[str, Any]:
    descriptor = json.loads((ALG1 / "descriptors" / f"{slug(key)}.json").read_text(encoding="utf-8"))
    actions = tuple(sorted(str(item["action_key"]) for item in descriptor["actions"]))
    require(len(actions) == len(set(actions)), f"duplicate actions: {key}")
    index = {name: position for position, name in enumerate(actions)}
    adjacency = [0] * len(actions)
    pair_rows = [json.loads(line) for line in (UVD0 / "shards" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    seen_pairs: set[tuple[int, int]] = set()
    for row in pair_rows:
        left, right = action_key(row["a"]), action_key(row["b"])
        require(left in index and right in index and left != right, f"invalid UVD0 edge: {key} {left} {right}")
        i, j = sorted((index[left], index[right]))
        require((i, j) not in seen_pairs, f"duplicate UVD0 edge: {key} {left} {right}")
        seen_pairs.add((i, j))
        adjacency[i] |= 1 << j
        adjacency[j] |= 1 << i
    triple_count = 0
    for i in range(len(actions)):
        higher_than_i = adjacency[i] >> (i + 1)
        while higher_than_i:
            lowest = higher_than_i & -higher_than_i
            offset = lowest.bit_length() - 1
            j = i + 1 + offset
            common_higher = adjacency[i] & adjacency[j]
            common_higher &= ~((1 << (j + 1)) - 1)
            triple_count += common_higher.bit_count()
            higher_than_i ^= lowest
    degrees = [value.bit_count() for value in adjacency]
    return {"context": [key[0], key[1]], "actions": len(actions), "structural_pairs": len(pair_rows), "unique_edges": len(seen_pairs), "structural_triples": triple_count, "min_degree": min(degrees, default=0), "max_degree": max(degrees, default=0), "mean_degree": sum(degrees) / max(len(degrees), 1), "isolated_actions": sum(value == 0 for value in degrees)}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(not (ROOT / "execution.json").exists(), "CENS0 execution already exists")
    inputs = [("cens0_plan", ROOT / "PLAN.md"), ("cens0_runner", Path(__file__)), ("alg1_execution", ALG1 / "execution.json"), ("uvd0_execution", UVD0 / "execution.json"), ("uvd0_contract", UVD0 / "CONTRACT.json")]
    for key in CONTEXTS:
        inputs.extend([(f"alg1_descriptor:{slug(key)}", ALG1 / "descriptors" / f"{slug(key)}.json"), (f"uvd0_shard:{slug(key)}", UVD0 / "shards" / f"{slug(key)}.jsonl")])
    bindings = [{"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)} for label, path in inputs]
    write_new(ROOT / "CONTRACT.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "outcomes_consulted": False, "geometry_executed": False, "readout_executed": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json"]})
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json")})
    try:
        results = [run_context(key) for key in CONTEXTS]
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "ALG3_CENS0_COMPLETE", "engineering_only": True, "scientific_promotion": False, "outcomes_consulted": False, "geometry_executed": False, "readout_executed": False, "counts": {"contexts": len(CONTEXTS), "actions": sum(item["actions"] for item in results), "structural_pairs": sum(item["structural_pairs"] for item in results), "structural_triples": sum(item["structural_triples"] for item in results)}, "contexts": results, "contract_sha256": digest(ROOT / "CONTRACT.json"), "conclusion": "Complete order-3 structural domain counted from the canonical UVD0 compatibility graph."}
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_ALG3_CENS0", "engineering_only": True, "scientific_promotion": False, "error_type": type(exc).__name__, "error": str(exc)}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
