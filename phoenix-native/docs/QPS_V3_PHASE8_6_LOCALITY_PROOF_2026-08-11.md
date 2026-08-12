# QPS V3 Phase 8.6 Locality Proof - 2026-08-11

## Outcome

Phase 8.6 is complete and produced a negative promotion decision:

> Matched-group locality is valid primitive evidence, but it does not materially
> explain the remaining Phase 8 failures.

The experiment improved partial-match saturation and reduced the graded loss
and worst-shape regression, but it regressed LongMemEval MRR, blind pairwise
accuracy, held-out top-1 improvement, phrase/order, document/conversation, and
wrong-concept results. Only one of the seven targeted residual classes improved.

Therefore:

- Phase 8.6B schema migration is **not authorized**.
- The canonical 30-feature schema and immutable ledger were not changed.
- No historical feature slot was reinterpreted.
- No production model was promoted.
- **V2 remains active.**

Diagnostic receipt:

`C:\benchmarks\phoenix-qps-v3-20260804\phase8_6-locality-proof-v1\phase8_6-locality-diagnostic-v1.json`

SHA-256:

`8aad1e322f89e97a926225585aff110804615b5d537b7434c87d14bf5542847a`

## Primitive proved

For `m` distinct matched query groups in a field and their minimum covering
span `s`:

```text
matched_group_locality = 0                         when m < 2
matched_group_locality = 1 / (1 + max(0, s - m))  otherwise
```

The implementation carries this value through field evidence and primitive
coherence, taking the maximum across fields. It is finite, bounded, deterministic,
configuration-independent, and uses the existing allocation-free position walk.

The following invariants are tested:

- fewer than two matched groups produces zero;
- perfect adjacency produces one;
- increasing span lowers locality;
- every result is in `[0, 1]`;
- complete coverage equals the existing complete-span quality;
- repeated input is bit-identical;
- field-order permutation is identical.

## Frozen-substrate proof

V2 positional scoring and V3 primitive collection now have independent request
flags. Ordinary V2 does not open position payloads when its positional signals
are disabled. Evidence collection can request the position walk without changing
candidate generation or the V2 equation.

Across the frozen mixed and LongMemEval workloads, all of these checks passed:

- query counts match;
- candidate identities match;
- candidate order matches;
- V2 score bits match;
- canonical 30-feature evidence matches;
- constitutional tiers match;
- locality is finite and bounded.

Release-sidecar receipt:

`C:\benchmarks\phoenix-qps-v3-20260804\phase8_6-locality-proof-v1\release-locality-sidecar-v1.json`

SHA-256:

`1ae71ef6dd3cc49abc4900e982b5f1e2f776ee18574dec4e890f13c3def3b794`

## Immutable-input and projection proof

The independent-data generator was repaired to reproduce the exact v9 source
composition. Its regenerated ledger and graded suite are byte-identical to the
canonical v9 inputs:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Regenerated ledger | 275,421,386 | `a28f906d13446e4c5c0b627bc6400e5112a48d413105d229fe053fefc92b35d8` |
| Regenerated graded suite | 35,930,996 | `d9be32daca38e0b4cefd2680447ebeb5e8e6f5021c8f789917e468f9704af02b` |
| Independent locality sidecar | 30,957,400 | `14ec0bc1bcfacad000748ddccf592d7be391c43f8b16c83e970d4098ad4ff984` |

Projection was diagnostic and in memory only:

- active reviewed judgments projected: `5,080 / 5,080`;
- reversed reviewed preferences preserved: `226`;
- nonzero pair locality deltas: `4,132`;
- independent graded candidates projected: `74,880 / 74,880`;
- frozen release candidates projected: `22,898 / 22,898`;
- missing queries or candidates: `0`;
- locality bound violations: `0`.

The experiment temporarily replaced redundant coordinate 8
(`missing_group_absence`) only inside cloned diagnostic vectors. It did not
serialize those vectors as canonical evidence.

## Controlled learner result

The same deterministic monotonic linear learner and the same leakage-safe split
were used. Development selected 256 epochs, learning rate `0.025`, and L2
`0.0001` from 48 configurations. Training the selected configuration twice
produced the same model identity.

| Metric | Canonical linear V3 | Locality diagnostic | Change |
|---|---:|---:|---:|
| LongMemEval hit@10 | `0.984` | `0.984` | `0.000` |
| LongMemEval MRR | `0.898899` | `0.898214` | `-0.000685` |
| LongMemEval top-1 | `0.844` | `0.842` | `-0.002` |
| Independent stretch MRR | `0.543202` | `0.546910` | `+0.003708` |
| Graded NDCG@10 change vs V2 | `-0.014278` | `-0.007362` | `+0.006917` |
| Blind pairwise accuracy | `0.785377` | `0.779481` | `-0.005896` |
| Held-out top-1 improvement | `+4.184` points | `+2.929` points | `-1.255` points |
| Worst-shape MRR regression | `0.016345` | `0.010964` | `-0.005381` |
| Mixed hit/MRR/top-1 | `1.000` | `1.000` | unchanged |

## Targeted residual result

| Failure class | Judgments | Baseline | Locality | Change |
|---|---:|---:|---:|---:|
| Phrase/order failure | 152 | `0.684211` | `0.677632` | `-0.006579` |
| Partial-match saturation | 40 | `0.350000` | `0.375000` | `+0.025000` |
| Document/conversation confusion | 144 | `0.791667` | `0.770833` | `-0.020833` |
| Wrong-concept proximity | 162 | `0.870370` | `0.864198` | `-0.006173` |
| Common-term dominance | 66 | `0.742424` | `0.742424` | `0.000000` |
| Length-prior failure | 17 | `0.411765` | `0.411765` | `0.000000` |
| Scattered terms | 27 | `0.814815` | `0.814815` | `0.000000` |

Complete-coverage blind accuracy remained `16 / 17` for both models, so the
primitive is safe on that narrow invariant. Safety alone is not enough to earn
a permanent schema slot.

## Verification

All commands used `D:\phoenix-target-qps-v3-phase86-20260811`.

- `cargo test -p phoenix-lexical-qps --all-targets`: `35` passed.
- `cargo test -p phoenix-memory-lock --all-targets`: `78` passed.
- `cargo clippy -p phoenix-lexical-qps -p phoenix-memory-lock --all-targets -- -D warnings`: passed.
- `cargo fmt --all -- --check`: passed.

## Next evidence question

Locality supplied positional compactness, but common-term dominance did not
move and wrong-concept proximity regressed. The next narrow audit should test
whether candidates cover the *discriminative* query groups, rather than merely
how many groups they cover or how rare their matched terms are in isolation.

The leading candidate is a bounded rarity-weighted group-coverage primitive.
That is a hypothesis for Phase 8.7, not an authorized schema change. Its exact
definition must first settle expansion-group rarity semantics and prove that it
adds information not already present in weighted coverage, rarest-term evidence,
and mean matched-term rarity.
