"""Prepare frozen FLY-PHENO-00 inputs and manifests.

This script reads only the shared anatomy TSV inputs and writes prospective
task, evaluation, topology-null, lesion, and fit manifests. It never reads a
DH-08A result artifact and has no measured-run mode.
"""

from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import struct
from dataclasses import dataclass
from typing import Iterable


ROOT = pathlib.Path(__file__).resolve().parents[1]
ANATOMY = ROOT / "inputs" / "anatomy"
GRAPHS = ROOT / "inputs" / "null-graphs"
MASKS = ROOT / "inputs" / "lesion-permutations"
BANKS = ROOT / "inputs" / "banks"
MANIFESTS = ROOT / "manifests"

SIDES = ("L", "R")
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
BLOCK_SEEDS = tuple(range(12000, 12012))
GRAPH_SEEDS = tuple(range(13000, 13008))
LESION_SEEDS = tuple(range(14001, 14005))
QUALIFICATION_SEEDS = tuple(range(910000, 910006))
SEVERITIES = (0.0, 0.01, 0.05, 0.10, 0.20)
RECOVERY_CHECKPOINTS = (0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512)
N_EVAL = 256
PRETRAIN_TRIALS = 512
DELAY_STEPS = 12
CUES = 16
ACCEPTED_SWAPS_PER_EDGE = 4


