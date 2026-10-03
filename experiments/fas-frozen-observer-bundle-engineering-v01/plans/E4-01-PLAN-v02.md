# E4-01 — Surface Survival and Substrate Value

**Version:** v02  
**Date:** 2026-09-27  
**Status:** activation plan; design-only until the E4-0 entry gate is satisfied  
**Lineage:** supersedes E4-01-PLAN-v01.md as the current plan snapshot, preserving its engineering decisions while refreshing custody and execution status. The older plan remains immutable history.

This document records the user-directed E4-01 mission and operating boundaries. It is not a machine-readable execution contract, a Ledger grant, a GPU lease, or permission to cross a sealed phase gate. The user has directed the lab to carry the flight through terminal disposition without returning for routine planning approval. Each gated operation still requires its contract-bound Ledger authorization.

## Mission

E4-01 is an engineering-selection flight. It asks:

1. Does the E4-0 machine remain useful across the surface variation needed for its intended operation?
2. Can a cheaper source meet the same capability and robustness requirements?

Choose the cheapest reproducible implementation that meets the need. Do not pause to explain mechanisms. Record surprising observations for possible JEV review.

The terminal routes are:

- KEEP_PRETRAINED
- KEEP_PRETRAINED_WITH_BOUNDARY
- USE_CHEAPER_SOURCE
- USE_FROM_SCRATCH
- KILL_PATH

A route is not authority for the next build.

## Activation directive

The Fabrique agent works only on Frozen Fabrique. It does not implement, repair, extend, or debug Kammi Ledger, Library Lab, shared custody schemas, policy, leases, adapters, exposure infrastructure, remote execution, or institutional-memory infrastructure.

Use the qualified Kammi Ledger and its approved SDK/API surfaces for new-flight custody and gated operations. If authorization, artifact registration, exposure, a lease, an adapter, remote execution, or a schema blocks the work, preserve the attempt, send Chief Kammi the exact request and denial/receipt, and wait for resolution. Do not build a local substitute.

Do not kill or preempt unrelated GPU work. Request the declared Ledger GPU lease and wait if it is unavailable. Do not bypass the lease, inspect or alter another lab's process, or switch devices without a prospective amendment.

## Entry gate and E4-0 dependency

E4-01 opens only after all of the following are true:

1. E4-0 has a sealed terminal disposition.
2. E4-0 produced a viable machine and its eligible population, representation, interface recipe, and operational measurements are frozen.
3. Chain of Custody has reconciled and registered the inherited E4-0 artifacts.
4. E4-01's use of inherited evaluation partitions is explicitly allowed. Previously opened E4-0 labels are spent evidence; they must not be described as a fresh or blind E4-01 evaluation.
5. Any new terminal population required for an independent E4-01 claim is generated under a frozen E4-01 contract before model contact.

If E4-0 has no viable machine, E4-01 does not run and does not create a rescue experiment. If E4-0 is still incomplete, finish its remaining phases under its existing sealed contract and separate Ledger stage authorizations. Do not rewrite E4-0 as part of E4-01.

### Current dependency state

E4-0 contract v16-v09 is sealed at root 278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1. The inherited population and tokenizer-only parity-panel artifacts were produced under E4 v06 root 7344badf07476d19d9c6228f80d026a112c339e93daa75593e61031f68456e64. Chief's 2026-09-27 visible-input inventory v1 binds 19 named nontruth roles to current bytes (SHA-256 `755618754dc51acd9d43e514e8d6a7c78e1eea090910ddeca29a1e8124a06204`); it reports no protected-label access, E4 authorization, or dynamic extraction inputs. The inventory prepares custody binding but does not grant execution authority.

The Fabrique-owned supervised adapter v02 now verifies the actual v16 contract, v16-v09 seal manifest, and v16-v11 postseal audit bytes; its no-model-contact CPU qualification passed 12 tests. The candidate execution spec remains unregistered and unauthorized. Chief Kammi owns the authoritative parity binding, run/stage grants, and GPU lease. No parity or feature extraction has run under the corrected candidate, and E4-0 has no terminal disposition.

The current qualified LibraryAcceptanceV1 identity is `sha256:f98dcd6743c5e8b7ff091cef2d69aa361e53c252711c7b001f3a71d322744602`, with handoff seal `ad1ffbc9203fd0cac5553ea4a5d3c72654c22054e68348474414096e35dd8cc5` and visible-only bridge `aacfd286b6349f0b35adb853a2cd9717c2463fedfeccc052bafaf515c69b027b`. Acceptance and inheritance records do not authorize E4-0 or E4-01 scientific execution.

