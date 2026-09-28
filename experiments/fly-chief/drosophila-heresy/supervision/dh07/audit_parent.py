"""Read-only ancestor verification and independent mathematical control checks.

Writes only a supervisor receipt; never modifies an experimental ancestor.
Run with the DH06 pinned Python. No fresh scientific seeds are evaluated.
"""
from pathlib import Path
import hashlib
import json
import math

BASE = Path(__file__).resolve().parents[2]
RUNS = [
    ("DH01", "artifacts/runs/20260912T032529Z"),
    ("DH02", "dh02/artifacts/runs/20260912T040045Z"),
    ("DH03", "dh03/artifacts/runs/20260912T042145Z"),
    ("DH04", "dh04/artifacts/runs/20260912T044912Z"),
    ("DH05", "dh05/artifacts/runs/20260915T184423Z"),
    ("DH06", "dh06/artifacts/runs/20260915T201008Z"),
]


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def verify(name, relative):
    run = BASE / relative
    seal = json.loads((run / "seal.json").read_text())
    completion = json.loads((run / "completion.json").read_text())
    assert digest(run / "seal.json") == completion["seal_sha256"]
    for key, expected in seal["fingerprints"].items():
        assert digest(run / "sealed" / key) == expected, (name, key)
    for key, expected in completion["output_hashes"].items():
        assert digest(run / key) == expected, (name, key)
    return dict(study=name, seal_sha256=completion["seal_sha256"],
                frozen_files=len(seal["fingerprints"]),
                output_files=len(completion["output_hashes"]))


def clipping_example():
    # Bounded counterfactual states; D is supported on both coordinates.
    base = [0.0, 1.0]
    retained = [0.1, 1.4]
    axis = [1.0, 1.0]
    delta = [r - b for r, b in zip(retained, base)]
    coefficient = sum(d * a for d, a in zip(delta, axis)) / 2
    perp = [d - coefficient * a for d, a in zip(delta, axis)]
    delivered = [min(2.0, max(0.0, b + p)) - b
                 for b, p in zip(base, perp)]
    assert abs(sum(perp)) < 1e-15
    assert sum(delivered) > 0.14
    return dict(kind="mathematical fixture, not an observed DH06 event",
                base=base, retained=retained, axis=axis,
                intended_perpendicular=perp, delivered=delivered,
                intended_axis_dot=sum(perp), delivered_axis_dot=sum(delivered))


def observed_controls():
    run = BASE / RUNS[-1][1]
    bundles = 0
    for path in sorted(run.glob("*-tau*.jsonl")):
        for line in path.read_text().splitlines():
            bundle = json.loads(line)
            rows = bundle["results"]
            for arm in ("E", "Z"):
                hashes = {tuple(r["result"]["acquisition_state_sha256"])
                          for r in rows if r["arm"] == arm}
                assert len(hashes) == 1
            controls = [r["result"] for r in rows if r["arm"] == "Z"]
            fields = ("accuracy", "acquisition", "reversal", "curve",
                      "probe_acquisition", "probe_reversal", "changed_weights")
            reference = {k: controls[0]["outcome"][k] for k in fields}
            for control in controls:
                assert {k: control["outcome"][k] for k in fields} == reference
            for r in rows:
                for point in r["result"]["trajectory"]:
                    assert point["old_map_margin"] == -point["reversed_map_margin"]
                assert r["result"]["outcome"]["hot_allocations"] == 0
            bundles += 1
    return dict(bundles=bundles, recorded_Z_behavior_parity=True,
                acquisition_hash_parity=True, complementary_margins=True,
                hot_allocations_zero=True,
                limitation="DH06 did not persist trial action hashes or delivered geometry")


if __name__ == "__main__":
    receipt = dict(ancestor_integrity=[verify(*r) for r in RUNS],
                   dh06_recorded_controls=observed_controls(),
                   clipping_counterexample=clipping_example(),
                   geometry_feasibility_note=(
                       "At a lower-bound corner WB=0 with strictly positive A, "
                       "every feasible nonnegative N with N dot A=0 is zero. "
                       "High support dimension alone does not imply a feasible null."),
                   interpretation_limits=[
                       "E has uniform modulation; no anatomy-specific routing inference.",
                       "Reward is action-dependent; shared RNG does not force shared rewards.",
                       "Acquisition coordinate is a geometric summary, not proof of latent memory.",
                       "DH06 perpendicular trajectory norm is normalized; parallel projection is raw.",
                       "Same-snapshot matched energy is not equal cumulative exposure across arms.",
                   ])
    output = Path(__file__).with_name("parent_audit.json")
    with output.open("x", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
        f.write("\n")
    print(json.dumps(receipt, indent=2))
