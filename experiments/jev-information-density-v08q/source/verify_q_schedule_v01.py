"""Clean-process verification of the sealed Q schedule and its training inputs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
Q_ROOT = ROOT / "experiments/jev-information-density-v08q"
SCHEDULE_ROOT = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01\schedule")
RUN_CONTRACT = Q_ROOT / "contracts/q-run-contract-v02.json"
ANALYSIS_CONTRACT = Q_ROOT / "contracts/q-analysis-contract-v02.json"
SOURCE_LOCK = Q_ROOT / "contracts/q-source-lock-v02.json"
ADDENDUM = Q_ROOT / "contracts/q-execution-addendum-v01.json"
MATERIALIZER = Q_ROOT / "source/materialize_q_schedule_v01.py"
RECEIPT = SCHEDULE_ROOT / "independent-verification-v01.json"
EXPECTED = {
    "run_contract": "5f6cd42b6de058a4fcdcbeb70b1939dbe944a6c973ee704a93148f9bea71d1ae",
    "analysis_contract": "b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc",
    "source_lock": "d6d70768242ac12801069e2bdb27cb976679c907206e81ae8c0921867bea2363",
    "addendum": "363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3",
    "schedule_algorithm_source": "831fdd1a44420bd251ba7fd52b3d3fa72d824fed8cabbd4b15c75c42c6232b1d",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("q_schedule_materializer_clean_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import frozen Q schedule materializer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    for key, path in (("run_contract", RUN_CONTRACT), ("analysis_contract", ANALYSIS_CONTRACT),
                      ("source_lock", SOURCE_LOCK), ("addendum", ADDENDUM)):
        if sha256_file(path) != EXPECTED[key]:
            raise RuntimeError(f"Q schedule parent hash mismatch: {key}")
    materializer_hash = sha256_file(MATERIALIZER)
    source = load_module(MATERIALIZER)
    seal_path = SCHEDULE_ROOT / "schedule-seal.json"
    manifest_path = SCHEDULE_ROOT / "fixed-schedule-manifest.json"
    schedule_path = SCHEDULE_ROOT / "fixed-schedule.jsonl"
    seal, manifest = read_json(seal_path), read_json(manifest_path)
    if seal.get("status") != "Q_SPARSE_SCHEDULE_SEALED_PRE_INITIALIZATION":
        raise RuntimeError("Q schedule seal status mismatch")
    if seal.get("schedule_sha256") != sha256_file(schedule_path):
        raise RuntimeError("Q schedule bytes differ from schedule seal")
    if seal.get("schedule_manifest_sha256") != sha256_file(manifest_path):
        raise RuntimeError("Q schedule manifest differs from schedule seal")
    if seal.get("addendum_sha256") != EXPECTED["addendum"]:
        raise RuntimeError("Q schedule seal does not bind the cadence addendum")
    if manifest.get("materializer_sha256") != materializer_hash:
        raise RuntimeError("Q materializer source differs from schedule manifest")
    if manifest.get("checkpoint_steps") != [40, 80, 100, 120] or manifest.get("trained_checkpoints") != 48:
        raise RuntimeError("Q schedule manifest does not describe the sparse analysis matrix")
    lock = read_json(SOURCE_LOCK)
    primary_entry = next(row for row in lock["entries"] if row["sha256"] == source.EXPECTED["primary"])
    primary_path = Path(primary_entry["path"])
    if sha256_file(primary_path) != source.EXPECTED["primary"]:
        raise RuntimeError("Q common primary stream changed after schedule sealing")
    primary = read_jsonl(primary_path)
    saved_bytes = schedule_path.read_bytes()
    saved_rows = read_jsonl(schedule_path)
    seeds = read_json(RUN_CONTRACT)["paired_design"]["seeds"]
    source.validate(primary, saved_rows, seeds)
    rebuilt = b"".join(source.canonical_json(row)
                      for seed in seeds for row in source.schedule_for_seed(primary, seed))
    if rebuilt != saved_bytes:
        raise RuntimeError("clean-process Q schedule reconstruction is not byte-identical")
    if RECEIPT.exists():
        raise FileExistsError(f"Q schedule verification receipt already exists: {RECEIPT}")
    receipt = {
        "status": "Q_SPARSE_SCHEDULE_CLEAN_PROCESS_VERIFICATION_PASS",
        "schedule_sha256": sha256_file(schedule_path),
        "schedule_rows": len(saved_rows),
        "schedule_manifest_sha256": sha256_file(manifest_path),
        "schedule_seal_sha256": sha256_file(seal_path),
        "materializer_sha256": materializer_hash,
        "materializer_parent_algorithm_sha256": EXPECTED["schedule_algorithm_source"],
        "addendum_sha256": EXPECTED["addendum"],
        "primary_manifest_sha256": source.EXPECTED["primary"],
        "clean_process_reconstruction": "BYTE_IDENTICAL",
        "optimizer_steps_per_run": 120,
        "trained_checkpoints": 48,
        "shared_initial_templates": 3,
        "head_initialized": False,
        "training": False,
        "panel_opened": False,
        "evaluation": False,
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
