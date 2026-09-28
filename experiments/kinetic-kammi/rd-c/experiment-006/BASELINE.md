# E006 baseline and authority contract

E006 is a new package at `C:\rd-c\experiment-006`. It reads E001/E002/E004/E005 code by local path and does not write to those projects, Phoenix, Northstar, or research branches. E005's published report and code are baseline inputs; its frozen run directories remain unchanged.

## Public and hidden data

The public observation contains an episode ID, task goal, two observer proposals, visible source revisions, ages, warning flags, confidence, and a route-domain key. It contains no source outcome, fixture state, correct action, or held-out label. The source fixture is generated and durably written separately before the runtime opens it. Domain IDs 8–11 occur only in the held-out bank.

The E005 domain table is loaded from E005's development generator and frozen value-model implementation. E006's smoothed and feature-based estimates are fitted on the E006 development bank. All route plans are written before the held-out labels are written or loaded.

## Proposal and authority

Inspection transport status and candidate evidence are parsed into four resolver outcomes. A unique, valid result that matches the active proposal is `Confirmed`; a unique valid alternative is `Contradicted`; missing, low-confidence, malformed, or internally inconsistent evidence is `Unknown`; timeout or transport failure is `Failed`.

`Confirmed` explicitly proposes the active action. A sufficiently strong unique `Contradicted` result proposes its candidate. `Unknown` and `Failed` propose `Action::Recover` from `DECIDING` to `OBSERVING`; the runtime stops that episode unresolved and records no task-action effect. The transition is compiled into the E002 authority with evidence, confidence, and a bounded-recovery guard. No inspected revision is trusted by authority.

## Measurement

The development and held-out banks each have 256 and 384 episodes respectively. Budgets are 16, 32, 48, and 64 distinct paid queries for every routing lane; all lanes use the same resolver, task simulator, compiled authority, and journal policy. The no-inspection lane uses zero calls. “Net completion” means actual tasks reaching `DONE`; unresolved inspection results leave the task pending in `OBSERVING` and therefore do not count as complete. The report also shows paid query units per completion so query cost remains visible without inventing a conversion between money and task completion.

Crash cases distinguish query intent, endpoint attempts, paid charges, resolver output, and task action effects. The simulated endpoint guarantees idempotent lookup by query ID. That guarantee is explicit and is not generalized to real services without an equivalent endpoint contract.
