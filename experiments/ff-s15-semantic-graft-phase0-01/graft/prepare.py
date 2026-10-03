from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from .contracts import (BANK, BANK_CODE, CACHE_ROOT, ENCODER_CACHE, NVME,
                        SUBSTRATES, canon_hash, default_config, sha_file,
                        supervision_abi, write_json)
from .supervision import (base_id, candidate_encoding, candidates_from_observation,
                          labels_from_world, observable_row)


def read_inputs(split: str, limit: int) -> list[dict]:
    if split not in ("TRAIN", "DEV"):
        raise ValueError("Phase 0 construction opens only TRAIN/DEV; TEST truth stays closed")
    rows = []
    with (BANK / "inputs" / f"{split}.jsonl").open(encoding="utf-8") as src:
        for line in src:
            if line.strip():
                rows.append(observable_row(json.loads(line)))
            if len(rows) >= limit:
                break
    if len(rows) != limit or len({r["world_id"] for r in rows}) != limit:
        raise ValueError("input count/unique row identity mismatch")
    return rows


def read_worlds(split: str, wanted: set[str]) -> dict[str, dict]:
    if split not in ("TRAIN", "DEV"):
        raise ValueError("Phase0 TEST truth access is prohibited")
    found = {}
    with (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8") as src:
        for line in src:
            world = json.loads(line)
            if world["world_id"] in wanted:
                found[world["world_id"]] = world
            if len(found) == len(wanted):
                break
    if set(found) != wanted:
        raise ValueError(f"missing canonical worlds: {len(wanted - set(found))}")
    return found


def causal_dir(substrate: str) -> Path:
    if substrate == "causal_base":
        return CACHE_ROOT / "bank-v1-surface-extremes" / "features"
    name = {"ner_lora_step500": "ner-step500-atlas", "nli_lora_step500": "nli-step500-atlas"}[substrate]
    return CACHE_ROOT / "survival" / "features" / name / "features"


def prepare_features(rows: list[dict], split: str, destination: Path, config: dict) -> dict:
    rowmap = {}
    rowmap_path = CACHE_ROOT / "bank-v1-surface-extremes" / "rowmap.jsonl"
    with rowmap_path.open(encoding="utf-8") as src:
        for line in src:
            r = json.loads(line)
            rowmap[str(r["row_id"])] = int(r["idx"])
    order = np.asarray([rowmap[r["world_id"]] for r in rows], dtype=np.int64)
    receipts = {}
    for substrate in SUBSTRATES:
        output = destination / f"H_{substrate}.npy"
        if substrate != "encoder_base":
            folder = causal_dir(substrate)
            seal = json.loads((folder / "extraction-seal.json").read_text())
            if seal.get("truth_joined") is not False:
                raise ValueError("cache was extracted with truth joined")
            if sha_file(rowmap_path) != seal["rowmap_sha256"]:
                raise ValueError("rowmap is not the cache's frozen identity")
            sources = {}
            arrays = []
            for primitive in ("final_token", "full_mean"):
                path = folder / f"{primitive}.npy"
                actual = sha_file(path)
                if actual != seal["primitives"][primitive]["sha256"]:
                    raise ValueError(f"source cache hash mismatch: {path}")
                arrays.append(np.load(path, mmap_mode="r", allow_pickle=False))
                sources[primitive] = {"path": str(path), "sha256": actual}
            merged = np.lib.format.open_memmap(output, mode="w+", dtype=np.float32,
                                               shape=(len(rows), config["input_dim"]))
            for start in range(0, len(rows), 256):
                end = min(start + 256, len(rows))
                ii = order[start:end]
                merged[start:end, :1024] = arrays[0][ii]
                merged[start:end, 1024:] = arrays[1][ii]
            merged.flush()
            del merged, arrays
            identity = {"model": seal["model"], "extraction_contract_sha256": seal["extraction_contract_sha256"],
                        "surface": "final_plus_mean", "sources": sources}
        else:
            path = ENCODER_CACHE / f"{split}.pt"
            receipt = json.loads((ENCODER_CACHE / f"{split}-receipt.json").read_text())
            actual = sha_file(path)
            if actual != receipt["sha256"]:
                raise ValueError("encoder cache hash mismatch")
            cache = torch.load(path, weights_only=True, map_location="cpu")
            ids = list(map(str, cache["row_ids"]))
            if len(set(ids)) != len(ids):
                raise ValueError("duplicate encoder row identity")
            lookup = {wid: i for i, wid in enumerate(ids)}
            ii = np.asarray([lookup[r["world_id"]] for r in rows], dtype=np.int64)
            # Only row_ids and final/mean feature tensors are consumed; cache labels are ignored.
            final = cache["surfaces"]["final"].numpy()
            mean = cache["surfaces"]["mean"].numpy()
            merged = np.lib.format.open_memmap(output, mode="w+", dtype=np.float32,
                                               shape=(len(rows), config["input_dim"]))
            for start in range(0, len(rows), 256):
                end = min(start + 256, len(rows))
                merged[start:end, :1024] = final[ii[start:end]]
                merged[start:end, 1024:] = mean[ii[start:end]]
            merged.flush()
            del cache, merged, final, mean
            model_root = ENCODER_CACHE.parents[1] / "models" / "LFM2.5-Encoder-230M"
            identity = {"model": "LiquidAI/LFM2.5-Encoder-230M",
                        "revision": "0b649ad0c684378b03d4d8304f7577a662ab89bc",
                        "model_files": {p.name: sha_file(p) for p in sorted(model_root.iterdir())
                                        if p.suffix in (".json", ".safetensors")},
                        "surface": "final_plus_mean",
                        "mean_definition": "final-layer masked mean; not all-layer full_mean",
                        "extractor_sha256": sha_file(BANK_CODE.parents[1] / "encoder-contrast-01" / "src" / "extract_primitives.py")}
        receipts[substrate] = {"path": str(output), "sha256": sha_file(output),
                               "representation_id": canon_hash(identity), "identity": identity}
        if substrate == "encoder_base":
            receipts[substrate]["population_source"] = {"path": str(path), "sha256": actual}
        print(f"features complete: {split}/{substrate}", flush=True)
    return receipts


def prepare(split: str, limit: int, output_root: Path, config: dict) -> dict:
    if limit <= 0:
        raise ValueError("positive row budget required")
    root = output_root.resolve()
    if root.drive.lower() != "c:":
        raise ValueError("generated Phase0 artifacts must remain on C: NVMe")
    destination = root / split
    if destination.exists():
        raise FileExistsError(f"no-clobber: {destination}")
    rows = read_inputs(split, limit)
    wanted = {base_id(r) for r in rows}
    other = "DEV" if split == "TRAIN" else "TRAIN"
    other_manifest = root / other / "manifest.json"
    if other_manifest.is_file():
        other_ids = set(json.loads((root / other / "groups.json").read_text()))
        if wanted & other_ids:
            raise ValueError("TRAIN/DEV canonical world group overlap")
    worlds = read_worlds(split, wanted)
    destination.mkdir(parents=True)
    gy, gm, cy, cm, actions, offsets, metadata = [], [], [], [], [], [0], []
    for row in rows:
        world = worlds[base_id(row)]
        if row.get("world_hash") != canon_hash({k: world[k] for k in sorted(world) if k != "world_id"}):
            raise ValueError("input/canonical-world hash mismatch")
        a = candidates_from_observation(row)
        g_y, g_m, c_y, c_m = labels_from_world(world, a)
        gy.append(g_y); gm.append(g_m); cy.append(c_y); cm.append(c_m)
        actions.append(candidate_encoding(row, a, config["max_entities"]))
        offsets.append(offsets[-1] + len(a))
        metadata.append({"world_id": row["world_id"], "group_id": base_id(row),
                         "renderer": row["surface_family"], "candidate_actions": a})
    arrays = {"global_y": np.stack(gy), "global_available": np.stack(gm),
              "candidate_y": np.concatenate(cy), "candidate_available": np.concatenate(cm),
              "actions": np.concatenate(actions), "offsets": np.asarray(offsets, np.int64)}
    for name, array in arrays.items():
        np.save(destination / f"{name}.npy", array, allow_pickle=False)
    write_json(destination / "groups.json", sorted(wanted))
    with (destination / "rows.jsonl").open("w", encoding="utf-8") as dst:
        for row in metadata:
            dst.write(json.dumps(row, sort_keys=True) + "\n")
    feature_receipts = prepare_features(rows, split, destination, config)
    files = {p.name: sha_file(p) for p in destination.iterdir() if p.is_file()}
    receipt = {
        "schema": "frozen-fabrique.phase0-prepared-data/v1", "split": split,
        "rows": len(rows), "canonical_world_groups": len(wanted),
        "candidates": offsets[-1], "config_sha256": canon_hash(config),
        "supervision_abi_sha256": canon_hash(supervision_abi()),
        "input_source": {"path": str(BANK / "inputs" / f"{split}.jsonl"),
                         "sha256": sha_file(BANK / "inputs" / f"{split}.jsonl")},
        "world_source": {"path": str(BANK / "worlds" / f"{split}.jsonl"),
                         "sha256": sha_file(BANK / "worlds" / f"{split}.jsonl")},
        "source_code_hashes": {n: sha_file(BANK_CODE / n) for n in ("schema.py", "worldgen.py", "simulator.py", "renderer.py", "build_bank.py")},
        "representations": feature_receipts, "files": files,
        "candidates_match_canonical": True, "input_world_hashes_verified": True,
        "model_inputs": "H tensors plus independently observable schema-derived A; labels/identities/renderer metadata never enter the graft",
        "truth_used_for_targets_only": True, "protected_test_truth_accessed": False,
        "supervision_masks": {"global": arrays["global_available"].sum(0).tolist(),
                              "candidate": arrays["candidate_available"].sum(0).tolist()},
    }
    write_json(destination / "manifest.json", receipt)
    return receipt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=("TRAIN", "DEV"), required=True)
    ap.add_argument("--rows", type=int)
    ap.add_argument("--out", type=Path, default=NVME / "data")
    args = ap.parse_args()
    cfg = default_config()
    count = args.rows if args.rows is not None else cfg["train_rows" if args.split == "TRAIN" else "dev_rows"]
    print(json.dumps(prepare(args.split, count, args.out, cfg), indent=2))


if __name__ == "__main__":
    main()
