# Native Reward Observation v1

Status: implemented; the canonical commit producer and horizon observer are installed.

## Purpose

Phoenix stores reward as a vector of eight independently authoritative dimensions. A native
decision outcome may carry that vector only when every dimension is observed. This contract
therefore persists partial observations separately instead of inventing values for dimensions
that are still unknown.

## Immutable observation

Each observation binds:

- the native decision receipt and chosen action;
- the exact BLAKE3 decision-to-truth link;
- the canonical `GraphTruthCommit` identity;
- one reward dimension;
- observe, revise, or retract semantics;
- an optional score in the frozen `[-1_000_000, 1_000_000]` range;
- observation time, authority class, authority identity, and evidence anchors;
- the predecessor receipt for revisions and retractions.

The append-only record shares the mmap-backed native decision log. Every payload has a BLAKE3
checksum, restart decoding revalidates its content identity, and retries of identical content are
idempotent. A revision must extend the latest receipt for the same decision, chosen action, and
dimension.

## Installed dimension producers

### Human acceptance

The observation requires `operator_preference` authority. Observation and evidence must occur no
earlier than the certified decision-to-truth link. Selection or mutation timestamps are not
silently converted into reward. A real canonical commit carrying both authority receipts emits a
distinct immutable human-evaluation evidence receipt, and the observation references that receipt.

### Future stability

The observation requires `authoritative_graph_outcome` authority. Observation and every evidence
anchor must occur at or after the frozen stability horizon derived from the linked truth commit.
Durable presence alone is not treated as semantic stability.

All other reward dimensions fail closed until their producer contracts are installed.

## Censorship and materialization

Observation responses always return `rewardComplete: false`. The census reports active human
acceptance, active future stability, retracted dimensions, and partial versus fully observed
decisions. It does not modify the original outcome receipt.

A later Reward Vector Materialization cut may append an outcome revision only when all eight
terminal dimension chains are active, identity-consistent, and visible at the requested temporal
cutoff. Until then the research dataset must treat reward as censored.

## Desktop surface

The native-only desktop RPC exposes:

- `record_native_reward_observation_json`;
- `native_reward_observation_census_json`.

The Overgraph canonical append hook emits human acceptance after it certifies the two-receipt truth
link. Native boot installs the restart-safe horizon observer, which submits future stability only
after the maturity boundary. Existing commits and operator journals without the exact authority
join remain untouched; the live corpus grows from newly linked canonical decisions.

See [Canonical Reward Producer Integration v1](canonical-reward-producer-integration-v1.md).
