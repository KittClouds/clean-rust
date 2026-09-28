"""Recompute PI target overlay metrics from the target-blind map."""
import json
import math
import struct
from pathlib import Path

from oracle import from_bits


def f64(bits):
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def close(a, b):
    assert math.isclose(a, b, rel_tol=3e-11, abs_tol=1e-20), (a, b)


def changed(records, position, base):
    for item in records:
        if item["union_position"] == position:
            return item["readout_bits"]
    return base


def audit(map_path: Path, fixture_path: Path, overlay_fixture_path: Path, overlay_path: Path):
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    fixtures = {x["event_key"]: x for x in json.loads(fixture_path.read_text(encoding="utf-8"))["events"]}
    targets = {x["event_key"]: x for x in json.loads(overlay_fixture_path.read_text(encoding="utf-8"))["events"]}
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    assert overlay["map_sha256"] == __import__("hashlib").sha256(map_path.read_bytes()).hexdigest()
    checked = 0
    for event, output in zip(mapping["events"], overlay["events"]):
        fixture = fixtures[event["event_key"]]
        target = targets[event["event_key"]]["target_readout_bits"]
        baseline = fixture["baseline_readout_bits"]
        base_error = [from_bits(a) - from_bits(b) for a, b in zip(baseline, target)]
        base_norm = math.sqrt(math.fsum(x * x for x in base_error))
        base_mismatch = sum(a != b for a, b in zip(baseline, target))
        assert math.isclose(output["baseline_error_norm"], base_norm, rel_tol=3e-11, abs_tol=1e-20)
        assert output["baseline_bitwise_mismatch_count"] == base_mismatch
        for pair_index, pair in enumerate(event["pairs"]):
            support = pair["support"]
            for candidate_index, candidate in enumerate(pair["candidates"]):
                out = output["candidates"][pair_index * 100 + candidate_index]
                base_sq = math.fsum(x * x for x in base_error)
                additive_sq = base_sq
                joint_sq = base_sq
                dot = 0.0
                support_by_row = {item["row"]: item for item in support}
                step_a = next(item for item in pair["single_a"] if item["signed_step"] == candidate["signed_steps"][0])
                step_b = next(item for item in pair["single_b"] if item["signed_step"] == candidate["signed_steps"][1])
                interaction = []
                joint_mismatch = base_mismatch
                for item in support:
                    row = item["row"]
                    pos = item["union_position"]
                    base_bits = baseline[row]
                    base = from_bits(base_bits)
                    goal = from_bits(target[row])
                    a = from_bits(changed(step_a["changed_readout"], pos, base_bits))
                    b = from_bits(changed(step_b["changed_readout"], pos, base_bits))
                    joint_bits = changed(candidate["joint_changed_readout"], pos, base_bits)
                    joint = from_bits(joint_bits)
                    old_error = base_error[row]
                    additive = base + (a - base) + (b - base)
                    additive_sq += (additive - goal) ** 2 - old_error * old_error
                    joint_sq += (joint - goal) ** 2 - old_error * old_error
                    joint_mismatch += (joint_bits != target[row]) - (base_bits != target[row])
                    value = joint - a - b + base
                    interaction.append(value)
                    dot += value * (-old_error)
                interaction_sq = math.fsum(x * x for x in interaction)
                cosine = dot / math.sqrt(interaction_sq * base_norm * base_norm) if interaction_sq and base_norm else 0.0
                actual_norm = math.sqrt(max(0.0, joint_sq))
                additive_norm = math.sqrt(additive_sq)
                close(out["actual_joint_error_norm"], actual_norm)
                close(out["additive_error_norm"], additive_norm)
                close(out["interaction_cosine_with_negative_error"], cosine)
                assert out["actual_joint_bitwise_mismatch_count"] == joint_mismatch
                expected_pareto = actual_norm <= base_norm and joint_mismatch <= base_mismatch and (actual_norm < base_norm or joint_mismatch < base_mismatch)
                assert out["pareto_improvement_vs_baseline"] == expected_pareto
                checked += 1
    return checked


if __name__ == "__main__":
    import sys
    n = audit(*(Path(x) for x in sys.argv[1:5]))
    print(f"independent PI overlay audit passed: {n} candidates")
