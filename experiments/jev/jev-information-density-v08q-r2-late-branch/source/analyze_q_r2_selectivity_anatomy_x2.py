"""Read-only X2 of Q-R2 sealed predictions: outliers, role/slot, anchor preservation."""

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

RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
EVAL = RUN / "evaluation-v03"
INPUT = EVAL / "raw-predictions-v01.jsonl"
COMPLETION = RUN / "provenance/q-r2-completion-seal-v06.json"
X1 = EVAL / "competitor-anatomy-x1/competitor-anatomy-x1-v01.json"
X1_SEAL = EVAL / "competitor-anatomy-x1/competitor-anatomy-x1-seal-v01.json"
OUT = EVAL / "competitor-anatomy-x2"
ARMS = ("LATE_SHAM_1X", "LATE_SHAM_HALF")
VIEWS = ("anchor", "fact_flip")
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
SEEDS = (646142852, 4252058077, 1220728050, 2568717680, 3591276468, 1418365871,
         3679801188, 3460102370, 2742373327, 154863765, 2514222543, 3252782908,
         139770160, 4146187570, 3662026063, 3393901947, 147164975, 3776251307,
         1091781421, 3214909693, 642604459, 3342956466, 2210322644, 1629262270)
RAW_SHA = "39c3fd8fccbf0a53897ae780b2ddff0bbbf25df2016230d428ed8dea49c11f2c"
COMPLETION_SHA = "5e5fd8a6b5d8255c57a480b9da4334307cf195bb07cf9cc6c0b200242f8abac4"
X1_SHA = "210430d1ec0cca7430b0ce2492c01f8c6bae4008c04b678d019d3bdb802668a6"
X1_SEAL_SHA = "081d23b8cea475af3ad449151db964797fe860bd4b8345b955dd8fd8404bb979"
X1_ROOT_SHA = "add172480012f9a441806ad76186e312ea3aac031381877ff72dd79f181faf16"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def need(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def argmax_id(ids: tuple[str, ...], probs: tuple[float, ...], excluded: str | None = None) -> str:
    # max keeps the first item on ties; ids are the frozen candidate order.
    indices = (i for i, cid in enumerate(ids) if cid != excluded)
    index = max(indices, key=lambda i: probs[i])
    return ids[index]


def blank_acc() -> dict[str, Any]:
    return {"n": 0, "sum_new_lift": 0.0, "sum_old_lift": 0.0,
            "sum_old_minus_new_margin_1x": 0.0, "sum_old_minus_new_margin_half": 0.0,
            "old_correct_1x": 0, "old_correct_half": 0}


def acc_add(acc: dict[str, Any], new_lift: float, old_lift: float, margin_1x: float,
            margin_half: float,
            correct_1x: bool, correct_half: bool) -> None:
    acc["n"] += 1
    acc["sum_new_lift"] += new_lift
    acc["sum_old_lift"] += old_lift
    acc["sum_old_minus_new_margin_1x"] += margin_1x
    acc["sum_old_minus_new_margin_half"] += margin_half
    acc["old_correct_1x"] += int(correct_1x)
    acc["old_correct_half"] += int(correct_half)


def summarize_seed_values(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [float(row[key]) for row in rows]
    return {"mean": mean(values), "median": median(values),
            "positive": sum(x > 0 for x in values), "negative": sum(x < 0 for x in values),
            "zero": sum(x == 0 for x in values), "min": min(values), "max": max(values)}


def summarize_acc_groups(groups: dict[str, dict[int, dict[str, Any]]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for group, by_seed in groups.items():
        per_seed = []
        for seed, acc in by_seed.items():
            n = int(acc["n"])
            per_seed.append({
                "seed": seed,
                "new_lift": acc["sum_new_lift"] / n,
                "old_lift": acc["sum_old_lift"] / n,
                "old_minus_new_margin_1x": acc["sum_old_minus_new_margin_1x"] / n,
                "old_minus_new_margin_half": acc["sum_old_minus_new_margin_half"] / n,
                "old_minus_new_margin_delta": (acc["sum_old_minus_new_margin_half"]
                                               - acc["sum_old_minus_new_margin_1x"]) / n,
                "anchor_old_map_1x": acc["old_correct_1x"] / n,
                "anchor_old_map_half": acc["old_correct_half"] / n,
                "anchor_old_map_delta": (acc["old_correct_half"] - acc["old_correct_1x"]) / n,
                "neighborhoods": n,
            })
        output[group] = {
            "seed_count": len(per_seed),
            "neighborhoods_per_seed": sorted({row["neighborhoods"] for row in per_seed}),
            "mean_across_seed_means": {
                field: mean(float(row[field]) for row in per_seed)
                for field in ("new_lift", "old_lift", "old_minus_new_margin_1x",
                              "old_minus_new_margin_half", "old_minus_new_margin_delta",
                              "anchor_old_map_1x", "anchor_old_map_half", "anchor_old_map_delta")
            },
            "per_seed": per_seed,
        }
    return output


def self_test() -> None:
    ids = ("old", "new", "other-a", "other-b")
    need(argmax_id(ids, (0.4, 0.2, 0.2, 0.2)) == "old", "frozen-order tie fixture failed")
    need(argmax_id(ids, (0.2, 0.2, 0.4, 0.2), excluded="new") == "other-a",
         "excluded-candidate argmax fixture failed")


def main() -> int:
    self_test()
    need(not OUT.exists(), "X2 output namespace already exists; refusing overwrite")
    need(sha(COMPLETION) == COMPLETION_SHA, "Q-R2 completion seal SHA mismatch")
    completion = json.loads(COMPLETION.read_text(encoding="utf-8"))
    need(completion.get("status") == "Q_R2_COMPLETE_RESULT_SEALED"
         and completion.get("opening_count") == 1, "Q-R2 completion/opening identity mismatch")
    raw_bindings = [row for row in completion["artifacts"] if Path(row["path"]) == INPUT]
    need(len(raw_bindings) == 1 and raw_bindings[0]["sha256"] == RAW_SHA,
         "completion seal does not uniquely bind raw predictions")
    need(sha(X1) == X1_SHA, "X1 decomposition identity mismatch")
    need(sha(X1_SEAL) == X1_SEAL_SHA, "X1 seal identity mismatch")
    x1_seal = json.loads(X1_SEAL.read_text(encoding="utf-8"))
    need(x1_seal.get("status") == "Q_R2_X1_EXPLORATORY_OUTPUTS_SEALED"
         and x1_seal.get("input_prediction_sha256") == RAW_SHA
         and x1_seal.get("output_root_sha256") == X1_ROOT_SHA,
         "X1 seal does not bind expected raw prediction source")
    x1_seal_sha = sha(X1_SEAL)
    x1_root_text = "".join(f"{item['path']}\t{item['bytes']}\t{item['sha256']}\n"
                           for item in x1_seal["files"])
    need(hashlib.sha256(x1_root_text.encode()).hexdigest() == X1_ROOT_SHA,
         "X1 output root digest mismatch")
    for item in x1_seal["files"]:
        source = Path(item["path"])
        need(source.stat().st_size == item["bytes"] and sha(source) == item["sha256"],
             f"X1 sealed file mismatch: {source}")

    data: dict[tuple[int, str], dict[str, dict[str, tuple[Any, ...]]]] = {
        (seed, arm): {} for seed in SEEDS for arm in ARMS}
    counts: Counter[tuple[int, str, str]] = Counter()
    panel_meta: dict[str, tuple[Any, ...]] = {}
    logit_fields: Counter[str] = Counter()
    digest = hashlib.sha256()
    line_count = selected = 0
    with INPUT.open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            line_count += 1
            row = json.loads(raw)
            if int(row["global_step"]) != 120 or row["arm"] not in ARMS or row["view"] not in VIEWS:
                continue
            seed, arm, view = int(row["seed"]), str(row["arm"]), str(row["view"])
            need(seed in SEEDS, f"unexpected seed {seed}")
            nid = str(row["neighborhood_id"])
            ids = tuple(str(value) for value in row["candidate_semantic_ids"])
            probs = tuple(float(value) for value in row["prediction"])
            old, new = str(row["old_candidate_id"]), str(row["new_candidate_id"])
            family = str(row["family_id"]).split(":")[-1]
            need(len(ids) == 4 and len(set(ids)) == 4 and len(probs) == 4,
                 f"invalid candidate vector {seed}/{nid}/{view}")
            need(all(math.isfinite(value) for value in probs)
                 and abs(sum(probs) - 1.0) <= 1e-6, f"invalid probability vector {seed}/{nid}/{view}")
            need(old in ids and new in ids and old != new and family in FAMILIES,
                 f"invalid role/family metadata {seed}/{nid}/{view}")
            for key in row:
                if "logit" in key.lower():
                    logit_fields[key] += 1
            meta = (ids, old, new, family)
            previous = panel_meta.setdefault(nid, meta)
            need(previous == meta, f"candidate order/role/family changed across cells: {nid}")
            views = data[(seed, arm)].setdefault(nid, {})
            need(view not in views, f"duplicate selected row {seed}/{arm}/{nid}/{view}")
            views[view] = (ids, probs, old, new, family)
            counts[(seed, arm, view)] += 1
            selected += 1
    need(digest.hexdigest() == RAW_SHA, "raw prediction stream SHA mismatch")
    need(line_count == 960_000 and selected == 192_000 and len(panel_meta) == 2_000,
         f"row/panel counts mismatch {line_count}/{selected}/{len(panel_meta)}")
    for seed in SEEDS:
        for arm in ARMS:
            need(len(data[(seed, arm)]) == 2_000, f"neighborhood count mismatch {seed}/{arm}")
            for view in VIEWS:
                need(counts[(seed, arm, view)] == 2_000, f"view count mismatch {seed}/{arm}/{view}")

    seed_rows: list[dict[str, Any]] = []
    by_family: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    by_family_slot: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    by_new_slot: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    by_new_identity: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    role_slot_counts: Counter[tuple[str, int]] = Counter()
    identity_role_counts: dict[str, Counter[str]] = defaultdict(Counter)

    # Role and slot composition is counted once per panel neighborhood, not once per seed.
    for nid, (ids, old, new, family) in panel_meta.items():
        role_slot_counts[("new", ids.index(new))] += 1
        role_slot_counts[("old", ids.index(old))] += 1
        identity_role_counts[new]["new"] += 1
        identity_role_counts[old]["old"] += 1
        for cid in ids:
            if cid not in (old, new):
                identity_role_counts[cid]["other"] += 1
        for slot, cid in enumerate(ids):
            if cid not in (old, new):
                role_slot_counts[("other", slot)] += 1

    for seed in SEEDS:
        accum = blank_acc()
        dd_new: list[float] = []
        dd_old: list[float] = []
        dd_other: list[float] = []
        competitor_switches = other_switches = 0
        for nid in sorted(data[(seed, ARMS[0])]):
            one = data[(seed, ARMS[0])][nid]
            half = data[(seed, ARMS[1])][nid]
            need(one.keys() == half.keys() and set(one) == set(VIEWS), f"paired views mismatch {seed}/{nid}")
            a1, ah = one["anchor"], half["anchor"]
            f1, fh = one["fact_flip"], half["fact_flip"]
            ids, p1a, old, new, family = a1
            idsh, pha, oldh, newh, familyh = ah
            need(ids == idsh and old == oldh and new == newh and family == familyh,
                 f"anchor branch metadata mismatch {seed}/{nid}")
            idsf1, p1f, oldf, newf, familyf = f1
            idsfh, phf, oldfh, newfh, familyfh = fh
            need(ids == idsf1 == idsfh and old == oldf == oldfh and new == newf == newfh
                 and family == familyf == familyfh, f"view metadata mismatch {seed}/{nid}")

            old_i, new_i = ids.index(old), ids.index(new)
            pnew1a, pnewha = p1a[new_i], pha[new_i]
            pold1a, poldha = p1a[old_i], pha[old_i]
            map1, maph = argmax_id(ids, p1a) == old, argmax_id(ids, pha) == old
            margin_1x = pold1a - pnew1a
            margin_half = poldha - pnewha
            acc_add(accum, pnewha - pnew1a, poldha - pold1a,
                    margin_1x, margin_half, map1, maph)
            slot = new_i
            for group_name, store in (
                    (family, by_family), (f"{family}|slot_{slot}", by_family_slot),
                    (f"slot_{slot}", by_new_slot), (f"identity_{new}", by_new_identity)):
                gacc = store.setdefault(group_name, {}).setdefault(seed, blank_acc())
                acc_add(gacc, pnewha - pnew1a, poldha - pold1a,
                        margin_1x, margin_half, map1, maph)

            # R2 registered response is a branch difference of fact-minus-anchor movement.
            d_new = (phf[new_i] - p1f[new_i]) - (pha[new_i] - p1a[new_i])
            d_old = (phf[old_i] - p1f[old_i]) - (pha[old_i] - p1a[old_i])
            others = [idx for idx, cid in enumerate(ids) if cid not in (old, new)]
            mass1f = sum(p1f[idx] for idx in others)
            masshf = sum(phf[idx] for idx in others)
            mass1a = sum(p1a[idx] for idx in others)
            massha = sum(pha[idx] for idx in others)
            d_other = (masshf - mass1f) - (massha - mass1a)
            dd_new.append(d_new)
            dd_old.append(d_old)
            dd_other.append(d_other)

            comp1 = argmax_id(ids, p1f, excluded=new)
            comph = argmax_id(ids, phf, excluded=new)
            other1 = argmax_id(tuple(ids[idx] for idx in others), tuple(p1f[idx] for idx in others))
            otherh = argmax_id(tuple(ids[idx] for idx in others), tuple(phf[idx] for idx in others))
            competitor_switches += int(comp1 != comph)
            other_switches += int(other1 != otherh)

        seed_rows.append({
            "seed": seed,
            "anchor_new_probability_lift": accum["sum_new_lift"] / accum["n"],
            "anchor_old_probability_lift": accum["sum_old_lift"] / accum["n"],
            "anchor_old_minus_new_margin_1x": accum["sum_old_minus_new_margin_1x"] / accum["n"],
            "anchor_old_minus_new_margin_half": accum["sum_old_minus_new_margin_half"] / accum["n"],
            "anchor_old_minus_new_margin_delta": (accum["sum_old_minus_new_margin_half"]
                                                   - accum["sum_old_minus_new_margin_1x"]) / accum["n"],
            "anchor_old_map_1x": accum["old_correct_1x"] / accum["n"],
            "anchor_old_map_half": accum["old_correct_half"] / accum["n"],
            "anchor_old_map_delta": (accum["old_correct_half"] - accum["old_correct_1x"]) / accum["n"],
            "selective_new_probability": mean(dd_new),
            "selective_old_probability": mean(dd_old),
            "selective_other_mass": mean(dd_other),
            "fact_competitor_switch_rate": competitor_switches / 2_000,
            "fact_residual_other_id_switch_rate": other_switches / 2_000,
        })

    selective_mass_residual = mean(
        row["selective_new_probability"] + row["selective_old_probability"]
        + row["selective_other_mass"] for row in seed_rows)
    need(abs(selective_mass_residual) < 1e-5,
         f"selective three-bucket probability conservation exceeds normalization tolerance: {selective_mass_residual}")

    anchor_lift = summarize_seed_values(seed_rows, "anchor_new_probability_lift")
    anchor_old_lift = summarize_seed_values(seed_rows, "anchor_old_probability_lift")
    anchor_margin_1x = summarize_seed_values(seed_rows, "anchor_old_minus_new_margin_1x")
    anchor_margin_half = summarize_seed_values(seed_rows, "anchor_old_minus_new_margin_half")
    anchor_margin_delta = summarize_seed_values(seed_rows, "anchor_old_minus_new_margin_delta")
    anchor_map_1x = summarize_seed_values(seed_rows, "anchor_old_map_1x")
    anchor_map_half = summarize_seed_values(seed_rows, "anchor_old_map_half")
    anchor_map_delta = summarize_seed_values(seed_rows, "anchor_old_map_delta")
    select_new = summarize_seed_values(seed_rows, "selective_new_probability")
    select_old = summarize_seed_values(seed_rows, "selective_old_probability")
    select_other = summarize_seed_values(seed_rows, "selective_other_mass")

    def role_summary(groups: dict[str, dict[int, dict[str, Any]]]) -> dict[str, Any]:
        return summarize_acc_groups(groups)

    role_slot = [{"role": role, "slot_zero_based": slot, "panel_neighborhood_assignments": n}
                 for (role, slot), n in sorted(role_slot_counts.items())]
    identity_rows = []
    for cid, counts_by_role in sorted(identity_role_counts.items()):
        per_seed_lifts = []
        for seed in SEEDS:
            acc = by_new_identity.get(f"identity_{cid}", {}).get(seed)
            if acc:
                per_seed_lifts.append(acc["sum_new_lift"] / acc["n"])
        identity_rows.append({"candidate_semantic_id": cid, "role_counts": dict(counts_by_role),
                              "new_role_anchor_lift_mean_across_seed_means": mean(per_seed_lifts)
                              if per_seed_lifts else None,
                              "new_role_seed_count": len(per_seed_lifts)})

    outlier_sorted = sorted(seed_rows, key=lambda row: row["selective_new_probability"], reverse=True)
    switch_sorted = sorted(seed_rows, key=lambda row: row["fact_competitor_switch_rate"], reverse=True)
    selected_seed_views = {
        "selective_new_max": outlier_sorted[0],
        "selective_new_min": outlier_sorted[-1],
        "selective_other_mass_min": min(seed_rows, key=lambda row: row["selective_other_mass"]),
        "selective_other_mass_max": max(seed_rows, key=lambda row: row["selective_other_mass"]),
        "fact_competitor_switch_top8": switch_sorted[:8],
    }
    result = {
        "status": "Q_R2_X2_EXPLORATORY_SELECTIVITY_ANATOMY_COMPLETE",
        "identity": "JEV-V08Q-R2-X2-OUTLIER-ROLE-ANCHOR-ANATOMY",
        "purpose": "bounded read-only post-hoc analysis; cannot revise Q-R2 or X1",
        "inputs": {"raw_prediction_sha256": RAW_SHA, "completion_seal_sha256": COMPLETION_SHA,
                   "x1_json_sha256": X1_SHA, "x1_seal_sha256": x1_seal_sha,
                   "raw_rows_scanned": line_count, "selected_step120_rows": selected,
                   "panel_neighborhoods": len(panel_meta), "seeds": len(SEEDS),
                   "target_fields_used": False, "metrics_or_checkpoints_used": False,
                   "logit_fields_present": dict(logit_fields), "inference": False,
                   "new_panel_opening": False},
        "estimand_notes": {
            "anchor_lift": "HALF minus 1X p(new_candidate) on anchor view; new_candidate is the candidate designated correct only after fact flip.",
            "anchor_margin": "p(old_candidate)-p(new_candidate), probability scale; positive favors anchor target.",
            "selective_effect": "(HALF_fact-1X_fact)-(HALF_anchor-1X_anchor) for each candidate probability coordinate.",
            "tie_rule": "earliest candidate in the frozen candidate array, matching the registered convention.",
        },
        "anchor_overall": {"new_probability_lift": anchor_lift, "old_probability_lift": anchor_old_lift,
                           "old_minus_new_margin_1x": anchor_margin_1x,
                           "old_minus_new_margin_half": anchor_margin_half,
                           "old_minus_new_margin_delta": anchor_margin_delta,
                           "old_map_correctness_1x": anchor_map_1x,
                           "old_map_correctness_half": anchor_map_half,
                           "old_map_correctness_delta": anchor_map_delta},
        "selective_difference_in_differences": {"new_probability": select_new,
                                                "old_probability": select_old,
                                                "other_mass": select_other,
                                                "mean_mass_conservation_residual": selective_mass_residual},
        "role_slot_panel_composition": role_slot,
        "anchor_lift_by_family": role_summary(by_family),
        "anchor_lift_by_family_and_new_slot": role_summary(by_family_slot),
        "anchor_lift_by_new_candidate_slot": role_summary(by_new_slot),
        "anchor_lift_by_new_candidate_identity": identity_rows,
        "outlier_and_switch_anatomy": selected_seed_views,
        "all_seed_rows": seed_rows,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    # X1 supplies sealed consistency context; X2 recomputes requested statistics
    # directly from the raw prediction matrix.
    x1_result = json.loads(X1.read_text(encoding="utf-8"))
    need(x1_result.get("status") == "Q_R2_X1_EXPLORATORY_COMPETITOR_ANATOMY_COMPLETE",
         "X1 result status mismatch")
    need(set(x1_result["per_seed"]) == {str(seed) for seed in SEEDS}, "X1 seed set mismatch")
    result["x1_crosscheck"] = {
        "source": "sealed X1 summary; no new outcome access",
        "fact_view_gap_mean": x1_result["fact_flip_seed_level"]["seed_level"]["delta_focus_winner_gap"]["mean"],
        "fact_view_target_probability_mean": x1_result["fact_flip_seed_level"]["seed_level"]["delta_p_new"]["mean"],
        "anchor_old_gap_mean": x1_result["anchor_seed_level"]["seed_level"]["delta_focus_winner_gap"]["mean"],
        "anchor_competitor_switch_rate": x1_result["competitor_switch_counts"]["anchor"]["strongest_non_target_competitor_switch_rate"],
    }
    result["outlier_and_switch_anatomy"]["selective_new_and_other_extreme_seed_overlap"] = (
        outlier_sorted[0]["seed"] == min(seed_rows, key=lambda row: row["selective_other_mass"])["seed"])

    OUT.mkdir(parents=True)
    json_path = OUT / "selectivity-anatomy-x2-v01.json"
    with json_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        stream.flush(); os.fsync(stream.fileno())

    lines = [
        "# Q-R2-X2: Exploratory selectivity, role, and anchor anatomy", "",
        "Read-only analysis of sealed Q-R2 predictions. It cannot revise registered R2 or X1.",
        "The fixed candidate contrast is `old` versus `new`; `new` denotes the candidate intended after fact flip, so it remains the counterfactual candidate on anchors.", "",
        f"Raw prediction SHA-256: `{RAW_SHA}`  ", f"Q-R2 completion seal SHA-256: `{COMPLETION_SHA}`  ",
        f"X1 result SHA-256: `{X1_SHA}`; X1 seal SHA-256: `{x1_seal_sha}`  ",
        f"Rows scanned: {line_count:,}; selected step-120 rows: {selected:,}; unique panel neighborhoods: {len(panel_meta):,}.", "",
        "## Anchor treatment shift and preservation", "",
        "| Coordinate | 1X mean | HALF mean | HALF−1X mean | Median seed delta | Positive / negative delta seeds |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, one_key, half_key, delta_key in (
            ("p(new candidate)", None, None, "anchor_new_probability_lift"),
            ("p(old candidate)", None, None, "anchor_old_probability_lift"),
            ("p(old)−p(new) margin", "anchor_old_minus_new_margin_1x",
             "anchor_old_minus_new_margin_half", "anchor_old_minus_new_margin_delta"),
            ("old-target anchor MAP correctness", "anchor_old_map_1x",
             "anchor_old_map_half", "anchor_old_map_delta")):
        delta = summarize_seed_values(seed_rows, delta_key)
        one_mean = "—" if one_key is None else f"{summarize_seed_values(seed_rows, one_key)['mean']:.6f}"
        half_mean = "—" if half_key is None else f"{summarize_seed_values(seed_rows, half_key)['mean']:.6f}"
        lines.append(f"| {label} | {one_mean} | {half_mean} | {delta['mean']:+.6f} | {delta['median']:+.6f} | {delta['positive']} / {delta['negative']} |")
    lines += ["", "## Fact-specific probability response", "",
              "The registered movement contrast is the branch effect on fact-minus-anchor movement, not the fact-view branch difference alone.", "",
              "| Difference-in-differences coordinate | Mean | Median | Positive / negative seeds | Range |",
              "|---|---:|---:|---:|---:|"]
    for label, key in (("p(new)", "selective_new_probability"),
                       ("p(old)", "selective_old_probability"),
                       ("other-candidate mass", "selective_other_mass")):
        s = summarize_seed_values(seed_rows, key)
        lines.append(f"| {label} | {s['mean']:+.6f} | {s['median']:+.6f} | {s['positive']} / {s['negative']} | [{s['min']:+.6f}, {s['max']:+.6f}] |")
    lines += ["", "## Role and output-slot composition", "",
              "Role/slot counts use each of the 2,000 panel neighborhoods once (not once per seed). Slot is the zero-based position in the frozen candidate array.", "",
              "| Role | Candidate slot | Neighborhood assignments |", "|---|---:|---:|"]
    for row in role_slot:
        lines.append(f"| {row['role']} | {row['slot_zero_based']} | {row['panel_neighborhood_assignments']} |")
    lines += ["", "### Anchor p(new) lift by semantic family and new-candidate slot", "",
              "Means are first computed within seed and stratum, then averaged across contributing seeds.", "",
              "| Family | New candidate slot | Seeds | Neighborhoods per seed | Mean anchor p(new) lift |",
              "|---|---:|---:|---|---:|"]
    for family, content in sorted(result["anchor_lift_by_family_and_new_slot"].items()):
        family_name, slot = family.rsplit("|slot_", 1)
        stats = content["mean_across_seed_means"]["new_lift"]
        lines.append(f"| {family_name} | {slot} | {content['seed_count']} | {content['neighborhoods_per_seed']} | {stats:+.6f} |")
    lines += ["", "### Anchor p(new) lift by candidate semantic identity", "",
              "| Candidate semantic ID | New-role count | Old-role count | Other-role count | Mean anchor p(new) lift when designated new |",
              "|---|---:|---:|---:|---:|"]
    for row in identity_rows:
        rc = row["role_counts"]
        lines.append(f"| {row['candidate_semantic_id']} | {rc.get('new', 0)} | {rc.get('old', 0)} | {rc.get('other', 0)} | {row['new_role_anchor_lift_mean_across_seed_means']} |")
    lines += ["", "## Outlier and competitor-switch overlap", "",
              "| Seed | Selective p(new) | Selective other mass | Fact-view strongest-competitor switch rate | Anchor old-MAP delta |",
              "|---:|---:|---:|---:|---:|"]
    interesting = {row["seed"] for row in (outlier_sorted[0], outlier_sorted[-1],
                  min(seed_rows, key=lambda item: item["selective_other_mass"]))}
    interesting.update(row["seed"] for row in switch_sorted[:8])
    for row in sorted((item for item in seed_rows if item["seed"] in interesting),
                      key=lambda item: item["fact_competitor_switch_rate"], reverse=True):
        lines.append(f"| {row['seed']} | {row['selective_new_probability']:+.6f} | {row['selective_other_mass']:+.6f} | {row['fact_competitor_switch_rate']:.1%} | {row['anchor_old_map_delta']:+.4f} |")
    lines += ["", "## Limits", "",
              "The raw prediction artifact contains probabilities, not logits; X2 therefore reports probability-scale old-minus-new margins only. `p(old)` is the contracted anchor target, and anchor MAP correctness is computed by comparing the frozen-order argmax with `old_candidate_id`. A branch shift on anchors is descriptive evidence about this fixed panel and candidate-role construction, not proof of a universal criterion shift.",
              "No target fields, checkpoints, or training telemetry were used. No inference or new panel opening occurred.", ""]
    report_path = OUT / "selectivity-anatomy-x2-v01.md"
    with report_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines)); stream.flush(); os.fsync(stream.fileno())

    source_path = Path(__file__).resolve()
    files = [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}
             for path in (source_path, json_path, report_path)]
    root = hashlib.sha256("".join(f"{r['path']}\t{r['bytes']}\t{r['sha256']}\n" for r in files).encode()).hexdigest()
    seal = {"status": "Q_R2_X2_EXPLORATORY_OUTPUTS_SEALED", "identity": result["identity"],
            "input_prediction_sha256": RAW_SHA, "completion_seal_sha256": COMPLETION_SHA,
            "x1_json_sha256": X1_SHA, "x1_seal_sha256": x1_seal_sha, "files": files,
            "output_root_sha256": root, "registered_q_r2_and_x1_modified": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat()}
    seal_path = OUT / "selectivity-anatomy-x2-seal-v01.json"
    with seal_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(seal, indent=2) + "\n"); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps({"status": result["status"], "report": str(report_path), "seal": str(seal_path),
                      "output_root_sha256": root, "anchor_new_lift_mean": anchor_lift["mean"],
                      "anchor_old_map_delta_mean": anchor_map_delta["mean"],
                      "selective_new_mean": select_new["mean"],
                      "selective_new_median": select_new["median"],
                      "selective_new_negative_seeds": select_new["negative"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
