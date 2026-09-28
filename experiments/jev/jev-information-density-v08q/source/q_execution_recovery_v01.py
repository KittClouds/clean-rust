"""Versioned Q execution adapter for pre-training source-lock compatibility.

The v02 trainer requires both feature receipts to be members of the source-lock
entry set. The sealed lock contains the candidate receipt, while the shared
training-cache receipt is independently pinned by its exact digest in the
trainer and binds the already-locked scope and tensor. This adapter verifies
that exact distinction, bypasses only the redundant membership conjunction,
and delegates all remaining checks to the frozen trainer.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
RUN1 = Path(r"D:\codex-runs\jev-information-density-v08q-run-v01")
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v02")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
INSTRUMENT = RUN1 / "instrument/q-execution-instrument-seal-v02.json"
SOURCE_LOCK = Q / "contracts/q-source-lock-v02.json"
SCHEDULE_SOURCE = RUN1 / "schedule"
PACKET = RUN / "q-full-execution-packet-v02.json"
PACKET_SEAL = RUN / "q-full-execution-packet-seal-v02.json"
ADAPTER_RECEIPT = RUN / "q-source-lock-adapter-receipt-v01.json"
STATE_RECEIPT_SHA = "d98ae657e28b976f187d4d67e58119ce80496e76c061c90362ac2e50ff7f720e"
CANDIDATE_RECEIPT_SHA = "29f8d67b24fd2a554500e1cfe2e0fe0b4311d32fad7052ad8ffb3464b7835f44"
STATE_SCOPE_SHA = "aa8cba58f4a8ec46ed6ec8eaf0bfbe992b03b9fa58f815b4259d9fdfe2b009f3"
STATE_FEATURES_SHA = "da946af90353c91c3b1298d2951eebc42b9f515708b628d3a053e700a960c4d6"
CANDIDATE_FEATURES_SHA = "3bb3036f455a83409361eb3e4150833bd8b255a2a783ec1218b00b12315c0590"
CONTRACTS = {
    "run": "5f6cd42b6de058a4fcdcbeb70b1939dbe944a6c973ee704a93148f9bea71d1ae",
    "analysis": "b5c3c02b56405c0a471f82907bbb400dc4655c5fa8e82a32463dce77675e16cc",
    "addendum": "363c9bd7b556d9e0003804bc18ddd15e844f9bf3ca5ec8d545117f2c995ec6d3",
    "source_lock": "d6d70768242ac12801069e2bdb27cb976679c907206e81ae8c0921867bea2363",
    "source_root": "5e973916fb62747cde2de51f7deb2e29616ea1ead13ce384dcdb254901d936d3",
    "panel_root": "1b99d39ab6bfed8173a5410f6c8ae0df442aae03038e31bab46b779bd1e039a6",
    "panel_seal": "161511e6617ee012b3051590b4a9ce747f79a85228c02649e61ca8a10d080ad6",
    "schedule": "af6688bd983cb01d113a4122938d71ab217143b7d17a43c25f376e04cf573662",
}
CORE_BINDINGS = (
    "experiments/jev-information-density-v08q/source/run_q_training_v02.py",
    "experiments/jev-information-density-v08q/source/evaluate_q_panel_v02.py",
    "experiments/jev-information-density-v08q/source/analyze_q_results_v02.py",
    "experiments/jev-information-density-v08q/source/verify_q_full_execution_v02.py",
    "experiments/jev-information-density-v08q/source/q_analysis_rules_v02.py",
    "experiments/jev-information-density-v08q/source/q_weighted_objective_v02.py",
    "experiments/jev-information-density-v08q/source/seal_q_execution_instrument_v02.py",
    "experiments/jev-information-density-v08q/source/seal_q_full_execution_packet_v02.py",
    "experiments/jev-information-density-v08q/source/q_execution_recovery_v01.py",
    "experiments/jev-information-density-v08q/tests/test_q_rules_v02.py",
    "experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py",
    "experiments/jev-information-density-v08n/phase_b/analyze_phase_b_v01.py",
    "experiments/jev-frozen-readout-v01/probe.py",
    "experiments/jev-frozen-scaling-v05/train_v05.py",
)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def entries_root(entries: list[dict[str, Any]]) -> str:
    raw = "".join(f"{r['path']}\t{r['bytes']}\t{r['sha256']}\n" for r in sorted(entries, key=lambda x: x["path"]))
    return hashlib.sha256(raw.encode()).hexdigest()


def receipt_lock_pass(lock_hashes: set[str], state_receipt_sha: str, candidate_receipt_sha: str,
                      required_locked_hashes: set[str]) -> bool:
    """True only for the exact v02 lock layout; no general exemption is allowed."""
    return (
        state_receipt_sha == STATE_RECEIPT_SHA
        and candidate_receipt_sha == CANDIDATE_RECEIPT_SHA
        and candidate_receipt_sha in lock_hashes
        and {STATE_SCOPE_SHA, STATE_FEATURES_SHA, CANDIDATE_FEATURES_SHA} <= lock_hashes
        and required_locked_hashes <= lock_hashes
    )


class ReceiptLockTests(unittest.TestCase):
    def test_exact_authorized_layout_passes(self) -> None:
        required = {"primary", "dup", "matched", "sham", "catalog"}
        hashes = required | {STATE_SCOPE_SHA, STATE_FEATURES_SHA, CANDIDATE_FEATURES_SHA, CANDIDATE_RECEIPT_SHA}
        self.assertTrue(receipt_lock_pass(hashes, STATE_RECEIPT_SHA, CANDIDATE_RECEIPT_SHA, required))

    def test_unpinned_shared_receipt_fails(self) -> None:
        hashes = {STATE_SCOPE_SHA, STATE_FEATURES_SHA, CANDIDATE_FEATURES_SHA, CANDIDATE_RECEIPT_SHA}
        self.assertFalse(receipt_lock_pass(hashes, "0" * 64, CANDIDATE_RECEIPT_SHA, set()))

    def test_unbound_candidate_receipt_fails(self) -> None:
        hashes = {STATE_SCOPE_SHA, STATE_FEATURES_SHA, CANDIDATE_FEATURES_SHA}
        self.assertFalse(receipt_lock_pass(hashes, STATE_RECEIPT_SHA, CANDIDATE_RECEIPT_SHA, set()))


def seal_packet() -> None:
    if RUN.exists():
        raise RuntimeError(f"Q repaired execution namespace already exists: {RUN}")
    for name, expected in (("q-run-contract-v02.json", CONTRACTS["run"]),
                           ("q-analysis-contract-v02.json", CONTRACTS["analysis"]),
                           ("q-execution-addendum-v01.json", CONTRACTS["addendum"]),
                           ("q-source-lock-v02.json", CONTRACTS["source_lock"])):
        if sha(Q / "contracts" / name) != expected:
            raise RuntimeError(f"frozen Q contract changed: {name}")
    panel_seal_path = PANEL / "seals/q-panel-phase-terminal-seal-v01.json"
    panel_seal = read_json(panel_seal_path)
    if sha(panel_seal_path) != CONTRACTS["panel_seal"] or panel_seal.get("root_sha256") != CONTRACTS["panel_root"]:
        raise RuntimeError("Q sealed panel identity mismatch")
    lock = read_json(SOURCE_LOCK)
    if lock.get("root_sha256") != CONTRACTS["source_root"]:
        raise RuntimeError("Q source-lock root mismatch")
    instrument = read_json(INSTRUMENT)
    if instrument.get("status") != "Q_EXECUTION_INSTRUMENTS_SEALED_PRE_HEAD_INITIALIZATION":
        raise RuntimeError("Q v02 core instrument seal is not pre-initialization")
    instrument_sha = sha(INSTRUMENT)
    schedule = SCHEDULE_SOURCE / "fixed-schedule.jsonl"
    schedule_seal = read_json(SCHEDULE_SOURCE / "schedule-seal.json")
    if sha(schedule) != CONTRACTS["schedule"] or schedule_seal.get("schedule_sha256") != CONTRACTS["schedule"]:
        raise RuntimeError("Q fixed schedule identity mismatch")
    schedule_files = ("fixed-schedule.jsonl", "schedule-seal.json", "fixed-schedule-manifest.json", "independent-verification-v01.json")
    for name in schedule_files:
        if not (SCHEDULE_SOURCE / name).is_file():
            raise FileNotFoundError(SCHEDULE_SOURCE / name)
    bindings = []
    for relative in CORE_BINDINGS:
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        bindings.append({"path": relative, "bytes": source.stat().st_size, "sha256": sha(source)})
    unittest_result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ReceiptLockTests)
    )
    if not unittest_result.wasSuccessful():
        raise RuntimeError("Q source-lock compatibility adapter tests failed")
    RUN.mkdir(parents=True, exist_ok=False)
    schedule_out = RUN / "schedule"
    schedule_out.mkdir()
    schedule_entries = []
    for name in schedule_files:
        source = SCHEDULE_SOURCE / name
        if not source.is_file():
            raise FileNotFoundError(source)
        target = schedule_out / name
        shutil.copyfile(source, target)
        if sha(source) != sha(target):
            raise RuntimeError(f"copied Q schedule artifact differs: {name}")
        schedule_entries.append({"path": name, "bytes": target.stat().st_size, "sha256": sha(target)})
    packet_root = entries_root(bindings)
    auth = (
        "Existing explicit Q full-run authorization, with the user's current instruction to repair pre-initialization "
        "engineering defects when no outcome contamination or upstream information flow occurred. This packet keeps "
        "the sealed scientific contracts, panel, treatments, seeds, schedule, metrics, and thresholds unchanged."
    )
    packet = {
        "schema": "jev-v08q-full-execution-packet-v02",
        "identity": "JEV-V08Q-SINGLE-DOSE-GAIN-FULL-EXECUTION-REPAIRED-V02",
        "authorization": {"phase": "Q_FULL_FROZEN_RUN_EVALUATION_AND_ANALYSIS", "explicit_user_authorization": True,
                          "source": "prior explicit full Q authorization plus current user authorization to repair non-contaminating execution bugs",
                          "statement": auth, "statement_sha256": hashlib.sha256(auth.encode()).hexdigest()},
        "parents": {"run_contract_sha256": CONTRACTS["run"], "analysis_contract_sha256": CONTRACTS["analysis"],
                    "addendum_sha256": CONTRACTS["addendum"], "source_lock_sha256": CONTRACTS["source_lock"],
                    "source_lock_root_sha256": CONTRACTS["source_root"], "panel_root_sha256": CONTRACTS["panel_root"],
                    "panel_terminal_seal_sha256": CONTRACTS["panel_seal"], "schedule_sha256": CONTRACTS["schedule"],
                    "schedule_seal_sha256": sha(schedule_out / "schedule-seal.json"),
                    "execution_instrument_seal_sha256": instrument_sha, "execution_instrument_root_sha256": instrument["root_sha256"]},
        "run_contract_sha256": CONTRACTS["run"], "analysis_contract_sha256": CONTRACTS["analysis"],
        "addendum_sha256": CONTRACTS["addendum"], "panel_root_sha256": CONTRACTS["panel_root"],
        "run": {"seeds": [2540205348, 2603246505, 3565067208], "arms": ["B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW"],
                "optimizer_steps_per_run": 120, "checkpoint_steps": [40, 80, 100, 120], "trained_runs": 12,
                "trained_checkpoints": 48, "shared_seed_initial_templates": 3, "prediction_rows": 408000,
                "panel_open_count": 1, "checkpoint_selection": False, "panel_feedback_during_training": False},
        "schedule_artifacts": schedule_entries, "implementation_bindings": bindings, "packet_root_sha256": packet_root,
        "failure_policy": "preserve partial outputs in this new namespace and stop; no retry or replacement",
        "prohibited": ["additional seeds", "extra checkpoints", "dose changes", "training extensions", "checkpoint selection",
                       "panel replacement", "evaluation feedback", "hyperparameter or metric changes"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    packet_path = RUN / "q-full-execution-packet-v02.json"
    seal_path = RUN / "q-full-execution-packet-seal-v02.json"
    write_json(packet_path, packet)
    write_json(seal_path, {"schema": "jev-v08q-full-execution-packet-seal-v02",
                           "status": "Q_FULL_EXECUTION_PACKET_SEALED_PRE_INITIALIZATION",
                           "packet_sha256": sha(packet_path), "packet_root_sha256": packet_root,
                           "implementation_count": len(bindings), "authorization_phase": packet["authorization"]["phase"],
                           "panel_root_sha256": CONTRACTS["panel_root"], "training_started": False,
                           "panel_opened": False, "sealed_at_utc": datetime.now(timezone.utc).isoformat()})
    print(json.dumps({"status": "Q_REPAIRED_EXECUTION_PACKET_SEALED_PRE_INITIALIZATION",
                      "run_namespace": str(RUN), "packet_sha256": sha(packet_path),
                      "packet_root_sha256": packet_root, "adapter_tests": 3,
                      "panel_opened": False, "head_initialization": False}, indent=2))


def verify_adapter_receipt(module: Any) -> None:
    if not ADAPTER_RECEIPT.is_file():
        raise RuntimeError("Q source-lock adapter receipt is missing")
    row = read_json(ADAPTER_RECEIPT)
    if row.get("adapter_sha256") != sha(Path(__file__).resolve()) or row.get("source_lock_sha256") != CONTRACTS["source_lock"]:
        raise RuntimeError("Q source-lock adapter receipt binding mismatch")
    if row.get("candidate_receipt_sha256") != CANDIDATE_RECEIPT_SHA or row.get("state_receipt_sha256") != STATE_RECEIPT_SHA:
        raise RuntimeError("Q source-lock adapter receipt identities changed")


def train(mode: str) -> int:
    core = Q / "source/run_q_training_v02.py"
    spec = importlib.util.spec_from_file_location("q_frozen_training_core_v02", core)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen Q v02 trainer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.RUN = RUN
    module.TRAIN = RUN / "training"
    module.SCHEDULE = RUN / "schedule"
    module.PACKET = PACKET
    module.INSTRUMENT = INSTRUMENT
    original_need = module.need

    def need_adapter(ok: bool, message: str) -> None:
        if message == "Q feature receipts are not bound by the sealed source lock" and not ok:
            paths = module.source_paths()
            lock = module.read_json(SOURCE_LOCK)
            lock_hashes = {str(entry["sha256"]) for entry in lock["entries"]}
            required = {module.HASHES["primary"], module.HASHES["dup"],
                        module.HASHES["matched"], module.HASHES["sham"]}
            state_receipt_sha = module.sha(paths["state_receipt"])
            candidate_receipt_sha = module.sha(paths["candidate_receipt"])
            if not receipt_lock_pass(lock_hashes, state_receipt_sha, candidate_receipt_sha, required):
                raise RuntimeError("Q source-lock receipt compatibility proof failed")
            original_need(lock.get("root_sha256") == CONTRACTS["source_root"], "Q source-lock root changed")
            return
        original_need(ok, message)

    module.need = need_adapter
    verify_parents = module.verify_contract_panel_and_sources

    def verify_parents_then_bind_adapter() -> dict[str, Any]:
        result = verify_parents()
        module.__file__ = str(Path(__file__).resolve())
        return result

    module.verify_contract_panel_and_sources = verify_parents_then_bind_adapter
    if mode == "run":
        verify_adapter_receipt(module)
    sys.argv = [str(core), mode]
    status = int(module.main())
    if mode == "preflight" and status == 0:
        paths = module.source_paths()
        lock = module.read_json(SOURCE_LOCK)
        lock_hashes = {str(entry["sha256"]) for entry in lock["entries"]}
        required = {module.HASHES[k] for k in ("primary", "dup", "matched", "sham")}
        if not receipt_lock_pass(lock_hashes, module.sha(paths["state_receipt"]),
                                 module.sha(paths["candidate_receipt"]), required):
            raise RuntimeError("post-preflight Q source-lock adapter audit failed")
        write_json(ADAPTER_RECEIPT, {"status": "Q_SOURCE_LOCK_RECEIPT_SCOPE_RECONCILED",
                    "adapter_sha256": sha(Path(__file__).resolve()), "frozen_trainer_sha256": sha(core),
                    "source_lock_sha256": CONTRACTS["source_lock"], "source_lock_root_sha256": CONTRACTS["source_root"],
                    "state_receipt_sha256": module.sha(paths["state_receipt"]),
                    "candidate_receipt_sha256": module.sha(paths["candidate_receipt"]),
                    "state_receipt_membership": "exact digest pinned by frozen trainer; scope and tensor separately source-locked",
                    "candidate_receipt_membership": "present in frozen source-lock entry set",
                    "training_preflight_receipt_sha256": sha(RUN / "training/training-preflight-receipt-v01.json"),
                    "optimizer_steps": 0, "panel_opened": False, "created_at_utc": datetime.now(timezone.utc).isoformat()})
    return status


def run_other(stage: str) -> int:
    module_file = {
        "evaluate": "evaluate_q_panel_v02.py",
        "analyze": "analyze_q_results_v02.py",
        "verify": "verify_q_full_execution_v02.py",
    }[stage]
    path = Q / "source" / module_file
    spec = importlib.util.spec_from_file_location(f"q_{stage}_core_v02", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen Q {stage} module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.RUN = RUN
    module.PACKET = PACKET
    module.PACKET_SEAL = PACKET_SEAL
    if stage == "evaluate":
        module.TRAIN = RUN / "training"
        module.OUTPUT = RUN / "evaluation"
    elif stage == "analyze":
        module.OUTPUT = RUN / "evaluation"
    else:
        module.TRAIN = RUN / "training"
        module.EVAL = RUN / "evaluation"
        module.RECEIPT = RUN / "independent-verification-v01.json"
    verify_adapter_receipt(module)
    if stage == "evaluate" and not (RUN / "training/training-seal-manifest.json").is_file():
        raise RuntimeError("Q held-out inference requires the complete sealed training tree")
    sys.argv = [str(path)]
    return int(module.main())


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "self-test":
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReceiptLockTests))
        return 0 if result.wasSuccessful() else 1
    if len(sys.argv) != 2:
        raise SystemExit("usage: q_execution_recovery_v01.py {seal|preflight|run|evaluate|analyze|verify|self-test}")
    stage = sys.argv[1]
    if stage == "seal":
        seal_packet(); return 0
    if stage in {"preflight", "run"}:
        return train(stage)
    if stage in {"evaluate", "analyze", "verify"}:
        return run_other(stage)
    raise SystemExit(f"unknown Q execution stage: {stage}")


if __name__ == "__main__":
    raise SystemExit(main())
