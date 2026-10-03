#!/usr/bin/env python3
"""Seal a positive-control bank construction specification; creates no bank."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PC_DIR = Path(r"C:\rd-c\selective-cognition-action-region-program\e012-readonly-anatomy-addendum")
E013_DIR = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-013-trust-signal")
WORK = Path(r"C:\Users\shuga\.codex\worktrees\e013-episode-factory\clean-rust\experiments\e013-episode-factory\precontact-v031")
SCRIPT = WORK / "seal_pc_buildspec_v13.py"
PARENT_PC = PC_DIR / "E012-POSITIVE-CONTROL-DESIGN-v1.2.md"
PARENT_E013_AMENDMENT = E013_DIR / "E013-PROTOCOL-AMENDMENT-v0.3.4.md"
PARENT_E013_LOCK = E013_DIR / "E013-PROTOCOL-LOCK-v0.3.4.json"
PARENT_E013_VERIFY = E013_DIR / "E013-PRECONTACT-VERIFICATION-v0.3.4.json"
SPEC = PC_DIR / "E012-POSITIVE-CONTROL-BANK-CONSTRUCTION-SPEC-v1.3.md"
LOCK = PC_DIR / "E012-POSITIVE-CONTROL-BANK-CONSTRUCTION-LOCK-v1.3.json"
VERIFY_RECEIPT = PC_DIR / "E012-POSITIVE-CONTROL-BANK-CONSTRUCTION-VERIFICATION-v1.3.json"
EXPECTED_V12 = "BE69EE36702E2C94CF0F5187AA0FE5F76D512B59D3DF645CB407CE4AB2A1C0AD"
EXPECTED_E013_LOCK = "85C0B4E4C13FAE800ECB42F5742D1A53E89F7388CE3C2FD42789C8759E613F38"
SEED = 13064
SCREEN_TIMEOUT_SECONDS = 120


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_parents() -> dict:
    if sha(PARENT_PC).upper() != EXPECTED_V12:
        raise RuntimeError("positive-control v1.2 parent changed")
    if sha(PARENT_E013_LOCK).upper() != EXPECTED_E013_LOCK:
        raise RuntimeError("E013 v0.3.4 lock changed")
    e013_lock = json.loads(PARENT_E013_LOCK.read_text(encoding="utf-8-sig"))
    e013_verify = json.loads(PARENT_E013_VERIFY.read_text(encoding="utf-8-sig"))
    if e013_verify.get("state") != "PASS" or e013_verify.get("lock_sha256", "").upper() != EXPECTED_E013_LOCK:
        raise RuntimeError("E013 v0.3.4 verification receipt is not passing")
    if e013_lock.get("model_contact_authorized") is not False or e013_lock.get("bank_owner") != "USER":
        raise RuntimeError("E013 bank/contact boundary changed")
    return e013_lock


def spec_text() -> str:
    return f"""# E012 Positive-Control Bank Construction Specification v1.3

**Parent run design:** `E012-POSITIVE-CONTROL-DESIGN-v1.2.md`  
**State:** `CONSTRUCTION_SPEC_SEALED; BANK_NOT_BUILT`  
**Bank owner:** user  
**Purpose:** make the authorized 64-task positive-control bank the first execution of the reusable E013-D/C construction pipeline. This document specifies construction; it does not create tasks or authorize additional model contact.

This is an additive construction amendment to v1.2. Preserve v1.2's two fresh Rust repositories, two cohorts, four families per repository, four tasks per repository-family-cohort cell, frozen v5 lanes, completion checks, and coarse recurrence criterion (`n_accept >= 8` and observed precision `>=80%` per cohort). The separate E013-D/C contact status is unchanged and remains unauthorized.

## 1. Fixed 64-task layout and empty-valid-set decision

Retain the v1.2 layout:

```text
2 fresh repositories × 2 cohorts × 4 task families × 4 tasks = 64
```

