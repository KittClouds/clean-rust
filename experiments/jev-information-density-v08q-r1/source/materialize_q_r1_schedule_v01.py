"""Materialize the frozen 12-seed Q-R1 schedule without model contact."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
R1 = ROOT / "experiments/jev-information-density-v08q-r1"
Q = ROOT / "experiments/jev-information-density-v08q"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r1\training-v01")
SCHEDULE_ROOT = RUN / "schedule"
CONTRACT = R1 / "contracts/q-r1-run-contract-v01.json"
ANALYSIS = R1 / "contracts/q-r1-analysis-contract-v01.json"
PACKET_SEAL = R1 / "seals/q-r1-packet-seal-and-authorization-v01.json"
SOURCE_LOCK = Q / "contracts/q-source-lock-v02.json"
PRIMARY = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-v03-inputs\common-primary-occurrence-manifest.jsonl")
EXPECTED = {
    "run": "e5fb3bd147bd5866849266937dc5b060abd8047c13faf2dea48908af518c1317",
    "analysis": "98d5f781d8f98a9a2e6f3737ddbcb2765bbb1f174c25a01292db1e3e5cc4e81b",
    "packet_root": "dfc1f1c9d1e59a1a9abd930f437f3227261e9fa91f85a70ff3ed4c849e6833c0",
    "source_lock": "d6d70768242ac12801069e2bdb27cb976679c907206e81ae8c0921867bea2363",
    "primary": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
}
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def schedule_for_seed(primary: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    group_to_index = {str(row["group_id"]): index for index, row in enumerate(primary)}
    require(len(group_to_index) == 10_000, "primary group IDs are not unique")
    ordered = sorted(group_to_index)
    rows: list[dict[str, Any]] = []
    for epoch in range(1, 4):
        shuffled = list(ordered)
        random.Random(seed + epoch - 1).shuffle(shuffled)
        for local_step in range(40):
            groups = shuffled[local_step * 256:(local_step + 1) * 256]
            indices = [group_to_index[group] for group in groups]
            slots = [primary[index]["occurrence_index"] // 2 for index in indices
                     if primary[index]["role"] == "anchor"]
            rows.append({
                "seed": seed,
                "epoch": epoch,
                "step": local_step + 1,
                "steps_in_epoch": 40,
                "primary_occurrence_indices": indices,
                "primary_group_ids": groups,
                "auxiliary_anchor_batch_slots": slots,
                "active_auxiliary_count": len(slots),
                "auxiliary_order": "ascending primary batch order; source role is arm payload only",
            })
    return rows


def validate(primary: list[dict[str, Any]], rows: list[dict[str, Any]], seeds: list[int]) -> None:
    require(len(primary) == 10_000, "common primary stream row count mismatch")
    require(all(row.get("occurrence_index") == i for i, row in enumerate(primary)),
            "common primary occurrence order is not dense")
    require(all(row.get("source_partition") == "train" for row in primary),
            "non-training row present in common primary stream")
    require(all(row.get("role") == ("anchor" if i % 2 == 0 else "fact_flip")
                for i, row in enumerate(primary)), "primary role layout mismatch")
    require(len(rows) == len(seeds) * 120, "R1 schedule row count mismatch")
    for seed in seeds:
        for epoch in (1, 2, 3):
            block = sorted((row for row in rows if row["seed"] == seed and row["epoch"] == epoch),
                           key=lambda row: row["step"])
            require(len(block) == 40 and [row["step"] for row in block] == list(range(1, 41)),
                    f"schedule epoch shape mismatch {seed}/{epoch}")
            primary_indices = [idx for row in block for idx in row["primary_occurrence_indices"]]
            aux_slots = [idx for row in block for idx in row["auxiliary_anchor_batch_slots"]]
            require(sorted(primary_indices) == list(range(10_000)), f"primary coverage mismatch {seed}/{epoch}")
            require(sorted(aux_slots) == list(range(5_000)), f"auxiliary coverage mismatch {seed}/{epoch}")
            for row in block:
                indices = row["primary_occurrence_indices"]
                expected_groups = [primary[index]["group_id"] for index in indices]
                expected_slots = [primary[index]["occurrence_index"] // 2 for index in indices
                                  if primary[index]["role"] == "anchor"]
                expected_batch = 16 if row["step"] == 40 else 256
                require(row["primary_group_ids"] == expected_groups
                        and row["auxiliary_anchor_batch_slots"] == expected_slots
                        and row["active_auxiliary_count"] == len(expected_slots)
                        and len(indices) == expected_batch,
                        f"schedule batch binding mismatch {seed}/{epoch}/{row['step']}")


def main() -> int:
    require(sha(CONTRACT) == EXPECTED["run"], "R1 run contract hash mismatch")
    require(sha(ANALYSIS) == EXPECTED["analysis"], "R1 analysis contract hash mismatch")
    packet = read_json(PACKET_SEAL)
    require(packet.get("status") == "SEALED_AUTHORIZED_PENDING_EXECUTION"
            and packet.get("contract_bundle_root_sha256") == EXPECTED["packet_root"],
            "R1 authorization packet mismatch")
    for row in packet["contracts"]:
        path = R1 / row["path"]
        require(path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
                f"R1 contract binding mismatch: {row['path']}")
    require(sha(SOURCE_LOCK) == EXPECTED["source_lock"] and sha(PRIMARY) == EXPECTED["primary"],
            "bound training source identity mismatch")
    lock = read_json(SOURCE_LOCK)
    require(any(row.get("sha256") == EXPECTED["primary"] and Path(row["path"]).resolve() == PRIMARY.resolve()
                for row in lock["entries"]), "primary source is not bound by the Q source lock")
    run = read_json(CONTRACT)
    seeds = run["paired_design"]["seeds"]
    require(len(seeds) == 12 and len(set(seeds)) == 12, "R1 seed set cardinality mismatch")
    q_seeds = {2540205348, 2603246505, 3565067208}
    require(not (set(seeds) & q_seeds), "R1 seed overlaps the original Q seed set")
    for index, seed in enumerate(seeds):
        label = f"jev-information-density-v08q-r1-run-v01/optimizer-seed/{index}".encode("utf-8")
        expected_seed = int.from_bytes(hashlib.sha256(label).digest()[:4], "little", signed=False)
        require(seed == expected_seed, f"R1 seed derivation mismatch at index {index}")
    primary = read_jsonl(PRIMARY)
    schedule = [row for seed in seeds for row in schedule_for_seed(primary, seed)]
    validate(primary, schedule, seeds)
    encoded = b"".join(canonical_json(row) for row in schedule)
    replay = b"".join(canonical_json(row) for seed in seeds for row in schedule_for_seed(primary, seed))
    require(encoded == replay, "independent in-process schedule reconstruction differs")
    require(not SCHEDULE_ROOT.exists(), f"refusing to overwrite schedule namespace: {SCHEDULE_ROOT}")
    SCHEDULE_ROOT.mkdir(parents=True, exist_ok=False)
    schedule_path = SCHEDULE_ROOT / "fixed-schedule.jsonl"
    schedule_path.write_bytes(encoded)
    schedule_hash = sha(schedule_path)
    order = {str(seed): list(ARMS[index % len(ARMS):] + ARMS[:index % len(ARMS)])
             for index, seed in enumerate(seeds)}
    manifest = {
        "status": "Q_R1_SCHEDULE_MATERIALIZED_PRE_INITIALIZATION",
        "schedule_sha256": schedule_hash,
        "schedule_rows": len(schedule),
        "seeds": seeds,
        "arms": list(ARMS),
        "arm_order_by_seed": order,
        "steps_per_epoch": 40,
        "total_steps_per_run": 120,
        "checkpoint_steps": [40, 80, 100, 120],
        "runs": 48,
        "schedule_rows_per_seed": 120,
        "primary_manifest_sha256": EXPECTED["primary"],
        "source_lock_sha256": EXPECTED["source_lock"],
        "run_contract_sha256": EXPECTED["run"],
        "analysis_contract_sha256": EXPECTED["analysis"],
        "algorithm_source_sha256": sha(Path(__file__).resolve()),
        "panel_opened": False,
        "head_initialized": False,
        "training": False,
        "evaluation": False,
    }
    manifest_path = SCHEDULE_ROOT / "fixed-schedule-manifest.json"
    manifest_path.write_bytes(canonical_json(manifest))
    seal = {
        "status": "Q_R1_SCHEDULE_SEALED_PRE_INITIALIZATION",
        "schedule_sha256": schedule_hash,
        "schedule_manifest_sha256": sha(manifest_path),
        "algorithm_source_sha256": manifest["algorithm_source_sha256"],
        "schedule_rows": len(schedule),
        "run_count": 48,
        "head_initialized": False,
        "training": False,
        "panel_read": False,
        "inference": False,
    }
    seal_path = SCHEDULE_ROOT / "schedule-seal.json"
    seal_path.write_bytes(canonical_json(seal))
    print(json.dumps({"status": seal["status"], "schedule_sha256": schedule_hash,
                      "schedule_rows": len(schedule), "seed_count": len(seeds), "run_count": 48}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