## Frozen inheritance

Bind through Chain of Custody before E4-01 execution:

- E4-0 terminal run and result identities
- eligible population and stratum identities
- model, tokenizer, and substrate identities
- feature-surface and extraction configuration
- five frozen E3 head and scaler identities
- fit identities and evaluation implementation
- serving-device configuration
- relevant E4-0 result roots and exposure history

The five E3 heads remain frozen. E4-01 cannot change their weights, scalers, thresholds, feature surface, or fit population. Alternative source arms may fit their own interfaces under the E4-01 contract.

## Population and truth handling

Reuse the fresh E4-0 population only where its sealed contract and Ledger exposure state permit. Preserve its identities and distinctions:

- seen rendering / fresh instance
- lexical OOD: context-novel, entity-novel, both-novel
- held-out template
- template plus lexical novelty, if present

Do not create templates after contact. Do not use E4-0 terminal evaluation data to select E4-01 candidate interfaces. If E4-0 labels have already been opened, treat them as spent and describe any permitted reanalysis accurately. Keep held-out-template and joint truth escrowed until the E4-01 analysis contract and Ledger exposure authorization permit their opening.

Where an independent E4-01 terminal claim requires new examples, construct a fresh population under a new sealed namespace. Keep development data, candidate selection, and terminal evaluation identities disjoint.

## Track T — Surface Survival

Question: does the frozen E4-0 implementation remain useful under the surface variation required for intended use?

Evaluate the unchanged E4-0 machine across the registered strata:

- SEEN / FRESH ITEM
- LEXICAL-OOD
- TEMPLATE-OOD
- TEMPLATE + LEXICAL OOD, where available

Use paired latent task instances across surface arms where possible. Do not refit the E3 heads, search layers or pooling, change prompts, or add a better head after seeing weak transfer.

For each qualified capability and surface stratum, report performance, absolute and relative degradation, failure count/rate, latency, serving cost, and memory. Keep each result visible; do not collapse the vector into one robustness score.

### Optional matched surface comparator

A matched mean-pooled comparator may be included only if it is already implementable without materially expanding the flight. It is engineering context, not a geometry study. If it cannot be instantiated cleanly, report NOT_APPLICABLE and continue.

## Track S — Source Value

Question: which representation source is worth carrying for the same task?

Use this fixed ladder:

| ID | Source | Definition |
| --- | --- | --- |
| L0 | LEXICAL | Cheap lexical counts and template-visible features |
| L1 | INPUT_EMBEDDING | Pooled frozen input-token embeddings or the declared cheap equivalent |
| L2 | RANDOM_SUBSTRATE | Random-weight version of the declared substrate architecture, where practical |
| L3 | PRETRAINED_SUBSTRATE | The frozen pretrained LFM final-position representation inherited from E4-0 |
| L4 | MATCHED_FROM_SCRATCH | Operation-matched purpose-built reference, only if its construction budget is frozen and affordable |

Hold constant where applicable: task populations, training/development/terminal identities, labels, task definitions, interface family and budget class, fit budget class, candidate selection procedure, and scoring implementation. Require decision fairness; do not force byte-identical parity when a source makes that meaningless.

An infeasible or over-budget source is reported with its estimate and reason, not silently counted as a capability failure.

## Development and candidate lock

E4-01 may use one bounded discovery budget for non-E3 sources. Before terminal evaluation contact, freeze:

- the interface candidates and maximum count per source
- fixed optimizer, schedule, seed roster, and subsample roster
- development identities and selection rule
- source-specific construction and fit budgets
- stopping rule

The menu may include the unchanged E4-0 interface, one simple readout variant, one modest nonlinear interface, and one normalization/projection variant if justified by E4-0. Select at most one candidate per source using development data only. No open-ended search, giant sweep, terminal-based selection, or post-evaluation rescue.

Repeated fits may measure optimizer/subsample variability under the fixed roster. They do not authorize adaptive budget expansion. E3 remains unchanged.

## Engineering gates

Do not inherit E3's 0.90 scientific qualification floor as an E4-01 usefulness threshold. After E4-0 reaches terminal disposition, define the intended operation and freeze E4-01's numerical performance, support, equivalence, degradation, latency, memory, and cost requirements before E4-01 terminal-population contact.