- Positive-control cohort: 32 clear, short local-commit tasks, explicit requested behavior, and at least one useful offered candidate. It contains zero empty-valid-set tasks.
- Difficulty-matched cohort: 32 tasks matched to E012's blinded construction-profile rubric. Include five empty-valid-set tasks and 27 candidate-selection tasks.

E012 had 8 empty-valid-set tasks among 48 (`8/48 = 16.67%`). The nearest integer quota at 32 tasks is `5/32 = 15.625%` (absolute rate difference 1.04 percentage points; six would be 18.75%, difference 2.08 points). The five empty tasks are part of, not additional to, the 32-task difficulty-matched cohort. They count in task completion and false-accept reporting. Any candidate proposal on one is wrong; an abstention is not a task error by itself.

Assign one empty task to each of five distinct repository-family cells, with two cells in one repository and three in the other. Initialize NumPy `SeedSequence({SEED})` and call `.spawn(5)` exactly once. Name child streams in order: `empty_cells`, `empty_task_slots`, `ordinal_assignment`, `candidate_slot_order`, `opaque_ids`. The first stream selects which repository receives two versus three and selects distinct family indices without replacement; the second selects one of the four task slots in each chosen cell. The third assigns valid-anchor ordinals and the `(2,1,1,1)` omitted-ordinal multiset; the fourth orders distractor roles around the preassigned anchor (or all four roles for an empty task); the fifth generates opaque task/candidate IDs independently of role and ordinal. Record NumPy version and each generated assignment. This spreads the empty stratum across both repositories and prevents any cell from being identified by quota concentration. The independent rater and the E012-profile scoring packet must not receive the quota rationale, task-level E012 outcomes, logs, anatomy, or task-level empty labels.

## 2. Stage 0 — blinded E012 rubric target

Before selecting new repositories or writing tasks, appoint the independent rubric rater and score all 48 E012 task materials. The rater may see only the task request, offered candidate patches in their recorded order, and the relevant repository context. Do not provide E012 outcomes, execution logs, label/valid-set files, prior anatomy reports, proposal-yield reports, or this bank-spec document. Do not tell the rater which tasks were empty-valid.

Score these six dimensions as ordinal values 0–3 using the same anchor sheet for E012 and the new bank:

| Dimension | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| Operative constraints | one clear constraint | two constraints | three constraints | four or more interacting constraints |
| Wording ambiguity | one clear interpretation | minor ambiguity resolved by normal context | multiple plausible readings | materially underspecified or conflicting request |
| Candidate similarity | one candidate clearly distinct | some meaningful differences | several close alternatives | near-identical alternatives require fine discrimination |
| Evidence conflict | task, code, and exposed checks align | one weakly inconsistent cue | multiple cues disagree | material conflict changes the plausible action |
| Reasoning depth | one local edit | local change with a short consequence chain | cross-file or multi-step behavior | nonlocal lifecycle/API interaction or several dependent consequences |
| Distractor plausibility | malformed/straw distractor | obvious miss | plausible partial/wrong-place/over-broad fix | all candidates plausible; visible success can hide a hidden-edge failure |

After scoring, freeze and hash the E012 rater sheet and the **aggregate marginal bin counts only** for each dimension. The E012 task-level scores remain in a restricted profile vault; task authors receive only the aggregate targets. No outcome-derived data may be used. The coordinator may use the previously sealed aggregate empty-set rate solely for the five-task quota above; the rater never sees it.

## 3. Stage 1 — repository selection and snapshot

Write and freeze this selection checklist before naming candidate repositories. Select two repositories not used in E009–E012 that satisfy every item:

1. Rust project with a pinned `rust-toolchain.toml` or equivalent exact toolchain identity.
2. Dependencies are vendored and clean builds/tests pass offline with `cargo --offline --locked`.
3. License is compatible with this internal research and any planned use.
4. Existing tests are deterministic on two clean runs and finish within the fixed 120-second per-stage timeout.
5. Source snapshot and `Cargo.lock` are available at an immutable commit; record repository origin, commit, snapshot SHA-256, lockfile SHA-256, toolchain SHA-256/version, OS, and license evidence.

