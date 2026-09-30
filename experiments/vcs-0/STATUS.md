# VCS-0 — Vector Control Surface lane (closed)

## Authoritative interpretation

**`CORRECTION-2026-09-30.md`** — the four-cell correction. Supersedes the interpretation in
the original closeout.

- Correction commit (authoritative): see `git log --oneline -1`
- Original sealed closeout, preserved unchanged: `13c22b57`

Both are part of the record. The first commit shows how the interpretation changed; the second
states it correctly. History is not polished to hide the mistake.

## Status

```
R2a scientific result            DONE
R2a operational packaging        DONE     (verified: hashes, lane identity, eligibility)
VCS-0c preflight                 PASS     (three-lane ID equality, 2000-row population)
VCS-0c execution                 DONE
Gate-1 bootstrap repair          DONE
O2 reversal diagnosis            DONE     (no reversal; earlier claim was an artifact)
VCS-1b                           NOT EARNED
Claudia                          scientifically idle
Shift transport                  NOT RUN
BANK-v2                          NOT USED
protected/test-truth             NEVER OPENED
```

## Headline

**VCS-0c closes without earning VCS-1b. Operational semantic estimates improve geometry, but
the cheap-versus-neural comparison is substrate/population dependent. Cheap wins the
preregistered primary causal/correctness cell; neural estimates show a supported advantage on
encoder/correctness. Across both substrates, on the primary population, the best operational
reconstruction remains below the frozen 25% oracle-gap recovery gate.**

Four-cell summary (verified against `vcs0c-result.json`):

| cell | G2 | G3-CHEAP | best neural | cheap lead | G0→G2 recovery |
|---|---|---|---|---|---|
| causal / correctness **(primary)** | 0.6174 | **0.6603** | 0.6504 | **+0.0099** | 15.4% |
| causal / solvability | 0.4613 | 0.6649 | 0.6658 | −0.0009 | 53.6% |
| encoder / correctness | 0.5706 | 0.6283 | **0.6441** | **−0.0158** | 24.3% |
| encoder / solvability | 0.4360 | **0.6614** | 0.6580 | +0.0034 | 54.2% |

## Result

> Representation-derived estimates add no advantage on the preregistered primary
> causal/correctness cell, but show a small substrate-specific advantage on
> encoder/correctness. That advantage is still insufficient to clear the frozen downstream
> geometry gate.

```
causal and encoder disagree
        ↓
construction method matters somewhat

but on the population that matters for authority (observer_correctness, primary)
neither operational surface recovers enough oracle geometry
        ↓
VCS-1b not earned
```

## What this lane contributed beyond the negative result

1. **The two-axis ABI.** `provenance_class` (conceptual origin) separated from
   `runtime_availability` (decision-time). The conflation in v0.1 let
   `observer.legal_set_support` survive into G3 and made G2 == G3 by accident. One coordinate
   has disagreeing axes, and it is exactly that one.
2. **A mandatory circularity detector.** The first atlas reported a clean three-population
   map that was definitional — BANK-v1 derives its decision labels from the same fields the
   coordinates read. Caught before it became a claim.
3. **Leave-one-in attribution.** Removal-from-G0 could not attribute the G0→G1 loss (shares
   came out negative) because the unavailable coordinates are mutually redundant; recovery sums
   exceeded total loss. Switching direction produced the VCS-0b estimator handoff.
4. **A degeneracy screen.** The causal `first` coordinate carries 7 distinct vectors across
   20,000 rows. Found here, and it retroactively invalidated the encoder run's P2 headline.
5. **Operational cost of an estimator is not its point accuracy.** A 25-feature ridge over
   cheap surface statistics beat frozen-hidden-state estimators on the primary cell.

## Files

- `CORRECTION-2026-09-30.md` — authoritative correction
- `RESULT.md` — original closeout (correct data, overgeneralized interpretation)
- `src/vcs_abi_v02.py` — two-axis ABI
- `src/vcs0c.py`, `src/vcs0c_run.py`, `src/vcs0c_closure.py` — preflight, execution, closure
- `src/vcs_attrib_v02.py`, `src/vcs_handoff.py` — VCS-0b attribution and handoff

Results: `D:\codex-runs\encoder-contrast-01\vcs\{vcs0c-result,vcs0c-closure,VCS-0b-HANDOFF}.json`