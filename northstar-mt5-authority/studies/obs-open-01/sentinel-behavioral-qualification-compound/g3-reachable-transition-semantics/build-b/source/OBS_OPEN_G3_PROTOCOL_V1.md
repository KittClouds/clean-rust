# G3 — Reachable Transition Semantics

Pre-execution lifecycle is `EXECUTION_STATE=NOT_STARTED`, `QUESTION_STATUS=OPEN`, `RESULT=NONE`, `DISPOSITION=NONE`. Closure is earned only by the sealed result.

## Primitive semantic objects

For each explicitly authorized immutable context `C`, G3 types separately:

- `K_reach(C)`: states reached by legal applied prefixes;
- `T_reach(C)`: state, input, applied/rejected result, next-state and ordered-emission tuples under that same context;
- `P_exec_G3(C)`: finite prefixes physically executable by the sealed G1 kernel.

The global view is the tagged union over `C_AUTH_G3`; context erasure or context stitching is forbidden. G5 comparison-continuation authority is not defined here.

## Authorized contexts

`C_AUTH_G3` contains sealed historically qualified G1 contexts and the finite declared synthetic contexts used by this gate. Constructed contexts require proven G1 kernel admissibility. Arbitrary schema-valid contexts are excluded. Synthetic witnesses earn machine-semantic reachability only, never historical market instantiation. Instrument, timeframe, and source generalization are not earned.

## Reachability sandwich

G3 maintains independently:

`K_minus(C) subset K_reach(C) subset K_plus(C)`

`T_minus(C) subset T_reach(C) subset T_plus(C)`

`P_exec_minus(C) subset P_exec_G3(C) subset P_exec_plus(C)`

Lower members require replayable witness prefixes. Upper envelopes are conjunctions of constraints derived from the sealed G1 kernel and may include impossible members, but must not exclude reachable G1 behavior. Exactness means equality of semantic denotations, never serialized artifact equality.

Input-language, prefix-language, state-reachability, and transition-reachability authority are independently typed. Search failure never proves unreachability.

## Applied and rejected steps

The semantic codomain is `APPLIED(next_state, ordered_emissions) | REJECTED(reason)`. Local schema validity, individual input authority, and applicability from a particular `(K,C)` are distinct. Rejected attempts do not extend an applied executable prefix.

## Firewalls and nonclaims

G3 consumes sealed G1/G2 semantics. It does not replay D_A and reads no outcome population. D_B, D_C, and D_D accesses are zero. Grammar remains `NOT_EVALUABLE`. G3 earns no redundancy, removability, minimality, behavioral equivalence, prediction, mechanism, economic, or trading authority.
