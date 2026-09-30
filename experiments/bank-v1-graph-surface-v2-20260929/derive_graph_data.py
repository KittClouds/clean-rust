"""Join extracted mention vectors to canonical BANK graphs and build fixed tasks."""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import random
from collections import Counter, defaultdict, deque
from pathlib import Path

from common import (ENTITY_TYPES, INPUT_SPECS, PREDICATES, WORLD_SPLITS,
                    identifier_type, read_jsonl, sha256, token_to_lexical_type, write_json)

TRAIN_CAP = 200_000
TASKS = ("node_type", "edge_existence", "edge_label", "one_hop_membership",
         "two_hop_membership", "link_completion")


class Reservoir:
    """Fixed-seed streaming sample for bounded TRAIN files."""
    def __init__(self, cap: int, seed: int):
        self.cap = cap
        self.rng = random.Random(seed)
        self.seen = 0
        self.rows: list[str] = []

    def add(self, value: dict):
        self.seen += 1
        line = json.dumps(value, sort_keys=True, separators=(",", ":"))
        if len(self.rows) < self.cap:
            self.rows.append(line)
            return
        slot = self.rng.randrange(self.seen)
        if slot < self.cap:
            self.rows[slot] = line


def shortest_distances(nodes, adjacency, source):
    distances = {source: 0}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        for neighbor in adjacency.get(node, ()):
            if neighbor not in distances:
                distances[neighbor] = distances[node] + 1
                queue.append(neighbor)
    return distances


def pair_record(row_meta, a, b, label, lex_by_idx, idtype_by_idx, **extra):
    record = {"row_idx": int(row_meta["row_idx"]), "world_id": row_meta["world_id"],
              "family": row_meta["surface_family"], "a_idx": int(a), "b_idx": int(b),
              "label": int(label), "lex_a": lex_by_idx[a], "lex_b": lex_by_idx[b],
              "id_type_a": idtype_by_idx[a], "id_type_b": idtype_by_idx[b]}
    record.update(extra)
    return record


