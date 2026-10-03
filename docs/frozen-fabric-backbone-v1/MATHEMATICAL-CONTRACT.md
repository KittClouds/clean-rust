# Operational mathematics and interfaces

This specifies the selected engineering construction. The definitions and proof sketches below are our design, not new experimental results or theorems attributed to the cited papers.

## 1. Domain, task and state

Define a finite task domain

\[
\mathcal D=(\mathcal T,\mathcal P,\mathcal R,\mathcal A,\mathcal M,\mathcal V,\mathcal I).
\]

Here `T` contains types, `P` typed predicates, `R` bounded-arity function-free signed rules, `A` primitive action schemas, `M` optional construction recipes, `V` provider contracts and `I` invariants. Each predicate declares argument roles, scope, temporal/revision applicability and an admission policy. Functional predicates additionally declare their unique-value key.

A task is

\[
\tau=(\mathcal D,g,E_\tau,\rho_0,B_0,\Gamma,\chi),
\]

with goal `g`, typed entities `E`, input resource revisions `rho`, budget `B`, applicable permission set `Gamma`, and output acceptance policy `chi` (validated-only or permitted best-effort/partial output).

Runtime state is

\[
S_t=(\tau,\rho_t,O_t,C_t,Z_t,W_t,H_t,J_t,B_t,Q_t).
\]

`O` is the observation ledger; `C` proposals; `Z` estimates; `W` warranted literals; `H` the obligation/plan graph; `J` justifications; `Q` pending/completed requests and attempts. There is no latent-world field. Source observations, model outputs and forecast states occupy different types.

A ground literal is a signed atom `ell=(sign,p,args,scope,validity)`. Exact entity identity is task/domain scoped. Proposed alias resolution is a separate candidate edge; it does not merge entities globally.

## 2. Evidence and conservative warrants

Represent an atom's support status by two bits:

\[
e(p)=(s^+(p),s^-(p))\in\{0,1\}^2.
\]

