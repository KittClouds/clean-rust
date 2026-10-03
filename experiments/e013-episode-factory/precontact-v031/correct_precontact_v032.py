#!/usr/bin/env python3
"""Versioned correction to E013 v0.3.1 asymptotic FAR algebra."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXP = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-013-trust-signal")
WORK = Path(r"C:\Users\shuga\.codex\worktrees\e013-episode-factory\clean-rust\experiments\e013-episode-factory\precontact-v031")
SCRIPT = WORK / "correct_precontact_v032.py"
V31_LOCK = EXP / "E013-PROTOCOL-LOCK-v0.3.1.json"
V31_RECEIPT = EXP / "E013-FEASIBILITY-RECEIPT-v0.3.1.md"
V31_PROJECTIONS = EXP / "E013-FEASIBILITY-PROJECTIONS-v0.3.1.json"
V31_VERIFY = EXP / "E013-PRECONTACT-VERIFICATION-v0.3.1.json"
CORRECTION = EXP / "E013-PRECONTACT-CORRECTION-v0.3.2.md"
PROJECTIONS = EXP / "E013-FEASIBILITY-PROJECTIONS-v0.3.2.json"
RECEIPT = EXP / "E013-FEASIBILITY-RECEIPT-v0.3.2.md"
LOCK = EXP / "E013-PROTOCOL-LOCK-v0.3.2.json"
VERIFY_RECEIPT = EXP / "E013-PRECONTACT-VERIFICATION-v0.3.2.json"
EXPECTED_V31_LOCK_SHA = "2dde2c7c2fd3baa6c7bc08debfd01f5118f9ac4348318a9f9be633a0f7357d17"
EPSILON = 0.05


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def corrected_projection() -> dict:
    data = json.loads(V31_PROJECTIONS.read_text(encoding="utf-8-sig"))
    for scenario_rows in data["fixed_recall_FAR"].values():
        for row in scenario_rows:
            correct = row["expected_correct_accepts"]
            wrong_pool = row["expected_wrong_raw_pool"]
            row["asymptotic_FAR_ceiling_for_5pct_empirical_risk"] = (EPSILON / (1.0 - EPSILON)) * correct / wrong_pool
    data["artifact_id"] = "E013-FEASIBILITY-PROJECTIONS-v0.3.2"
    data["formula_correction"] = {
        "version": "v0.3.2",
        "correct_formula": "FAR <= epsilon/(1-epsilon) * expected_correct_accepts / expected_wrong_raw_proposals",
        "supersedes": "The inverse epsilon-odds multiplier in the v0.3.1 asymptotic FAR fields.",
        "finite_exact_gate_far_unchanged": True,
        "actual_admission_uses_realized_counts": True,
    }
    return data


def correction_note() -> str:
    return """# E013 Precontact Arithmetic Correction v0.3.2

**Effective protocol lineage:** v0.3 + v0.3.1 amendment + this arithmetic correction  
**Parent lock:** `E013-PROTOCOL-LOCK-v0.3.1.json`, SHA-256 `2dde2c7c2fd3baa6c7bc08debfd01f5118f9ac4348318a9f9be633a0f7357d17`  
**State:** `SEALED_PRECONTACT_DESIGN_ONLY`  
**Scope:** Correct the asymptotic 5% risk FAR calculation only. No protocol gate, bank size, signal, task, model, or authority change.

## Defect and repair

The v0.3.1 feasibility calculation inverted the error-odds factor in its asymptotic FAR ceiling. For `A` expected correct accepted proposals and `W` wrong raw proposals, if fraction `f` of wrong proposals is accepted, then:

```text
f*W / (A + f*W) <= epsilon
f <= (epsilon / (1-epsilon)) * (A/W)
```

The erroneous v0.3.1 expression used `(1-epsilon)/epsilon`. The corrected expression and values are in `E013-FEASIBILITY-PROJECTIONS-v0.3.2.json` and `E013-FEASIBILITY-RECEIPT-v0.3.2.md`.

