#!/usr/bin/env python3
"""Build/check the E013 v0.3.1 pre-bank package. No bank or model access."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program")
EXP = ROOT / "experiment-013-trust-signal"
ANATOMY = ROOT / "e012-readonly-anatomy-addendum"
WORKTREE = Path(r"C:\Users\shuga\.codex\worktrees\e013-episode-factory\clean-rust")
SCRIPT = WORKTREE / "experiments/e013-episode-factory/precontact-v031/build_precontact_v031.py"
HANDOFF_STATUS = WORKTREE / "experiments/e013-episode-factory/precontact-v031/HANDOFF-STATUS-v0.3.1.md"
PARENT_PROTOCOL = EXP / "E013-TRUST-SIGNAL-DEVELOPMENT-PROTOCOL-v0.3.md"
PARENT_LOCK = EXP / "E013-PROTOCOL-LOCK-v0.3.json"
PARENT_PROJECTIONS = EXP / "E013-FEASIBILITY-PROJECTIONS-v0.3.json"
PARENT_RECEIPT = EXP / "E013-FEASIBILITY-RECEIPT-v0.3.md"
RAW_YIELD = ANATOMY / "E012-RAW-PROPOSAL-YIELD-v1.0.json"
POSITIVE_CONTROL = ANATOMY / "E012-POSITIVE-CONTROL-DESIGN-v1.2.md"
LAB_LAW = Path(r"D:\1-story\1-Notes Central\1- Core story\Newest Data\1-clean data\Lore\part 2\World\1-rewrite\!1-notes\! V5 rewite\Frozen Fabrique\Lab Law.txt")
LAB_GRANT = Path(r"D:\1-story\1-Notes Central\1- Core story\Newest Data\1-clean data\Lore\part 2\World\1-rewrite\!1-notes\! V5 rewite\Frozen Fabrique\lab law grant.txt")
PROTOCOL = EXP / "E013-PROTOCOL-AMENDMENT-v0.3.1.md"
PROJECTIONS = EXP / "E013-FEASIBILITY-PROJECTIONS-v0.3.1.json"
RECEIPT = EXP / "E013-FEASIBILITY-RECEIPT-v0.3.1.md"
LOCK = EXP / "E013-PROTOCOL-LOCK-v0.3.1.json"
VERIFY_RECEIPT = EXP / "E013-PRECONTACT-VERIFICATION-v0.3.1.json"
EXPECTED_PARENT_LOCK_SHA = "422efcda45938c5aa1258c49afd101ef30fa4f4405ed3b7a70945a4716aec788"

SMALL_MS = 11621.291 / 48.0
LARGE_MS = 147675.950 / 48.0
EPSILON = 0.05


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def binom_cdf(n: int, p: float, k: int) -> float:
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    q = 1.0 - p
    term = q**n
    total = term
    for j in range(k):
        term *= ((n - j) / (j + 1)) * (p / q)
        total += term
    return min(1.0, max(0.0, total))


def binom_tail(n: int, p: float, k: int) -> float:
    if k <= 0:
        return 1.0
    if k > n or p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    return min(1.0, max(0.0, 1.0 - binom_cdf(n, p, k - 1)))


def cp_upper(n: int, errors: int, alpha: float = 0.05) -> float:
    if n <= 0 or errors < 0 or errors > n:
        raise ValueError("require n > 0 and 0 <= errors <= n")
    if errors == n:
        return 1.0
    lo, hi = errors / n, 1.0
    for _ in range(90):
        mid = (lo + hi) / 2.0
        if binom_cdf(n, mid, errors) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def minimum_support(errors: int) -> tuple[int, float]:
    n = max(1, errors + 1)
    while cp_upper(n, errors) > EPSILON:
        n += 1
    return n, cp_upper(n, errors)


def max_errors_at_expected_support(correct_accepts: int) -> int:
    passing = -1
    for errors in range(correct_accepts + 1):
        n = correct_accepts + errors
        if n >= 60 and cp_upper(n, errors) <= EPSILON:
            passing = errors
        elif passing >= 0:
            break
    return passing


def multinomial_joint_tail(n: int, pc: float, pw: float, min_c: int, min_w: int) -> float:
    q = 1.0 - pc
    conditional_wrong = pw / q
    term = q**n
    total = 0.0
    for correct in range(n + 1):
        if correct >= min_c:
            total += term * binom_tail(n - correct, conditional_wrong, min_w)
        if correct < n:
            term *= ((n - correct) / (correct + 1)) * (pc / q)
    return min(1.0, max(0.0, total))


def yield_row(n: int, pc: float, pw: float) -> dict[str, Any]:
    pnull = 1.0 - pc - pw
    nonnull = n * (pc + pw)
    return {
        "tasks": n, "p_correct": pc, "p_wrong": pw, "p_no_proposal": pnull,
        "expected_correct_raw": n * pc, "expected_wrong_raw": n * pw,
        "expected_no_proposal": n * pnull, "expected_nonnull": nonnull,
        "prob_T5_at_least_100_correct_and_wrong": multinomial_joint_tail(n, pc, pw, 100, 100),
        "T1_screen_jobs": 4 * nonnull, "T2_small_evaluations": 3 * nonnull,
        "T3_candidate_score_evaluations": 4 * nonnull, "T4_pairwise_evaluations": 12 * nonnull,
        "T2_full_small_call_proxy_seconds": 3 * nonnull * SMALL_MS / 1000.0,
        "T3_full_small_call_proxy_seconds_not_teacher_forced_actual": 4 * nonnull * SMALL_MS / 1000.0,
        "T4_full_small_call_proxy_seconds": 12 * nonnull * SMALL_MS / 1000.0,
    }


def fixed_recall_rows(label: str, pc: float, pw: float, tasks: int) -> list[dict[str, Any]]:
    wrong_pool = tasks * pw
    rows = []
    for recall in (0.5, 0.7, 0.9):
        expected_correct = tasks * pc * recall
        rounded_correct = round(expected_correct)
        max_errors = max_errors_at_expected_support(rounded_correct)
        asymptotic_far = pc * recall * (1.0 - EPSILON) / (EPSILON * pw)
        rows.append({
            "scenario": label, "target_correct_proposal_recall": recall,
            "expected_correct_accepts": expected_correct,
            "rounded_expected_correct_accepts_for_gate_illustration": rounded_correct,
            "expected_wrong_raw_pool": wrong_pool,
            "max_wrong_accepts_at_rounded_expected_support": max_errors,
            "finite_gate_FAR_among_wrong_raw_pool": max_errors / wrong_pool,
            "asymptotic_FAR_ceiling_for_5pct_empirical_risk": asymptotic_far,
            "actual_gate_uses_realized_integer_counts": True,
        })
    return rows


def project() -> dict[str, Any]:
    banks = {"D": (864, 48), "C": (1120, 64)}
    pooled = (7 / 48, 11 / 48)
    nominal = (0.25, 0.25)
    # E012 strata: nonempty 7C/9W/24N of 40; empty 0C/2W/6N of 8.
    stratum_candidate = (7 / 40, 9 / 40)
    stratum_empty = (0.0, 2 / 8)
    bank_rows: dict[str, Any] = {}
    for name, (n, empty) in banks.items():
        candidate = n - empty
        matched = (
            (candidate * stratum_candidate[0] + empty * stratum_empty[0]) / n,
            (candidate * stratum_candidate[1] + empty * stratum_empty[1]) / n,
        )
        bank_rows[name] = {
            "design": {"tasks": n, "candidate_selection": candidate, "empty_valid": empty},
            "pooled_E012_conservative": yield_row(n, *pooled),
            "nominal_assumption": yield_row(n, *nominal),
            "E012_stratum_standardized_sensitivity_only": yield_row(n, *matched),
        }
    confirmation_n = banks["C"][0]
    gate_probability = []
    for label, pc in (("E012_pooled_conservative", pooled[0]), ("nominal", nominal[0])):
        for recall in (1.0, 0.5, 0.7, 0.9):
            p = pc * recall
            gate_probability.append({
                "scenario": label, "recall": recall, "tasks": confirmation_n,
                "expected_correct_accepts": confirmation_n * p,
                "P_at_least_59_CP_only": binom_tail(confirmation_n, p, 59),
                "P_at_least_60_combined_zero_error_gate": binom_tail(confirmation_n, p, 60),
                "P_at_least_93_one_error_support": binom_tail(confirmation_n, p, 93),
            })
    c_match = bank_rows["C"]["E012_stratum_standardized_sensitivity_only"]
    specificity = {
        "E012_pooled_C1120": fixed_recall_rows("E012_pooled", *pooled, confirmation_n),
        "nominal_C1120": fixed_recall_rows("nominal", *nominal, confirmation_n),
        "E012_stratum_sensitivity_C1120": fixed_recall_rows(
            "E012_stratum_standardized", c_match["p_correct"], c_match["p_wrong"], confirmation_n),
    }
    nonnull_rate = 18 / 48
    time_margin = []
    for recall in (0.5, 0.7, 0.9):
        direct_share = pooled[0] * recall
        saved = direct_share * LARGE_MS
        margin = saved - SMALL_MS
        time_margin.append({
            "correct_proposal_recall": recall, "large_time_saved_ms_per_task": saved,
            "small_base_call_ms_per_task": SMALL_MS,
            "remaining_trust_and_screen_budget_ms_per_task": margin,
            "remaining_budget_ms_per_nonnull_proposal_at_E012_rate": margin / nonnull_rate,
            "assumes_zero_wrong_accepts_and_excludes_semantic_harm": True,
        })
    cp = [{"errors": x, "min_n": minimum_support(x)[0], "upper_error_bound": minimum_support(x)[1]}
          for x in range(5)]
    return {
        "schema_version": 1, "artifact_id": "E013-FEASIBILITY-PROJECTIONS-v0.3.1",
        "banks_built_by_agent": False, "bank_owner": "USER", "E013_model_contact": False,
        "E012_yield": {"all": {"correct": 7, "wrong": 11, "no_proposal": 30, "tasks": 48},
                       "candidate_selection": {"correct": 7, "wrong": 9, "no_proposal": 24, "tasks": 40},
                       "empty_valid": {"correct": 0, "wrong": 2, "no_proposal": 6, "tasks": 8}},
        "planning_scenarios": {
            "pooled_E012_is_conservative_reference": "applies 7/48 correct, 11/48 wrong, 30/48 no-proposal to every bank task",
            "nominal_not_empirical": "25% correct, 25% wrong, 50% no-proposal",
            "stratum_standardized_sensitivity": "reweights E012 candidate-selection and empty-valid rates to E013 fixed strata; not an E013 yield claim",
            "iid_limitation": "planning probabilities ignore repository/family clustering",
        },
        "banks": bank_rows,
        "exact_gate": {"n_min": 60, "epsilon": EPSILON, "CP_only_zero_error_minimum": 59,
                       "combined_zero_error_minimum": 60, "minimums_by_errors": cp},
        "confirmation_support": {
            "C1120": gate_probability,
            "old_512_comparison": {
                "P_at_least_59_CP_only": binom_tail(512, pooled[0], 59),
                "P_at_least_60_combined_zero_error_gate": binom_tail(512, pooled[0], 60),
                "P_at_least_59_at_70pct_recall": binom_tail(512, pooled[0] * 0.7, 59),
                "P_at_least_60_at_70pct_recall": binom_tail(512, pooled[0] * 0.7, 60),
            },
        },
        "fixed_recall_FAR": specificity,
        "time_planning": {
            "small_full_call_ms": SMALL_MS, "large_full_call_ms": LARGE_MS,
            "E012_nonnull_rate": nonnull_rate, "break_even_headroom": time_margin,
            "full_call_equivalent_ms_per_task": {
                "T2_three_extra_small_evals": 3 * nonnull_rate * SMALL_MS,
                "T3_four_small_full_calls_not_actual_teacher_forced_cost": 4 * nonnull_rate * SMALL_MS,
                "T4_twelve_extra_small_evals": 12 * nonnull_rate * SMALL_MS,
                "T5_extra_model_calls_if_inline_hook_passes_identity": 0,
                "T1_runtime_screen_cost": "UNMEASURED; must be timed and charged",
            },
        },
        "positive_control": {
            "id": "E012-PC-01-v1.2", "tasks": 64,
            "criterion": "at least 8 accepts and >=80% observed precision per cohort; coarse recurrence diagnostic only",
            "c_use": "lineage only; does not update E013 planning projections or bank construction",
            "E013_D_scale_ratio": 864 / 64, "E013_C_scale_ratio": 1120 / 64,
        },
    }


AMENDMENT = r'''# R&D-C / Frozen Fabrique — E013 Protocol Amendment v0.3.1

**Effective protocol ID:** `E013-TRUST-SIGNAL-DEVELOPMENT-v0.3.1`  
**Parent:** sealed `E013-TRUST-SIGNAL-DEVELOPMENT-v0.3`, SHA-256 `74910aededa494c49f741a05fa4d632e1f46c8466ae31ac2447f42832f25c70e`  
**State:** `SEALED_PRECONTACT_DESIGN_ONLY`  
**Contact:** E013-D/C unauthorized; the separate E012 positive control remains authorized but awaits the user-built bank.  
**Bank owner:** user. This amendment creates no bank, task, fixture, seed, label, observer run, or model call.

The effective v0.3.1 protocol is the sealed v0.3 protocol plus the clauses below. These clauses supersede only the corresponding v0.3 requirements. All other v0.3 definitions, bank counts, observer identities, signal definitions, authority, and replay rules remain in force. The v0.3 file and lock remain byte-identical. Its filename/title say v0.3 while its internal ID/status/revision lines say v0.2; this is preserved as a historical identity defect, and v0.3.1 supplies the corrected effective identity.

## 1. Bank-builder locks before task-bank freeze

### Visible-evidence principle

Visible screening represents evidence plausibly available to an ordinary contributor before protected evaluation: patch application, normal compilation/type checking, repository linting, and a deliberately exposed subset of ordinary tests. Hidden completion checks cover task-authoritative behavior not exposed to the router. Select and freeze the visible/hidden partition from the task contract before model contact. Never select or strengthen visible tests in response to observer outputs.

Keep visible and hidden fixtures in disjoint roots with separate manifests and label-writer permissions. The public frame may receive only the designated visible results after a paid/receipted screen. Construction telemetry and hidden labels never enter the observer frame.

### Construction-time T1 cost profile

During bank construction, run the full visible sequence (`apply -> compile/type-check -> lint -> visible tests`) on a known reference-valid patch for every task. Receipt per-stage CPU time and wall time, peak memory when available, host and tool versions, and cache/warm-state conditions. This profile is construction telemetry only: do not expose it to observers, reuse it as the T1 result for an offered candidate, pre-screen offered candidates for later free reuse, or alter fixtures after contact. Measure T1 separately on the small observer's proposed candidate during the experiment; charge every screen as incremental routing cost unless the large-only comparator performs those exact screens.

### Pair and empty-valid construction honesty

Retain the v0.3 truth-changing-pair counts. Pair members must have byte-identical offered candidate patches and identical producer order; task/environment semantics must make the valid set change. Do not encode the changed answer in IDs, order, formatting, family labels, or obvious wording artifacts.

Retain the v0.3 empty-valid quotas. These tasks must look like ordinary candidate-selection tasks with four plausible offered patches; only the sealed executable contract check establishes that the valid set is empty. Do not make them identifiable by malformed candidates, unusual candidate counts, special metadata, or conspicuous phrasing.

## 2. Fixed-correct-recall false-accept diagnostic

In E013-D, for every available trust signal, report false-accept rate at 50%, 70%, and 90% recall of correct non-null raw proposals. Use repository-grouped out-of-fold scores for fitted signals. Define:

```text
correct-proposal recall = correct raw proposals accepted / all correct raw proposals
FAR = wrong raw proposals accepted / all wrong raw proposals
```

All wrong raw proposals enter the FAR denominator, including proposals on empty-valid-set tasks. `NO_PROPOSAL` stays separate and cannot be recovered by a trust signal. At each recall target, use the least-permissive whole-tie threshold that reaches or exceeds the target; report achieved recall, accepted-correct count, accepted-wrong count, total wrong-proposal denominator, FAR, and accepted risk. If ties prevent the target, report the nearest attainable whole-tie point and mark the exact target unavailable. These are development diagnostics, not independent admission gates or a substitute for risk-coverage. Confirmation uses only the frozen development-selected route and threshold.

The oracle-trust ceiling remains an evaluation-only outcome: accept exactly correct non-null proposals. It cannot create a proposal when the small observer returns `NO_PROPOSAL`.

## 3. Fallback accuracy by proposal availability

On E013-C, use the already-required large-only lane to report large raw-action correctness and large-only task completion conditional on the small raw outcome: `NO_PROPOSAL`, `RAW_CORRECT_PROPOSAL`, `RAW_WRONG_PROPOSAL`, and non-null aggregate. Give denominators and repository/family strata. This is a post-outcome diagnostic only; hidden labels do not become routing features or task-selection criteria. Never treat the large observer as ground truth.

## 4. Primary resource axis and gate replacement

The primary engineering resource axis is paired mean end-to-end wall-clock milliseconds per task versus large-only. On the same host and loaded model versions, run both lanes without concurrent benchmark work and balance or randomize lane order by task block. The measured interval includes small inference, routing, receipts, every incremental T1 screen, large fallback, retries, and tool work; it excludes one-time model loading and bank construction. Report paired per-task deltas, the pooled mean (primary), median, p50/p95, and repository/family results. Repository/family-cluster resampling is descriptive uncertainty, not a new gate.

Replace v0.3 admission condition 4 with: no lower observed completed-task count than large-only; at least one large call displaced; and a strictly lower paired mean end-to-end wall time per task. A favorable token, inference-cost, or tool-cost result cannot rescue a failed primary wall-time criterion. Report those axes separately with small/large calls, logical evaluations, screen jobs and durations, input/generated tokens, inference cost, environment/tool cost, and peak memory when available. Do not form an unregistered scalar utility. Every visible screen is incremental unless large-only performs the same screen.

The semantic gate is unchanged: `n_min=60` and one-sided exact 95% Clopper–Pearson upper semantic-error bound `<=5%`. The 59-accept number is only the zero-error CP boundary; it does not satisfy the combined E013 gate. One, two, three, and four errors require at least 93, 124, 153, and 181 accepts respectively. No lowering of the risk bound or post-outcome bank expansion is allowed.

## 5. Positive-control and feasibility boundary

The existing `E012-POSITIVE-CONTROL-DESIGN-v1.2` already freezes `n_accept >= 8` and observed precision `>=80%` per cohort, exact intervals, the between-cohort contrast, and raw correct-proposal yield `c`. Call a passing result only coarse recurrence, never recovery of a safety-qualified region. Under v1.2, `c` is lineage-only and cannot update E013 projections, bank composition, task selection, or trust-signal rules. Any future use requires a versioned amendment before the affected bank is sealed.

The 64-task control is 13.5 times smaller than E013-D (864 tasks) and 17.5 times smaller than E013-C (1,120 tasks); do not describe it as exactly a twelve-times scale-up. Its bank is user-built and absent here, so it remains pending.

## 6. Current execution boundary

E013-D has 864 tasks and E013-C has 1,120 tasks under the unchanged v0.3 design. The user owns construction. No bank, task, fixture, seed, T1 screen, observer call, model/API contact, or scoring was performed by this work. E013-D/C contact remains unauthorized. The v0.3 artifacts remain preserved unchanged.
'''


def md_receipt(data: dict[str, Any]) -> str:
    pooled = data["banks"]["C"]["pooled_E012_conservative"]
    nominal = data["banks"]["C"]["nominal_assumption"]
    sens = data["banks"]["C"]["E012_stratum_standardized_sensitivity_only"]
    far = data["fixed_recall_FAR"]
    timing = data["time_planning"]
    rows = far["E012_pooled_C1120"]
    out = [
        "# E013 Precontact Feasibility Receipt v0.3.1", "",
        "State: `PRECONTACT_FEASIBILITY_COMPLETE; USER_BANKS_PENDING; NO_E013_MODEL_CONTACT`  ",
        "Date: 2026-09-26  ",
        "Purpose: reconcile proposal yield, exact-gate specificity, trust-signal compute, T1 costs, fallback reporting, and the primary resource axis before bank freeze.", "",
        "## Lab Law and ownership boundary", "",
        "The exact supplied `Lab Law.txt` and `lab law grant.txt` files were read and their hashes are bound by this lock. The former is the System 1.5 Lab charter; the latter is strategic/funding guidance, not the E013 protocol. The user owns E013 bank construction. No bank or model contact occurred.", "",
        "## E012 yield and bank-composition sensitivity", "",
        "E012 pooled: 7 correct, 11 wrong, 30 `NO_PROPOSAL` of 48. By stratum: candidate-selection 7/9/24 of 40; empty-valid 0/2/6 of 8. The pooled rate is retained as the conservative planning proxy. Reweighting the E012 strata to the fixed E013 quotas yields:", "",
        "| Bank | Candidate-selection + empty tasks | Expected correct / wrong / no-proposal |", "|---|---:|---:|",
        "| D, 864 | 816 + 48 | 142.8 / 195.6 / 525.6 |",
        f"| C, 1,120 | 1,056 + 64 | {sens['expected_correct_raw']:.1f} / {sens['expected_wrong_raw']:.1f} / {sens['expected_no_proposal']:.1f} |", "",
        "The stratum-weighted values are a sensitivity, not an E013 yield claim. They assume E012 within-stratum rates transfer. E012 old-rectangle acceptance was 6/7 correct and 10/11 wrong; that failed contract is not reused.", "",
        "## Exact support and false-accept specificity", "",
        "The combined gate is `n>=60` plus exact one-sided 95% upper error bound `<=5%`. Zero errors alone reaches the CP boundary at 59, so 59 is CP-only. One through four errors require 93, 124, 153, and 181 accepts.", "",
        "At C=1,120 under pooled E012 rates, expected correct/wrong raw proposals are "
        f"{pooled['expected_correct_raw']:.1f}/{pooled['expected_wrong_raw']:.1f}. At rounded expected correct support, the exact gate permits:", "",
        "| Correct-proposal recall | Expected correct accepts | Max wrong accepts at expected support | FAR of wrong raw pool |", "|---:|---:|---:|---:|",
    ]
    for row in rows:
        out.append(f"| {row['target_correct_proposal_recall']:.0%} | {row['expected_correct_accepts']:.1f} | {row['max_wrong_accepts_at_rounded_expected_support']} | {row['finite_gate_FAR_among_wrong_raw_pool']:.2%} |")
    out += [
        "", "For comparison, the asymptotic 5% risk ceilings at 50/70/90% recall are "
        + "/".join(f"{r['asymptotic_FAR_ceiling_for_5pct_empirical_risk']:.2%}" for r in rows)
        + ". The finite exact gate at expected support is stricter. Under nominal 25/25/50 rates, finite-gate FAR illustrations are "
        + "/".join(f"{r['finite_gate_FAR_among_wrong_raw_pool']:.2%}" for r in far["nominal_C1120"])
        + "; under stratum sensitivity they are "
        + "/".join(f"{r['finite_gate_FAR_among_wrong_raw_pool']:.2%}" for r in far["E012_stratum_sensitivity_C1120"])
        + ". These fractional-mean calculations are planning illustrations; actual admission uses realized integer counts.", "",
        "E013-D will report empirical FAR at 50/70/90% correct-proposal recall for every available signal, using repository-grouped out-of-fold scores and whole ties. `NO_PROPOSAL` remains separate; a trust signal cannot manufacture proposals.", "",
        "## Signal workload and economic headroom", "",
        "For each non-null four-candidate proposal, v0.3 charges T1 four screen jobs, T2 three extra small evaluations, T3 four teacher-forced candidate scores, and T4 twelve pairwise evaluations. T5 is zero additional model calls only if an inline hook passes the no-hook identity check; hook wall time still must be measured. T1 runtime cost and actual T3 teacher-forced latency are unmeasured.", "",
        "Projected logical evaluations and rough full-small-call-equivalent time (using E012's small-call mean) are:", "",
        "| Bank / scenario | T1 jobs | T2 evals / proxy | T3 evals / proxy* | T4 evals / proxy |",
        "|---|---:|---:|---:|---:|",
    ]
    scenario_keys = (("pooled_E012_conservative", "pooled"), ("nominal_assumption", "nominal"),
                     ("E012_stratum_standardized_sensitivity_only", "stratum sensitivity"))
    for bank in ("D", "C"):
        for key, label in scenario_keys:
            row = data["banks"][bank][key]
            out.append(
                f"| {bank}{row['tasks']} / {label} | {row['T1_screen_jobs']:.0f} | "
                f"{row['T2_small_evaluations']:.0f} / {row['T2_full_small_call_proxy_seconds'] / 60:.2f} min | "
                f"{row['T3_candidate_score_evaluations']:.0f} / {row['T3_full_small_call_proxy_seconds_not_teacher_forced_actual'] / 60:.2f} min* | "
                f"{row['T4_pairwise_evaluations']:.0f} / {row['T4_full_small_call_proxy_seconds'] / 60:.2f} min |"
            )
    out += [
        "", "*T3's full-call proxy is not its measured teacher-forced cost. Batch execution may reduce request overhead but does not remove logical evaluations. T1 screen CPU/wall cost remains unmeasured until the user bank builder profiles it.", "",
        f"E012 mean full calls: {SMALL_MS:.2f} ms small, {LARGE_MS:.2f} ms large. Under pooled E012 yield and zero false accepts, the large-call saving minus the always-paid small call leaves "
        + "/".join(f"{r['remaining_trust_and_screen_budget_ms_per_task']:.1f} ms/task" for r in timing["break_even_headroom"])
        + " at 50/70/90% correct-proposal recall. At 70%, that is only "
        + f"{timing['break_even_headroom'][1]['remaining_budget_ms_per_nonnull_proposal_at_E012_rate']:.1f} ms per non-null proposal at E012's 37.5% non-null rate.", "",
        "Full-small-call proxies at that non-null rate are "
        + "/".join(f"{data['time_planning']['full_call_equivalent_ms_per_task'][k]:.1f} ms/task" for k in (
            "T2_three_extra_small_evals", "T3_four_small_full_calls_not_actual_teacher_forced_cost", "T4_twelve_extra_small_evals"))
        + " for T2/T3/T4 respectively. These proxy costs show the headroom risk; they do not substitute for measured end-to-end lane time.", "",
        "## Frozen engineering comparison", "",
        "Primary resource gate: paired mean end-to-end wall-clock ms/task versus large-only, with small inference, routing, receipts, incremental T1 screens, fallback, retries, and tool work included; one-time model load and bank construction excluded. Same host and loaded models, no concurrent benchmark work, balanced/randomized lane order by task blocks. The route must strictly reduce this primary mean while preserving completion, displacing a large call, and passing the exact semantic gate. Tokens, inference/tool cost, screen work, calls, and memory remain separate reports; no secondary axis can rescue a failed wall-time gate.", "",
        "All candidate-specific T1 screens are incremental unless large-only performs those exact screens. Bank construction separately times the full screen sequence on a known reference-valid patch per task; construction telemetry is not a reusable/cached T1 result.", "",
        "## Positive control and status", "",
        "The already-locked 64-task E012 positive control has `>=8` accepts and `>=80%` observed precision as its coarse recurrence criterion, plus exact intervals and a cohort contrast. Its `c` values remain lineage-only and do not update E013 projections. The 64-task control is 13.5x smaller than D864 and 17.5x smaller than C1120. Its user-built bank is pending.", "",
        "No bank, seed, fixture, screen, observer call, or model/API contact was produced by this work. E013-D/C model contact remains unauthorized. v0.3 and its lock are unchanged.", "",
    ]
    return "\n".join(out)


def build() -> dict[Path, bytes]:
    if digest(PARENT_LOCK) != EXPECTED_PARENT_LOCK_SHA:
        raise RuntimeError("sealed v0.3 lock hash mismatch")
    parent_lock = json.loads(PARENT_LOCK.read_text(encoding="utf-8-sig"))
    expected = parent_lock["upstream_artifacts_sha256"]
    input_checks = {
        PARENT_PROTOCOL: expected["protocol"], PARENT_PROJECTIONS: expected["feasibility_json"],
        PARENT_RECEIPT: expected["feasibility_receipt"], RAW_YIELD: expected["e012_raw_yield_json"],
        POSITIVE_CONTROL: expected["positive_control_design"], LAB_LAW: expected["lab_law"],
        LAB_GRANT: expected["lab_law_grant"],
    }
    for path, wanted in input_checks.items():
        if digest(path) != wanted:
            raise RuntimeError(f"sealed input hash mismatch: {path}")
    raw = json.loads(RAW_YIELD.read_text(encoding="utf-8-sig"))
    if raw["counts"]["nonempty_valid_set"] != {"accepted": 14, "accepted_correct": 6, "accepted_wrong": 8, "correct": 7, "null": 24, "tasks": 40, "wrong": 9}:
        raise RuntimeError("E012 candidate-selection counts differ from sealed source")
    if raw["counts"]["empty_valid_set"]["correct"] != 0 or raw["counts"]["empty_valid_set"]["wrong"] != 2 or raw["counts"]["empty_valid_set"]["null"] != 6:
        raise RuntimeError("E012 empty-valid counts differ from sealed source")
    data = project()
    files: dict[Path, bytes] = {
        PROTOCOL: AMENDMENT.encode("utf-8"),
        PROJECTIONS: (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"),
        RECEIPT: md_receipt(data).encode("utf-8"),
    }
    bound = {
        "amendment": PROTOCOL, "feasibility_projections": PROJECTIONS, "feasibility_receipt": RECEIPT,
        "parent_protocol": PARENT_PROTOCOL, "parent_lock": PARENT_LOCK,
        "parent_projections": PARENT_PROJECTIONS, "parent_receipt": PARENT_RECEIPT,
        "e012_raw_yield": RAW_YIELD, "positive_control_v1_2": POSITIVE_CONTROL,
        "lab_law": LAB_LAW, "lab_law_grant": LAB_GRANT, "generator_script": SCRIPT,
        "construction_handoff_status": HANDOFF_STATUS,
    }
    lock = {
        "schema_version": 1,
        "protocol_id": "E013-TRUST-SIGNAL-DEVELOPMENT-v0.3.1",
        "state": "SEALED_PRECONTACT_DESIGN_ONLY",
        "parent_protocol_id": "E013-TRUST-SIGNAL-DEVELOPMENT-v0.3",
        "parent_protocol_sha256": digest(PARENT_PROTOCOL), "parent_lock_sha256": digest(PARENT_LOCK),
        "model_contact_authorized": False, "model_contact_performed": False,
        "bank_owner": "USER", "bank_generation_performed_by_agent": False,
        "banks": {"D": {"tasks": 864, "status": "USER_BUILD_PENDING"},
                  "C": {"tasks": 1120, "status": "USER_BUILD_PENDING"}},
        "positive_control": {"id": "E012-PC-01-v1.2", "model_contact_authorized": True,
                              "bank_status": "USER_BUILD_PENDING", "run_status": "NOT_RUN",
                              "c_use": "LINEAGE_ONLY; no E013 projection or bank-design update"},
        "locked_decisions": {"n_min": 60, "epsilon": 0.05,
                             "primary_resource_axis": "PAIRED_MEAN_END_TO_END_WALL_MS_PER_TASK_VS_LARGE_ONLY",
                             "t1_screen_cost": "INCREMENTAL_UNLESS_LARGE_ONLY_RUNS_IDENTICAL_SCREENS",
                             "development_fixed_recall_targets": [0.5, 0.7, 0.9],
                             "no_proposal_fallback_conditionals": True},
        "freeze_boundary": [
            "No E013 bank, task, fixture, label, seed, T1 screen, model call, or scoring was produced by this work.",
            "The user owns and builds both E013 banks.",
            "E013-D/C model contact remains unauthorized.",
            "The separate positive control is authorized but awaits the user-built sealed bank.",
            "Parent v0.3 files and lock remain byte-identical.",
        ],
        "artifact_paths": {key: str(path) for key, path in bound.items()},
        "sha256": {key: hashlib.sha256(files[path]).hexdigest() if path in files else digest(path)
                   for key, path in bound.items()},
        "self_hash_note": "This lock does not hash itself or the post-lock verification receipt.",
    }
    files[LOCK] = (json.dumps(lock, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    return files


def self_test() -> dict[str, Any]:
    assert [minimum_support(e)[0] for e in range(5)] == [59, 93, 124, 153, 181]
    assert abs(binom_tail(512, 7 / 48, 60) - 0.9739509669172008) < 1e-10
    assert max_errors_at_expected_support(82) == 0
    assert max_errors_at_expected_support(114) == 1
    assert max_errors_at_expected_support(147) == 2
    d = project()
    c = d["banks"]["C"]["E012_stratum_standardized_sensitivity_only"]
    assert abs(c["expected_correct_raw"] - 184.8) < 1e-9
    assert abs(c["expected_wrong_raw"] - 253.6) < 1e-9
    r70 = d["fixed_recall_FAR"]["E012_pooled_C1120"][1]
    assert abs(r70["finite_gate_FAR_among_wrong_raw_pool"] - 1 / (11 / 48 * 1120)) < 1e-12
    margin = d["time_planning"]["break_even_headroom"][1]["remaining_trust_and_screen_budget_ms_per_task"]
    assert 71.9 < margin < 72.1
    assert abs(d["positive_control"]["E013_D_scale_ratio"] - 13.5) < 1e-9
    receipt = md_receipt(d)
    for phrase in ("stratum rates", "50%", "70%", "90%", "T1 jobs", "paired mean end-to-end wall-clock", "user owns"):
        assert phrase in receipt, phrase
    for phrase in ("Visible screening represents evidence", "NO_PROPOSAL", "181", "13.5 times", "17.5 times"):
        assert phrase in AMENDMENT, phrase
    return {"status": "PASS", "exact_gate_minima": [minimum_support(e)[0] for e in range(5)],
            "pooled_FAR_at_70pct_recall": r70["finite_gate_FAR_among_wrong_raw_pool"],
            "remaining_ms_task_at_70pct_recall": margin, "projection_scenarios": 3,
            "amendment_and_receipt_smoke": "PASS"}


def write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)


def verify() -> dict[str, Any]:
    lock = json.loads(LOCK.read_text(encoding="utf-8-sig"))
    checks: dict[str, bool] = {}
    actual: dict[str, str | None] = {}
    for key, path_text in lock["artifact_paths"].items():
        path = Path(path_text)
        checks[f"exists:{key}"] = path.is_file()
        actual[key] = digest(path) if path.is_file() else None
        if path.is_file():
            checks[f"sha256:{key}"] = actual[key] == lock["sha256"][key]
    checks["identity_and_parent"] = (lock["protocol_id"] == "E013-TRUST-SIGNAL-DEVELOPMENT-v0.3.1"
                                     and lock["parent_protocol_sha256"] == digest(PARENT_PROTOCOL))
    checks["contact_closed"] = lock["model_contact_authorized"] is False and lock["model_contact_performed"] is False
    checks["user_owns_banks"] = lock["bank_owner"] == "USER" and lock["bank_generation_performed_by_agent"] is False
    checks["gate_and_resource"] = lock["locked_decisions"]["n_min"] == 60 and "WALL_MS_PER_TASK" in lock["locked_decisions"]["primary_resource_axis"]
    checks["inputs_unchanged"] = all(actual.get(k) == lock["sha256"][k] for k in ("parent_protocol", "parent_lock", "parent_projections", "parent_receipt", "e012_raw_yield", "positive_control_v1_2", "lab_law", "lab_law_grant"))
    result = {"artifact_id": "E013-PRECONTACT-VERIFICATION-v0.3.1", "state": "PASS" if all(checks.values()) else "FAIL",
              "lock_sha256": digest(LOCK), "checks": checks, "checked_sha256": actual,
              "model_contact_performed": False, "banks_generated_by_agent": False}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--build", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
    elif args.build:
        self_test()
        outputs = build()
        present = [str(path) for path in outputs if path.exists()]
        if present:
            raise FileExistsError("refusing to overwrite existing versioned outputs: " + ", ".join(present))
        # New versioned artifacts are write-once; never overwrite a prior seal.
        for path in (PROTOCOL, PROJECTIONS, RECEIPT, LOCK):
            write_new(path, outputs[path])
        print(json.dumps({"state": "BUILT", "sha256": {str(p): hashlib.sha256(b).hexdigest() for p, b in outputs.items()}}, indent=2))
    else:
        result = verify()
        print(json.dumps(result, indent=2))
        if result["state"] != "PASS":
            raise SystemExit(1)
        if VERIFY_RECEIPT.exists():
            raise FileExistsError(f"refusing to overwrite {VERIFY_RECEIPT}")
        write_new(VERIFY_RECEIPT, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
