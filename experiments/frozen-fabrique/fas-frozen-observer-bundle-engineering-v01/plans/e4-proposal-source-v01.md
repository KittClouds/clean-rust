# E4 Proposal — Capability Fabric Routing and Integration

Sep 26, 2026 · @Craig Harvey

## Summary and authorization request

This proposal requests authorization for E4-0 and E4-A, plus two companion branches that share E4-0's fresh population. E4-B is design-frozen only; E4-C and E5 stay proposed.

E3 v02 qualified five frozen linear heads over one pinned LFM cache for routing design. E4 turns that qualification into a served system and measures what it costs. It does not refit, retune, or extend the E3 heads.

Three separate authorizations are requested, each with its own contract, seal, and stop conditions:

- **E4 (stages 0 and A):** fresh sealed population, online/cache parity, simultaneous fresh qualification, deterministic dispatch, and measured serving economics.
- **FF-BUNDLE-TEMPLATE-01:** does the qualified fabric survive structural rendering shift, compared against an R1-style surface on the same items?
- **FF-BUNDLE-ATTRIBUTION-01:** does the pretrained substrate contribute beyond lexical, embedding-only, and random-weight features, and how large is fit variance?

Not requested: E4-B execution, E4-C, E5, capability cartography, any E3 head refit or threshold change, reuse of E1 v04 TEST, or any deployment or product claim.

## Background: what E3 established

E3 v02 passed all eight individual gates on the sealed E1 v04 TEST panel (disposition `ALL_EIGHT_GATES_PASS_BUNDLE_QUALIFIED_FOR_ROUTING_DESIGN`). Each gate required a whole-quartet bootstrap one-sided 95% lower bound of at least 0.90. The weakest lower bound was 0.997724 (exact target, both novel).

| Quantity | Value |
| --- | --- |
| Substrate | `LiquidAI/LFM2.5-1.2B-Base`, pinned, frozen |
| Feature surface | `V1_FINAL_POSITION`, one immutable cache (832 MiB) |
| Heads | 5 linear heads, 147,528 parameters, 672,032 bytes with scalers |
| Extraction time | 3,402.17 s |
| Fit time, all five heads | 19.47 s |
| E3 score seal root | `a104bffedbc3e31268c0f1c0103ad4326add5a9da93816007904b70cdf3c7d1f` |

E3 established that one frozen cache supports five separately fitted observers that met their registered held-out gates on this population. It did not establish a simultaneous bundle guarantee, generalization beyond this task family, bundle-versus-standalone parity, serving latency, cost savings, or deployment value.

Four facts from E3 and the cross-lab state constrain E4's design:

- **The E3 test panel is spent.** The scored-row artifact holds opened TEST labels, so E1 v04 TEST is historical evidence only.
- **The cache is task-agnostic.** One final-position vector per row serves all five heads, so the item representation cannot say which task a caller wants.
- **E3's novelty is lexical, not structural.** Context and entity names vary; templates do not.
- **R1 failed on structure with the same LFM.** R1's semantic identity passed vocabulary-OOD but failed template-OOD and joint-OOD (mean balanced accuracy 0.4066 and 0.3843), using a different surface.

## Scope and branch structure

E4 stays about serving and routing; the two larger questions E3 raised get their own identities. The three branches share E4-0's fresh population and extraction infrastructure, but not their questions or gates.

| Branch | Question | E3 heads | Requested now |
| --- | --- | --- | --- |
| E4 routing and integration | Can the qualified bundle be served and selected correctly, and at what cost? | Frozen, scored only | E4-0, E4-A (E4-B design frozen) |
| FF-BUNDLE-TEMPLATE-01 | Does the fabric survive structural rendering shift, and is the difference from R1 a surface effect? | Frozen, scored only; R1-style comparator fitted | Yes |
| FF-BUNDLE-ATTRIBUTION-01 | Does pretrained computation contribute beyond cheap features? | New heads on alternative feature sources | Yes |

Out of scope for all three:

- Any refit, threshold change, head sharing, or view search on the E3 heads.
- A joint item-plus-request prompt, which would create a new representation surface and a new bundle version.
- Any reuse of E1 v04 TEST rows.
- Taylor scoring, controller work, capability cartography, and deployment or product claims.

## E4-0: preconditions

E4-0 produces a fresh sealed population, proves online features match the cache, and restates E3's qualification as a simultaneous bound on fresh data. Nothing downstream runs until all three pass.

### Fresh sealed population

Generate from the frozen E1 generator with new namespaced seeds, and seal before any model contact. Freeze and hash the held-out template set before generation; those templates must never appear in E1 or in any fit.

- **Seen-rendering stratum:** E1 templates, new items.
- **Lexical novelty strata:** context-novel, entity-novel, both-novel, matching E3's definitions.
- **Held-out-template stratum:** templates never used in E1.
- **Joint template-plus-lexical stratum:** included if affordable; see open decisions.

### Online/cache parity

E3 scored cached features; serving recomputes them, and the two are not automatically identical. The parity panel uses cached E1 v04 train/validation rows, compares features and predictions only, and opens no labels.

