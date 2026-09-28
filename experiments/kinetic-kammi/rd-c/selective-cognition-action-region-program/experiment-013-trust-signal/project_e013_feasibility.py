#!/usr/bin/env python3
"""Precontact feasibility math for E013 v0.3; no bank or model access."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program")
OUT = ROOT / "experiment-013-trust-signal" / "E013-FEASIBILITY-PROJECTIONS-v0.3.json"
SMALL_MS = 11621.291 / 48.0
LARGE_MS = 147675.950 / 48.0
SCENARIOS = {
    "E012_pessimistic": {"p_correct": 7 / 48, "p_wrong": 11 / 48},
    # Planning assumption only: 50% raw proposal yield at 50% raw precision.
    "nominal_planning_assumption": {"p_correct": 0.25, "p_wrong": 0.25},
}
BANKS = {"development": 864, "confirmation": 1120}

def binom_tail(n: int, p: float, cutoff: int) -> float:
    if cutoff <= 0:
        return 1.0
    if cutoff > n:
        return 0.0
    q = 1.0 - p
    term = q ** n
    total = 0.0
    for k in range(n):
        term *= ((n - k) / (k + 1)) * (p / q)
        if k + 1 >= cutoff:
            total += term
    return min(1.0, max(0.0, total))

def binom_cdf(n: int, p: float, cutoff: int) -> float:
    """P(X <= cutoff), evaluated by the binomial recurrence."""
    if cutoff < 0:
        return 0.0
    if cutoff >= n:
        return 1.0
    q = 1.0 - p
    term = q ** n
    total = term
    for k in range(cutoff):
        term *= ((n - k) / (k + 1)) * (p / q)
        total += term
    return min(1.0, max(0.0, total))

def cp_upper(n: int, errors: int, alpha: float = 0.05) -> float:
    """One-sided exact Clopper-Pearson upper limit."""
    if errors >= n:
        return 1.0
    lo, hi = errors / n, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if binom_cdf(n, mid, errors) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0

def minimum_support(errors: int, epsilon: float = 0.05) -> tuple[int, float]:
    n = max(1, errors + 1)
    while cp_upper(n, errors) > epsilon:
        n += 1
    return n, cp_upper(n, errors)

def multinomial_joint_tail(n: int, pc: float, pw: float, min_c: int, min_w: int) -> float:
    """P(C>=min_c,W>=min_w) for iid C/W/null task categories."""
    q = 1.0 - pc
    conditional_wrong = pw / q
    term = q ** n  # P(C=0)
    total = 0.0
    for c in range(n + 1):
        if c >= min_c:
            total += term * binom_tail(n - c, conditional_wrong, min_w)
        if c < n:
            term *= ((n - c) / (c + 1)) * (pc / q)
    return min(1.0, max(0.0, total))

def scenario_row(name: str, n: int, pc: float, pw: float) -> dict:
    proposals = pc + pw
    return {
        "scenario": name,
        "tasks": n,
        "p_correct_raw_proposal": pc,
        "p_wrong_raw_proposal": pw,
        "p_no_proposal": 1.0 - proposals,
        "expected_correct_proposals": n * pc,
        "expected_wrong_proposals": n * pw,
        "expected_nonnull_proposals": n * proposals,
        "prob_T5_at_least_100_correct_and_100_wrong": multinomial_joint_tail(n, pc, pw, 100, 100),
        "t1_screen_jobs_4_per_nonnull": 4 * n * proposals,
        "t2_small_evaluations_3_per_nonnull": 3 * n * proposals,
        "t3_candidate_score_evaluations_4_per_nonnull": 4 * n * proposals,
        "t4_pairwise_evaluations_12_per_nonnull": 12 * n * proposals,
        "t6_separate_none_schema_evaluations_per_task": n,
        "t6_estimated_small_pass_seconds": n * SMALL_MS / 1000.0,
        "t2_estimated_small_pass_seconds": 3 * n * proposals * SMALL_MS / 1000.0,
        "t3_estimated_small_pass_seconds": 4 * n * proposals * SMALL_MS / 1000.0,
        "t4_estimated_small_pass_seconds": 12 * n * proposals * SMALL_MS / 1000.0,
    }

def main() -> None:
    rows = []
    for name, s in SCENARIOS.items():
        for bank, n in BANKS.items():
            row = scenario_row(name, n, s["p_correct"], s["p_wrong"])
            row["bank"] = bank
            rows.append(row)
    conf = []
    for name, s in SCENARIOS.items():
        pc = s["p_correct"]
        for n in (512, BANKS["confirmation"]):
            conf.append({
                "scenario": name,
                "tasks": n,
                "oracle_expected_correct_proposals": n * pc,
                "oracle_probability_at_least_59": binom_tail(n, pc, 59),
                "oracle_probability_at_least_93": binom_tail(n, pc, 93),
                "rho_70_expected_accepted_correct": n * pc * 0.70,
                "rho_70_probability_at_least_93": binom_tail(n, pc * 0.70, 93),
                "rho_50_expected_accepted_correct": n * pc * 0.50,
                "rho_50_probability_at_least_93": binom_tail(n, pc * 0.50, 93),
                "rho_required_for_59": 59 / (n * pc),
                "rho_required_for_93": 93 / (n * pc),
            })
    result = {
        "schema_version": 1,
        "artifact_id": "E013-FEASIBILITY-PROJECTIONS-v0.3",
        "model_contact": False,
        "banks_built": False,
        "assumptions": {
            "E012_pessimistic_source": "small raw proposals: 7 correct, 11 wrong, 30 null among 48 tasks",
            "nominal_planning_assumption": "25% correct proposals, 25% wrong proposals, 50% no proposal; scenario only, not an empirical estimate or bank requirement",
            "iid_limitation": "Binomial/multinomial probabilities ignore repository/family clustering and are planning illustrations, not guarantees or inferential claims.",
            "four_candidate_signal_workload": "T1 has four screening jobs; T2 has three perturbations; T3 scores four candidate IDs; T4 has six pairs in both orientations (12 observer evaluations). Each applies only to non-null baseline proposals, except base inference/T5 capture which occur once per task.",
            "runtime_timing_proxy": "E012 full-call averages (small 242.11 ms, large 3076.58 ms) scale extra small-observer evaluations only; T1 execution time and teacher-forced scoring speed are unmeasured.",
        },
        "baseline_ms_per_call": {"small": SMALL_MS, "large": LARGE_MS},
        "banks": rows,
        "confirmation_gate_support": conf,
        "exact_gate_minimum_support": [
            {"errors": x, "minimum_n": minimum_support(x)[0],
             "upper_error_bound": minimum_support(x)[1], "epsilon": 0.05}
            for x in range(4)
        ],
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Independent deterministic checks of the calculations and gate boundary.
    assert round(binom_tail(512, 7 / 48, 59), 3) == 0.981
    assert round(binom_tail(512, 7 / 48, 93), 3) == 0.015
    assert multinomial_joint_tail(864, 7 / 48, 11 / 48, 100, 100) > 0.99
    assert multinomial_joint_tail(576, 7 / 48, 11 / 48, 100, 100) < 0.05
    assert minimum_support(0)[0] == 59 and minimum_support(1)[0] == 93
    assert cp_upper(59, 0) <= 0.05 and cp_upper(93, 1) <= 0.05
    print(json.dumps({"output": str(OUT), "banks": rows,
                      "confirmation_gate_support": conf,
                      "exact_gate_minimum_support": result["exact_gate_minimum_support"]}, indent=2))

if __name__ == "__main__":
    main()
