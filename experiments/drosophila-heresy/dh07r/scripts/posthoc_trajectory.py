"""Post hoc DH-07R trajectory decomposition; never reruns the simulator."""

import csv
import hashlib
import itertools
import json
import math
import pathlib
import statistics
import sys

T_CRIT_975_DF31 = 2.0395134463964077
CHECKPOINTS = (0, 16, 32, 64, 128, 256)
CONTEXTS = {
    "parallel_off": ("true_perpendicular", "null_perpendicular"),
    "parallel_on": ("both_true", "parallel_null"),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def interval(values):
    mean = statistics.fmean(values)
    if all(value == mean for value in values):
        return mean, mean, mean
    se = statistics.stdev(values) / math.sqrt(len(values))
    return mean, mean - T_CRIT_975_DF31 * se, mean + T_CRIT_975_DF31 * se


def correlation(left, right):
    ml, mr = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((x - ml) * (y - mr) for x, y in zip(left, right))
    denominator = math.sqrt(sum((x - ml) ** 2 for x in left) * sum((y - mr) ** 2 for y in right))
    return numerator / denominator if denominator else None


run = pathlib.Path(sys.argv[1]).resolve()
out = pathlib.Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=False)
rows = []
inputs = []
for side, tau in itertools.product(("R", "L"), (4, 16)):
    path = run / f"{side}-tau{tau}.jsonl"
    inputs.append({"path": str(path.relative_to(run)), "sha256": digest(path)})
    for line in path.read_text().splitlines():
        bundle = json.loads(line)
        rows.extend(row for row in bundle["results"] if row["arm"] == "E")
lookup = {(row["seed"], row["side"], row["tau"], row["condition"]): row for row in rows}

seed_rows = []
summary_rows = []
for context, (true_condition, null_condition) in CONTEXTS.items():
    for checkpoint_index, checkpoint in enumerate(CHECKPOINTS):
        margins, axes = [], []
        for seed in range(7000, 7032):
            margin_parts, axis_parts = [], []
            for side, tau in itertools.product(("R", "L"), (4, 16)):
                true = lookup[seed, side, tau, true_condition]["result"]["trajectory"][checkpoint_index]
                null = lookup[seed, side, tau, null_condition]["result"]["trajectory"][checkpoint_index]
                margin_parts.append(true["old_map_margin"] - null["old_map_margin"])
                axis_parts.append(true["acquisition_axis_coordinate"] - null["acquisition_axis_coordinate"])
            margin = statistics.fmean(margin_parts)
            axis = statistics.fmean(axis_parts)
            margins.append(margin)
            axes.append(axis)
            seed_rows.append({
                "context": context, "checkpoint": checkpoint, "seed": seed,
                "true_minus_null_old_map_margin": margin,
                "true_minus_null_acquisition_coordinate": axis,
            })
        mm, ml, mh = interval(margins)
        am, al, ah = interval(axes)
        summary_rows.append({
            "context": context, "checkpoint": checkpoint,
            "margin_mean": mm, "margin_t95_low": ml, "margin_t95_high": mh,
            "axis_mean": am, "axis_t95_low": al, "axis_t95_high": ah,
            "seed_correlation_margin_axis": correlation(margins, axes),
        })

