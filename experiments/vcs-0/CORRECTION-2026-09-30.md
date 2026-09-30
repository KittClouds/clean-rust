# CORRECTION — 2026-09-30

Correction to `13c22b57` ("vcs-0: VectorControlState ABI + operational reconstruction").
`13c22b57` is preserved unchanged as the original interpretation. This is an
**interpretive** correction only: no artifact, threshold, arm, normalization, metric, or gate
was altered or rerun.

## What was incorrect

`13c22b57` stated:

> "G3-CHEAP beats every neural arm: 1-NN 0.6603 vs 0.6463 (Base) / 0.6504 (NER) /
> 0.6471 (Hybrid-Fixed)"

> "Outcome B"

> "the `representation -> semantic estimate -> control` bridge does not pay rent on BANK-v1"

Those numbers are correct **for the preregistered primary cell
(causal / observer_correctness)** and were generalized to all cells. The data did not support
that generalization.

## Correct interpretation — verified four-cell table

| cell | G2 | G3-CHEAP | best neural | cheap lead | all G3 supported? | G0→G2 recovery |
|---|---|---|---|---|---|---|
| causal / correctness **(primary)** | 0.6174 | **0.6603** | NER 0.6504 | **+0.0099** | cheap only | **15.4%** |
| causal / solvability | 0.4613 | 0.6649 | NER 0.6658 | −0.0009 | all four | 53.6% |
| encoder / correctness | 0.5706 | 0.6283 | BASE 0.6441 | **−0.0158** | all four | **24.3%** |
| encoder / solvability | 0.4360 | **0.6614** | NER 0.6580 | +0.0034 | all four | 54.2% |

- `causal/correctness` — cheap wins, supported
- `causal/solvability` — effectively tied (0.0009, within noise)
- `encoder/correctness` — **neural wins, supported** (Base and Hybrid-Fixed both beat cheap)
- `encoder/solvability` — effectively tied (0.0034)

## A second overgeneralization, in the opposite direction

The correction instruction proposed:

> "Across both substrates, however, the best operational reconstruction remains below the
> frozen 25% oracle-gap recovery gate."

That holds for `observer_correctness` (15.4% causal, 24.3% encoder) and is **false for
`solvability`**, where recovery is 53.6% and 54.2% — comfortably above 25%. Verified directly
from `vcs0c-result.json` before writing.

Gate 3 was preregistered against the primary population, where it fails. Solvability clears it
comfortably. Both facts are recorded rather than reconciled.

## Unchanged

- All point estimates and ratio values
- The gate-1 bootstrap repair (fixed per-row LOO, grouped paired bootstrap)
- The O2 diagnosis (no reversal on either population; the earlier claim was a main-run artifact)
- The preregistered gate ledger, evaluated on the primary cell
- Gate 3 FAIL (15.4% < 25%)
- Gate 5 FAIL on the primary cell (cheap is best there)
- **VCS-1b NOT EARNED**

## Corrected summary

> Representation-derived estimates add no advantage on the preregistered primary
> causal/correctness cell, but show a small substrate-specific advantage on
> encoder/correctness. That advantage is still insufficient to clear the frozen downstream
> geometry gate.

## Durable result

```
causal and encoder disagree
        ↓
construction method matters somewhat

but on the population that matters for authority
(observer_correctness, primary)
neither operational surface recovers enough oracle geometry
        ↓
VCS-1b not earned
```

`protected/test-truth` was never opened. BANK-v2 was not used. No shift transport was run.