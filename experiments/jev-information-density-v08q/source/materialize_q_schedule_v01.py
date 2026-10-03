"""Materialize and independently verify the sparse, arm-paired Q schedule.

This is a pre-head operation: it reads training-side inputs only and imports no
torch/model code or evaluation-panel content.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
Q_ROOT = ROOT / "experiments/jev-information-density-v08q"
RUN_CONTRACT = Q_ROOT / "contracts/q-run-contract-v02.json"
ANALYSIS_CONTRACT = Q_ROOT / "contracts/q-analysis-contract-v02.json"
SOURCE_LOCK = Q_ROOT / "contracts/q-source-lock-v02.json"
ADDENDUM = Q_ROOT / "contracts/q-execution-addendum-v01.json"
PANEL_SEAL = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02\seals\q-panel-phase-terminal-seal-v01.json")
INPUT_ROOT = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-v03-inputs")
OUTPUT_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01\schedule")

EXPECTED = {
    "run_contract": "5f6cd42b6de058a4fcdcbeb70b1939dbe944a6c973ee704a93148f9bea71d1ae",
    "analysis_contract": "b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc",
    "source_lock": "d6d70768242ac12801069e2bdb27cb976679c907206e81ae8c0921867bea2363",
    "primary": "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06",
    "B-DUP": "f6f4ec519a04efeac02962c68c2d2d8ec92cf43d25bb9fd974f168e67c4d3b2b",
    "B-MATCHED": "bd38446c0328f8092dc3293090fd3041d7be5d53945df6f80fb3770244d87b0d",
    "B-SHAM": "9dd346766856f56006be326c171e664dcbab23983cdd7501f480b6fabb6ff895",
    "addendum": "363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3",
}
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def schedule_for_seed(primary: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    group_to_index = {str(row["group_id"]): index for index, row in enumerate(primary)}
    require(len(group_to_index) == 10_000, "primary groups are not unique")
    base_order = sorted(group_to_index)
    output: list[dict[str, Any]] = []
    for epoch in range(1, 4):
        shuffled = list(base_order)
        random.Random(seed + epoch - 1).shuffle(shuffled)
        for local_step in range(40):
            start = local_step * 256
            groups = shuffled[start : start + 256]
            indices = [group_to_index[group] for group in groups]
            aux_slots = [primary[index]["occurrence_index"] // 2 for index in indices
                         if primary[index]["role"] == "anchor"]
            output.append({
                "seed": seed,
                "epoch": epoch,
                "step": local_step + 1,
                "steps_in_epoch": 40,
                "primary_occurrence_indices": indices,
                "primary_group_ids": groups,
                "auxiliary_anchor_batch_slots": aux_slots,
                "active_auxiliary_count": len(aux_slots),
                "auxiliary_order": "ascending primary batch order; source role is arm payload only",
            })
    return output


def validate(primary: list[dict[str, Any]], rows: list[dict[str, Any]], seeds: list[int]) -> None:
    require(len(primary) == 10_000, "Q common primary count must be 10000")
    require(all(row.get("occurrence_index") == i for i, row in enumerate(primary)),
            "Q primary indices are not dense and ordered")
    require(all(row.get("source_partition") == "train" for row in primary),
            "non-training primary row in the common stream")
    require(all(row.get("role") == ("anchor" if i % 2 == 0 else "fact_flip")
                for i, row in enumerate(primary)), "Q anchor/fact occurrence layout changed")
    require(len(rows) == 360, "Q schedule must contain 360 rows")
    for seed in seeds:
        for epoch in (1, 2, 3):
            block = sorted((r for r in rows if r["seed"] == seed and r["epoch"] == epoch),
                           key=lambda r: r["step"])
            require(len(block) == 40 and [r["step"] for r in block] == list(range(1, 41)),
                    f"Q schedule block mismatch at {seed}/{epoch}")
            seen_primary = [idx for row in block for idx in row["primary_occurrence_indices"]]
            seen_aux = [idx for row in block for idx in row["auxiliary_anchor_batch_slots"]]
            require(sorted(seen_primary) == list(range(10_000)), f"primary coverage mismatch {seed}/{epoch}")
            require(sorted(seen_aux) == list(range(5_000)), f"auxiliary coverage mismatch {seed}/{epoch}")
            for row in block:
                ids = row["primary_occurrence_indices"]
                expected_aux = [primary[idx]["occurrence_index"] // 2 for idx in ids
                                if primary[idx]["role"] == "anchor"]
                require(row["primary_group_ids"] == [primary[idx]["group_id"] for idx in ids],
                        f"group/index mismatch {seed}/{epoch}/{row['step']}")
                require(row["auxiliary_anchor_batch_slots"] == expected_aux
                        and row["active_auxiliary_count"] == len(expected_aux),
                        f"auxiliary placement mismatch {seed}/{epoch}/{row['step']}")
                expected_count = 16 if row["step"] == 40 else 256
                require(len(ids) == expected_count, f"batch boundary mismatch {seed}/{epoch}/{row['step']}")


def main() -> int:
    require(sha256_file(RUN_CONTRACT) == EXPECTED["run_contract"], "Q run contract hash mismatch")
    require(sha256_file(ANALYSIS_CONTRACT) == EXPECTED["analysis_contract"], "Q analysis contract hash mismatch")
    require(sha256_file(SOURCE_LOCK) == EXPECTED["source_lock"], "Q source-lock hash mismatch")
    require(sha256_file(ADDENDUM) == EXPECTED["addendum"], "Q execution addendum hash mismatch")
    lock = read_json(SOURCE_LOCK)
    require(len(lock["entries"]) > 0, "Q source lock is empty")
    primary_entry = next(row for row in lock["entries"] if row["sha256"] == EXPECTED["primary"])
    primary_path = Path(primary_entry["path"])
    require(primary_path.is_file() and sha256_file(primary_path) == EXPECTED["primary"],
            "Q primary stream source is absent or changed")
    primary = read_jsonl(primary_path)
    arms: dict[str, list[dict[str, Any]]] = {}
    for arm in ("B-DUP", "B-MATCHED", "B-SHAM"):
        entry = next((row for row in lock["entries"] if row["sha256"] == EXPECTED[arm]), None)
        require(entry is not None, f"Q source lock lacks {arm} event manifest")
        path = Path(entry["path"])
        require(path.is_file() and sha256_file(path) == EXPECTED[arm], f"Q arm manifest changed: {arm}")
        rows = read_jsonl(path)
        require(len(rows) == 15_000, f"Q arm manifest row count mismatch: {arm}")
        for i, common in enumerate(primary):
            row = rows[i]
            require(row.get("event_kind") == "primary" and row.get("occurrence_index") == i
                    and row.get("group_id") == common["group_id"]
                    and row.get("source_episode_id") == common["episode_id"]
                    and row.get("target_hash") == common["target_hash"]
                    and row.get("candidate_order_hash") == common["candidate_order_hash"]
                    and row.get("candidate_semantic_ids") == common["candidate_semantic_ids"],
                    f"Q shared primary stream differs in {arm} row {i}")
        expected_role = {"B-DUP": "anchor_duplicate", "B-MATCHED": "matched_neutral",
                         "B-SHAM": "certified_sham"}[arm]
        auxiliary = rows[10_000:]
        require(all(row.get("event_kind") == "auxiliary" and row.get("batch_slot") == slot
                    and row.get("auxiliary_source_role") == expected_role
                    and row.get("loss_weight") == 1.0
                    for slot, row in enumerate(auxiliary)), f"Q auxiliary identity/role mismatch: {arm}")
        arms[arm] = rows
    for arm in ("B-MATCHED", "B-SHAM"):
        for i in range(10_000):
            fields = ("group_id", "source_episode_id", "target_hash", "candidate_order_hash",
                      "candidate_semantic_ids", "target")
            require(all(arms[arm][i].get(field) == arms["B-DUP"][i].get(field) for field in fields),
                    f"common primary payload differs in {arm} row {i}")
    aux_hashes = {
        arm: [row.get("target_hash") for row in arms[arm][10_000:]]
        for arm in ("B-DUP", "B-MATCHED", "B-SHAM")
    }
    require(aux_hashes["B-DUP"] == aux_hashes["B-MATCHED"] == aux_hashes["B-SHAM"],
            "Q auxiliary target sequence differs across frozen treatment manifests")
    run = read_json(RUN_CONTRACT)
    analysis = read_json(ANALYSIS_CONTRACT)
    seeds = run["paired_design"]["seeds"]
    require(len(seeds) == 3 and run["paired_design"]["runs"] == 12, "Q run cardinality mismatch")
    addendum = read_json(ADDENDUM)
    require(addendum["resolution"]["checkpoint_steps"] == [40, 80, 100, 120]
            and addendum["resolution"]["trained_checkpoints_total"] == 48
            and addendum["schedule_algorithm"]["rows"] == 360,
            "Q execution addendum sparse-schedule identity mismatch")
    require(analysis["analysis_cells"] == {"trained": 48, "initialization_baselines": 3,
                                          "total": 51, "rows_per_cell": 8000,
                                          "prediction_rows": 408000}, "Q analysis cell schema mismatch")
    schedule = [row for seed in seeds for row in schedule_for_seed(primary, seed)]
    validate(primary, schedule, seeds)
    encoded = b"".join(canonical_json(row) for row in schedule)
    again = b"".join(canonical_json(row) for seed in seeds for row in schedule_for_seed(primary, seed))
    require(encoded == again, "independent deterministic Q schedule replay differs")
    require(not OUTPUT_ROOT.exists(), f"Q schedule output already exists: {OUTPUT_ROOT}")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    schedule_path = OUTPUT_ROOT / "fixed-schedule.jsonl"
    schedule_path.write_bytes(encoded)
    schedule_hash = sha256_file(schedule_path)
    require(schedule_hash == hashlib.sha256(encoded).hexdigest(), "Q schedule durable hash mismatch")
    addendum_hash = sha256_file(ADDENDUM)
    source_hash = sha256_file(Path(__file__).resolve())
    manifest = {
        "status": "Q_SPARSE_SCHEDULE_VALIDATED_PRE_INITIALIZATION",
        "schedule_sha256": schedule_hash,
        "schedule_rows": len(schedule),
        "seeds": seeds,
        "arms": list(ARMS),
        "steps_per_epoch": 40,
        "total_steps_per_run": 120,
        "checkpoint_steps": [40, 80, 100, 120],
        "trained_checkpoints": 48,
        "initialization_templates": 3,
        "sealed_model_states_total": 51,
        "primary_manifest_sha256": EXPECTED["primary"],
        "arm_manifest_sha256": {arm: EXPECTED[arm] for arm in ("B-DUP", "B-MATCHED", "B-SHAM")},
        "sham_low_source": {"manifest_sha256": EXPECTED["B-SHAM"],
                             "identity_sequence_sha256": hashlib.sha256(
                                 "".join(aux_hashes["B-SHAM"]).encode("ascii")).hexdigest(),
                             "loss_multiplier": 0.5},
        "addendum_sha256": addendum_hash,
        "materializer_sha256": source_hash,
        "panel_opened": False,
        "head_initialized": False,
        "training": False,
        "evaluation": False,
    }
    manifest_path = OUTPUT_ROOT / "fixed-schedule-manifest.json"
    manifest_path.write_bytes(canonical_json(manifest))
    seal = {
        "status": "Q_SPARSE_SCHEDULE_SEALED_PRE_INITIALIZATION",
        "schedule_sha256": schedule_hash,
        "schedule_manifest_sha256": sha256_file(manifest_path),
        "addendum_sha256": addendum_hash,
        "materializer_sha256": source_hash,
        "independent_reconstruction": "BYTE_IDENTICAL",
        "schedule_rows": len(schedule),
        "head_initialized": False,
        "training": False,
        "panel_read": False,
        "inference": False,
    }
    seal_path = OUTPUT_ROOT / "schedule-seal.json"
    seal_path.write_bytes(canonical_json(seal))
    print(json.dumps({"status": seal["status"], "schedule_sha256": schedule_hash,
                      "rows": len(schedule), "addendum_sha256": addendum_hash,
                      "head_initialized": False, "training": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
