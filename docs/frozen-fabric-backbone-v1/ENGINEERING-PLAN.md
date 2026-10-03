# Frozen Fabric / System 1.5: backbone construction v1

Date: 2026-10-01. Status: engineering design ready for implementation.

## 1. Decision and target

Build **a domain-neutral, task-local operational kernel with frozen semantic providers**. The kernel represents observations, resolves declared obligations, plans bounded action sequences, requests missing inputs, and checks actions against the domain's execution contract. Frozen representations supply proposals and estimates through replaceable interfaces.

This is the Frozen Fabric / System 1.5 engineering program. Its first implementation has no dependency on Phoenix's graph system, stores, action ontology, retrieval stack, or promotion machinery. Phoenix could later implement an adapter, as could another application. The earlier [backbone draft](../backbone-engineering-v1/ENGINEERING-PLAN.md) is preserved; this plan supersedes its Phoenix-centered implementation choice.

The first machine is a **Fabric Workbench**: given a typed task, inputs, output requirements, available tools and a budget, produce and validate an artifact in a local task sandbox. It can repair missing dependencies, choose among permitted construction recipes, execute registered tools, inspect their outcomes, and return a usable partial artifact when the task permits it. It does not need to infer a universal action policy before doing useful work.

The first user-visible target is:

```text
task + available inputs + declared requirements
    -> executable construction plan
    -> acquire concrete missing input if needed
    -> build a candidate artifact
    -> run its declared checks
    -> return artifact, actual check results, and unresolved requirements
```

A standalone library and command-line runner will live at `rust-native/frozen-fabric-backbone/`. Domain definitions and provider implementations are separate modules. The reference domain creates a structured report from versioned JSON/CSV inputs; the same kernel also runs a small relocation/activation fixture to test state-changing planning. Neither fixture reads BANK truth.

## 2. What the measurements buy us

The local record constrains construction; it does not certify this new assembly.

| Local finding | Construction consequence | What it does not establish |
| --- | --- | --- |
| Rung 0 surfaces allocate capabilities differently. | Keep task-specific observer bundles; use the four earned live surfaces. | A universal embedding or universal controller. |
| Specialization often invalidates old heads while same-family refits recover capability. | Bundle backbone, tokenizer, serialization, surface, scaler and head together. | Heads are detachable or specialization preserves coordinates. |
| Graph-local edge ranking survives several perturbations. | An edge provider is useful as a candidate/ranking service. | Its score is a transportable authorization probability. |
| C0's typed deterministic controller is executable and replayable. | Reuse the interface lesson and implement known combinatorics directly. | C1's learned policy solves general action selection. |
| C1-C4 produce limited useful action coverage; surface/risk fixes did not unlock the policy. | Use authored action semantics and task search rather than another generic policy-head sweep. | Action learning is impossible. |
| X0 makes composition executable under materialized facts; X1 and X6 do not earn generic graph arbitration/acquisition superiority. | Give the graph explicit dependency, planning, sharing and invalidation jobs. | Topology alone supplies reliable semantics or optimal information value. |
| R2a emits operational estimates, including a narrowly scoped missing-fact count. | Estimates can prioritize work; named blockers come from the actual domain graph. | A count identifies the missing fact or makes it available. |
| VCS-0's corrected reconstruction is mixed; VCS-1b is unearned. | Region geometry is an optional consumer of operational coordinates. | Geometry is a required runtime controller or VCS-1b has been earned. |

These conclusions are recovered from [FF-S15 status](../../experiments/ff-s15-STATUS.md), [VCS-0 status](../../experiments/vcs-0/STATUS.md), its [correction](../../experiments/vcs-0/CORRECTION-2026-09-30.md), and the specialization/masking/R2a results supplied in the thread. H2 remains closed. Existing experiment locks and dispositions remain unchanged.

## 3. Deferred ideas, now assigned a construction role

