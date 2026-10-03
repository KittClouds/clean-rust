# E4-1: Surface Survival and Substrate Value

**Identity:** `FAS_FROZEN_CAPABILITY_FABRIC_E4_1_PLAN_V01`  
**Status:** design only; not sealed; not authorized for construction, fitting, model contact, evaluation, or scoring  
**Created:** 2026-09-27  
**Parent:** pinned [E4 codebase map v01](E4-CODEBASE-MAP-v01.md) and its proposal source  
**Purpose:** define the engineering fork-selection stage that follows a terminal E4-0 result.

This plan records the intended question and stage boundaries. It does not revise the pinned E4 map, authorize E4-0, grant entry to E4-1, or freeze numeric gates. The E4-0 v16-v09 contract seal is a contract seal only; its authorization fields remain false. E4-0 has no terminal result in the current workspace state.

## Mission

E4-1 selects which implementation path from E4-0 is worth carrying forward. It asks:

1. Does the selected machine remain useful across required surface variation?
2. Does the frozen pretrained representation earn its cost compared with cheaper or from-scratch sources?

E4-1 produces an engineering route decision. It does not explain a mechanism. Any unexplained result is recorded as a `SCIENCE_HANDOFF_CANDIDATE` for the appropriate science lab.

```text
selection evidence != mechanistic evidence
```

Keep the measured utility vector intact:

```text
U = (performance, surface survival, fit cost, inference cost, memory, latency)
```

Do not collapse this vector into one score.

## Current entry state

| Requirement | Current state |
| --- | --- |
| E4-0 contract identity | v16-v09 sealed; seal root `278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1` |
| E4-0 execution authorization | Closed in the contract; population generation, tokenizer/model contact, feature extraction, label opening, scoring, fitting, and E4-A are unauthorized |
| E4-0 terminal disposition | Not present in the current workspace; the contract seal is not an E4-0 outcome |
| Chief Kammi Chain of Custody | Architecture v1 is locked at `C:\code land\clean-rust\program-infrastructure\kammi-ledger\ARCHITECTURE-v1.md`, SHA-256 `c9e9d5bb54ee863ce99760ee26c0f0e912b952ff3e8a3b502cc23f2d78eb3524`. Lock receipt `C:\code land\clean-rust\program-infrastructure\kammi-ledger\ARCHITECTURE-LOCK-v1.json` has SHA-256 `94bcba258bd3658ccda3d917aaedf75aaf2a228edf8e9fda23f37159a9ccd364`. The receipt records `acceptance_status=NOT_RUN`, independent legacy-fixture closure `PENDING`, and `new_flight_gate=CLOSED_PENDING_ACCEPTANCE`. Initial daemon and fixture-verification work is reported underway; that report is not an acceptance receipt. |
| E4-1 eligibility | Closed |

The current sealed E4-0 contract binds these predecessor roots: E0 v10 `899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd`, E1 v04 `6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03`, E2 v07 `a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a`, and E3 v02 bundle `899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1`. The E3 score replay root is `a104bffedbc3e31268c0f1c0103ad4326add5a9da93816007904b70cdf3c7d1f`.

Exact current contract identity: `contracts/e4-0-contract-v16-v09-final.json`, SHA-256 `21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f`. Its seal manifest is `seals/e4-0-contract-v16-v09-seal.json`, SHA-256 `0635de4a384b4d5121d8b2295e88a73f649c53e402ffcda311fcaf9c8d93099c`, root `278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1`. Chain of Custody must register the exact artifacts and roots, not only these summary values.

If E4-0 ends without a viable machine, E4-1 does not run. Do not create a rescue experiment under this identity.

## Entry gate

E4-1 becomes eligible only after every condition below has a bound artifact and an independent review:

1. E4-0 has a terminal, sealed disposition.
2. That disposition identifies at least one capability worth carrying forward and says which exact head or operation is eligible. Do not infer eligibility from partial metrics or reinterpret a failed bundle gate.
3. The E4-0 representation, fitted interface recipe, population identities, operational metrics, and eligible capability list are frozen by exact hashes.
4. Chief Kammi's Chain of Custody has an explicit later acceptance receipt bound to the locked architecture and lock-receipt identities above. The lock receipt alone is not acceptance. The acceptance must pass implementation and independent closure verification of the registered legacy fixture: E4-0 v16-v09 contract SHA-256 `21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f`, seal-file SHA-256 `0635de4a384b4d5121d8b2295e88a73f649c53e402ffcda311fcaf9c8d93099c`, root `278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1`, and exact 447/447 entry closure. The receipt must explicitly open the new-flight gate.
5. The accepted custody subsystem has registered the inherited E4-0 artifacts, their owners, roots, access history, and exposure state.
6. The E4-1 population and its development/evaluation boundary can be created without using E4-0 terminal evaluation outcomes to select candidates.
7. A versioned E4-1 contract fixes source identities, task definitions, truth partitions, numeric gates, resources, selection rules, and stop conditions before E4-1 population contact.

