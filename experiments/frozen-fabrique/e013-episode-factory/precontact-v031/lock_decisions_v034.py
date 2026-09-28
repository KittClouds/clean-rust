#!/usr/bin/env python3
"""Seal E013 precontact wall-time uncertainty and D-to-C selection rules."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

EXP = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-013-trust-signal")
WORK = Path(r"C:\Users\shuga\.codex\worktrees\e013-episode-factory\clean-rust\experiments\e013-episode-factory\precontact-v031")
SCRIPT = WORK / "lock_decisions_v034.py"
PARENT_LOCK = EXP / "E013-PROTOCOL-LOCK-v0.3.2.json"
PARENT_VERIFY = EXP / "E013-PRECONTACT-VERIFICATION-v0.3.2.json"
SUPPLEMENT_LOCK = EXP / "E013-PRECONTACT-SUPPLEMENT-LOCK-v0.3.3.json"
SUPPLEMENT_VERIFY = EXP / "E013-PRECONTACT-SUPPLEMENT-VERIFICATION-v0.3.3.json"
PROJECTIONS = EXP / "E013-FEASIBILITY-PROJECTIONS-v0.3.2.json"
AMENDMENT = EXP / "E013-PROTOCOL-AMENDMENT-v0.3.4.md"
LOCK = EXP / "E013-PROTOCOL-LOCK-v0.3.4.json"
VERIFY_RECEIPT = EXP / "E013-PRECONTACT-VERIFICATION-v0.3.4.json"
EXPECTED_P32 = "fbac0d86ffd6a593793d2a35d00d2250ae63b52a0abec99864d36456d1af1adb"
EXPECTED_S33 = "a3445cac2493e8b448f4ffeefd189fa7bd40e8b33a4ff99e2af995fdd255146b"
BOOTSTRAP_REPS = 100_000
BOOTSTRAP_SEED = 13034


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def inputs() -> tuple[dict, dict]:
    if sha(PARENT_LOCK) != EXPECTED_P32:
        raise RuntimeError("v0.3.2 parent lock mismatch")
    if sha(SUPPLEMENT_LOCK) != EXPECTED_S33:
        raise RuntimeError("v0.3.3 supplement lock mismatch")
    for lock_path in (PARENT_LOCK, SUPPLEMENT_LOCK):
        lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
        for name, path_text in lock["artifact_paths"].items():
            path = Path(path_text)
            if not path.is_file() or sha(path) != lock["sha256"][name]:
                raise RuntimeError(f"parent artifact changed: {lock_path.name}:{name}")
    parent = json.loads(PARENT_LOCK.read_text(encoding="utf-8-sig"))
    if parent["model_contact_authorized"] or parent["bank_owner"] != "USER":
        raise RuntimeError("parent bank/contact boundary changed")
    for verification_path, expected_lock in ((PARENT_VERIFY, sha(PARENT_LOCK)), (SUPPLEMENT_VERIFY, sha(SUPPLEMENT_LOCK))):
        verification = json.loads(verification_path.read_text(encoding="utf-8-sig"))
        if verification.get("state") != "PASS" or verification.get("lock_sha256") != expected_lock:
            raise RuntimeError(f"parent verification failed: {verification_path.name}")
    return parent, json.loads(PROJECTIONS.read_text(encoding="utf-8-sig"))


def tmax_values(data: dict) -> dict:
    timing = data["time_planning"]
    small = timing["small_full_call_ms"]
    large = timing["large_full_call_ms"]
    cases = {"E012_pooled": (7 / 48, 18 / 48), "nominal": (0.25, 0.50)}
    out = {}
    for name, (correct_rate, nonnull_rate) in cases.items():
        out[name] = {
            "break_even_recall_free_trust": small / (correct_rate * large),
            "T_max_ms_per_nonnull_proposal": {
                str(recall): (correct_rate * recall * large - small) / nonnull_rate
                for recall in (0.7, 0.9, 1.0)
            },
        }
    return {"small_call_ms": small, "large_call_ms": large, "cases": out}


def amendment_text(data: dict) -> str:
    numbers = tmax_values(data)
    pooled = numbers["cases"]["E012_pooled"]
    nominal = numbers["cases"]["nominal"]
    return f"""# R&D-C / Frozen Fabrique — E013 Protocol Amendment v0.3.4

**Effective protocol ID:** `E013-TRUST-SIGNAL-DEVELOPMENT-v0.3.4`  
**Parents:** sealed v0.3.2 protocol package and v0.3.3 feasibility supplement  
**State:** `SEALED_PRECONTACT_DESIGN_ONLY`  
**Contact:** E013-D/C remains unauthorized; E012 positive control remains separately authorized and awaits the user-built bank.  
**Bank owner:** user. This amendment creates no bank, task, fixture, seed, score, or model call.

