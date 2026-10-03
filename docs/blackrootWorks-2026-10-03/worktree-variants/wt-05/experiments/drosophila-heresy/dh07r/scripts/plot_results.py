"""Create a dependency-free SVG figure from archived DH-07R analysis outputs."""

import csv
import html
import json
import pathlib
import sys


def scale(value, low, high, left, right):
    return left + (value - low) * (right - left) / (high - low)


run = pathlib.Path(sys.argv[1]).resolve()
analysis = run / "analysis"
summary = json.loads((analysis / "summary.json").read_text())
with (analysis / "seed_contrasts.csv").open(newline="") as handle:
    rows = list(csv.DictReader(handle))

values = [float(row["primary_true_minus_null"]) for row in rows]
secondary = summary["descriptive"]["paired_seed_intervals"]
contexts = [
    ("Parallel off", secondary["parallel_off_true_minus_null"]),
    ("Parallel on", secondary["parallel_on_true_minus_null"]),
    ("Averaged primary", summary["primary"]),
]
all_limits = values + [number for _, item in contexts for number in item["t_ci95"]] + [0.0]
pad = max(0.001, (max(all_limits) - min(all_limits)) * 0.12)
x_low, x_high = min(all_limits) - pad, max(all_limits) + pad
left, right = 105, 930
width, height = 1000, 600
parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
    '<rect width="100%" height="100%" fill="#fbfaf7"/>',
    '<style>text{font-family:Segoe UI,Arial,sans-serif;fill:#18212a}.title{font-size:24px;font-weight:700}.sub{font-size:14px;fill:#52606b}.label{font-size:14px}.tick{font-size:12px;fill:#52606b}.axis{stroke:#6b7680;stroke-width:1}.zero{stroke:#b42318;stroke-width:1.5;stroke-dasharray:6 5}.ci{stroke:#155eef;stroke-width:4}.point{fill:#0e7490;fill-opacity:.7}.mean{fill:#155eef}</style>',
    '<text x="55" y="42" class="title">DH-07R realized residual-direction effect</text>',
    '<text x="55" y="66" class="sub">True endogenous residual minus feasible matched null; negative values favor direction-specific suppression</text>',
]
zero_x = scale(0.0, x_low, x_high, left, right)
parts.append(f'<line x1="{zero_x:.2f}" y1="92" x2="{zero_x:.2f}" y2="538" class="zero"/>')

parts.append('<text x="55" y="108" class="label" font-weight="700">A. Paired seed-bundle effects</text>')
for index, value in enumerate(sorted(values)):
    row = index // 16
    slot = index % 16
    y = 138 + row * 54 + (slot % 4 - 1.5) * 5
    x = scale(value, x_low, x_high, left, right)
    parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" class="point"><title>{value:+.8f}</title></circle>')

parts.append('<text x="55" y="270" class="label" font-weight="700">B. Mean effects and paired 95% t intervals</text>')
for index, (label, item) in enumerate(contexts):
    y = 315 + index * 67
    lo, hi = item["t_ci95"]
    mean = item["mean"]
    x1, x2, xm = (scale(value, x_low, x_high, left, right) for value in (lo, hi, mean))
    parts += [
        f'<text x="55" y="{y + 5}" class="label">{html.escape(label)}</text>',
        f'<line x1="{x1:.2f}" y1="{y}" x2="{x2:.2f}" y2="{y}" class="ci"/>',
        f'<line x1="{x1:.2f}" y1="{y - 8}" x2="{x1:.2f}" y2="{y + 8}" class="ci"/>',
        f'<line x1="{x2:.2f}" y1="{y - 8}" x2="{x2:.2f}" y2="{y + 8}" class="ci"/>',
        f'<circle cx="{xm:.2f}" cy="{y}" r="7" class="mean"><title>{mean:+.8f} [{lo:+.8f}, {hi:+.8f}]</title></circle>',
    ]

axis_y = 538
parts.append(f'<line x1="{left}" y1="{axis_y}" x2="{right}" y2="{axis_y}" class="axis"/>')
for index in range(6):
    value = x_low + index * (x_high - x_low) / 5
    x = scale(value, x_low, x_high, left, right)
    parts += [
        f'<line x1="{x:.2f}" y1="{axis_y}" x2="{x:.2f}" y2="{axis_y + 7}" class="axis"/>',
        f'<text x="{x:.2f}" y="{axis_y + 24}" text-anchor="middle" class="tick">{value:+.4f}</text>',
    ]
parts.append('<text x="517" y="590" text-anchor="middle" class="label">Old-map margin difference at reversal trial 256</text>')
parts.append('</svg>')
(analysis / "dh07r_direction_effect.svg").write_text("\n".join(parts) + "\n", encoding="utf-8")
print(analysis / "dh07r_direction_effect.svg")
