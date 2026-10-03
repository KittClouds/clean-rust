"""Independent standard-library reviewer for Q10-JBR1 receipts."""
from __future__ import annotations
import hashlib, json, math, sys
from pathlib import Path

PROTOCOL = "Q10-JBR2"
FORBIDDEN = {"accuracy", "reward", "actions", "old_map_margin", "behavior"}
SEEDS, SIDES, TAUS, TRIALS = {9701, 9702}, {"R", "L"}, {4.0, 16.0}, {128}

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
        fail("usage: review_q10_jbr.py ROOT SAMPLE_DIR OUTPUT")
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
        fail("event coverage mismatch")
    events = []
    for path in files:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        reject(bundle)
        if bundle["protocol"] != PROTOCOL or bundle["scientific_seed_bundles"] != 0 or bundle["behavioral_inference"] or bundle["dh08b_authorized"]:
            fail(f"firewall mismatch: {path.name}")
        if len(bundle["events"]) != 1:
            fail(f"event count mismatch: {path.name}")
        event = bundle["events"][0]
        if event["seed"] not in SEEDS or event["side"] not in SIDES or event["tau"] not in TAUS or event["trial"] not in TRIALS:
            fail(f"event coverage mismatch: {path.name}")
        if event["status"] != "BLOCK_ORDER_AUDIT_COMPLETE" or event["block_count"] != 6 or event["shared_block_count"] != 3 or event["disjoint_block_count"] != 3:
            fail(f"block capacity mismatch: {path.name}")
        for key in ("base_error_norm", "best_shared_residual_ratio", "best_disjoint_residual_ratio"):
            if not finite(event[key]) or float(event[key]) < 0.0:
                fail(f"invalid event metric {key}: {path.name}")
        if len(event["blocks"]) != 6:
            fail(f"block receipt mismatch: {path.name}")
        for block in event["blocks"]:
            if block["category"] not in {"shared", "disjoint"} or block["candidate_count"] != 125:
                fail(f"invalid block identity: {path.name}")
            if block["category"] == "disjoint" and block["shared_rows"] != 0:
                fail(f"disjoint block has shared rows: {path.name}")
            if block["category"] == "shared" and block["shared_rows"] == 0:
                fail(f"shared block lacks shared rows: {path.name}")
            for key in ("base_error_norm", "best_residual_norm", "best_residual_ratio", "residual_reduction"):
                if not finite(block[key]) or (key != "residual_reduction" and float(block[key]) < 0.0):
                    fail(f"invalid block metric {key}: {path.name}")
            if len(block["best_steps"]) != 3 or any(step not in {1, 2, 4, 8, 16} for step in block["best_steps"]):
                fail(f"invalid best prefix: {path.name}")
        events.append(event)
    if len({(event["seed"], event["side"], event["tau"], event["trial"]) for event in events}) != 8:
        fail("event uniqueness mismatch")
    receipt = {
        "protocol": PROTOCOL,
        "status": "VERIFIED",
        "audited_events": 8,
        "block_count": 48,
        "blocks_per_event": 6,
        "joint_candidates_per_block": 125,
        "scientific_seed_bundles": 0,
        "behavioral_inference": False,
        "dh08b_authorized": False,
        "plan_sha256": sha256(root / "PLAN.md"),
        "contract_sha256": sha256(root / "CONTRACT.json"),
    }
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
