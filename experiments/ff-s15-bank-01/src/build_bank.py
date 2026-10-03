"""Build sealed finite BANK-v1 release. Data-engineering only. No model contact."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

CODE = Path(__file__).resolve().parent
EXP = CODE.parent
ROOT = CODE.parents[2]

from src import worldgen as W
from src import renderer as R
from src import projections as P
from src import splits as S
from src import verify as V
from src.schema import SURFACE_FAMILIES


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def canon(v) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(canon(r) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=str, default="releases/BANK-v1")
    ap.add_argument("--pair-rate", type=float, default=0.1)
    args = ap.parse_args()
    budget = S.FAST_BUDGET if args.fast else S.FULL_BUDGET
    if args.fast:
        outdir = EXP / "releases" / "BANK-v1-fast"
    else:
        outdir = EXP / args.out
    worlds_by_split: dict[str, list[dict]] = {}
    input_rows: dict[str, list[dict]] = {}
    truth_rows: dict[str, list[dict]] = {}
    stats = {}
    # Deterministic unique-fill: pure function of (split, seed) + generation order.
    # Later literal-dups are skipped and topped up from further indices. Global `seen`
    # spans splits in budget order, so TEST never repeats TRAIN content. Cleanroom
    # reconstruction replays this exact loop (see seal G25).
    seen_literal: set[str] = set()
    skipped_dups = 0
    for split, n in budget.items():
        worlds, inputs = [], []
        i = 0
        guard = 0
        while len(worlds) < n and guard < n * 20 + 10000:
            guard += 1
            w = W.generate_world(split, i, args.seed)
            i += 1
            h0 = V.world_hash(w)
            if h0 in seen_literal:
                skipped_dups += 1
                continue
            seen_literal.add(h0)
            rend = R.render(w)
            proj = P.project(w, rend)
            verrs = V.validate_example(w, rend, proj)
            if verrs:
                raise RuntimeError(f"validator failed {w['world_id']}: {verrs}")
            mchk = V.metamorphic_checks(w)
            if mchk:
                raise RuntimeError(f"metamorphic failed {w['world_id']}: {mchk}")
            wh = V.world_hash(w)
            row = {"world_id": w["world_id"], "split": split, "world_hash": wh,
                   "graph_hash": V.canonical_graph_hash(w),
                   "surface_family": w["surface_family"], "input_text": rend["text"],
                   "bindings": rend["bindings"], "goal": w["goal"],
                   "difficulty": w["difficulty"], "decision": w["decision"]}
            worlds.append(w)
            inputs.append({**row, "labels": {"policy": proj["policy"], "abstention": proj["abstention"],
                           "evidence": proj["evidence"], "nli": proj["nli"],
                           "entity": proj["entity"], "relation": proj["relation"],
                           "transition": proj["transition"]}})
            # paired surfaces: same truth, extra renderings (deterministic extras)
            if (i % int(1 / args.pair_rate)) == 0:
                extras = [f for f in SURFACE_FAMILIES if f != w["surface_family"]][:2]
                for ef in extras:
                    r2 = R.render(w, ef)
                    inputs.append({**row, "world_id": w["world_id"] + f"@{ef}", "surface_family": ef,
                                   "input_text": r2["text"], "bindings": r2["bindings"],
                                   "paired_world": w["world_id"], "labels": {"policy": proj["policy"]}})
        if len(worlds) < n:
            raise RuntimeError(f"unique-fill exhausted for {split}: kept {len(worlds)}/{n}")
        worlds_by_split[split] = worlds
        input_rows[split] = inputs
        stats[split] = {"worlds": len(worlds), "input_rows": len(inputs)}
    leaks = V.leakage_scan(worlds_by_split)
    lit = [x for x in leaks if "literal_dup" in x]
    if lit:
        raise RuntimeError(f"literal leakage after unique-fill: {lit[:5]}")
    graph_iso = len(leaks)
    print(json.dumps({"unique_fill_skipped_dups": skipped_dups, "graph_iso_collisions_reported": graph_iso}))
    # write worlds + inputs; escrow test truth
    for split in budget:
        write_jsonl(outdir / "worlds" / f"{split}.jsonl", worlds_by_split[split])
        if split.startswith("TEST-"):
            pub = [{k: r[k] for k in ("world_id", "split", "surface_family", "input_text", "bindings", "goal", "difficulty", "world_hash", "graph_hash", "paired_world") if k in r} for r in input_rows[split]]
            tru = [{"world_id": r["world_id"], "world_hash": r["world_hash"], "labels": r["labels"]} for r in input_rows[split]]
            write_jsonl(outdir / "public" / "test-inputs" / f"{split}.jsonl", pub)
            write_jsonl(outdir / "protected" / "test-truth" / f"{split}.jsonl", tru)
        else:
            write_jsonl(outdir / "inputs" / f"{split}.jsonl", input_rows[split])
    # manifests
    code_files = ["schema.py", "worldgen.py", "simulator.py", "renderer.py", "projections.py", "splits.py", "verify.py", "build_bank.py", "seal.py"]
    code_hashes = {f: sha_file(CODE / f) for f in code_files if (CODE / f).exists()}
    seed_man = json.loads((EXP / "seed-registry-v1.json").read_text())
    manifest = {"bank": "FF-S15-BANK-01", "release": "BANK-v1", "seed": args.seed,
                "fast": args.fast, "budget": budget, "stats": stats,
                "schema_version": "ff-s15-bank-schema-v1", "generator_version": W.GENERATOR_VERSION,
                "code_hashes": code_hashes, "seed_registry_hash": hashlib.sha256(canon(seed_man).encode()).hexdigest(),
                "surfaces": SURFACE_FAMILIES,
                "row_hashes": {s: hashlib.sha256(open(outdir / "worlds" / f"{s}.jsonl", "rb").read()).hexdigest() for s in budget},
                "unique_fill": {"version": "v1-skip-later-literal-dups-global-order", "skipped_dups": skipped_dups, "graph_iso_collisions": graph_iso},
                "frozen_fabric_contact": False, "system_1_5_training": False, "terminal_truth_opened": False,
                "external_rows_imported": 0}
    (outdir / "manifests").mkdir(parents=True, exist_ok=True)
    (outdir / "manifests" / "release.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (outdir / "manifests" / "split-manifest.json").write_text(json.dumps({"budget": budget, "stats": stats}, indent=2) + "\n")
    print(json.dumps({"status": "BANK_BUILD_COMPLETE", "out": str(outdir), "stats": stats}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
