# Reviewer audit: GC1 PAR8 and AUDIT1

This is a post hoc review, not a new constructor qualification or a preregistered experiment. Original artifacts were read without modification. Only this reviewer folder was written. No beam search, fresh engineering sample, scientific seed, or behavior was executed.

## Disposition

**PASS for reproduction of the saved partial outputs; exact-constructor readiness remains unqualified.** The partial result is real and reproducible within the frozen Python learner. Several earlier interpretations and claims about the strength of verification need narrowing.

## Findings

1. **Material interpretation correction: geometry is a constraint, not an established sole bottleneck.** Eight saved best-search outputs fail final gates; all 14 selected valid states still contain 124–222 mismatches. Even best-search diagnostics retain 123–169. Selecting a geometry-balancing successor as a hypothesis is reasonable; claiming it solves the remaining problem is unsupported.

2. **Material omitted outcome: collateral damage.** Fresh row-wise reconstruction finds 1,050 initially wrong rows repaired and 118 initially exact rows damaged. These counts reconcile exactly with 3,386 → 2,454 global mismatches. Reporting repairs alone would overstate efficacy.

3. **Prospective correctness gap: exact-success predicate omits target-weight distinctness.** `q10-gc1-par8-v1/scripts/run_gc1.py:353` checks zero readout mismatches and final numerical geometry, but not `W_alternative != W_target`. No exact outputs occurred, so the current negative exact result is unaffected. Explicit distinctness, support/bounds/reserve, complete maps, and bitwise parity should be mandatory success assertions in a successor.

4. **Prospective correctness gap: unconditional partial label.** The same branch labels every non-exact return `PARTIAL_GLOBAL_FEASIBILITY`, without asserting a final-valid, nonidentity, strictly baseline-improving output. This review independently confirms those conditions for all 14 saved selections. Thus the reported count survives, but the status mechanism alone would not certify a future run.

5. **Audit independence was overstated.** AUDIT1 uses the same PF5 prefix/readout/geometry routines and GC0 score routine as PAR8. It does not itself check all of permitted/interior membership, baseline improvement, or target distinctness. Its selected-group set equality also does not rule out duplicate selected-group records (`audit.py:96`), and its diagnostic rejection count trusts the saved flag (`:140`). This reviewer pass explicitly tests those saved-state conditions, unique group choices, and diagnostic geometry using independently written replay/scoring/geometry code. The shared state loader remains a common dependency. Neither audit verifies every historical candidate or beam decision.

6. **Bounded search differs from the broad proposed constructor.** The actual group-order fourth key is physical-support row count (`run_gc1.py:294`), not conflict-graph degree. Exploration uses rounded geometry debt plus active-group count (`:273`), not all proposed diversity signatures. These are the inspected frozen runtime semantics; do not describe the run as testing every mechanism in the original proposal. Beam width 48 is a maximum: 605/801 rounds retained 48, and early rounds retained fewer. No outcome comparison here isolates these choices.

7. **Receipt immutability is procedural.** `write_json` uses direct `write_text` (`run_gc1.py:44`), without atomic rename or overwrite protection. PREEXECUTION remains a historical pre-run record and does not prevent rerunning the command into the same output paths. Current hashes match and were stable before/after this review; that supports present integrity, not a tamper-proof execution history. Earlier commentary calling emission atomic was incorrect. Archive completed bytes and add exclusive/atomic output handling in a successor.

8. **Generalization and inferential units.** The 14 cases are repeated endpoint/set instances of seed9731. They are not 14 fresh seeds or biological replicates. No significance test or broad success-rate estimate is justified. Exact matching concerns the declared sequential readout panel, not every possible future input or dynamical trajectory.

## Verification performed

- Checked PAR8 and AUDIT1 plan, contract, runner, declared parent hashes, and STATUS hashes for execution/summary/result files.
- Verified the nested runtime bindings against current frozen RH1 contract checks.
- Reconstructed both `best_valid` and `best_search` for every case: 28 saved states total.
- Checked one selected palette entry per group, exact group coverage, canonical map agreement, palette identity, ZERO semantics, and committed/canonical choice agreement.
- Rebuilt prefixes directly from baseline f32 bytes; verified permitted/interior coordinates, legal vocabulary, finite weight bounds, unchanged coordinates outside the map, boundary membership, and the inherited 16-step reserve.
- Reimplemented sequential accumulation with explicit IEEE-f32 storage after each addition, initialized at negative zero; compared full readout bit hashes, including signed-zero distinctions.
- Recomputed mismatch count, ULP distance, L2/max residual, and full axis/norm/linear-drive geometry independently of the existing helpers; all exactly matched saved values.
- Verified all selected valid states strictly beat baseline and differ from both baseline and target weights. Independently replayed geometry-invalid search diagnostics instead of trusting their flags.
- Checked 801 completed group traces, 14 unique task keys, and summed recorded evaluation counts of 323,648. Evaluation counts are receipt arithmetic, not an independent reenactment of every call.
- Rehashed bound inputs after verification; no parent changes detected.

