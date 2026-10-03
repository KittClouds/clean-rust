# BANK-v2 implementation plan (against the sealed v0.6 freeze)

Authority: `BANK-V2-FREEZE.md` v0.6, sha256 in `bank-v2-objects.sha256`. Code is authorized from that seal. Everything below is an implementation choice **inside** §1–§9. Anything that would change §1–§9 semantics is stopped and amended (v0.7) first, per §11.

## Principles

1. **Bound to the freeze.** `src/bank2/freeze.py` loads `bank-v2-objects.json`, re-hashes it against the sidecar at import, and exposes predicates, slots, reasons, gates and budgets from it. Code cannot drift from the constitution silently.
2. **Labels are derived, never sampled.** The generator picks a *scenario intent* (which algebra branch to build toward) to steer and stratify worlds. The label is then computed by the §6 algebra. If the derived branch differs from the intent the world is **regenerated, never relabeled** (§5.2).
3. **One evaluator.** `requirements.py` is the single source of truth for requirement objects, alternatives, satisfaction, repairs and the four counterfactual checks. The generator, the algebra and the gates all call it.
4. **Observation sufficiency.** When `M = ∅`, algebra steps 3–10 run twice, on the full state `S` and on the observed state (`Sup` plus closed-slot completeness). They must agree, otherwise the world is regenerated. This keeps "determinable from what the agent can observe" true. It is part of G03's re-derivation, not a new gate.
5. **Fail closed.** Every gate computes its predicate over data; none can be hardcoded.

## Choices the freeze left to implementation (recorded, none changes §1–§9)

- **Fact ids are content-derived** (`f_` + sha256 of predicate and args). The v1 sequential-id gap leak cannot recur. Entity ids are `e<ordinal>` with ordinals shuffled within each world (S1).
- **Timed facts.** A fact may carry `{valid_from, valid_to}`; it holds at tick `t` iff `valid_from ≤ t < valid_to`. Only `STATE` facts of exogenous devices are timed, so `WAIT` has real work (a gate that opens at tick *k*) and is `truth_optimal` somewhere. `BEFORE`/`AFTER` targets are derived from `valid_from`.
- **Movement gates** live in `transition_system.gates` (an edge that also requires a `STATE` value), not as a world predicate; `REQUIRES` stays forbidden in truth.
- **Reports.** `OBSERVATION.reports[]` carry claim facts with a channel and confidence. Reports are *derived* supported facts with a witness, so a hidden fact can be supported through a true report, and a false report can create `CONFLICTING_EVIDENCE`. A fact supported only through an uncertain report can trigger a `CONFIRM_UNCERTAIN` escalation (step 8).
- **The policy is declared in the rendered text** (what is requestable, what is denied, which escalation rules exist); otherwise `ASK` versus `DECLINE_UNAVAILABLE` could not be determined from what the agent sees.
- **`NO_VALID_ACTION` worlds omit `WAIT`** from `available_actions` (WAIT is otherwise always legal) and leave every other instance illegal.
- **Multi-alternative requirements** arise from diamond `REL` chains on a `required_slot` transitive relation (schema-scope asks) and from synthetic unit cases in the requirement-engine tests. `object_location` has one true chain per entity by the §1.7 closed-world rule.

## Stages, each with its own tests and a written receipt

| # | stage | module(s) | done when |
|---|---|---|---|
| 1 | schema, freeze binding, registries | `freeze`, `canon`, `facts`, `registry` | the registry table is split-scoped and validated (inverse scope, property-combination holdout, no lexical ids); every predicate has a slot |
| 2 | simulator and action algebra | `sim` | all nine actions have pre/effects; BFS with depth cap, exhaustive certificates, tie sets and a consulted-fact trace |
| 3 | requirement/support engine | `requirements` | ruling-C example, four counterfactual checks, repairs and requestability, all as property tests |
| 4 | algebra | `algebra` | every reason emitted by exactly one step; reason to disposition is a function; observation sufficiency |
| 5 | canonical world generation | `worldgen`, `lexicon` | every branch constructible; derived label equals intent; deterministic by seed |
| 6 | interventions | `interventions` | P1–P12 with the pair invariants (G10), P5 sharp, P11 null |
| 7 | renderers | `render` | 8 seen plus 4 held families; the policy, goal and reports appear in the text; mention spans verify |
| 8 | splits | `splits` | a structural predicate per split; collision-policy matrix (G09) |
| 9 | seal verifier | `gates` | G01–G18 computed over the generated bank |
| 10 | **pilot** | `build.py pilot` | ~4,000 worlds exercising **all nine actions, all five query scopes, every slot type, all five dispositions and every ASK cardinality branch**; all 18 gates pass; throughput measured |
| 11 | full generation | `build.py full` | post-dedup minimums met, `rendered_rows = 800,000`, deterministic across re-runs |
| 12 | seal | `build.py seal` | `BANK_v2_SEALED=true`, manifest with shard hashes, escrow tiers, `terminal_truth_opened=false` |

Nothing scales up until the pilot is clean on every gate and every coverage cell.

## Out of scope for this build

External adapters and challenge panels (O7, deferred); any model contact (`frozen_fabric_contact=false`); `TEST-RELATION-PROPERTY` (named, not scheduled); concurrency and asynchronous agents (challenge modes).
