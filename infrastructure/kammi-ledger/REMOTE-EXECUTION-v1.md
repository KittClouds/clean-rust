# Portable remote execution v1

The daemon signs canonical bundles with Ed25519. Workers pin the issuer public key;
the bundle cannot nominate a replacement trust anchor. A registered worker has its own
signing key and scoped credential. Bundles bind specifications, Git commit, clean-tree
policy, sealed inputs, environment, GPU/runtime requirements, seeds, command, outputs,
authorization, assigned worker and optional lease fence.

Workers receive declared input bytes, a limited process environment and disposable
input/output roots. They validate hashes/signature/environment/fence before execution.
Record RemoteWorkerStarted through the API before launch. Only exact declared outputs
are returned. Worker returns signed environment/execution receipt and stream/output hashes.

The daemon checks identity, signature, environment and outputs before acceptance.
Duplicates return the existing verified result; conflicting returns fail closed.
Acceptance does not promote a scientific result head.

Environment identity is a trusted worker's signed assertion, not hardware attestation.
The disposable worker is an isolation fixture, not a hostile-code sandbox or a proof
that the command cannot access unrelated files under its OS account.
