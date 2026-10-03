"""Independent standard-library reviewer for Q10-SR3 engineering receipts."""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from pathlib import Path

PROTOCOL = "Q10-SR3"
FORBIDDEN = {"accuracy", "reward", "actions", "old_map_margin", "behavior"}


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def hash_f32(values: list[float]) -> str:
    h = hashlib.sha256()
    for value in values:
        h.update(struct.pack("<I", bits(value)))
    return h.hexdigest()


def sequential(rows: list[list[int]], weights: list[float]) -> list[float]:
    output = []
    for row in rows:
        # Matches Rust's f32 Iterator::sum identity, including empty rows.
        total = f32(-0.0)
        for coordinate in row:
            total = f32(total + f32(weights[coordinate]))
        output.append(total)
    return output


def reject_forbidden(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN:
                fail(f"forbidden field {path}.{key}")
            reject_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_forbidden(child, f"{path}[{index}]")


def verify_replay(path: Path) -> None:
    replay = json.loads(path.read_text(encoding="utf-8"))
    reject_forbidden(replay)
    rows = replay["operator"]["rows"]
    target = [f32(x) for x in replay["target_readout"]]
    truth = sequential(rows, [f32(x) for x in replay["snapshot"]["target"]])
    if [bits(x) for x in truth] != [bits(x) for x in target]:
        fail(f"target sequential replay mismatch: {path.name}")
    receipt = replay["receipt"]
    if hash_f32(target) != receipt["target_readout_sha256"]:
        fail(f"target readout hash mismatch: {path.name}")
    initial = [f32(x) for x in replay["initial_alternate"]]
    if initial and hash_f32(initial) != receipt["initial_alternate_sha256"]:
        fail(f"initial endpoint hash mismatch: {path.name}")
    final = replay.get("final_weights")
    final_readout = replay.get("final_readout")
    if final is None:
        if final_readout is not None or replay["path"]:
            fail(f"incomplete absent final state: {path.name}")
        return
    final = [f32(x) for x in final]
    recomputed = sequential(rows, final)
    if [bits(x) for x in recomputed] != [bits(f32(x)) for x in final_readout]:
        fail(f"final sequential replay mismatch: {path.name}")
    if hash_f32(final) != receipt["final_weights_sha256"]:
        fail(f"final endpoint hash mismatch: {path.name}")
    if hash_f32(recomputed) != receipt["final_readout_sha256"]:
        fail(f"final readout hash mismatch: {path.name}")
    current = initial[:]
    for move in replay["path"]:
        coordinate = move["coordinate"]
        if bits(current[coordinate]) != move["before_bits"]:
            fail(f"repair path before-bits mismatch: {path.name}")
        current[coordinate] = struct.unpack("<f", struct.pack("<I", move["after_bits"]))[0]
    if [bits(x) for x in current] != [bits(x) for x in final]:
        fail(f"repair path endpoint mismatch: {path.name}")
    gates = receipt.get("final_gates")
    if gates and gates["sequential_bitwise_equal"]:
        if [bits(x) for x in recomputed] != [bits(x) for x in target]:
            fail(f"claimed equality failed replay: {path.name}")
        if gates["total_moves"] != len(replay["path"]):
            fail(f"move count mismatch: {path.name}")


def verify_manifest(root: Path, pre: dict) -> None:
    for item in pre["source_manifest"]:
        path = root / item["path"]
        if not path.is_file() or sha256(path).lower() != item["sha256"].lower():
            fail(f"source manifest mismatch: {item['path']}")


def main() -> None:
    if len(sys.argv) != 4:
        fail("usage: review_q10_sr.py ROOT STAGE_DIR OUTPUT")
    root = Path(sys.argv[1]).resolve()
    stage_dir = Path(sys.argv[2]).resolve()
    output = Path(sys.argv[3]).resolve()
    contract = json.loads((root / "CONTRACT.json").read_text(encoding="utf-8"))
    if contract["protocol"] != PROTOCOL:
        fail("contract protocol mismatch")
    if sha256(root / "PLAN.md").upper() != contract["plan_sha256"].upper():
        fail("plan hash mismatch")
    pre = json.loads((stage_dir / "pre-execution.json").read_text(encoding="utf-8"))
    verify_manifest(root, pre)
    execution = json.loads((stage_dir / "execution.json").read_text(encoding="utf-8"))
    if execution["protocol"] != PROTOCOL or not execution["complete"]:
        fail("execution identity or completion mismatch")
    expected = 1024 if execution["stage"] == "stage1-a" else 4096
    expected_seeds = [9521] if execution["stage"] == "stage1-a" else [9522, 9523, 9524, 9525]
    bundles = sorted(stage_dir.glob("seed*-*-tau*.json"))
    if len(bundles) != len(expected_seeds) * 4:
        fail("bundle coverage mismatch")
    events = []
    observed_seeds = set()
    counters = {"eligible": 0, "equal": 0, "mismatched": 0, "repaired": 0,
                "exhausted": 0, "gate_failures": 0, "ambiguous": 0,
                "capacity_exact": 0, "capacity_gated": 0, "search_entered": 0}
    for path in bundles:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        reject_forbidden(bundle)
        if bundle["protocol"] != PROTOCOL or bundle["scientific_seed_bundles"] != 0:
            fail(f"bundle firewall mismatch: {path.name}")
        observed_seeds.add(bundle["seed"])
        events.extend(bundle["events"])
        for event in bundle["events"]:
            status = event["repair_status"]
            counters["eligible"] += status != "PARENT_CONSTRUCTOR_INELIGIBLE"
            counters["equal"] += status == "READOUT_ALREADY_EQUAL__FINAL_GATES_PASS"
            counters["mismatched"] += event["mismatch_status"] == "READOUT_MISMATCHED"
            counters["repaired"] += status == "REPAIR_VALID"
            counters["exhausted"] += status.startswith("SEARCH_EXHAUSTED")
            counters["gate_failures"] += status == "EXACT_READOUT_FOUND__FINAL_GATE_FAILURE"
            counters["ambiguous"] += status == "SEARCH_NUMERICALLY_AMBIGUOUS"
            counters["capacity_exact"] += (
                event.get("capacity") is not None
                and event["capacity"]["status"] == "CAPACITY_EXACT_WITHIN_TOLERANCE"
            )
            counters["capacity_gated"] += status == "CAPACITY_GATE_SKIPPED__PARTIAL_OR_EMPTY"
            counters["search_entered"] += event.get("search") is not None
            if status == "CAPACITY_GATE_SKIPPED__PARTIAL_OR_EMPTY":
                if event.get("search") is not None:
                    fail(f"capacity-gated event entered search: {path.name}")
                if event.get("capacity", {}).get("status") not in {
                    "CAPACITY_PARTIAL", "CAPACITY_ZERO_OR_EMPTY_BANK"
                }:
                    fail(f"capacity-gated status mismatch: {path.name}")
    if observed_seeds != set(expected_seeds) or len(events) != expected:
        fail("event or seed coverage mismatch")
    checks = {
        "audited_states": expected,
        "eligible_states": counters["eligible"],
        "initially_equal": counters["equal"],
        "initially_mismatched": counters["mismatched"],
        "repair_valid": counters["repaired"],
        "search_exhausted": counters["exhausted"],
        "final_gate_failures": counters["gate_failures"],
        "numerically_ambiguous": counters["ambiguous"],
        "capacity_exact": counters["capacity_exact"],
        "capacity_gated": counters["capacity_gated"],
        "search_entered": counters["search_entered"],
    }
    for key, expected_value in checks.items():
        if execution[key] != expected_value:
            fail(f"execution counter mismatch: {key}")
    replays = sorted(stage_dir.glob("replay-*.json"))
    if len(replays) != len(bundles):
        fail("replay coverage mismatch")
    for replay in replays:
        verify_replay(replay)
    receipt = {
        "protocol": PROTOCOL,
        "status": "VERIFIED",
        "stage": execution["stage"],
        "audited_states": expected,
        "bundle_count": len(bundles),
        "replay_count": len(replays),
        "execution_status": execution["status"],
        "counters": counters,
        "contract_sha256": sha256(root / "CONTRACT.json"),
        "plan_sha256": sha256(root / "PLAN.md"),
        "scientific_seed_bundles": 0,
        "behavioral_inference": False,
        "dh08b_authorized": False,
    }
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
