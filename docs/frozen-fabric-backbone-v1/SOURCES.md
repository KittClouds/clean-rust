# Source and assumption register

Checked 2026-10-01. This is a focused construction review, not a systematic survey. Primary papers/author or publisher records were opened. Access depth is recorded so an abstract-level check is not described as a full-paper audit.

## Borrowed methods

| ID | Primary source | Operation borrowed / access | Assumption boundary |
| --- | --- | --- | --- |
| L1 | Bonet & Geffner, [Planning as heuristic search](https://www.cs.toronto.edu/~sheila/2542/s14/A1/bonetgeffner-heusearch-aij01.pdf), AIJ 2001 | Explicit action search; max-relaxation cost heuristic. Full PDF, heuristic section checked. | Admissibility is for the modeled planning fragment, not uncertain provider outcomes. Initial implementation uses zero heuristic. |
| L2 | Nau et al., [SHOP2: An HTN Planning System](https://www.cs.umd.edu/~nau/papers/nau2003shop2.pdf), JAIR 2003 | Authored task methods and ordered/partially ordered decomposition. Full PDF, task/method definitions checked. | Methods encode domain knowledge and may restrict the allowed plans. V1 recipes guide primitive search; no full HTN claim. |
| L3 | Garrett et al., [PDDLStream](https://arxiv.org/html/1802.08705v5), ICAPS 2020 | External-procedure domain and output contracts; lazy task-directed generation. Full text, stream/certification/state definitions checked. | Paper-certified stream facts are immutable; our expiring observations and learned proposals require separate semantics. |
| L4 | Doyle, [A Glimpse of Truth Maintenance](https://dspace.mit.edu/entities/publication/e274a3b1-dcb7-4d62-abe7-a4b0db173191), MIT AIM-461, 1978 | Belief dependencies and revision. Repository identity checked; download unavailable in this pass. | Broad dependency principle only. Our conservative signed closure is explicitly our own construction, not Doyle's complete algorithm. |
| L5 | Green, Karvounarakis & Tannen, [Provenance Semirings](https://www.cs.ucdavis.edu/~green/papers/pods07.pdf), PODS 2007 | Joint versus alternative source lineage. Full PDF, annotations/polynomial sections checked. | Lineage algebra is not calibrated probability multiplication. Recursive provenance can be cyclic/infinite; keep finite warrant witnesses. |
| L6 | Belnap, [A Useful Four-Valued Logic](https://link.springer.com/chapter/10.1007/978-94-010-1161-7_2), 1977 | Separate unknown, positive, negative and inconsistent evidence. Publisher abstract/identity checked. | We use two support bits and our own action policy; no claim to implement full FDE or its extensions. |
| L7 | Alshiekh et al., [Safe Reinforcement Learning via Shielding](https://arxiv.org/abs/1708.08611), AAAI 2018 | Separate proposals from specification checks. Author abstract checked. | Temporal-game guarantees require a model/specification and synthesis. Our initial checker enforces local contracts only. |
| L8 | Liu et al., [LLM+P](https://arxiv.org/abs/2304.11477), 2023 | Language interpretation and classical planning as different components. Author abstract checked. | Correct search does not guarantee a correctly translated task/model. No performance transfer to 230M is assumed. |
| L9 | Ahn et al., [SayCan](https://arxiv.org/abs/2204.01691), 2022 | Task relevance versus executable skill feasibility. Author abstract checked. | We borrow interface separation, not pretrained robot values or their probabilistic combination. |
| L10 | Golovin & Krause, [Adaptive Submodularity](https://arxiv.org/abs/1003.3967), JAIR 2011 | Conditional route to cost-aware adaptive acquisition. Author abstract checked. | Greedy guarantees require adaptive-submodular/monotone objectives and the relevant outcome model; prerequisite complements can violate them. |

The signed two-pass closure, task budget policy, evidence admission classes, estimate-permitted draft actions, resource version checks and module boundaries are **engineering choices made here**. The source papers do not prove this assembled system works.

## Recovered graph methods

The prior [paper-to-contract sprint](../focused-paper-to-contract-sprint-v1.md) contains detailed operations and task distinctions. It belongs to the historical Phoenix lane. We recover the literature independently; its product tickets and empirical gates do not become Frozen Fabric dependencies.

| ID | Primary source | Construction option / access | When to use |
| --- | --- | --- | --- |
| G1 | Zhu et al., [Neural Bellman-Ford Networks](https://arxiv.org/abs/2106.06935), NeurIPS 2021 | Query-conditioned learned path aggregation. Author abstract checked. | Default learned nomination design when the existing candidate front has a demonstrated gap. Link score is not a logical warrant. |
| G2 | Vashishth et al., [CompGCN](https://arxiv.org/abs/1911.03082), ICLR 2020 | Joint entity/relation composition. Author page checked. | Reusable relational encoding on a stable inventory, when that is more suitable than per-query propagation. |
| G3 | Galkin et al., [StarE](https://aclanthology.org/2020.emnlp-main.596/), EMNLP 2020 | Qualified statements retaining primary triple roles. Publisher page checked. | A learned front must represent source/time/other qualifiers without flattening statement roles. |
| G4 | Galkin et al., [ULTRA](https://arxiv.org/abs/2310.04562), ICLR 2024 | Transferable relation-conditioned graph representations. Author abstract checked. | Multiple unrelated relation vocabularies become an actual requirement. Transfer of link ranking is distinct from action-policy transfer. |

RRF, temporal link forecasting and richer hyper-relational models remain available in the recovered register, but are not required methods for the first machine. Avoid adding an algorithm merely because we already have a paper about it.

## Local evidence and designs used

| Local source | Use in this construction |
| --- | --- |
| [FF-S15 status](../../experiments/ff-s15-STATUS.md) | C0 runtime; C1-C4 limits; X0 composition; X1 arbitration; X6 acquisition attribution; deferred observer ABI. |
| [VCS-0 status](../../experiments/vcs-0/STATUS.md) and [correction](../../experiments/vcs-0/CORRECTION-2026-09-30.md) | Preserve corrected four-cell results and the unearned VCS-1b disposition. |
| [X0 plan](../../experiments/ff-s15-x0-graph-sandbox-01/PLAN.md) | Typed goal/state composition and distinction between materialization and search. |
| [X6-A plan](../../experiments/ff-s15-x6a-acquisition-01/PLAN.md) | Named slots, query costs and bounded information gathering; no inherited claim of graph scheduling superiority. |
| [V2 graph design](../../experiments/ff-s15-v2-graph-design-00/V2-2-DESIGN-DRAFT.md) | Explicit observation/policy obligations; no BANK-v2 data or model contact. |
| [VCS-1A freeze](../../experiments/ff-s15-vcs1a-runtime-01/VCS-1A-FREEZE.md) | Infrastructure concepts only. Its frozen files and experimental authorization remain unchanged. |
| [Earlier engineering draft](../backbone-engineering-v1/ENGINEERING-PLAN.md) | Recover operational contracts, warrants, repair and authority; supersede its Phoenix application and package choice. |
| Current thread | Locked live surfaces; causal first-token degeneracy; specialization rotation; closed H2; R2a count/identity contract; synthetic engineering authorization. |

Historical Phoenix trajectory/policy artifacts were inspected to identify a boundary: their production-data and promotion requirements belong to their own programs. No package or build dependency here requires those artifacts. No new experiment was run and no protected truth was opened for this plan.

## Established / assumed / unresolved

**Established methods:** finite typed action search; task decomposition; external-procedure contracts; explicit source lineage; distinct incomplete/conflicting evidence; proposal/execution separation. Their guarantees apply only under their stated assumptions.

**Engineering assumptions:** a useful first domain can be described with bounded typed rules/actions; validators can check selected output properties; task-scoped source revisions are available; frozen providers can contribute useful candidates in their registered scope; real utility can be measured on task execution.

**Unresolved design questions:** semantic provider utility on the chosen domain, cost of graph nomination, scheduling quality under complementary requests, source-churn cost, and which estimated-input actions are useful. Each has a working default and a decision-changing check in the plan. None blocks the first deterministic kernel or draft-producing task loop.

**Not established:** general action competence of 230M; universal semantic admission thresholds; zero retrieval harm; optimal acquisition; globally transitive context compatibility; transportable region authority; VCS-1b; interpretability/mechanistic claims about graph or attention components.