Entry readiness, contract sealing, population construction, feature extraction, fitting, and evaluation are separate authorization boundaries. Passing one does not authorize the next. Keep E4-1 unopened until the later explicit Kammi Ledger acceptance receipt passes and opens the new-flight gate.

## Track T — Surface Survival

**Question:** Does the selected E4-0 machine remain usable when the same underlying task is rendered through prospectively defined surface forms?

This track absorbs the earlier `TEMPLATE-01` question into E4-1. It is a test of usable transfer outside the discovery wrapper, not a claim of general invariance. Existing E4-0 template/joint truth remains under its current escrow and custody until an E4-1 contract explicitly registers any permitted handoff. E4-1 will also construct the fresh population required by its own contract; it will not spend E4-0 terminal evaluation outcomes during candidate selection.

### Population and strata

Construct fresh latent task instances and render paired surface arms where possible. Preserve the underlying task semantics while varying prospectively registered dimensions, including:

- same or seen rendering with fresh instances;
- unseen templates;
- lexical substitutions;
- syntactic changes and altered wording or slot order;
- irrelevant surface material;
- template-plus-lexical combinations.

Use E4-0's terminal result to decide which strata are meaningful. The later E4-1 contract must define exact strata, paired latent IDs, transformation rules, row/quartet identity, and overlap checks. Do not assume E1's historical `HELDOUT` role text is a true template holdout; the pinned codebase map records that E1 templates crossed FIT and TEST.

### Interface boundary

The primary Track T evaluation uses the exact E4-0 selected representation and interface, unchanged. No layer, pooling, prompt, head family, or threshold search is allowed on evaluation data.

If the frozen machine misses its surface or source requirement, one bounded discovery budget may test a small, fixed menu of inexpensive alternatives on development data. Freeze the menu, per-source candidate budget, fitting budget, selection rule, and tie-breaks after E4-0 closes and before E4-1 evaluation contact. Such alternatives are new candidates; they do not replace or rewrite the primary frozen-machine result.

### Track T report

For each E4-0-eligible capability and surface stratum, report the registered operational performance metric and denominator, absolute and relative degradation from the E4-0 reference, failure rate, fit/inference cost, memory, and latency. Keep strata separate.

Disposition per capability:

- `SURFACE_PASS`: meets every prospectively required surface floor.
- `SURFACE_BOUNDARY`: remains useful only in a prospectively describable subset of the rendering region.
- `SURFACE_FAIL`: fails a required surface floor for intended use.

These labels describe surface behavior; the final route decision also considers source cost and capability requirements.

## Track S — SOURCE-LADDER

**Question:** Given the same task information and a comparable interface budget, which feature source is worth using?

The source ladder is an engineering comparison, not mechanistic attribution:

1. **LEXICAL:** inexpensive features visible in the task text.
2. **TOKEN:** token embeddings or another prospectively declared low-cost pretrained surface representation.
3. **RANDOM:** the declared substrate architecture with random weights, where feasible.
4. **PRETRAINED:** the exact frozen representation selected by E4-0.
5. **FROM-SCRATCH:** an operation-matched model trained from scratch under a declared data and compute budget.

For each source, bind implementation and weight identities, preprocessing, fit recipe, resource measurement, and any source-specific limitations. The later contract must say what “matched” means for each comparison. Hold constant where applicable: task population and labels, development/evaluation identities, interface family and width, fitting budget, candidate selection procedure, and scoring implementation. Require decision fairness; do not force byte-identical parity where a source makes that nonsensical.

Infeasible or over-budget sources are reported as such with their estimate and evidence. They are not silently treated as failed capabilities. A `FROM-SCRATCH` path must have an explicit operation-specific construction budget before it is attempted.

## Engineering route rule

Choose the lowest-cost implementation that meets the frozen capability and robustness requirements. “Equivalent,” “materially useful advantage,” and “acceptable cost” must receive prospective operational definitions in the sealed E4-1 contract; no numeric margins or floors are set in this design note.

Apply these route rules after locked evaluation:

| Evidence | Route implication |
| --- | --- |
| PRETRAINED has a useful capability or robustness advantage over cheaper controls at acceptable cost | `KEEP` the frozen-substrate path |
| A cheaper source meets the same required capability and robustness floors | `REPLACE WITH CHEAPER SOURCE` |
| RANDOM is equivalent to PRETRAINED for the intended operation | Pretraining is not required for that path; choose by measured engineering properties |
| FROM-SCRATCH materially exceeds PRETRAINED at acceptable construction and operating cost | `REPLACE WITH FROM-SCRATCH SOURCE`, or boundary/kill the frozen path |
| PRETRAINED wins the source comparison but fails required surface variation | Keep only if its frozen applicability boundary is operationally useful; otherwise `KILL PATH` |
| A machine is useful only on a prospectively identifiable surface region | `KEEP WITH BOUNDARY` |
| No candidate meets the frozen requirements | `KILL PATH` |

The permitted route values are `KEEP`, `KEEP WITH BOUNDARY`, `REPLACE WITH CHEAPER SOURCE`, `REPLACE WITH FROM-SCRATCH SOURCE`, and `KILL PATH`. A route decision is not an authorization for the next build.