Apply the checklist in a predeclared candidate order. Record every candidate repository considered and every rejection reason before selecting the two. Do not replace a repository because tasks or model outcomes are unfavorable; repository replacement is allowed only before model contact and under the same frozen criteria, with a versioned construction receipt.

## 4. Stage 2 — task families and visible/hidden principle

Before authoring tasks, freeze the same four task-family definitions for both repositories. Use families that exercise distinct local coding work, such as: boundary/off-by-one behavior; error handling; parsing/configuration behavior; and API behavior. Record each family's scope and exclusions. Do not change a family after observing any observer output.

Freeze this evidence partition before writing tasks:

> Visible checks are what an ordinary contributor would realistically see before protected evaluation: the existing repository suite plus any example explicitly named in the task request. Hidden checks encode the full requested behavior, including edge cases not exposed by those visible checks. Neither visible nor hidden checks may be selected or strengthened in response to observer outputs.

Keep visible and hidden check sources in separate roots and manifests, with distinct hashes and permissions. Hash disjointness is required but is not a substitute for the construction principle above. A visible suite that passes a wrong patch is an intended signal outcome if the hidden contract rejects that patch.

## 5. Stage 3 — task authoring and difficulty matching

Author four tasks in every repository × cohort × family cell. Each task has a natural-language request, a reference patch, a four-candidate slot, visible checks, hidden checks, and the sealed executable completion contract. The reference patch must pass visible and hidden checks. For empty-valid tasks, the reference patch is not one of the four offered candidates.

Authors record the six rubric scores and rationale at authoring time. The independent rater then scores each task from an anonymized packet containing task text, repository context, and offered candidate patches, but not cohort label, author notes, reference patch, hidden checks, validity labels, or observer outputs. Use the same rater and anchor sheet as Stage 0 where feasible; otherwise calibrate the replacement rater on the anchor sheet without exposing labels.

Use the independent rater scores to match the 32-task difficulty cohort's **marginal 0–3 bin count for each of the six dimensions** to the Stage 0 E012 target. For each dimension, convert the E012 48-task proportions to a 32-task target using Hamilton/largest-remainder apportionment; ties in fractional remainder go to the lower score bin. Require exact equality to those apportionment counts before sealing. Do not claim that six-dimensional joint distributions are matched; report joint profiles descriptively. If the fixed 32-task cohort cannot meet the six marginal quotas within the four-family cell structure, stop and issue a versioned construction amendment before model contact rather than relaxing bins after seeing results.

Keep author scores as construction metadata, not matching truth. Report author/rater exact agreement and mean absolute score difference for each dimension, plus their histograms. Cohort matching uses only the independent rater's scores.

## 6. Stage 4 — independent four-candidate production and ordinal balance

Every task has exactly four offered candidates. Candidate production and review must be independent of both frozen v5 observers. Do not call, query, or use outputs from the v5 small or large observer to write, rank, filter, or vet candidates. Hand-written candidates, a separately identified non-observer model, and systematic reference-patch mutations are permitted; record method, tools, prompts, outputs, and author for provenance.

Use plausible distractors: partial fixes, correct changes in the wrong location, over-broad changes, and candidates that compile and pass visible checks but fail hidden edge cases. Do not make distractors malformed strawmen. Keep candidate IDs opaque and independent of correctness and ordinal; comments, variable names, filenames, and task prose must not announce which candidate is intended to be valid.

Balance the designated reference-derived valid candidate's **producer ordinal**, using the frozen `SeedSequence({SEED})` PCG64 child streams defined in Stage 1, with no additional draws for other purposes:

- Positive-control cohort: within every repository × family cell, place the designated valid candidate at ordinals 0, 1, 2, and 3 exactly once across its four tasks.
- Difficulty cohort: each of the three cells without an empty task uses ordinals 0–3 once. In each of the five cells with an empty task, assign the remaining three candidate-selection tasks three distinct ordinals. Balance the omitted ordinals across those five cells as counts `(2,1,1,1)`, giving valid-anchor totals `(6,7,7,7)` over the 27 candidate-selection tasks.
- Empty-valid tasks have no valid ordinal; randomize their four offered candidate order using the separate frozen order stream.

