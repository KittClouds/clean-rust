# Architecture amendment v4.1: immediate activation and Chief workspace governance

Status: authorized by the program owner's direct instruction on 2026-09-29. This amendment
supersedes only the October 6, 2026 activation floor in v4. It does not simulate the clock or
weaken the live verification, backup, rehearsal, activation, or independent-verifier steps.

## Activation decision

The program owner authorizes the rollback-window closure and v4 activation effective at the real
UTC time recorded in the closure artifact. The Library records this amendment and closure before
activation. The effective time must be valid UTC and may not be in the future according to the
Library clock.

The owner accepts these concrete conditions and consequences:

- Monitoring has gaps. The activation audit binds the exact monitor snapshot and reports every
  interval longer than 45 minutes, warning count, latest sample age, projection lag, and gate state.
- The existing Rust release history includes a failed MCP probe followed by re-acceptance of the
  previous release and confirmation that it served with the flight gate open. The checker must
  read and verify the actual release report and fallback steps.
- A pre-activation verified backup is required. After activation, Python rollback is retired and
  recovery is fix-forward.
- The monitor depends on an interactive logged-in session; scheduled backup and daemon autostart
  are not configured. These limits are recorded, not represented as passing controls.

The live activation still requires a current backup, Python's independent verification of its v1
export, `kammi-verify` PASS at the exact pre-activation journal head, a current-copy rehearsal with
the real clock, and `LibraryVocabularyActivated` as the first v4 event. The activation payload
references registered CAS artifacts for this amendment, closure decision, backup manifest,
monitoring snapshot, rollback evidence audit, and pre-activation verification.

## Workspace governance

Chief Kammi is the sole workspace owner and governor. Workspaces are created with exactly
`owners: ["chief-kammi"]`. Chief controls workspace creation, objective, scope, next step, handoffs,
closure, lifecycle, routing, and institutional memory. Agents and labs are producers and
participants; they contribute through Chief-issued handoffs and cannot create or govern workspaces.

Chief controls the workspace, not the scientific truth inside it. A workspace may cite a lab's
sealed artifacts and summarize routing state, but ingestion must preserve source lab, artifact and
seal identities, timestamps, classifications, decisions, evidence references, contact boundaries,
and lineage. Sealed scientific evidence is ingested by identity and provenance; it is never
flattened, rewritten, or reinterpreted as a Library claim.

## Contract and tooling changes

- The fixed October 6 floor is removed from the activation validator and core.
- `KAMMI_ROLLBACK_WINDOW_CLOSURE_V2` records owner authority, real effective time, named risk
  acceptance, and references to monitoring and rollback evidence.
- The preflight checks real monitor history, release reports, fallback outcome, frozen Python
  rollback materials, the current Library head/gate, leases, panel exposures, and projection lag.
- Test fixtures may use deterministic clocks only on isolated disposable stores. Live rehearsal and
  activation use the actual Library clock.
- The Python rollback path is retired after activation; the Python source and pre-cutover backup
  remain preserved as historical evidence.