class SplitMix64:
    def __init__(self, seed: int):
        self.state = seed & ((1 << 64) - 1)

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & ((1 << 64) - 1)
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & ((1 << 64) - 1)
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & ((1 << 64) - 1)
        return (z ^ (z >> 31)) & ((1 << 64) - 1)

    def index(self, n: int) -> int:
        if n <= 0:
            raise ValueError("index bound must be positive")
        threshold = (-n) % n
        while True:
            value = self.next()
            if value >= threshold:
                return value % n

    def shuffle(self, values: list[int]) -> None:
        for i in range(len(values) - 1, 0, -1):
            j = self.index(i + 1)
            values[i], values[j] = values[j], values[i]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_write(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Node:
    body: int
    kind: int
    local: int


@dataclass
class Edge:
    pre: int
    post: int
    weight: int


@dataclass
class SideData:
    nodes: list[Node]
    by_body: dict[int, Node]
    by_index: dict[int, Node]
    edges: list[Edge]
    layers: dict[str, list[int]]
    local_to_body: dict[tuple[int, int], int]


def read_nodes(side: str) -> SideData:
    nodes: list[Node] = []
    by_body: dict[int, Node] = {}
    by_index: dict[int, Node] = {}
    counts = [0] * 5
    with (ANATOMY / f"nodes-{side}.tsv").open(encoding="utf-8") as handle:
        header = next(handle).rstrip("\n\r").split("\t")
        if header != ["body", "kind", "nt"]:
            raise ValueError(f"unexpected node header: {header}")
        for line in handle:
            body_s, kind_s, _nt = line.rstrip("\n\r").split("\t")
            body, kind = int(body_s), int(kind_s)
            if not 0 <= kind < 5:
                raise ValueError("node kind out of range")
            node = Node(body, kind, counts[kind])
            counts[kind] += 1
            nodes.append(node)
            by_body[body] = node
            by_index[len(nodes) - 1] = node
    local_to_body = {(node.kind, node.local): index for index, node in by_index.items()}
    layers = {"pn_kc": [], "kc_mb": [], "kc_dan": [], "mb_dan": [], "route": []}
    with (ANATOMY / f"edges-{side}.tsv").open(encoding="utf-8") as handle:
        header = next(handle).rstrip("\n\r").split("\t")
        if header != ["pre", "post", "weight"]:
            raise ValueError(f"unexpected edge header: {header}")
        edges: list[Edge] = []
        for row_index, line in enumerate(handle):
            pre_s, post_s, weight_s = line.rstrip("\n\r").split("\t")
            pre, post, weight = int(pre_s), int(post_s), int(weight_s)
            if pre not in by_index or post not in by_index or weight <= 0:
                raise ValueError("edge endpoint or weight invalid")
            edge = Edge(pre, post, weight)
            edges.append(edge)
            pair = (by_index[pre].kind, by_index[post].kind)
            layer = {
                (0, 1): "pn_kc",
                (1, 2): "kc_mb",
                (1, 3): "kc_dan",
                (2, 3): "mb_dan",
                (3, 2): "route",
            }.get(pair)
            if layer is not None:
                layers[layer].append(row_index)
    return SideData(nodes, by_body, by_index, edges, layers, local_to_body)


def layer_key(data: SideData, edge: Edge) -> tuple[int, int]:
    return (data.by_index[edge.pre].local, data.by_index[edge.post].local)


def rewired_side(data: SideData, seed: int) -> tuple[list[Edge], dict[str, dict[str, int]]]:
    edges = [Edge(edge.pre, edge.post, edge.weight) for edge in data.edges]
    stats: dict[str, dict[str, int]] = {}
    for layer_index, layer_name in enumerate(("pn_kc", "kc_mb", "kc_dan", "mb_dan", "route")):
        indices = data.layers[layer_name]
        rng = SplitMix64(seed ^ (0x887733 + layer_index * 0x10001))
        original_pairs = {layer_key(data, edges[i]) for i in indices}
        current_pairs = set(original_pairs)
        target = ACCEPTED_SWAPS_PER_EDGE * len(indices)
        accepted = 0
        attempts = 0
        max_attempts = max(target * 100, 100)
        while accepted < target and attempts < max_attempts:
            attempts += 1
            if len(indices) < 2:
                break
            ia = indices[rng.index(len(indices))]
            ib = indices[rng.index(len(indices))]
            if ia == ib:
                continue
            a, b = edges[ia], edges[ib]
            a_local = layer_key(data, a)
            b_local = layer_key(data, b)
            if a_local[0] == b_local[0] or a_local[1] == b_local[1]:
                continue
            candidate_a = (a_local[0], b_local[1])
            candidate_b = (b_local[0], a_local[1])
            current_pairs.remove(a_local)
            current_pairs.remove(b_local)
            valid = candidate_a not in current_pairs and candidate_b not in current_pairs and candidate_a != candidate_b
            if valid:
                current_pairs.add(candidate_a)
                current_pairs.add(candidate_b)
                a_post = data.local_to_body[(data.by_index[a.post].kind, b_local[1])]
                b_post = data.local_to_body[(data.by_index[b.post].kind, a_local[1])]
                edges[ia].post = a_post
                edges[ib].post = b_post
                accepted += 1
            else:
                current_pairs.add(a_local)
                current_pairs.add(b_local)
        if accepted != target:
            raise RuntimeError(f"{layer_name}: accepted {accepted}, target {target}")
        overlap = len(original_pairs & current_pairs)
        stats[layer_name] = {
            "edge_rows": len(indices),
            "accepted_swaps": accepted,
            "attempts": attempts,
            "target_accepted_swaps": target,
            "original_pair_overlap": overlap,
        }
    return edges, stats


def write_edges(path: pathlib.Path, edges: Iterable[Edge]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("pre\tpost\tweight\n")
        for edge in edges:
            handle.write(f"{edge.pre}\t{edge.post}\t{edge.weight}\n")
    return sha256_file(path)


def prepare_null_graphs(side_data: dict[str, SideData]) -> dict[str, object]:
    graph_manifest: dict[str, object] = {
        "schema": "FLY-PHENO-00-null-graph-manifest-v1",
        "substrates": [f"g{i:03d}" for i in range(1, 9)],
        "graph_seeds": list(GRAPH_SEEDS),
        "algorithm": "directed-double-edge-swap",
        "accepted_swaps_per_edge": ACCEPTED_SWAPS_PER_EDGE,
        "reject": ["duplicate-edge", "same-pre", "same-post", "illegal-layer"],
        "weight_rule": "edge weight remains attached to its original source row",
        "original_edge_overlap_is_reported_not_filtered": True,
        "nodes": {
            side: {
                "path": f"inputs/anatomy/nodes-{side}.tsv",
                "sha256": sha256_file(ANATOMY / f"nodes-{side}.tsv"),
            }
            for side in SIDES
        },
        "realizations": [],
    }
    for graph_index, graph_seed in enumerate(GRAPH_SEEDS, start=1):
        substrate = f"g{graph_index:03d}"
        realization: dict[str, object] = {"substrate": substrate, "seed": graph_seed, "sides": {}}
        for side in SIDES:
            rewired, stats = rewired_side(side_data[side], graph_seed ^ (0xABCD + ord(side)))
            path = GRAPHS / substrate / f"edges-{side}.tsv"
            digest = write_edges(path, rewired)
            realization["sides"][side] = {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": digest,
                "layer_stats": stats,
            }
        graph_manifest["realizations"].append(realization)
    json_write(MANIFESTS / "NULL-GRAPH-MANIFEST.json", graph_manifest)
    return graph_manifest


def canonical_kc_mb(data: SideData, edges: Iterable[Edge]) -> list[tuple[int, int, int]]:
    values = []
    for edge in edges:
        pre = data.by_index[edge.pre]
        post = data.by_index[edge.post]
        if (pre.kind, post.kind) == (1, 2):
            values.append((pre.local, post.local, edge.weight))
    values.sort(key=lambda value: (value[1], value[0], value[2]))
    if len({(pre, post) for pre, post, _weight in values}) != len(values):
        raise ValueError("KC->MB edge universe contains duplicate pairs")
    return values


def substrate_edges(side_data: dict[str, SideData], substrate: str, side: str) -> list[tuple[int, int, int]]:
    if substrate == "fly":
        return canonical_kc_mb(side_data[side], side_data[side].edges)
    path = GRAPHS / substrate / f"edges-{side}.tsv"
    edges: list[Edge] = []
    with path.open(encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            pre_s, post_s, weight_s = line.rstrip("\n\r").split("\t")
            edges.append(Edge(int(pre_s), int(post_s), int(weight_s)))
    return canonical_kc_mb(side_data[side], edges)


def pack_u32(values: Iterable[int]) -> bytes:
    values = list(values)
    return b"".join(struct.pack("<I", value) for value in values)


def prepare_lesions(side_data: dict[str, SideData]) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema": "FLY-PHENO-00-lesion-manifest-v1",
        "target": "unique trainable KC->MB edge indices",
        "severity_ladder": list(SEVERITIES),
        "random_permutations": list(LESION_SEEDS),
        "mask_semantics": "stored weights retained; effective weight is mask times stored weight",
        "nested": True,
        "substrates": {},
    }
    for substrate in SUBSTRATES:
        substrate_entry: dict[str, object] = {}
        for side in SIDES:
            edges = substrate_edges(side_data, substrate, side)
            edge_count = len(edges)
            pre_degree: dict[int, int] = {}
            for pre, _post, _weight in edges:
                pre_degree[pre] = pre_degree.get(pre, 0) + 1
            high_order = sorted(
                range(edge_count),
                key=lambda index: (-pre_degree[edges[index][0]], edges[index][0], edges[index][1], index),
            )
            side_entry: dict[str, object] = {"edge_count": edge_count, "families": {}}
            high_path = MASKS / substrate / side / "high-degree.order.u32le"
            high_path.parent.mkdir(parents=True, exist_ok=True)
            high_path.write_bytes(pack_u32(high_order))
            families = side_entry["families"]
            families["high_degree_targeted"] = {
                "m": 0,
                "permutation_path": str(high_path.relative_to(ROOT)).replace("\\", "/"),
                "permutation_sha256": sha256_file(high_path),
                "mask_hashes": {},
            }
            for severity in SEVERITIES:
                count = int(severity * edge_count)
                prefix = pack_u32(high_order[:count])
                families["high_degree_targeted"]["mask_hashes"][f"{severity:.2f}"] = {
                    "edge_count": count,
                    "sha256": sha256_bytes(prefix),
                }
            random_entries = {}
            for m, lesion_seed in enumerate(LESION_SEEDS, start=1):
                order = list(range(edge_count))
                stable = int.from_bytes(hashlib.sha256(f"{substrate}:{side}".encode()).digest()[:8], "little")
                rng = SplitMix64(lesion_seed ^ stable)
                rng.shuffle(order)
                path = MASKS / substrate / side / f"random-m{m}.order.u32le"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(pack_u32(order))
                entry = {
                    "m": m,
                    "seed": lesion_seed,
                    "permutation_path": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "permutation_sha256": sha256_file(path),
                    "mask_hashes": {},
                }
                for severity in SEVERITIES:
                    count = int(severity * edge_count)
                    entry["mask_hashes"][f"{severity:.2f}"] = {
                        "edge_count": count,
                        "sha256": sha256_bytes(pack_u32(order[:count])),
                    }
                random_entries[str(m)] = entry
            families["uniform_random"] = random_entries
            families["sham"] = {
                "m": 0,
                "mask_hashes": {"0.00": {"edge_count": 0, "sha256": sha256_bytes(b"")}},
            }
            substrate_entry[side] = side_entry
        manifest["substrates"][substrate] = substrate_entry
    json_write(MANIFESTS / "LESION-MANIFEST.json", manifest)
    return manifest


def make_schedule(seed: int) -> tuple[list[bool], list[list[int]]]:
    rng = SplitMix64(seed)
    labels = [index % 2 == 0 for index in range(CUES)]
    order = list(range(CUES))
    rng.shuffle(order)
    labels = [labels[index] for index in order]
    schedule: list[list[int]] = []
    for _ in range(PRETRAIN_TRIALS):
        row = [rng.index(CUES)]
        row.extend(CUES + rng.index(32) for _ in range(DELAY_STEPS))
        schedule.append(row)
    return labels, schedule


def make_response_draws(seed: int) -> list[list[int]]:
    rng = SplitMix64(seed)
    return [[rng.next() for _ in range(CUES)] for _ in range(N_EVAL)]


def prepare_banks() -> dict[str, object]:
    BANKS.mkdir(parents=True, exist_ok=True)
    training: dict[str, object] = {
        "schema": "FLY-PHENO-00-training-bank-v1",
        "training_never_reads_evaluation_banks": True,
        "pretraining_trials": PRETRAIN_TRIALS,
        "delay_steps": DELAY_STEPS,
        "cues": CUES,
        "blocks": {},
    }
    for seed in BLOCK_SEEDS:
        labels, schedule = make_schedule(seed ^ 0x545241494E)
        training["blocks"][str(seed)] = {
            "task_seed": seed,
            "labels": labels,
            "schedule": schedule,
        }
    json_write(BANKS / "training.json", training)
    competence = {
        "schema": "FLY-PHENO-00-evaluation-bank-v1",
        "bank": "competence",
        "seed_namespace": "competence-response",
        "seed": 16000,
        "n_eval": N_EVAL,
        "draw_shape": [N_EVAL, CUES],
        "training_never_reads": True,
        "response_draws_u64": make_response_draws(16000),
    }
    measurement = {
        "schema": "FLY-PHENO-00-evaluation-bank-v1",
        "bank": "measurement",
        "seed_namespace": "measurement-response",
        "seed": 17000,
        "n_eval": N_EVAL,
        "draw_shape": [N_EVAL, CUES],
        "training_never_reads": True,
        "response_draws_u64": make_response_draws(17000),
    }
    json_write(BANKS / "competence.json", competence)
    json_write(BANKS / "measurement.json", measurement)
    return {
        "training": {"path": "inputs/banks/training.json", "sha256": sha256_file(BANKS / "training.json")},
        "competence": {"path": "inputs/banks/competence.json", "sha256": sha256_file(BANKS / "competence.json")},
        "measurement": {"path": "inputs/banks/measurement.json", "sha256": sha256_file(BANKS / "measurement.json")},
        "n_eval": N_EVAL,
    }


def prepare_fit_manifest() -> dict[str, object]:
    path = MANIFESTS / "FIT-MANIFEST.csv"
    fields = [
        "fit_id", "substrate", "graph_seed", "side", "learner_task_seed", "lesion_family",
        "lesion_m", "severity", "arm", "checkpoint_key", "task_bank", "competence_bank",
        "measurement_bank", "primary_cell",
    ]
    rows = []
    fit_id = 0
    for substrate in SUBSTRATES:
        graph_seed = 0 if substrate == "fly" else GRAPH_SEEDS[int(substrate[1:]) - 1]
        for side in SIDES:
            for learner_seed in BLOCK_SEEDS:
                checkpoint_key = f"{substrate}:{side}:{learner_seed}"
                conditions: list[tuple[str, int, float]] = []
                for m in range(1, 5):
                    for severity in SEVERITIES:
                        conditions.append(("uniform_random", m, severity))
                for severity in SEVERITIES:
                    conditions.append(("high_degree_targeted", 0, severity))
                conditions.append(("sham", 0, 0.0))
                for lesion_family, lesion_m, severity in conditions:
                    for arm in ("adaptive", "weight_frozen"):
                        primary = lesion_family == "uniform_random" and abs(severity - 0.10) < 1e-12
                        rows.append({
                            "fit_id": fit_id,
                            "substrate": substrate,
                            "graph_seed": graph_seed,
                            "side": side,
                            "learner_task_seed": learner_seed,
                            "lesion_family": lesion_family,
                            "lesion_m": lesion_m,
                            "severity": f"{severity:.2f}",
                            "arm": arm,
                            "checkpoint_key": checkpoint_key,
                            "task_bank": "inputs/banks/training.json",
                            "competence_bank": "inputs/banks/competence.json",
                            "measurement_bank": "inputs/banks/measurement.json",
                            "primary_cell": str(primary).lower(),
                        })
                        fit_id += 1
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    primary_rows = sum(row["primary_cell"] == "true" for row in rows)
    return {
        "path": "manifests/FIT-MANIFEST.csv",
        "sha256": sha256_file(path),
        "rows": len(rows),
        "primary_rows": primary_rows,
        "substrates": len(SUBSTRATES),
        "sides": len(SIDES),
        "learner_task_blocks": len(BLOCK_SEEDS),
        "random_lesion_permutations": len(LESION_SEEDS),
        "null_graph_realizations": len(GRAPH_SEEDS),
    }


def prepare_contract(side_data: dict[str, SideData], banks: dict[str, object], fit: dict[str, object]) -> dict[str, object]:
    anatomy = {
        side: {
            name: {"path": f"inputs/anatomy/{name}-{side}.tsv", "sha256": sha256_file(ANATOMY / f"{name}-{side}.tsv")}
            for name in ("nodes", "edges")
        }
        for side in SIDES
    }
    contract = {
        "schema": "FLY-PHENO-00-analysis-contract-v1",
        "study_id": "FLY-PHENO-00",
        "status": "PREEXECUTION_CONTRACT",
        "measured_execution_authorized": False,
        "source_lineage": {
            "source_root": "source/dh08a",
            "protected_receipt": "provenance/PROTECTED-DH08A-TREE-RECEIPT.json",
            "outcome_artifacts_copied": False,
        },
        "anatomy": anatomy,
        "seed_namespaces": {
            "learner_task": list(BLOCK_SEEDS),
            "null_graph": list(GRAPH_SEEDS),
            "random_lesion": list(LESION_SEEDS),
            "qualification": list(QUALIFICATION_SEEDS),
            "competence_response": [16000],
            "measurement_response": [17000],
        },
        "qualification": {
            "seeds": list(QUALIFICATION_SEEDS),
            "cannot_enter_measured_namespace": True,
            "may_record": ["contract booleans", "finite status", "mask/update invariants", "competence attainment"],
            "may_not_record": ["adaptive-vs-frozen lesion recovery differences"],
        },
        "pretraining": {
            "fixed_trials": PRETRAIN_TRIALS,
            "competence_bank": "inputs/banks/competence.json",
            "criterion": {"heldout_error_fraction_lte": 0.25, "evaluation_count": N_EVAL},
            "failure": "CRITERION_FAILURE; no replacement",
            "support": {"minimum_global_complete_blocks": 8, "global_intersection": True},
        },
        "evaluation": {
            "measurement_bank": "inputs/banks/measurement.json",
            "n_eval": N_EVAL,
            "epsilon_D": f"max(4/{N_EVAL},0.01)",
            "epsilon_D_value": max(4 / N_EVAL, 0.01),
            "read_only": True,
            "common_draws_within_pair": True,
        },
        "lesion": {
            "target": "unique KC->MB edge indices",
            "stored_weight_values_preserved": True,
            "effective_weight": "mask * stored_weight",
            "masked_update": 0.0,
            "severity_ladder": list(SEVERITIES),
            "nested_random_prefixes": True,
        },
        "primary": {
            "condition": {"lesion_family": "uniform_random", "severity": 0.10},
            "B": "L_weight_frozen,p(512)-L_adaptive,p(512)",
            "C": "B_p-B_0",
            "contrast": "mean_s,m C_0.10(fly) - mean_g,s,m C_0.10(shuffle_g)",
            "bootstrap": {"replicates": 20000, "resample_units": ["s", "m", "g"], "two_sided": True},
            "fly_resampled": False,
        },
        "cardinality": fit,
        "banks": banks,
        "null_graph": {
            "accepted_swaps_per_edge": ACCEPTED_SWAPS_PER_EDGE,
            "duplicate_rejection": True,
            "illegal_edge_rejection": True,
            "outcome_dependent_convergence": False,
        },
        "recovery_checkpoints": list(RECOVERY_CHECKPOINTS),
        "explicit_stop": "seal pre-execution package; do not collect recovery outcomes",
    }
    json_write(MANIFESTS / "ANALYSIS-CONTRACT.json", contract)
    return contract


def main() -> None:
    side_data = {side: read_nodes(side) for side in SIDES}
    nulls = prepare_null_graphs(side_data)
    lesions = prepare_lesions(side_data)
    banks = prepare_banks()
    fit = prepare_fit_manifest()
    contract = prepare_contract(side_data, banks, fit)
    summary = {
        "null_graphs": len(nulls["realizations"]),
        "lesion_substrates": len(lesions["substrates"]),
        "fit_rows": fit["rows"],
        "primary_rows": fit["primary_rows"],
        "banks": banks,
        "contract_sha256": sha256_file(MANIFESTS / "ANALYSIS-CONTRACT.json"),
    }
    json_write(MANIFESTS / "PREPARATION-SUMMARY.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