| Idea recovered from the thread/designs | Concrete role now | Initial implementation |
| --- | --- | --- |
| Typed observer cartridges and a latent ABI | Frozen semantic provider with explicit scope and output types | Bundle loader + deterministic inference/export adapter |
| System 1.5 between quick readout and expensive deliberation | Cheap proposal followed by bounded graph computation | One task loop; invoke a provider only for a named need |
| Operational rather than oracle coordinates | State fields derive from actual inputs, observations, receipts or attached estimators | Separate fact, candidate and estimate stores |
| Goal-path deficiency and repair | An AND/OR obligation graph names alternatives and prerequisites | Goal regression + bounded repair recipes |
| Multi-provider materialization | Compatible observations, proposed bindings and shared ancestry | Admission policy per predicate; no vote-count truth shortcut |
| Acquisition / ASK | A provider request for a typed obligation | Cheapest applicable repair first; explicit retries and cost |
| Graph-local capability | Nominate bindings/edges in the current task graph | Existing frozen edge readout where its input contract applies |
| Directed lexical compatibility | Optional retrieval/nomination provider | Edge-local ALLOW/REFUSE/ABSTAIN; no transitive closure |
| Capacity/readout ladder | An interface implementation choice when needed | Existing linear readout first; no width or surface census |
| Representation rotation | Artifact compatibility/lifecycle problem | Reject mismatched bundles; preserve a known working bundle |
| Region control surfaces | Optional scheduling/decision annotation | Not required for the first executable loop |
| Query-conditioned graph propagation | A future learned nomination implementation | NBFNet-style provider behind the same candidate interface |

This recovers useful ideas without importing Phoenix's training tickets or JEV's characterization agenda. Their historical experiment conditions continue to govern those experiments, not this separately scoped construction.

## 4. Literature we can use directly

The source register in [SOURCES.md](SOURCES.md) records the primary papers and the assumptions we adopt. We use established operations without making their empirical replication a build dependency.

