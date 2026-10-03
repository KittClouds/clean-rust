"""Replayable supervision/pairs and existing encoder-local cache adapter; no F pass."""
from __future__ import annotations

import argparse
import importlib
import itertools
import json
import sys
import types
from pathlib import Path

import numpy as np
import torch

from .contracts import (BANK_CODE, ENCODER_CACHE, NVME, PARENT_NVME,
                        PARENT_LOCK_SHA256, SUBSTRATES, canon_hash, default_config,
                        sha_file, supervision_abi, write_json)
from .prepare import read_inputs, read_worlds
from .supervision import action_key, base_id, candidates_from_observation


def verify_parent():
    path = PARENT_NVME / "PHASE0-LOCK.json"
    if sha_file(path) != PARENT_LOCK_SHA256:
        raise ValueError("prior frozen lock changed")
    lock = json.loads(path.read_text())
    for relative, digest in lock["package_files"].items():
        if sha_file(Path(lock["package"]) / relative) != digest:
            raise ValueError("prior package changed")
    for record in lock["data"].values():
        if sha_file(Path(record["path"])) != record["sha256"]:
            raise ValueError("prior data manifest changed")
    return lock


def canonical_renderer():
    tag = "phase0_v2_canonical_bank"
    if tag not in sys.modules:
        pkg = types.ModuleType(tag)
        pkg.__path__ = [str(BANK_CODE)]
        sys.modules[tag] = pkg
    return importlib.import_module(tag + ".renderer")


def action_endpoint(world, actions):
    selected = world.get("selected_action")
    if world.get("decision") != "ACT" or selected is None:
        return -1, False
    lookup = {action_key(a): i for i, a in enumerate(actions)}
    idx = lookup.get(action_key(selected), -1)
    return idx, idx >= 0


def renderer_pairs(rows, metadata, actions, offsets, config):
    groups = {}
    for i, row in enumerate(rows):
        if row["surface_family"] in config["meaning_preserving_renderers"]:
            groups.setdefault(base_id(row), []).append(i)
    pairs = []
    for _group, indices in sorted(groups.items()):
        for left, right in itertools.combinations(indices, 2):
            a, b = rows[left], rows[right]
            if a["surface_family"] == b["surface_family"]:
                continue
            if a["world_hash"] != b["world_hash"] or a["goal"] != b["goal"]:
                raise ValueError("paired renderer canonical truth/goal mismatch")
            if [action_key(x) for x in metadata[left]["candidate_actions"]] != [action_key(x) for x in metadata[right]["candidate_actions"]]:
                raise ValueError("paired candidate identities not aligned")
            la = actions[offsets[left]:offsets[left+1]]
            ra = actions[offsets[right]:offsets[right+1]]
            if not np.array_equal(la, ra):
                raise ValueError("paired binding ordinals differ")
            pairs.append((left, right))
    return np.asarray(pairs, np.int64).reshape(-1, 2)


def encoder_local(rows, split, destination, parent_representation):
    path = ENCODER_CACHE / f"{split}.pt"
    receipt = json.loads((ENCODER_CACHE / f"{split}-receipt.json").read_text())
    digest = sha_file(path)
    if digest != receipt["sha256"]:
        raise ValueError("encoder source hash mismatch")
    cache = torch.load(path, weights_only=True, map_location="cpu")
    lookup = {str(wid): i for i, wid in enumerate(cache["row_ids"])}
    index = cache["entity_index"]
    if [i for i, _ids in index] != list(range(len(index))):
        raise ValueError("entity-index row positions disagree")
    source_offsets = np.concatenate(([0], np.cumsum([len(ids) for _i, ids in index])))
    if source_offsets[-1] != len(cache["entity_vectors"]):
        raise ValueError("entity cache shape/index mismatch")
    total = sum(len(r["bindings"]) for r in rows)
    vectors = np.lib.format.open_memmap(destination / "entity_local.npy", mode="w+", dtype=np.float16, shape=(total, 1024))
    available = np.zeros(total, np.bool_)
    offsets = [0]
    for row in rows:
        i = lookup[row["world_id"]]
        source_ids = list(map(str, index[i][1]))
        binding_ids = [str(b["entity_id"]) for b in row["bindings"]]
        if source_ids != binding_ids or len(set(source_ids)) != len(source_ids):
            raise ValueError("entity cache is not aligned to observable bindings")
        ids = sorted(binding_ids)
        permutation = [source_ids.index(eid) for eid in ids]
        source = cache["entity_vectors"][int(source_offsets[i]):int(source_offsets[i+1])].numpy()
        local = source[permutation]
        if not np.isfinite(local).all():
            raise ValueError("nonfinite entity-local feature")
        begin, end = offsets[-1], offsets[-1] + len(ids)
        vectors[begin:end] = local
        available[begin:end] = np.any(local != 0, axis=1)
        offsets.append(end)
    vectors.flush()
    del vectors, cache
    np.save(destination / "entity_available.npy", available, allow_pickle=False)
    np.save(destination / "entity_offsets.npy", np.asarray(offsets, np.int64), allow_pickle=False)
    interface = {"parent_representation_id": parent_representation,
                 "local_surface": "existing final-layer first-mention span mean, max_len=512",
                 "candidate_argument_alignment": "sorted observable binding IDs, one-based ordinal; zero padding",
                 "unresolved_span": "explicit unavailable mask; never semantic absence"}
    return {"representation_id": canon_hash(interface), "interface": interface,
            "source": {"path": str(path), "sha256": digest},
            "entity_vectors": total, "unresolved_vectors": int((~available).sum())}


