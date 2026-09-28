# FLY-DROP-00 Protocol v0.1

**Status: pre-outcome freeze candidate.** The protocol is not sealed until the
source columns, graph realizations, effective operators, diagnostics, and
training examples have been generated and their hashes recorded. No learner
training is allowed before that seal.

## 1. Question and scope

Measure whether the complete MaleCNS v1.0 segment-connection-table operator,
after one prospectively fixed 128D projection, changes held-out loss in an
otherwise ordinary learner relative to a degree/weight-context-preserving
topology shuffle. The direction is open: either improvement or harm is a
computational phenotype. This does not test biological function or justify a
mechanism claim. Jev is deferred.

The official source calls the released weights segment-to-segment connection
strengths. This study retains every row and every endpoint ID from that table;
the operator will be called the **projected MaleCNS segment-connection-table
operator**, never “the fly brain.” The preflight verified the source file SHA-256
and observed 151,856,684 rows, 311,833,243 total weight, and 88,384,522 unique
endpoint IDs. The endpoint universe is the sorted set of IDs appearing in
either endpoint column; annotation-only IDs with no edge are not added.

## 2. Source graph and exact projection

For every row `(u, v, w)`, `u` is `body_pre`, `v` is `body_post`, and positive
integer `w` is the released connection weight. Rows and repeated pairs are
retained exactly as released. Self-loops are retained. Define

`d_in(v) = sum_q w(q -> v)` and `A[v,u] += w(u -> v) / d_in(v)`.

There is no activation, recurrence, residual, bias, gain, task information, or
plasticity inside `A`. A destination with zero incoming strength has an all-zero
row. No second normalization is applied.

For each adapter seed `s`, define

`b_s(id) = SplitMix64(id XOR s) AND 127`.

The same function is used for pre and post IDs. `E_s` copies host coordinate
`x[b_s(id)]` to each endpoint ID. `R_s` takes the arithmetic mean of outputs
over all endpoint IDs in each bucket, including IDs whose graph output is zero.
The operator used by the learner is exactly `M_s = R_s A E_s`, computed in
f64 accumulation and stored as row-major little-endian f64. There is no fitted
projection and no post-projection normalization. The adapter seeds are fixed
at `1101, 1102, 1103, 1104`; none may be replaced based on matrix diagnostics.

The bucket function is the SplitMix64 finalizer applied to `u64(id) XOR seed`:
add `0x9e3779b97f4a7c15`, then xor-shift/multiply by `0xbf58476d1ce4e5b9`,
xor-shift/multiply by `0x94d049bb133111eb`, and a final xor-shift, using shifts
30, 27, and 31 respectively. The endpoint universe is the sorted unique set of
signed 64-bit IDs in either source endpoint column. It is not enlarged with
annotation-only IDs. For each edge row and adapter, the builder adds
`((w as f64 / d_in(v) as f64) / bucket_population[b_s(v)])` to matrix entry
`[b_s(v), b_s(u)]`, in source row order. This is the direct algebraic `R_s A E_s`
projection; f64 arithmetic is its frozen numerical representation.

Before outcomes, verify the projected action against direct sparse evaluation
on a small deterministic graph fixture for every adapter seed, with a stated
floating-point tolerance. The fixture is an implementation check and is not a
scientific sample.

## 3. Arms and prospective graph realizations

Every arm occupies the same layer position and uses the same trainable host
parameter count:

`x -> L1 -> GELU -> M_arm -> GELU -> L2 -> logit`.

There is no residual connection, learned gain, task-specific normalization,
LayerNorm, or architecture rescue. `L1` maps 128 to 128; `L2` maps 128 to one
binary logit. Only `L1` and `L2` train.

1. **Identity:** `M = I_128`.
2. **Dense:** four independently seeded frozen positive dense matrices. Draw
   independent Exp(1) entries and normalize each row to sum to one; seeds
   `5101..5104`.
3. **Random sparse:** four independent graph realizations. For each source row,
   independently sample pre and post IDs uniformly from the frozen endpoint
   universe; attach the original source row's weight. Preserve row count and
   the complete weight multiset, but do not preserve degrees. Allow loops and
   repeated pairs. Seeds `3101..3104`.
