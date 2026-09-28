# Kammi Ledger acceptance status v0.2

**New-flight gate: CLOSED_PENDING_ACCEPTANCE.** Existing authorized lab work
is outside this gate. The architecture lock remains v1 and was not edited.

## E4 generic history slice

- The 447-entry final E4 seal still verifies exactly. Its 432 unique byte
  objects remain bound under the original Merkle import root.
- A separate oversight supplement captured 61 E4 audit/contract/seal JSON
  paths that the final scientific seal omitted. Its 60 unique new objects are
  bound to the original Merkle import as a child; the scientific seal is intact.
- A distinct, versioned E4 history run contains 557 typed facts: 168 attempt
  assertions (including nested stages), 17 supersession edges, 223 contact
  assertions, 148 evidence-access assertions, and one snapshot head. The
  counts are parsed legacy assertions, not live telemetry.
- A fresh Ladybug projection rebuilt from only CAS and journal reproduced the
  journal head, fact rows, counts, and 493-object supplemental closure.
- The stopped partial v3 import into the earlier run remains in the journal
  with its failure receipt. The completed pass uses a new run identity.
- No positive contact assertion was found in the captured sources. That is
  not a program-wide no-contact attestation. Source coverage is limited to
  the verified final seal and the captured E4 JSON supplement.

The generic history API returns heads, stopped and other attempts,
supersessions, predecessor chains, scoped contact claims, and scoped evidence
access claims. It always reports no authorization conferred by these facts.

## Remaining acceptance gates

The E4 fixture demonstrates history reconstruction for the captured snapshot.
The following remain open: policy and exposure enforcement; GPU/resource
leases; schema adapters; remote bundles; memory retrieval; crash and power-loss
qualification; independent actor authorization; and production one-writer
process fencing. No new flight is authorized by this v0.2 status.
