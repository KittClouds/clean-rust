# Day 7 Research State — Later Checkpoint

**Snapshot:** 2026-09-26 14:00 UTC. This later Day 7 checkpoint follows the earlier [Day 7 snapshot](day-07-research-state-2026-09-26.md) from 12:15 UTC, which preserves the Day 6 starting line. The earlier Day 7 file remains unchanged; this update records the completed observer-bundle scoring and the newer cross-lab carry-forward states.

## Observer bundle: scoring answered the engineering question

One pinned, frozen `LiquidAI/LFM2.5-1.2B-Base` substrate and one immutable `V1_FINAL_POSITION` cache supported five independent linear heads. E3 v02 held-out scoring passed **all eight individual gates** on the sealed E1 v04 test panel. Each gate required a whole-quartet-bootstrap one-sided 95% lower bound of at least 0.90. These are individual gates, not a simultaneous 95% guarantee over the bundle.

| Endpoint | Test rows | Balanced accuracy | Bootstrap lower bound | Gate |
|---|---:|---:|---:|---|
| Context identity | 21,292 | 0.999010 | 0.998639 | PASS |
| Entity identity | 21,292 | 0.998744 | 0.998317 | PASS |
| Relation | 5,436 | 1.000000 | 1.000000 | PASS |
| Observed state | 5,436 | 1.000000 | 1.000000 | PASS |
| Exact target, in-domain | 5,436 | 1.000000 | 1.000000 | PASS |
| Exact target, context novel | 5,120 | 0.999624 | 0.999060 | PASS |
| Exact target, entity novel | 5,260 | 0.999435 | 0.998869 | PASS |
| Exact target, both novel | 5,476 | 0.998677 | 0.997724 | PASS |

The exact-target rows include the predeclared lexical novelty slices; the identity endpoints remain literal closed-set class-ID prediction tasks. All 21,292 TEST rows across 5,323 whole quartets were scored. E1's evaluation-label stream was opened once: 9,758,374 bytes, SHA-256 `5dcc56dd42cac4bb60c72552c646fd6511a4389ceba3d22a1aa142b25287ab7e`, matching the E1 seal. The independent auditor replayed row identity, support, every prediction, all eight metric tables, and all 10,000 bootstrap replicates per endpoint. It did not open the raw label file.

| Binding | Identity |
|---|---|
| E0 v10 | `899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd` |
| E1 v04 | `6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03` |
| E2 v07 | `a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a` |
| E3 v02 fits | `899ff6a61272b86fdf1cd51d8c14100e77185157c242f27fbffe452803a435e1` |
| E3 score v02 seal | `a104bffedbc3e31268c0f1c0103ad4326add5a9da93816007904b70cdf3c7d1f` |

Scoring records: [v02 contract](../experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e3-score-v02.json), [authorization](../experiments/fas-frozen-observer-bundle-engineering-v01/audits/e3-score-authorization-v02.json), [sealed manifest](../experiments/fas-frozen-observer-bundle-engineering-v01/seals/e3-score-v02-seal.json), and [independent audit](../experiments/fas-frozen-observer-bundle-engineering-v01/audits/e3-score-v02-independent-audit.json). Score outputs are under `D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-score-v02`. The saved scored-row artifact contains the opened TEST truth labels; treat it as post-truth-access data. The independent auditor replayed from that saved artifact and never reopened E1's raw label file.

Terminal disposition: `ALL_EIGHT_GATES_PASS_BUNDLE_QUALIFIED_FOR_ROUTING_DESIGN`. The five heads contain 147,528 trainable parameters (590,112 bytes) plus 81,920 scaler bytes, 672,032 bytes total. The shared feature cache is 872,415,232 bytes (832 MiB). Scoring used CPU PyTorch and did not initialize CUDA. Its five output artifacts occupy 9,436,019 bytes. The v02 contract SHA-256 is `6d1c7f35a7f3405313b9b67cbebebbb1b740c7e1c670b93d5579f280a7889704`; authorization SHA-256 is `d82ef561eb666e86ed48f8414d148a54af12a30f31f627faf520d5cd74768195`.

