# Focused Paper-to-Contract Sprint v1

## Decision

The six papers define five different research axes, not one interchangeable
leaderboard:

1. CompGCN changes typed message construction by jointly composing entities and
   relations.
2. StarE adds statement-scoped qualifier sets while preserving the distinct
   roles of the primary triple and qualifier pairs.
3. TGB 2.0 defines future temporal evaluation, hard negative domains, online
   history, and scalability pressure.
4. HypeTKG combines explicit timestamps, qualifiers, and optional time-invariant
   facts, but evaluates interpolation rather than forecasting.
5. NBFNet changes node encoding into query-conditioned path dynamic programming.
6. ULTRA lifts relations into a second graph so the NBFNet machinery can transfer
   across unrelated relation vocabularies.

Phoenix must introduce these axes one at a time. A model may advance the ladder
only against the same frozen task and evaluator as its predecessor. Scores from
static completion, temporal interpolation, temporal forecasting, sampled
ranking, full ranking, transductive graphs, and unseen graphs are separate
claims with separate identities.

The immediate learned-model ticket is **Temporal CompGCN Link Predictor v1**.
It changes one axis above the proven Temporal R-GCN while retaining the current
Smallpedia source, chronological task, structural baseline, exact all-entity
evaluator, locked test partition, and mmap artifact boundary. The immediate
data/evaluator ticket after it is **Canonical Hyper-Relational Link Prediction
Task v1** over the already frozen WD50K statement artifact.

## Primary-source audit

