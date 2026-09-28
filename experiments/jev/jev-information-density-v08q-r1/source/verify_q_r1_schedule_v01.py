"""Clean-process byte and coverage verification of the Q-R1 fixed schedule."""

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
SOURCE_LOCK = Q / "contracts/q-source-lock-v02.json"
PRIMARY = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-v03-inputs\common-primary-occurrence-manifest.jsonl")
RECEIPT = SCHEDULE_ROOT / "independent-verification-v01.json"
EXPECTED = {
    "run": "e5fb3bd147bd5866849266937dc5b060abd8047c13faf2dea48908af518c1317",
    "analysis": "98d5f781d8f98a9a2e6f3737ddbcb2765bbb1f174c25a01292db1e3e5cc4e81b",
    "source_lock": "d6d70768242ac12801069e2bdb27cb976679c907206e81ae8c0921867bea2363",
    "primary": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
}


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


def need(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def independently_reconstruct(primary: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    index_by_group: dict[str, int] = {}
    for index, row in enumerate(primary):
        group = str(row["group_id"])
        need(group not in index_by_group, "duplicate primary group identity")
        index_by_group[group] = index
    ordered_groups = sorted(index_by_group)
    result: list[dict[str, Any]] = []
    for epoch in (1, 2, 3):
        permutation = ordered_groups.copy()
        random.Random(seed + epoch - 1).shuffle(permutation)
        for batch_idx in range(40):
            start = batch_idx * 256
            group_batch = permutation[start:start + 256]
            occurrence_batch = [index_by_group[group] for group in group_batch]
            aux = [primary[idx]["occurrence_index"] // 2 for idx in occurrence_batch
                   if primary[idx]["role"] == "anchor"]
            result.append({
                "seed": seed, "epoch": epoch, "step": batch_idx + 1, "steps_in_epoch": 40,
                "primary_occurrence_indices": occurrence_batch,
                "primary_group_ids": group_batch,
                "auxiliary_anchor_batch_slots": aux,
                "active_auxiliary_count": len(aux),
                "auxiliary_order": "ascending primary batch order; source role is arm payload only",
            })
    return result


def main() -> int:
    need(sha(CONTRACT) == EXPECTED["run"] and sha(ANALYSIS) == EXPECTED["analysis"],
         "R1 contract identity mismatch")
    need(sha(SOURCE_LOCK) == EXPECTED["source_lock"] and sha(PRIMARY) == EXPECTED["primary"],
         "bound primary source identity mismatch")
    run = read_json(CONTRACT)
    seeds = run["paired_design"]["seeds"]
    need(len(seeds) == 12 and len(set(seeds)) == 12, "R1 seed count or uniqueness mismatch")
    primary = read_jsonl(PRIMARY)
    schedule_path = SCHEDULE_ROOT / "fixed-schedule.jsonl"
    saved = read_jsonl(schedule_path)
    rebuilt = [row for seed in seeds for row in independently_reconstruct(primary, seed)]
    saved_bytes = schedule_path.read_bytes()
    rebuilt_bytes = b"".join(canonical_json(row) for row in rebuilt)
    need(saved_bytes == rebuilt_bytes, "clean-process schedule reconstruction is not byte-identical")
    need(len(saved) == 1_440, "R1 schedule row count mismatch")
    for seed in seeds:
        rows = [row for row in saved if row["seed"] == seed]
        need(len(rows) == 120, f"R1 per-seed schedule row count mismatch: {seed}")
        for epoch in (1, 2, 3):
            block = sorted((r for r in rows if r["epoch"] == epoch), key=lambda r: r["step"])
            need(len(block) == 40 and [r["step"] for r in block] == list(range(1, 41)),
                 f"R1 epoch sequence mismatch: {seed}/{epoch}")
            primary_ids = [idx for row in block for idx in row["primary_occurrence_indices"]]
            aux_ids = [idx for row in block for idx in row["auxiliary_anchor_batch_slots"]]
            need(sorted(primary_ids) == list(range(10_000)) and sorted(aux_ids) == list(range(5_000)),
                 f"R1 occurrence coverage mismatch: {seed}/{epoch}")
            need(all(len(row["primary_occurrence_indices"]) == (16 if row["step"] == 40 else 256)
                     for row in block), f"R1 batch boundary mismatch: {seed}/{epoch}")
    manifest = read_json(SCHEDULE_ROOT / "fixed-schedule-manifest.json")
    seal = read_json(SCHEDULE_ROOT / "schedule-seal.json")
    need(manifest["schedule_sha256"] == sha(schedule_path) == seal["schedule_sha256"],
         "R1 schedule hash is inconsistent")
    need(manifest["schedule_rows"] == seal["schedule_rows"] == 1_440
         and manifest["runs"] == seal["run_count"] == 48
         and manifest["checkpoint_steps"] == [40, 80, 100, 120],
         "R1 schedule manifest contract mismatch")
    need(not any(manifest.get(key) for key in ("panel_opened", "head_initialized", "training", "evaluation")),
         "R1 schedule manifest overstates downstream state")
    need(not any(seal.get(key) for key in ("head_initialized", "training", "panel_read", "inference")),
         "R1 schedule seal overstates downstream state")
    need(not RECEIPT.exists(), "refusing to replace R1 schedule verification receipt")
    receipt = {
        "status": "Q_R1_SCHEDULE_CLEAN_PROCESS_VERIFICATION_PASS",
        "schedule_sha256": sha(schedule_path),
        "schedule_manifest_sha256": sha(SCHEDULE_ROOT / "fixed-schedule-manifest.json"),
        "schedule_seal_sha256": sha(SCHEDULE_ROOT / "schedule-seal.json"),
        "schedule_rows": len(saved),
        "seed_count": len(seeds),
        "run_count": 48,
        "checkpoint_steps": [40, 80, 100, 120],
        "clean_process_reconstruction": "BYTE_IDENTICAL",
        "verifier_source_sha256": sha(Path(__file__).resolve()),
        "head_initialization": False,
        "training": False,
        "panel_read": False,
        "inference": False,
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
