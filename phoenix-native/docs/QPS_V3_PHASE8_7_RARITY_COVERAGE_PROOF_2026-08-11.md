# QPS V3 Phase 8.7 Rarity-Weighted Coverage Proof - 2026-08-11

## Outcome

Phase 8.7 is complete and produced a negative schema-migration decision:

> Rarity-weighted group coverage contains real missing pairwise information,
> but one global monotonic slope does not transfer that information to the
> residual failure classes the primitive was intended to solve.

The leakage-safe preflight passed: among training and development pairs with
effectively equal ordinary group coverage, the preferred candidate had higher
rarity-weighted coverage in `240 / 337` directional target-class pairs
(`71.2166%`). The controlled learner then improved aggregate LongMemEval MRR,
stretch MRR, graded NDCG, and worst-shape behavior. However, none of the five
target failure classes improved on the blind split, and two regressed beyond
the allowed `0.005` tolerance.

Therefore:

- Phase 8.7C schema migration is **not authorized**.
- The canonical 30-feature schema and immutable ledger remain unchanged.
- The redundant coordinate 8 was replaced only in cloned diagnostic vectors.
- No production model was promoted.
- **V2 remains active.**

Authoritative diagnostic receipt:

`C:\benchmarks\phoenix-qps-v3-20260804\phase8_7-rarity-coverage-proof-v1\phase8_7-rarity-coverage-diagnostic-v3.json`

SHA-256:

`780a0bbbdd7ec2c1cbaa609ea9c7a0ed4d47db7a95e4771b745e2f8798a93cbb`

## Primitive proved

For each query group `g`, compute one candidate-independent weight:

```text
w_g = max(expansion_quality(e) * normalized_term_rarity(e)) for e in g
```

For candidate `d`:

```text
rarity_weighted_group_coverage(d)
    = sum(w_g for matched groups) / sum(w_g for all groups)
```

The result fails closed to zero when the denominator is zero.

Important semantic boundaries are enforced:

- the denominator belongs to the query and is identical for every candidate;
- group weight uses `max`, so adding synonyms cannot manufacture mass;
- candidate-selected expansion quality is not multiplied into the numerator;
- existing expansion-quality coordinates retain that separate responsibility;
- the primitive is finite, bounded, deterministic, allocation-free, and does
  not require postings or position traversal beyond work already performed.

Unit tests prove that two candidates with identical `2 / 3` count coverage can
be separated when only one matches the rare group, low-quality synonyms cannot
inflate group weight, the result stays in `[0, 1]`, and ordinary V2 leaves the
experimental field at zero.

## Frozen-substrate proof

Query rarity weights are prepared only when V3 evidence is requested, after
candidate selection. Ordinary V2 does not compute them.

Across the frozen mixed and LongMemEval workloads, all checks passed:

- candidate identities and order are identical;
- V2 score bits are identical;
- canonical RankEvidenceV3 arrays are identical;
- constitutional tiers are identical;
- all experimental values are finite and bounded;
- candidate-pool selection and the `160` cap are unchanged.

Release sidecar:

`C:\benchmarks\phoenix-qps-v3-20260804\phase8_7-rarity-coverage-proof-v1\release-rarity-coverage-sidecar-v1.json`

SHA-256:

`c06ec04b84c245e047ee9a726fbf9a2dc386f9a6e1183c6314701696dea06f22`

## Immutable-input proof

The independent generator reproduced the canonical v9 inputs byte-for-byte:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Regenerated ledger | 275,421,386 | `a28f906d13446e4c5c0b627bc6400e5112a48d413105d229fe053fefc92b35d8` |
| Regenerated graded suite | 35,930,996 | `d9be32daca38e0b4cefd2680447ebeb5e8e6f5021c8f789917e468f9704af02b` |
| Independent rarity sidecar | 32,445,173 | `dd07693582e6da9a71bc7508a173c4bd600ad18ac30d47d8bd9095ba3da5b7f3` |
| Regenerated v9 receipt | 5,496 | `00ec54b9f9508a1f0629b810b7e2efa4593e6e8c5ee0f527c9b4810f0090499c` |

All `5,080` active reviewed labels projected by keyed query/document identity,
including `226` reversed preferences. Missing queries and candidates were zero.

## Leakage-safe pair-delta preflight

The authoritative preflight binds the Phase 6 grouped split and uses only
training and development judgments. Blind judgments remain evaluation-only.

A pair enters the pure diagnostic cohort when:

```text
abs(positive matched fraction - negative matched fraction) <= 1e-6
abs(positive weighted coverage - negative weighted coverage) <= 0.01
abs(positive rarity coverage - negative rarity coverage) > 1e-6
```

The gate required at least 30 directional target-class pairs and preferred-
higher agreement of at least `70%`.

