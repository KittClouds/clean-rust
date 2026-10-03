"""Outcome-blind validation for generated FLY-PHENO-00 preparation inputs."""

from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from prepare_contract import (  # noqa: E402
    ANATOMY,
    BLOCK_SEEDS,
    GRAPHS,
    LESION_SEEDS,
    MANIFESTS,
    MASKS,
    SEVERITIES,
    SIDES,
    SUBSTRATES,
    read_nodes,
    sha256_bytes,
    sha256_file,
)


def read_edges(path: pathlib.Path) -> list[tuple[int, int, int]]:
    with path.open(encoding="utf-8") as handle:
        header = next(handle).rstrip("\n\r")
        assert header == "pre\tpost\tweight"
        return [tuple(map(int, line.rstrip("\n\r").split("\t"))) for line in handle]


def local_layer(data, edge: tuple[int, int, int]) -> tuple[str, int, int, int]:
    pre, post, weight = edge
    pk, qk = data.by_index[pre].kind, data.by_index[post].kind
    layer = {(0, 1): "pn_kc", (1, 2): "kc_mb", (1, 3): "kc_dan", (2, 3): "mb_dan", (3, 2): "route"}.get((pk, qk))
    if layer is None:
        return ("other", pre, post, weight)
    return (layer, data.by_index[pre].local, data.by_index[post].local, weight)


def layer_invariants(data, edges: list[tuple[int, int, int]]) -> dict[str, tuple[dict[int, int], dict[int, int], dict[int, int], set[tuple[int, int]]]]:
    result = {}
    for layer in ("pn_kc", "kc_mb", "kc_dan", "mb_dan", "route"):
        pre_degree: dict[int, int] = {}
        post_degree: dict[int, int] = {}
        source_strength: dict[int, int] = {}
        pairs: set[tuple[int, int]] = set()
        for name, pre, post, weight in map(lambda edge: local_layer(data, edge), edges):
            if name != layer:
                continue
            if (pre, post) in pairs:
                raise AssertionError(f"duplicate {layer} pair")
            pairs.add((pre, post))
            pre_degree[pre] = pre_degree.get(pre, 0) + 1
            post_degree[post] = post_degree.get(post, 0) + 1
            source_strength[pre] = source_strength.get(pre, 0) + weight
        result[layer] = (pre_degree, post_degree, source_strength, pairs)
    return result


def validate_nulls() -> int:
    manifest = json.loads((MANIFESTS / "NULL-GRAPH-MANIFEST.json").read_text(encoding="utf-8"))
    data = {side: read_nodes(side) for side in SIDES}
    count = 0
    for realization in manifest["realizations"]:
        substrate = realization["substrate"]
        for side in SIDES:
            original = read_edges(ANATOMY / f"edges-{side}.tsv")
            path = pathlib.Path(realization["sides"][side]["path"])
            actual = read_edges(path)
            assert len(original) == len(actual)
            assert sha256_file(path) == realization["sides"][side]["sha256"]
            before, after = layer_invariants(data[side], original), layer_invariants(data[side], actual)
            for layer in before:
                assert before[layer][0] == after[layer][0]
                assert before[layer][1] == after[layer][1]
                assert before[layer][2] == after[layer][2]
                target = manifest["accepted_swaps_per_edge"] * len(before[layer][3])
                assert realization["sides"][side]["layer_stats"][layer]["accepted_swaps"] == target
            count += 1
    return count


def read_u32(path: pathlib.Path) -> list[int]:
    payload = path.read_bytes()
    assert len(payload) % 4 == 0
    return [value[0] for value in struct.iter_unpack("<I", payload)]


def validate_lesions() -> int:
    manifest = json.loads((MANIFESTS / "LESION-MANIFEST.json").read_text(encoding="utf-8"))
    count = 0
    for substrate, side_data in manifest["substrates"].items():
        for side, entry in side_data.items():
            edge_count = entry["edge_count"]
            random = entry["families"]["uniform_random"]
            for m in LESION_SEEDS:
                permutation = read_u32(MASKS / substrate / side / f"random-m{m - LESION_SEEDS[0] + 1}.order.u32le")
                assert len(permutation) == edge_count and len(set(permutation)) == edge_count
                for severity in SEVERITIES:
                    n = int(severity * edge_count)
                    assert sha256_bytes(b"".join(struct.pack("<I", x) for x in permutation[:n])) == random[str(m - LESION_SEEDS[0] + 1)]["mask_hashes"][f"{severity:.2f}"]["sha256"]
                    assert random[str(m - LESION_SEEDS[0] + 1)]["mask_hashes"][f"{severity:.2f}"]["edge_count"] == n
                count += 1
            high = read_u32(MASKS / substrate / side / "high-degree.order.u32le")
            assert len(high) == edge_count and len(set(high)) == edge_count
            count += 1
    return count


def validate_banks_and_fit() -> tuple[int, int]:
    training = json.loads((MANIFESTS.parent / "inputs/banks/training.json").read_text(encoding="utf-8"))
    assert set(map(int, training["blocks"])) == set(BLOCK_SEEDS)
    for block in training["blocks"].values():
        assert len(block["labels"]) == 16 and len(block["schedule"]) == 512
        assert all(len(row) == 13 for row in block["schedule"])
    competence = json.loads((MANIFESTS.parent / "inputs/banks/competence.json").read_text(encoding="utf-8"))
    measurement = json.loads((MANIFESTS.parent / "inputs/banks/measurement.json").read_text(encoding="utf-8"))
    assert competence["seed"] != measurement["seed"]
    assert competence["response_draws_u64"] != measurement["response_draws_u64"]
    with (MANIFESTS / "FIT-MANIFEST.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    keys = [(r["substrate"], r["side"], r["learner_task_seed"], r["lesion_family"], r["lesion_m"], r["severity"], r["arm"]) for r in rows]
    assert len(rows) == 11232 and len(keys) == len(set(keys))
    assert sum(row["primary_cell"] == "true" for row in rows) == 1728
    return len(rows), sum(row["primary_cell"] == "true" for row in rows)


def main() -> None:
    null_count = validate_nulls()
    lesion_count = validate_lesions()
    fit_count, primary_count = validate_banks_and_fit()
    print(json.dumps({"status": "PASS", "null_side_realizations": null_count, "lesion_permutations": lesion_count, "fit_rows": fit_count, "primary_rows": primary_count}, sort_keys=True))


if __name__ == "__main__":
    main()