**Established:** this frozen representation cache produced five separately fitted observers that met their registered held-out performance gates on this controlled E1 population. **Not established:** generalization beyond this panel/task family, bundle-versus-standalone parity, serving latency, serving-cost savings, deployment value, or scale behavior. The E2 extraction took 3,402.17 seconds; the five E3 fits took 19.47 seconds. The declared B1 shared-extraction, B2 repeated-extraction, and B3 deployment-arithmetic distinctions remain intact; realized savings and online serving costs are unmeasured.

### Preserved precontact repair

Two earlier prelabel drafts are preserved after the verifier rejected an inference-schema comparison and an authorization receipt missing its explicit scope boolean. After those plumbing fixes, v01 passed prelabel verification; code review then found its bootstrap lookup indexed E1 manifest rows rather than joined rows carrying TEST truth labels. No held-out label was opened and no score output directory was created. The v01 contract and authorization remain under `experiments/fas-frozen-observer-bundle-engineering-v01/contracts/drafts/` and `audits/drafts/`; a stop receipt records the joined-row defect. The corrected scorer, contract, authorization, and output root use v02. No E0/E1/E2/E3 scientific identity or metric gate changed.

**Next boundary:** E3 is complete. Routing integration (E4) remains unauthorized; the next action is a separately frozen routing-design proposal and authorization. No refit, threshold adjustment, head sharing, view search, or scale comparison follows from this score.

## Current cross-lab state

| Lab / branch | Strongest current evidence | Failed hypothesis or limit | Next status and stop condition | Bound identity |
|---|---|---|---|---|
| **FAS S12 observer-plane intervention** | Selective causal dependence of the fixed LFM-plus-observer system was supported at all six layer/surface sites. The S12 protocol completed and independent replay passed all 432 prediction/margin/metric cells and 10,000 shared-plan bootstrap replicates. | This was a paired follow-up on the already revealed S11 panel, not independent population confirmation. It does not establish mathematical necessity, native generation behavior, transformer-circuit causality, or semantic feature identity. | Close this S12 protocol. Any independent confirmation needs a new population and a separate authorization; stop before broad causal or model-internal claims. | Final seal root `ea753bd876981aeba199d15e621aa140928af685e9c3080eac13dbf78801182c`; independent verification receipt SHA `a89dab9f0030de81c51cd74801ff76cc918b77bb624a952ec3925932ea67479a`. Run: `D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v02`. |
| **FAS frozen observer bundle** | The eight v02 endpoints above passed; notably entity identity reached 0.998744 balanced accuracy and both-novel exact-target transfer had a 0.997724 lower bound. | The result is bounded to one pinned 1.2B substrate, one final-position cache, five independent heads, and the sealed synthetic task population. It is not evidence of production serving economics. | E3 complete; E4 closed pending a new proposal and authorization. Stop if a follow-up changes heads, views, thresholds, or fit data without a new version. | E3 score root `a104bffedbc3e31268c0f1c0103ad4326add5a9da93816007904b70cdf3c7d1f`; E0/E1/E2/E3 roots above. |
| **JEV Q-R2 late-only weight branch** | 24 training runs, 48 late continuations from shared step-80 histories, 120 evaluation cells, and 960,000 prediction rows completed. Independent replay passed. Step-120 half-minus-1X effects were heterogeneous across the 24 paired trajectories. | A scalar half-weight is not a reliable universal control knob; this is not a full-course dose effect, mechanism result, seed-population estimate, or validated controller. | Treat Q-R2 as closed. No controller fitting or weight-policy promotion is authorized; any new dose or scheduling intervention needs its own prospective freeze. | Artifact root `95e95ce58602a8c47923a05dfd6af2d8eb303b9456e866a6a6a708dff17bc464`; status `Q_R2_INDEPENDENT_RESULT_REPLAY_PASS`. Result: `D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01\evaluation-v03\q-r2-results-v01.md`. |
| **F4-BINDING-01 Stage B** | The observed six-assignment pair-swap Δ balanced-error vector was positive: `[0.135933, 0.152516, 0.147601, 0.110644, 0.080655, 0.138628]`; mean `0.127663`. | The frozen block interval was unavailable (`null`), so disposition is `INCONCLUSIVE_BOOTSTRAP_SUPPORT`. No trajectory capability, measured REACH-03, controller work, PHENO change, or biological promotion follows. | Keep Stage B qualification-only. Do not advance from the positive observed vector without a new supported result and authorization. | Run: [`F4-BINDING-01 Stage B terminal receipt`](../experiments/fly-reach-03/runs/F4-BINDING-01-STAGE-B-PROSP-v0.1/STAGE-B-TERMINAL-RECEIPT.json). No aggregate seal root is recorded in the terminal receipt. Terminal receipt SHA `a84a379b1b1acdd15ac30d999a6a5f143fc9005739d3a878c930996ad19d7152`; prediction lock SHA `3dc0e1a68b33d02c45b86c2a948e8fa35fcbc08628e0f30468ea270a975a126c`. |
| **FAS-R1 Stage 1 sensor** | Frozen semantic identity passed 6 of 12 seed-condition cells: ID-seen and vocabulary-OOD passed all three seeds. | Template-OOD and joint-OOD failed all three seeds (mean balanced accuracy 0.4066 and 0.3843). The terminal state is `R1_SENSOR_FAIL_SEMANTIC`; binding and action-relevance fits were not run. | Stop the current LFM-backed R1 path at the semantic rung. No proposal/value training, particle search, measured REACH-03, or protected evaluation is authorized. Reopen only with a separately frozen semantic-interface branch. | Run root: `D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\sensor-qualification-v01\probe-execution-v01`; terminal receipt SHA `313fa8caeff0a479abdd335f840c954f551cbb9fa0491b88c5ace9e055f8ed3d`; qualification manifest SHA `ae755731c8b377b2672e9ce1aae3be0a1d8469b5e453475fc1297102a23190b0`. |
| **AR-04D sentinel exposure frontier** | Validated 25 crossed cells, 7 arms, 175 trajectories, and 735,000 decisions. K=16 cyclic beat blocked in 22/25 cells; K=64 and fresh were nearly tied on mean final V96 loss. | The result rejects a simple “freshest always wins” rule. The pooled K=16 arm used V2048 rather than V128, so its lower loss is not compute-matched evidence for support alone. | Design the V × reuse follow-up around compute-matched support allocation; execution authorization is not inferred here. Stop before adding Taylor cost, adaptive refresh, or unrelated controller tuning. | Integrity valid; run source commit `8fd4fbea3402aa492d45b0feb5c08685fd1a1873`; current worktree HEAD `0055876cb9b9c6ef7e34c58e3a90c8aef19e0d88`; validation receipt SHA `a1ce5558e796dbe8f20683794b44b22429552460f8fea4c637ee2cafe1402b1e` (see exact file at `C:\Users\shuga\.codex\worktrees\ar-04d-exposure-frontier-20260926\clean-rust\experiments\adaptive-runtime\ar-04d\artifacts\run-20260926-ar04d-v1\validation-receipt.json`). |
| **R&D-C** | Carry forward the Day 7 bounded authority/router results. | Not re-audited for this checkpoint. | Keep the prior bounded scope; no new claim or execution authorization is recorded here. | See [Day 7](day-07-research-state-2026-09-26.md). |

