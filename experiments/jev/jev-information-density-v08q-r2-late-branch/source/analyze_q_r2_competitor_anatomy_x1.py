"""Post-hoc, read-only anatomy of Q-R2's sealed paired step-120 predictions.

Uses only candidate identities and model probability vectors from the sealed
raw prediction stream. It does not read target fields, training artifacts, or
the sealed Q-R2 analysis; it cannot revise the registered result.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
EVAL = RUN / "evaluation-v03"
INPUT = EVAL / "raw-predictions-v01.jsonl"
COMPLETION = RUN / "provenance/q-r2-completion-seal-v06.json"
OUT = EVAL / "competitor-anatomy-x1"
ARMS = ("LATE_SHAM_1X", "LATE_SHAM_HALF")
VIEWS = ("anchor", "fact_flip")
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
SEEDS = (646142852, 4252058077, 1220728050, 2568717680, 3591276468, 1418365871,
         3679801188, 3460102370, 2742373327, 154863765, 2514222543, 3252782908,
         139770160, 4146187570, 3662026063, 3393901947, 147164975, 3776251307,
         1091781421, 3214909693, 642604459, 3342956466, 2210322644, 1629262270)
EXPECTED_RAW_SHA = "39c3fd8fccbf0a53897ae780b2ddff0bbbf25df2016230d428ed8dea49c11f2c"
EXPECTED_COMPLETION_SHA = "5e5fd8a6b5d8255c57a480b9da4334307cf195bb07cf9cc6c0b200242f8abac4"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def winner(ids: tuple[str, ...], probs: tuple[float, ...], eligible: set[str]) -> str:
    return max((candidate for candidate in ids if candidate in eligible),
               key=lambda candidate: (probs[ids.index(candidate)], candidate))


def read_inputs() -> tuple[dict[tuple[int, str], dict[str, dict[str, tuple[Any, ...]]]], str, int]:
    require(sha(COMPLETION) == EXPECTED_COMPLETION_SHA, "Q-R2 completion seal identity mismatch")
    completion = json.loads(COMPLETION.read_text(encoding="utf-8"))
    require(completion.get("status") == "Q_R2_COMPLETE_RESULT_SEALED"
            and completion.get("opening_count") == 1, "Q-R2 result is not sealed under the sole opening")
    bound_raw = [row for row in completion["artifacts"] if Path(row["path"]) == INPUT]
    require(len(bound_raw) == 1 and bound_raw[0]["sha256"] == EXPECTED_RAW_SHA,
            "completion seal does not uniquely bind the expected raw prediction file")

    data: dict[tuple[int, str], dict[str, dict[str, tuple[Any, ...]]]] = {
        (seed, arm): {} for seed in SEEDS for arm in ARMS
    }
    cell_view_counts: Counter[tuple[int, str, str]] = Counter()
    digest = hashlib.sha256()
    line_count = selected_count = 0
    with INPUT.open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            line_count += 1
            row = json.loads(raw)
            if (int(row["global_step"]) != 120 or str(row["arm"]) not in ARMS
                    or str(row["view"]) not in VIEWS):
                continue
            seed, arm, view = int(row["seed"]), str(row["arm"]), str(row["view"])
            require(seed in SEEDS, f"unexpected seed in selected prediction row: {seed}")
            nid = str(row["neighborhood_id"])
            ids = tuple(str(value) for value in row["candidate_semantic_ids"])
            probs = tuple(float(value) for value in row["prediction"])
            require(len(ids) == len(probs) == 4 and len(set(ids)) == 4,
                    f"invalid candidate vector at {seed}/{arm}/{nid}/{view}")
            require(all(math.isfinite(value) for value in probs)
                    and abs(sum(probs) - 1.0) <= 1e-6,
                    f"invalid probability vector at {seed}/{arm}/{nid}/{view}")
            old, new = str(row["old_candidate_id"]), str(row["new_candidate_id"])
            family = str(row["family_id"]).split(":")[-1]
            require(old in ids and new in ids and old != new and family in FAMILIES,
                    f"invalid neighborhood identity at {seed}/{arm}/{nid}/{view}")
            views = data[(seed, arm)].setdefault(nid, {})
            require(view not in views, f"duplicate selected view at {seed}/{arm}/{nid}/{view}")
            # Deliberately retain only the fields required for the decomposition.
            views[view] = (ids, probs, old, new, family)
            cell_view_counts[(seed, arm, view)] += 1
            selected_count += 1
    observed_sha = digest.hexdigest()
    require(observed_sha == EXPECTED_RAW_SHA, "raw prediction bytes failed their sealed SHA-256")
    require(line_count == 960_000 and selected_count == 192_000,
            f"raw/selected row counts mismatch: {line_count}/{selected_count}")
    for seed in SEEDS:
        for arm in ARMS:
            require(len(data[(seed, arm)]) == 2_000, f"neighborhood count mismatch {seed}/{arm}")
            for view in VIEWS:
                require(cell_view_counts[(seed, arm, view)] == 2_000,
                        f"view count mismatch {seed}/{arm}/{view}")
    return data, observed_sha, line_count


def metrics_for_pair(ids: tuple[str, ...], p1: tuple[float, ...], ph: tuple[float, ...],
                     old: str, new: str, view: str) -> dict[str, Any]:
    p1m, phm = dict(zip(ids, p1, strict=True)), dict(zip(ids, ph, strict=True))
    others = set(ids) - {old, new}
    require(len(others) == 2, "expected exactly two non-old/non-new candidates")
    rest1, resth = sum(p1m[x] for x in others), sum(phm[x] for x in others)
    if view == "fact_flip":
        # max() preserves the first candidate on ties, matching the frozen
        # candidate-order argmax convention used by the registered analysis.
        comp1 = max((x for x in ids if x != new), key=lambda x: p1m[x])
        comph = max((x for x in ids if x != new), key=lambda x: phm[x])
        gap1, gaph = p1m[new] - p1m[comp1], phm[new] - phm[comph]
        focus = "new"
    else:
        comp1 = max((x for x in ids if x != old), key=lambda x: p1m[x])
        comph = max((x for x in ids if x != old), key=lambda x: phm[x])
        gap1, gaph = p1m[old] - p1m[comp1], phm[old] - phm[comph]
        focus = "old"
    other1 = max((x for x in ids if x in others), key=lambda x: p1m[x])
    otherh = max((x for x in ids if x in others), key=lambda x: phm[x])
    dp_new, dp_old = phm[new] - p1m[new], phm[old] - p1m[old]
    dp_rest, dp_comp = resth - rest1, phm[comph] - p1m[comp1]
    dgap = gaph - gap1
    dp_focus = dp_new if focus == "new" else dp_old
    require(abs((dp_focus - dp_comp) - dgap) <= 1e-12,
            f"winner-gap decomposition identity failed ({view})")
    require(abs(dp_new + dp_old + dp_rest) <= 1e-6,
            f"new/old/rest mass conservation failed ({view})")
    return {
        "delta_p_new": dp_new,
        "delta_p_old": dp_old,
        "delta_p_other_mass": dp_rest,
        "delta_p_strongest_competitor": dp_comp,
        "delta_focus_winner_gap": dgap,
        "delta_strongest_other_probability": phm[otherh] - p1m[other1],
        "winner_competitor_1x": comp1,
        "winner_competitor_half": comph,
        "winner_competitor_changed": comp1 != comph,
        "winner_competitor_was_old_1x": comp1 == old,
        "winner_competitor_is_old_half": comph == old,
        "winner_competitor_type_changed": (comp1 == old) != (comph == old),
        "strongest_other_id_1x": other1,
        "strongest_other_id_half": otherh,
        "strongest_other_id_changed": other1 != otherh,
        "arm_1x_probability_mass": {"new": p1m[new], "old": p1m[old], "other": rest1},
        "arm_half_probability_mass": {"new": phm[new], "old": phm[old], "other": resth},
        "focus_candidate": focus,
    }


def summarize_seed_rows(rows: list[dict[str, Any]], view: str) -> dict[str, Any]:
    fields = ("delta_p_new", "delta_p_old", "delta_p_other_mass", "delta_p_strongest_competitor",
              "delta_focus_winner_gap", "delta_strongest_other_probability")
    result: dict[str, Any] = {name: mean(float(row[name]) for row in rows) for name in fields}
    result["winner_competitor_switch_rate"] = mean(float(row["winner_competitor_changed"]) for row in rows)
    result["winner_competitor_type_switch_rate"] = mean(float(row["winner_competitor_type_changed"]) for row in rows)
    result["strongest_other_id_switch_rate"] = mean(float(row["strongest_other_id_changed"]) for row in rows)
    for arm_key in ("arm_1x_probability_mass", "arm_half_probability_mass"):
        result[arm_key] = {bucket: mean(float(row[arm_key][bucket]) for row in rows)
                           for bucket in ("new", "old", "other")}
    result["view"] = view
    return result


def cohort_summary(seed_rows: list[dict[str, Any]], view: str) -> dict[str, Any]:
    numeric = ("delta_p_new", "delta_p_old", "delta_p_other_mass", "delta_p_strongest_competitor",
               "delta_focus_winner_gap", "delta_strongest_other_probability")
    output: dict[str, Any] = {"view": view, "seed_count": len(seed_rows), "seed_level": {}}
    for name in numeric:
        vals = [float(row[name]) for row in seed_rows]
        output["seed_level"][name] = {
            "mean": mean(vals), "median": median(vals),
            "positive_seeds": sum(x > 0 for x in vals),
            "negative_seeds": sum(x < 0 for x in vals),
            "zero_seeds": sum(x == 0 for x in vals), "range": [min(vals), max(vals)],
        }
    for name in ("winner_competitor_switch_rate", "winner_competitor_type_switch_rate",
                 "strongest_other_id_switch_rate"):
        vals = [float(row[name]) for row in seed_rows]
        output["seed_level"][name] = {"mean_across_seeds": mean(vals), "median_across_seeds": median(vals),
                                      "range_across_seeds": [min(vals), max(vals)]}
    output["probability_mass_mean_across_seeds"] = {}
    for arm_key in ("arm_1x_probability_mass", "arm_half_probability_mass"):
        output["probability_mass_mean_across_seeds"][arm_key] = {
            bucket: mean(float(row[arm_key][bucket]) for row in seed_rows)
            for bucket in ("new", "old", "other")}
    return output


def self_test() -> None:
    ids = ("old", "new", "other-a", "other-b")
    one = (0.30, 0.40, 0.20, 0.10)
    half = (0.24, 0.40, 0.26, 0.10)
    row = metrics_for_pair(ids, one, half, "old", "new", "fact_flip")
    require(abs(row["delta_focus_winner_gap"] - 0.04) < 1e-12
            and row["winner_competitor_changed"] is True
            and abs(sum(row["arm_half_probability_mass"].values()) - 1.0) < 1e-12,
            "synthetic competitor-decomposition fixture failed")
    tied = metrics_for_pair(ids, (0.30, 0.20, 0.25, 0.25),
                            (0.30, 0.20, 0.25, 0.25), "old", "new", "fact_flip")
    require(tied["winner_competitor_1x"] == "old",
            "synthetic tie fixture failed to preserve frozen candidate order")
    anchor = metrics_for_pair(ids, (0.40, 0.20, 0.20, 0.20),
                              (0.35, 0.20, 0.25, 0.20), "old", "new", "anchor")
    require(abs(anchor["delta_focus_winner_gap"] + 0.10) < 1e-12,
            "synthetic anchor-focus decomposition fixture failed")


def main() -> int:
    self_test()
    require(not OUT.exists(), "exploratory anatomy output namespace already exists")
    data, input_sha, line_count = read_inputs()
    seed_views: dict[str, list[dict[str, Any]]] = {view: [] for view in VIEWS}
    family_views: dict[str, dict[str, list[dict[str, Any]]]] = {
        view: {family: [] for family in FAMILIES} for view in VIEWS}
    all_rows: dict[str, list[dict[str, Any]]] = {view: [] for view in VIEWS}
    competitor_counts: dict[str, Counter[str]] = {view: Counter() for view in VIEWS}
    other_id_counts: dict[str, Counter[str]] = {view: Counter() for view in VIEWS}
    per_seed: dict[str, dict[str, Any]] = {}

    for seed in SEEDS:
        anchor_arm = data[(seed, ARMS[0])]
        half_arm = data[(seed, ARMS[1])]
        require(anchor_arm.keys() == half_arm.keys(), f"paired neighborhood IDs differ at seed {seed}")
        seed_result: dict[str, Any] = {}
        for view in VIEWS:
            rows: list[dict[str, Any]] = []
            for nid in sorted(anchor_arm):
                left, right = anchor_arm[nid][view], half_arm[nid][view]
                ids1, p1, old1, new1, family1 = left
                idsh, ph, oldh, newh, familyh = right
                require(ids1 == idsh and old1 == oldh and new1 == newh and family1 == familyh,
                        f"paired semantic alignment mismatch {seed}/{nid}/{view}")
                row = metrics_for_pair(ids1, p1, ph, old1, new1, view)
                row.update({"seed": seed, "neighborhood_id": nid, "family": family1})
                rows.append(row)
                all_rows[view].append(row)
                family_views[view][family1].append(row)
                competitor_counts[view]["changed"] += int(row["winner_competitor_changed"])
                competitor_counts[view]["1x_old"] += int(row["winner_competitor_was_old_1x"])
                competitor_counts[view]["half_old"] += int(row["winner_competitor_is_old_half"])
                competitor_counts[view]["type_changed"] += int(row["winner_competitor_type_changed"])
                other_id_counts[view]["changed"] += int(row["strongest_other_id_changed"])
            summary = summarize_seed_rows(rows, view)
            summary["family"] = rows[0]["family"] if len({r['family'] for r in rows}) == 1 else "mixed"
            seed_result[view] = summary
            seed_views[view].append({"seed": seed, **summary})
        per_seed[str(seed)] = seed_result

    summaries = {view: cohort_summary(seed_views[view], view) for view in VIEWS}
    family_summary: dict[str, dict[str, Any]] = {}
    for view in VIEWS:
        family_summary[view] = {}
        for family in FAMILIES:
            by_seed = []
            for seed in SEEDS:
                rows = [r for r in family_views[view][family] if r["seed"] == seed]
                require(len(rows) == 500, f"family cell is not 500 rows: {view}/{family}/{seed}")
                by_seed.append({"seed": seed, **summarize_seed_rows(rows, view)})
            family_summary[view][family] = cohort_summary(by_seed, view)

    total_pairs = len(SEEDS) * 2_000
    switch_summary = {view: {"paired_neighborhoods": total_pairs,
        "strongest_non_target_competitor_changed": competitor_counts[view]["changed"],
        "strongest_non_target_competitor_switch_rate": competitor_counts[view]["changed"] / total_pairs,
        "old_was_strongest_competitor_1x_count": competitor_counts[view]["1x_old"],
        "old_was_strongest_competitor_half_count": competitor_counts[view]["half_old"],
        "old_vs_other_competitor_type_changed": competitor_counts[view]["type_changed"],
        "strongest_other_identity_changed": other_id_counts[view]["changed"],
        "strongest_other_identity_switch_rate": other_id_counts[view]["changed"] / total_pairs}
        for view in VIEWS}

    result = {
        "status": "Q_R2_X1_EXPLORATORY_COMPETITOR_ANATOMY_COMPLETE",
        "identity": "JEV-V08Q-R2-X1-SEALED-PREDICTION-COMPETITOR-ANATOMY",
        "purpose": "post-hoc exploratory decomposition; cannot revise Q-R2 registered result",
        "input": {"completion_seal_sha256": EXPECTED_COMPLETION_SHA, "raw_prediction_sha256": input_sha,
                  "raw_prediction_rows": line_count, "selected_step120_rows": 192_000,
                  "selected_arm_pairs": total_pairs, "views": list(VIEWS),
                  "targets_read_or_used": False, "metrics_or_training_artifacts_read": False,
                  "model_contact": False, "inference": False, "panel_opening_count": 1},
        "decomposition": {
            "fact_flip": "gap(new)=p(new)-max(p(non-new)); delta gap = delta p(new)-delta p(strongest non-new)",
            "anchor": "gap(old)=p(old)-max(p(non-old)); delta gap = delta p(old)-delta p(strongest non-old)",
            "other_mass": "sum of probabilities for the two candidates that are neither designated old nor new",
            "strongest_other": "max probability among those two residual candidates",
            "identity_switch": "argmax competitor ID differs between paired 1x and half branches",
            "aggregation": "first average neighborhoods within seed, then summarize 24 seed means",
        },
        "fact_flip_seed_level": summaries["fact_flip"],
        "anchor_seed_level": summaries["anchor"],
        "competitor_switch_counts": switch_summary,
        "family_seed_level": family_summary,
        "per_seed": per_seed,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    OUT.mkdir(parents=True)
    json_path = OUT / "competitor-anatomy-x1-v01.json"
    with json_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())

    lines = [
        "# Q-R2-X1: Exploratory competitor anatomy of sealed predictions", "",
        "This post-hoc read-only diagnostic cannot revise the registered Q-R2 result.",
        "It uses only the sealed step-120 candidate identities and model probability vectors; target fields are not used.", "",
        f"Input prediction SHA-256: `{input_sha}`  ",
        f"Completion seal SHA-256: `{EXPECTED_COMPLETION_SHA}`  ",
        f"Rows scanned: {line_count:,}; paired neighborhoods per view: {total_pairs:,}.", "",
        "All continuous summaries below average 2,000 neighborhoods within each seed first, then summarize the 24 seed means.", "",
        "## Fact-flip view: HALF minus 1X", "",
        "| Quantity | Mean across seed means | Median seed | Positive / negative / zero seeds |", "|---|---:|---:|---:|",
    ]
    for name, label in (("delta_p_new", "Δ probability of intended new candidate"),
                        ("delta_p_old", "Δ probability of old candidate"),
                        ("delta_p_other_mass", "Δ total residual-other mass"),
                        ("delta_p_strongest_competitor", "Δ strongest non-new competitor probability"),
                        ("delta_focus_winner_gap", "Δ new-vs-strongest-competitor gap"),
                        ("delta_strongest_other_probability", "Δ strongest probability among residual others")):
        s = summaries["fact_flip"]["seed_level"][name]
        lines.append(f"| {label} | {s['mean']:+.6f} | {s['median']:+.6f} | {s['positive_seeds']} / {s['negative_seeds']} / {s['zero_seeds']} |")
    lines += ["", "### Competitor identities", "",
              "| View | Paired neighborhoods | Strongest competitor switched | 1X strongest competitor = old | Half strongest competitor = old | Old-vs-other type changed | Residual strongest-other ID changed |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for view in VIEWS:
        c = switch_summary[view]
        lines.append(f"| {view} | {c['paired_neighborhoods']:,} | {c['strongest_non_target_competitor_changed']:,} ({c['strongest_non_target_competitor_switch_rate']:.1%}) | {c['old_was_strongest_competitor_1x_count']:,} | {c['old_was_strongest_competitor_half_count']:,} | {c['old_vs_other_competitor_type_changed']:,} | {c['strongest_other_identity_changed']:,} ({c['strongest_other_identity_switch_rate']:.1%}) |")
    lines += ["", "### Three-bucket probability mass", "",
              "| View / arm | New | Old | Other (sum of remaining candidates) |", "|---|---:|---:|---:|"]
    for view in VIEWS:
        for arm_key, label in (("arm_1x_probability_mass", "1X"), ("arm_half_probability_mass", "HALF")):
            m = summaries[view]["probability_mass_mean_across_seeds"][arm_key]
            lines.append(f"| {view} / {label} | {m['new']:.6f} | {m['old']:.6f} | {m['other']:.6f} |")
    lines += ["", "## Interpretation boundary", "",
              "The decomposition is descriptive. The strongest competitor may differ between branches, so Δ competitor probability is computed from each branch's own argmax competitor; identity-switch counts are reported alongside it. The three-bucket mass conserves probability but does not identify a causal mechanism. Results are conditional on the sealed panel and the 24 paired step-80 histories.", ""]
    report_path = OUT / "competitor-anatomy-x1-v01.md"
    with report_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines))
        stream.flush()
        os.fsync(stream.fileno())
    files = [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}
             for path in (Path(__file__).resolve(), json_path, report_path)]
    seal = {"status": "Q_R2_X1_EXPLORATORY_OUTPUTS_SEALED",
            "identity": result["identity"], "input_prediction_sha256": input_sha,
            "completion_seal_sha256": EXPECTED_COMPLETION_SHA, "files": files,
            "output_root_sha256": hashlib.sha256("".join(
                f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in files).encode()).hexdigest(),
            "registered_q_r2_result_modified": False, "created_at_utc": datetime.now(timezone.utc).isoformat()}
    seal_path = OUT / "competitor-anatomy-x1-seal-v01.json"
    with seal_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(seal, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": result["status"], "output_seal": str(seal_path),
        "output_root_sha256": seal["output_root_sha256"],
        "report": str(report_path), "fact_gap_mean": summaries["fact_flip"]["seed_level"]["delta_focus_winner_gap"]["mean"],
        "fact_target_probability_mean": summaries["fact_flip"]["seed_level"]["delta_p_new"]["mean"],
        "fact_competitor_switch_rate": switch_summary["fact_flip"]["strongest_non_target_competitor_switch_rate"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