4. **Degree/weight-context shuffle (primary control):** four independent
   realizations. Globally permute the source `body_pre` column across rows,
   preserving every original `(body_post, weight)` pair. This preserves row
   count, every destination's incoming row count and weight multiset, every
   source's outgoing row count, the source endpoint multiplicities, and the
   global weight multiset. Do not reject loops or repeated pairs. Seeds
   `2101..2104`.
5. **MaleCNS:** the released source rows without rewiring, projected through
   each of the four adapter seeds.

The endpoint universe is held fixed for every random graph. Each stochastic
graph realization is constructed once and projected through all four adapter
seeds. Graph realizations are experimental factors; more learner seeds do not
replace them.

All pseudorandom streams use the SplitMix64 increment/finalizer implemented in
the builder. Stream state starts at the seed; `next` adds
`0x9e3779b97f4a7c15` then applies the SplitMix64 finalizer. For an unbiased
integer draw below `n`, values below
`((-n) mod 2^64) mod n` are rejected before taking the remainder. The degree
shuffle uses Fisher-Yates from the final pre-column index down to one. Random
pre and post endpoints use independent streams seeded by `graph_seed XOR
0x7072652d6e756c6c` and `graph_seed XOR 0x706f73742d6e756c`; each draws from the
sorted endpoint universe. Degree shuffles use the stream seed
`graph_seed XOR 0x6465677265652d70`. Dense entries use stream seed
`dense_seed XOR 0x64656e73652d7631` and `-ln(U)` with
`U=((next >> 12)+1)/(2^52+1)`, then normalize each row by its sum. Each
canonical graph hash is SHA-256 over the UTF-8 domain prefix
`FLY-DROP-00/canonical-rows/v1` followed by each ordered `(pre, post, weight)`
triple as three little-endian signed 64-bit integers. These choices, seeds,
and resultant hashes are frozen before training.

## 4. Frozen synthetic task

Use four independent teacher worlds with seeds `6101..6104`. Each teacher has
`W` of shape 32-by-128 and `v` of length 32, initialized from independent
standard normal values and scaled by `1/sqrt(128)` and `1/sqrt(32)` respectively.
For `x ~ N(0, I_128)`, define the binary label as

`y = 1[ v^T tanh(W x) > 0 ]`.

Generate 8,192 train examples and 4,096 held-out examples per teacher from
separate fixed example streams. Store the actual arrays and labels before
training; record hashes and class counts. Do not rebalance, add noise, augment,
or select examples after inspecting outcomes. The odd teacher and symmetric
input give balanced labels in distribution; finite-sample class counts are
reported without correction.

Teacher parameters and inputs are generated as f64 Box-Muller normal draws
from SplitMix64 streams, scaled as above, then stored as little-endian f32.
Each scalar normal consumes two open-interval uniforms and uses
`sqrt(-2 ln U1) cos(2 pi U2)`. Uniforms are
`((next >> 12)+1)/(2^52+1)`. Stream seeds are `teacher_seed XOR
0x746561636865722d` for parameters, `teacher_seed XOR 0x747261696e2d7631`
for training inputs, and `teacher_seed XOR 0x68656c646f75742d` for held-out
inputs. Labels are generated from
the stored f32 values, accumulated and passed through `tanh` in f64, and set
to one only when the final score is strictly positive. Input arrays are stored
row-major. Exact seeds, stream domains, file hashes, and class counts appear in
the frozen manifest.

## 5. Training contract

Use four paired learner initialization/data-order seeds `7101..7104`. Pair the
same teacher world, learner seed, examples, minibatch order, and initialization
across every matrix arm. Use AdamW with learning rate `1e-3`, weight decay zero,
batch size 128, 20 epochs, and one deterministic reshuffle of the training
indices per epoch. No validation-driven checkpointing or hyperparameter search;
the final epoch is the sole endpoint. Train all 41 matrices across four teacher
worlds and four learner seeds (656 total fits).

