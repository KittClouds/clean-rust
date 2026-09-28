"""Independent standard-library reviewer for Q10-PF2 receipts."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

PROTOCOL = "Q10-PF2"
FORBIDDEN = {"accuracy", "reward", "actions", "old_map_margin", "behavior"}
SEEDS = {9661, 9662}
SIDES = {"R", "L"}
TAUS = {4.0, 16.0}
TRIALS = {128}


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def reject(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN:
                fail(f"forbidden field {path}.{key}")
            reject(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject(child, f"{path}[{index}]")


def finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def main() -> None:
    if len(sys.argv) != 4:
        fail("usage: review_q10_pf2.py ROOT SAMPLE_DIR OUTPUT")
    root, sample, output = map(lambda value: Path(value).resolve(), sys.argv[1:])
    contract = json.loads((root / "CONTRACT.json").read_text(encoding="utf-8"))
    if contract["protocol"] != PROTOCOL or sha256(root / "PLAN.md").lower() != contract["plan_sha256"].lower():
        fail("contract or plan identity mismatch")
    pre = json.loads((sample / "pre-execution.json").read_text(encoding="utf-8"))
    if pre["protocol"] != PROTOCOL or pre["status"] != "FROZEN_PRE_EXECUTION":
        fail("pre-execution identity mismatch")
    for item in pre["source_manifest"]:
        path = root / item["path"]
        if not path.is_file() or sha256(path).lower() != item["sha256"].lower():
            fail(f"source manifest mismatch: {item['path']}")
    execution = json.loads((sample / "execution.json").read_text(encoding="utf-8"))
    if execution["protocol"] != PROTOCOL or not execution["complete"] or execution["audited_events"] != 8:
        fail("execution identity or count mismatch")
    files = sorted(sample.glob("seed*-*-tau*.json"))
    if len(files) != 8:
        fail("bundle coverage mismatch")
    events = []
    for path in files:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        reject(bundle)
        if bundle["protocol"] != PROTOCOL or bundle["scientific_seed_bundles"] != 0 or bundle["behavioral_inference"] or bundle["dh08b_authorized"]:
            fail(f"bundle firewall mismatch: {path.name}")
        if len(bundle["events"]) != 1:
            fail(f"event count mismatch: {path.name}")
        for event in bundle["events"]:
            if event["seed"] not in SEEDS or event["side"] not in SIDES or event["tau"] not in TAUS or event["trial"] not in TRIALS:
                fail(f"event coverage mismatch: {path.name}")
            if event["status"] != "INTERACTION_AUDIT_COMPLETE":
                fail(f"incomplete pair coverage: {path.name}")
            if event["shared_pair_count"] != 12 or event["disjoint_pair_count"] != 12 or event["pair_count"] != 24:
                fail(f"pair coverage mismatch: {path.name}")
            for key in ("base_error_norm", "max_interaction_ratio_error", "mean_interaction_ratio_error"):
                if not finite(event[key]) or float(event[key]) < 0.0:
                    fail(f"invalid event metric {key}: {path.name}")
            if len(event["pairs"]) != 24:
                fail(f"pair receipt count mismatch: {path.name}")
            for pair in event["pairs"]:
                if pair["category"] not in {"shared", "disjoint"} or not finite(pair["interaction_norm"]) or not finite(pair["interaction_ratio_error"]) or not finite(pair["interaction_ratio_joint"]):
                    fail(f"invalid pair metric: {path.name}")
                if pair["interaction_norm"] < 0.0 or pair["interaction_ratio_error"] < 0.0 or pair["interaction_ratio_joint"] < 0.0:
                    fail(f"negative pair metric: {path.name}")
                if pair["category"] == "disjoint" and pair["shared_rows"] != 0:
                    fail(f"disjoint pair has shared rows: {path.name}")
            events.append(event)
    keys = {(event["seed"], event["side"], event["tau"], event["trial"]) for event in events}
    if len(events) != 8 or len(keys) != 8:
        fail("event uniqueness or count mismatch")
    receipt = {"protocol": PROTOCOL, "status": "VERIFIED", "audited_events": 8, "bundle_count": 8, "pairs_per_event": 24, "scientific_seed_bundles": 0, "behavioral_inference": False, "dh08b_authorized": False, "plan_sha256": sha256(root / "PLAN.md"), "contract_sha256": sha256(root / "CONTRACT.json")}
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