This version locks the two remaining precontact decisions: uncertainty for the primary wall-time gate and selection of the single development signal passed to confirmation. It also freezes the requested repository and leave-one-repository-out reporting. All prior bank sizes, signal definitions, authority/replay semantics, exact semantic gate, T1 accounting, and contact boundaries remain unchanged unless expressly stated here. Earlier versions remain byte-identical.

## 1. Primary wall-time gate: paired repository-cluster bootstrap

For every confirmation task `i`, define the paired difference:

```text
d_i = routed end-to-end wall-clock milliseconds_i - large-only end-to-end wall-clock milliseconds_i
```

The primary point estimate is the arithmetic mean of `d_i` over all C tasks. To pass the resource gate, the **one-sided 95% upper confidence bound** for this mean must be strictly below zero. A negative point estimate alone does not pass.

Compute that bound with a two-stage paired cluster bootstrap, preserving the repository/family structure and task pairing:

1. Use repositories as the outer resampling unit. In each replicate, sample the four confirmation repositories with replacement, four draws total.
2. For each selected repository draw, sample its eight task-family blocks with replacement, eight draws total. Include all 35 task rows in each selected family block; keep truth-changing pair members together and retain each task's routed/large-only timing pair.
3. Pool the resulting 1,120 paired deltas and calculate their arithmetic mean.
4. Use 100,000 replicates, NumPy `PCG64` with seed `{BOOTSTRAP_SEED}`, and the nearest-rank empirical 95th percentile as the one-sided upper bound.

The scoring implementation, NumPy version, exact bootstrap code, and its fixture tests must be hashed before E013-C contact. Do not change the resampling unit, replicate count, seed, quantile convention, or estimator after seeing confirmation timings. The four-repository cluster count is small; report each repository mean and the leave-one-repository-out estimates so readers can see concentration. These are diagnostics and do not create an alternate resource gate.

All timing inclusion/exclusion, same-host conditions, lane-order balancing, and paired measurement rules from v0.3.1 remain in force. Completion must remain no lower than large-only, at least one large call must be displaced, and integrity checks must remain clean. The wall-time upper bound replaces the prior point-estimate-only “strictly lower mean” criterion; no secondary cost axis may rescue it.

## 2. Frozen E013-D signal selection rule

Apply this rule once, using only E013-D and the already-frozen repository-grouped out-of-fold predictions, outcomes, and measured costs. E013-C remains untouched until the selected route and all code/threshold artifacts are frozen.

### Per-signal operating point

For each available individual T1-T5 signal and the one combination permitted by v0.3, use its cross-fitted scores and whole-tie threshold behavior. Select the **highest-coverage** operating point that simultaneously has at least 60 accepted non-null small proposals and an exact one-sided 95% Clopper-Pearson upper semantic-error bound at or below 5%. If no point satisfies both, mark that signal development-ineligible. T6/NONE remains a separate action-space arm and cannot enter this selection.

For each remaining signal, report its operating recall `s_D` (accepted correct raw proposals divided by all correct raw proposals), its empirical FAR at that operating point (accepted wrong raw proposals divided by all wrong raw proposals), and the fixed-recall FAR diagnostics at 50%, 70%, and 90%. `NO_PROPOSAL` is outside all trust-signal denominators and remains its own outcome.

For fixed-recall FAR diagnostics, preserve the v0.3.1 whole-tie rule: never split equal scores. Use the least-permissive whole-tie threshold that reaches or exceeds each target; report achieved recall and the exact accepted counts. If the target is not attainable exactly, mark that fact and report the achieved whole-tie point. For the selected operating threshold, use the concatenated repository-grouped out-of-fold score values and outcomes. If a signal is refit on all E013-D, apply the frozen numeric threshold unchanged; no full-D or E013-C recalibration is allowed. Any score-scale shift is evaluated only on untouched E013-C.

### Economic eligibility

On E013-D, measure mean full small-call latency `C_small`, mean full large-call latency `C_large`, correct raw proposal fraction `c_D`, and non-null proposal fraction `p_D`. For signal `j`, compute its mean incremental wall-clock trust cost per non-null proposal `T_j` from all measured work attributable to that signal; allocate any fixed per-task signal overhead across the D bank's non-null proposals. Include actual T1 screens and all signal-specific inference/processing; do not substitute full-call proxies for measured teacher-forced or batched costs.

At the signal's development operating recall `s_D`, compute:

```text
T_max(s_D) = (c_D * s_D * C_large - C_small) / p_D
```

