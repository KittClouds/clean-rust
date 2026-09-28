"""Independent audit for the Q10-NA v2 preflight receipt."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check_hash(path: Path, expected: str, label: str) -> None:
    require(path.is_file(), f"missing {label}: {path}")
    require(digest(path) == expected.upper(), f"hash mismatch: {label}")


def check_forbidden(value: Any, forbidden: set[str], location: str = "receipt") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            require(str(key).lower() not in forbidden, f"forbidden field {key} at {location}")
            check_forbidden(nested, forbidden, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            check_forbidden(nested, forbidden, f"{location}[{index}]")


def main() -> int:
    protocol = Path(__file__).resolve().parents[1]
    workspace = protocol.parents[2]
    contract = load(protocol / "CONTRACT.json")
    require(contract["protocol"] == "Q10-NA", "protocol identity mismatch")
    require(contract["version"] == 2, "unexpected Q10-NA contract version")
    check_hash(protocol / "PLAN.md", contract["plan_sha256"], "Q10-NA PLAN.md")

    parent = workspace / contract["parent"]["root"]
    receipt_root = workspace / contract["parent"]["receipt_root"]
    for filename, expected in contract["parent"]["protocol_file_sha256"].items():
        check_hash(parent / filename, expected, f"parent/{filename}")
    for filename, expected in contract["parent"]["receipt_file_sha256"].items():
        check_hash(receipt_root / filename, expected, f"receipt/{filename}")

    replay = contract["parent"]["replay_inputs"]
    source_root = workspace / replay["source_root"]
    for filename, expected in replay["source_files_sha256"].items():
        check_hash(source_root / filename, expected, f"replay-source/{filename}")
    check_hash(workspace / replay["da2_results_path"], replay["da2_results_sha256"], "DA2 results")

    preflight = load(protocol / "qualification" / "preflight.json")
    require(preflight["protocol"] == "Q10-NA", "preflight protocol mismatch")
    require(preflight["status"] == "Q10_NA_PREFLIGHT_VALID__READY_FOR_REPLAY", "preflight is not valid")
    require(preflight["errors"] == [], "preflight contains errors")
    require(preflight["scientific_seed_bundles_used"] == 0, "scientific bundles were used")
    require(preflight["behavioral_inference"] is False, "behavioral inference was reported")
    require(preflight["canonical_repair_applied"] is False, "canonical repair was reported")
    require(preflight["dh08b_authorized"] is False, "DH08B was authorized")
    require(preflight["replay_findings_emitted"] is False, "replay findings were emitted during preflight")

    targets = preflight["targets"]
    require(targets["observed"] == 326, "target count mismatch")
    require(targets["unique_identities"] == 326, "target identity mismatch")
    empty = targets["empty_support_summary"]
    require(empty["empty_support_count"] == 2, "empty-support count mismatch")
    require(empty["nonempty_support_count"] == 324, "nonempty-support count mismatch")
    require(empty["global_impossibility_claim"] is False, "empty domain was promoted to impossibility")

    raw = preflight["raw_support"]
    require(raw["complete"] is True and raw["union_mismatch_count"] == 0, "raw-support union failed")
    replay_report = preflight["prefix_coverage"]["replay"]
    require(replay_report["raw_support_replay_complete"] is True, "replay coverage incomplete")
    require(replay_report["replayable_prefix_keys"] == 25940, "replayable prefix count mismatch")
    require(replay_report["serialized_prefix_keys"] == 8515, "serialized prefix count mismatch")
    require(replay_report["missing_serialized_prefix_keys"] == 17425, "serialized-missing count mismatch")
    require(replay_report["unavailable_prefix_keys"] == 0, "unexpected unavailable legal prefixes")

    target_replay = preflight["parent"]["target_replay"]
    require(target_replay["checked"] == 326, "target replay count mismatch")
    require(target_replay["mismatch_count"] == 0, "reconstructed target bits mismatch")

    costs = preflight["cost_projection"]
    require(costs["pair"]["exact_total_candidates"] == 1493624, "pair cost mismatch")
    require(costs["pair"]["within_total_budget"] is True, "pair budget unexpectedly exceeded")
    require(costs["triple"]["exact_total_candidates"] == 61058294, "triple cost mismatch")
    require(costs["triple"]["global_truncation_required"] is True, "triple truncation was not declared")
    require(costs["classification_guard"]["incomplete_global_triple_domain"] == "higher-order-or-untested", "triple guard drift")
    require("pair_findings" not in preflight and "triple_findings" not in preflight, "replay section leaked into preflight")

    forbidden = {
        "accuracy", "reward", "actions", "behavior", "old_map_margin",
        "reversed_map_margin", "scientific_seed_id", "biological_mechanism",
        "connectome_generalization", "repair_applied_to_canonical_model",
        "dh08b_authorization",
    }
    check_forbidden(preflight, forbidden)
    print(
        "Q10-NA preflight audit passed: targets=326 empty_support=2 "
        "replayable_prefixes=25940 pair_candidates=1493624 "
        "triple_candidates=61058294 triple_budget=TRUNCATED"
    )
    print("Q10-NA pair/triple replay: not executed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, TypeError, ValueError, AuditError) as error:
        raise SystemExit(f"Q10-NA independent audit failed: {error}") from error
