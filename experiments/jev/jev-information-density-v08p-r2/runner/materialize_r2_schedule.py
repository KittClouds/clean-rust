"""Materialize and independently validate the frozen v0.8P-R2 run schedule.

This tool is deliberately pre-initialization: it imports no model code, opens no
head checkpoint, and has no panel/evaluation paths.
"""

from __future__ import annotations

import hashlib
import json
import random
import argparse
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PHASE = ROOT / "experiments/jev-information-density-v08p/phase_b"
R2_ROOT = Path(r"D:\codex-runs\jev-information-density-v08p-r2\v0.8P-R2")
INPUT_ROOT = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-v03-inputs")
PRIMARY_PATH = INPUT_ROOT / "common-primary-occurrence-manifest.jsonl"
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM")
SEEDS = (3243871208, 669993655, 3076094663)
EXPECTED = {
    "run_contract": "e345225b4a17fc18eb35fcab24cbe1d72bd0e34bed9de272f927a7be461853e6",
    "analysis_contract": "84111122033fda65c84344317cfe3b50639b23be4c71f480ba665c67a23cc939",
    "r2_contract": "51cd8dee09688f1aae24ff575fa0a181d50b2a6ffc94dc6b7e7ed5b61c58ef14",
    "panel_ready": "c0d48381356113451bc72f9578204ade4ef7449a75264cd5018a34d002b313ac",
    "primary": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
    "B-DUP": "f6f4ec519a04efeac02962c68c2d2d8ec92cf43d25bb9fd974f168e67c4d3b2b",
    "B-MATCHED": "bd38446c0328f8092dc3293090fd3041d7be5d53945df6f80fb3770244d87b0d",
    "B-SHAM": "9dd346766856f56006be326c171e664dcbab23983cdd7501f480b6fabb6ff895",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def schedule_for_seed(primary: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    by_group = {str(row["group_id"]): index for index, row in enumerate(primary)}
    require(len(by_group) == 10_000, "primary group IDs are not unique")
    base_order = sorted(by_group)
    rows: list[dict[str, Any]] = []
    for epoch in range(1, 4):
        shuffled = list(base_order)
        random.Random(seed + epoch - 1).shuffle(shuffled)
        for step_index in range(40):
            start = step_index * 256
            batch_groups = shuffled[start : start + 256]
            ids = [by_group[group] for group in batch_groups]
            slots = [primary[index]["occurrence_index"] // 2
                     for index in ids if primary[index]["role"] == "anchor"]
            rows.append({
                "seed": seed,
                "epoch": epoch,
                "step": step_index + 1,
                "steps_in_epoch": 40,
                "primary_occurrence_indices": ids,
                "primary_group_ids": batch_groups,
                "auxiliary_anchor_batch_slots": slots,
                "active_auxiliary_count": len(slots),
                "auxiliary_order": "ascending primary batch order; source role is arm payload only",
            })
    return rows


def validate_schedule(primary: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    require(len(primary) == 10_000, "primary occurrence count differs from the frozen contract")
    require(all(row.get("occurrence_index") == i for i, row in enumerate(primary)),
            "primary occurrence indices are not dense")
    require(all(row.get("source_partition") == "train" for row in primary),
            "non-training primary occurrence found")
    require(all(primary[i]["role"] == ("anchor" if i % 2 == 0 else "fact_flip")
                for i in range(10_000)), "anchor/fact occurrence pairing differs from the frozen layout")
    require(len(rows) == 360, "schedule must contain exactly 360 seed/epoch/step rows")
    for seed in SEEDS:
        for epoch in range(1, 4):
            block = sorted((row for row in rows if row["seed"] == seed and row["epoch"] == epoch),
                           key=lambda row: row["step"])
            require(len(block) == 40 and [row["step"] for row in block] == list(range(1, 41)),
                    f"step schedule mismatch: {seed}/{epoch}")
            all_indices = [index for row in block for index in row["primary_occurrence_indices"]]
            all_slots = [slot for row in block for slot in row["auxiliary_anchor_batch_slots"]]
            require(sorted(all_indices) == list(range(10_000)), f"primary coverage mismatch: {seed}/{epoch}")
            require(sorted(all_slots) == list(range(5_000)), f"auxiliary coverage mismatch: {seed}/{epoch}")
            require(all(len(row["primary_occurrence_indices"]) == len(row["primary_group_ids"])
                        for row in block), f"primary group/index count mismatch: {seed}/{epoch}")
            for row in block:
                ids = row["primary_occurrence_indices"]
                expected_slots = [primary[index]["occurrence_index"] // 2 for index in ids
                                  if primary[index]["role"] == "anchor"]
                require(row["auxiliary_anchor_batch_slots"] == expected_slots,
                        f"auxiliary slot order mismatch: {seed}/{epoch}/{row['step']}")
                require(row["active_auxiliary_count"] == len(expected_slots),
                        f"auxiliary event count mismatch: {seed}/{epoch}/{row['step']}")
                require(len(ids) == (16 if row["step"] == 40 else 256),
                        f"primary batch boundary mismatch: {seed}/{epoch}/{row['step']}")


def jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                    for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-existing", action="store_true",
                        help="reconstruct and verify a previously materialized schedule without replacing it")
    args = parser.parse_args()
    bindings = {
        "run_contract": PHASE / "phase-b-p-run-contract-v01.json",
        "analysis_contract": PHASE / "phase-b-p-analysis-contract-v01.json",
        "r2_contract": ROOT / "experiments/jev-information-density-v08p-r2/contracts/r2-execution-contract-v01.json",
        "panel_ready": ROOT / "experiments/jev-information-density-v08p-r2/provenance/r2-panel-ready-manifest-v01.json",
        "primary": PRIMARY_PATH,
    }
    for name, path in bindings.items():
        require(path.is_file(), f"missing bound input: {name}")
        require(sha256_file(path) == EXPECTED[name], f"bound input hash mismatch: {name}")
    contract = json.loads(bindings["run_contract"].read_text(encoding="utf-8"))
    require(contract["training"]["seed_set"]["seeds"] == list(SEEDS), "P seed contract drift")
    require(contract["training"]["schedule"]["schedule_rows"] == 360, "schedule row contract drift")
    require(contract["training"]["steps_per_run"] == 120, "optimizer step contract drift")
    primary = read_jsonl(PRIMARY_PATH)
    require(sha256_file(PRIMARY_PATH) == EXPECTED["primary"], "primary manifest hash drift")

    arm_paths = {arm: INPUT_ROOT / f"head-input-manifest-{arm}.jsonl" for arm in ARMS}
    arm_rows = {}
    for arm, path in arm_paths.items():
        require(path.is_file() and sha256_file(path) == EXPECTED[arm], f"arm input hash mismatch: {arm}")
        arm_rows[arm] = read_jsonl(path)
        require(len(arm_rows[arm]) == 15_000, f"arm input count mismatch: {arm}")
        for i, primary_row in enumerate(primary):
            row = arm_rows[arm][i]
            require(row.get("event_kind") == "primary" and row.get("occurrence_index") == i,
                    f"primary stream drift in {arm} at {i}")
            require(row.get("source_episode_id") == primary_row["episode_id"]
                    and row.get("target_hash") == primary_row["target_hash"]
                    and row.get("candidate_order_hash") == primary_row["candidate_order_hash"],
                    f"common primary payload differs in {arm} at {i}")
        expected_role = {"B-DUP": "anchor_duplicate", "B-MATCHED": "matched_neutral",
                         "B-SHAM": "certified_sham"}[arm]
        require(all(row.get("auxiliary_source_role") == expected_role for row in arm_rows[arm][10_000:]),
                f"auxiliary role mismatch: {arm}")
        require(all(row.get("loss_weight") == 1.0 for row in arm_rows[arm]), f"loss weight mismatch: {arm}")

    all_rows = [row for seed in SEEDS for row in schedule_for_seed(primary, seed)]
    validate_schedule(primary, all_rows)
    first = jsonl_bytes(all_rows)
    second = jsonl_bytes([row for seed in SEEDS for row in schedule_for_seed(primary, seed)])
    require(first == second, "independent in-process schedule reconstruction differs")
    schedule_sha = hashlib.sha256(first).hexdigest()

    out = R2_ROOT / "schedule"
    if args.verify_existing:
        require(out.is_dir(), f"schedule directory is absent: {out}")
        schedule_path = out / "fixed-schedule.jsonl"
        manifest_path = out / "fixed-schedule-manifest.json"
        require(schedule_path.is_file() and manifest_path.is_file(), "existing schedule package is incomplete")
        require(schedule_path.read_bytes() == first and sha256_file(schedule_path) == schedule_sha,
                "independent process reconstruction differs from sealed schedule bytes")
        saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(saved_manifest.get("schedule_sha256") == schedule_sha
                and saved_manifest.get("schedule_rows") == 360
                and saved_manifest.get("status") == "P_R2_FIXED_SCHEDULE_VALIDATED_PRE_INITIALIZATION",
                "existing schedule manifest does not match reconstructed schedule")
        seal_path = out / "r2-schedule-seal-v01.json"
        require(not seal_path.exists(), "schedule seal already exists; refusing overwrite")
        seal = {
            "status": "P_R2_SCHEDULE_SEALED_PRE_INITIALIZATION",
            "schedule_sha256": schedule_sha,
            "schedule_manifest_sha256": sha256_file(manifest_path),
            "schedule_rows": 360,
            "independent_process_reconstruction": "BYTE_IDENTICAL",
            "materializer_sha256": sha256_file(Path(__file__).resolve()),
            "head_initialized": False,
            "panel_or_evaluation_read": False,
            "E1_access": False,
            "phoenix_access": False,
        }
        seal_path.write_text(json.dumps(seal, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": seal["status"], "schedule_sha256": schedule_sha,
                          "materializer_sha256": seal["materializer_sha256"],
                          "head_initialized": False}, separators=(",", ":")))
        return 0

    require(not out.exists(), f"schedule output already exists; refusing overwrite: {out}")
    out.mkdir(parents=True, exist_ok=False)
    schedule_path = out / "fixed-schedule.jsonl"
    schedule_path.write_bytes(first)
    require(sha256_file(schedule_path) == schedule_sha, "durable schedule hash mismatch")
    manifest = {
        "status": "P_R2_FIXED_SCHEDULE_VALIDATED_PRE_INITIALIZATION",
        "schedule_sha256": schedule_sha,
        "schedule_rows": len(all_rows),
        "seeds": list(SEEDS),
        "arms_share_schedule": True,
        "independent_reconstruction_byte_equal": True,
        "primary_rows_per_epoch": 10_000,
        "auxiliary_events_per_epoch": 5_000,
        "optimizer_steps_per_epoch": 40,
        "global_optimizer_steps_per_run": 120,
        "checkpoint_steps": [40, 80, *range(81, 121)],
        "checkpoint_count_per_run": 42,
        "source_bindings": {name: {"path": str(path), "sha256": EXPECTED[name]}
                            for name, path in bindings.items()},
        "arm_manifest_sha256": {arm: EXPECTED[arm] for arm in ARMS},
        "model_or_head_loaded": False,
        "panel_or_evaluation_read": False,
        "E1_access": False,
        "phoenix_access": False,
    }
    manifest_path = out / "fixed-schedule-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "schedule_sha256": schedule_sha,
                      "rows": len(all_rows), "output": str(out), "head_initialized": False},
                     separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