The reviewer script had a reporting-key typo during development, after state checks passed. It was corrected before the final evidence file was produced. The final script exits successfully. This did not change the constructor or its sealed results.

A Luna xhigh agent performed a read-only static review of the two original runners/contracts. It corroborated the classification and audit-coverage gaps above. The new arithmetic verification was performed locally; the agent's agreement is code-review corroboration, not a second independent numerical experiment.

## Per-case outcomes

All endpoint names below start with `seed9731-`. “Search” is the best state in the final retained beam; “valid” is the cumulative selected best-final-gate-valid state. The former is not a certified unconstrained optimum or necessarily the best state ever considered.

| Endpoint | Set | Baseline | Valid | Search | Fixed old errors | New damage | Search gate failure |
|---|---:|---:|---:|---:|---:|---:|---|
| L-tau16 | 0 | 243 | 164 | 164 | 84 | 5 | none |
| L-tau16 | 1 | 244 | 169 | 169 | 80 | 5 | none |
| L-tau16 | 2 | 251 | 166 | 164 | 90 | 5 | axis |
| L-tau16 | 3 | 249 | 159 | 159 | 96 | 6 | none |
| L-tau4 | 0 | 259 | 166 | 166 | 108 | 15 | none |
| L-tau4 | 1 | 251 | 167 | 167 | 105 | 21 | none |
| L-tau4 | 2 | 247 | 162 | 162 | 105 | 20 | none |
| L-tau4 | 3 | 245 | 222 | 157 | 32 | 9 | axis |
| R-tau16 | 1 | 247 | 185 | 144 | 70 | 8 | axis |
| R-tau16 | 3 | 234 | 181 | 134 | 57 | 4 | axis |
| R-tau4 | 0 | 222 | 211 | 129 | 11 | 0 | linear drive |
| R-tau4 | 1 | 241 | 181 | 143 | 68 | 8 | axis, linear drive |
| R-tau4 | 2 | 238 | 197 | 143 | 45 | 4 | axis, linear drive |
| R-tau4 | 3 | 215 | 124 | 123 | 99 | 8 | axis, linear drive |
| **Total** | | **3,386** | **2,454** | **2,124** | **1,050** | **118** | **8 cases** |

Final normalized limits: acquisition axis ≤2e-6, norm ≤2e-7, linear drive ≤2e-6. In the eight rejected search states: axis failures 7, linear-drive failures 4, both 3, norm failures 0. Gate failures are diagnoses of those particular saved candidates.

## Source chain and reproducibility

Paths are relative to `C:/code land/clean-rust/experiments/drosophila-heresy/`:

- `q10-gc0-gp1-par2-v1/qualification/palettes.jsonl`: sealed candidate library.
- `q10-gc1-pf0-v1/qualification/execution.json`: support/conflict preflight.
- `q10-gc1-par8-v1/{PLAN.md,CONTRACT.json,PREEXECUTION.json,scripts/run_gc1.py}`: executed protocol and runtime.
- `q10-gc1-par8-v1/qualification/execution.json`: authoritative saved outputs and traces.
- `q10-gc1-par8-v1/qualification/derived/{SUMMARY.json,RESULT.md,STATUS.json}`: derived result and digest bindings.
- `q10-gc1-par8-audit1-v1/qualification/execution.json`: prior selected-state reconstruction audit.
- `supervision/gc1-review-20260918/{verify_review.py,evidence.json}`: this review's verification and detailed manifest.

PAR8 execution SHA-256: `A4304E70F7D32436109CD6F3367C298CD1227FBD5C4AA2578C28D14272721D6B`.

AUDIT1 execution SHA-256: `054698350A686B3E259D4D6AF4218D725AFC748141D2253449C5962022B058AA`.

PAR1–PAR7 have no execution receipts on disk; their drafts/smokes are not result evidence. Interruption markers exist for PAR1 and PAR3–PAR6, but not PAR2 or PAR7. Do not represent missing markers as independently verified execution history.

To reproduce this reviewer pass from the repository root: `python -B experiments/drosophila-heresy/supervision/gc1-review-20260918/verify_review.py`. It only writes `evidence.json` in this reviewer folder. It reuses the frozen data loader, so the local parent data and runtime dependencies are required.
