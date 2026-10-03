"""Independent stdlib recomputation of Sol's first-event qualification failures.

Replays candidate geometry from saved vectors, not acquisition/reversal training.
No model weights are committed. No experimental outcomes or seeds are added.
"""
import hashlib
import json
import math
from pathlib import Path
import struct

BASE = Path(__file__).resolve().parents[2]
SOURCE = BASE / "dh07/qualification/constructor-first-real-seed9000.json"
MASK = (1 << 64) - 1
SALT = 0x444830374E554C4C


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def rotate(x, n):
    return ((x << n) | (x >> (64 - n))) & MASK


def mix(x):
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & MASK
    return x ^ (x >> 31)


class Counter:
    def __init__(self, key):
        self.state = key ^ SALT

    def next(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK
        return mix(self.state)


def dot(a, b):
    return math.fsum(x * y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def cosine(a, b):
    denominator = norm(a) * norm(b)
    return dot(a, b) / denominator if denominator else 0.0


def project_out(z, unit):
    coefficient = dot(z, unit)
    return [x - coefficient * y for x, y in zip(z, unit)]


def check_vectors(row):
    failure = row["failure"]
    snapshot = failure["snapshot"]
    # serde f32 JSON uses decimal round-trip strings; recover the stored bits.
    base = list(map(f32, snapshot["base"]))
    target = list(map(f32, snapshot["true_target"]))
    axis = snapshot["masked_acquisition_axis"]
    p = [t - b for t, b in zip(target, base)]
    assert len(set(snapshot["support_indices"])) == len(base)
    assert all(0 <= x <= 2 for x in base + target)
    actual_cos = cosine(p, axis)
    actual_norm = norm(p)
    assert math.isclose(actual_cos, failure["true_axis_cosine"], abs_tol=1e-12)
    assert math.isclose(actual_norm, failure["target_l2"], rel_tol=1e-12)
    receipt = dict(condition=row["condition"], support_size=len(base),
                   reversal_trial=failure["reversal_trial"],
                   independently_computed_true_l2=actual_norm,
                   independently_computed_true_axis_cosine=actual_cos,
                   base_lower_count=sum(x == 0 for x in base),
                   agrees_with_rust_receipt=True)
    return receipt, base, p, axis


def replay_candidates(base, p, axis, key):
    a_norm = norm(axis)
    a_unit = [x / a_norm for x in axis]
    p_orth = project_out(p, a_unit)
    p_norm = norm(p_orth)
    p_unit = [x / p_norm for x in p_orth]
    p_target_norm = norm(p)
    failures = []
    max_cos = 0.0
    for attempt in range(64):
        rng = Counter(key ^ attempt)
        permutation = list(range(len(base)))
        for i in range(len(base) - 1, 0, -1):
            j = rng.next() % (i + 1)
            permutation[i], permutation[j] = permutation[j], permutation[i]
        z = [p[i] * (1 if rng.next() & 1 == 0 else -1) for i in permutation]
        for unit in (a_unit, p_unit, a_unit, p_unit):
            z = project_out(z, unit)
        scale = p_target_norm / norm(z)
        update = [scale * x for x in z]
        max_cos = max(max_cos, abs(cosine(update, axis)), abs(cosine(update, p)))
        targets = [b + n for b, n in zip(base, update)]
        bad = [i for i, value in enumerate(targets) if value < 0 or value > 2]
        assert bad, "A candidate passed bounds; investigate disagreement with Rust"
        failures.append(dict(attempt=attempt + 1, violating_coordinates=len(bad),
                             min_target=min(targets), max_target=max(targets)))
    return dict(attempts=64, independently_reproduced_bound_rejections=len(failures),
                min_violating_coordinates=min(x["violating_coordinates"] for x in failures),
                max_violating_coordinates=max(x["violating_coordinates"] for x in failures),
                max_ideal_null_cosine=max_cos, candidates=failures,
                claim="Specified 64 candidates fail; no claim of global infeasibility")


if __name__ == "__main__":
    data = json.loads(SOURCE.read_text())
    key = (data["seed"] ^ rotate(struct.unpack("<I", struct.pack("<f", data["tau"]))[0], 17)
           ^ rotate(ord(data["side"]), 7) ^ SALT)
    results = []
    for row in data["null_constructor"]:
        receipt, base, p, axis = check_vectors(row)
        if row["condition"] == "parallel_null":
            receipt["independent_candidate_replay"] = replay_candidates(base, p, axis, key)
        results.append(receipt)
    output = dict(status="QUALIFICATION_FAILURE_INDEPENDENTLY_REPRODUCED",
                  input_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                  source=str(SOURCE), method="Python stdlib, f32 bit recovery, math.fsum",
                  measured_samples_added=0, results=results)
    with Path(__file__).with_name("snapshot_audit.json").open("x", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
        f.write("\n")
    for receipt in results:
        replay = receipt.get("independent_candidate_replay")
        if replay:
            replay.pop("candidates")
    print(json.dumps(output, indent=2))
