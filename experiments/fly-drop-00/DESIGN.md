# FLY-DROP-00 — Initial Design

**Status:** initial design notes, superseded by `PROTOCOL.md` v0.1 and its
pretraining seal. No learner has been trained and no scientific outcome has
been inspected. This remains separate from `experiments/drosophila-heresy/`;
Jev is deferred.

## Question

Does a frozen, directed connectivity-derived mixing operator produce a
reproducible computational effect inside an otherwise ordinary learner, and
does that effect differ from sparse-graph and topology controls?

This is an engineering/computational test of one source table and one host task.
It is not a claim about fly cognition, biological function, or general AI
performance.

## Source and scope

The local MaleCNS v1.0, minimum-confidence 0.5 source is already present at
`D:\drosophila-heresy\data`. Its recorded SHA-256 receipts are preserved in
`preflight/source-census.json`. The connection table has 151,856,684 rows and
weight sum 311,833,243. The official download documentation describes this file
as segment-to-segment connection strengths for all segments, not a neuron-only
adjacency table ([MaleCNS download page](https://male-cns.janelia.org/download/)).
The source census observed 88,384,522 distinct endpoint IDs and 88,404,403 IDs
after adding annotated bodies, so most source IDs are outside the annotation
table.

The default interpretation of “literal connectivity” for this experiment is
the complete directed connection table: retain every source row, with no
hemisphere, cell-class, or `Traced`-status filter. This includes source rows
whose bodies are unannotated or not classified as neurons. The resulting
operator must therefore be described as the MaleCNS segment-connection-table
operator, not as a neuron-only or biologically complete brain model. The 88M
node-ID universe and its resource cost must be qualified before a run.

The preflight also measured the traced-to-traced induced subgraph: 165,122
traced bodies and 25,563,197 edge rows. That is a diagnostic showing what a
traced-only filter would remove; it is not the default operator for this study.

## Operator contract to freeze

- Direction is `body_pre -> body_post`; source weights are retained as positive
  connection strengths. No neurotransmitter sign or cell-type interpretation
  is added.
- Repeated source rows are accumulated as weights for the same directed pair.
- Normalize each destination's incoming weights by its total incoming weight;
  destinations with no incoming weight emit zero. This is the sole activation
  normalization and is fixed before any task outcomes are accessed.
- No learned rewiring, selected pathway, internal activation, plasticity rule,
  task label, or eligibility mechanism is placed inside the operator.
- A 128-dimensional host is the proposed starting width. Input/output adapters
  are frozen, shared across the graph arms, and have no trainable parameters.
  Their exact sparse projection rule and seed schedule remain to be frozen.

## Arms

1. Ordinary learner with no inserted operator (identity path).
2. Same learner with a frozen ordinary dense 128-by-128 mixer.
3. Same learner with a random directed sparse graph matched to the fly graph's
   node and edge-row budgets and source weight multiset.
4. Same learner with a degree-preserving shuffled fly graph.
5. Same learner with the literal MaleCNS operator.
6. Optional direction-shuffled control, secondary only if its construction can
   be specified without changing the primary contrasts.

All arms share host architecture outside the inserted operation, training
examples, initialization seeds, optimizer, update count, and evaluation split.
The adapter realization is paired across graph arms. The exact graph-null
algorithm, acceptance/retention gates, adapter map, and arm-level seed count
must be recorded before training outcomes are read.

## Host task and readout

The host task is not selected yet. Recommended smallest default: a deterministic
synthetic teacher-student classification task with 128-dimensional inputs and
a small ordinary MLP. This avoids coupling the first test to Jev, a fly-specific
task, or a hand-picked benchmark. If adopted, the teacher, data-generation
seeds, train/test draws, learner, optimizer, and fixed training budget must be
specified in the sealed protocol.

Use one primary held-out loss comparison across paired seeds; report accuracy
and per-seed outcomes as secondary descriptions. Preserve all arms and report
null or mixed outcomes without selecting a favorable seed, split, or metric.

## Next freeze gate

Before building the scientific runner or training any host model, freeze:

1. exact host task and train/test generation;
2. adapter projection rule, dimension, normalization, and paired seeds;
3. graph aggregation and degree-preserving/random-null algorithms, including
   acceptance and edge-retention requirements;
4. learner, optimizer, training budget, paired seed count, and primary analysis;
5. source-to-artifact hashes and a reproducible build/run contract.

The source census is read-only preflight evidence only. It does not qualify a
runner, seal the protocol, or count as a model result.
