"""Materialize and independently reconstruct the sealed 24-seed R2 event schedule."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
OUT = RUN / "training-v01/schedule"
CONTRACT = EXP / "contracts/q-r2-run-contract-v01.json"
PACKET = EXP / "seals/q-r2-phase-packet-seal-v01.json"
SOURCE_LOCK = ROOT / "experiments/jev-information-density-v08q/contracts/q-source-lock-v02.json"
PRIMARY = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-v03-inputs\common-primary-occurrence-manifest.jsonl")
EXPECTED = {
    "contract": "52d093a00076700ed24bfe0e2cc33ada73dfc07d073b39cbdbe52103aef525e6",
    "analysis": "e06cb4d9428f6c1e30603fbfcb442629f991ef96e37555fb09ac7a4fd0b80e64",
    "packet": "3f6367cb5bf03400923913fffb9acc5cc21ffa32ffdaee807615725ff7f2c209",
    "source_lock": "d6d70768242ac12801069e2bdb27cb976679c907206e81ae8c0921867bea2363",
    "primary": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def schedule_for_seed(primary: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    group_to_index = {str(row["group_id"]): i for i, row in enumerate(primary)}
    require(len(group_to_index) == 10_000, "primary group IDs are not unique")
    ordered = sorted(group_to_index)
    rows: list[dict[str, Any]] = []
    for epoch in range(1, 4):
        shuffled = list(ordered)
        random.Random(seed + epoch - 1).shuffle(shuffled)
        for local_step in range(40):
            groups = shuffled[local_step * 256 : (local_step + 1) * 256]
            indices = [group_to_index[group] for group in groups]
            slots = [primary[i]["occurrence_index"] // 2 for i in indices if primary[i]["role"] == "anchor"]
            rows.append({
                "seed": seed,
                "epoch": epoch,
                "step": local_step + 1,
                "global_step": (epoch - 1) * 40 + local_step + 1,
                "primary_occurrence_indices": indices,
                "primary_group_ids": groups,
                "auxiliary_anchor_batch_slots": slots,
                "active_auxiliary_count": len(slots),
                "auxiliary_order": "ascending primary batch order; same B-SHAM payload in both branches",
            })
    return rows


def validate(primary: list[dict[str, Any]], rows: list[dict[str, Any]], seeds: list[int]) -> None:
    require(len(primary) == 10_000, "common primary stream row count mismatch")
    require(all(row.get("occurrence_index") == i for i, row in enumerate(primary)), "primary order is not dense")
    require(all(row.get("source_partition") == "train" for row in primary), "non-training row in primary stream")
    require(len(rows) == len(seeds) * 120, "R2 schedule row count mismatch")
    for seed in seeds:
        for epoch in (1, 2, 3):
            block = sorted((r for r in rows if r["seed"] == seed and r["epoch"] == epoch), key=lambda r: r["step"])
            require(len(block) == 40 and [r["step"] for r in block] == list(range(1, 41)), f"schedule block mismatch {seed}/{epoch}")
            require(sorted(i for row in block for i in row["primary_occurrence_indices"]) == list(range(10_000)), "primary coverage mismatch")
            require(sorted(i for row in block for i in row["auxiliary_anchor_batch_slots"]) == list(range(5_000)), "auxiliary coverage mismatch")
            for row in block:
                idx = row["primary_occurrence_indices"]
                slots = [primary[i]["occurrence_index"] // 2 for i in idx if primary[i]["role"] == "anchor"]
                require(row["auxiliary_anchor_batch_slots"] == slots, "auxiliary slot binding mismatch")
                require(len(idx) == (16 if row["step"] == 40 else 256), "batch size mismatch")
                require(row["global_step"] == (epoch - 1) * 40 + row["step"], "global step mapping mismatch")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        assert canonical({"b": 1, "a": 2}) == b'{"b":1,"a":2}\n'
        assert len(schedule_for_seed([{"group_id": str(i), "occurrence_index": i, "role": "anchor" if i % 2 == 0 else "fact_flip"} for i in range(10_000)], 7)) == 120
        print("R2 schedule synthetic self-test PASS")
        return 0
    require(sha(CONTRACT) == EXPECTED["contract"] and sha(SOURCE_LOCK) == EXPECTED["source_lock"], "R2 schedule authority hash mismatch")
    require(sha(PRIMARY) == EXPECTED["primary"], "bound primary stream hash mismatch")
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    require(sha(PACKET) == EXPECTED["packet"] and packet.get("status") == "SEALED_AUTHORIZED_FOR_PHASE_EXECUTION", "R2 authorization packet mismatch")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    seeds = contract["paired_seed_design"]["seeds"]
    require(len(seeds) == 24 and len(set(seeds)) == 24, "R2 seed set invalid")
    primary = read_jsonl(PRIMARY)
    schedule = [row for seed in seeds for row in schedule_for_seed(primary, seed)]
    validate(primary, schedule, seeds)
    replay = [row for seed in seeds for row in schedule_for_seed(primary, seed)]
    encoded = b"".join(canonical(row) for row in schedule)
    require(encoded == b"".join(canonical(row) for row in replay), "clean deterministic schedule reconstruction mismatch")
    require(not OUT.exists(), f"refusing existing schedule output: {OUT}")
    OUT.mkdir(parents=True, exist_ok=False)
    schedule_path = OUT / "fixed-schedule.jsonl"
    schedule_path.write_bytes(encoded)
    order = {str(seed): (["LATE_SHAM_1X", "LATE_SHAM_HALF"] if i % 2 == 0 else ["LATE_SHAM_HALF", "LATE_SHAM_1X"]) for i, seed in enumerate(seeds)}
    manifest = {
        "status": "Q_R2_SCHEDULE_MATERIALIZED_PRE_INITIALIZATION",
        "schedule_sha256": sha(schedule_path), "schedule_rows": len(schedule), "seeds": seeds,
        "common_history_steps": [1, 80], "continuation_steps": [81, 120],
        "branch_order_by_seed": order, "steps_per_epoch": 40, "total_steps": 120,
        "checkpoints": [80, 100, 120], "common_prefixes": 24, "continuations": 48,
        "run_contract_sha256": EXPECTED["contract"], "analysis_contract_sha256": EXPECTED["analysis"],
        "primary_manifest_sha256": EXPECTED["primary"], "algorithm_source_sha256": sha(Path(__file__).resolve()),
        "head_initialized": False, "training": False, "panel_opened": False, "evaluation": False,
    }
    (OUT / "fixed-schedule-manifest.json").write_bytes(canonical(manifest))
    seal = {"status": "Q_R2_SCHEDULE_SEALED_PRE_INITIALIZATION", "schedule_sha256": sha(schedule_path),
            "manifest_sha256": sha(OUT / "fixed-schedule-manifest.json"), "rows": len(schedule),
            "seed_count": len(seeds), "continuations": 48, "head_initialized": False, "training": False, "panel_read": False}
    (OUT / "schedule-seal.json").write_bytes(canonical(seal))
    print(json.dumps(seal, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
