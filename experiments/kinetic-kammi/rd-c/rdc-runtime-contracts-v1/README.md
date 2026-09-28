# R&D-C Runtime Contracts v1

This standalone crate extracts the two reusable E006 boundaries without changing E006:

1. Typed inspection results classify as `Confirmed`, `Contradicted`, `Unknown`, or `Failed`. Only the first two carry an action proposal. Unknown and failed replies produce an explicit no-action result.
2. Paid external operations persist intent, attempt, and outcome receipts around a stable request ID. The endpoint must honor that ID idempotently for a retry to avoid a second charge or side effect.
3. Candidate presentation receipts bind a task to the exact ordered sequence of action IDs and patch digests shown to an observer. `resolve_candidate_proposal` validates that receipt before mapping an observer proposal to an action; changed order, remapping, and unoffered IDs are rejected.
4. Producer ordinals restore a candidate list's construction order after transport permutation. The caller assigns each ordinal when it creates the action candidate, carries it with that candidate, and sorts by the ordinal before serializing the observer request. Ordinals are separate from opaque action IDs.

The fixed 64-byte inspection reply and variable-length candidate receipt are versioned zero-copy payload surfaces. Candidate receipt validation can inspect read-only mapped bytes without allocating. The append-only query journal uses a hash chain and durable flushes. Its guarantee is local replay plus stable-ID retry; exactly-once remote effects remain conditional on the endpoint contract.

Candidate presentation receipts preserve the producer's order. They do not claim that an arbitrary reordered candidate list is behaviorally equivalent, and they do not make a wrong proposal correct. The producer must create and persist the receipt before observer contact; the same receipt is checked before proposal authorization and during replay.

E006 remains unchanged and is recorded as source provenance in E007. The v1 crate is independently testable and is consumed by E007 through a local path dependency.