def create_world_examples(world, row_meta, entities, goals, rng, split):
    examples = defaultdict(list)
    typed_nodes = {}
    lex_by_idx = {}
    idtype_by_idx = {}
    truth_type = {}
    for entity in world.get("entities", []):
        eid = str(entity.get("id"))
        label = str(entity.get("type"))
        truth_type[eid] = label
        item = entities.get(eid)
        if item and item[2]:
            typed_nodes[eid] = item[0]
            lex_by_idx[item[0]] = token_to_lexical_type(item[1])
            idtype_by_idx[item[0]] = identifier_type(eid)
            examples["node_type"].append({
                "row_idx": row_meta["row_idx"], "world_id": row_meta["world_id"],
                "family": row_meta["surface_family"], "feature_kind": "entity",
                "feature_idx": item[0], "label": ENTITY_TYPES.index(label),
                "lex_type": token_to_lexical_type(item[1]), "id_type": identifier_type(eid),
            })
    goal_by_id = {str(g["entity_id"]): g for g in goals}
    for eid, goal in goal_by_id.items():
        label = truth_type.get(eid)
        if label in ENTITY_TYPES and goal["matched"]:
            examples["node_type"].append({
                "row_idx": row_meta["row_idx"], "world_id": row_meta["world_id"],
                "family": row_meta["surface_family"], "feature_kind": "goal",
                "feature_idx": goal["goal_index"], "label": ENTITY_TYPES.index(label),
                "lex_type": token_to_lexical_type(goal["mention"]), "id_type": identifier_type(eid),
            })

    facts = world.get("initial_state") or []
    binary_facts = set()
    typed_facts = set()
    loc_ids = {str(e["id"]) for e in world.get("entities", []) if e.get("type") == "LOCATION"}
    adjacency = defaultdict(set)
    connected_edges = set()
    for fact in facts:
        args = [str(x) for x in (fact.get("args") or [])]
        pred = str(fact.get("pred"))
        if len(args) != 2 or pred not in PREDICATES:
            continue
        subject, obj = args
        if subject not in typed_nodes or obj not in typed_nodes:
            continue
        pair = (typed_nodes[subject], typed_nodes[obj])
        binary_facts.add(pair)
        typed_facts.add((pair[0], pair[1], PREDICATES.index(pred)))
        if pred == "CONNECTED" and subject in loc_ids and obj in loc_ids and subject != obj:
            edge = tuple(sorted((subject, obj)))
            connected_edges.add(edge)
            adjacency[subject].add(obj)
            adjacency[obj].add(subject)

    entities_by_id = {str(e["id"]): e for e in world.get("entities", [])}
    id_by_idx = {index: eid for eid, index in typed_nodes.items()}
    node_indices = sorted(id_by_idx)
    candidates = [(a, b) for a in node_indices for b in node_indices if a != b]
    negative_pairs = [pair for pair in candidates if pair not in binary_facts]
    positive_pairs = sorted(binary_facts)
    rng.shuffle(negative_pairs)
    for a, b in positive_pairs:
        examples["edge_existence"].append(pair_record(row_meta, a, b, 1, lex_by_idx, idtype_by_idx))
    for a, b in negative_pairs[:len(positive_pairs)]:
        examples["edge_existence"].append(pair_record(row_meta, a, b, 0, lex_by_idx, idtype_by_idx))

    positive_typed = sorted(typed_facts)
    for a, b, label in positive_typed:
        examples["edge_label"].append(pair_record(row_meta, a, b, label + 1, lex_by_idx, idtype_by_idx))
    for a, b in negative_pairs[:len(positive_typed)]:
        examples["edge_label"].append(pair_record(row_meta, a, b, 0, lex_by_idx, idtype_by_idx))

    loc_indices = sorted(typed_nodes[eid] for eid in loc_ids if eid in typed_nodes)
    by_loc_id = {typed_nodes[eid]: eid for eid in loc_ids if eid in typed_nodes}
    loc_pairs = [(a, b) for i, a in enumerate(loc_indices) for b in loc_indices[i + 1:]]
    dist_cache = {a: shortest_distances(loc_ids, adjacency, a) for a in loc_ids}
    one_pos, one_neg, two_pos, two_neg = [], [], [], []
    for a, b in loc_pairs:
        left, right = by_loc_id[a], by_loc_id[b]
        distance = dist_cache.get(left, {}).get(right, 10**6)
        if distance == 1:
            one_pos.append((a, b))
        else:
            one_neg.append((a, b))
        if distance == 2:
            two_pos.append((a, b))
        elif distance > 2:
            two_neg.append((a, b))
    rng.shuffle(one_neg)
    rng.shuffle(two_neg)
    for a, b in one_pos:
        examples["one_hop_membership"].append(pair_record(row_meta, a, b, 1, lex_by_idx, idtype_by_idx))
        examples["one_hop_membership"].append(pair_record(row_meta, b, a, 1, lex_by_idx, idtype_by_idx))
    for a, b in one_neg[:len(one_pos)]:
        examples["one_hop_membership"].append(pair_record(row_meta, a, b, 0, lex_by_idx, idtype_by_idx))
        examples["one_hop_membership"].append(pair_record(row_meta, b, a, 0, lex_by_idx, idtype_by_idx))
    for a, b in two_pos:
        examples["two_hop_membership"].append(pair_record(row_meta, a, b, 1, lex_by_idx, idtype_by_idx))
        examples["two_hop_membership"].append(pair_record(row_meta, b, a, 1, lex_by_idx, idtype_by_idx))
    for a, b in two_neg[:len(two_pos)]:
        examples["two_hop_membership"].append(pair_record(row_meta, a, b, 0, lex_by_idx, idtype_by_idx))
        examples["two_hop_membership"].append(pair_record(row_meta, b, a, 0, lex_by_idx, idtype_by_idx))

    true_triples = sorted({(a, b, label) for a, b, label in typed_facts})
    for a, b, label in true_triples:
        subject_id = id_by_idx[a]
        valid_targets = [x for x in node_indices if x != a and
                         (a, x, label) not in typed_facts]
        if split == "TRAIN":
            if not valid_targets:
                continue
            negative = rng.choice(valid_targets)
            for target, y in ((b, 1), (negative, 0)):
                examples["link_completion"].append(pair_record(
                    row_meta, a, target, y, lex_by_idx, idtype_by_idx,
                    predicate=label, query_id=f"{row_meta['world_id']}|{subject_id}|{label}|{row_meta['row_idx']}"))
        else:
            examples["link_completion"].append({
                "row_idx": int(row_meta["row_idx"]), "world_id": row_meta["world_id"],
                "family": row_meta["surface_family"], "a_idx": int(a),
                "target_idx": int(b), "predicate": int(label),
                "candidate_indices": [int(x) for x in node_indices if x != a],
                "candidate_lex_types": [lex_by_idx[x] for x in node_indices if x != a],
                "candidate_id_types": [idtype_by_idx[x] for x in node_indices if x != a],
                "query_id": f"{row_meta['world_id']}|{subject_id}|{label}|{row_meta['row_idx']}",
                "lex_a": lex_by_idx[a], "lex_target": lex_by_idx[b],
                "id_type_a": idtype_by_idx[a], "id_type_target": idtype_by_idx[b],
            })
    return examples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-cap", type=int, default=TRAIN_CAP)
    args = parser.parse_args()
    out_root = args.output
    mentions_path = out_root / "row-mentions.jsonl"
    preflight_path = out_root / "preflight.json"
    if not mentions_path.is_file() or not (out_root / "features" / "extraction-seal.json").is_file():
        raise RuntimeError("local extraction must be sealed before graph truth is joined")
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    extraction = json.loads((out_root / "features" / "extraction-seal.json").read_text(encoding="utf-8"))
    if extraction.get("truth_joined") is not False or extraction.get("row_mentions_sha256") != sha256(mentions_path):
        raise RuntimeError("extraction receipt/hash invalid or truth was already joined")
    row_count = int(preflight["rows"])
    rowmap_path = out_root / "rowmap.jsonl"
    if not rowmap_path.exists():
        # The immutable Rung-0 rowmap is copied by the extraction process.
        raise RuntimeError("extraction rowmap is missing")
    row_meta = [None] * row_count
    rows_by_world = defaultdict(list)
    with rowmap_path.open("r", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            idx = int(r["idx"])
            canonical = str(r.get("paired_world") or r["world_id"])
            row_meta[idx] = {"row_idx": idx, "world_id": canonical,
                             "split": r["split"], "surface_family": r.get("surface_family") or "",
                             "paired_world": r.get("paired_world")}
            rows_by_world[canonical].append(idx)
    if any(r is None for r in row_meta):
        raise RuntimeError("rowmap has missing indexes")
    entities_by_row = [dict() for _ in range(row_count)]
    goals_by_row = [[] for _ in range(row_count)]
    with mentions_path.open("r", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            idx = int(record["row_idx"])
            entities_by_row[idx] = {
                str(m["entity_id"]): (int(m["entity_index"]), str(m.get("mention") or ""), bool(m.get("matched")),
                                      str(m.get("alignment_kind") or ""))
                for m in record["mentions"]
            }
            goals_by_row[idx] = [{"entity_id": str(g["entity_id"]),
                                  "goal_index": int(g["goal_index"]),
                                  "mention": str(g.get("mention") or ""),
                                  "matched": bool(g.get("matched"))}
                                 for g in record["goals"]]

    task_dir = out_root / "task-examples"
    task_dir.mkdir(exist_ok=True)
    reservoirs = {task: Reservoir(args.train_cap, 20260929 + i * 37)
                  for i, task in enumerate(TASKS)}
    destinations = {}
    counts = {task: Counter() for task in TASKS}
    for task in TASKS:
        for split in WORLD_SPLITS:
            (task_dir / task).mkdir(parents=True, exist_ok=True)
            if split == "TRAIN":
                continue
            destinations[(task, split)] = (task_dir / task / f"{split}.jsonl").open(
                "w", encoding="utf-8", newline="\n")
    source_hashes = {}
    skipped_worlds = []
    for split in WORLD_SPLITS:
        path = args.bank_root / "worlds" / f"{split}.jsonl"
        source_hashes[split] = sha256(path)
        world_count = 0
        for world in read_jsonl(path):
            world_count += 1
            if world_count % 10000 == 0:
                print(json.dumps({"phase": "join_progress", "split": split,
                                  "worlds": world_count}), flush=True)
            world_id = str(world["world_id"])
            row_indexes = rows_by_world.get(world_id, [])
            if not row_indexes:
                raise RuntimeError(f"canonical graph world has no rendered input rows: {world_id}")
            # Fit only the canonical row. DEV stays canonical; TEST also emits paired renderers.
            selected_rows = [idx for idx in row_indexes if row_meta[idx]["paired_world"] is None]
            if split.startswith("TEST"):
                selected_rows += [idx for idx in row_indexes if row_meta[idx]["paired_world"] is not None]
            if len(selected_rows) == 0:
                skipped_worlds.append(world_id)
                continue
            for row_idx in selected_rows:
                metadata = row_meta[row_idx]
                entity_map = entities_by_row[row_idx]
                goals = goals_by_row[row_idx]
                rng_seed = int.from_bytes(hashlib.blake2b(
                    f"{20260929}|{world_id}|{metadata['surface_family']}".encode(), digest_size=8
                ).digest(), "little")
                examples = create_world_examples(world, metadata, entity_map, goals,
                                                 random.Random(rng_seed), split)
                for task in TASKS:
                    for record in examples.get(task, []):
                        counts[task][split] += 1
                        counts[task][f"{split}:{metadata['surface_family']}"] += 1
                        if split == "TRAIN":
                            reservoirs[task].add(record)
                        else:
                            destinations[(task, split)].write(
                                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        expected_worlds = int(json.loads((args.bank_root / "manifests" / "release.json").read_text(
            encoding="utf-8"))["stats"][split]["worlds"])
        if world_count != expected_worlds:
            raise RuntimeError(f"{split} worlds {world_count} != manifest {expected_worlds}")
    for task, reservoir in reservoirs.items():
        with (task_dir / task / "TRAIN.jsonl").open("w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(reservoir.rows))
            if reservoir.rows:
                f.write("\n")
        counts[task]["TRAIN_seen"] = reservoir.seen
        counts[task]["TRAIN_saved"] = len(reservoir.rows)
    for f in destinations.values():
        f.close()
    report = {"schema": "phoenix.bank-v1.graph-task-data/v2", "truth_joined": True,
              "extraction_seal_sha256": sha256(out_root / "features" / "extraction-seal.json"),
              "derivation_script_sha256": sha256(Path(__file__)),
              "spec_sha256": sha256(Path(__file__).with_name("spec.json")),
              "row_mentions_sha256": sha256(mentions_path), "rowmap_sha256": sha256(rowmap_path),
              "canonical_world_hashes": source_hashes,
              "span_alignment_by_renderer": preflight.get("family_span_coverage", {}),
              "tasks": {task: dict(counts[task]) for task in TASKS},
              "train_cap_per_task": args.train_cap,
              "train_sampling": "fixed-seed reservoir over canonical TRAIN worlds only",
              "negative_sampling": "fixed-seed, within-world candidate pairs; no qrels or external retrieval labels",
              "skipped_worlds": skipped_worlds,
              "feature_firewall": "no structured IDs or graph labels are supplied as side-channel features; textual symbolic argument IDs present in renderer S9 remain in the input spans and are audited against identifier-type controls; world IDs, corpus IDs, renderer IDs, and graph truth are not model features"}
    write_json(out_root / "graph-task-data-report.json", report)
    print(json.dumps({"phase": "task_data_complete", "tasks": {
        task: {"TRAIN": counts[task]["TRAIN_saved"], "DEV": counts[task]["DEV"],
               "TEST": sum(counts[task][split] for split in WORLD_SPLITS if split.startswith("TEST"))}
        for task in TASKS}, "report": str((out_root / "graph-task-data-report.json").resolve())}), flush=True)


if __name__ == "__main__":
    main()