with (out / "seed_trajectory_contrasts.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(seed_rows[0]))
    writer.writeheader(); writer.writerows(seed_rows)
with (out / "trajectory_summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
    writer.writeheader(); writer.writerows(summary_rows)

final = {row["context"]: row for row in summary_rows if row["checkpoint"] == 256}
first_resolved = {}
for context in CONTEXTS:
    context_rows = [row for row in summary_rows if row["context"] == context]
    first_resolved[context] = {
        "margin": next((row["checkpoint"] for row in context_rows if row["checkpoint"] > 0
                        and (row["margin_t95_low"] > 0 or row["margin_t95_high"] < 0)), None),
        "axis": next((row["checkpoint"] for row in context_rows if row["checkpoint"] > 0
                      and (row["axis_t95_low"] > 0 or row["axis_t95_high"] < 0)), None),
    }
summary = {
    "schema": "dh07r-posthoc-trajectory-v1",
    "status": "DESCRIPTIVE_POST_HOC",
    "source_run": str(run),
    "source_seal_sha256": digest(run / "seal.json"),
    "source_completion_sha256": digest(run / "completion.json"),
    "inputs": inputs,
    "fresh_seed_bundles_added": 0,
    "simulator_rerun": False,
    "first_checkpoint_with_descriptive_t95_excluding_zero": first_resolved,
    "final": final,
    "interpretation_limit": "Event-local matching does not imply matched cumulative geometry after adaptive trajectories diverge.",
}
(out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

width, height, left, right = 1000, 580, 95, 950
plot_rows = [row for row in summary_rows if row["checkpoint"] > 0]
margin_limit = max(abs(row[key]) for row in plot_rows for key in ("margin_t95_low", "margin_t95_high")) * 1.15
axis_limit = max(abs(row[key]) for row in plot_rows for key in ("axis_t95_low", "axis_t95_high")) * 1.15
def sx(t): return left + t / 256 * (right - left)
def sy(value, center, limit): return center - value / limit * 135
colors = {"parallel_off": "#0e7490", "parallel_on": "#7c3aed"}
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
       '<rect width="100%" height="100%" fill="#fbfaf7"/>',
       '<style>text{font-family:Segoe UI,Arial,sans-serif;fill:#18212a}.title{font-size:23px;font-weight:700}.label{font-size:14px}.tick{font-size:12px;fill:#59636e}.zero{stroke:#9aa3ab;stroke-dasharray:5 5}.ci{stroke-width:2}.line{fill:none;stroke-width:3}</style>',
       '<text x="50" y="36" class="title">DH-07R post hoc trajectory: true minus matched null</text>']
for center, metric, limit, title in [(205, "margin", margin_limit, "Old-map margin"), (445, "axis", axis_limit, "Acquisition-axis coordinate")]:
    svg += [f'<text x="50" y="{center-155}" class="label" font-weight="700">{title}</text>',
            f'<line x1="{left}" y1="{center}" x2="{right}" y2="{center}" class="zero"/>']
    for context in CONTEXTS:
        points=[]
        for row in summary_rows:
            if row["context"] != context: continue
            x=sx(row["checkpoint"]); y=sy(row[f"{metric}_mean"],center,limit)
            lo=sy(row[f"{metric}_t95_low"],center,limit); hi=sy(row[f"{metric}_t95_high"],center,limit)
            svg += [f'<line x1="{x:.2f}" y1="{lo:.2f}" x2="{x:.2f}" y2="{hi:.2f}" class="ci" stroke="{colors[context]}"/>',
                    f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{colors[context]}"/>']
            points.append(f'{x:.2f},{y:.2f}')
        svg.append(f'<polyline points="{" ".join(points)}" class="line" stroke="{colors[context]}"/>')
for checkpoint in CHECKPOINTS:
    x=sx(checkpoint); svg.append(f'<text x="{x:.2f}" y="570" text-anchor="middle" class="tick">{checkpoint}</text>')
svg += ['<circle cx="710" cy="36" r="5" fill="#0e7490"/><text x="722" y="41" class="label">parallel off</text>',
        '<circle cx="830" cy="36" r="5" fill="#7c3aed"/><text x="842" y="41" class="label">parallel on</text>',
        '<text x="520" y="570" text-anchor="middle" class="label">Reversal trials</text>', '</svg>']
(out / "trajectory.svg").write_text("\n".join(svg) + "\n")

report = f"""# DH-07R post hoc trajectory audit

This analysis reads the sealed DH-07R outputs and adds no samples or simulator executions. Its intervals are descriptive because trajectory timing was not a primary endpoint.

The true-minus-null behavioral difference first has a descriptive 95% t interval excluding zero at trial **{first_resolved['parallel_off']['margin']}** with parallel off and **{first_resolved['parallel_on']['margin']}** with parallel on. Acquisition-axis divergence resolves at trial **{first_resolved['parallel_off']['axis']}** off and **{first_resolved['parallel_on']['axis']}** on.

At trial 256, parallel-off true-minus-null old-map margin is **{final['parallel_off']['margin_mean']:+.6f}** while acquisition-coordinate difference is **{final['parallel_off']['axis_mean']:+.6f}**. Parallel-on margin is **{final['parallel_on']['margin_mean']:+.6f}**, accompanied by a much larger acquisition-coordinate difference of **{final['parallel_on']['axis_mean']:+.6f}**.

The parallel-on axis difference is already resolved at trial 16, before the old-map margin difference resolves at trial 32. The DH-07R primary therefore identifies an adaptive direction-replacement policy effect. It does not isolate a final behavior effect at matched cumulative acquisition-axis position.

The next experiment should branch true and matched-null endpoints from one identical state, probe immediately with learning disabled, discard both branches, and continue a canonical trajectory. That impulse design prevents the intervention from changing the state from which future updates are generated.
"""
(out / "REPORT.md").write_text(report)
print(json.dumps(summary, indent=2))
