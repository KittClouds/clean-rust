"""Descriptive post hoc shape audit for the sealed DH-08A event-local result."""

import csv
import hashlib
import json
import math
import pathlib
import statistics
import sys

T_CRIT_975_DF31 = 2.0395134463964077
WINDOWS = ("1-16", "17-32", "33-64", "65-128", "129-256")


def digest(path):
    with pathlib.Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def interval(values):
    assert len(values) == 32 and all(math.isfinite(value) for value in values)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values)
    radius = T_CRIT_975_DF31 * sd / math.sqrt(32)
    return {
        "mean": mean,
        "t_ci95": [mean - radius, mean + radius],
        "positive_seed_bundles": sum(value > 0 for value in values),
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: analyze_shape.py SEALED_RUN")
    run = pathlib.Path(sys.argv[1]).resolve()
    out = pathlib.Path(__file__).resolve().parent
    official = json.loads((run / "analysis/summary.json").read_text())
    assert official["protocol"] == "DH-08A" and official["status"] == "INCONCLUSIVE"
    seed_rows = list(csv.DictReader((run / "analysis/seeds.csv").open(newline="")))
    event_rows = list(csv.DictReader((run / "analysis/events.csv").open(newline="")))
    assert len(seed_rows) == 32 and len(event_rows) == 32_768

    seeds = [(int(row["seed"]), float(row["primary_true_minus_null"])) for row in seed_rows]
    ordered = sorted(seeds, key=lambda item: item[1])
    leave_one_out = {
        str(seed): statistics.fmean(value for other, value in seeds if other != seed)
        for seed, _ in seeds
    }
    tau_windows = {}
    for tau in (4.0, 16.0):
        for window in WINDOWS:
            values = []
            for seed in range(8000, 8032):
                repeated = [
                    float(row["true_minus_null"])
                    for row in event_rows
                    if int(row["seed"]) == seed
                    and float(row["tau"]) == tau
                    and row["window"] == window
                ]
                assert len(repeated) in (32, 64, 128, 256)
                values.append(statistics.fmean(repeated))
            tau_windows[f"tau_{tau:g}_window_{window}"] = interval(values)

    summary = {
        "kind": "POST_HOC_DESCRIPTIVE_NO_NEW_SAMPLES",
        "parent_run": str(run),
        "parent_seal_sha256": digest(run / "seal.json"),
        "official_status_unchanged": official["status"],
        "seed_shape": {
            "positive": sum(value > 0 for _, value in seeds),
            "negative": sum(value < 0 for _, value in seeds),
            "median": statistics.median(value for _, value in seeds),
            "one_each_tail_trimmed_mean": statistics.fmean(value for _, value in ordered[1:-1]),
            "minimum": ordered[0],
            "maximum": ordered[-1],
            "leave_one_out_mean_range": [min(leave_one_out.values()), max(leave_one_out.values())],
        },
        "exploratory_tau_by_window": tau_windows,
        "limitations": [
            "No new samples and no confirmatory claim.",
            "Tau-by-window interaction was inspected after the primary result.",
            "Intervals are descriptive seed-level t intervals without multiplicity adjustment.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    report = f"""# DH-08A Post Hoc Shape Audit

The frozen result remains `INCONCLUSIVE`. No sample was added.

- Positive seed means: {summary['seed_shape']['positive']} / 32
- Median: {summary['seed_shape']['median']:.12g}
- One-per-tail trimmed mean: {summary['seed_shape']['one_each_tail_trimmed_mean']:.12g}
- Leave-one-out mean range: [{summary['seed_shape']['leave_one_out_mean_range'][0]:.12g}, {summary['seed_shape']['leave_one_out_mean_range'][1]:.12g}]

The positive mean is not created by one seed: every leave-one-out mean remains positive. The sign is
still heterogeneous across seeds. Exploratory tau-by-window summaries show no resolved tau-4 window,
while tau 16 becomes positively separated from zero in windows 65-128 and 129-256. This is a
hypothesis generator for a fresh-seed temporal-mechanism study, not a revised DH-08A finding.
"""
    (out / "REPORT.md").write_text(report)
    manifest = {
        "parent_inputs": {
            "seal.json": digest(run / "seal.json"),
            "analysis/summary.json": digest(run / "analysis/summary.json"),
            "analysis/seeds.csv": digest(run / "analysis/seeds.csv"),
            "analysis/events.csv": digest(run / "analysis/events.csv"),
        },
        "outputs": {
            "analyze_shape.py": digest(out / "analyze_shape.py"),
            "summary.json": digest(out / "summary.json"),
            "REPORT.md": digest(out / "REPORT.md"),
        },
        "scientific_sample_size_increased": False,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
