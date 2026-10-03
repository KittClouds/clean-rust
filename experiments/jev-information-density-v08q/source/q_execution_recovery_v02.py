"""Q-only source/arm validation adapter; preserves sealed core code and design."""
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
RUN2 = Path(r"D:\codex-runs\jev-information-density-v08q-run-v02")
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-run-v03")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-panel-v02")
SCHEDULE_SOURCE = RUN1 / "schedule"
INSTRUMENT = RUN1 / "instrument/q-execution-instrument-seal-v02.json"
SOURCE_LOCK = Q / "contracts/q-source-lock-v02.json"
PACKET = RUN / "q-full-execution-packet-v02.json"
PACKET_SEAL = RUN / "q-full-execution-packet-seal-v02.json"
ADAPTER_RECEIPT = RUN / "q-execution-adapter-receipt-v02.json"
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
ARMS = {"B-DUP": "anchor_duplicate", "B-MATCHED": "matched_neutral", "B-SHAM": "certified_sham"}
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
    "experiments/jev-information-density-v08q/source/q_execution_recovery_v02.py",
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


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def entries_root(entries: list[dict[str, Any]]) -> str:
    body = "".join(f"{r['path']}\t{r['bytes']}\t{r['sha256']}\n" for r in sorted(entries, key=lambda x: x["path"]))
    return hashlib.sha256(body.encode()).hexdigest()


def receipt_layout_pass(lock_hashes: set[str], state_receipt: str, candidate_receipt: str,
                        required: set[str]) -> bool:
    return (state_receipt == STATE_RECEIPT_SHA and candidate_receipt == CANDIDATE_RECEIPT_SHA
            and candidate_receipt in lock_hashes
            and {STATE_SCOPE_SHA, STATE_FEATURES_SHA, CANDIDATE_FEATURES_SHA} <= lock_hashes
            and required <= lock_hashes)


def auxiliary_payload_pass(rows_by_arm: dict[str, list[dict[str, Any]]]) -> bool:
    if set(rows_by_arm) != set(ARMS) or any(len(rows) != 5_000 for rows in rows_by_arm.values()):
        return False
    common = ("neighborhood_id", "target_source_episode_id", "target_hash", "candidate_order_hash",
              "candidate_semantic_ids", "candidate_indices", "candidate_mask", "candidate_profile",
              "target", "state_feature_dimension", "candidate_feature_dimension", "loss_weight", "normalization")
    for slot in range(5_000):
        selected = {arm: rows_by_arm[arm][slot] for arm in ARMS}
        for arm, role in ARMS.items():
            row = selected[arm]
            if (row.get("arm") != arm or row.get("event_kind") != "auxiliary"
                    or row.get("batch_slot") != slot):
                return False
            if row.get("auxiliary_source_role") != role or row.get("loss_weight") != 1.0:
                return False
        ids = {row.get("source_episode_id") for row in selected.values()}
        if len(ids) != 3:
            return False
        reference = selected["B-DUP"]
        for arm in ("B-MATCHED", "B-SHAM"):
            if any(selected[arm].get(field) != reference.get(field) for field in common):
                return False
    return True


class AdapterRulesTests(unittest.TestCase):
    def test_same_target_different_source_payload_passes(self) -> None:
        rows = {}
        for arm, role, source in (("B-DUP", "anchor_duplicate", "a"),
                                  ("B-MATCHED", "matched_neutral", "n"),
                                  ("B-SHAM", "certified_sham", "s")):
            rows[arm] = [{"arm": arm, "event_kind": "auxiliary", "batch_slot": i, "auxiliary_source_role": role,
                          "source_episode_id": source + str(i), "neighborhood_id": f"w{i}",
                          "target_source_episode_id": f"a{i}", "target_hash": "t", "candidate_order_hash": "c",
                          "candidate_semantic_ids": ["c0", "c1"], "candidate_indices": [0, 1],
                          "candidate_mask": [True, True], "candidate_profile": "name_definition", "target": [1., 0.],
                          "state_feature_dimension": 2048, "candidate_feature_dimension": 2048,
                          "loss_weight": 1.0, "normalization": "batch"} for i in range(5_000)]
        self.assertTrue(auxiliary_payload_pass(rows))

    def test_treatment_source_roles_are_required(self) -> None:
        rows = {arm: [{"event_kind": "auxiliary", "batch_slot": i, "auxiliary_source_role": role,
                       "arm": arm,
                       "source_episode_id": f"{arm}{i}", "neighborhood_id": f"w{i}",
                       "target_source_episode_id": f"a{i}", "target_hash": "t", "candidate_order_hash": "c",
                       "candidate_semantic_ids": ["c0"], "candidate_indices": [0], "candidate_mask": [True],
                       "candidate_profile": "name_definition", "target": [1.], "state_feature_dimension": 2048,
                       "candidate_feature_dimension": 2048, "loss_weight": 1.0, "normalization": "batch"}
                      for i in range(5_000)] for arm, role in ARMS.items()}
        rows["B-SHAM"][15]["auxiliary_source_role"] = "matched_neutral"
        self.assertFalse(auxiliary_payload_pass(rows))

    def test_cross_arm_target_mismatch_fails(self) -> None:
        rows = {arm: [{"event_kind": "auxiliary", "batch_slot": i, "auxiliary_source_role": role,
                       "arm": arm,
                       "source_episode_id": f"{arm}{i}", "neighborhood_id": f"w{i}",
                       "target_source_episode_id": f"a{i}", "target_hash": "t", "candidate_order_hash": "c",
                       "candidate_semantic_ids": ["c0"], "candidate_indices": [0], "candidate_mask": [True],
                       "candidate_profile": "name_definition", "target": [1.], "state_feature_dimension": 2048,
                       "candidate_feature_dimension": 2048, "loss_weight": 1.0, "normalization": "batch"}
                      for i in range(5_000)] for arm, role in ARMS.items()}
        rows["B-MATCHED"][44]["target_hash"] = "other"
        self.assertFalse(auxiliary_payload_pass(rows))