## Numeric gates and discovery budget

This design intentionally freezes no performance threshold, support count, equivalence margin, degradation allowance, latency ceiling, memory ceiling, or cost ceiling. E4-0 must first establish the actual operating regime and intended use. After E4-0 reaches terminal disposition, freeze E4-1's numeric engineering gates before E4-1 population contact.

The post-E4-0 contract must also freeze the single discovery budget: exact interface candidates, candidate count per eligible source, fitting/selection allowance, development data, and a stopping rule. A small fixed menu may include the unchanged E4-0 interface, one simple readout variant, one modest nonlinear interface, and one normalization/projection variant, if still justified by the E4-0 result. The evaluation set is never used to choose among them. No open-ended sweep or post-evaluation rescue is permitted.

## Phase sequence

Each phase ends at its own reviewable boundary. Do not skip ahead or treat a later-phase description here as permission.

| Phase | Work product | Boundary |
| --- | --- | --- |
| 0 — Inherit | E4-1 plan, entry receipt, population contract, source-ladder contract, and engineering-gates contract; register E4-0 artifacts with Chain of Custody | Model-free. Entry remains closed until E4-0 is terminal and custody readiness is evidenced. |
| 1 — Construct | Fresh E4-1 population with paired latent identities, surface strata, and sealed development/evaluation partitions | No fitting. Independently audit identity, semantics, overlap, support, and truth isolation. |
| 2 — Materialize | Features for each feasible source-ladder arm and the frozen Track T path | Reuse approved extraction code only by bound identity; do not use E4-0 terminal evaluation rows as training inputs. Seal feature/source/resource receipts. |
| 3 — Develop | Fit the frozen candidate menu on development material; select at most one implementation per source under the frozen rule | No evaluation-label access. Receipt all fit inputs, candidates, costs, and exclusions. |
| 4 — Lock | Seal exact source/interface candidates, predictions code, gates, and evaluation plan | No further candidate or threshold changes. |
| 5 — Evaluate | One opening of the registered fresh evaluation partition for locked candidates; run Track T and Track S | Record all registered outcomes, including failures. No rescue or candidate deletion. |
| 6 — Replay and route | Independent reconstruction, terminal table, per-capability route decisions, and custody closeout | Emit route dispositions; next build requires its own decision and authorization. |

## Required terminal report

Report one row per registered source and eligible capability. Do not average away a failed operation or surface stratum.

| Source | Capability | Base performance | Template OOD | Lexical OOD | Combined OOD | Fit cost | Inference cost | Memory | Latency | Disposition |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| LEXICAL |  |  |  |  |  |  |  |  |  |  |
| TOKEN |  |  |  |  |  |  |  |  |  |  |
| RANDOM |  |  |  |  |  |  |  |  |  |  |
| PRETRAINED |  |  |  |  |  |  |  |  |  |  |
| FROM-SCRATCH |  |  |  |  |  |  |  |  |  |  |

The sealed terminal artifact must additionally state:

```text
SELECTED_ENGINEERING_PATH =
SELECTED_SOURCE =
SELECTED_INTERFACE =
SUPPORTED_SURFACE_REGION =
KNOWN_FAILURE_REGION =
NEXT_BUILD_AUTHORIZED = false
```

`NEXT_BUILD_AUTHORIZED` remains false in this design. A later decision may authorize a distinct build after reviewing the terminal evidence.

## Science handoff and exclusions

If a result is scientifically surprising, record only:

```text
SCIENCE_HANDOFF_CANDIDATE
observation:
minimal reproduction:
possible question:
```

E4-1 does not perform component localization, Matryoshka attribution, circuit discovery, latent geometry explanation, curvature analysis, causal mediation, neuron/head/layer interpretation, JEV hypothesis confirmation, R1 geometry work, controller fitting, reverse self-play, broad capability claims, or open-ended hyperparameter search.

## Stops and status rules

- If E4-0 has no viable machine, close E4-1 as `NOT_ELIGIBLE_E4_0_NO_VIABLE_MACHINE`; do not run a rescue.
- If the E4-0 terminal artifact or custody receipt is absent, stale, or inconsistent, stop before E4-1 construction.
- If Kammi Ledger acceptance or independent closure verification is pending, absent, or bound to a different architecture hash or E4-0 fixture, the new-flight gate stays closed; do not begin E4-1.
- Any E4-1 identity, label-partition, leakage, resource, source-integrity, or replay failure is preserved under its attempt identity and stops that attempt.
- A surface or source failure is an engineering result, not grounds for a same-identity rerun or mechanism search.
- No phase in this design grants model contact, fitting, truth access, evaluation, or downstream build authority.

## Status summary

| Item | State |
| --- | --- |
| E4-1 mission and route intent | Defined for design |
| Track T and Track S structure | Defined for design |
| Entry and chain-of-custody requirements | Defined; not satisfied |
| Numeric engineering gates | Deferred until E4-0 terminal result |
| Exact candidate/source budgets | Deferred until E4-0 terminal result |
| E4-1 contract seal | Not created |
| E4-1 population or execution | Not authorized |