| Failure class | Preferred higher | Preferred lower | Higher ratio |
|---|---:|---:|---:|
| Common-term dominance | 163 | 6 | `0.964497` |
| Wrong-concept proximity | 2 | 15 | `0.117647` |
| Partial-match saturation | 30 | 64 | `0.319149` |
| Document/conversation confusion | 35 | 8 | `0.813953` |
| Long-query failure | 10 | 4 | `0.714286` |
| **Combined target cohort** | **240** | **97** | **0.712166** |

The combined signal passes, but its sign is visibly class-dependent. Common-
term and document/conversation cases strongly favor it; partial-match and
wrong-concept cases mostly oppose it. That heterogeneity foreshadows the
learner result.

Authoritative preflight receipt:

`C:\benchmarks\phoenix-qps-v3-20260804\phase8_7-rarity-coverage-proof-v1\phase8_7-rarity-coverage-preflight-v2.json`

SHA-256:

`fda7906445a654b4a8b992d99cf51bebbfbe6cd286ca7fe0791b04ba4f6b83d7`

## Controlled learner result

The same deterministic monotonic linear learner and leakage-safe split were
used. Development selected 512 epochs, learning rate `0.005`, and L2 `0.001`
from 48 configurations. Training the selected configuration twice produced the
same model identity.

| Metric | Canonical linear V3 | Rarity diagnostic | Change |
|---|---:|---:|---:|
| LongMemEval hit@10 | `0.984` | `0.984` | `0.000` |
| LongMemEval MRR | `0.898899` | `0.902032` | `+0.003133` |
| LongMemEval top-1 | `0.844` | `0.848` | `+0.004` |
| Independent stretch MRR | `0.543202` | `0.554677` | `+0.011475` |
| Graded NDCG@10 change vs V2 | `-0.014278` | `+0.001312` | `+0.015590` |
| Blind pairwise accuracy | `0.785377` | `0.775943` | `-0.009434` |
| Held-out top-1 improvement | `+4.184` points | `+2.929` points | `-1.255` points |
| Worst-shape MRR regression | `0.016345` | `0.013126` | `-0.003219` |
| Mixed hit/MRR/top-1 | `1.000` | `1.000` | unchanged |

The graded metric crosses from negative to slightly positive, but remains below
the Phase 8 gate of `+0.020`. LongMemEval MRR and worst-shape regression also
remain below their gates. Aggregate improvement is therefore real but
insufficient even before targeted transfer is considered.

## Targeted blind result

| Failure class | Baseline | Rarity diagnostic | Change |
|---|---:|---:|---:|
| Common-term dominance | `0.742424` | `0.727273` | `-0.015152` |
| Wrong-concept proximity | `0.870370` | `0.870370` | `0.000000` |
| Partial-match saturation | `0.350000` | `0.350000` | `0.000000` |
| Document/conversation confusion | `0.791667` | `0.756944` | `-0.034722` |
| Long-query failure | `0.875000` | `0.875000` | `0.000000` |

Target classes improved: `0 / 5`.

Complete-coverage blind accuracy stayed `16 / 17`, and the mixed suite stayed
perfect. Those invariants prove safety in narrow regions; they do not overcome
the absence of targeted transfer.

## Interpretation

The learned diagnostic weight for coordinate 8 rose from `0.09420989` to
`0.71882915`, while adjacent ordinary coverage slopes contracted. The learner
used rarity coverage as a strong global replacement for count coverage.

That is the wrong abstraction for the observed data. Rarity coverage is useful
inside the deliberately tied coverage cohort, but its desired direction changes
by failure class. A single non-negative global coefficient cannot say:

```text
use rarity mass strongly for common-term dominance,
but do not use it the same way for partial-match or wrong-concept cases.
```

This is evidence about conditional use, not permission to add another permanent
feature or jump to a tree. The next cut should explain the class-dependent sign
or find a narrower invariant formulation before any schema work.

## Receipt supersession

The v1 preflight pooled blind labels and is retained only as a superseded
diagnostic. Diagnostic v1 and v2 are also superseded. The only authoritative
Phase 8.7 receipts are:

- `phase8_7-rarity-coverage-preflight-v2.json`;
- `phase8_7-rarity-coverage-diagnostic-v3.json`.

No superseded receipt authorizes migration or promotion.

## Verification

All compilation and tests used:

`D:\phoenix-target-qps-v3-phase87-20260811`

- `cargo test -p phoenix-lexical-qps --all-targets`: `36` passed.
- `cargo test -p phoenix-memory-lock --all-targets`: `80` passed.
- `cargo clippy -p phoenix-lexical-qps -p phoenix-memory-lock --all-targets -- -D warnings`: passed.
- `cargo fmt --all -- --check`: passed.
- `git diff --check`: passed; existing Windows line-ending warnings only.

## Decision

Phase 8.7 answered both intended questions:

1. **Does the primitive contain missing information?** Yes.
2. **Can the current global monotonic learner use it without damaging the
   claimed retrieval behavior?** No.

Stop Phase 8.7C. Preserve the receipts, keep V2 active, and analyze the
class-dependent sign before selecting the next primitive or architecture cut.
