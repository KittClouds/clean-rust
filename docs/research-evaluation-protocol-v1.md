# Research Evaluation Protocol v1

## Authority

`phoenix-research-evaluation-protocol/v1` certifies one evaluation contract over one Frozen Graph Research Snapshot and its exact Frozen Tensorization. It never reads mutable application state, changes graph truth, resplits rows, or regenerates negatives.

The protocol id is BLAKE3-addressed over the tensor id, source dataset id, temporal split policy, evaluation policy, seed certificate, task definitions, and completed leakage audit.

## Chronological splits

The source snapshot's train and validation time boundaries remain authoritative:

- nodes and edges use `availableAtMs`;
- proposals use `max(observedAtMs, labelAvailableAtMs)`;
- `uncommitted` proposals remain censored and cannot enter supervised loss;
- test rows are never used for fitting or model-family selection.

The evaluator checks the source snapshot against every corresponding tensor array. It fails closed on identity drift, shape drift, future rows, split reassignment, endpoint chronology violations, altered features or labels, incidence drift, uncertified feature columns, mixed feature schemas, unsafe negatives, and duplicate negative samples.

## Certified seeds

The caller supplies a seed root and repeat count. Individual seeds are derived with BLAKE3 from:

`protocol schema + tensor id + feature schema id + seed root + repeat ordinal`

The ordered seeds receive their own BLAKE3 digest. Results are reproducible without depending on a platform RNG implementation.

## Immutable artifacts

`ResearchEvaluationBundle::write` durably installs `<protocol-id>.evaluation.json` followed by `<report-id>.baselines.json`. Both names are content addressed, writes use create-new temporary files plus `sync_all` and rename, and identical completed artifacts are reusable. A baseline report whose protocol id differs from its certificate fails closed.

## Task definitions

### Proposal outcome binary v1

- Examples: observed proposals from exactly one feature schema.
- Positive: `active`.
- Negative: `superseded`, `retracted`, or `reverted`.
- Censored: `uncommitted`.
- Metrics: average precision, ROC-AUC, log loss, Brier score, and expected calibration error.
- Status: executable in v1.

### Typed link prediction v1

- Examples: asserted typed edges and certified type/time-constrained corruptions.
- Target: rank the asserted target above valid corruptions.
- Metrics: filtered MRR and Hits@1/3/10.
- Status: contract frozen; `Train-Topology Feature Derivation v1` now supplies certified inputs. Ranking-metric execution is the next evaluator extension.

### Hyperedge role completion v1

- Examples: resolved incidence with one typed participant role masked.
- Target: rank the held-out participant within its certified node type.
- Metrics: filtered MRR and Hits@1/3/10.
- Status: contract frozen; `Train-Topology Feature Derivation v1` now supplies certified inputs and incidence negatives. Ranking-metric execution is the next evaluator extension.

The two ranking tasks are deliberately not approximated with uncertified full-graph degrees, embeddings, or manifold coordinates.

## Entry points

Low-level callers use `certify_evaluation_protocol`, `evaluate_binary_scores`, and `ResearchEvaluationBundle::write` from `phoenix-graph-research`.

Store-backed callers use `GraphStageApi::evaluate_research_baselines`, which loads one checkpoint and one commit/proposal lineage, freezes and tensorizes it, then returns the protocol certificate and baseline report together.