- Test each intended serving configuration: batch 1, the production batch size if batching exists, and each intended device path.
- Record the maximum absolute feature deviation and per-head prediction agreement.
- Gate: 100% prediction agreement per head, and maximum deviation within a declared tolerance ε. Cross-device bit identity is not required.

### Simultaneous fresh qualification

Score the five frozen E3 heads, with no refit, on the seen-rendering and lexical strata. Keep E3's metric, whole-quartet bootstrap, and 0.90 threshold, but Bonferroni-correct across the eight endpoints:

```latex
\alpha_i = \frac{0.05}{8}, \qquad \mathrm{LB}_{1-\alpha_i}(\mathrm{BA}_i) \ge 0.90 \quad \text{for all } i = 1,\dots,8
```

Passing yields a simultaneous bundle statement on fresh data. The held-out-template stratum is reported descriptively here; FF-BUNDLE-TEMPLATE-01 owns its primary analysis, so it is not gated twice.

## E4-A: deterministic dispatch and serving economics

E4-A serves the frozen bundle with the task supplied explicitly and measures the cost of each added capability. It is a systems baseline, not a routing test.

Each request carries a typed task contract, T ∈ {context-ID, entity-ID, relation, state, target}. The pipeline runs one extraction, looks up the registered head, and returns a typed result with a receipt that the validator replays.

Correctness invariants (all must hold):

- **Bundle-versus-standalone parity:** bundled serving returns the same outputs as each head served alone in its own process.
- **Offline parity:** dispatched outputs equal offline head outputs on the same features.
- **Zero misdispatch** and clean receipt replay on every request.

The core measurement compares two serving plans for k = 1 to 5 heads. B1 runs one extraction and k heads; B2 runs k separate extractions with one head each.

```latex
C_{\mathrm{B1}}(k) = C_{\mathrm{extract}} + \sum_{i=1}^{k} C_{H_i}, \qquad C_{\mathrm{B2}}(k) = \sum_{i=1}^{k} \left( C_{\mathrm{extract}} + C_{H_i} \right)
```

Report p50/p95 latency, throughput, peak memory, device utilization, and marginal latency and memory per added head. The headline metric is capability per extraction: the marginal cost of a head once extraction is paid. E4-A makes no accuracy claims beyond E4-0's qualification.

## E4-B: request routing (design frozen, execution later)

E4-B asks whether a router can infer which head a caller wants when the task is not supplied. It reads the request through a separate channel so E3's item extraction, and its qualification, stay untouched.

```latex
x_{\mathrm{item}} \rightarrow V_{\mathrm{E3}}(F_\theta) \rightarrow \{H_1,\dots,H_5\} \qquad q_{\mathrm{request}} \rightarrow R(q) \rightarrow \{1,\dots,5,\ \mathrm{abstain}\}
```

Requests are natural-language phrasings of the five tasks. Training and validation phrasings are separated from a held-out phrasing set, frozen and hashed before any router is fitted. In-template requests alone would make routing trivially lexical.

The router ladder stops at the first rung that meets the gate on held-out phrasings:

1. Oracle task ID (upper bound).
2. Schema or lexical router.
3. Linear router over frozen LFM features of the request text.
4. A richer router, only if rungs 2 and 3 fail.

If the lexical router passes, routing is solved by schema and a learned router is not justified. That is a useful closing result, not a failure.

Score routing as a vector, never as one accuracy:

- Route accuracy.
- Head accuracy given the correct route.
- End-to-end accuracy.
- Abstention rate.
- Misroutes that return a well-formed but meaningless output, counted separately.
- Routing cost per request.

## E4-C: applicability routing (proposed, separate authorization)

E4-C asks which heads can be trusted on a given item, which is the deeper routing question. It is selective prediction per head, using signals the heads cannot simply assert.

```latex
\mathbf{z}_j(x) = \left[\ \mathrm{margin}_j(x),\ \mathrm{dist}(x),\ \mathrm{density}(x),\ \mathrm{template\ novelty}(x),\ \dots\ \right] \ \rightarrow\ A_j(x) \in \{\mathrm{accept},\ \mathrm{abstain}\}
```

- Feature distance can be Mahalanobis distance from the training distribution in the cached feature space.
- Freeze each head's accept region on development data, then evaluate on a shifted population.
- Report risk-coverage curves and AUROC for separating correct from wrong head outputs, per head and stratum.

E4-C waits on two things. Heads are near-perfect in distribution, so a trust signal needs shifted inputs that produce errors; FF-BUNDLE-TEMPLATE-01 supplies that population. It also needs E4-A's serving path.

E4-C is the same trust-region problem E013 poses for model actions, applied to capability heads.

## Companion branches

### FF-BUNDLE-TEMPLATE-01: structural transfer

This is the highest-value experiment in the queue: it tests whether the qualified fabric survives a template shift, and whether R1's failure was an interface effect. A cross-lab comparison alone cannot isolate the surface, because R1 and the bundle also differ in tasks, serialization, and targets.

The matched design runs the same semantic items and the same held-out templates through two representation surfaces:

