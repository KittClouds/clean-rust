#!/usr/bin/env python3
"""Readable, hash-bound presentation of precontact support probabilities."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXP = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-013-trust-signal")
WORK = Path(r"C:\Users\shuga\.codex\worktrees\e013-episode-factory\clean-rust\experiments\e013-episode-factory\precontact-v031")
SCRIPT = WORK / "supplement_precontact_v033.py"
PARENT_LOCK = EXP / "E013-PROTOCOL-LOCK-v0.3.2.json"
PROJECTIONS = EXP / "E013-FEASIBILITY-PROJECTIONS-v0.3.2.json"
PARENT_RECEIPT = EXP / "E013-FEASIBILITY-RECEIPT-v0.3.2.md"
CORRECTION = EXP / "E013-PRECONTACT-CORRECTION-v0.3.2.md"
SUPPLEMENT = EXP / "E013-PRECONTACT-FEASIBILITY-SUPPLEMENT-v0.3.3.md"
LOCK = EXP / "E013-PRECONTACT-SUPPLEMENT-LOCK-v0.3.3.json"
VERIFY_RECEIPT = EXP / "E013-PRECONTACT-SUPPLEMENT-VERIFICATION-v0.3.3.json"
EXPECTED_PARENT_LOCK_SHA = "fbac0d86ffd6a593793d2a35d00d2250ae63b52a0abec99864d36456d1af1adb"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def percent(value: float, digits: int = 2) -> str:
    if value >= 0.99999999:
        return ">99.999999%"
    return f"{100 * value:.{digits}f}%"


def read_inputs() -> tuple[dict, dict]:
    if sha(PARENT_LOCK) != EXPECTED_PARENT_LOCK_SHA:
        raise RuntimeError("v0.3.2 parent lock hash mismatch")
    lock = json.loads(PARENT_LOCK.read_text(encoding="utf-8-sig"))
    for key, path_text in lock["artifact_paths"].items():
        path = Path(path_text)
        if not path.is_file() or sha(path) != lock["sha256"][key]:
            raise RuntimeError(f"v0.3.2 parent artifact changed: {key}")
    return lock, json.loads(PROJECTIONS.read_text(encoding="utf-8-sig"))


def supplement_text(data: dict) -> str:
    bank = data["banks"]
    t5_rows = []
    for code in ("D", "C"):
        for scenario in ("pooled_E012_conservative", "nominal_assumption", "E012_stratum_standardized_sensitivity_only"):
            row = bank[code][scenario]
            t5_rows.append(
                f"| {code} / {row['tasks']} | {scenario} | {row['expected_correct_raw']:.1f} | "
                f"{row['expected_wrong_raw']:.1f} | {percent(row['prob_T5_at_least_100_correct_and_wrong'], 6)} |"
            )

    support_rows = []
    for scenario in ("E012_pooled_conservative", "nominal"):
        for row in data["confirmation_support"]["C1120"]:
            if row["scenario"] == scenario and row["recall"] in (0.5, 0.7, 0.9):
                support_rows.append(
                    f"| {scenario} | {row['recall']:.0%} | {row['expected_correct_accepts']:.1f} | "
                    f"{percent(row['P_at_least_60_combined_zero_error_gate'], 4)} | "
                    f"{percent(row['P_at_least_93_one_error_support'], 4)} |"
                )

    old = data["confirmation_support"]["old_512_comparison"]
    pooled_70 = next(
        r for r in data["confirmation_support"]["C1120"]
        if r["scenario"] == "E012_pooled_conservative" and r["recall"] == 0.7
    )
    return f"""# E013 Precontact Feasibility Supplement v0.3.3

**Parent design:** sealed E013 v0.3.2, lock SHA-256 `{EXPECTED_PARENT_LOCK_SHA}`  
**State:** `SEALED_PRECONTACT_DESIGN_ONLY`  
**Scope:** expose the already-calculated T5 and confirmation-support probabilities in readable receipt form. No input values, gates, bank design, or model-contact state change.

## T5 development-support feasibility

T5 requires at least 100 correct and 100 wrong non-null small proposals in E013-D (864 tasks). The probabilities below use the locked iid multinomial planning scenarios; they are sizing illustrations, not guarantees. The same projected counts are preserved for E013-C for lineage, though T5 is a development-only probe.

| Bank | Scenario | Expected correct raw | Expected wrong raw | P(both counts >=100) |
|---|---|---:|---:|---:|
{chr(10).join(t5_rows)}

Under pooled E012 rates, E013-D expects 126 correct and 198 wrong proposals; the joint threshold probability is {percent(bank['D']['pooled_E012_conservative']['prob_T5_at_least_100_correct_and_wrong'], 4)}. Thus the 864-task resize addresses the prior correct-proposal support shortfall, while observed sealed-bank support still determines T5 eligibility. If either observed count is below 100, T5 remains unavailable; do not enlarge the bank after model outputs.

## Confirmation support ceiling

These are probabilities of having enough **correct proposals retained by an oracle trust signal** under the stated recall; they are not probabilities of passing the semantic-risk gate. False accepts and the exact Clopper-Pearson bound remain decisive.

