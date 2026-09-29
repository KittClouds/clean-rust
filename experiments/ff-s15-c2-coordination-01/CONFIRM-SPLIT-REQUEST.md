# Request: a fresh sealed BANK split for System 1.5 confirmation (draft — not sent)

For the BANK / representation side (Lexi). The System 1.5 build (Claudia's C-rungs) has taken the development data as far as it can: BANK-v1 TEST has been opened twice, and DEV has now
been used for calibration and holdout scoring (C1) and a census (C2a). Any claim beyond "development evidence" needs a population nobody has looked at.

**Ask: `BANK-C1-CONFIRM`** — new world seeds, new render seeds, the same frozen task contract, truth sealed. Build it now, in parallel; it is not a blocker for the C-rungs.

## What must hold

- **Same task contract as BANK-v1** (decision ACT/ASK/ABSTAIN, the 14 actions, 11 abstain reasons, NLI, typed sets), same input format, same row schema, so the frozen C1 procedure runs unchanged.
- **New seeds:** none of the seeds in `seed-registry-v1.json` for world generation or rendering. No world, and ideally no relation graph, shared with TRAIN, DEV or TEST — report the `graph_hash` overlap if it cannot be zero
  (inside DEV, 19,220 distinct graph hashes cover 24,000 rows, so graph reuse exists).
- **Truth sealed:** publish a hash of the truth file before anyone scores; predictions and thresholds are sealed by the consumer *before* truth is joined. Claudia does not open it.
- **Paired renderers stay together** (the `…@S0/@S1` ids), as in DEV, so a grouped split is possible.

## Composition (rough sizing from C1's measured rates)

C1's cheap tier executes about 6% of rows at a 5% harm target, so confidence intervals are set by *executed* counts, not row counts.

- **Enough of the troublesome families.** C1 showed pooled harm 5.1% but 9.7–12.0% on surface families S3, S4 and S5 (35–75 executed rows each, so noisy). To tell whether that is real, aim for
  ≥ 8,000 rows each of S3, S4 and S5 (S4 executes only about 3% of rows), and ≥ 3,000 for each other family — roughly 42,000 rows.
- **Enough ASK.** ASK is 4.9% of DEV, and the ASK rung will need to be scored on it. Either oversample ASK or size for ≥ 1,500 ASK rows (about 31,000 rows at the natural rate).
- Keep the natural mix of ACT / ABSTAIN otherwise, so pooled numbers stay comparable to C1.

## What will be run on it, once

The frozen C1 baseline (thresholds from CAL, unchanged), any coordination policy that survives (C2a found no headroom, so probably none), and the ASK treatment — each frozen before the split is opened,
all scored on the same population. No family-specific thresholds; the split only needs to show whether the family brittleness is real.