def seal_packet() -> None:
    if RUN.exists():
        raise RuntimeError(f"Q repaired run namespace already exists: {RUN}")
    for name, expected in (("q-run-contract-v02.json", CONTRACTS["run"]),
                           ("q-analysis-contract-v02.json", CONTRACTS["analysis"]),
                           ("q-execution-addendum-v01.json", CONTRACTS["addendum"]),
                           ("q-source-lock-v02.json", CONTRACTS["source_lock"])):
        if sha(Q / "contracts" / name) != expected:
            raise RuntimeError(f"sealed Q contract hash mismatch: {name}")
    panel_seal_path = PANEL / "seals/q-panel-phase-terminal-seal-v01.json"
    panel_seal = read_json(panel_seal_path)
    if sha(panel_seal_path) != CONTRACTS["panel_seal"] or panel_seal.get("root_sha256") != CONTRACTS["panel_root"]:
        raise RuntimeError("sealed Q panel identity mismatch")
    instrument = read_json(INSTRUMENT)
    if instrument.get("status") != "Q_EXECUTION_INSTRUMENTS_SEALED_PRE_HEAD_INITIALIZATION":
        raise RuntimeError("Q frozen core instrument seal invalid")
    if sha(RUN2 / "q-full-execution-packet-v02.json") != "493e6858d993acabdbcae6a2f5c5e86bccc2a0da0d6fc25d33c52e305b653edf":
        raise RuntimeError("Q prior repaired-attempt packet identity changed")
    if (RUN1 / "training").exists() or (RUN1 / "evaluation").exists() or (RUN2 / "training").exists() or (RUN2 / "evaluation").exists():
        raise RuntimeError("prior Q attempt created training/evaluation outputs; do not continue this repair path")
    schedule_source = SCHEDULE_SOURCE / "fixed-schedule.jsonl"
    schedule_seal = read_json(SCHEDULE_SOURCE / "schedule-seal.json")
    if sha(schedule_source) != CONTRACTS["schedule"] or schedule_seal.get("schedule_sha256") != CONTRACTS["schedule"]:
        raise RuntimeError("Q schedule identity mismatch")
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(AdapterRulesTests))
    if not result.wasSuccessful():
        raise RuntimeError("Q execution repair tests failed")
    bindings = []
    for relative in CORE_BINDINGS:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        bindings.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha(path)})
    RUN.mkdir(parents=True, exist_ok=False)
    schedule_out = RUN / "schedule"
    schedule_out.mkdir()
    schedule_entries = []
    for name in ("fixed-schedule.jsonl", "schedule-seal.json", "fixed-schedule-manifest.json", "independent-verification-v01.json"):
        source = SCHEDULE_SOURCE / name
        if not source.is_file():
            raise FileNotFoundError(source)
        target = schedule_out / name
        shutil.copyfile(source, target)
        if sha(source) != sha(target):
            raise RuntimeError(f"Q schedule copy mismatch: {name}")
        schedule_entries.append({"path": name, "bytes": target.stat().st_size, "sha256": sha(target)})
    packet_root = entries_root(bindings)
    statement = ("Continue the previously authorized frozen JEV v0.8Q execution in a new output identity. This repair "
                 "only corrects two pre-initialization validator assumptions: exact shared-receipt binding and the "
                 "expected arm-specific auxiliary source identities. Scientific contracts, panel, treatments, seeds, "
                 "schedule, objective, metrics, thresholds, and opening order are unchanged.")
    packet = {
        "schema": "jev-v08q-full-execution-packet-v02",
        "identity": "JEV-V08Q-SINGLE-DOSE-GAIN-EXECUTION-REPAIRED-V03",
        "authorization": {"phase": "Q_FULL_FROZEN_RUN_EVALUATION_AND_ANALYSIS", "explicit_user_authorization": True,
                          "source": "prior explicit full-Q authorization plus current explicit repair instruction",
                          "statement": statement, "statement_sha256": hashlib.sha256(statement.encode()).hexdigest()},
        "parents": {"run_contract_sha256": CONTRACTS["run"], "analysis_contract_sha256": CONTRACTS["analysis"],
                    "addendum_sha256": CONTRACTS["addendum"], "source_lock_sha256": CONTRACTS["source_lock"],
                    "source_lock_root_sha256": CONTRACTS["source_root"], "panel_root_sha256": CONTRACTS["panel_root"],
                    "panel_terminal_seal_sha256": CONTRACTS["panel_seal"], "schedule_sha256": CONTRACTS["schedule"],
                    "schedule_seal_sha256": sha(schedule_out / "schedule-seal.json"),
                    "execution_instrument_seal_sha256": sha(INSTRUMENT),
                    "execution_instrument_root_sha256": instrument["root_sha256"],
                    "prior_v01_packet_sha256": sha(RUN1 / "q-full-execution-packet-v01.json"),
                    "prior_v02_packet_sha256": sha(RUN2 / "q-full-execution-packet-v02.json")},
        "run_contract_sha256": CONTRACTS["run"], "analysis_contract_sha256": CONTRACTS["analysis"],
        "addendum_sha256": CONTRACTS["addendum"], "panel_root_sha256": CONTRACTS["panel_root"],
        "run": {"seeds": [2540205348, 2603246505, 3565067208], "arms": ["B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW"],
                "optimizer_steps_per_run": 120, "checkpoint_steps": [40, 80, 100, 120], "trained_runs": 12,
                "trained_checkpoints": 48, "shared_seed_initial_templates": 3, "prediction_rows": 408000,
                "panel_open_count": 1, "checkpoint_selection": False, "panel_feedback_during_training": False},
        "schedule_artifacts": schedule_entries, "implementation_bindings": bindings,
        "packet_root_sha256": packet_root,
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
    print(json.dumps({"status": "Q_EXECUTION_PACKET_REPAIRED_V03_SEALED",
                      "run_namespace": str(RUN), "packet_sha256": sha(packet_path),
                      "implementation_count": len(bindings), "adapter_tests": 3,
                      "training": False, "panel_opened": False}, indent=2))


def read_aux_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for _ in range(10_000):
            if not stream.readline():
                raise RuntimeError(f"Q primary rows ended early: {path}")
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def validate_training_receipts(module: Any) -> None:
    paths = module.source_paths()
    lock = module.read_json(SOURCE_LOCK)
    lock_hashes = {str(entry["sha256"]) for entry in lock["entries"]}
    required = {module.HASHES[k] for k in ("primary", "dup", "matched", "sham")}
    required |= {STATE_SCOPE_SHA, STATE_FEATURES_SHA, CANDIDATE_FEATURES_SHA}
    state_receipt_sha = module.sha(paths["state_receipt"])
    candidate_receipt_sha = module.sha(paths["candidate_receipt"])
    if not receipt_layout_pass(lock_hashes, state_receipt_sha, candidate_receipt_sha, required):
        raise RuntimeError("Q exact training receipt/source-lock layout mismatch")
    state_receipt = module.read_json(paths["state_receipt"])
    if (state_receipt.get("status") != "V08N_SHARED_FEATURE_CACHE_SEALED_TRAINING_ONLY"
            or state_receipt.get("scope", {}).get("sha256") != STATE_SCOPE_SHA
            or state_receipt.get("feature_tensor", {}).get("sha256") != STATE_FEATURES_SHA
            or state_receipt.get("representation", {}).get("feature_key") != "mean_full@16"):
        raise RuntimeError("Q pinned shared-cache receipt metadata mismatch")


def validate_auxiliary_sources(module: Any) -> None:
    paths = module.source_paths()
    rows_by_arm = {"B-DUP": read_aux_rows(paths["dup"]),
                   "B-MATCHED": read_aux_rows(paths["matched"]),
                   "B-SHAM": read_aux_rows(paths["sham"])}
    if not auxiliary_payload_pass(rows_by_arm):
        raise RuntimeError("Q arm-specific auxiliary payloads do not satisfy the frozen common-target/control contract")


def load_core() -> Any:
    core = Q / "source/run_q_training_v02.py"
    spec = importlib.util.spec_from_file_location("q_frozen_training_core_v02", core)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load sealed Q training core")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.RUN = RUN
    module.TRAIN = RUN / "training"
    module.SCHEDULE = RUN / "schedule"
    module.PACKET = PACKET
    module.INSTRUMENT = INSTRUMENT
    original_need = module.need
    adapter_events: list[dict[str, Any]] = []

    def need_adapter(ok: bool, message: str) -> None:
        if not ok and message == "Q feature receipts are not bound by the sealed source lock":
            validate_training_receipts(module)
            adapter_events.append({"check": "feature_receipt_binding", "result": "PASS",
                                   "basis": "state receipt pinned by exact digest; state scope/tensor locked; candidate receipt locked"})
            return
        if not ok and message == "auxiliary identities differ across arms":
            validate_auxiliary_sources(module)
            adapter_events.append({"check": "auxiliary_treatment_payload", "result": "PASS",
                                   "basis": "common neighborhood, target-source, exact target and candidate order; role-specific source IDs"})
            return
        original_need(ok, message)

    module.need = need_adapter
    original_parent_check = module.verify_contract_panel_and_sources

    def parent_check_then_bind_adapter() -> dict[str, Any]:
        result = original_parent_check()
        module.__file__ = str(Path(__file__).resolve())
        return result

    module.verify_contract_panel_and_sources = parent_check_then_bind_adapter
    module._q_adapter_events = adapter_events
    return module


def verify_adapter_receipt() -> None:
    row = read_json(ADAPTER_RECEIPT)
    if (row.get("status") != "Q_TRAINING_INPUT_ADAPTER_PASS"
            or row.get("adapter_sha256") != sha(Path(__file__).resolve())
            or row.get("run_contract_sha256") != CONTRACTS["run"]
            or row.get("source_lock_sha256") != CONTRACTS["source_lock"]):
        raise RuntimeError("Q adapter receipt identity mismatch")


def train(mode: str) -> int:
    module = load_core()
    if mode == "run":
        verify_adapter_receipt()
    sys.argv = [str(Q / "source/run_q_training_v02.py"), mode]
    status = int(module.main())
    if mode == "preflight" and status == 0:
        events = module._q_adapter_events
        if {row["check"] for row in events} != {"feature_receipt_binding", "auxiliary_treatment_payload"}:
            raise RuntimeError(f"Q expected two preflight corrections, observed {events}")
        write_json(ADAPTER_RECEIPT, {"status": "Q_TRAINING_INPUT_ADAPTER_PASS",
                    "adapter_sha256": sha(Path(__file__).resolve()),
                    "frozen_trainer_sha256": sha(Q / "source/run_q_training_v02.py"),
                    "run_contract_sha256": CONTRACTS["run"], "source_lock_sha256": CONTRACTS["source_lock"],
                    "source_lock_root_sha256": CONTRACTS["source_root"], "state_receipt_sha256": STATE_RECEIPT_SHA,
                    "candidate_receipt_sha256": CANDIDATE_RECEIPT_SHA, "adapter_events": events,
                    "preflight_receipt_sha256": sha(RUN / "training/training-preflight-receipt-v01.json"),
                    "head_initialization": True, "optimizer_steps": 0, "panel_opened": False,
                    "created_at_utc": datetime.now(timezone.utc).isoformat()})
    return status


def run_other(stage: str) -> int:
    names = {"evaluate": "evaluate_q_panel_v02.py", "analyze": "analyze_q_results_v02.py",
             "verify": "verify_q_full_execution_v02.py"}
    path = Q / "source" / names[stage]
    spec = importlib.util.spec_from_file_location(f"q_{stage}_core_v02", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load sealed Q {stage} implementation")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.RUN = RUN
    module.PACKET = PACKET
    module.PACKET_SEAL = PACKET_SEAL
    if stage == "evaluate":
        module.TRAIN = RUN / "training"
        module.OUTPUT = RUN / "evaluation"
        if not (module.TRAIN / "training-seal-manifest.json").is_file():
            raise RuntimeError("Q inference cannot open the panel before the complete training seal")
    elif stage == "analyze":
        module.OUTPUT = RUN / "evaluation"
    else:
        module.TRAIN = RUN / "training"
        module.EVAL = RUN / "evaluation"
        module.RECEIPT = RUN / "independent-verification-v01.json"
    verify_adapter_receipt()
    sys.argv = [str(path)]
    return int(module.main())


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: q_execution_recovery_v02.py {self-test|seal|preflight|run|evaluate|analyze|verify}")
    stage = sys.argv[1]
    if stage == "self-test":
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AdapterRulesTests))
        return 0 if result.wasSuccessful() else 1
    if stage == "seal":
        seal_packet(); return 0
    if stage in {"preflight", "run"}:
        return train(stage)
    if stage in {"evaluate", "analyze", "verify"}:
        return run_other(stage)
    raise SystemExit(f"unknown Q stage: {stage}")


if __name__ == "__main__":
    raise SystemExit(main())