If more than one candidate passes all hidden checks, record the whole valid set and the designated anchor ordinal separately. Do not relabel a multiple-valid task to force ordinal balance. Candidate roles are placed into their final sequence by the producer using the locked ordinal/order streams; that initial sequence is the producer order. Preserve it through transport and bind task, IDs, patch hashes, and exact sequence to the E011 presentation receipt. Never sort candidates after receipt creation.

Before labels are opened, have an independent leakage reviewer check task wording, candidate text/comments/names, candidate IDs, and metadata for answer-revealing artifacts. Repair construction defects before bank seal; preserve each rejection and its reason. The review receives no answer labels.

## 7. Stage 5 — execution-only labels and deterministic validation

An independent label writer receives the sealed task, four candidates, and executable checks, but not the author's intended answer or rationale. It runs each candidate against visible and hidden checks in an isolated clean worktree and writes the valid set from execution results alone. The reference patch and all four candidates are tested. Do not ask either v5 observer which patch is correct.

Construction acceptance requires:

1. The reference patch passes all visible and hidden checks.
2. Every offered distractor fails at least one hidden check; if another offered candidate passes all checks, include it in the valid set and record that the task has multiple valid candidates.
3. Two clean source worktrees produce identical check outcomes and test identities for the reference patch and every candidate.
4. All task labels and author intent records are kept in separate vaults; the label writer's result is an execution receipt, not an author-provided key.
5. Empty-valid tasks have ordinary-looking requests and four plausible candidates; execution establishes that none passes the full hidden contract.

Any nondeterministic result, failed reference patch, leakage, or unexplained candidate outcome rejects the task/cell before model contact. Use only a predeclared outcome-blind reserve in the same cell; otherwise fail bank construction and version the repair. Preserve failures.

## 8. Stage 6 — construction telemetry and runtime bound

Use a fixed warm-cache policy. For each repository, pin host, toolchain, lint/test commands, and a repository-local `CARGO_TARGET_DIR`. Prime the dependency/build cache once from the clean base snapshot using offline locked commands. For each task, start from a fresh source worktree at the frozen commit, apply its reference patch, and run the full T1 construction sequence: patch application, compile/type-check, lint, and visible tests. Reuse only the warmed repository cache; do not reuse a prior task's source tree or any candidate's check result. Freeze and record the per-repository task execution order and cache-prewarm receipt before timing.

Record per stage and per task: CPU and wall milliseconds, peak memory if available, cache/prewarm identity, host/tool versions, exit code, and timeout. The hard construction ceiling is **120 seconds per full reference-patch T1 sequence**. A timeout or failure rejects that repository/task construction path; it does not convert the timing into an E013 signal result. The pipeline must not call the time “free” or treat this reference-patch timing as a cached candidate result.

This telemetry is a pilot and schedule input. It is not a direct substitute for E013-D's measured T1 cost on offered candidates. Compare it descriptively with v0.3.4's planning headroom (about 192 ms per non-null proposal at 70% recall under pooled E012 rates); actual D economic eligibility uses measured E013-D values and the locked `T_max` equation.

## 9. Stage 7 — seal and dry-run

Seal one manifest covering the two repository snapshots, `Cargo.lock` and toolchains, task/cell IDs, task prompts, candidate IDs and patch hashes with producer ordinals, reference patches, visible and hidden checks (separate roots/manifests/hashes), independent label receipts in a vault, author/rater rubric data, family definitions, empty-cell allocation, ordinal seed/streams, leakage audits, construction-time and rejection logs, and generator/tool versions. Hash each artifact; record the manifest root hash and access boundaries.

