# Backbone v1 source and assumption register

Checked: 2026-10-01. This is a focused engineering source map, not a systematic review or a new empirical qualification. The plan separates published methods, local measured findings, and its own construction assumptions.

## Primary literature used for the selected construction

| ID | Source | Operation used | Boundary checked |
| --- | --- | --- | --- |
| L1 | Fikes and Nilsson, [STRIPS: A New Approach to the Application of Theorem Proving to Problem Solving](https://cs.uky.edu/~sgware/reading/papers/fikes1972strips.pdf); [published identity](https://www.sciencedirect.com/science/article/pii/0004370271900105) | Explicit state-changing operators, preconditions, and effects. | Our observation ledger uses explicit negative evidence; it does not inherit closed-world absence semantics. |
| L2 | Bonet and Geffner, [Planning as heuristic search](https://www.cs.toronto.edu/~sheila/2542/s14/A1/bonetgeffner-heusearch-aij01.pdf), 2001 | Cost search and optional delete-relaxed h-max heuristic. | Its admissibility applies to the modeled planning fragment. Use h=0 first; bounds on search effort do not establish global impossibility. |
| L3 | Garrett, Lozano-Perez, and Kaelbling, [PDDLStream](https://arxiv.org/abs/1802.08705), ICAPS 2020; [full text](https://arxiv.org/html/1802.08705v5) | Domain/certified-output specifications for external generators and task-directed invocation. | Section 3 declares certified outputs; the paper's streams add immutable initial facts. Versioned or approximate model observations do not automatically meet those assumptions. |
| L4 | Doyle, [A Glimpse of Truth Maintenance](https://dspace.mit.edu/entities/publication/e274a3b1-dcb7-4d62-abe7-a4b0db173191), MIT repository; [A truth maintenance system](https://www.sciencedirect.com/science/article/pii/0004370279900080), 1979 | Record reasons for beliefs and dependency-directed revision. | Adopt dependency bookkeeping. Do not claim the proposed conservative signed closure is an implementation of Doyle's complete system. |
| L5 | Green, Karvounarakis, and Tannen, [Provenance Semirings](https://www.cs.ucdavis.edu/~green/papers/pods07.pdf), PODS 2007 | Factor alternative derivations and joined premises; preserve shared evidence ancestry. | Polynomial/semiring provenance is not a license to multiply correlated model probabilities. The first engine stores a factorized justification graph rather than full symbolic expansions. |
| L6 | Cormack, Clarke, and Buettcher, [Reciprocal Rank Fusion](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf), SIGIR 2009 | Deterministic fusion of heterogeneous retrieval rankings. | Ranking only. No truth probability, no authority threshold, and no guarantee it improves our task before application use is measured. |
| L7 | Alshiekh et al., [Safe Reinforcement Learning via Shielding](https://arxiv.org/abs/1708.08611), AAAI 2018 | Separate proposal selection from specification-based action monitoring. | We borrow the separation. Our first monitor is not a synthesized temporal-game shield; sound action checks depend on correct source/domain/executor contracts. |
| L8 | Golovin and Krause, [Adaptive Submodularity](https://arxiv.org/abs/1003.3967), JAIR 2011 | A later route to justified cost-aware adaptive acquisition. | Greedy guarantees require the appropriate monotonicity/diminishing-returns assumptions. Obligation complements/conflicts may violate them, so v0.1's scheduler is explicitly heuristic. |
| L9 | Kaelbling, Littman, and Cassandra, [Planning and acting in partially observable stochastic domains](https://www.sciencedirect.com/science/article/pii/S000437029800023X), 1998 | Belief-state formulation for genuinely stochastic contingent decision problems. | No calibrated transition/observation distribution is assumed available today. It is an alternative construction, not an implementation prerequisite. |
| L10 | McSherry, Murray, Isaacs, and Isard, [Differential dataflow](https://www.microsoft.com/en-us/research/publication/differential-dataflow/), CIDR 2013 | Incremental maintenance of iterative computations on changing data. | Only adopt if bounded closure recomputation is a measured bottleneck. It does not solve source truth or action permissions. |

Full-text sections consulted for this plan include PDDLStream's stream/action definitions, the planning paper's max heuristic, the provenance paper's introduction/formal annotations, STRIPS's operator formulation, and the two-page RRF paper. Primary author/publisher abstracts and records ground the narrower descriptions of shielding, adaptive acquisition, POMDPs, and differential dataflow. Some publisher full-text endpoints were unavailable; the plan makes no additional theorem claim from those inaccessible pages.

## Graph literature recovered from the existing paper-to-contract sprint

These were already organized locally in [focused-paper-to-contract-sprint-v1.md](../focused-paper-to-contract-sprint-v1.md). Primary identities/pages were checked again. They become graph-provider construction choices, not replacements for observation or authority contracts.

| ID | Source | Role in the backbone | Important distinction |
| --- | --- | --- | --- |
| G1 | Vashishth et al., [CompGCN](https://arxiv.org/abs/1911.03082), ICLR 2020 | Reusable entity/relation composition for typed candidate nomination. | Static relational completion is not demonstrated temporal action execution. |
| G2 | Galkin et al., [StarE: Message Passing for Hyper-Relational Knowledge Graphs](https://aclanthology.org/2020.emnlp-main.596/), EMNLP 2020 | Statement-scoped qualifiers while retaining primary triple roles. | Source/time qualifiers must not be erased by flattening them into arbitrary relation IDs. |
| G3 | Zhu et al., [Neural Bellman-Ford Networks](https://arxiv.org/abs/2106.06935), NeurIPS 2021 | Query-conditioned path aggregation for a bounded relational nomination service. | Learned path representations produce ranking scores, not logical proof certificates. |
| G4 | Galkin et al., [ULTRA / Towards Foundation Models for Knowledge Graph Reasoning](https://arxiv.org/abs/2310.04562), ICLR 2024 | Relation-interaction conditioning when entity/relation inventories change across domains. | Unseen-vocabulary link-prediction performance is not a guarantee on operational policy transfer. |
| G5 | Gastinger et al., [TGB 2.0](https://arxiv.org/abs/2406.09639), NeurIPS 2024 | As-of topology and future-link task discipline for temporal providers. | Simple priors remain relevant; chronological forecasting is a distinct task from interpolation. |
| G6 | Ding et al., [Temporal Fact Reasoning over Hyper-Relational Knowledge Graphs](https://aclanthology.org/2024.findings-emnlp.20/), Findings of EMNLP 2024 | Explicit validity time and qualifier structure. | The existing local audit identifies its interpolation regime; do not use those results as forecasting evidence. |

## Local design evidence consulted

| Source | What was recovered | How used |
| --- | --- | --- |
| [FF-S15 status](../../experiments/ff-s15-STATUS.md) | Controller limits, edge-ranking/threshold contrast, X0/X1/X6 attribution, deferred interfaces. | Bounded result history; historical waiting instructions do not veto this newly requested engineering plan. |
| [VCS-0 corrected status](../../experiments/vcs-0/STATUS.md) and [correction](../../experiments/vcs-0/CORRECTION-2026-09-30.md) | Four-cell operational reconstruction; VCS-1b not earned. | Preserve scientific disposition; do not turn geometry into authority. |
| [X0 plan](../../experiments/ff-s15-x0-graph-sandbox-01/PLAN.md) | Typed state/action/goal graph and bounded planning. | Reuse action/dependency abstraction, without oracle materialization. |
| [X1 candidate ABI](../../experiments/ff-s15-x1-materializers-01/x1/abi.py) | Candidate edges, producer identities, provenance. | Keep candidates separate from warranted facts; avoid enumerating every global pair. |
| [X6-A plan](../../experiments/ff-s15-x6a-acquisition-01/PLAN.md) | Missing slots, query costs, incomplete vs empty results. | Primary schema-based acquisition; graph composes shared/alternative obligations. |
| [V2 graph design draft](../../experiments/ff-s15-v2-graph-design-00/V2-2-DESIGN-DRAFT.md) | Materialization/transition boundary and structural attribution concerns. | Design reference only; no BANK-v2 data or model run used. |
| [VCS-1A freeze](../../experiments/ff-s15-vcs1a-runtime-01/VCS-1A-FREEZE.md) and [schema](../../experiments/ff-s15-vcs1a-runtime-01/vcs/schema.py) | Envelope/schema IDs, dispositions, applicability, deterministic authority concepts. | Versioned engineering adapter; frozen three-valued region semantics remain unchanged. |
| [AI harness audit](../app-native-ai-harness-audit-v1.md) | Evidence/source records, durable provider events, note transaction ownership. | Fit the kernel into real Phoenix resource operations. |
| [Candle/Burn spike](../candle-vs-burn-graph-runtime-spike-v1.md) | Existing isolated CPU numeric runtime and staging bottleneck. | Reuse an available readout service if needed; do not generalize its benchmark to all workloads. |
| [Agent control commands](../../phoenix-native/crates/phoenix-agent-control/src/parser.rs) | stat/read/insert/events, expected revision, idempotency fields. | First real source/executor boundary; host atomicity still checked during adapter implementation. |
| [Memory records](../../phoenix-native/crates/phoenix-memory-contract/src/records.rs) | Evidence spans, candidates, producer capabilities, validity and supersession. | Reuse immutable source artifacts through explicit versioned mappings. |

The thread also supplies the locked live representation surfaces, the closed masking rung, R2a's estimate/truth separation, and the user's decision to permit synthetic engineering data. They constrain the plan without creating a new model run.

## Assumptions that remain ours to implement/check

The signed two-pass warrant construction, resource-risk tiers, task-local obligation policy, bounded planner configuration, and performance budgets are proposed engineering choices. The literature supports constituent methods; it does not certify this assembled machine. Software tests check invariants, real task use checks usefulness, and a focused experiment is reserved for a design choice with a materially uncertain outcome.
