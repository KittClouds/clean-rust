"""Design-only C/D scale and variance summary from the sealed Q-R2 predictions.

No targets, metrics, checkpoints, or model inference are used. Probability values
are parsed as float64 and logged without clipping; any nonpositive/nonfinite
old/new probability fails the calculation closed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, variance
from typing import Any

RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
EVAL = RUN / "evaluation-v03"
RAW = EVAL / "raw-predictions-v01.jsonl"
COMPLETION = RUN / "provenance/q-r2-completion-seal-v06.json"
OUT = EVAL / "criterion-discriminability-sizing-v01"
ARMS = ("LATE_SHAM_1X", "LATE_SHAM_HALF")
VIEWS = ("anchor", "fact_flip")
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
SEEDS = (646142852, 4252058077, 1220728050, 2568717680, 3591276468, 1418365871,
         3679801188, 3460102370, 2742373327, 154863765, 2514222543, 3252782908,
         139770160, 4146187570, 3662026063, 3393901947, 147164975, 3776251307,
         1091781421, 3214909693, 642604459, 3342956466, 2210322644, 1629262270)
RAW_SHA = "39c3fd8fccbf0a53897ae780b2ddff0bbbf25df2016230d428ed8dea49c11f2c"
COMPLETION_SHA = "5e5fd8a6b5d8255c57a480b9da4334307cf195bb07cf9cc6c0b200242f8abac4"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def need(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def linear_quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def summarize(values: list[float]) -> dict[str, Any]:
    return {
        "n_histories": len(values),
        "mean": mean(values),
        "median": median(values),
        "sample_sd": math.sqrt(variance(values)),
        "q10_linear": linear_quantile(values, 0.10),
        "q25_linear": linear_quantile(values, 0.25),
        "q75_linear": linear_quantile(values, 0.75),
        "q90_linear": linear_quantile(values, 0.90),
        "positive_histories": sum(x > 0.0 for x in values),
        "negative_histories": sum(x < 0.0 for x in values),
        "zero_histories": sum(x == 0.0 for x in values),
        "min": min(values),
        "max": max(values),
    }


def stratified_mean_se(values_by_family: dict[str, list[float]]) -> float:
    """SE of equal-family mean from within-history neighborhood variation."""
    need(set(values_by_family) == set(FAMILIES), "family set incomplete for within-history SE")
    family_n = {len(values_by_family[family]) for family in FAMILIES}
    need(family_n == {500}, f"expected 500 neighborhoods/family, found {family_n}")
    # Overall estimator is the equally weighted mean of four family means.
    estimator_variance = sum(variance(values_by_family[f]) / 500 for f in FAMILIES) / 16
    return math.sqrt(estimator_variance)


def main() -> int:
    need(not OUT.exists(), "design-sizing output namespace exists; refusing overwrite")
    need(sha(COMPLETION) == COMPLETION_SHA, "Q-R2 completion seal mismatch")
    completion = json.loads(COMPLETION.read_text(encoding="utf-8"))
    need(completion.get("status") == "Q_R2_COMPLETE_RESULT_SEALED"
         and completion.get("opening_count") == 1, "Q-R2 completion/opening identity mismatch")
    binding = [item for item in completion["artifacts"] if Path(item["path"]) == RAW]
    need(len(binding) == 1 and binding[0]["sha256"] == RAW_SHA,
         "completion seal does not uniquely bind the raw prediction stream")

    # Hold only the four requested branch/view log-odds for each seed/neighborhood.
    rows: dict[tuple[int, str], dict[str, dict[str, tuple[str, float]]]] = {
        (seed, arm): {} for seed in SEEDS for arm in ARMS}
    counts: Counter[tuple[int, str, str]] = Counter()
    digest = hashlib.sha256()
    raw_count = selected_count = invalid_probabilities = 0
    invalid_examples: list[str] = []
    with RAW.open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            raw_count += 1
            row = json.loads(raw)
            if (int(row["global_step"]) != 120 or row["arm"] not in ARMS
                    or row["view"] not in VIEWS):
                continue
            seed, arm, view = int(row["seed"]), str(row["arm"]), str(row["view"])
            need(seed in SEEDS, f"unexpected seed {seed}")
            nid = str(row["neighborhood_id"])
            ids = tuple(str(value) for value in row["candidate_semantic_ids"])
            probs = tuple(float(value) for value in row["prediction"])
            old, new = str(row["old_candidate_id"]), str(row["new_candidate_id"])
            family = str(row["family_id"]).split(":")[-1]
            need(len(ids) == len(probs) == 4 and len(set(ids)) == 4,
                 f"invalid candidate vector {seed}/{nid}/{view}")
            need(old in ids and new in ids and old != new and family in FAMILIES,
                 f"invalid old/new/family binding {seed}/{nid}/{view}")
            p = dict(zip(ids, probs, strict=True))
            pn, po = p[new], p[old]
            if (not math.isfinite(pn) or not math.isfinite(po) or pn <= 0.0 or po <= 0.0):
                invalid_probabilities += 1
                if len(invalid_examples) < 8:
                    invalid_examples.append(f"{seed}/{nid}/{arm}/{view}: pnew={pn!r}, pold={po!r}")
                continue
            log_odds = math.log(pn) - math.log(po)
            need(math.isfinite(log_odds), f"nonfinite log-odds {seed}/{nid}/{arm}/{view}")
            item = rows[(seed, arm)].setdefault(nid, {"family": family})
            need(item["family"] == family, f"family mismatch across views {seed}/{nid}")
            need(view not in item, f"duplicate selected row {seed}/{nid}/{arm}/{view}")
            item[view] = (new, log_odds)
            counts[(seed, arm, view)] += 1
            selected_count += 1

    need(digest.hexdigest() == RAW_SHA, "raw prediction SHA mismatch")
    need(raw_count == 960_000, f"raw row count mismatch: {raw_count}")
    if invalid_probabilities:
        raise RuntimeError("NO_CLIP_LOGODDS_NOT_EVALUABLE: "
                           f"{invalid_probabilities} selected rows contain nonpositive/nonfinite old/new probabilities; "
                           f"examples={invalid_examples}")
    need(selected_count == 192_000, f"selected row count mismatch: {selected_count}")
    for seed in SEEDS:
        for arm in ARMS:
            need(len(rows[(seed, arm)]) == 2_000, f"neighborhood count mismatch {seed}/{arm}")
            for view in VIEWS:
                need(counts[(seed, arm, view)] == 2_000, f"view count mismatch {seed}/{arm}/{view}")

    history_rows = []
    within_se: dict[str, list[float]] = {"baseline_B": [], "criterion_C": [], "discriminability_D": []}
    for seed in SEEDS:
        history = rows[(seed, ARMS[0])]
        half = rows[(seed, ARMS[1])]
        need(history.keys() == half.keys(), f"paired neighborhood set mismatch {seed}")
        family_values: dict[str, dict[str, list[float]]] = {
            family: {key: [] for key in within_se} for family in FAMILIES}
        for nid in sorted(history):
            one_row, half_row = history[nid], half[nid]
            need(set(one_row) == set(half_row) == {"family", "anchor", "fact_flip"},
                 f"incomplete branch/view tuple {seed}/{nid}")
            need(one_row["family"] == half_row["family"], f"paired family mismatch {seed}/{nid}")
            family = str(one_row["family"])
            new1a, l1a = one_row["anchor"]
            newha, lha = half_row["anchor"]
            new1f, l1f = one_row["fact_flip"]
            newhf, lhf = half_row["fact_flip"]
            need(new1a == newha == new1f == newhf, f"candidate identity mismatch {seed}/{nid}")
            b_i = l1f - l1a
            c_i = lha - l1a
            d_i = (lhf - l1f) - (lha - l1a)
            family_values[family]["baseline_B"].append(b_i)
            family_values[family]["criterion_C"].append(c_i)
            family_values[family]["discriminability_D"].append(d_i)

        vals = {key: [x for family in FAMILIES for x in family_values[family][key]]
                for key in within_se}
        need(all(len(vals[key]) == 2_000 for key in vals), f"history count mismatch {seed}")
        history_row = {"seed": seed,
                       "baseline_B_1x_fact_minus_anchor_logodds": mean(vals["baseline_B"]),
                       "criterion_C_anchor_HALF_minus_1X_logodds": mean(vals["criterion_C"]),
                       "discriminability_D_HALF_minus_1X_fact_minus_anchor_logodds": mean(vals["discriminability_D"])}
        history_rows.append(history_row)
        for key in within_se:
            by_family = {family: family_values[family][key] for family in FAMILIES}
            within_se[key].append(stratified_mean_se(by_family))

    baseline = [row["baseline_B_1x_fact_minus_anchor_logodds"] for row in history_rows]
    criterion = [row["criterion_C_anchor_HALF_minus_1X_logodds"] for row in history_rows]
    discrim = [row["discriminability_D_HALF_minus_1X_fact_minus_anchor_logodds"] for row in history_rows]
    summaries = {"baseline_B": summarize(baseline), "criterion_C": summarize(criterion),
                 "discriminability_D": summarize(discrim)}
    variance_report = {}
    for key, history_values in (("baseline_B", baseline), ("criterion_C", criterion),
                                ("discriminability_D", discrim)):
        typical_within = median(within_se[key])
        between = math.sqrt(variance(history_values))
        variance_report[key] = {
            "between_history_sample_sd": between,
            "median_within_history_stratified_se": typical_within,
            "between_sd_divided_by_median_within_se": between / typical_within if typical_within else None,
            "within_history_se_range": [min(within_se[key]), max(within_se[key])],
        }

    result = {
        "status": "Q_R2_DESIGN_ONLY_CRITERION_DISCRIMINABILITY_SCALE_COMPLETE",
        "identity": "JEV-V08Q-R2-DESIGN-SIZING-C-D-V01",
        "purpose": "design input only; not a new R2 scientific result",
        "input": {"raw_prediction_sha256": RAW_SHA, "completion_seal_sha256": COMPLETION_SHA,
                  "raw_rows": raw_count, "selected_rows": selected_count,
                  "histories": len(SEEDS), "neighborhoods_per_history": 2_000,
                  "families_per_history": {family: 500 for family in FAMILIES},
                  "probability_rule": "parse stored JSON numbers as float64; compute ln(p_new)-ln(p_old); no clipping, smoothing, or rounding; any selected old/new p <= 0 or nonfinite fails closed",
                  "nonpositive_or_nonfinite_required_probabilities": invalid_probabilities,
                  "targets_metrics_or_checkpoints_used": False, "inference": False,
                  "new_panel_opening": False},
        "estimands": {
            "B": "within each history, mean over neighborhoods of 1X [log(p_new/p_old)_fact - log(p_new/p_old)_anchor]",
            "C": "within each history, mean over neighborhoods of [HALF-1X] log(p_new/p_old)_anchor",
            "D": "within each history, mean over neighborhoods of [HALF-1X](log(p_new/p_old)_fact-log(p_new/p_old)_anchor)",
            "history_unit": "one paired common-step-80 history; neighborhoods averaged within history with equal family representation",
        },
        "history_summaries": summaries,
        "variance_decomposition": variance_report,
        "within_history_standard_errors_by_history": {
            key: {str(seed): value for seed, value in zip(SEEDS, values, strict=True)}
            for key, values in within_se.items()},
        "history_rows": history_rows,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    OUT.mkdir(parents=True)
    json_path = OUT / "criterion-discriminability-sizing-v01.json"
    with json_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        stream.flush(); os.fsync(stream.fileno())

    lines = [
        "# Q-R2 design-only sizing: criterion and discriminability", "",
        "This is a design-input calculation over sealed predictions, not a new R2 result.",
        "Probability rule was frozen before calculation: stored probabilities parsed as float64; `ln(p_new)-ln(p_old)`; no clipping/smoothing; nonpositive/nonfinite values fail closed.", "",
        f"Raw SHA-256: `{RAW_SHA}`  ", f"Completion seal SHA-256: `{COMPLETION_SHA}`  ",
        f"Rows scanned: {raw_count:,}; selected rows: {selected_count:,}; paired histories: {len(SEEDS)}; neighborhoods/history: 2,000.", "",
        "Each history value is the equal-family mean over 2,000 neighborhoods. `B` is 1X baseline fact-minus-anchor log-odds separation; `C` is the anchor HALF−1X contrast; `D` is the HALF−1X fact-minus-anchor contrast.", "",
        "| Quantity | Mean | Median | SD across histories | Q10 | Q25 | Q75 | Q90 | Positive / negative | Range | Median within-history SE | Between-SD / within-SE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in (("baseline_B", "Baseline B (1X fact−anchor)"),
                       ("criterion_C", "Criterion C (anchor HALF−1X)"),
                       ("discriminability_D", "Discriminability D (HALF−1X fact−anchor)")):
        s, v = summaries[key], variance_report[key]
        lines.append(f"| {label} | {s['mean']:+.6f} | {s['median']:+.6f} | {s['sample_sd']:.6f} | {s['q10_linear']:+.6f} | {s['q25_linear']:+.6f} | {s['q75_linear']:+.6f} | {s['q90_linear']:+.6f} | {s['positive_histories']} / {s['negative_histories']} | [{s['min']:+.6f}, {s['max']:+.6f}] | {v['median_within_history_stratified_se']:.6f} | {v['between_sd_divided_by_median_within_se']:.2f} |")
    lines += ["", "## Per-history values", "",
              "| Seed/history | Baseline B | Criterion C | Discriminability D |",
              "|---:|---:|---:|---:|"]
    for row in history_rows:
        lines.append(f"| {row['seed']} | {row['baseline_B_1x_fact_minus_anchor_logodds']:+.6f} | {row['criterion_C_anchor_HALF_minus_1X_logodds']:+.6f} | {row['discriminability_D_HALF_minus_1X_fact_minus_anchor_logodds']:+.6f} |")
    lines += ["", "## Design-use boundary", "",
              "The between-history SD and stratified within-history SE are descriptive sizing inputs for this 24-history R2 sample. They do not estimate a population law. The prospective equivalence margin must still be justified and frozen before new data; a fraction of the observed baseline B scale may be considered, not silently adopted from this artifact. For a median D estimand, use a history-level bootstrap interval and require the full interval inside the prespecified equivalence region; TOST pertains to a separately declared mean estimand.", ""]
    md_path = OUT / "criterion-discriminability-sizing-v01.md"
    with md_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines)); stream.flush(); os.fsync(stream.fileno())

    files = [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}
             for path in (Path(__file__).resolve(), json_path, md_path)]
    root = hashlib.sha256("".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
                                  for row in files).encode()).hexdigest()
    seal = {"status": "Q_R2_DESIGN_ONLY_SIZING_OUTPUTS_SEALED", "identity": result["identity"],
            "input_raw_sha256": RAW_SHA, "completion_seal_sha256": COMPLETION_SHA,
            "files": files, "output_root_sha256": root,
            "registered_q_r2_x1_x2_modified": False, "created_at_utc": datetime.now(timezone.utc).isoformat()}
    seal_path = OUT / "criterion-discriminability-sizing-seal-v01.json"
    with seal_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(seal, indent=2) + "\n"); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps({"status": result["status"], "report": str(md_path),
                      "seal": str(seal_path), "output_root_sha256": root,
                      "C_median": summaries["criterion_C"]["median"],
                      "D_median": summaries["discriminability_D"]["median"],
                      "D_mean": summaries["discriminability_D"]["mean"],
                      "D_between_sd": variance_report["discriminability_D"]["between_history_sample_sd"],
                      "D_median_within_se": variance_report["discriminability_D"]["median_within_history_stratified_se"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