Run the exact parser, receipt validation, authority, journal, and replay path with synthetic fixtures only. Include synthetic outputs for correct choice, wrong choice, `NO_PROPOSAL`, malformed output, and explicit abstention. No observer is contacted and no bank label is used to author these synthetic fixtures. Require deterministic replay identity and zero unauthorized effects. Repair any pipeline defect by versioned amendment; preserve this sealed bank unchanged if a later pipeline version is needed.

## 10. Construction acceptance checks

| Check | Pass condition |
|---|---|
| Snapshot | Two fresh eligible Rust repositories; commit, lockfile, and toolchain identities sealed |
| Reference validity | Reference passes visible and hidden checks on two clean runs |
| Distractor validity | Every offered non-valid candidate fails at least one hidden check; full valid set comes from execution |
| Determinism | Identical check outcomes/test identities across repeat runs |
| Leakage | Independent blinded audit finds no answer-bearing task/candidate/ID artifact |
| Ordinal balance | Positive cohort exactly balanced per cell; difficulty cohort totals 6/7/7/7 over nonempty tasks |
| Difficulty matching | Six rater-score marginals exactly meet Hamilton-apportioned E012 target bins |
| Observer isolation | Zero v5 small/large observer contact during construction and dry-run |
| Runtime bound | Every reference-patch T1 sequence completes within 120 seconds under the frozen warm-cache policy |
| Dry-run | All synthetic output classes replay deterministically with zero unauthorized effects |

## 11. Pipeline use and sequencing

Record per-task authoring/curation time, rejection reason and stage, author/rater disagreement, candidate-generation method, and the T1 timing distribution. These pilot measurements inform staffing and schedule estimates for the additional 864-task E013-D and 1,120-task E013-C banks.

1. Complete Stage 0 blinded rubric scoring.
2. Complete Stages 1–7 for this 64-task bank and dry-run; seal it.
3. Run the already-authorized positive-control lanes once under v1.2. Do not promote its coarse recurrence criterion into an E013 safety claim.
4. Version any pipeline amendments discovered by the pilot. Then build and seal **both** E013-D and E013-C with the same locked pipeline before any E013 model contact. Do not let D outcomes affect C construction.
5. Build/hash T1–T5 adapters and time them on non-bank inputs only after separate explicit timing-only authorization.
6. Request E013-D contact authorization only after both banks, adapters, scoring code, manifests, and precontact checks are sealed. E013-C remains separately authorized only after development selection is frozen.

## 12. v0.3.4 result-reading note (non-normative)

The four-repository percentile cluster bootstrap is **not guaranteed conservative**. With four outer repositories its resampling distribution is lumpy; the between-repository component may be understated, while second-stage family-block resampling adds variance, so the net direction is unclear. Keep the locked pooled resource gate unchanged, and report each repository's mean and the leave-one-repository-out view. If a wall-time bound passes narrowly and one repository carries most of the saving, interpret the result as fragile even if the pooled bound meets its rule. This note does not reopen v0.3.4 or add a new gate.

## 13. Authorization boundary