def construct(split, config):
    verify_parent()
    destination = NVME / "data" / split
    if destination.exists():
        raise FileExistsError("no-clobber construction")
    parent = PARENT_NVME / "data" / split
    manifest = json.loads((parent / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        if sha_file(parent / name) != digest:
            raise ValueError("frozen parent data changed")
    for name, digest in manifest["source_code_hashes"].items():
        if sha_file(BANK_CODE / name) != digest:
            raise ValueError("canonical BANK source changed")
    rows = read_inputs(split, manifest["rows"])
    metadata = [json.loads(line) for line in (parent / "rows.jsonl").read_text().splitlines()]
    if [r["world_id"] for r in rows] != [r["world_id"] for r in metadata]:
        raise ValueError("parent row universe mismatch")
    worlds = read_worlds(split, {base_id(r) for r in rows})
    render = canonical_renderer().render
    endpoint, endpoint_available = [], []
    for row, meta in zip(rows, metadata):
        world = worlds[base_id(row)]
        if row["world_hash"] != canon_hash({k: v for k, v in world.items() if k != "world_id"}):
            raise ValueError("canonical world mismatch")
        replay = render(world, row["surface_family"])
        if replay["text"] != row["input_text"] or replay["bindings"] != row["bindings"]:
            raise ValueError("renderer replay differs from stored observation")
        a = candidates_from_observation(row)
        if a != meta["candidate_actions"]:
            raise ValueError("candidate replay mismatch")
        idx, available = action_endpoint(world, a)
        endpoint.append(idx); endpoint_available.append(available)
    destination.mkdir(parents=True)
    np.save(destination / "action_target.npy", np.asarray(endpoint, np.int64), allow_pickle=False)
    np.save(destination / "action_available.npy", np.asarray(endpoint_available, np.bool_), allow_pickle=False)
    actions = np.load(parent / "actions.npy", mmap_mode="r")
    offsets = np.load(parent / "offsets.npy", mmap_mode="r")
    pairs = renderer_pairs(rows, metadata, actions, offsets, config)
    np.save(destination / "renderer_pairs.npy", pairs, allow_pickle=False)
    np.save(destination / "contrast_pairs.npy", np.zeros((0, 4), np.int64), allow_pickle=False)
    local = encoder_local(rows, split, destination, manifest["representations"]["encoder_base"]["representation_id"])
    identities = {s: manifest["representations"][s]["representation_id"] for s in SUBSTRATES}
    identities["encoder_base"] = local["representation_id"]
    receipt = {"schema": "frozen-fabrique.phase0-shared-loss-data/v2", "split": split,
               "rows": len(rows), "config_sha256": canon_hash(config), "supervision_abi_sha256": canon_hash(supervision_abi()),
               "parent_path": str(parent), "parent_manifest_sha256": sha_file(parent / "manifest.json"),
               "parent_lock_sha256": PARENT_LOCK_SHA256, "representation_ids": identities,
               "encoder_local": local, "renderer_pairs": len(pairs), "renderer_replay_verified": True,
               "renderer_exclusions": ["S5 ambiguous aliases", "S9 drops values/conditions"],
               "action_eligible_rows": int(sum(endpoint_available)), "contrast_support_pairs": 0,
               "contrast_status": "UNAVAILABLE_NO_CANONICAL_CANDIDATE_SUPPORT",
               "files": {p.name: sha_file(p) for p in destination.iterdir() if p.is_file()},
               "protected_truth_contact": False, "backbone_passes": 0}
    write_json(destination / "manifest.json", receipt)
    return receipt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True, choices=("TRAIN", "DEV"))
    args = ap.parse_args()
    print(json.dumps(construct(args.split, default_config()), indent=2))


if __name__ == "__main__":
    main()
