"""Render frozen DH04 results after verifying the sealed summary hash."""
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / ".plot-deps"))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


run = pathlib.Path(sys.argv[1]).resolve()
completion = json.loads((run / "completion.json").read_text())
assert digest(run / "summary.json") == completion["output_hashes"]["summary.json"]
summary = json.loads((run / "summary.json").read_text())
means = summary["means"]["R"]["E"]
out = ROOT / "artifacts/figures" / run.name
out.mkdir(parents=True, exist_ok=True)

conditions = ["immediate", "quiet", "eligibility_retained", "eligibility_suppressed"]
labels = ["Immediate", "Quiet", "Eligibility\nretained", "Eligibility\nsuppressed"]
colors = ["#237c73", "#7c799f", "#d06f3e", "#ba9c45"]
reversed_probe = [100 * means[c]["paired_final_reversal_probe"] for c in conditions]
coordinate = [
    means[c]["weight_geometry"]["acquisition_axis_coordinate"] for c in conditions
]
old_margin = [means[c]["weight_geometry"]["final_old_map_margin"] for c in conditions]

plt.rcParams.update(
    {"font.size": 9.5, "axes.spines.top": False, "axes.spines.right": False}
)
fig, axes = plt.subplots(1, 3, figsize=(13.2, 5))
fig.subplots_adjust(left=0.06, right=0.985, bottom=0.25, top=0.7, wspace=0.32)
fig.suptitle(
    "DH-04: distractor eligibility partially erased the acquired mapping",
    x=0.04,
    ha="left",
    y=0.96,
    fontsize=15,
)
fig.text(
    0.04,
    0.845,
    "Same acquired states | 24 fresh seed bundles | state restored in both causal cells | right soma slice",
    fontsize=10,
    color="#555555",
)

axes[0].bar(labels, reversed_probe, color=colors, width=0.7)
for index, value in enumerate(reversed_probe):
    axes[0].text(index, value + 1.4, f"{value:.2f}%", ha="center", fontsize=8.5)
axes[0].axhline(50, color="#777777", linestyle="--", linewidth=1)
axes[0].set_ylim(0, 62)
axes[0].set_ylabel("Same-RNG reversed probe (%)")
axes[0].set_title("Reversal behavior", loc="left", fontsize=11)

axes[1].bar(labels, coordinate, color=colors, width=0.7)
for index, value in enumerate(coordinate):
    axes[1].text(index, value + 0.025, f"{value:.3f}", ha="center", fontsize=8.5)
axes[1].axhline(1, color="#777777", linestyle="--", linewidth=1, label="Acquired")
axes[1].axhline(0, color="#999999", linestyle=":", linewidth=1, label="Initial")
axes[1].set_ylim(0, 1.12)
axes[1].set_ylabel("Acquisition-axis coordinate")
axes[1].set_title("Weight-axis retention", loc="left", fontsize=11)
axes[1].legend(frameon=False, fontsize=8, loc="lower left")

axes[2].bar(labels, old_margin, color=colors, width=0.7)
for index, value in enumerate(old_margin):
    offset = 0.0015 if value >= 0 else -0.003
    axes[2].text(index, value + offset, f"{value:+.3f}", ha="center", fontsize=8.5)
axes[2].axhline(0, color="#777777", linestyle="--", linewidth=1)
axes[2].set_ylim(-0.012, 0.043)
axes[2].set_ylabel("Deterministic old-map margin")
axes[2].set_title("Mapping preference", loc="left", fontsize=11)

components = summary["primary_components"]
effect = components["retained_minus_suppressed_reversal_probe"]
axis_effect = components["retained_minus_suppressed_acquisition_axis"]
fig.text(
    0.04,
    0.13,
    f"Eligibility retained: reversal {100 * effect['mean']:+.2f} pp "
    f"[{100 * effect['ci95'][0]:+.2f}, {100 * effect['ci95'][1]:+.2f}]; "
    f"acquisition-axis shift {axis_effect['mean']:+.3f} "
    f"[{axis_effect['ci95'][0]:+.3f}, {axis_effect['ci95'][1]:+.3f}].",
    fontsize=10.5,
)
fig.text(
    0.04,
    0.055,
    "Retained eligibility improved reversal but stopped between initial and acquired weights with the old mapping still preferred.",
    fontsize=9,
    color="#555555",
)
for extension in ["png", "svg"]:
    fig.savefig(out / f"dh04-results.{extension}", dpi=160, facecolor="white")
plt.close(fig)
receipt = {
    "summary_sha256": digest(run / "summary.json"),
    "statistics_recomputed": False,
    "matplotlib_version": matplotlib.__version__,
    "output_hashes": {
        path.name: digest(path)
        for path in out.iterdir()
        if path.suffix in [".png", ".svg"]
    },
}
(out / "plot-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(out / "dh04-results.png")
