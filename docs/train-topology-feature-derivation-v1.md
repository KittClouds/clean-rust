# Train-Topology Feature Derivation v1

## Purpose

`phoenix-train-topology-features/v1` is the leakage firewall between frozen tensors and topology-aware graph models. It derives deterministic link-prediction and hyperedge-role features from asserted training topology only.

The derivation accepts one Frozen Graph Research Snapshot, its exact Frozen Tensorization, and its certified Research Evaluation Protocol. It re-certifies the protocol against the source before reading topology. Identity drift, altered split policy, future train edges, candidate-edge fitting, or malformed arrays fail closed.

## Fit authority

The fit view contains only:

- asserted edges whose certified split is `train` and whose `availableAtMs` does not exceed `trainThroughMs`;
- resolved incidence whose certified split is `train`;
- node type and authority metadata already present in Frozen Tensorization.

Validation and test topology is never inserted into adjacency, degree, relation, neighborhood, role, or incidence statistics. The train topology receives its own BLAKE3 digest and exact row counts.

## Leave-one-positive-out rule

Merely fitting on train topology is insufficient for training examples: a positive can reveal itself through direct-edge flags, degrees, or incidence counts.

For every training positive, the derivation masks that exact edge or incidence while computing its features. Every constrained negative paired with the positive receives the same exclusion. The correction is applied against one immutable train adjacency without rebuilding topology per example.

Validation and test examples receive the unchanged training fit because their positives are absent from it.

## Typed link features

V1 emits one positive row per asserted edge and one negative row per certified tensor corruption. The 16 fixed columns contain:

- source/target in-degree and out-degree;
- source-relation out-degree and target-relation in-degree;
- common outgoing and incoming neighbors;
- reciprocal-edge and direct-edge flags;
- preferential attachment and self-loop indicators;
- four reserved zero columns.

Count values use `ln1p`; flags are Boolean `f32`. Two-level adjacency tables are ordered deterministically and built once.

## Hyperedge-role features

V1 emits one positive per resolved incidence and deterministic, same-node-type negative participants. Candidates must be asserted, available no later than the example split, and absent from the same hyperedge-role incidence in every split.

Features include participant incidence degree, participant-role degree, hyperedge degree, global role degree, and graph in/out degree for participant and hyperedge. Eight columns remain reserved zeroes.

Negative enumeration uses a BLAKE3-derived coprime permutation, avoiding an allocated shuffle per incidence.

## Feature certificates

Every column records:

- task and feature-schema ids;
- name, `f32-le` dtype, and transform;
- `train` as the only fit split;
- exact fit-through timestamp;
- label-free status;
- leave-one-positive-out status.

Reserved columns are explicitly certified as constant zero rather than carrying ambiguous values.

## Immutable artifact

Each derivation writes:

- `<derivation-id>.ttf-manifest.json`;
- `<derivation-id>.ttf`.

The binary is BLAKE3-addressed and contains fixed-width link and incidence records. `TrainTopologyFeatureMapped` validates schema, digest, version, byte ranges, and row counts before exposing borrowed `zerocopy` slices over one read-only `memmap2` mapping.

Writes use create-new temporary files, `sync_all`, and rename. Existing identical content-addressed artifacts are reusable.

## Entry points

Low-level callers use `derive_train_topology_features`, `TrainTopologyFeatureBundle::write`, and `TrainTopologyFeatureMapped::open`.

Store-backed callers use `GraphStageApi::derive_research_topology_features`, which freezes, tensorizes, certifies, and derives from one store lineage.

## Deliberate exclusions

V1 does not compute learned embeddings, spectral decompositions, manifold coordinates, or message-passing activations. Those require a fitted-model artifact whose training topology digest and feature derivation id are independently certified. Ranking Evaluation and Structural Baselines v1 now provides the framework-neutral scoring and evaluation seam for Candle or Burn.
