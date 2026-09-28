from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
from collections import Counter, deque
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[4]
EXP = ROOT / "experiments" / "drosophila-heresy"
OUT = Path(__file__).resolve().parents[1]
CONTEXT = ("seed9731-R-tau4.json", 3)
SLUG = "seed9731-R-tau4__set3"
O1 = EXP / "q10-gc1-lr1-requal1-csc1-o1-readmat1-v1"
O2 = EXP / "q10-gc1-lr1-requal1-csc1-pair-front1-v2"
O3 = EXP / "q10-gc1-lr1-requal1-csc1-o3-maskmat1-v1"
R1 = EXP / "q10-gc1-lr1-requal1-csc1-resid1-r1-v1"
FRONT2_SCRIPT = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-front2-v3" / "scripts" / "run_front2.py"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest().upper()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def reference_bits() -> tuple[int, ...]:
    path = O2 / "shards" / f"{SLUG}.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if int(record["frontier_pair_index"]) == 0:
                return tuple(int(value) for value in record["readout_bits"])
    raise RuntimeError("order-2 reference record missing")


def target_bits() -> tuple[int, ...]:
    spec = importlib.util.spec_from_file_location("q10_resid_comp_current_runtime", FRONT2_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("current runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    alg = module.load_alg1()
    context = module.prepare_context(CONTEXT, alg)
    return tuple(int(value) for value in context["state"].target_readout_bits)


def main() -> None:
    allowed = {Path("PLAN.md"), Path("scripts"), Path("scripts/run_resid_comp1.py"), Path("execution.json"), Path("STATUS.json"), Path("REPORT.md"), Path("compatibility.json")}
    if OUT.exists():
        unexpected = {path.relative_to(OUT) for path in OUT.rglob("*")} - allowed
        if unexpected:
            raise RuntimeError(f"unexpected output paths: {sorted(map(str, unexpected))}")
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        (OUT / "scripts").mkdir()

    reference = reference_bits()
    target = target_bits()
    r1 = load_json(R1 / "row-stats.json")
    target_rows = sorted(int(row) for row, value in r1.items() if value["ever_target_exact"])
    if len(target_rows) != 33:
        raise RuntimeError(f"targetable-row cardinality drift: {len(target_rows)}")
    positions = {row: index for index, row in enumerate(target_rows)}
    classes = {row: str(r1[str(row)]["classification"]) for row in target_rows}
    source_paths = [O1 / "records.jsonl", O1 / "execution.json", O2 / "execution.json", O2 / "shards" / f"{SLUG}.jsonl", O3 / "execution.json", O3 / "schema.json", O3 / "semantic.jsonl", O3 / "semantic.bin", R1 / "execution.json", R1 / "row-stats.json", FRONT2_SCRIPT]
    before = {str(path): digest(path) for path in source_paths}
    schema = load_json(O3 / "schema.json")
    residual_indices = [int(row) for row in schema["residual_indices"]]
    residual_positions = {row: index for index, row in enumerate(residual_indices)}
    record_bytes = int(schema["binary_record_bytes"])
    mask_bytes = int(schema["mask_bytes"])
    residual_value_bytes = len(residual_indices) * 4

    co = [[0] * len(target_rows) for _ in target_rows]
    target_set_counts: dict[int, Counter[int]] = {1: Counter(), 2: Counter(), 3: Counter()}
    target_set_examples: dict[int, dict[str, object]] = {}
    order_counts = Counter()

    def consume(order: int, target_set: set[int], identity: object) -> None:
        ordered = sorted(target_set)
        size = len(ordered)
        target_set_counts[order][size] += 1
        order_counts[order] += 1
        if size > int(target_set_examples.get(order, {}).get("size", -1)):
            target_set_examples[order] = {"size": size, "identity": identity, "rows": ordered}
        for left_index, left_row in enumerate(ordered):
            left = positions[left_row]
            for right_row in ordered[left_index + 1 :]:
                right = positions[right_row]
                co[left][right] += 1
                co[right][left] += 1

    with (O1 / "records.jsonl").open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if (str(record["endpoint"]), int(record["set_index"])) != CONTEXT or not bool(record["final_geometry_pass"]):
                continue
            bits = tuple(int(value) for value in record["readout_bits"])
            consume(1, {row for row in target_rows if bits[row] == target[row]}, record["identity"])

    with (O2 / "shards" / f"{SLUG}.jsonl").open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            bits = tuple(int(value) for value in record["readout_bits"])
            consume(2, {row for row in target_rows if bits[row] == target[row]}, record["frontier_pair_index"])

    with (O3 / "semantic.jsonl").open("r", encoding="utf-8") as metadata, (O3 / "semantic.bin").open("rb") as binary:
        for line in metadata:
            record = json.loads(line)
            binary.seek(int(record["binary_offset"]) + 2 * mask_bytes)
            payload = binary.read(residual_value_bytes)
            if len(payload) != residual_value_bytes:
                raise RuntimeError("truncated O3 residual payload")
            values = struct.unpack(f"<{len(residual_indices)}I", payload)
            by_row = dict(zip(residual_indices, values))
            consume(3, {row for row in target_rows if by_row[row] == target[row]}, record["semantic_index"])

    adjacency = {row: set() for row in target_rows}
    edge_count = 0
    class_edge_counts: Counter[str] = Counter()
    for left_index, left_row in enumerate(target_rows):
        for right_row in target_rows[left_index + 1 :]:
            if co[left_index][positions[right_row]] > 0:
                adjacency[left_row].add(right_row)
                adjacency[right_row].add(left_row)
                edge_count += 1
                pair_class = "|".join(sorted((classes[left_row], classes[right_row])))
                class_edge_counts[pair_class] += 1

    unseen = set(target_rows)
    component_sizes = []
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        queue = deque([start])
        component = {start}
        while queue:
            node = queue.popleft()
            for neighbor in adjacency[node]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        component_sizes.append(sorted(component))
    component_sizes.sort(key=lambda value: (-len(value), value))
    after = {str(path): digest(path) for path in source_paths}
    if before != after:
        raise RuntimeError("source changed during RESID-COMP1")

    compatibility = {
        "context": list(CONTEXT),
        "targetable_rows": target_rows,
        "row_classes": classes,
        "edge_count": edge_count,
        "possible_edges": len(target_rows) * (len(target_rows) - 1) // 2,
        "edge_fraction": edge_count / (len(target_rows) * (len(target_rows) - 1) // 2),
        "degrees": {str(row): len(adjacency[row]) for row in target_rows},
        "class_edge_counts": dict(sorted(class_edge_counts.items())),
        "components": component_sizes,
        "target_set_size_counts_by_order": {str(order): dict(sorted(counts.items())) for order, counts in target_set_counts.items()},
        "max_observed_target_set_by_order": target_set_examples,
        "co_attainment_matrix": co,
    }
    execution = {
        "identity": OUT.name,
        "protocol": "Q10-RESID-COMP1",
        "status": "RESID_COMP1_COMPLETE",
        "context": list(CONTEXT),
        "replay_executed": False,
        "scientific_promotion": False,
        "targetable_rows": len(target_rows),
        "possible_edges": compatibility["possible_edges"],
        "observed_edges": edge_count,
        "edge_fraction": compatibility["edge_fraction"],
        "component_count": len(component_sizes),
        "largest_component": max((len(component) for component in component_sizes), default=0),
        "parent_sha256": before,
        "compatibility_sha256": None,
    }
    payload = json.dumps(compatibility, indent=2, sort_keys=True) + "\n"
    (OUT / "compatibility.json").write_text(payload, encoding="utf-8", newline="\n")
    execution["compatibility_sha256"] = digest(OUT / "compatibility.json")
    (OUT / "execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "STATUS.json").write_text(json.dumps({"identity": OUT.name, "status": execution["status"], "replay_executed": False, "scientific_promotion": False}, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    report = "\n".join([
        "# RESID-COMP1 targetable-row compatibility audit",
        "",
        f"Context: `{CONTEXT[0]}`, set `{CONTEXT[1]}`; targetable residual rows: `{len(target_rows)}`.",
        f"Observed co-attainment edges: `{edge_count}/{compatibility['possible_edges']}` ({compatibility['edge_fraction']:.6f}).",
        f"Connected components: `{len(component_sizes)}`; largest component: `{max((len(component) for component in component_sizes), default=0)}`.",
        f"Maximum observed targetable subset by order: `{json.dumps(target_set_examples, sort_keys=True)}`.",
        "",
        "Pairwise compatibility does not establish simultaneous compatibility of all targetable rows.",
        "This is read-only engineering evidence; order 4 and scientific promotion remain closed.",
        "",
    ])
    (OUT / "REPORT.md").write_text(report, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
