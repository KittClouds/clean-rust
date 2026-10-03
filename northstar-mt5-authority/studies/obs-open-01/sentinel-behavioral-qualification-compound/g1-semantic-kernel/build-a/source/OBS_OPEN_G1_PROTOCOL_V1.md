# G1 - Sentinel Semantic Kernel Extraction

Original compound specification SHA-256:
`52291ca51de55031fad432abe401f5d4fe2a053ba2b94fa40e90b84c7b90d394`

This executable protocol incorporates the original G1 specification and the
oversight hardenings accepted by Northstar Prime.

## Lifecycle

Before execution:

```text
EXECUTION_STATE = NOT_STARTED
QUESTION_STATUS = OPEN
RESULT = NONE
DISPOSITION = NONE
```

Execution may transition through `RUNNING` to `SEALED`. `QUESTION_STATUS`
becomes `CLOSED` or `NOT_EVALUABLE` only after evidence exists. A disposition
is issued only after closure.

## Prime rule

**Do not improve the observer while extracting it.** G1 preserves every
authorized 04A causal distinction. It does not minimize, merge, redesign, or
reinterpret state.

## Oracle and projection

The sealed ancestor causal mechanism is the primary semantic oracle. Derived
04A metrology products are validation-only and may not drive `init`, `step`,
transition selection, state reconstruction, or missing-dependency substitution.

G1 is not required to copy the ancestor's storage layout. It must define an
authoritative projection `Pi_04A(K, O, C) -> A_04A` and prove ordered state and
emission trace equality:

```text
Pi_04A(Trace_G1(B_G0(D_A))) == Trace_04A(D_A)
```

Literal internal-field equality is required only where a one-to-one ancestor
mapping is earned.

## Kernel contract

```text
init(C) -> K0
step(Kt, Xt+1, C) -> (Kt+1, Ot+1)
```

Determinism is required only on the extracted semantic domain `D_G1`: states
produced by qualified initialization and admitted sequences, plus injected
states with an explicit ancestor-equivalent construction. G1 makes no claim
that arbitrary syntactically constructible states are reachable or meaningful.

All dependencies must be typed as prior kernel state, current admitted
observation, immutable authorized context, or within-step derivation. Explicit,
reproducible context already authorized by 04A/G0 remains compatible with
`EXACT_SEMANTIC_KERNEL_EXTRACTED`. Only newly required authority may yield
`SEMANTIC_KERNEL_EXTRACTED_WITH_ADDITIONAL_CONTEXT_AUTHORITY`.

## Firewalls and scope

Retrospective/metrology access is `VALIDATION_ONLY`. D_B, D_C, and D_D outcome
access is zero. Current canonical L2 is not admitted as a direct 04A input.
Source authority remains the G0-qualified 154-session, 57,500-bar US30 M1 D_A
surface with one-second source-time authority and nanosecond storage only.

```text
GENERALIZATION_AUTHORITY = NONE
INSTRUMENT_GENERALIZATION = NOT_EARNED
TIMEFRAME_GENERALIZATION = NOT_EARNED
SOURCE_GENERALIZATION = NOT_EARNED
```

Language neutrality is not population universality.

## Required proof

G1 requires stepwise projected state parity, exact ordered event/emission
parity, sequence-generated adversarial parity, input-authority rejection,
dependency closure, initialization closure, provenance, deterministic double
builds, and sealed artifacts. Historically `NOT_EVALUABLE` surfaces remain
typed `NOT_EVALUABLE`.

Successful extraction earns an explicit deterministic semantic kernel over the
qualified domain. It does not earn minimal state, necessary memory, formal
machine membership, reachability, behavioral equivalence, generalized source
authority, prediction, mechanism, economics, or trading authority.

