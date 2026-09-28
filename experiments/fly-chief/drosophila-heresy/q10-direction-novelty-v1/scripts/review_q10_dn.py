"""Independent standard-library reviewer for Q10-DN1 diagnostic receipts."""
from __future__ import annotations
import hashlib, json, math, sys
from pathlib import Path

PROTOCOL = "Q10-DN1"
FORBIDDEN = {"accuracy", "reward", "actions", "old_map_margin", "behavior"}
SEEDS = {9601, 9602}
SIDES = {"R", "L"}
TAUS = {4.0, 16.0}
TRIALS = {1, 64, 128, 256}

def fail(message: str) -> None:
    raise RuntimeError(message)

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

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
        fail("usage: review_q10_dn.py ROOT SAMPLE_DIR OUTPUT")
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
    if execution["protocol"] != PROTOCOL or not execution["complete"] or execution["audited_events"] != 32:
        fail("execution identity or count mismatch")
    files = sorted(sample.glob("seed*-*-tau*.json"))
    if len(files) != 8:
        fail("bundle coverage mismatch")
    events = []
    for path in files:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        reject(bundle)
        if bundle["protocol"] != PROTOCOL or bundle["scientific_seed_bundles"] != 0:
            fail(f"bundle firewall mismatch: {path.name}")
        for event in bundle["events"]:
            if event["seed"] not in SEEDS or event["side"] not in SIDES or event["tau"] not in TAUS or event["trial"] not in TRIALS:
                fail(f"event coverage mismatch: {path.name}")
            if event["status"] == "ANALYZED":
                for point in event["curve"]:
                    if point["steps"] not in {1, 2, 4, 8, 16} or not finite(point["residual_ratio"]):
                        fail(f"invalid curve metric: {path.name}")
                for metric in event["step_metrics"]:
                    for key in ("mean_novelty_fraction", "max_novelty_fraction", "mean_error_alignment", "max_abs_error_alignment"):
                        if not finite(metric[key]):
                            fail(f"nonfinite novelty metric: {path.name}")
            events.append(event)
    if len(events) != 32 or {(e["seed"], e["side"], e["tau"], e["trial"]) for e in events}.__len__() != 32:
        fail("event uniqueness or count mismatch")
    receipt = {"protocol": PROTOCOL, "status": "VERIFIED", "audited_events": 32, "bundle_count": 8, "scientific_seed_bundles": 0, "behavioral_inference": False, "dh08b_authorized": False, "plan_sha256": sha256(root / "PLAN.md"), "contract_sha256": sha256(root / "CONTRACT.json")}
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
