# E012 bank construction plan v1.4 — paired counterfactual repair

**State:** design repair frozen before the A12 scored-check rerun. Model contact is prohibited.

This amendment repairs the bank defect recorded in `E012-BANK-A11`. It preserves the 48 tasks, 12 families, three repositories, four candidates per task, 26 frame conditions, E009 v5 observer contract, and E002/E011 authority path.

## Paired channel blocks

- Task/request, execution, and context pairs share the same candidate patches bound to the same action IDs and the same producer-order sequence. Only the declared evidence payload and its executable task check vary.
- Joint families are complete 2×2 request-by-execution designs. Candidate content, IDs, order, context, observer task ID, and task variant are common across all four cells.
- Candidate/action pairs share request, execution evidence, repository context, tests, action-ID sequence, observer task ID, and task variant. The patch bound to each action ID changes; the executable valid action-ID set must change.
- Abstention controls remain separate examples with no passing candidate. They are not counted as truth-switch pairs.

Within every paired block, the observer-facing task ID and task variant are held constant. The sealed truth index retains each unique internal task ID and maps it to the shared presentation ID. Presentation receipts continue to bind each full frame digest, ordered action IDs, and request identity.

## Exact balance

The paired assignment solver is frozen before the rerun. It chooses role-to-ID maps and a producer-order sequence subject to paired equality and exact valid/invalid balance by action ID and position within family. Families with one passing candidate per action task have four positive and twelve negative candidate rows; `bounded-prefix-copy` has two passing and two failing candidates per task; abstention families have zero passing candidates. Primary-gold positions are balanced where a primary gold role exists.

## Candidate menu repair

- `help-color-capability`: the narrow-width distractor keeps its width side effect but uses `ColorChoice::Auto`, so it fails the task's required Always/Never color contract. The two context states then have exactly one passing action each.
- `map-order-feature-contract`: the redundant canonical-sort distractor omits the first map key, making it fail the exact output contract. The two context states then have exactly one passing action each.

These candidate patches are versioned A12 inputs. Their original v1 forms and prior outcomes remain preserved.

## Execution order

1. Freeze the A12 design, preparation script, source fixture, candidate patches, test harnesses, and assignment/finalization rule.
2. Run the complete candidate and base checks in isolated overlays with a content-addressed `D:` Cargo target. Quarantine conflicts and preserve failed runs.
3. Derive valid action sets from the new consistent executable checks; solve paired ID/order assignments under the frozen exact-balance constraints.
4. Project all conditions from the repaired source channels, create receipts, and run paired-truth, nuisance-feature, frame, schema, and replay audits.
5. Create a new `FROZEN_BEFORE_MODEL_CONTACT` lock only after those audits pass.
