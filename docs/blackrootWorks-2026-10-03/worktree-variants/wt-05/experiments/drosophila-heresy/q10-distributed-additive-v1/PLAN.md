# Q10-DA1 distributed additive readout diagnostics

This root is an engineering-only implementation. It has no behavioral endpoint,
scientific seed bundle, DH08B path, or claim that a readout repair is a valid
geometric endpoint.

## Frozen event schedule

The declared schedule is the eight combinations of seeds `9731, 9732`, sides
`R, L`, taus `4, 16`, and trial `128`. A parent Q10-SM constructor failure is
retained as an unavailable event with the full declared denominator. There is
no replacement seed, resampling, or silent event deletion.

The parent constructor and the canonical DH06 anatomy are verified before
`Graph::load`. PREEXECUTION records the canonical anatomy directory and a
sorted SHA256 manifest for every input file in that directory.

## Readout and support contract

The production readout is the ordered operator row replay with f32 addition;
an empty row starts at signed `-0.0`. Fixture rows preserve occurrence order,
including duplicate coordinates. Each available event stores one shared
snapshot fixture: base f32 bits, acquisition axis f64 values, permitted mask,
interior indices, initial and target weight bits, and initial and target readout
bits. The runner emits final coalition changes and ordered operator rows so the
independent Python oracle can recompute each sequential replay.

Support incidence is structural over every operator row. Coordinates with empty
support are excluded before selection. Four fixed selector salts produce four
target-blind stable hash orders; each order is greedily consumed to a maximal
support-disjoint set. The policy has no coalition size cap and does not claim
maximum coverage. Excluded coordinates and rows outside coverage are recorded.
The stable event key identifies tau, trial, and side; seed and event domains are
mixed independently.

For every selected coordinate, the independent optimizer compares zero and
signed `+/-1,2,4,8,16` adjacent f32 steps from the initial endpoint. A candidate
is legal only inside the committed bounds with at least 16 interior reserve
steps in both directions. It minimizes the full structural row support by
lexicographic mismatch count, then squared residual. Mismatch-first selection
may increase L2; the receipt reports that tradeoff and Pareto improvement
separately and does not require L2 monotonicity.

The combined result is assembled from independent row replays and then checked
against a fresh full sequential oracle bit-for-bit. Prefixes are fixed at
`1,3,8,16,32,all`; each prefix also requires assembled/full replay parity.
No interaction search or nonlinear replay is used.

## Geometry diagnostics

Existing gates audit committed support, bounds, boundary membership, reserve,
and axis, norm, and linear readout drift. The inherited path length `<=64`
check is retained as a named legacy diagnostic only; it is not a DA coalition
budget or acceptance constraint. The receipt separately reports readout
authority, geometry gate outcome, and endpoint status.

The acquisition-orthogonal direction report projects final displacement and
true displacement with `u = d - dot(d,A)/dot(A,A) * A`; it is diagnostic and
has no frozen direction threshold. The pass label is
`READOUT_AND_LISTED_GEOMETRY_PASS__DIRECTION_UNQUALIFIED`.

## Review and commands

Supervisor review of source and synthetic regression tests precedes any seal or
engineering sample. The intended bounded checks are:

```text
$env:CARGO_TARGET_DIR='D:\\drosophila-heresy\\q10-distributed-additive-v1-target'
cargo test --lib da_core::tests -- --nocapture
cargo test --all-targets
cargo build --release
python -B -c "compile(open('scripts/review_q10_da.py', encoding='utf-8').read(), 'scripts/review_q10_da.py', 'exec')"
```

The engineering sample and `seal` command remain pending supervisor approval.