For C=1,120 at 50/70/90% correct-proposal recall, the corrected asymptotic FAR ceilings are:

| Scenario | 50% | 70% | 90% |
|---|---:|---:|---:|
| E012 pooled | 1.67% | 2.34% | 3.01% |
| Nominal 25/25/50 | 2.63% | 3.68% | 4.74% |
| E012 stratum sensitivity | 1.92% | 2.69% | 3.45% |

The finite exact-gate illustration (0/1/2 max wrong accepts at pooled expected support for 50/70/90% recall, or FAR 0.00/0.39/0.78%) was computed independently and is unchanged. The actual admission rule continues to use realized integer outcomes, `n_min=60`, and the exact one-sided 95% Clopper–Pearson bound of at most 5%.

## Preservation boundary

Keep v0.3.1 unchanged as the preserved first precontact package. This v0.3.2 correction supersedes only its asymptotic FAR field and corresponding displayed comparison. All task-bank, model-contact, and ownership boundaries remain unchanged: the user builds both banks; E013-D/C model contact is unauthorized; the separate positive control awaits its user-built bank. No bank, task, fixture, seed, screen, model call, or score was created here.
"""


def receipt_text(data: dict) -> str:
    prior = V31_RECEIPT.read_text(encoding="utf-8-sig")
    old = "604.55%/846.36%/1088.18%"
    new = "1.67%/2.34%/3.01%"
    if prior.count(old) != 1:
        raise RuntimeError("unexpected v0.3.1 receipt wording; refusing a broad replacement")
    text = prior.replace("Feasibility Receipt v0.3.1", "Feasibility Receipt v0.3.2", 1)
    text = text.replace(old, new, 1)
    text += "\n## Versioned arithmetic correction\n\n"
    text += "The asymptotic FAR formula is corrected under `E013-PRECONTACT-CORRECTION-v0.3.2.md`. The v0.3.1 finite exact-gate FAR table is unchanged. The corrected asymptotic ceilings at 50/70/90% recall are E012 pooled 1.67%/2.34%/3.01%, nominal 2.63%/3.68%/4.74%, and E012 stratum sensitivity 1.92%/2.69%/3.45%. The underlying error is an inverted `epsilon/(1-epsilon)` factor; no bank or model boundary changed.\n"
    return text


def self_test() -> dict:
    d = corrected_projection()
    pooled = d["fixed_recall_FAR"]["E012_pooled_C1120"]
    nominal = d["fixed_recall_FAR"]["nominal_C1120"]
    strat = d["fixed_recall_FAR"]["E012_stratum_sensitivity_C1120"]
    assert abs(pooled[1]["asymptotic_FAR_ceiling_for_5pct_empirical_risk"] - 0.023444976076555) < 1e-12
    assert abs(nominal[1]["asymptotic_FAR_ceiling_for_5pct_empirical_risk"] - 0.036842105263158) < 1e-12
    assert abs(strat[1]["asymptotic_FAR_ceiling_for_5pct_empirical_risk"] - 0.026847086169683) < 1e-12
    assert pooled[1]["finite_gate_FAR_among_wrong_raw_pool"] == 1 / (11 / 48 * 1120)
    assert "f <= (epsilon / (1-epsilon)) * (A/W)" in correction_note()
    return {"status": "PASS", "corrected_70pct_FAR": {"pooled": pooled[1]["asymptotic_FAR_ceiling_for_5pct_empirical_risk"],
            "nominal": nominal[1]["asymptotic_FAR_ceiling_for_5pct_empirical_risk"],
            "stratum": strat[1]["asymptotic_FAR_ceiling_for_5pct_empirical_risk"]},
            "finite_exact_gate_unchanged": True}


def make_outputs() -> dict[Path, bytes]:
    if sha(V31_LOCK) != EXPECTED_V31_LOCK_SHA:
        raise RuntimeError("v0.3.1 parent lock hash mismatch")
    parent = json.loads(V31_LOCK.read_text(encoding="utf-8-sig"))
    for key, path_text in parent["artifact_paths"].items():
        path = Path(path_text)
        if not path.is_file() or sha(path) != parent["sha256"][key]:
            raise RuntimeError(f"v0.3.1 parent artifact changed: {key}")
    data = corrected_projection()
    docs = {
        CORRECTION: correction_note().encode("utf-8"),
        PROJECTIONS: (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"),
        RECEIPT: receipt_text(data).encode("utf-8"),
    }
    bindings = {
        "correction_note": CORRECTION, "corrected_projections": PROJECTIONS,
        "corrected_receipt": RECEIPT, "correction_script": SCRIPT,
        "parent_lock_v031": V31_LOCK, "parent_receipt_v031": V31_RECEIPT,
        "parent_projections_v031": V31_PROJECTIONS, "parent_verification_v031": V31_VERIFY,
    }
    lock = {
        "schema_version": 1, "protocol_id": "E013-TRUST-SIGNAL-DEVELOPMENT-v0.3.2",
        "state": "SEALED_PRECONTACT_DESIGN_ONLY",
        "effective_lineage": ["sealed v0.3 protocol", "v0.3.1 pre-bank amendment", "v0.3.2 asymptotic FAR arithmetic correction"],
        "parent_lock_v031_sha256": sha(V31_LOCK), "model_contact_authorized": False,
        "model_contact_performed": False, "bank_owner": "USER", "bank_generation_performed_by_agent": False,
        "positive_control": {"id": "E012-PC-01-v1.2", "contact_authorized": True,
                             "bank_status": "USER_BUILD_PENDING", "run_status": "NOT_RUN"},
        "correction_scope": "asymptotic FAR formula only; finite exact-gate FAR and all gates unchanged",
        "artifact_paths": {k: str(v) for k, v in bindings.items()},
        "sha256": {k: hashlib.sha256(docs[v]).hexdigest() if v in docs else sha(v) for k, v in bindings.items()},
        "self_hash_note": "Lock does not hash itself or post-lock verification receipt.",
    }
    docs[LOCK] = (json.dumps(lock, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    return docs


def verify() -> dict:
    lock = json.loads(LOCK.read_text(encoding="utf-8-sig"))
    checks, actual = {}, {}
    for key, path_text in lock["artifact_paths"].items():
        path = Path(path_text)
        checks[f"exists:{key}"] = path.is_file()
        actual[key] = sha(path) if path.is_file() else None
        if path.is_file():
            checks[f"sha256:{key}"] = actual[key] == lock["sha256"][key]
    data = json.loads(PROJECTIONS.read_text(encoding="utf-8-sig"))
    p70 = data["fixed_recall_FAR"]["E012_pooled_C1120"][1]
    checks["corrected_formula"] = abs(p70["asymptotic_FAR_ceiling_for_5pct_empirical_risk"] - 0.023444976076555) < 1e-12
    checks["finite_gate_preserved"] = abs(p70["finite_gate_FAR_among_wrong_raw_pool"] - 1 / (11 / 48 * 1120)) < 1e-12
    checks["scope_and_boundary"] = lock["model_contact_authorized"] is False and lock["bank_owner"] == "USER"
    result = {"artifact_id": "E013-PRECONTACT-VERIFICATION-v0.3.2", "state": "PASS" if all(checks.values()) else "FAIL",
              "lock_sha256": sha(LOCK), "checks": checks, "checked_sha256": actual,
              "model_contact_performed": False, "banks_generated_by_agent": False}
    return result


def write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(content)


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
        outputs = make_outputs()
        existing = [str(p) for p in outputs if p.exists()]
        if existing:
            raise FileExistsError("refusing to overwrite versioned artifacts: " + ", ".join(existing))
        for p in (CORRECTION, PROJECTIONS, RECEIPT, LOCK):
            write_new(p, outputs[p])
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