## What is now answered

1. **Can one shared frozen feature fabric support five useful narrow observers?** Yes, for the five registered tasks on E1 v04: every individual held-out gate passed and independently replayed.
2. **Did the observers qualify for routing design?** Yes. Did routing integration happen or receive authorization? No.
3. **Did S12 demonstrate selective intervention dependence?** Yes, at six tested sites in the fixed S11 population. Did it establish necessity or generalize to new worlds? No.
4. **Did Q-R2 establish one reliable scalar weight controller?** No; effects varied across paired trajectories.
5. **Did R1 achieve template-invariant semantic identity?** No; template-OOD and joint-OOD were terminal failures.
6. **Did AR-04D establish that fresher evidence is always better?** No; it points to support size and reuse spacing, with compute matching still needed.

## Storage and execution snapshot

At capture, C: had 348,788,555,776 bytes free and D: had 738,896,592,896 bytes free. The observer bundle adds about 832 MiB of shared features, 672,032 bytes of heads and scalers, and 9,436,019 bytes of score outputs. The scoring process used CPU only; it did not initialize CUDA. These free-space figures are point-in-time values and include unrelated activity.

**For all agents:** Keep Day 7 immutable and use this as the new carry-forward state. Preserve `authorized`, `executed`, `audited`, `qualified`, and `proposed` as separate states. The capability-fabric result earns an E4 routing-design proposal; it does not itself authorize E4 or a deployment claim.
