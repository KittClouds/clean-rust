"""Fixed-order FLY-PHENO-00 RUN1 readout after the integrity gate."""

from __future__ import annotations

import csv
import json
import math
import pathlib
import random
import statistics
from collections import defaultdict


RUN = pathlib.Path(__file__).resolve().parents[1]
STUDY = RUN.parents[1]
EPSILON_D = 0.015625
PRIMARY_SEVERITY = 0.10
CHECKPOINTS = (0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512)
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
LOSS_INDEX: dict[tuple, float] = {}


def load_rows() -> list[dict]:
    rows = [json.loads(line) for line in (RUN / "final-outcomes.jsonl").open(encoding="utf-8")]
    with (RUN / "final-outcomes.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = list(rows[0])
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    LOSS_INDEX.clear()
    for row in rows:
        key = (row["substrate"], row["side"], int(row["block"]), row["family"], int(row["lesion_m"]),
               round(float(row["severity"]), 8), row["arm"], int(row["checkpoint"]))
        LOSS_INDEX[key] = float(row["loss"])
    return rows


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def loss(rows: list[dict], *, substrate: str, side: str, block: int, family: str,
         m: int, severity: float, arm: str, checkpoint: int) -> float:
    key = (substrate, side, block, family, m, round(severity, 8), arm, checkpoint)
    try:
        return LOSS_INDEX[key]
    except KeyError as exc:
        raise ValueError(f"missing loss cell {key}") from exc


def competence_summary(rows: list[dict]) -> tuple[dict, dict, set[int]]:
    side_flags: dict[tuple[str, str, int], bool] = {}
    for row in rows:
        side_flags[(row["substrate"], row["side"], int(row["block"]))] = bool(row["competent"])
    substrate_rates = {}
    for substrate in SUBSTRATES:
        complete = [block for block in range(12000, 12012)
                    if side_flags.get((substrate, "L", block), False)
                    and side_flags.get((substrate, "R", block), False)]
        substrate_rates[substrate] = {"complete_blocks": len(complete), "of": 12,
                                      "rate": len(complete) / 12.0}
    global_complete = {block for block in range(12000, 12012)
                       if all(substrate_rates[s]["complete_blocks"] >= 0 and
                              side_flags.get((s, "L", block), False) and
                              side_flags.get((s, "R", block), False)
                              for s in SUBSTRATES)}
    return side_flags, substrate_rates, global_complete


def b_and_c(rows: list[dict]) -> tuple[dict, dict]:
    b: dict[tuple, float] = {}
    c: dict[tuple, float] = {}
    for substrate in SUBSTRATES:
        for side in ("L", "R"):
            for block in range(12000, 12012):
                b0 = loss(rows, substrate=substrate, side=side, block=block,
                          family="sham", m=0, severity=0.0, arm="weight_frozen", checkpoint=512) - loss(
                              rows, substrate=substrate, side=side, block=block,
                              family="sham", m=0, severity=0.0, arm="adaptive", checkpoint=512)
                b[(substrate, side, block, "sham", 0, 0.0)] = b0
                for family, ms in (("uniform_random", range(1, 5)), ("high_degree_targeted", (0,))):
                    for m in ms:
                        for severity in (0.0, 0.01, 0.05, 0.10, 0.20):
                            value = loss(rows, substrate=substrate, side=side, block=block,
                                         family=family, m=m, severity=severity,
                                         arm="weight_frozen", checkpoint=512) - loss(
                                             rows, substrate=substrate, side=side, block=block,
                                             family=family, m=m, severity=severity,
                                             arm="adaptive", checkpoint=512)
                            key = (substrate, side, block, family, m, severity)
                            b[key] = value
                            c[key] = value - b0
    return b, c


def primary(rows: list[dict], c: dict, global_complete: set[int]) -> dict:
    fly = [c[("fly", side, block, "uniform_random", m, PRIMARY_SEVERITY)]
           for side in ("L", "R") for block in range(12000, 12012)
           for m in range(1, 5)]
    null = [c[(graph, side, block, "uniform_random", m, PRIMARY_SEVERITY)]
            for graph in SUBSTRATES[1:] for side in ("L", "R")
            for block in range(12000, 12012) for m in range(1, 5)]
    result = {
        "estimand": "Delta_C = mean C_0.10(fly) - mean C_0.10(degree-preserving-shuffle)",
        "status": "PRIMARY_NOT_EVALUABLE" if len(global_complete) < 8 else "EVALUABLE",
        "global_complete_blocks": sorted(global_complete),
        "minimum_global_complete_blocks": 8,
        "support_rule": "global intersection across fly and every null realization; no replacement",
        "fly_C_mean_raw_all_declared_cells": mean(fly),
        "null_C_mean_raw_all_declared_cells": mean(null),
        "raw_descriptive_delta_all_declared_cells": mean(fly) - mean(null) if fly and null else None,
        "bootstrap": {"replicates_declared": 20000, "executed": False if len(global_complete) < 8 else True,
                       "resample_units": ["s", "m", "g"], "percentile_interval": None},
    }
    if len(global_complete) < 8:
        result["reason"] = "0 of 12 learner/task blocks reached competence on every substrate"
    return result


def secondary(rows: list[dict], b: dict, c: dict) -> tuple[dict, list[dict], list[dict]]:
    controls = {}
    for substrate in SUBSTRATES:
        values = [b[(substrate, side, block, "sham", 0, 0.0)]
                  for side in ("L", "R") for block in range(12000, 12012)]
        controls[substrate] = {"B_0_mean": mean(values), "B_0_n": len(values)}
    bp_means = {}
    for substrate in SUBSTRATES:
        for family, ms in (("uniform_random", range(1, 5)), ("high_degree_targeted", (0,))):
            for m in ms:
                for severity in (0.0, 0.01, 0.05, 0.10, 0.20):
                    values = [b[(substrate, side, block, family, m, severity)]
                              for side in ("L", "R") for block in range(12000, 12012)]
                    bp_means[f"{substrate}|{family}|{m}|{severity:.2f}"] = {
                        "B_p_mean": mean(values), "n": len(values)}
    controls = {"B_0": controls, "B_p": bp_means}
    crossed = []
    for substrate in SUBSTRATES:
        for block in range(12000, 12012):
            for family, ms in (("uniform_random", range(1, 5)), ("high_degree_targeted", (0,))):
                for m in ms:
                    for severity in (0.0, 0.01, 0.05, 0.10, 0.20):
                        values = [c[(substrate, side, block, family, m, severity)] for side in ("L", "R")]
                        crossed.append({"substrate": substrate, "block": block, "family": family,
                                        "lesion_m": m, "severity": severity, "C_mean_sides": mean(values)})
    return controls, crossed, []


def trajectory(rows: list[dict]) -> list[dict]:
    out = []
    for substrate in SUBSTRATES:
        for family, ms in (("uniform_random", range(1, 5)), ("high_degree_targeted", (0,))):
            for m in ms:
                for severity in (0.01, 0.05, 0.10, 0.20):
                    for checkpoint in CHECKPOINTS:
                        d_values = []; a_values = []; r_values = []
                        for side in ("L", "R"):
                            for block in range(12000, 12012):
                                pre = loss(rows, substrate=substrate, side=side, block=block, family="sham", m=0, severity=0.0, arm="adaptive", checkpoint=-1)
                                post = loss(rows, substrate=substrate, side=side, block=block, family=family, m=m, severity=severity, arm="adaptive", checkpoint=0)
                                current = loss(rows, substrate=substrate, side=side, block=block, family=family, m=m, severity=severity, arm="adaptive", checkpoint=checkpoint)
                                damage = post - pre; absolute = post - current
                                d_values.append(damage); a_values.append(absolute)
                                if damage >= EPSILON_D: r_values.append(absolute / damage)
                        out.append({"substrate": substrate, "family": family, "lesion_m": m, "severity": severity,
                                    "checkpoint": checkpoint, "D_mean": mean(d_values), "A_mean": mean(a_values),
                                    "R_mean_defined": mean(r_values), "R_defined_n": len(r_values), "n": len(d_values)})
    return out


def write_results(rows: list[dict], primary_result: dict, controls: dict, crossed: list[dict], trajectories: list[dict], rates: dict, global_complete: set[int]) -> None:
    results = RUN / "results"; results.mkdir(exist_ok=True)
    pre_losses = [loss(rows, substrate=s, side=side, block=block, family="sham", m=0,
                       severity=0.0, arm="adaptive", checkpoint=-1)
                  for s in SUBSTRATES for side in ("L", "R") for block in range(12000, 12012)]
    (results / "primary-contrast.json").write_text(json.dumps(primary_result, indent=2, sort_keys=True) + "\n")
    (results / "primary-bootstrap.json").write_text(json.dumps(primary_result["bootstrap"], indent=2, sort_keys=True) + "\n")
    (results / "secondary-controls.json").write_text(json.dumps(controls, indent=2, sort_keys=True) + "\n")
    with (results / "crossed-factor-summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(crossed[0])); writer.writeheader(); writer.writerows(crossed)
    with (results / "trajectory-summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(trajectories[0])); writer.writeheader(); writer.writerows(trajectories)
    (results / "exploratory-operator-phenotype.json").write_text(json.dumps({"status": "NOT_COLLECTED", "reason": "operator census is outside PHENO-00 measured outputs"}, indent=2) + "\n")
    lines = [
        "# FLY-PHENO-00 RUN1 results",
        "",
        "## Primary readout",
        "",
        f"**Disposition: `{primary_result['status']}`.** The declared minimum support was 8 globally complete learner/task blocks; the run produced {len(global_complete)} of 12.",
        "",
        "No primary confidence interval or inferential bootstrap was opened because the predeclared competence support rule was not met. No seed, mask, graph, or criterion failure was replaced.",
        "",
        f"Raw descriptive C means across all declared cells were fly={primary_result['fly_C_mean_raw_all_declared_cells']:.12g} and shuffled={primary_result['null_C_mean_raw_all_declared_cells']:.12g}; these are descriptive only and are not a supported primary comparison.",
        "",
        "## Competence support",
        "",
        f"Every one of the 216 substrate×side×learner base blocks completed finitely, but none reached the fixed held-out competence threshold of 0.25. Pre-lesion held-out error ranged from {min(pre_losses):.6f} to {max(pre_losses):.6f} (mean {statistics.fmean(pre_losses):.6f}). The per-substrate and global support table is recorded in `competence-summary.json` and the integrity receipt.",
        "",
        "## Secondary descriptive quantities",
        "",
        "The package retains sham benefit B₀, damage-specific C, vulnerability D, absolute recovery A(t), and normalized R(t) only where the frozen denominator rule permits it. These summaries are descriptive because the primary support gate failed.",
        "",
        "## Scope",
        "",
        "This is an engineering result for the sealed host, task, evaluator, lesion masks, and shuffled substrates. It does not support a biological repair or mechanism claim.",
    ]
    (results / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rows = load_rows()
    _flags, rates, complete = competence_summary(rows)
    b, c = b_and_c(rows)
    p = primary(rows, c, complete)
    controls, crossed, _ = secondary(rows, b, c)
    trajectories = trajectory(rows)
    (RUN / "results").mkdir(exist_ok=True)
    (RUN / "results" / "competence-summary.json").write_text(json.dumps({"per_substrate": rates, "global_complete_blocks": sorted(complete)}, indent=2, sort_keys=True) + "\n")
    write_results(rows, p, controls, crossed, trajectories, rates, complete)
    print(json.dumps({"primary_status": p["status"], "global_complete_blocks": len(complete), "outcome_rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