`00` is unobserved, `10` supported, `01` opposed and `11` conflicted. Missing evidence is not negative evidence. This uses the four-valued evidence distinction motivated by [Belnap](https://link.springer.com/chapter/10.1007/978-94-010-1161-7_2); the action policy below is our own conservative policy, not a claim to implement every connective of that logic.

An admitted observation records literal, source/range, source revision, provider contract, producer/bundle identity, validity, observed event and shared ancestry. Admission is domain-specific. Examples:

* A parsed authoritative manifest can establish a declared manifest field at that revision.
* A validator can establish its own check result for a specific artifact hash.
* An excerpt establishes what a source says, not that the world satisfies the excerpt.
* An estimate remains an estimate even when an action's policy allows using it.

Let `F_t` be currently valid verified premises, selected from `O_t`. For signed rules `r: body(r) -> head(r)`, derive the finite signed closure:

\[
D_0=F_t,\qquad
D_{k+1}=D_k\cup\{head(r):body(r)\subseteq D_k\},\quad
D=\bigcup_kD_k.
\]

Signed negation is explicit data; rules contain no negation-as-failure and no explosion rule. Let `K` contain atoms with both polarities in `D`, plus keyed alternatives violating declared uniqueness. Compute a second closure:

\[
W_0=\{\ell\in F_t:atom(\ell)\notin K\},
\]
\[
W_{k+1}=W_k\cup\{head(r):body(r)\subseteq W_k,
\ atom(head(r))\notin K\}.
\]

This is a deterministic, conservative engineering choice. A conflict derived through a tainted branch can withhold a conclusion that a richer defeasible logic might accept. That trade-off is explicit; it does not require designing a universal belief-revision system before the first build.

Use a premise-count work queue and reverse incidence lists. Once ground rules are registered, closure is linear in visited premise incidences per pass; entity grounding/join construction is a separate, potentially expensive operation. Ground only typed, goal-relevant tuples, enforce task limits, and report truncated grounding as incomplete.

Each warranted literal has at least one grounded justification. Store AND nodes for premises and OR alternatives for different derivations. Preserve shared source ancestry. Cyclic programs may produce cyclic dependency graphs; operational warrants retain finite grounded derivation witnesses, so cycles cannot support themselves. [Provenance semirings](https://www.cs.ucdavis.edu/~green/papers/pods07.pdf) supply the alternative-versus-joint lineage distinction; v1 uses compact dependency records rather than expanded provenance polynomials or probability products.

After a source changes, expire its old assertions and recompute the bounded closure. The dependency index identifies stale actions/checks and supports a later incremental implementation. This adopts the revision/dependency principle of [truth maintenance](https://dspace.mit.edu/entities/publication/e274a3b1-dcb7-4d62-abe7-a4b0db173191), not an assertion that we have reproduced Doyle's full system.

**Grounding invariant:** every literal in `W` has a finite derivation rooted in current admitted verified premises. Proof is induction over `W_k`. This establishes support under the domain/source contracts, not unconditional real-world truth.

## 3. Providers and typed estimates

A provider contract is

\[
v=(input,domain,outputs,scope,admission,completeness,cost,expiry,identity).
\]

Legal inputs satisfy `domain(v)`. Output types and allowable predicates are fixed. An exhaustive absence result requires both an exact scope and a procedure that declares completeness there. A partial search cannot certify absence.

The interface borrows the domain/output specification pattern from [PDDLStream](https://arxiv.org/html/1802.08705v5). Unlike immutable certified streams, our observations can expire and learned outputs can be uncertain. Only an actual verifier with the relevant contract emits `VERIFIED_RESULT`.

```rust
enum ProviderValue {
    Observation(Observation),
    Verified(VerifiedResult),
    Proposal(Proposal),
    Estimate(Estimate),
    CompleteEmpty(CompletenessWitness),
    Unknown(InsufficiencyReason),
    Unsupported(ApplicabilityReason),
    Failed(FailureReason),
}

struct Request {
    id: RequestId,
    task: TaskId,
    snapshot: SnapshotId,
    provider: ProviderId,
    obligation: ObligationId,
    arguments: SmallVec<[EntityId; 4]>,
    input_versions: VersionRange,
    budget: RequestBudget,
}
```

Every response carries the request and input identities. Cache key is `(provider identity, normalized arguments, input versions, output contract)`. Retry allowance is explicit. `UNKNOWN`, `UNSUPPORTED`, `FAILED` and `COMPLETE_EMPTY` are distinct outcomes.

R2a runtime count is `max(0,nearest_integer(raw))`, preserving the frozen artifact's exact rounding rule. Export raw only as diagnostic. Preserve target definition, representation, artifact hash, promotion scope and phenotype. A count estimate never discharges `NeedField(x)`, `At(object,location)` or another named requirement. Schema-derived blocker counts use their own observable provenance and coordinate names.

## 4. Actions, partial knowledge and plans

An action schema is

\[
a=(params,Pre_V,Pre_E,Add,Del,reads,writes,c,permission,executor,checks).
\]

`Pre_V` requires warranted verified literals. `Pre_E` contains explicit estimate-acceptance predicates: bundle/scope/value/support checks permitted by this action contract. An estimated-input action does not insert the estimate into `W`; it records that its construction depended on that estimate.

For the exact modeled fragment, a planning state `X` is a consistent set of signed literals. Preconditions must be explicitly present, including negative ones. Unknown literals are not assumed false. A modeled transition is

\[
T_a(X)=(X\setminus Del_a)\cup Add_a,
\]

with opposite literals removed as specified by the domain. Register actions with internally consistent effects and nonnegative integer costs. Compute derived predicates for each hypothetical state; do not carry stale derived literals across transitions.

This is a restricted action model. In the exact search fragment, `Pre_a` means `Pre_V(a)`. An estimated-input action is eligible only after its `Pre_E` guard passes on the currently available proposal/estimate records; those records are not turned into verified literals. A hypothetical future estimate cannot pass that guard. The search plan is a forecast, not an execution receipt. Execute one step, validate the observed result and replan; never insert all future modeled effects into operational state.

Use bounded uniform-cost search with stable ties and a visited-state cost table. `h=0` makes the initial implementation easy to audit. Under finite complete grounding, correct transitions, nonnegative costs and no resource limit, the first found goal has minimum modeled cost. In normal bounded operation, report `PLAN_FOUND`, `SEARCH_LIMIT`, `INCOMPLETE_MODEL` or `NO_PLAN_IN_COMPLETE_MODEL` distinctly.

For the positive delete-relaxed fragment, an optional heuristic is

\[
d(p)=\min_{a:p\in Add_a}\left(c(a)+\max_{q\in Pre_a}d(q)\right),
\quad d(p)=0\text{ when }p\in X,
\qquad h_{max}(G)=\max_{p\in G}d(p).
\]

Use an empty-premise maximum of zero. This is the max-relaxation construction in [Bonet and Geffner](https://www.cs.toronto.edu/~sheila/2542/s14/A1/bonetgeffner-heusearch-aij01.pdf). Its admissibility applies to the corresponding relaxed model; do not apply the theorem indiscriminately to estimated effects, request outcomes or numeric constraints.

Recipes expand compound tasks into ordered/partially ordered primitive steps. Initially they guide candidate ordering, with primitive search retained as fallback. We do not claim full HTN expressivity or completeness.

## 5. Obligations and repair

For a target literal `g`, incoming alternatives can be an existing warrant, a derivation rule, an action producing `g`, or a provider/check capable of establishing `g`. Each alternative contributes an AND set of prerequisites. The resulting graph is an AND/OR hypergraph.

For a consistent goal set `G`, regression through an action gives

\[
Reg_a(G)=(G\setminus Add_a)\cup Pre_a
\]

when `Del_a` does not destroy an unreplaced goal and the regressed set is consistent. Exact forward validation remains authoritative for candidate plans. Bound recursion and expansion; detect cycles. A loop without a grounded source or feasible primitive escape remains unresolved.

For a plan/recipe `pi`, collect its currently unresolved premise frontier `U(pi,S)`. Partition it:

```text
UNKNOWN_REQUESTABLE   a registered applicable provider could supply evidence
KNOWN_OPPOSITION      an opposite is warranted; may require a state-changing action
CONFLICTED            incompatible support; resolve/refresh the relevant sources
UNAVAILABLE           no applicable provider/transition is registered
BUDGET_BLOCKED        repair exists but exceeds the remaining budget
```

Opposition is not automatically ASK. If an object is known to be elsewhere, the repair is a move; if its location is unobserved, the repair may be a location query. Counts of missing premises do not determine which repair applies.

A repair recipe is a bounded set/sequence of calls and actions that could close the frontier. Provider success is conditional. An optimistic recipe may be used to choose the next query; it cannot be executed as though its hypothetical answers had arrived. In particular, invoking a validator does not have the deterministic effect `CheckPassed`: only an actual successful response supplies that premise. Search can plan to create the validator's inputs and expose the remaining check as a repair frontier.

Deduplicate shared requests and dependency nodes. A single checked input may discharge several needs. Evaluate complete candidate recipes when practical; independently choosing the cheapest provider for every node can miss sharing or incompatible alternatives.

Initial scheduling score is an engineering heuristic:

\[
priority(q)=\frac{\sum_{o\in U: q\ may\ repair\ o}w_o}
 {cost(q)+\lambda latency(q)+\epsilon}.
\]

Weights come from declared task priorities, not hidden labels. Begin with equal weights and fixed unit/declared costs. Apply only to applicable requests on a goal-relevant frontier. Stable ties and bounded retries prevent thrashing. No probability of success or optimal information-value theorem is implied.

A later expected-value policy would need

\[
VOI(q\mid S)=\mathbb E[V(Update(S,Y_q))\mid S]-V(S)-cost(q).
\]

The distribution of `Y_q` is an additional modeled assumption, not a neural confidence renamed as a probability. [Adaptive submodularity](https://arxiv.org/abs/1003.3967) offers greedy guarantees only under its assumptions; prerequisite complementarity and conflicts can break them. The initial loop does not depend on this machinery.

## 6. Execution and useful uncertainty

Define

\[
Permit(S,a)=Granted(\Gamma,a)\land Current(reads_a,\rho)
\land Invariants(S,a)\land Budget(B,a)
\land (Pre_V(a)\subseteq W)\land Accept_E(Pre_E(a),Z,C).
\]

The permit binds task, domain, action/payload, relevant input versions, supporting witnesses, estimate-use policy and idempotency key. The executor checks applicable resource versions atomically with the operation, or supplies a resource lease/isolation contract. A resource lacking either cannot claim race-free execution.

An execution receipt records actual outputs/effects, failed checks and resulting revisions. Predicted effects do not constitute success. A validator records the property it checked; it does not certify unrelated semantic quality. The design follows the proposal/check separation of [shielding](https://arxiv.org/abs/1708.08611), with immediate contracts rather than a synthesized temporal controller.

`BUILD_DRAFT` may be executable with an estimated binding. `RETURN_VALIDATED` requires the declared actual check set and emits that set as `validation_scope`; schema/arithmetic validation alone is not semantic validation of a guessed binding. If the task requires a verified mapping, that is a separate verified premise. `RETURN_PARTIAL` is a distinct successful disposition only if `chi` allows it. A useful artifact with unresolved semantics is therefore expressible without falsifying its validation status.

Runtime outcomes are `EXECUTE`, `REQUEST`, `WAIT`, `RETURN_VALIDATED`, `RETURN_PARTIAL`, `ESCALATE`, `DECLINE_UNAVAILABLE`, and `STOP_BUDGET`. A no-op/goal-already-satisfied disposition is separate from inability to make progress.

**Execution invariant:** checked prerequisites and permissions hold at the executor's declared revision boundary. This is conditional on domain correctness, admission policy and executor isolation; it does not prove the user intended the chosen task or that every semantic interpretation is correct.

**Progress bound:** cap requests, retries, grounding, search expansions and execution attempts. Each attempt consumes a positive attempt budget even when monetary cost is zero. Unchanged failed request/recipe keys are not retried without a new revision, alternative or remaining declared retry. Thus an episode terminates or yields within its declared budget; graph cycles cannot create unlimited free work.

## 7. Learned graph and observer boundaries

Exact graph operations consume typed premises. A learned provider consumes the visible task graph and a typed query, and emits candidates with source/argument references. Optional query-conditioned propagation has the form

\[
h_v^{k+1}=Agg(Indicator(v,q),\{Message(h_u^k,r,q):(u,r,v)\in E_{visible}\}).
\]

This uses the query-conditioned path pattern of [NBFNet](https://arxiv.org/abs/2106.06935). Bounded sparse neighborhoods and fused accumulation avoid a per-edge hidden-width message arena. Proposed relation scores remain proposed; type constraints reject impossible arguments, and actual provider/verifier contracts determine admission.

Pairwise context compatibility stays a directed, partial edge decision. `A~B` and `B~C` do not authorize `A~C`. No learned compatibility edge creates global entity/sense equivalence.

Bundle identity:

```text
backbone + tokenizer + serialization + surface + normalization
+ readout + output schema + calibration (if used) + applicability
```

A model adaptation creates a new bundle. A refitted head belongs to that new bundle; it does not retroactively repair an old artifact identity. Runtime model absence or unsupported input leaves exact providers and task execution usable.

## 8. Public kernel interfaces

```rust
fn admit(state: &TaskState, response: &ProviderResponse)
    -> Result<AdmissionDelta, ContractError>;
fn derive(state: &TaskState, scratch: &mut Scratch) -> WarrantView;
fn obligations(state: &TaskState, scratch: &mut Scratch) -> RepairView;
fn plan(state: &TaskState, limits: SearchLimits, scratch: &mut Scratch)
    -> PlanOutcome;
fn step(state: &TaskState, scratch: &mut Scratch) -> NextStep;
fn permit(state: &TaskState, action: &GroundAction) -> PermitOutcome;
fn apply_receipt(state: &mut TaskState, receipt: ExecutionReceipt)
    -> Result<RevisionDelta, ContractError>;
fn run(task: Task, providers: &mut ProviderRegistry, executor: &mut Executor)
    -> TaskOutcome;
```

Provider/executor dispatch occurs outside dense traversal. Replay consumes recorded responses and ordering, not new provider calls. Semantic identity excludes timing noise; performance receipts record timing separately. Source/argument scopes and artifact hashes are checked before borrowed/mmap access.

These interfaces are sufficient to build the first machine. Incremental closure, richer task methods, learned graph propagation and probabilistic scheduling can replace implementations behind them when an actual workload justifies the change.
