"""Render the hash-verified frozen DH03 summary without recomputing inference."""
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

conditions = [
    "immediate",
    "quiet",
    "retain_both",
    "suppress_eligibility",
    "restore_state",
    "suppress_both",
]
labels = [
    "Immediate",
    "Quiet",
    "Retain\nboth",
    "Suppress\neligibility",
    "Restore\nstate",
    "Suppress\nboth",
]
colors = ["#247c73", "#7c799f", "#d06f3e", "#ba9c45", "#d06f3e", "#ba9c45"]
values = [100 * means[condition]["probe_reversal"] for condition in conditions]

plt.rcParams.update(
    {"font.size": 10, "axes.spines.top": False, "axes.spines.right": False}
)
fig, (left, right) = plt.subplots(
    1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [1.35, 1]}
)
fig.subplots_adjust(left=0.065, right=0.98, bottom=0.25, top=0.72, wspace=0.28)
fig.suptitle(
    "DH-03: interval eligibility helped; retained neural state did not",
    x=0.04,
    ha="left",
    y=0.965,
    fontsize=15,
)
fig.text(
    0.04,
    0.855,
    "Identical acquired states | 24 fresh seed bundles | two eligibility settings | right soma slice",
    fontsize=10,
    color="#555555",
)

left.bar(labels, values, color=colors, width=0.7)
for index, value in enumerate(values):
    left.text(index, value + 1.6, f"{value:.2f}%", ha="center", fontsize=9)
left.axhline(50, color="#777777", linestyle="--", linewidth=1)
left.set_ylim(0, 65)
left.set_ylabel("Final reversal-probe accuracy (%)")
left.set_title("Anchors and factorial cells", loc="left", fontsize=12)

x = [0, 1]
retained = [
    100 * means["suppress_eligibility"]["probe_reversal"],
    100 * means["retain_both"]["probe_reversal"],
]
restored = [
    100 * means["suppress_both"]["probe_reversal"],
    100 * means["restore_state"]["probe_reversal"],
]
right.plot(x, retained, "-o", color="#555555", label="State retained")
right.plot(x, restored, "-o", color="#3c8fca", label="State restored")
right.axhline(50, color="#999999", linestyle=":", linewidth=1)
right.set_xticks(x, ["Eligibility\nsuppressed", "Eligibility\nretained"])
right.set_xlim(-0.25, 1.25)
right.set_ylim(28, 52)
right.set_ylabel("Final reversal-probe accuracy (%)")
right.set_title("Causal 2×2 split", loc="left", fontsize=12)
right.legend(frameon=False, loc="upper left")

eligibility = summary["co_primary"]["eligibility_retained"]
state = summary["co_primary"]["state_retained"]
fig.text(
    0.04,
    0.13,
    f"Eligibility retained: {100 * eligibility['mean']:+.2f} pp, familywise 97.5% interval "
    f"[{100 * eligibility['ci97.5'][0]:+.2f}, {100 * eligibility['ci97.5'][1]:+.2f}].   "
    f"State retained: {100 * state['mean']:+.2f} pp "
    f"[{100 * state['ci97.5'][0]:+.2f}, {100 * state['ci97.5'][1]:+.2f}].",
    fontsize=10.5,
)
fig.text(
    0.04,
    0.055,
    "Both eligibility-retained cells remained below chance; mechanism beyond the two channel interventions was not established.",
    fontsize=9,
    color="#555555",
)
for extension in ["png", "svg"]:
    fig.savefig(out / f"dh03-results.{extension}", dpi=160, facecolor="white")
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
print(out / "dh03-results.png")
