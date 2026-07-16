# Frozen Model Selection Ledger v1

## Purpose

`phoenix-frozen-model-selection/v1` makes model selection and the single locked-test
execution immutable research facts. The ledger binds the complete candidate set,
validation aggregates, deterministic winner, held-out test result, and finalized
model identity. It does not train models or accept live graph state.

## Candidate authority

Selection opens every `phoenix-frozen-model/v1` candidate through mmap and requires:

- one exact dataset, tensor, topology, protocol, task, and seed-certificate chain;
- no candidate containing a test certificate;
- `selected_on_validation` and `test_locked_during_selection` on every receipt;
- exactly one model for every certified repeat in every configuration;
- canonical SIMD score, validation metric, and stored-certificate parity.

The configuration identity is BLAKE3 over source identity, architecture,
hyperparameters, runtime identity, training/optimizer receipt, and selection policy.
It deliberately excludes seed-specific weights, selected repeat, and certificates.
The ledger content-addresses the sorted candidate model IDs and their independently
content-addressed weight digests.

## Deterministic selection

For each complete configuration, v1 aggregates validation average precision and
Brier score across every certified seed. Aggregate floats are canonicalized through
their JSON representation before ledger identity hashing.

Configurations sort by:

1. highest mean validation average precision;
2. lowest mean validation Brier score;
3. lexicographically smallest configuration ID.

The representative seed inside the winning configuration uses the same metric order,
then the smallest model ID. No test value is available to this phase: the selection
API accepts only the validation set and returns an opaque selection token.

## Locked-test finalization

Finalization consumes that opaque token and atomically creates a content-addressed
test-access claim before scoring. A concurrent or restarted attempt for the same
candidate set fails closed before evaluating test. A crash leaves the claim in place
instead of silently spending the locked test again. The canonical SIMD scorer then
computes one test score stream and one test certificate. That certificate is appended
to a snapshot reconstructed from the selected mmap model.

Appending the certificate changes the model manifest ID but preserves the selected
weight BLAKE3. Weight files are named by their independent digest, so finalization in
the same artifact directory reuses the existing blob without copying its bytes. The
new files are the test-access claim, finalized manifest, and immutable selection
ledger.

The ledger records `lockedTestExecutions: 1`, selected validation model ID, finalized
model ID, preserved weight digest, test metrics, and test certificate. Its filename
is its BLAKE3 ledger ID. Restart loading recomputes that identity and validates the
filename, schema, one-shot count, test claim, test split, and manifest transition.

## Failure shields

V1 fails closed on an incomplete seed grid, duplicate repeats, source or seed drift,
test-touched candidates, missing or mismatched validation certificates, non-finite
or undefined selection metrics, metric/score drift, mutable artifact collisions,
renamed or edited ledgers, a repeated test count, and finalized weight drift.

## Verification gate

The focused suite proves complete-grid selection, deterministic winner and seed,
one-shot finalization, exact weight-blob reuse, restart ledger identity, incomplete
grid rejection, test leakage rejection, validation drift rejection, and a six-model,
4,000-row selection performance ceiling of two seconds.

The Windows MSVC release gate on the local Ryzen 7 5800X3D selected across those six
mmap models and 4,000 rows in 12.159 ms.
