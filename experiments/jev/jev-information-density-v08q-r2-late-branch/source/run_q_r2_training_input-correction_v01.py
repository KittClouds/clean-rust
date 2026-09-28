"""Versioned adapter for the identity-only/common-primary manifest seam.

The sealed common-primary manifest intentionally contains occurrence identities
and target hashes, while the separately sealed B-SHAM head-input manifest
contains the corresponding target vectors and candidate indices.  The frozen
trainer expects a materialized primary payload.  This adapter joins those two
already-bound sources by exact occurrence identity and validates every joined
field before delegating to the unchanged trainer.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
TRAIN = RUN / "training-v01"
PROVENANCE = RUN / "provenance"
TRAINER = EXP / "source/run_q_r2_training_v01.py"
CORRECTION_RECEIPT = PROVENANCE / "q-r2-training-input-correction-preflight-v01.json"
FAILURE_RECEIPT = PROVENANCE / "q-r2-training-input-correction-failure-v01.json"
COMPLETION_RECEIPT = PROVENANCE / "q-r2-training-input-correction-completion-v01.json"
EXPECTED_TRAINER_SHA256 = "2991a27c68985e5fcb64facf9bb15afdb881c2b22ffc4145f6ad2c27da2839d0"
EXPECTED_PRIMARY_SHA256 = "773119294a51aa46487de26f9f253355187a7bfd1e75cb2f258c307c86f10b06"
EXPECTED_SHAM_SHA256 = "9dd346766856f56006be326c171e664dcbab23983cdd7501f480b6fabb6ff895"
EXPECTED_CATALOG_SHA256 = "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e"
EXPECTED_RUN_CONTRACT_SHA256 = "52d093a00076700ed24bfe0e2cc33ada73dfc07d073b39cbdbe52103aef525e6"
EXPECTED_TARGET_HASH_ALGORITHM = "SHA256(canonical JSON: sort_keys=true, separators=(',', ':'), ensure_ascii=false)"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_target_hash(target: Any) -> str:
    payload = json.dumps(target, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def enrich_primary(identity_rows: list[dict[str, Any]], payload_rows: list[dict[str, Any]], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    require(len(identity_rows) == 10_000 and len(payload_rows) == 15_000, "bound training manifest row count mismatch")
    require(catalog.get("feature_dimension") == 2048 and len(catalog.get("rows", [])) == 48,
            "bound candidate catalog contract mismatch")
    semantic_ids_by_index = [row["candidate_semantic_id"] for row in catalog["rows"]]
    require(len(set(semantic_ids_by_index)) == 48, "candidate catalog semantic IDs are not unique")
    primary_payloads = payload_rows[:10_000]
    require(all(row.get("event_kind") == "primary" and row.get("arm") == "B-SHAM" for row in primary_payloads),
            "B-SHAM primary payload segment identity mismatch")

    joined: list[dict[str, Any]] = []
    for index, (identity, payload) in enumerate(zip(identity_rows, primary_payloads, strict=True)):
        expected = {
            "occurrence_index": index,
            "group_id": identity.get("group_id"),
            "source_episode_id": identity.get("episode_id"),
            "target_hash": identity.get("target_hash"),
            "candidate_order_hash": identity.get("candidate_order_hash"),
            "candidate_semantic_ids": identity.get("candidate_semantic_ids"),
            "feature_scope_index": identity.get("feature_scope_index"),
        }
        for key, value in expected.items():
            require(payload.get(key) == value, f"common-primary identity join mismatch at row {index}/{key}")

        target = payload.get("target")
        require(isinstance(target, list) and len(target) == 4 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in target),
                f"primary target vector malformed at row {index}")
        require(abs(sum(target) - 1.0) <= 1e-12, f"primary target not normalized at row {index}")
        require(canonical_target_hash(target) == identity.get("target_hash"), f"primary target hash mismatch at row {index}")

        indices = payload.get("candidate_indices")
        ids = identity.get("candidate_semantic_ids")
        require(isinstance(indices, list) and len(indices) == 4 and all(type(value) is int for value in indices),
                f"primary candidate indices malformed at row {index}")
        require(all(0 <= value < len(semantic_ids_by_index) for value in indices),
                f"primary candidate index outside catalog at row {index}")
        require([semantic_ids_by_index[value] for value in indices] == ids,
                f"primary candidate index/semantic identity mismatch at row {index}")

        materialized = dict(identity)
        materialized["source_episode_id"] = identity["episode_id"]
        materialized["target"] = target
        materialized["candidate_indices"] = indices
        joined.append(materialized)
    return joined


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("q_r2_frozen_trainer_under_input_adapter", path)
    require(spec is not None and spec.loader is not None, "cannot load frozen trainer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def install_join_adapter(module: Any) -> dict[str, Any]:
    require(sha(TRAINER) == EXPECTED_TRAINER_SHA256, "frozen trainer identity mismatch")
    identity_path = module.INPUT / "common-primary-occurrence-manifest.jsonl"
    sham_path = module.INPUT / "head-input-manifest-B-SHAM.jsonl"
    catalog_path = module.INPUT / "candidate-catalog.json"
    require(sha(identity_path) == EXPECTED_PRIMARY_SHA256, "common-primary source identity mismatch")
    require(sha(sham_path) == EXPECTED_SHAM_SHA256, "B-SHAM source identity mismatch")
    require(sha(catalog_path) == EXPECTED_CATALOG_SHA256, "candidate catalog source identity mismatch")

    original_reader = module.read_jsonl
    original_read_json = module.read_json
    resolved_identity_path = identity_path.resolve()
    resolved_sham_path = sham_path.resolve()
    resolved_catalog_path = catalog_path.resolve()
    join_receipt: dict[str, Any] = {}

    def adapted_reader(path: Path) -> list[dict[str, Any]]:
        rows = original_reader(path)
        if path.resolve() != resolved_identity_path:
            return rows
        payload_rows = original_reader(sham_path)
        catalog = original_read_json(catalog_path)
        materialized = enrich_primary(rows, payload_rows, catalog)
        join_receipt.update({
            "identity_rows": len(rows),
            "payload_manifest_rows": len(payload_rows),
            "joined_primary_rows": len(materialized),
            "target_hash_verified_rows": len(materialized),
            "candidate_order_verified_rows": len(materialized),
            "identity_source_sha256": sha(identity_path),
            "payload_source_sha256": sha(sham_path),
            "catalog_source_sha256": sha(catalog_path),
            "join_key": "occurrence_index + group_id + episode_id + feature_scope_index",
        })
        return materialized

    module.read_jsonl = adapted_reader
    return {"join_receipt": join_receipt, "resolved_sources": [str(resolved_identity_path), str(resolved_sham_path), str(resolved_catalog_path)]}


def write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def run() -> int:
    preflight = "--preflight" in sys.argv[1:]
    require("--self-test" not in sys.argv[1:], "use the dedicated self-test command for synthetic fixtures")
    module = load_module(TRAINER)
    adapter = install_join_adapter(module)

    if preflight:
        require(not CORRECTION_RECEIPT.exists(), "correction preflight receipt already exists")
        sys.argv = [str(TRAINER), "--preflight"]
        result = module.main()
        require(result == 0 and len(adapter["join_receipt"]) > 0, "corrected training preflight did not pass")
        receipt = {
            "identity": "JEV-V08Q-R2-TRAINING-PRIMARY-PAYLOAD-JOIN-CORRECTION-V01",
            "status": "Q_R2_TRAINING_INPUT_JOIN_PREFLIGHT_PASS_NO_HEAD_INITIALIZATION",
            "frozen_trainer_path": str(TRAINER),
            "frozen_trainer_sha256": sha(TRAINER),
            "adapter_path": str(Path(__file__).resolve()),
            "adapter_sha256": sha(Path(__file__).resolve()),
            "run_contract_sha256": EXPECTED_RUN_CONTRACT_SHA256,
            "target_hash_algorithm": EXPECTED_TARGET_HASH_ALGORITHM,
            "joined_payload": adapter["join_receipt"],
            "join_source_files_read": adapter["resolved_sources"],
            "head_initialized": False,
            "optimizer_steps": 0,
            "panel_opened": False,
            "predictions": False,
            "metrics": False,
        }
        write_new(CORRECTION_RECEIPT, receipt)
        print(json.dumps(receipt, indent=2))
        return 0

    require(CORRECTION_RECEIPT.is_file(), "corrected no-initialization preflight receipt is missing")
    receipt = json.loads(CORRECTION_RECEIPT.read_text(encoding="utf-8"))
    require(receipt.get("status") == "Q_R2_TRAINING_INPUT_JOIN_PREFLIGHT_PASS_NO_HEAD_INITIALIZATION"
            and receipt.get("adapter_sha256") == sha(Path(__file__).resolve())
            and receipt.get("frozen_trainer_sha256") == sha(TRAINER), "corrected training preflight receipt mismatch")
    sys.argv = [str(TRAINER)]
    try:
        result = module.main()
    except BaseException as exc:
        if not FAILURE_RECEIPT.exists():
            write_new(FAILURE_RECEIPT, {
                "identity": "JEV-V08Q-R2-TRAINING-INPUT-JOIN-CORRECTION-FAILURE-V01",
                "status": "Q_R2_TRAINING_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED",
                "exception_type": type(exc).__name__, "exception": str(exc),
                "frozen_trainer_sha256": sha(TRAINER), "adapter_sha256": sha(Path(__file__).resolve()),
                "panel_opened": False, "automatic_retry": False,
            })
        raise
    require(result == 0, "frozen trainer returned nonzero status")
    training_seal = TRAIN / "training-seal-manifest.json"
    checkpoint_tree = TRAIN / "checkpoint-hash-tree.json"
    require(training_seal.is_file() and checkpoint_tree.is_file(), "training seal outputs are incomplete")
    completion = {
        "identity": "JEV-V08Q-R2-TRAINING-INPUT-JOIN-CORRECTION-COMPLETION-V01",
        "status": "Q_R2_TRAINING_COMPLETE_WITH_VERSIONED_INPUT_JOIN_ADAPTER",
        "preflight_receipt_sha256": sha(CORRECTION_RECEIPT),
        "adapter_sha256": sha(Path(__file__).resolve()),
        "frozen_trainer_sha256": sha(TRAINER),
        "training_seal_sha256": sha(training_seal),
        "checkpoint_tree_sha256": sha(checkpoint_tree),
        "head_initialization": True,
        "training_complete": True,
        "panel_opened": False,
        "evaluation": False,
    }
    write_new(COMPLETION_RECEIPT, completion)
    print(json.dumps(completion, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