| Scenario | Correct-proposal recall | Expected oracle correct accepts | P(n >= 60) | P(n >= 93) |
|---|---:|---:|---:|---:|
{chr(10).join(support_rows)}

For the retired 512-task sizing case, E012's pooled rate gives an oracle ceiling of `512 * 7/48 = 74.67` expected correct proposals: `P(n >= 59)={percent(old['P_at_least_59_CP_only'], 2)}` at 100% recall. At 70% recall, expected oracle support is 52.27, `P(n >= 60)={percent(old['P_at_least_60_at_70pct_recall'], 2)}`, and `P(n >= 93)=0.0000037%`. The current C=1,120 pooled case at 70% recall has {pooled_70['expected_correct_accepts']:.1f} expected oracle accepts and {percent(pooled_70['P_at_least_93_one_error_support'], 4)} support probability for 93. These comparisons explain the resize; neither predicts trust-signal specificity.

## Interpretation and boundaries

- `NO_PROPOSAL` is a separate outcome. An oracle trust signal cannot create a missing proposal.
- T5's sample-count event is only a precondition for attempting the probe, not a promotion result.
- The probabilities assume independent task-level outcomes and ignore repository/family clustering.
- The v0.3.2 correction to asymptotic FAR is unchanged; finite exact-gate illustrations and admission rules are unchanged.
- E013-D/C model contact remains unauthorized. The user builds both banks. No bank, task, fixture, screen, observer call, or score was created.
"""


def outputs() -> dict[Path, bytes]:
    parent, data = read_inputs()
    text = supplement_text(data).encode("utf-8")
    bindings = {
        "supplement": SUPPLEMENT,
        "generator": SCRIPT,
        "parent_lock_v032": PARENT_LOCK,
        "parent_projections_v032": PROJECTIONS,
        "parent_receipt_v032": PARENT_RECEIPT,
        "parent_correction_v032": CORRECTION,
    }
    lock = {
        "schema_version": 1,
        "artifact_id": "E013-PRECONTACT-SUPPLEMENT-v0.3.3",
        "state": "SEALED_PRECONTACT_DESIGN_ONLY",
        "scope": "readable projection of already-locked T5 and confirmation-support probabilities",
        "parent_lock_v032_sha256": sha(PARENT_LOCK),
        "bank_owner": "USER",
        "banks_generated_by_agent": False,
        "model_contact_authorized": False,
        "model_contact_performed": False,
        "artifact_paths": {k: str(v) for k, v in bindings.items()},
        "sha256": {
            k: hashlib.sha256(text).hexdigest() if k == "supplement" else sha(v)
            for k, v in bindings.items()
        },
        "self_hash_note": "Lock excludes itself and the post-lock verification receipt.",
    }
    return {
        SUPPLEMENT: text,
        LOCK: (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }


def self_test() -> dict:
    _, data = read_inputs()
    body = supplement_text(data)
    assert "99.5662%" in body
    assert ">99.999999%" in body
    assert "P(n >= 93)=" in body
    assert "NO_PROPOSAL" in body
    return {"state": "PASS", "t5_D_pooled": data["banks"]["D"]["pooled_E012_conservative"]["prob_T5_at_least_100_correct_and_wrong"],
            "gate_C_pooled_70pct_P_ge_93": next(r["P_at_least_93_one_error_support"] for r in data["confirmation_support"]["C1120"] if r["scenario"] == "E012_pooled_conservative" and r["recall"] == 0.7)}


def verify() -> dict:
    lock = json.loads(LOCK.read_text(encoding="utf-8-sig"))
    checks, actual = {}, {}
    for key, path_text in lock["artifact_paths"].items():
        path = Path(path_text)
        checks[f"exists:{key}"] = path.is_file()
        actual[key] = sha(path) if path.is_file() else None
        if path.is_file():
            checks[f"sha256:{key}"] = actual[key] == lock["sha256"][key]
    _, data = read_inputs()
    text = SUPPLEMENT.read_text(encoding="utf-8-sig")
    checks["t5_probability_rendered"] = "99.5662%" in text and ">99.999999%" in text
    checks["one_error_support_rendered"] = "98.6363%" in text
    checks["ownership_contact_boundary"] = lock["bank_owner"] == "USER" and not lock["model_contact_authorized"]
    checks["projection_source_bound"] = sha(PROJECTIONS) == lock["sha256"]["parent_projections_v032"]
    result = {"artifact_id": "E013-PRECONTACT-SUPPLEMENT-VERIFICATION-v0.3.3", "state": "PASS" if all(checks.values()) else "FAIL",
              "lock_sha256": sha(LOCK), "checks": checks, "checked_sha256": actual,
              "banks_generated_by_agent": False, "model_contact_performed": False}
    return result


def write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(content)


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
    elif args.build:
        self_test()
        files = outputs()
        existing = [str(p) for p in files if p.exists()]
        if existing:
            raise FileExistsError("refusing to overwrite versioned artifacts: " + ", ".join(existing))
        for path, content in files.items():
            write_new(path, content)
        print(json.dumps({"state": "BUILT", "sha256": {str(p): hashlib.sha256(b).hexdigest() for p, b in files.items()}}, indent=2))
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