The signal is economically eligible only when `T_max(s_D) > 0` and `T_j < T_max(s_D)`. A signal at or above break-even does not proceed to C, even if its semantic risk-coverage curve is better. These D measurements are a selection screen; C must still pass the independently locked paired wall-time confidence-bound gate.

For planning reference only, E012's measured means were `C_small={numbers['small_call_ms']:.3f} ms` and `C_large={numbers['large_call_ms']:.3f} ms`:

| Scenario | Free-trust break-even recall | `T_max` at 70% recall | at 90% | at 100% |
|---|---:|---:|---:|---:|
| E012 pooled (`c=7/48`, `p=18/48`) | {pooled['break_even_recall_free_trust']:.1%} | {pooled['T_max_ms_per_nonnull_proposal']['0.7']:.1f} ms | {pooled['T_max_ms_per_nonnull_proposal']['0.9']:.1f} ms | {pooled['T_max_ms_per_nonnull_proposal']['1.0']:.1f} ms |
| Nominal (`c=25%`, `p=50%`) | {nominal['break_even_recall_free_trust']:.1%} | {nominal['T_max_ms_per_nonnull_proposal']['0.7']:.1f} ms | {nominal['T_max_ms_per_nonnull_proposal']['0.9']:.1f} ms | {nominal['T_max_ms_per_nonnull_proposal']['1.0']:.1f} ms |

The planning rows are not observed E013 performance. The per-signal D decision uses measured E013-D values in the formula above.

### One signal moves to C

Among signals that pass both the development semantic operating-point condition and the economic eligibility condition, select the signal with the **lowest development FAR at its selected operating point**. This deliberately selects specificity after each candidate has independently selected its highest-coverage point under the same risk/support rule. If FAR is exactly tied, choose lower measured `T_j`; if still tied, use this frozen identifier order: `T1`, `T2`, `T3`, `T4`, `T5`, `COMBINATION`.

Freeze the selected signal, cross-fit/refit artifacts, operating threshold, achieved development recall, cost calculation, fallback, and scorer hashes before any C task outcomes are opened. Run only that one selected signal as the primary E013-C route. If none qualify, select no router and do not substitute another signal after looking at C.

## 3. Repository and leave-one-out reporting

For E013-C, report accepted direct-action count `n`, wrong accepted count `x`, and correct accepted count `n-x` separately for each repository, alongside the pooled counts. Also report completion, large calls displaced, and mean paired wall-time difference by repository.

Add a descriptive leave-one-repository-out table: omit each repository in turn and recalculate pooled `n`, `x`, observed risk, exact one-sided 95% Clopper-Pearson upper error bound, completion difference, and mean paired wall-time difference on the remaining tasks. This is a concentration diagnostic only. It does not replace or modify the full-bank admission rule, enable threshold changes, or support a per-repository portability claim. Preserve the already-locked repository harmful-stratum guard and the exact pooled semantic gate unchanged.

## 4. Admission gate and authorization boundary

The full-bank E013-C semantic gate remains `n >= 60` plus one-sided exact 95% Clopper-Pearson upper semantic-error bound `<=5%`, including wrong proposals on empty-valid-set tasks. The pre-existing repository guard, completion condition, at-least-one-displaced-large-call condition, presentation/authority/replay invariants, and duplicate-effect checks remain unchanged. The resource condition is now the one-sided 95% upper bound above being `<0`.

