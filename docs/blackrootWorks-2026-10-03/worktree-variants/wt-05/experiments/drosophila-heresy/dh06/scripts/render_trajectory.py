"""Render a dependency-free SVG from the frozen DH-05 trajectory summary."""
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
conditions = ["eligibility_retained", "eligibility_suppressed"]
labels = {"eligibility_retained": "Eligibility retained", "eligibility_suppressed": "Eligibility suppressed"}
colors = {"eligibility_retained": "#c65f32", "eligibility_suppressed": "#19766f"}
W, H = 1120, 760
panels = [(75, 145, 465, 270), (585, 145, 465, 270), (75, 480, 465, 210), (585, 480, 465, 210)]


def esc(value):
    return html.escape(str(value))


def scale(value, lo, hi, start, length):
    return start + (value - lo) / (hi - lo) * length


def path_for(values, panel, lo, hi):
    x, y, width, height = panel
    return " ".join(f"{scale(checkpoint, checkpoints[0], checkpoints[-1], x, width):.2f},{y + height - scale(value, lo, hi, 0, height):.2f}" for checkpoint, value in zip(checkpoints, values))


def panel_svg(panel, field, title, ylabel, lo, hi, ticks, zero=False):
    x, y, width, height = panel
    parts = [f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="none" stroke="#b7b7b7"/>']
    for tick in ticks:
        py = y + height - scale(tick, lo, hi, 0, height)
        parts.append(f'<line x1="{x}" y1="{py:.2f}" x2="{x + width}" y2="{py:.2f}" stroke="#dddddd"/>')
        parts.append(f'<text x="{x - 10}" y="{py + 4:.2f}" text-anchor="end" class="tick">{esc(f"{tick:.2f}")}</text>')
    if zero and lo < 0 < hi:
        py = y + height - scale(0, lo, hi, 0, height)
        parts.append(f'<line x1="{x}" y1="{py:.2f}" x2="{x + width}" y2="{py:.2f}" stroke="#777" stroke-dasharray="5 4"/>')
    for condition in conditions:
        values = trajectory[condition][field]
        parts.append(f'<polyline points="{path_for(values, panel, lo, hi)}" fill="none" stroke="{colors[condition]}" stroke-width="3"/>')
        for checkpoint, value in zip(checkpoints, values):
            px = scale(checkpoint, checkpoints[0], checkpoints[-1], x, width)
            py = y + height - scale(value, lo, hi, 0, height)
            parts.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="4" fill="{colors[condition]}"/>')
    for checkpoint in checkpoints:
        px = scale(checkpoint, checkpoints[0], checkpoints[-1], x, width)
        parts.append(f'<text x="{px:.2f}" y="{y + height + 22}" text-anchor="middle" class="tick">{checkpoint}</text>')
    parts.append(f'<text x="{x}" y="{y - 18}" class="panel-title">{esc(title)}</text>')
    parts.append(f'<text x="{x - 54}" y="{y + height / 2:.2f}" transform="rotate(-90 {x - 54} {y + height / 2:.2f})" text-anchor="middle" class="axis">{esc(ylabel)}</text>')
    return "\n".join(parts)


svg = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
    '<style>text{font-family:Arial,sans-serif;fill:#252525}.title{font-size:22px;font-weight:600}.subtitle{font-size:14px;fill:#555}.panel-title{font-size:15px;font-weight:600}.axis{font-size:12px}.tick{font-size:11px;fill:#555}.legend{font-size:13px}</style>',
    '<text x="75" y="42" class="title">DH-05: interval eligibility accelerates old-map destabilization</text>',
    '<text x="75" y="70" class="subtitle">Right soma slice | 24 fresh seed bundles | state restored in both causal cells | means across taus and seeds</text>',
    panel_svg(panels[0], "old_map_margin", "Old-map expression", "Old-map margin", -0.01, 0.055, [-0.00, 0.02, 0.04, 0.05]),
    panel_svg(panels[1], "acquisition_axis_coordinate", "Acquired structure retained", "Acquisition-axis coordinate", 0.55, 1.02, [0.6, 0.8, 1.0]),
    panel_svg(panels[2], "reversal_parallel_projection", "Movement along anti-acquisition axis", "Parallel projection", -7.0, 0.2, [-6, -4, -2, 0], zero=True),
    panel_svg(panels[3], "reversal_perpendicular_norm", "Movement outside acquisition axis", "Perpendicular norm", 0.0, 1.05, [0, 0.3, 0.6, 0.9]),
    '<line x1="760" y1="95" x2="780" y2="95" stroke="#c65f32" stroke-width="3"/><circle cx="770" cy="95" r="4" fill="#c65f32"/><text x="790" y="100" class="legend">Eligibility retained</text>',
    '<line x1="940" y1="95" x2="960" y2="95" stroke="#19766f" stroke-width="3"/><circle cx="950" cy="95" r="4" fill="#19766f"/><text x="970" y="100" class="legend">Eligibility suppressed</text>',
    f'<text x="75" y="730" class="subtitle">Final old-map probe: {100 * summary["primary"]["retained_minus_suppressed_final_old_probe"]["mean"]:+.2f} pp; acquisition-axis projection: {summary["primary"]["retained_minus_suppressed_final_acquisition_axis_projection"]["mean"]:+.3f}</text>',
    '</svg>',
]
(out / "dh05-results.svg").write_text("\n".join(svg), encoding="utf-8")
receipt = {"summary_sha256": digest(run / "summary.json"), "statistics_recomputed": False, "renderer": "dependency-free Python SVG writer", "output_hashes": {"dh05-results.svg": digest(out / "dh05-results.svg")}}
(out / "plot-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(out / "dh05-results.svg")