The positive-control v1.2 model-contact authorization remains in force only after the user-built 64-task bank and this dry-run are sealed. This construction spec does not authorize or perform bank generation by the agent. It does not authorize E013-D/C model contact, adapter timing contact, threshold selection, or any experiment run. **The user builds the bank.**
"""


def make_outputs() -> dict[Path, bytes]:
    e013_lock = verify_parents()
    body = spec_text().encode("utf-8")
    bindings = {
        "construction_spec": SPEC,
        "generator": SCRIPT,
        "parent_positive_control_v12": PARENT_PC,
        "parent_e013_v034_amendment": PARENT_E013_AMENDMENT,
        "parent_e013_v034_lock": PARENT_E013_LOCK,
        "parent_e013_v034_verification": PARENT_E013_VERIFY,
    }
    lock = {
        "schema_version": 1,
        "artifact_id": "E012-PC-BANK-CONSTRUCTION-v1.3",
        "state": "CONSTRUCTION_SPEC_SEALED_BANK_NOT_BUILT",
        "parent_positive_control_v12_sha256": sha(PARENT_PC),
        "parent_e013_v034_lock_sha256": sha(PARENT_E013_LOCK),
        "bank_owner": "USER",
        "bank_generated_by_agent": False,
        "positive_control_model_contact_authorized": True,
        "positive_control_bank_status": "USER_BUILD_PENDING",
        "positive_control_run_status": "NOT_RUN",
        "e013_d_c_model_contact_authorized": e013_lock["model_contact_authorized"],
        "difficulty_cohort_empty_valid": {"count": 5, "total": 32, "target_rate": "8/48", "nearest_integer_quota": "5/32", "cell_allocation": "five distinct repo-family cells, split 2/3 across repositories"},
        "position_seed": {"algorithm": "NumPy SeedSequence.spawn(5) with PCG64", "seed": SEED, "streams": ["empty_cells", "empty_task_slots", "ordinal_assignment", "candidate_slot_order", "opaque_ids"], "positive_counts_by_ordinal": [8, 8, 8, 8], "difficulty_nonempty_counts_by_ordinal": [6, 7, 7, 7]},
        "visible_screen_policy": {"cache": "warm repository-local Cargo cache, primed from clean base snapshot", "per_sequence_timeout_seconds": SCREEN_TIMEOUT_SECONDS},
        "artifact_paths": {key: str(path) for key, path in bindings.items()},
        "sha256": {key: hashlib.sha256(body).hexdigest() if key == "construction_spec" else sha(path) for key, path in bindings.items()},
        "self_hash_note": "Lock excludes itself and the post-lock verification receipt.",
    }
    return {
        SPEC: body,
        LOCK: (json.dumps(lock, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"),
    }


def self_test() -> dict:
    verify_parents()
    text = spec_text()
    required = (
        "five empty-valid-set tasks", "Hamilton/largest-remainder", "Do not provide E012 outcomes",
        "two fresh Rust repositories", "independent of both frozen v5 observers", "(6,7,7,7)",
        "120 seconds", "build and seal **both** E013-D and E013-C", "not guaranteed conservative",
        "The user builds the bank.",
    )
    for phrase in required:
        assert phrase.casefold() in text.casefold(), phrase
    return {"state": "PASS", "layout_tasks": 64, "matched_empty_tasks": 5, "matched_candidate_tasks": 27,
            "positive_valid_ordinal_counts": [8, 8, 8, 8], "difficulty_valid_anchor_counts": [6, 7, 7, 7],
            "seed": SEED, "screen_timeout_seconds": SCREEN_TIMEOUT_SECONDS}


def verify() -> dict:
    lock = json.loads(LOCK.read_text(encoding="utf-8-sig"))
    checks, actual = {}, {}
    for name, path_text in lock["artifact_paths"].items():
        path = Path(path_text)
        checks[f"exists:{name}"] = path.is_file()
        actual[name] = sha(path) if path.is_file() else None
        if path.is_file():
            checks[f"sha256:{name}"] = actual[name] == lock["sha256"][name]
    verify_parents()
    text = SPEC.read_text(encoding="utf-8-sig")
    checks["empty_set_decision"] = "five empty-valid-set tasks" in text
    checks["contact_boundary"] = lock["positive_control_model_contact_authorized"] and not lock["e013_d_c_model_contact_authorized"] and lock["bank_generated_by_agent"] is False
    checks["bank_owner"] = lock["bank_owner"] == "USER" and lock["positive_control_bank_status"] == "USER_BUILD_PENDING"
    checks["positive_control_parent"] = sha(PARENT_PC) == lock["sha256"]["parent_positive_control_v12"]
    checks["e013_parent"] = sha(PARENT_E013_LOCK) == lock["sha256"]["parent_e013_v034_lock"]
    result = {"artifact_id": "E012-PC-BANK-CONSTRUCTION-VERIFICATION-v1.3", "state": "PASS" if all(checks.values()) else "FAIL", "lock_sha256": sha(LOCK), "checks": checks, "checked_sha256": actual, "bank_generated_by_agent": False, "model_contact_performed": False}
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