This amendment is protocol-only. E013-D/C model contact is still unauthorized until separate explicit authorization after the user-built banks, adapters, scoring implementation, manifests, and precontact checks are sealed. It authorizes no task construction, screen, model call, scoring, bank resizing, or experiment run.
"""


def make_outputs() -> dict[Path, bytes]:
    parent, data = inputs()
    doc = amendment_text(data).encode("utf-8")
    bindings = {
        "amendment": AMENDMENT,
        "generator": SCRIPT,
        "parent_lock_v032": PARENT_LOCK,
        "parent_verification_v032": PARENT_VERIFY,
        "supplement_lock_v033": SUPPLEMENT_LOCK,
        "supplement_verification_v033": SUPPLEMENT_VERIFY,
        "projections_v032": PROJECTIONS,
    }
    lock = {
        "schema_version": 1,
        "protocol_id": "E013-TRUST-SIGNAL-DEVELOPMENT-v0.3.4",
        "state": "SEALED_PRECONTACT_DESIGN_ONLY",
        "effective_lineage": ["sealed v0.3", "v0.3.1 bank/resource amendment", "v0.3.2 FAR correction", "v0.3.3 feasibility supplement", "v0.3.4 uncertainty and selection locks"],
        "parent_v032_lock_sha256": sha(PARENT_LOCK),
        "supplement_v033_lock_sha256": sha(SUPPLEMENT_LOCK),
        "bank_owner": "USER",
        "banks_generated_by_agent": False,
        "model_contact_authorized": False,
        "model_contact_performed": False,
        "positive_control": {"id": "E012-PC-01-v1.2", "contact_authorized": True, "bank_status": "USER_BUILD_PENDING", "run_status": "NOT_RUN"},
        "locked_wall_time_rule": {"bound": "one-sided 95% upper bound < 0 on mean paired routed-minus-large-only ms/task", "method": "two-stage paired repository/family-block bootstrap", "replicates": BOOTSTRAP_REPS, "numpy_bit_generator": "PCG64", "seed": BOOTSTRAP_SEED, "quantile": "nearest rank 95th percentile"},
        "locked_signal_selection": "highest-coverage dev OOF point meeting n>=60 and exact one-sided CP95 upper risk<=5%; filter by measured T<Tmax; select lowest FAR at its operating point; exact ties by cost then T1,T2,T3,T4,T5,COMBINATION",
        "artifact_paths": {key: str(path) for key, path in bindings.items()},
        "sha256": {key: hashlib.sha256(doc).hexdigest() if key == "amendment" else sha(path) for key, path in bindings.items()},
        "self_hash_note": "Lock excludes itself and the post-lock verification receipt.",
    }
    lock_bytes = (json.dumps(lock, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    return {AMENDMENT: doc, LOCK: lock_bytes}


def self_test() -> dict:
    _, data = inputs()
    nums = tmax_values(data)
    e = nums["cases"]["E012_pooled"]
    n = nums["cases"]["nominal"]
    assert abs(e["break_even_recall_free_trust"] - 0.5396197049785598) < 1e-12
    assert abs(e["T_max_ms_per_nonnull_proposal"]["0.7"] - 191.88679050925938) < 1e-9
    assert abs(e["T_max_ms_per_nonnull_proposal"]["0.9"] - 431.17652430555586) < 1e-9
    assert abs(e["T_max_ms_per_nonnull_proposal"]["1.0"] - 550.8213912037039) < 1e-9
    assert abs(n["T_max_ms_per_nonnull_proposal"]["0.7"] - 592.58334375) < 1e-9
    doc = amendment_text(data)
    for required in ("one-sided 95% upper confidence bound", "PCG64", "lowest development FAR", "leave-one-repository-out", "whole-tie rule", "threshold unchanged", "E013-D/C model contact is still unauthorized"):
        assert required.casefold() in doc.casefold()
    return {"state": "PASS", "E012_pooled_Tmax_ms": e["T_max_ms_per_nonnull_proposal"], "nominal_Tmax_ms": n["T_max_ms_per_nonnull_proposal"], "break_even_recall": {k: v["break_even_recall_free_trust"] for k, v in nums["cases"].items()}}


def verify() -> dict:
    lock = json.loads(LOCK.read_text(encoding="utf-8-sig"))
    actual, checks = {}, {}
    for name, path_text in lock["artifact_paths"].items():
        path = Path(path_text)
        checks[f"exists:{name}"] = path.is_file()
        actual[name] = sha(path) if path.is_file() else None
        if path.is_file():
            checks[f"sha256:{name}"] = actual[name] == lock["sha256"][name]
    _, data = inputs()
    doc = AMENDMENT.read_text(encoding="utf-8-sig")
    checks["wall_time_bound_present"] = "one-sided 95% upper confidence bound" in doc and "nearest-rank empirical 95th percentile" in doc
    checks["selection_rule_present"] = "lowest development FAR" in doc and "T_max(s_D)" in doc
    checks["cluster_reporting_present"] = "leave-one-repository-out" in doc
    checks["Tmax_matches_locked_inputs"] = abs(tmax_values(data)["cases"]["E012_pooled"]["T_max_ms_per_nonnull_proposal"]["0.7"] - 191.88679050925938) < 1e-9
    checks["contact_and_ownership_boundary"] = not lock["model_contact_authorized"] and lock["bank_owner"] == "USER"
    result = {"artifact_id": "E013-PRECONTACT-VERIFICATION-v0.3.4", "state": "PASS" if all(checks.values()) else "FAIL", "lock_sha256": sha(LOCK), "checks": checks, "checked_sha256": actual, "banks_generated_by_agent": False, "model_contact_performed": False}
    return result


def write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)


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
        files = make_outputs()
        existing = [str(path) for path in files if path.exists()]
        if existing:
            raise FileExistsError("refusing to overwrite versioned artifacts: " + ", ".join(existing))
        for path, payload in files.items():
            write_new(path, payload)
        print(json.dumps({"state": "BUILT", "sha256": {str(path): hashlib.sha256(payload).hexdigest() for path, payload in files.items()}}, indent=2))
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