| Paper | Audited source | Experimental regime that Phoenix records |
| --- | --- | --- |
| CompGCN | [ICLR 2020 / arXiv 1911.03082](https://arxiv.org/abs/1911.03082) | Static transductive multi-relational completion |
| StarE | [EMNLP 2020](https://aclanthology.org/2020.emnlp-main.596/) | Static transductive hyper-relational completion |
| TGB 2.0 | [NeurIPS 2024 / arXiv 2406.09639](https://arxiv.org/abs/2406.09639) | Chronological temporal future-link prediction |
| HypeTKG | [Findings of EMNLP 2024](https://aclanthology.org/2024.findings-emnlp.20/) | Hyper-relational temporal interpolation |
| NBFNet | [NeurIPS 2021 / arXiv 2106.06935](https://arxiv.org/abs/2106.06935) | Static transductive and fixed-relation inductive completion |
| ULTRA | [ICLR 2024 / arXiv 2310.04562](https://arxiv.org/abs/2310.04562) | Static zero-shot induction across entity and relation vocabularies |

The complete papers, including appendices, were inspected. The contracts below
extract executable operations, discriminating ablations, data assumptions,
leakage hazards, and evaluator obligations. Paper claims and Phoenix decisions
are deliberately separated.

## Contract card 1: CompGCN

### Paper operation

CompGCN augments every original edge with an inverse edge and every node with a
self-loop. It learns entity and relation states jointly. For node `v`, one layer
computes:

`h_v = f(sum_(u,r in N(v)) W_direction(r) * phi(x_u, z_r))`

The direction map selects one of three matrices for original, inverse, or
self-loop messages. `phi` is a relation composition operator. The paper tests
subtraction, elementwise multiplication, and circular correlation. Relations
are advanced to the next layer through a shared projection:

`h_r = W_rel * z_r`

The encoder is independent of the decoder. The paper combines it with TransE,
DistMult, and ConvE scoring. Link-prediction training uses binary cross-entropy
with label smoothing. Relation bases reduce parameters; they are an optional
compression, not part of the semantic definition.

### Ablations Phoenix must preserve

- No graph encoder versus Directed-GCN, R-GCN, Weighted-GCN, and CompGCN under
  the same decoder.
- `sub`, `mult`, and `corr` composition under the same decoder.
- Entity-only propagation versus joint entity/relation propagation.
- Full relation parameters versus fixed basis counts.
- Performance as the relation inventory grows.
- One-to-one, one-to-many, many-to-one, and many-to-many relation slices.

The paper's relation-count experiment retains only the most frequent relation
types. Phoenix records it as a data-pruning ablation, not as proof of runtime
scaling at fixed data volume.

### Dataset assumptions

- FB15k-237 and WN18RR are static, transductive graphs.
- Entities and relations are known at train time.
- The source benchmarks removed common inverse shortcuts, but the model derives
  inverse edges internally.
- Evaluation is filtered head and tail completion over the complete entity set.
- The paper reports MRR, MR, and Hits@N.

### Leakage and validity shields

- Derived inverse and self edges are created only after the visible split graph
  is selected. Creating them over the complete corpus would leak held-out facts.
- A target edge and its derived inverse are both excluded from that training
  example's message graph.
- Filtered truth may use evaluator-private validation/test facts to avoid false
  negatives, but those facts never enter model features or topology.
- Decoder, composition operator, basis count, and relation inventory are model
  selection inputs and therefore validation-only.

### Phoenix adoption

Temporal CompGCN v1 reuses the current train-only typed adjacency and changes
only the learned residual:

- keep the exact structural frequency prior and canonical score formula;
- add one learned vector per directed relation;
- compose each neighbor state with its relation state before the existing
  direction transform;
- advance relations through a shared `W_rel` once per layer;
- start with elementwise multiplication because it maps directly to the current
  bounded SIMD kernel;
- retain subtraction and exact circular correlation as required ablation arms;
- add no relation-batch sidecar unless measured staging copies are material.

Acceptance requires exact same-task validation against the frozen R-GCN, not a
comparison to numbers copied from the paper.

## Contract card 2: StarE

### Paper operation

StarE represents a statement as `(s, r, o, Q)`, where `Q` is an arbitrary set
of qualifier `(relation, entity)` pairs. It does not flatten qualifiers into new
relation types and does not erase the special role of the primary triple.

For one statement it computes a position-invariant qualifier state:

`h_q = W_q * sum_(q_r,q_v in Q) phi_q(h_qr, h_qv)`

It merges `h_q` with the primary relation through `gamma`, tested as
concatenation, elementwise multiplication, or a weighted sum. The resulting
message is:

`phi_r(h_u, gamma(h_r, h_q))`

Messages are aggregated at the destination. Inverse facts retain the same
qualifier set. The link-prediction system then linearizes the query, applies a
Transformer/pooling/fully connected decoder, and scores the entity matrix.

The paper's sparse representation is already close to Phoenix's source
artifact: one COO-like primary fact table, one qualifier table, and a shared
fact index. Memory is `O(|E| + |Q|)`, not a dense entity-by-entity matrix.

### Ablations Phoenix must preserve

- Triple-only decoder versus qualifier-aware decoder.
- Decoder alone versus StarE encoder plus the identical decoder.
- Qualifier-bearing statement ratios near 33%, 66%, and 100%.
- Maximum retained qualifiers from one through six.
- `gamma` as concatenate, multiply, and weighted sum.
- Original versus cleaned JF17K.
- Hyper-relational data versus a triple-only collapse that deduplicates equal
  primary triples.
- Metrics by exact qualifier count and by whether a queried statement has any
  qualifiers.

The paper observed saturation after two qualifiers. Phoenix treats this as an
ablation result to challenge, not a truncation license.

### Dataset assumptions

- WD50K uses official random train/validation/test partitions and has no time
  semantics.
- WD50K contains 236,507 statements; 32,167 have qualifiers.
- Thousands of entities and dozens of relations occur only in qualifiers.
- Literals were removed, low-frequency entities were dropped, and test rows
  with unseen entities or relations were removed.
- The task predicts primary subjects/objects; qualifiers are context.
- The paper reports filtered MRR and Hits@1/5/10.

### Leakage and validity shields

StarE found that roughly 44.5% of JF17K test statements shared their primary
triple with training statements. Phoenix rejects JF17K as an authoritative
selection dataset unless it is independently cleaned and re-certified.

WD50K removed train and validation statements whose exact primary triple occurs
in test, but the appendix still found direct or semantic inverse shortcuts in
under 4% of test statements. Therefore Phoenix additionally certifies:

- exact primary-triple overlap;
- direct inverse overlap;
- source-declared semantic inverse overlap;
- complete statement duplication, including reordered qualifier sets;
- entity and relation role inventories per split.

A statement is the split atom. Its qualifier pairs may never be split,
independently shuffled into another partition, or attached to a derived inverse
with a different fact identity.

### Evaluator contract

- Preserve the official WD50K partitions and all qualifier-only identifiers.
- Canonicalize qualifier order for serialization while hashing the original
  order and proving encoder permutation invariance separately.
- Evaluate head and tail completion with exact filtered ranks.
- Report paper-parity Hits@5 in addition to Phoenix Hits@1/3/10.
- Report full-candidate and role-constrained-candidate metrics as different
  certificates; never substitute one for the other.
- Slice by qualifier presence, qualifier count, primary relation, and
  main-position versus qualifier-only candidate provenance.

### Phoenix adoption

The frozen external dataset already stores fixed-width fact rows with qualifier
offset/count ranges. No new source representation is needed. The next artifact
is a compact task view containing canonical head/tail queries, statement IDs,
borrowed qualifier ranges, filtered truth ranges, and an implicit candidate
universe. It must not materialize repeated qualifier arrays or dense negatives.

## Contract card 3: TGB 2.0

### Paper operation and task semantics

TGB 2.0 splits every dataset chronologically 70/15/15 and keeps all edges from
one timestamp in exactly one partition. It evaluates dynamic link prediction at
a future time. TKG queries predict both directions by deriving inverse
relations; THG queries predict tails.

The protocol is single-step online prediction: predict the next timestamp, then
make its ground-truth facts visible before predicting the following timestamp.
The filtered rank removes other facts true at the query timestamp. Ties receive
average rank.

Small TKGs use 1-vs-all. Large graphs use pre-generated, reproducible 1-vs-q
negatives. Random negatives made the task too easy, so TGB samples destinations
from the query relation's observed destination domain, or from the destination
node type for heterogeneous graphs. The appendix shows that this strategy is
closer to 1-vs-all than random sampling while still optimistic.

### Ablations and controls Phoenix must preserve

- 1-vs-all versus type-aware 1-vs-q versus random 1-vs-q.
- Relation-aware models versus the identical model with relation type removed.
- Recurrency Baseline and both finite-window and all-history EdgeBank.
- Per-relation results paired with relation recurrency.
- Direct recurrency, any-past recurrency, consecutiveness, and inductive-node
  cohort slices.
- Runtime, peak host/GPU memory, OOM, and OOT as first-class results.

TGB's strongest scientific warning is not a model score: simple recurrence
heuristics remain competitive, while most learned methods fail on the largest
graphs. A learned rung that does not beat the certified train-only recurrence
ladder does not advance.

### Dataset assumptions

- TKGs have discrete timestamps; THGs use continuous event time.
- The new datasets range from 550,376 to 53,632,788 temporal edges.
- Test sets contain new nodes, relation distributions are highly skewed, and
  recurrence varies drastically by relation and dataset.
- Smallpedia and Wikidata also provide static edges. Static dump truth is a
  separate information source, not automatically historical truth.
- The paper uses full candidates where feasible and q of 1,000, 100, or 20 on
  larger datasets.

### Leakage and validity shields

- Timestamp groups are indivisible split units.
- Evaluation negative-domain tables may inspect the full benchmark to match the
  official protocol; training samplers may inspect train facts only. The two
  artifacts have different identities and APIs.
- Online validation/test history is visible only after its timestamp has been
  scored. Each visibility transition is receipt-bound.
- Static Wikidata rows require an observation/source date before they may enter
  temporal training. `is_static` does not mean `known in the past`.
- Relation inverses are derived after the visible temporal cut.
- Full-ranking, sampled-ranking, cold-history forecasting, and single-step
  online forecasting remain distinct certificates.

### Phoenix status

The canonical Smallpedia task already proves official ordered negative parity,
time-aware filtering, inverse-query derivation, average tie rank, immutable test
locking, and exact all-entity validation. It exceeds the paper's minimum by
using all 47,433 dynamic candidates for 4.802 billion validation scores. TGB 2.0
therefore contributes new cohort/resource requirements, not a replacement
evaluator.

## Contract card 4: HypeTKG

### Paper operation

HypeTKG represents a fact as `((s, r, o, t), Q)`: an explicit timestamp plus a
set of qualifier pairs.

Its qualifier-attentional time-aware graph encoder (QATGE):

- composes each qualifier relation/entity pair;
- applies element-wise attention conditioned on the primary relation;
- aggregates temporal neighbors;
- gates the amount of primary-relation versus qualifier information;
- represents time with learned cosine features.

Its qualifier matching decoder (QMD):

- encodes query qualifiers with a qualifier-wise Transformer;
- retrieves qualifiers on other observed facts sharing the query subject;
- attentively builds a global subject-qualifier feature;
- combines subject/time, relation, query qualifiers, and global qualifiers in a
  query-wise Transformer;
- scores every candidate with a learned bilinear form.

HypeTKG-psi adds time-invariant facts through a separate gated graph path and a
time-invariant-neighbor Transformer. Training is one-vs-all binary
cross-entropy over corrupted object entities.

### Ablations Phoenix must preserve

- No qualifier information.
- Qualifier information without QATGE attention.
- Qualifier information without the QMD matcher.
- Full qualifiers with no time model.
- 0%, 25%, 50%, 75%, and 100% retained qualifiers.
- Varying proportions of qualifier-bearing facts.
- With and without time-invariant facts.
- Query-local qualifiers versus subject-related qualifiers from other visible
  facts.

The paper's table isolates all three essential components: time, qualifier
attention, and qualifier matching. A Phoenix temporal hyper-relational model
must report the same factorial controls.

### Dataset assumptions

- Wiki-hy derives from Wikidata11k and spans years 1513-2020.
- YAGO-hy derives from YAGO1830 and spans years 1830-2018.
- Only about 9.59% and 6.98% of their facts, respectively, have qualifiers.
- Qualifiers are retrieved from Wikidata through relation mapping and API
  lookup; added qualifier-only entities and relations join the model universe.
- YAGO1830 was originally extrapolative. The authors redistribute it into an
  interpolation benchmark before qualifier lookup.
- The experiments are explicitly temporal interpolation, not future
  forecasting.
- Time-invariant facts are made available during training, validation, and
  test.

### Leakage and validity shields

HypeTKG's results cannot be cited as temporal forecasting evidence. In its
interpolation regime, facts after a query timestamp may be observed. Phoenix
uses a task-regime field that makes this difference identity-bearing.

Further shields are required because qualifier and time-invariant facts are
looked up from an external knowledge base:

- bind the exact Wikidata snapshot and lookup receipt;
- record `observed_at` separately from the fact's asserted validity time;
- make subject-related qualifier retrieval obey the task's visibility cut;
- prevent validation/test query facts from contributing qualifier context;
- keep time-invariant relations in a separate typed graph with provenance;
- reject any forecasting artifact whose auxiliary facts were observed after
  the prediction cutoff;
- certify raw fact and inverse overlap after the YAGO redistribution.

### Evaluator contract

Phoenix may support an official-parity interpolation task, but it receives a
different task schema from temporal forecasting. Both require full head/tail
filtered MRR and Hits@1/3/10, qualifier-presence/count slices, time-range slices,
and the complete time/attention/matcher ablation grid. Only the forecasting task
may compete with the current Temporal R-GCN ladder.

## Contract card 5: NBFNet

### Paper operation

NBFNet defines a query-conditioned representation of `(source, target)` as a
generalized sum over path representations, where each path is a generalized
product of its edge representations. A generalized Bellman-Ford recurrence
avoids enumerating paths.

The neural form learns three operators:

- `INDICATOR(source, node, query_relation)` sets the boundary condition;
- `MESSAGE(previous_node_state, query-conditioned_edge)` extends paths;
- `AGGREGATE(messages plus boundary)` combines paths.

Every node state is conditioned on the source and query relation; it is not an
ordinary reusable node embedding. The paper considers TransE, DistMult, and
RotatE-style messages and sum, mean, max, or PNA aggregation. Edge states are
query-conditioned and layer-specific. One propagation for `(source, relation)`
scores every candidate target.

Training corrupts a positive head or tail, minimizes positive/negative log
loss, and drops the direct query edge so the model must use longer paths. The
implementation fuses MESSAGE and AGGREGATE, reducing message memory from
`O(|E|d)` to `O(|V|d)`. Inference for one grouped query is
`O(|E|d + |V|d^2)` under the paper's formulation.

### Ablations Phoenix must preserve

- MESSAGE operator crossed with AGGREGATE operator.
- Sum/mean/max against PNA.
- Two, four, six, and eight Bellman-Ford iterations.
- One-to-one, one-to-many, many-to-one, and many-to-many relations.
- Direct-edge present versus removed during training.
- Transductive versus genuinely inductive graphs.
- Fused propagation versus explicit-message memory and runtime.

The paper finds performance saturating around six layers. Phoenix treats depth
as a measured model-selection arm and records the reachable-path distribution;
it does not hard-code six.

### Dataset assumptions

- Static completion uses FB15k-237 and WN18RR with full filtered ranking.
- The inductive benchmark has unseen entities but retains the relation
  vocabulary.
- Its published inductive metric ranks against 50 negatives and reports
  Hits@10, while the transductive task uses all filtered candidates.
- The paper's appendix states that the inductive validation set is actually
  transductive and shares the training fact graph; only test has unseen entities
  and fact/query triples.

### Leakage and validity shields

- Phoenix does not use that shared-graph validation protocol to select a model
  claimed as inductive. Selection requires a disjoint validation support graph.
- The target edge, its inverse, and duplicate equivalent facts are removed from
  the message graph for every training example.
- Temporal NBFNet constructs support only from facts visible before the query,
  or from earlier online-scored timestamps under the TGB protocol.
- Evaluator-private filtered truths do not enter the Bellman-Ford support graph.
- Path explanations name only visible support edges and bind their source fact
  identities.

### Evaluator and runtime contract

- Full filtered MRR and Hits@1/3/10 remain authoritative; 50-negative Hits@10
  is a separately labeled paper-parity metric.
- Score all candidates once per unique `(timestamp, source, directed_relation)`
  group and reuse that propagation for all positive destinations.
- Report propagation, candidate projection, ranking, hashing, peak working set,
  and allocation volume separately.
- Certify path-depth and relation-arity cohorts.
- Require fused propagation to avoid an edge-by-feature message arena.

### Phoenix adoption

The current canonical query grouping and all-entity evaluator fit NBFNet better
than a per-triple API. The existing typed train adjacency is the first input.
A new path sidecar is forbidden until profiling proves repeated temporal
visibility cuts cannot be served by bounded indexes over the current mmap
topology.

## Contract card 6: ULTRA

### Paper operation

ULTRA creates a graph whose nodes are relation types, including inverses. Two
relation nodes are connected by one of four typed interactions observed in the
entity graph:

- tail-to-head;
- head-to-head;
- head-to-tail;
- tail-to-tail.

The resulting adjacency has shape `|R| x |R| x 4` and can be derived with sparse
matrix multiplication. A relation-level NBFNet labels the query relation with a
vector of ones and produces every relation's representation relative to that
query. An entity-level NBFNet then uses the query relation state as its source
indicator and transforms all conditional relation states per layer before
scoring candidate entities.

No entity IDs, relation IDs, text features, or pretrained vocabulary are model
parameters. Training mixes graphs, samples a graph in proportion to its train
edge count, and applies binary cross-entropy to head/tail corruptions.

### Ablations Phoenix must preserve

- Pretrained zero-shot versus training from scratch versus fine-tuning.
- One, two, three, four, five, six, and eight pretraining graphs.
- Four typed relation interactions versus a homogeneous relation graph.
- Query-conditioned relation encoding versus unconditional GNNs initialized by
  ones or random features.
- Full-candidate metrics versus Hits@10 against 50 random negatives.
- Entity-inductive versus entity-and-relation-inductive target graphs.

The paper reduces training steps for mixtures of five or more large graphs to
fit a three-day budget. Phoenix records step count and examples seen so the
reported saturation after three graphs is not treated as a clean mixture-size
causal result.

### Dataset assumptions

- The main model is pretrained on FB15k-237, WN18RR, and CoDEx-Medium.
- It is evaluated over 57 graphs: transductive, unseen-entity, and
  unseen-entity-plus-relation families.
- Zero-shot runs are deterministic; fine-tuning reports five seeds and chooses
  checkpoints by validation MRR.
- Graph sizes range from roughly one thousand to 120 thousand entities and up
  to about two million inference edges.
- Some target benchmarks are variants or subsets of the same source families
  as pretraining graphs. Vocabulary disjointness alone is not source-lineage
  disjointness.

### Leakage and validity shields

- A cross-graph certificate includes raw source lineage, not only remapped node
  and relation IDs.
- Pretraining and target graphs are audited for exact facts, inverse facts,
  entity aliases, relation aliases, and upstream-family overlap.
- The relation-interaction graph is derived from the target support graph only.
  Held-out query edges may not create interaction edges.
- Pretraining-mixture selection uses held-out development graphs; target test
  graph performance never chooses the mixture.
- Fine-tuning and zero-shot are separate model artifacts and claims.
- A relation vocabulary is "unseen" only if its semantic mapping and upstream
  lineage are also declared; arbitrary integer remapping is insufficient.

### Evaluator contract

- Full filtered head/tail MRR and Hits@1/3/10 are authoritative.
- Sampled Hits@10 remains a compatibility metric because ULTRA itself shows
  that 50 random negatives substantially overestimate performance.
- Report graph-macro, query-micro, and per-graph results; a large graph may not
  dominate the cross-graph score silently.
- Report zero-shot results separately for unseen entities, unseen relations,
  both unseen, and upstream-family-disjoint graphs.
- Certify relation-graph construction time/bytes, entity propagation time,
  candidate scoring, peak working set, and graph-size failure boundaries.

## Cross-paper task taxonomy

| Task identity field | Static KG | Hyper-relational KG | Temporal interpolation | Temporal forecast | Cross-graph zero-shot |
| --- | --- | --- | --- | --- | --- |
| Primary fact | `(s,r,o)` | `(s,r,o,Q)` | `(s,r,o,t,Q)` | `(s,r,o,t[,Q])` | Target support plus held-out queries |
| Future facts visible | N/A | N/A | May be visible | Never before cutoff | Only declared support graph |
| Split atom | Triple | Whole statement | Whole timestamped statement | Timestamp group | Whole graph lineage |
| Model support | Train graph | Train statements | Interpolation-observed graph | Train/online-past graph | Target support graph |
| Authoritative candidates | Full entities | Full or role-certified, labeled | Full entities | Full/type-aware certified | Full target entities |
| Principal evidence | Filtered MRR/Hits | Filtered MRR/Hits plus qualifier slices | Labeled interpolation score | Chronological online score | Macro/micro zero-shot score |

No score certificate is comparable unless every column relevant to the task has
the same value.

## Common leakage audit v2

Every future graph task must certify all applicable checks before training:

1. Source bytes, upstream version, license notice, and source lineage are frozen.
2. Split units are atomic: timestamp groups, statements with qualifiers, or
   entire target graphs cannot straddle partitions.
3. Train topology contains train-visible facts only.
4. Each training positive and its inverse/equivalent forms are masked from its
   message topology.
5. Qualifier lookup and subject-context lookup obey the same visibility cut.
6. Static or time-invariant facts carry observation provenance and cannot be
   backdated from validity semantics.
7. Evaluation filters may know held-out truth; model features and samplers may
   not read evaluator-private truth.
8. Negative-domain construction states whether it is train-only, full-benchmark
   official parity, type-aware, relation-aware, sampled, or full-candidate.
9. Hyperparameter and checkpoint selection are validation-only.
10. Pretraining and target graph lineages are checked for structural and
    semantic overlap.
11. Test access remains one-shot, durable, and task-wide.
12. Any weaker paper-parity protocol is labeled and cannot replace the stronger
    Phoenix certificate.

## Evaluator requirements v2

The exact Phoenix evaluator remains the authority and gains orthogonal report
dimensions rather than per-model scoring code:

- exact average-tie filtered rank;
- full candidate universe whenever physically feasible;
- official sampled candidates only as a separate identity;
- MRR and Hits@1/3/10, plus paper-required Hits@5 where applicable;
- per-relation and relation-arity cohorts;
- recurrence and inductive-node cohorts for temporal tasks;
- qualifier presence/count and qualifier-only-identifier cohorts;
- seen/unseen entity, relation, and graph-lineage cohorts;
- graph-macro and query-micro cross-graph aggregation;
- scorer, propagation, ranking, stream/hash, allocation, mmap, working-set,
  wall-time, OOM, and OOT accounting;
- exact score digest and certificate reproducibility across restart.

Model-native forward results are never the score authority. Models emit scores;
the frozen SIMD evaluator owns ranks, filters, metrics, hashes, and certificates.

## Artifact consequences

### Reuse without new sidecars

- CompGCN consumes the existing Smallpedia train facts, typed adjacency, query
  grouping, model artifact, and evaluator.
- StarE consumes the existing WD50K fact/qualifier mmap ranges.
- NBFNet begins from the existing typed adjacency and grouped query surface.
- Every rung reuses frozen model, selection ledger, test lock, and score
  certificate machinery.

### New artifacts justified by semantics

1. `phoenix-canonical-hyper-relational-link-prediction-task/v1`
   - WD50K statement IDs, split, head/tail query records, borrowed qualifier
     ranges, filtered truth, candidate-role policy, and official-parity receipt.
2. `phoenix-temporal-hyper-relational-task/v1`
   - only after a source with defensible timestamp and qualifier provenance is
     frozen; interpolation and forecasting use different schemas.
3. `phoenix-relation-interaction-graph/v1`
   - only for ULTRA, only if profiling proves deriving the four sparse
     interactions from frozen support topology is material across restarts.

No dense feature sidecar, materialized negative matrix, duplicated qualifier
arena, or pre-expanded inverse graph is authorized by these papers.

## Experimental ladder

### Rung 0: certified controls

- Relation/destination frequency, finite-window recurrence, all-history
  recurrence, and EdgeBank.
- Existing frozen Temporal R-GCN.
- Exact full-candidate evaluator and current three-second validation gate.

### Rung 1: Temporal CompGCN v1 — immediate

- Same source, task, structural prior, seed protocol, evaluator, and test lock.
- Joint relation state and entity/relation composition only.
- `mult`, `sub`, and `corr` arms; no decoder replacement in the first result.
- Must beat frozen R-GCN validation MRR and not regress calibration/resource
  gates materially.
- Same-seed weights, scores, digest, certificate, and model ID reproduce.

### Rung 2: Static StarE v1

- First build Canonical Hyper-Relational Link Prediction Task v1 on WD50K.
- Compare triple-only, qualifier-decoder-only, and StarE encoder arms.
- Require gains on qualifier-bearing statements, not only aggregate MRR.
- Keep the model static; do not fabricate timestamps.

### Rung 3: Temporal qualifier composition

- Import Wiki-hy/YAGO-hy only as labeled interpolation benchmarks.
- Seek or construct a separately frozen forecasting-grade
  timestamp-plus-qualifier corpus before making a future-prediction claim.
- Factor time, qualifier attention, qualifier matching, and time-invariant
  knowledge independently.

### Rung 4: Temporal NBFNet

- Query-conditioned path propagation over train/online-visible topology.
- Full candidates, direct-edge masking, fused message/aggregate kernel.
- Must beat CompGCN and recurrence controls under the same temporal task.

### Rung 5: ULTRA-style cross-graph transfer

- Frozen multi-graph pretraining mixture and graph-lineage holdouts.
- Relation interaction graph derived from support facts only.
- Zero-shot evaluation on entity-and-relation-unseen graphs with full ranks.
- Must beat training-free structural controls and per-graph trained baselines
  under both graph-macro and query-micro aggregation.

## Immediate ticket: Temporal CompGCN Link Predictor v1

### Scope

Replace the R-GCN residual message `W_r h_u` with the CompGCN message
`W_direction phi(h_u, z_r)` and advance `z_r` through `W_rel`. Preserve every
other production boundary.

### Proof matrix

1. Existing R-GCN artifact and certificate remain the frozen control.
2. A no-composition compatibility arm reproduces the R-GCN score bits.
3. Multiplication, subtraction, and circular-correlation arms receive distinct
   architecture and model identities.
4. Joint relation updates are compared with frozen relation states.
5. Validation reports aggregate, per-relation, arity, recurrence, and
   inductive-node cohorts.
6. Direct and inverse positive edges are absent from each training message view.
7. Training and restart resource receipts include relation-state bytes and
   composition-kernel time.
8. No test query is opened.

### Stop conditions

- If the current typed adjacency forces no material copies, add no relation
  sidecar.
- If circular correlation needs an FFT that changes canonical `f32` operation
  order across platforms, keep it as a separately identified research arm; do
  not weaken reproducibility of the multiplication arm.
- If CompGCN cannot beat the frozen R-GCN after a certified configuration/seed
  ladder, retain the negative result and move to the qualifier task. Do not tune
  on test or hide behind a different evaluator.

## North-star conclusion

The long-term model is not "the biggest GNN." It is a certified relational
reasoner that can compose relation state, retain qualifier roles, obey temporal
visibility, aggregate useful paths, and transfer those operations to unseen
graphs. The papers suggest that architecture. They do not justify building it
all at once.

Phoenix's advantage is the research substrate the papers commonly lack: frozen
source and topology identities, train-only derivation, exact mmap artifacts,
one-shot test authority, full-candidate SIMD ranking, exact score digests, and
restart-reproducible certificates. The next scientific gain should come from
one isolated model operation, beginning with CompGCN composition, while those
boundaries remain unchanged.