Choose the lowest-cost candidate that meets the prospectively frozen capability and robustness requirements. Preserve the full utility vector:

U = (quality, surface survival, latency, memory, fit/construction cost, serving cost)

Do not choose a path because it has the prettiest isolated score or a post-hoc significance result.

## Execution phases

Run one phase at a time. Each phase uses Ledger custody and its own required authorization/exposure/lease.

| Phase | Work | Boundary |
| --- | --- | --- |
| 0 — Inherit | Register and reconcile E4-0 terminal artifacts and exposure history | No new model contact; entry gate must pass |
| 1 — Population | Reuse only authorized E4-0 strata or construct the contract-bound fresh E4-01 population | Seal identities, partitions, support, and truth boundary; no fitting |
| 2 — Sources | Materialize feasible source features | Bind source and resource receipts; no terminal scoring |
| 3 — Develop | Fit the fixed candidate roster and select at most one per source | Development data only |
| 4 — Lock | Seal candidates, predictions code, gates, and evaluation plan | No further changes |
| 5 — Evaluate | Open the authorized terminal partition once for locked candidates | Report every registered result and failure |
| 6 — Replay and route | Independently reconstruct results and issue engineering dispositions | Next build remains separately gated |

## Route rules

- If a cheaper source meets the same required capability and robustness floors, use it.
- If pretrained features provide a useful advantage at acceptable cost, keep the frozen-substrate path.
- If random and pretrained sources are equivalent, pretraining is not required for that path; choose by measured engineering properties.
- If matched from-scratch materially exceeds pretrained at acceptable cost, replace or boundary the frozen path.
- If pretrained wins but only on an operationally useful surface region, keep it with that boundary; otherwise kill it.
- If no candidate meets the requirements, kill the path.

Do not explain any source advantage mechanistically in E4-01.

## Science handoff

For an unexplained result, preserve a short handoff candidate with:

- observation and exact comparison
- population and strata
- effect and operational consequence
- artifact references
- possible question

Then continue the engineering disposition. JEV decides whether it merits a scientific experiment.

## Exclusions

E4-01 does not perform component localization, Matryoshka attribution, circuit discovery, representation geometry or curvature analysis, causal mediation, neuron/head/layer interpretation, JEV hypothesis confirmation, R1 geometry, controller fitting, request/applicability routing, E5 composition, reverse self-play, capability cartography, a prospector, or open-ended hyperparameter search. Those remain separate branches.

## Stop conditions

Preserve and stop the affected operation if:

- E4-0 inheritance or custody identity fails
- protected data are exposed without a valid Ledger authorization
- an E3 frozen identity changes
- development and terminal partitions contaminate each other
- a candidate or threshold changes after terminal opening
- source-ladder comparability is invalid
- Ledger denies a required operation or lease
- a required deterministic or replay invariant fails

For any Library or custody problem, page Chief Kammi with the exact denial/receipt and required capability. Do not repair the shared infrastructure.

## Terminal disposition

Report every source and capability without averaging away a failed task or stratum.

| Source | Capability | Seen | Lexical OOD | Template OOD | Joint OOD | Fit cost | Serve cost | Memory | Latency | Disposition |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Lexical |  |  |  |  |  |  |  |  |  |  |
| Input embedding |  |  |  |  |  |  |  |  |  |  |
| Random |  |  |  |  |  |  |  |  |  |  |
| Pretrained LFM |  |  |  |  |  |  |  |  |  |  |
| From scratch |  |  |  |  |  |  |  |  |  |  |

The sealed terminal result also records:

- E4_01_STATUS
- SELECTED_PATH
- SELECTED_SOURCE
- SELECTED_INTERFACE
- SUPPORTED_SURFACE_REGION
- KNOWN_FAILURE_REGION
- FIT_COST
- SERVING_COST
- NEXT_BUILD_ELIGIBLE
- SCIENCE_HANDOFFS

E4-01 is done when it identifies the cheapest machine worth retaining, its supported and failed surface regions, its fit and serving costs, whether the pretrained substrate adds operational value, and the next engineering route.

## Current state

E4-01 is not yet eligible, its contract is not sealed, no E4-01 run is registered, and no E4-01 labels or models have been contacted. Finish E4-0 under its existing sealed contract through Chief's authoritative binding, stage grants, and GPU lease. E4-01 remains closed until E4-0 has a sealed terminal disposition and its inherited artifacts have been reconciled in Ledger.
