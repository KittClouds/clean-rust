# Candle R-GCN v1

## Definition of complete

`candle-rgcn16/v1` is the first topology-aware learned rung. It trains from the
same frozen graph, tensor, train-topology, evaluation protocol, seed certificate,
and selected-repeat authority as the baseline ladder. It may emit a model only when
its validation result strictly beats the model selected by a finalized Frozen Model
Selection Ledger under the same binary evaluator.

The comparison rule is deterministic: higher validation average precision wins; an
exact AP tie requires lower Brier score. Test rows are never staged, trained, scored,
or attached to the R-GCN artifact.

## Array audit and encoder mapping

Frozen Tensorization v1 already contains the required framework-neutral surfaces.
All source sections remain mmap-backed and BLAKE3-verified until one exact-sized,
native-endian runtime staging pass.

| Frozen surface | R-GCN use |
|---|---|
| node type ids | learned 16-wide initial node embeddings |
| typed COO source/target/relation | forward and inverse edge message channels |
| COO authority/split/weight | asserted train-only filtering and degree normalization |
| incidence hyperedge/participant/role | forward and inverse role message channels |
| incidence split/resolved | resolved train-only filtering |
| train-topology link rows | train/validation query order, candidates, and labels |

Edge relations and incidence roles occupy disjoint encoder namespaces. The fixed
weight order is node-type embeddings, self transform, forward edge/role transforms,
inverse edge/role transforms, edge-relation DistMult decoder, and decoder bias.
Only edge relations are prediction targets; roles contribute messages but cannot be
mistaken for decoder relations.

The staging boundary validates all node, edge, relation, incidence, role, split,
authority, resolution, and query bounds before Candle sees a tensor. Candidate and
test topology cannot enter the encoder: only asserted train COO edges and resolved
train incidences become messages.

## Training and authoritative scoring

The CPU Candle model performs one R-GCN layer with degree-normalized typed messages,
ReLU, and a sigmoid DistMult link decoder. Full-batch deterministic SGD executes
exactly once per model artifact and exports five ordered tensors into
`phoenix-frozen-model/v1`.

Candle scores are only a parity witness. Validation scores and certificates come
from the Phoenix SIMD scorer. After emission, the trainer drops its live model,
reopens the content-addressed manifest and mmap weight blob, and requires bit-exact
restart scores. Restart scoring has no Candle or optimizer dependency.

The request must provide both the finalized baseline ledger and its selected
validation manifest. Source identity, seed universe, selected model id, weight
digest, task, evaluator schema, calibration bins, and absence of a test certificate
must all match before R-GCN fitting begins.

## Relation-batch artifact decision

No frozen relation-batch artifact is added in v1. The typed COO and incidence arrays
require one owned native-endian grouping because Candle's index operations cannot
borrow little-endian, relation-interleaved mmap columns. That grouping is exact-sized
and reused across every epoch.

The trainer records source edges, incidence rows, staged messages, train/validation
queries, bytes, and latency. A fail-closed pressure gate demands a future frozen
relation batch only when staging is at least 5 ms and at least 25% of training time.
The 23,000-edge plus 23,000-incidence release profile stages 86,000 directed messages
and 44,000 queries into 1,880,004 bytes in 9.047 ms. This one-time work is not the current
training limiter, so persisting a second authority artifact would add complexity
without buying meaningful runtime.

On the certified topology-only learning fixture, release training took 42.116 ms,
cold source/model reopen, restaging, and authoritative scoring took 1.105 ms, while
the initial staging took 22 us. The
ledger-selected dense baseline scored AP `0.5740040843` / Brier `0.250000`; R-GCN
scored AP `1.0` / Brier `0.249983` from the incidence signal.

## Proof gates

- Zero-feature dense baseline rows force the baseline ladder to be non-predictive.
- Positive and negative candidates share the same node type.
- A resolved train incidence is the only distinguishing signal, so the test cannot
  pass without typed message propagation.
- The R-GCN must beat the ledger-selected baseline under authoritative AP/Brier.
- Same inputs/config/seed reproduce weights, scores, certificates, and model id.
- A different certified seed produces a distinct weight and model identity.
- Corruption and source/ledger drift fail before training or scoring.
- Restart inference is bit-exact and at least 2x faster than training.
- All emitted certificates are validation-only.

## Scope guard

Dense feature sidecars remain deferred. The encoder intentionally uses the existing
mmap tensor authority and does not rewrite graph layouts, introduce a GPU path, open
test data, train a hypergraph-specific decoder, or persist derived relation batches.
GPU execution and multi-layer/basis-decomposed R-GCNs require their own measured
tickets after this first rung is reproduced on real research snapshots.