- **E3 final-position surface:** the frozen E3 heads, scored with no refit.
- **R1-style mean-pooled surface:** a matched fixed-class semantic observer, fitted on the same training items and templates as E3.

| Final-position | R1-style | Reading |
| --- | --- | --- |
| Survives | Fails | Surface/interface effect; the E3 surface becomes the candidate semantic interface for an R1 reopening (separate authorization) |
| Fails | Fails | Structural invariance not accessible under either surface; cartography claims bounded to seen templates |
| Survives | Survives | R1's earlier failure was task- or rendering-specific |

If an R1-style extraction cannot be applied to E1-style items, run the E3 surface alone and report it as a bundle result, with no cross-lab attribution.

### FF-BUNDLE-ATTRIBUTION-01: feature-source attribution

This branch asks whether pretrained LFM computation does the work, or whether cheaper features would qualify too. The same five head types, fit protocol, and splits run on four feature sources:

1. Lexical counts (bag of tokens, template ID).
2. Frozen input token embeddings, pooled, before any transformer layer.
3. The same LFM architecture with random weights.
4. The pretrained LFM final-position cache.

The primary strata are context-novel, entity-novel, both-novel, and template-novel. If the pretrained source only ties the lexical baseline everywhere, the fabric remains valid engineering but does not show pretrained computation is necessary. A gap that opens under novelty supports attribution to the substrate.

This branch also measures fit variance. Refit each head type across several seeds and data subsamples, for every source, so within-task fitting variance is known before any between-source or between-capability comparison.

## Downstream links

None of these is requested here; they are recorded so E4's artifacts are built to serve them.

- **E5 composition.** Chain heads in two stages: teacher-forced, with correct upstream intermediates, then free-running, with predicted ones. Decompose final correctness against per-stage reliability. This is the sensor reliability R1's search machine needs.
- **E013 correctness probe.** Reuse the bundle pipeline (pinned substrate, immutable cache, linear heads, whole-unit bootstrap gates) as a trust signal for coding actions. The probe reads task plus candidate, one extraction per candidate, and competes with execution, stability, and token-margin signals on the same development bank.
- **Evaluation policy for cartography.** AR-04C/D already rule out adapting repeatedly against one exposed panel. Cartography must use multiple independent panels, log exposure per panel, and keep an untouched terminal confirmation population. How aggressively panels can be reused waits for AR-04E.

## Predeclared outcomes and stop conditions

Every stage has a declared result for pass and for fail, and every failure is preserved rather than repaired in place.

| Stage | If it passes | If it fails |
| --- | --- | --- |
| E4-0 parity | Proceed to qualification | Stop; diagnose extraction determinism under a new version |
| E4-0 fresh qualification | Simultaneous bundle statement on fresh data; E4-A may start | Stop; preserve; no refit or threshold change |
| E4-A invariants | Report the B1/B2 cost curve and capability per extraction | Stop on any misdispatch, parity break, or replay failure |
| E4-B lexical rung | Routing closed as schema-solved | Continue to the linear request router |
| E4-B linear rung | Frozen-fabric request routing supported | Routing needs explicit task contracts, or a richer router under new authorization |
| TEMPLATE-01 | See its outcome table | See its outcome table |
| ATTRIBUTION-01 | Pretrained gap under novelty supports substrate attribution | Tie with lexical: engineering valid, substrate not shown necessary |

Standing stop rule: any change to heads, views, thresholds, templates, or fit data requires a new version and a new authorization.

## Execution order and authorization states

E4-0 runs first; the two companion branches then run in parallel with E4-A on the same population. States follow the Day 7 convention: authorized, executed, audited, qualified, and proposed are kept separate.

| Order | Stage | Depends on | State if this proposal is approved |
| --- | --- | --- | --- |
| 1 | E4-0 | Nothing | Authorized |
| 2 | FF-BUNDLE-TEMPLATE-01 | E4-0 population | Authorized |
| 2 | FF-BUNDLE-ATTRIBUTION-01 | E4-0 population | Authorized |
| 2 | E4-A | E4-0 parity and qualification | Authorized |
| 3 | E4-B | E4-A complete | Proposed, design frozen |
| 4 | E4-C | E4-A and TEMPLATE-01 | Proposed |
| 5 | E5 | E4-A | Proposed |

The E013 correctness probe and the AR-04E evaluation policy proceed in their own labs and are not gated by this proposal.

## Open decisions before freeze

These must be settled in the frozen contracts; none should be chosen after contact with the fresh population.

- [ ] Parity tolerance ε, and which device and batch configurations are production-intended.
- [ ] Keep the 0.90 qualification threshold, or tighten it given observed lower bounds near 0.998.
- [ ] Population size per stratum, sized for the Bonferroni-corrected bounds.
- [ ] Size and construction of the held-out template set; whether the joint template-plus-lexical stratum is affordable.
- [ ] Whether an R1-style mean-pooled extraction can be applied to E1-style items.
- [ ] Default request channel for E4-B: frozen-LFM request extraction or a schema parser.
- [ ] Whether E4-A may still run as a systems-only measurement if fresh qualification fails.