* **Planning:** explicit operators and bounded state search; optional domain-authored recipes. [Planning as heuristic search](https://www.cs.toronto.edu/~sheila/2542/s14/A1/bonetgeffner-heusearch-aij01.pdf) supplies a path to admissible relaxation heuristics. [SHOP2](https://www.cs.umd.edu/~nau/papers/nau2003shop2.pdf) supplies the task-decomposition pattern when a domain already knows useful procedures.
* **External procedures:** [PDDLStream](https://arxiv.org/html/1802.08705v5) gives a useful separation between a procedure's implementation, legal inputs and certified outputs. We adopt that interface pattern. Approximate model outputs and changing observations do not inherit the paper's immutable certified-fact assumptions.
* **Changing evidence:** [truth maintenance](https://dspace.mit.edu/entities/publication/e274a3b1-dcb7-4d62-abe7-a4b0db173191) and [provenance semirings](https://www.cs.ucdavis.edu/~green/papers/pods07.pdf) motivate dependency-directed revision and preserving alternative derivations.
* **Proposal versus execution:** [shielding](https://arxiv.org/abs/1708.08611) separates a proposed action from a specification-based check. Our first checker enforces immediate declared action contracts; it is not a synthesized temporal-game shield.
* **Language and tools:** [LLM+P](https://arxiv.org/abs/2304.11477) separates language interpretation from planning; [SayCan](https://arxiv.org/abs/2204.01691) separates task relevance from skill feasibility. We borrow those separations without assuming their models, calibration or embodiment transfer to the 230M.

The custom work is the composition: versioned provider contracts, typed uncertainty, obligation repair, the observer ABI, and a compact operational graph that connects them.

## 5. Machine structure

```text
request + domain + tools + budget
            |
            v
typed task / candidate bindings <--- frozen semantic providers
            |
            v
operational state <--- actual observations / tool receipts
            |
            v
dependency + obligation graph
            |
      +-----+----------------+
      |                      |
      v                      v
ready action             named missing requirement
      |                      |
      v                      v
action contract check    acquire / inspect / request
      |                      |
      v                      |
registered executor ---------+
      |
      v
actual outcome -> state revision -> next step
```

The mathematical specification is in [MATHEMATICAL-CONTRACT.md](MATHEMATICAL-CONTRACT.md). The essential separation is between three planes:

1. **Observed plane:** versioned sources, explicit assertions and verified tool outcomes.
2. **Proposed plane:** bindings, semantic relations, estimates and forecast plans.
3. **Executable plane:** an action whose declared admission, resource and permission checks currently pass.

The kernel does not have a hidden `truth` plane. It does not equate a provider score with a fact or a predicted effect with an observed effect.

### Domain and task contracts

A domain declares types, predicates, derivation rules, action schemas, goal checks, invariants, recipes and providers. A task binds a domain to concrete entities, input revisions, goal, budget and already applicable permissions. The same library supports different domains through these declarations.

The reference domain's predicates include `InputAtRevision`, `HasField`, `CandidateBuilt`, `SchemaValid`, `ChecksPassed`, `OutputMaterialized` and `RequirementUnresolved`. Verified predicates have actual source/check witnesses. `LikelyRelevantColumn` or `ProposedBinding` remain model outputs.

Each action specifies which premises require verified support and which, if any, may use an explicitly accepted estimate. `BUILD_DRAFT` may accept a guessed column mapping under a task's best-effort policy. `RETURN_VALIDATED` requires the actual validators to pass. Uncertainty therefore permits useful construction without being renamed certainty.

### Provider contracts

The minimum provider response distinguishes:

```text
OBSERVATION       asserted under a declared source contract
VERIFIED_RESULT   independently checked predicate/output
PROPOSAL          binding, relation, candidate or recipe nomination
ESTIMATE          numeric/typed estimate with artifact identity
COMPLETE_EMPTY    exhaustive empty result for an exact declared scope
UNKNOWN           attempted, local evidence insufficient
UNSUPPORTED       outside the provider's input/task applicability
FAILED            timeout, error or resource failure
```

Each response binds its request, input revisions, provider/bundle identity, scope and ancestry. `COMPLETE_EMPTY` is not inferred from a top-k search returning no result. A provider may establish only predicates granted by its registered contract. Even a sound procedure cannot establish an unrelated property: byte integrity does not establish semantic correctness.

### Frozen fabric interface

```text
infer(bundle_id, typed_query, visible_input, candidate_bound)
    -> proposals / scores / estimates / applicability status
```

Use only validated interfaces: `middle_plus_final`, `final_plus_mean`, `layer_m4_final`, `full_mean`, and earned task-specific local vectors. Causal `first_token` remains a degenerate control and is never an operational input. No new surface sweep is part of implementation.

The operational bundle binds backbone revision, tokenizer, serialization, extraction definition, normalization, readout, output schema and applicability. An available provider is invoked only when the task needs its output. GPU extraction is batched across ready requests; cached representations are keyed by the full bundle/input identity.

R2a retains `estimate.n_evidence_facts` and `estimate.n_missing_facts`, `MODEL_ESTIMATE`, and artifact-dependent availability. Raw regression remains diagnostic. `truth.*` remains `ORACLE_TRUTH / UNAVAILABLE`. The 0/1 BANK-v1 scope of `n_missing_facts` remains attached. Arbitrary Workbench text is not silently brought into that estimator's scope.

## 6. The graph's concrete job

Use a task-local typed **hypergraph**, not just an entity-link store. Nodes include literals, artifacts, actions, provider requests and obligations. Hyperedges represent an AND dependency; multiple incoming alternatives represent OR. Keep arguments, statement qualifiers and source/version scope explicit.

It does six operational jobs:

1. Bind an instruction to typed entities and candidate actions.
2. Derive warranted consequences from admitted observations.
3. Compose feasible action sequences, including prerequisites and deletions.
4. Name repair alternatives for a blocked goal.
5. Share one acquisition/check across several requirements.
6. Invalidate dependent consequences and action permits after a revision changes.

A normal pairwise graph is insufficient for conjunctions: `CompilePassed` and `SchemaValid` together may be required for `Ready`. Simple reachability would permit `Ready` after finding only one premise. Hyperedges preserve that distinction.

There are two separate graph computations. The exact dependency graph decides what a declared rule or recipe requires. A learned graph provider ranks plausible bindings or relationships for investigation. Its proposed edges do not automatically become premises of exact planning.

For a future learned front, the default candidate is **query-conditioned NBFNet-style path propagation**, because the operational request is about a particular source/relation/goal rather than an all-purpose embedding. [NBFNet](https://arxiv.org/abs/2106.06935) supplies that pattern; it does not turn a learned path score into a proof. Start with existing readouts and deterministic typed candidate generation. New GNN training is not a critical-path dependency.

The recovered [CompGCN](https://arxiv.org/abs/1911.03082), [StarE](https://aclanthology.org/2020.emnlp-main.596/) and [ULTRA](https://arxiv.org/abs/2310.04562) offer alternatives if the actual requirements become reusable entity/relation encoding, qualifier-aware statements or transfer across relation vocabularies. They remain construction options, independent of Phoenix's model ladder.

## 7. Choose the first construction

| Construction | Advantage | Cost/assumption | Disposition |
| --- | --- | --- | --- |
| Another end-to-end action classifier | Minimal runtime orchestration | Must learn dependencies, sufficiency and tool applicability together | Candidate proposer only |
| Full probabilistic belief-state planner | Represents contingent outcomes and expected utility | Needs transition/observation models; much larger state space | Use when a concrete stochastic domain needs it |
| Full HTN engine | Strong authored procedure guidance | Methods can restrict reachable solutions; substantial authoring | Add small recipes now; no full HTN implementation initially |
| Neural graph backbone first | Flexible candidate composition | Training/staging cost; scores still need contracts | Replaceable front-end option |
| Typed state + obligations + bounded classical search | Transparent construction path with repair and executable tools | Requires explicit domain schemas and source contracts | **Selected** |

The first version uses finite, typed rules; bounded uniform-cost search over declared actions; domain-authored construction recipes; and lazy provider requests. It checks one step, executes it, ingests the actual outcome, and replans. Start with a zero search heuristic. Introduce `h_max` when search effort warrants it, rather than solving heuristic learning first.

Acquisition initially uses applicable provider cost and goal-relevant blocker coverage, with stable tie-breaking and bounded retries. This is an engineering scheduling heuristic. We do not claim adaptive-submodular guarantees: complementary prerequisites can violate the assumptions in [adaptive submodularity](https://arxiv.org/abs/1003.3967).

## 8. A complete first task

Request: “Build a report with the required totals and a short explanation from these input files; return the validated artifact if checks pass, otherwise return the draft and the missing requirements.” The task supplies the output schema and sandbox scope. It authorizes local draft construction and the registered validators.

The initial domain is small and explicit:

| Operation | Required inputs | Actual result |
| --- | --- | --- |
| `SnapshotInput` | Declared readable input in scope | Immutable bytes, hash and observed fields |
| `ResolveBinding` | Required field and observed candidate columns | Exact binding or typed proposals; may remain unresolved |
| `FetchInput` | Named missing input with a registered provider | New source, complete-empty, unknown or failure |
| `BuildReport` | Snapshotted numeric inputs and an accepted mapping | Candidate JSON report and explanatory template text |
| `CheckSchema` | Candidate plus output schema | Actual pass/fail for structure and types |
| `CheckArithmetic` | Candidate, frozen input rows and any declared control totals | Actual pass/fail for computation and stated cross-checks |
| `ReturnArtifact` | Candidate and the task's acceptance policy | Validated-with-scope or partial-with-unresolved-needs |

Input snapshots become immutable task artifacts, so computation reads the exact observed bytes even if an external path later changes. Validators are outcome-bearing providers: running a check does not have a modeled effect of “pass.” A construction recipe remains conditional until those actual results arrive. A wrong mapping is detectable only by checks that bear on it; schema/arithmetic success alone does not prove the mapping's meaning. The output names its validation scope.

1. `SnapshotInput` returns file identities, revisions and observed fields. A frozen semantic provider may propose which source column maps to a required output field.
2. The graph expands `ReportReady` into `CandidateBuilt AND SchemaValid AND RequiredChecksPassed`. A recipe exposes `ReadInput`, `BindColumns`, `Aggregate`, `Render` and `Validate`.
3. An unresolved mapping produces `NeedBinding(required_field)`. Exact name/type matches are tried first. If none exist, the semantic provider supplies ranked alternatives. Under best-effort draft permission a candidate mapping may be used, with its estimate provenance retained.
4. One missing input has a registered local lookup provider. The engine requests it and records its actual response. An unavailable input stays unresolved; no review packet is created.
5. The runner materializes a draft and runs schema, arithmetic and reference checks. A predicted pass never substitutes for their actual receipts.
6. A failed arithmetic check repairs the construction recipe or tries the next permitted binding. A missing required source causes the task to return its draft with that requirement unresolved if the task permits partial output.
7. A successful check set yields the validated output. A change to an input revision invalidates the dependent checks; only affected work is logically stale, even if the initial implementation recomputes the small task closure.

The vertical slice is complete when it handles ordinary success, a repairable missing input, a guessed mapping caught by a validator, a source conflict, a stale revision, an unavailable provider and a useful partial result. It should not spend every uncertain task abstaining before attempting draft construction.

## 9. Modules, dependencies and implementation order

| Slice | Modules / concrete output | Dependency | Done means |
| --- | --- | --- | --- |
| S0 | `ids`, `domain`, `envelope`, `bundle`, `budget` | This plan | Typed contracts compile; fixtures round-trip; invalid scopes/types are rejected |
| S1 | `state`, `admission`, `closure`, `justification` | S0 | Explicit support/conflict/retraction and alternative support work against a reference interpreter |
| S2 | `obligation`, `planner`, `recipe` | S1 | Actual plans and named repair frontiers; tiny exact-reference agreement |
| S3 | `provider`, `scheduler`, `executor`, `journal` | S2 | Bounded request/build/check/replan loop, idempotent outcomes and replay |
| S4 | Workbench CLI + local file/check providers | S3 | The complete report task above produces real files and a useful partial output |
| S5 | One existing frozen observer bundle adapter | S0/S3 | Model output contributes to an actual task; unsupported inputs are explicit; no new atlas run |
| S6 | Candidate graph nomination adapter | S4, actual nomination need | Adds useful candidates through the same contract; does not replace the state kernel |

S0-S4 are the first implementation ticket. S5 can be integrated as soon as the inference interface is ready; it does not require completing another characterization lane. The first version can replay recorded provider responses and use programmatic/synthetic fixtures while that adapter is wired.

The Rust package is independent of the Phoenix workspaces. Choose `hashbrown`, `smallvec`, `bumpalo`, packed `Vec<u64>` membership sets, `memmap2`, `memchr`, `zerocopy` for validated immutable layouts, `serde`/`serde_json` for control contracts, and `blake3` for new local artifacts. Preserve historical SHA-256 identities at existing bundle boundaries. `rayon` and `crossbeam-channel` serve independent batches and bounded owned-stage messages; no per-edge locking. Use `criterion`, `proptest` and optional `dhat` for construction verification and measurement. Resolve compatible crate versions into the package lockfile at implementation, rather than inventing version pins here. The tensor runtime sits in a provider process/adapter, not in the planning core. Use the existing inference implementation where available; selecting a new tensor framework is not a prerequisite.

Store task-local IDs in `u32`, dense records in `Vec`/`Box<[T]>`, adjacency in offsets plus contiguous edge arrays, and source text in borrowed immutable ranges. Reuse scratch allocation across closure/search cycles. Intern/index during construction, then publish sorted immutable views. Use SIMD-backed `memchr` parsing, packed set operations and existing numeric kernels where applicable, with scalar parity. No allocation, logging or virtual dispatch inside graph traversal.

Files should remain below approximately 800 lines. Source and runtime artifacts stay on `C:\codex-runs\frozen-fabric-backbone-v1`, on the verified C: NVMe; D: is USB. The separate compile-target convention remains `:G` with a C: test-executable link. Resolve that alias explicitly in the build script; an operational cache must not follow it onto USB. No historical artifacts are moved.

## 10. Validation is construction work

Start with meaningful unit/reference tests, then smoke and performance tests:

* Signed closure and warranted closure against a simple finite reference interpreter; contradictions never cause arbitrary derivation.
* Rule cycles cannot create support without a source; retracting one support preserves another clean alternative.
* AND prerequisites, alternative recipes, destructive effects, impossible goals and bounded-search exhaustion against tiny exhaustive planning.
* Explicit negative versus incomplete query, complete-empty scope, provider timeout, stale applicability and retry exhaustion.
* A draft based on an estimated mapping can be built, but cannot be declared validated without its actual checks.
* Permit scope, read versions, idempotent retry and executor revision check through real sandbox operations.
* Recorded-response replay produces identical decisions and semantic receipts; remote/GPU response reproducibility is not assumed.
* Criterion kernel benchmarks and allocation profiling; separate parsing, inference, closure, search, I/O and checking costs.

Initial performance budgets: 10 ms warm control-plane p95 on a representative 10k-literal/20k-grounded-rule slice; 64 MiB task working memory excluding model/source residency; zero allocation per traversed edge. These are engineering budgets to profile against, not measured results or promotion gates. Smaller first fixtures should not be inflated merely to hit these sizes.

Primary utility is task completion, useful partial completion, correction after failed checks, tool/model cost and latency. Compare with the same workflow using fixed recipes and no semantic provider. Source integrity, operational contract compliance and semantic output quality are separate measurements.

## 11. Remaining questions with executable defaults

| Question | Default that permits implementation | When a new experiment changes a decision |
| --- | --- | --- |
| Does the frozen front improve field/entity binding? | Exact/type match first; model proposes alternatives for drafts | Matched task replay determines whether to retain the provider or use a simpler matcher |
| Does learned edge nomination add useful options? | Deterministic typed candidate set remains available | A fixed task workload determines whether the new candidate provider earns its inference cost |
| Is the request scheduler wasteful on shared/alternative obligations? | Cheapest applicable repair with deduplication | Small exact contingent examples determine whether to add outcome-aware scheduling |
| Does closure recomputation dominate under source churn? | Recompute the bounded task closure | Measured churn/cost determines whether to implement incremental truth maintenance |
| Are authored recipes too restrictive? | Recipes guide ordering; primitive action search remains available | A real unexpressible task justifies extending the domain or adding richer HTN constructs |
| Can a semantic estimate authorize a particular low-impact action? | Action contract explicitly permits estimated inputs only where consequences/checks are bounded | Actual errors determine whether to tighten that contract; no universal semantic threshold is required |

Every proposed experiment must name a construction choice it could reverse. Broad head masking, surface/seed sweeps, a new review campaign and internal-model explanation are outside this implementation ticket.

## 12. Next executable deliverable

Implement S0-S4 in `rust-native/frozen-fabric-backbone/`, with the Workbench domain, two provider alternatives, actual draft generation, validators, missing-input repair, partial output and recorded-event replay. Expose `run(task)` and `step(snapshot)` as the integration points.

The machine should make its first useful artifact before any new backbone training. Then integrate one compatible frozen observer bundle and improve concrete failures. The next dependency is executable code, not another experimental gate.
