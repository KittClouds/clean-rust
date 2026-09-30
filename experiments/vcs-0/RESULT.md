# VCS-0c — Operational Reconstruction (sealed)

> **CORRECTED — see `CORRECTION-2026-09-30.md`.** The headline in this document was computed
> correctly for the preregistered primary cell (causal / observer_correctness) and was
> overgeneralized to all cells. `13c22b57` is preserved as the original interpretation; the
> four-cell result is authoritative. Specifically, on **encoder / observer_correctness** the
> neural arms beat the cheap estimator by 1.6 pp with supported intervals, which this document
> does not reflect. The gate ledger, the VCS-1b decision, and every number here are unchanged.

**Outcome B on the preregistered primary cell. VCS-1b NOT earned on BANK-v1.**

Population: the exact 2,000-row R2a DEV export population, 1,668 canonical world groups
(332 paired-surface rows retained as separate observations, bootstrap grouped by
`paired_world`). Primary population `observer_correctness`; `solvability` secondary.

Preflight PASS: intended-population ID-set hash matches the export manifest, export SHA-256
verified, all three lanes (`causal_base`, `ner_lora_step500`, `B1_count_statistics`) equal the
intended population with 0 duplicates, B1 artifact hashes agree across manifest and atlas,
no gate-failed lane present.

## Primary population — causal / observer_correctness

| arm | 1-NN | ratio |
|---|---|---|
| G2 | 0.6174 | 0.9090 |
| G3-EVIDENCE-ONLY | 0.6388 | 0.9009 |
| G3-MISSING-ONLY | 0.6380 | 0.8513 |
| **G3-CHEAP** | **0.6603** | **0.8249** |
| G3-BASE | 0.6463 | 0.8520 |
| G3-NER | 0.6504 | 0.8482 |
| G3-HYBRID-FIXED | 0.6471 | 0.8534 |
| O2 (truth) | 0.7934 | 0.7269 |
| G0 (oracle) | 0.8967 | 0.6515 |

## Gate 1 repaired

Per-row leave-one-out correctness is now fixed once per arm; the bootstrap resamples
group means only, so no distance recomputation occurs inside a resample.

| arm | mean diff vs G2 | 95% CI | excludes zero |
|---|---|---|---|
| **G3-CHEAP** | +0.0430 | **[0.0123, 0.0605]** | **yes** |
| G3-BASE | +0.0289 | [−0.0098, 0.0468] | no |
| G3-NER | +0.0331 | [−0.0016, 0.0543] | no |
| G3-HYBRID-FIXED | +0.0298 | [−0.0083, 0.0479] | no |

Instrument-variation receipt: 399–453 distinct bootstrap deltas, 67 distinct group
multiplicities, 87 distinct sampled row counts, 89–103 distinct paired totals. The previous
byte-identical-150-times behaviour is gone.

**Only the cheap estimator's improvement is statistically supported.** Every neural arm's
interval spans zero.

## Gate ledger

| gate | result |
|---|---|
| 1. beats G2, grouped paired CI excludes zero | **PASS** — G3-CHEAP, +0.0430 |
| 2. ratio moves toward oracle | **PASS** — 0.909 → 0.825, 46% of the G2→O2 move |
| 3. recovers ≥25% of G0→G2 gap | **FAIL** — 15.4% |
| 4. circularity + degeneracy | **PASS** |
| 5. neural beats cheap | **FAIL** — G3-CHEAP *is* the best arm |

Threshold, arms, metrics and normalization were not changed by this closure.

## O2 reversal — does not occur on the primary population

| surface | correctness | solvability |
|---|---|---|
| G2 | 0.6174 | 0.4613 |
| G2 + truth.n_evidence_facts | 0.7826 | 0.5779 |
| G2 + truth.n_missing_facts | 0.6744 | 0.5431 |
| O2 (both truth) | 0.7934 | 0.6249 |

The O2-below-G3-CHEAP ordering seen in the main run was on **solvability**, and it does not
reproduce here: O2 (0.6249) exceeds G3-CHEAP (0.6649) only in the main-run cell where the
cheap arm scored higher; on the primary population O2 (0.7934) is far above every G3 arm.
Neither truth coordinate hurts alone on either population. Recorded as a main-run
measurement artifact rather than a real geometric reversal, and gate 2 keeps its caveat.

## Result

> A cheap observable semantic estimator recovers some useful control geometry, but the frozen
> representation adds no operational advantage over that cheap route, and the recovered
> geometry is too small to earn downstream authority testing under the frozen gate.

Architecture as it now stands for this bank:

```
oracle semantic state
        ↓
cheap observable approximation      ← 25 statistics, ridge alpha=1
        ↓
some geometry survives              ← +0.043 over G2, 46% of the oracle ratio move
frozen hidden-state estimator        ← +0.029, interval spans zero
        ↓
no additional geometry
```

The `representation → semantic estimate → control` bridge did not pay rent on BANK-v1. The
cheap route did.

Scope limit carried from R2a: `n_missing_facts` is restricted to 0/1 in this panel and is
partly scenario-construction-defined, so any positive result supports this BANK-v1 estimator
interface only.

## Files

- `src/vcs_abi_v02.py` — two-axis ABI (provenance_class / runtime_availability)
- `src/vcs0c.py` — preflight, arm construction, grouped metrics
- `src/vcs0c_run.py` — main run, five gates
- `src/vcs0c_closure.py` — gate-1 repair and O2 diagnosis
- `src/vcs_handoff.py`, `src/vcs_attrib_v02.py` — VCS-0b handoff and leave-one-in attribution
- Results: `D:\codex-runs\encoder-contrast-01\vcs\{vcs0c-result,vcs0c-closure,VCS-0b-HANDOFF}.json`

`protected/test-truth` was never opened. BANK-v2 was not used. No shift transport run.