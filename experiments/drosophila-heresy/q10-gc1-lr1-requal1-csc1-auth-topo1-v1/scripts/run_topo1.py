from __future__ import annotations

import hashlib
import json
from collections import Counter, deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PROTOCOL = "Q10-AUTH-TOPO1"
IDENTITY = ROOT.name
EXH1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-exh1-v1"
ALG3 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-v1"
ALG3_DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-domain-v1"
ALG1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
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
    index = {name: i for i, name in enumerate(actions)}
    adjacency: dict[str, set[str]] = {name: set() for name in actions}
    frontier = [json.loads(line) for line in (EXH1 / "valid-frontier" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    for row in frontier:
        left, right = action_key(row["a"]), action_key(row["b"])
        require(left in index and right in index and left != right, f"invalid frontier edge: {key} {left} {right}")
        adjacency[left].add(right)
        adjacency[right].add(left)
    degrees = sorted(len(neighbors) for neighbors in adjacency.values())
    visited: set[str] = set()
    components: list[int] = []
    for name in actions:
        if name in visited:
            continue
        queue = deque([name])
        visited.add(name)
        size = 0
        while queue:
            current = queue.popleft()
            size += 1
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        components.append(size)
    triangles = 0
    for i, left in enumerate(actions):
        for right in actions[i + 1 :]:
            if right not in adjacency[left]:
                continue
            triangles += sum(neighbor in adjacency[right] for neighbor in adjacency[left] if index[neighbor] > index[right])
    domain = [json.loads(line) for line in (ALG3_DOMAIN / "shards" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    results = {int(json.loads(line)["triple_index"]): json.loads(line) for line in (ALG3 / "results" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line}
    triple_morphology = Counter()
    sampled_valid = 0
    for triple in domain:
        result = results[int(triple["triple_index"])]
        if not bool(result["exact_final_geometry_pass"]):
            continue
        sampled_valid += 1
        names = (str(triple["a"]), str(triple["b"]), str(triple["c"]))
        pair_valid = tuple(sorted((names[0] in adjacency and names[1] in adjacency[names[0]], names[0] in adjacency and names[2] in adjacency[names[0]], names[1] in adjacency and names[2] in adjacency[names[1]])))
        triple_morphology["pairwise_valid_triangle" if all(pair_valid) else "higher_order_rescue"] += 1
        triple_morphology["missing_pair_edges"] += 3 - sum(pair_valid)
    return {"context": [key[0], key[1]], "vertices": len(actions), "valid_edges": len(frontier), "degree_min": min(degrees, default=0), "degree_max": max(degrees, default=0), "degree_mean": sum(degrees) / max(len(degrees), 1), "isolated_vertices": sum(value == 0 for value in degrees), "components": len(components), "largest_component": max(components, default=0), "valid_graph_triangles": triangles, "sampled_triples": len(domain), "sampled_valid_triples": sampled_valid, "sampled_valid_triple_morphology": dict(triple_morphology)}


def main() -> int:
    require(not (ROOT / "execution.json").exists(), "TOPO1 execution already exists")
    inputs = [("topo1_plan", ROOT / "PLAN.md"), ("topo1_runner", Path(__file__)), ("exh1_execution", EXH1 / "execution.json"), ("exh1_contract", EXH1 / "CONTRACT.json"), ("alg3_execution", ALG3 / "execution.json"), ("alg3_domain_execution", ALG3_DOMAIN / "execution.json")]
    for key in CONTEXTS:
        inputs.extend([(f"alg1_descriptor:{slug(key)}", ALG1 / "descriptors" / f"{slug(key)}.json"), (f"exh1_frontier:{slug(key)}", EXH1 / "valid-frontier" / f"{slug(key)}.jsonl"), (f"alg3_domain:{slug(key)}", ALG3_DOMAIN / "shards" / f"{slug(key)}.jsonl"), (f"alg3_result:{slug(key)}", ALG3 / "results" / f"{slug(key)}.jsonl")])
    bindings = [{"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)} for label, path in inputs]
    write_new(ROOT / "CONTRACT.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "readout_executed": False, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json"]})
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json")})
    try:
        results = [run_context(key) for key in CONTEXTS]
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "AUTH_TOPO1_COMPLETE", "engineering_only": True, "scientific_promotion": False, "readout_executed": False, "counts": {"contexts": len(CONTEXTS), "valid_edges": sum(item["valid_edges"] for item in results), "graph_triangles": sum(item["valid_graph_triangles"] for item in results), "sampled_valid_triples": sum(item["sampled_valid_triples"] for item in results), "higher_order_rescue_sample": sum(item["sampled_valid_triple_morphology"].get("higher_order_rescue", 0) for item in results)}, "contexts": results, "contract_sha256": digest(ROOT / "CONTRACT.json"), "conclusion": "Exact order-2 validity topology and sampled order-3 pairwise-validity morphology were computed read-only."}
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_AUTH_TOPO1", "engineering_only": True, "scientific_promotion": False, "error_type": type(exc).__name__, "error": str(exc)}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
