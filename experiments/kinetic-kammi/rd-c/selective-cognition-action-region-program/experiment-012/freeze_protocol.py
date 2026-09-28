from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROGRAM = Path(r"C:\rd-c\selective-cognition-action-region-program")
EXPERIMENT = PROGRAM / "experiment-012"
RUN = EXPERIMENT / "protocol-lock-v0.json"
E011 = Path(r"C:\rd-c\experiment-011")
QUAL = (
    E011
    / "repairs"
    / "producer-order-v1"
    / "artifacts"
    / "runs"
    / "e011-producer-order-integration-qual-01"
)
AMENDMENT = (
    E011
    / "artifacts"
    / "runs"
    / "e011-20260925-causal-evidence-01"
    / "E011-postrun-engineering-amendment-03.md"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if "target" in path.parts or ".git" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def write_lock(*, allow_existing: bool) -> dict:
    frozen_input_path = QUAL / "frozen-input-lock.json"
    score_lock_path = QUAL / "score-replay-input-lock.json"
    summary_path = QUAL / "qualification-summary.json"
    contract = json.loads((EXPERIMENT / "channel-contract-v0.json").read_text(encoding="utf-8"))
    frozen_input = json.loads(frozen_input_path.read_text(encoding="utf-8"))
    score_lock = json.loads(score_lock_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    if frozen_input.get("state") != "FROZEN_BEFORE_MODEL_CONTACT":
        raise SystemExit("E011 inherited system lock is not a frozen precontact input lock")
    if score_lock.get("state") != "SCORED_AFTER_MODEL_CONTACT":
        raise SystemExit("E011 inherited switchboard lacks completed integration qualification")
    if not summary.get("all_repository_gates_passed"):
        raise SystemExit("E011 integration qualification did not pass both repository gates")
    if frozen_input.get("thresholds") != {
        "minimum_applicability_milli": 850,
        "maximum_abstention_milli": 150,
    }:
        raise SystemExit("E011 threshold pair drifted")
    if contract.get("model_contact_authorized") is not False:
        raise SystemExit("E012 protocol unexpectedly authorizes model contact")

    artifacts = {
        "program_readme": PROGRAM / "README.md",
        "protocol": EXPERIMENT / "PROTOCOL.md",
        "channel_contract": EXPERIMENT / "channel-contract-v0.json",
        "observer_frame_projection": EXPERIMENT / "observer-frame-projection-v0.md",
        "bank_construction_plan": EXPERIMENT / "bank-construction-plan-v0.md",
        "freezer_source": EXPERIMENT / "freeze_protocol.py",
        "e011_frozen_input_lock": frozen_input_path,
        "e011_score_replay_lock": score_lock_path,
        "e011_qualification_summary": summary_path,
        "e011_qualification_report": QUAL / "integration-qualification-report.md",
        "e011_runtime_source_tree": E011 / "repairs" / "producer-order-v1" / "runtime-integration",
        "e011_engineering_amendment": AMENDMENT,
    }
    hashes = {
        key: tree_sha256(path) if path.is_dir() else sha256(path)
        for key, path in artifacts.items()
    }
    lock = {
        "schema_version": 1,
        "program": "Selective Cognition / Action Region Program",
        "experiment": "E012 Prospective Frame Decomposition",
        "protocol_version": 0,
        "state": "FROZEN_FOR_BANK_CONSTRUCTION",
        "model_contact_authorized": False,
        "task_construction_started": False,
        "sealed_at_local": None,
        "hashes": hashes,
        "inherited_switchboard": {
            "run_id": frozen_input["run_id"],
            "bank_id": frozen_input["bank_id"],
            "frozen_input_lock_sha256": sha256(frozen_input_path),
            "score_replay_lock_sha256": sha256(score_lock_path),
            "runtime_source_tree_sha256": hashes["e011_runtime_source_tree"],
            "thresholds": frozen_input["thresholds"],
            "normalization_contract": frozen_input["normalization_contract"],
            "reasoning_mode": frozen_input["reasoning_mode"],
            "maximum_output_tokens": frozen_input["maximum_output_tokens"],
            "models": frozen_input["models"],
            "routing": frozen_input["routing"],
        },
        "bank_requirements": contract["task_bank_minimums"],
        "precontact_gate": "build and audit the complete bank, then create a separate immutable FROZEN_BEFORE_MODEL_CONTACT lock",
    }

    if RUN.exists():
        existing = json.loads(RUN.read_text(encoding="utf-8"))
        if not allow_existing:
            if existing != lock:
                raise SystemExit("protocol lock already exists and differs; create a versioned amendment")
            return existing
        if existing != lock:
            raise SystemExit("refusing to replace a differing frozen protocol lock")
        return existing

    if not allow_existing:
        raise SystemExit("protocol is not sealed yet; use --freeze after the review pass")

    RUN.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return lock


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true", help="write protocol-lock-v0.json if absent")
    args = parser.parse_args()
    lock = write_lock(allow_existing=args.freeze)
    print(json.dumps(lock, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
