"""Render a dependency-free SVG from the sealed DH06 summary."""
import hashlib
import html
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


run = pathlib.Path(sys.argv[1]).resolve()
completion = json.loads((run / "completion.json").read_text())
assert digest(run / "summary.json") == completion["output_hashes"]["summary.json"]
summary = json.loads((run / "summary.json").read_text())
out = ROOT / "artifacts/figures" / run.name
out.mkdir(parents=True, exist_ok=True)
checkpoints = summary["checkpoints"]
trajectory = summary["trajectory_means"]
conditions = ["neither", "parallel_only", "perpendicular_only", "both"]
labels = {"neither": "Neither", "parallel_only": "Parallel only", "perpendicular_only": "Perpendicular only", "both": "Both"}
colors = {"neither": "#777777", "parallel_only": "#c65f32", "perpendicular_only": "#19766f", "both": "#7256a5"}
W, H = 1160, 790
panels = [(90, 145, 455, 255), (625, 145, 455, 255), (90, 485, 455, 220), (625, 485, 455, 220)]


def esc(value):
    return html.escape(str(value))


def scale(value, lo, hi, start, length):
    return start + (value - lo) / (hi - lo) * length


def draw(panel, field, title, ylabel, lo, hi, ticks):
    x, y, width, height = panel
    parts = [f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="none" stroke="#b7b7b7"/>']
    for tick in ticks:
        py = y + height - scale(tick, lo, hi, 0, height)
        parts.append(f'<line x1="{x}" y1="{py:.2f}" x2="{x + width}" y2="{py:.2f}" stroke="#dddddd"/>')
        parts.append(f'<text x="{x - 12}" y="{py + 4:.2f}" text-anchor="end" class="tick">{tick:.2f}</text>')
    for condition in conditions:
        values = trajectory[condition][field]
        points = " ".join(f"{scale(c, checkpoints[0], checkpoints[-1], x, width):.2f},{y + height - scale(v, lo, hi, 0, height):.2f}" for c, v in zip(checkpoints, values))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{colors[condition]}" stroke-width="3"/>')
        for checkpoint, value in zip(checkpoints, values):
            px = scale(checkpoint, checkpoints[0], checkpoints[-1], x, width)
            py = y + height - scale(value, lo, hi, 0, height)
            parts.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="4" fill="{colors[condition]}"/>')
    for checkpoint in checkpoints:
        px = scale(checkpoint, checkpoints[0], checkpoints[-1], x, width)
        parts.append(f'<text x="{px:.2f}" y="{y + height + 22}" text-anchor="middle" class="tick">{checkpoint}</text>')
    parts.append(f'<text x="{x}" y="{y - 18}" class="panel-title">{esc(title)}</text>')
    parts.append(f'<text x="{x - 55}" y="{y + height / 2:.2f}" transform="rotate(-90 {x - 55} {y + height / 2:.2f})" text-anchor="middle" class="axis">{esc(ylabel)}</text>')
    return "\n".join(parts)


primary_old = summary["primary"]["perpendicular_effect_on_old_map_margin"]
primary_axis = summary["primary"]["parallel_effect_on_acquisition_axis_coordinate"]
svg = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
    '<style>text{font-family:Arial,sans-serif;fill:#252525}.title{font-size:22px;font-weight:600}.subtitle{font-size:14px;fill:#555}.panel-title{font-size:15px;font-weight:600}.axis{font-size:12px}.tick{font-size:11px;fill:#555}.legend{font-size:13px}</style>',
    '<text x="90" y="42" class="title">DH-06: aligned erosion and off-axis reconfiguration are separable</text>',
    '<text x="90" y="70" class="subtitle">Right soma slice | 32 fresh seed bundles | realized clipped updates | state restored in all causal cells</text>',
    draw(panels[0], "old_map_margin", "Old-map expression", "Old-map margin", -0.01, 0.055, [0, 0.02, 0.04, 0.05]),
    draw(panels[1], "acquisition_axis_coordinate", "Acquired structure retained", "Acquisition-axis coordinate", 0.55, 1.02, [0.6, 0.8, 1.0]),
    draw(panels[2], "reversal_parallel_projection", "Parallel movement", "Parallel projection", -8.0, 0.2, [-6, -4, -2, 0]),
    draw(panels[3], "reversal_perpendicular_norm", "Perpendicular movement", "Perpendicular norm", 0.0, 1.05, [0, 0.3, 0.6, 0.9]),
    '<text x="780" y="95" class="legend"><tspan fill="#777">■ Neither</tspan><tspan dx="24" fill="#c65f32">■ Parallel only</tspan><tspan dx="24" fill="#19766f">■ Perpendicular only</tspan><tspan dx="24" fill="#7256a5">■ Both</tspan></text>',
    f'<text x="90" y="748" class="subtitle">Perpendicular effect on old-map margin: {primary_old["mean"]:+.4f} [{primary_old["ci97_5"][0]:+.4f}, {primary_old["ci97_5"][1]:+.4f}]; parallel effect on acquisition coordinate: {primary_axis["mean"]:+.4f} [{primary_axis["ci97_5"][0]:+.4f}, {primary_axis["ci97_5"][1]:+.4f}]</text>',
    '</svg>',
]
(out / "dh06-results.svg").write_text("\n".join(svg), encoding="utf-8")
receipt = {"summary_sha256": digest(run / "summary.json"), "statistics_recomputed": False, "renderer": "dependency-free Python SVG writer", "output_hashes": {"dh06-results.svg": digest(out / "dh06-results.svg")}}
(out / "plot-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(out / "dh06-results.svg")