The MLP has biased 128-to-128 and 128-to-1 linear layers. Both weight matrices
use Xavier uniform initialization with bound `sqrt(6/(fan_in+fan_out))`; biases
start at zero. GELU uses the fixed tanh approximation
`0.5*x*(1+tanh(sqrt(2/pi)*(x+0.044715*x^3)))`. Training uses binary
cross-entropy-with-logits, mean-reduced gradients, AdamW betas `(0.9, 0.999)`,
epsilon `1e-8` outside the square root, standard bias correction, and no
learning-rate schedule. Initialization and order streams derive from
`(teacher_seed << 32) XOR learner_seed XOR 0x696e69742d7631` for initialization
and `(teacher_seed << 32) XOR learner_seed XOR 0x6f726465722d7631` for order.
The same generated order and initial parameters are reused across all operator
arms for that teacher/learner pair. The initialization stream uses the
SplitMix64 open-uniform rule above in row-major order: `L1[128,128]` followed by
`L2[128,1]`; biases are zero. The order stream remains continuous across
epochs; each epoch performs the specified unbiased Fisher-Yates shuffle. Each
epoch has exactly 64 minibatches; the incomplete-batch path is not used.

Trainable layers and activations use f32. Each frozen f64 operator is applied
by f64 accumulation to the f32 post-first-GELU activations promoted to f64;
the result is cast to f32 before the second GELU. The same numerical path is
used for every arm, including identity. Held-out BCE is computed from final
logits using the stable expression `max(z,0)-z*y+ln(1+exp(-abs(z)))` and then
averaged across the 4,096 held-out examples.

## 6. Outcomes and analysis

The primary outcome is final held-out binary cross-entropy. Define

`Delta = loss(MaleCNS) - mean_g loss(DegreeShuffle_g)`.

Negative `Delta` means lower loss for the projected MaleCNS topology; positive
`Delta` means higher loss. Use a two-sided 95% multiway bootstrap interval with
20,000 replicates, resampling adapter seeds, degree-shuffle realizations,
teacher worlds, and learner seeds as separate axes; bootstrap seed `20260921`.
Report the point estimate and interval regardless of sign or interval crossing
zero. No seed replacement, metric switching, stopping adjustment, or favorable
slice selection is allowed.

The point estimate averages paired differences over the four adapters, four
teacher worlds, and four learner seeds, with the degree-control loss averaged
over its four graph realizations inside each paired cell. Each bootstrap draw
resamples four indices with replacement independently on each of the adapter,
degree-graph, teacher, and learner axes; shared adapter/teacher/learner draws
are used for both sides of the paired contrast. Use the percentile interval at
2.5% and 97.5%, with linear interpolation, from the 20,000 seeded draws.

Identity, dense, and random-sparse comparisons are secondary controls.
Accuracy, per-seed outcomes, and training trajectories are descriptive only.

## 7. Mandatory pre-training operator census

For every frozen matrix, report matrix rank, Frobenius norm, largest and
smallest singular values, full singular-value spectrum, condition number where
defined, row sums, zero rows, entry sparsity/density, row entropy, and—where
applicable—adapter bucket populations. Diagnostics may reveal degenerate or
near-singular operators, but may not select, replace, or reorder a seed.
Replacement is allowed only for a documented contract/build failure, never for
an unattractive diagnostic.

Singular values use a one-sided cyclic Jacobi SVD on the f64 matrix, at most
100 sweeps, rotating column pairs while normalized correlation exceeds
`8*f64::EPSILON`; rank tolerance is `128*f64::EPSILON*sigma_max`. Condition
number is reported only when `sigma_min` exceeds that tolerance. Row entropy is
`-sum(p*ln(p))` with `p=entry/row_sum`; a zero row has entropy zero. Density is
the fraction of matrix entries that are exactly nonzero.

## 8. Freeze, receipts, and stop boundary

Before training, record source hashes; endpoint-universe hash and count; graph
realization hashes; all adapter-map hashes; every effective-operator hash;
operator census; teacher/data hashes and class counts; code, lockfile, compiler,
and preparation-executable hashes; resource estimates; and the exact
preparation command. The pretraining seal contains no learner outputs and
licenses no training before the user chooses to proceed. Any change to the
protocol or frozen preparation identity requires a new protocol version and
remains outside FLY-DROP-00 v0.1.

The initial implementation phase ends at the sealed pre-training handoff.
No learner run, outcome analysis, or Jev handoff is part of the sealing step.

On the preparation host, the exact command is
`$env:CARGO_TARGET_DIR='D:\\fly-drop-00-target'; cargo run --release --offline --manifest-path experiments\\fly-drop-00\\Cargo.toml`.
The release executable is also reachable through the local
`experiments/fly-drop-00/target` junction to `D:\\fly-drop-00-target`.
